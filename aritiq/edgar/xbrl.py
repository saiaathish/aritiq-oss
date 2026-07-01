"""
SEC XBRL fact grounding — standardized financial facts, no LLM, no label-matching.

WHY THIS EXISTS
---------------
Every extraction bug found across five rounds of live benchmarking (unit-scale
mismatches, wrong line items, zero/null liabilities, NCI/UPREIT mezzanine
confusion, and filers whose prose statements the LLM couldn't parse at all) has
one root cause: the LLM grounds numbers from free-form prose and table layout,
which varies filer to filer. SEC filers are ALSO legally required to submit their
statements as XBRL — every number tagged against the standardized US-GAAP taxonomy
(`Assets`, `Liabilities`, `NetIncomeLoss`, `EarningsPerShareBasic`, ...) regardless
of how they laid out their prose. The SEC's own tagging already resolved the
ambiguity, so grounding from XBRL sidesteps label-matching entirely.

FIREWALL: this module is plain HTTP against the SEC's free, no-auth JSON API — the
exact pattern aritiq/edgar/sec.py already uses for EDGAR. NO model SDK is imported
here, and nothing in aritiq/core/ imports this. XBRL facts become ordinary
operand values fed to the EXISTING, unmodified verifier rules.

HONESTY DISCIPLINE
------------------
We return the fact the SEC tagged, or None. We do NOT interpolate, derive, or guess
a missing fact — a missing tag becomes None and the downstream verifier gate
declines (INSUFFICIENT_EVIDENCE) rather than convict on a fabricated number. In
particular we deliberately do NOT compute `Liabilities = Assets - Equity` when the
`Liabilities` tag is absent (e.g. AMD does not tag total Liabilities): that
derivation would make the balance-sheet identity check tautological. A missing
`Liabilities` fact is reported as missing, honestly.

Endpoint: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json
  - free, no auth; requires a descriptive User-Agent (SEC blocks generic clients)
  - 10 req/sec per IP rate limit (we cache + space requests)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from .sec import lookup_cik, _default_fetch, FetchFn, EdgarError

XBRL_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

# Where to cache raw companyfacts JSON (mirrors benchmark filing cache location).
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)),
    "benchmark", "reliability", "cache", "xbrl",
)


# ---------------------------------------------------------------------------
# The concept tags we need for the three existing internal-consistency checks.
# Where a filer commonly uses one of several equivalent tags, we list fallbacks
# in priority order. The FIRST present tag wins; if none are present -> None.
# ---------------------------------------------------------------------------

# Balance sheet identity: Assets == Liabilities + Equity
_ASSETS_TAGS = ["Assets"]
_LIABILITIES_TAGS = ["Liabilities"]  # NOTE: intentionally no derived fallback (see module docstring)
# Prefer TOTAL equity incl. noncontrolling interest — the exact tag that resolves
# the TSLA/GOOGL/SPG "parent-only equity" mechanism-2 bug. Fall back to plain
# StockholdersEquity only when the incl-NCI tag is absent (filers with no NCI).
_EQUITY_TAGS = [
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "StockholdersEquity",
]

# EPS reconciliation: stated_eps == numerator / shares
# Prefer net income AVAILABLE TO COMMON (the exact tag that resolves the JPM/BAC/DUK
# preferred-dividend mechanism-1 bug). Fall back to NetIncomeLoss (total) when the
# available-to-common tag is absent (filers with no preferred stock).
_NI_COMMON_TAGS = ["NetIncomeLossAvailableToCommonStockholdersBasic"]
_NI_TOTAL_TAGS = ["NetIncomeLoss", "ProfitLoss"]
_EPS_BASIC_TAGS = ["EarningsPerShareBasic"]
_EPS_DILUTED_TAGS = ["EarningsPerShareDiluted"]
_SHARES_BASIC_TAGS = [
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
]
_SHARES_DILUTED_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding"]

# Cash tie-out: statement ending cash (may incl. restricted) vs balance-sheet cash
_BS_CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsAndShortTermInvestments",
]
_CF_CASH_TAGS = [
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
    "CashAndCashEquivalentsAtCarryingValue",
]


@dataclass
class XbrlFacts:
    """The standardized facts needed for the three internal-consistency checks.

    Every field is the value the SEC tagged for the matched 10-K period, or None
    if that concept was not tagged. `*_tag` fields record WHICH concept supplied
    the value (provenance), and `period_end` / `fy` pin the fiscal period.
    """
    ticker: str
    cik: Optional[int] = None
    company: str = ""
    form: str = "10-K"                      # "10-K" (annual) or "10-Q" (quarterly)
    period_end: Optional[str] = None
    fy: Optional[int] = None
    fp: Optional[str] = None                # fiscal period label (FY, Q1, Q2, ...)

    # balance sheet
    assets: Optional[float] = None
    liabilities: Optional[float] = None
    equity: Optional[float] = None
    equity_includes_nci: bool = False       # True when the incl-NCI tag supplied equity

    # income / EPS
    net_income_total: Optional[float] = None
    net_income_to_common: Optional[float] = None
    eps_basic: Optional[float] = None
    eps_diluted: Optional[float] = None
    shares_basic: Optional[float] = None
    shares_diluted: Optional[float] = None

    # cash tie-out
    bs_cash: Optional[float] = None
    cf_cash: Optional[float] = None
    cf_cash_includes_restricted: bool = False   # True when the incl-restricted tag supplied cf_cash

    # provenance: concept tag actually used per field
    tags_used: Dict[str, str] = field(default_factory=dict)
    fetch_error: Optional[str] = None


def _cache_path(ticker: str, cache_dir: str) -> str:
    return os.path.join(cache_dir, f"{ticker.upper()}.json")


def _load_companyfacts(ticker: str, *, fetch: FetchFn, cache_dir: str,
                       use_cache: bool) -> dict:
    """Fetch (or load cached) the raw companyfacts JSON for a ticker."""
    os.makedirs(cache_dir, exist_ok=True)
    raw_path = os.path.join(cache_dir, f"_raw_{ticker.upper()}.json")
    if use_cache and os.path.exists(raw_path):
        return json.load(open(raw_path))
    cik, company = lookup_cik(ticker, fetch=fetch)
    url = XBRL_FACTS_URL.format(cik10=f"{cik:010d}")
    data = json.loads(fetch(url))
    data["_resolved_cik"] = cik
    data["_resolved_company"] = company
    json.dump(data, open(raw_path, "w"))
    time.sleep(0.12)   # be well under the SEC 10 req/sec limit
    return data


def _span_days(fact: dict) -> int:
    """Days between a duration fact's start and end (0 for instant facts)."""
    s, e = fact.get("start"), fact.get("end")
    if not s or not e:
        return 0
    try:
        import datetime as _dt
        return (_dt.date.fromisoformat(e) - _dt.date.fromisoformat(s)).days
    except Exception:
        return 0


def _select_fact(
    gaap: dict, tags: List[str], unit_keys: List[str],
    *, period_end: Optional[str] = None, want_duration: bool = False,
    form: str = "10-K",
) -> tuple[Optional[float], Optional[str]]:
    """Return (value, tag_used) for the first present tag with a matching fact.

    `form` selects the filing type ("10-K" annual, "10-Q" quarterly). If period_end
    is given, prefer the fact whose `end` matches it; otherwise take the most recent
    fact of that form. `want_duration` selects income-statement facts (which carry a
    `start`). Returns (None, None) if nothing matches — never guesses.

    Duration handling differs by form:
      * 10-K income facts report the FULL FISCAL YEAR (~365 days). The same tag also
        carries quarterly facts, so we keep only ~annual spans (>= 300 days) and pick
        the longest — never a quarter (the AMD 491M-vs-4,335M bug this guards).
      * 10-Q income facts report the STANDALONE QUARTER (~90 days) AND a
        year-to-date cumulative (~180/270 days). The reported quarterly EPS pairs
        with the standalone-quarter numerator/shares, so we keep only ~quarter spans
        (<= 100 days) and pick the SHORTEST — so numerator, shares, and stated EPS
        all describe the same single quarter.
    """
    is_q = (form == "10-Q")
    is_8k = (form == "8-K")
    for tag in tags:
        concept = gaap.get(tag)
        if not concept:
            continue
        for uk in unit_keys:
            facts = concept.get("units", {}).get(uk)
            if not facts:
                continue
            cand = [f for f in facts if f.get("form") == form and "val" in f]
            if want_duration:
                if is_q:
                    # standalone quarter only (~90 days), never the YTD cumulative
                    cand = [f for f in cand if f.get("start") and 60 <= _span_days(f) <= 100]
                elif is_8k:
                    # 8-K earnings exhibits report either a quarter OR a full year
                    # depending on which release it is. Accept a standalone quarter
                    # OR an annual span, but exclude YTD-cumulative interim spans
                    # (~120-300 days) so a numerator can't be mixed with a different
                    # period's shares. Prefer the fact matching the pinned period.
                    cand = [f for f in cand if f.get("start")
                            and (60 <= _span_days(f) <= 100 or _span_days(f) >= 300)]
                else:
                    cand = [f for f in cand if f.get("start") and _span_days(f) >= 300]
            if not cand:
                continue
            if period_end:
                # A specified period pins the filing. If this tag has NO fact whose
                # end matches that period, the concept is NOT applicable to this
                # filing (e.g. AMD last tagged NetIncomeLossAvailableToCommon in
                # 2011). Return None for THIS tag and try the next fallback — never
                # fall back to a stale fact from a different period.
                exact = [f for f in cand if f.get("end") == period_end]
                if not exact:
                    continue
                # 10-K: longest span (full year); 10-Q: shortest span (single quarter)
                dur_key = (lambda f: (-_span_days(f), f.get("filed", ""))) if is_q else \
                          (lambda f: (_span_days(f), f.get("filed", "")))
                chosen = max(exact, key=dur_key)
                return float(chosen["val"]), tag
            # No period pin: most recent fact; span tie-break by form convention.
            span_pref = (lambda f: -_span_days(f)) if is_q else (lambda f: _span_days(f))
            chosen = max(cand, key=lambda f: (f.get("end", ""), span_pref(f),
                                              f.get("filed", "")))
            return float(chosen["val"]), tag
    return None, None


def extract_xbrl_facts(
    ticker: str,
    *,
    period_end: Optional[str] = None,
    form: str = "10-K",
    fetch: Optional[FetchFn] = None,
    cache_dir: str = _DEFAULT_CACHE,
    use_cache: bool = True,
) -> XbrlFacts:
    """Fetch and structure the XBRL facts for a ticker's latest filing of `form`.

    `form` selects the filing type: "10-K" (annual, the default — unchanged
    behaviour) or "10-Q" (quarterly). Income/EPS/shares are then read as annual or
    standalone-quarter facts respectively, so the numerator, shares, and stated EPS
    all describe the same reporting period. `period_end` (YYYY-MM-DD) pins the
    period; if omitted, the most recent fact of that form is used.

    Never raises on missing data: a concept the filer didn't tag becomes None, and
    a fetch/parse failure is recorded in `.fetch_error` (the result is still a valid
    XbrlFacts with all-None facts) so a benchmark loop never crashes.
    """
    fetch = fetch or _default_fetch
    out = XbrlFacts(ticker=ticker.upper())
    out.form = form
    try:
        data = _load_companyfacts(ticker, fetch=fetch, cache_dir=cache_dir, use_cache=use_cache)
    except EdgarError as e:
        out.fetch_error = f"{type(e).__name__}: {e}"
        return out
    except Exception as e:  # network / parse / missing facts key
        out.fetch_error = f"{type(e).__name__}: {str(e)[:180]}"
        return out

    out.cik = data.get("_resolved_cik")
    out.company = data.get("_resolved_company", "")
    gaap = (data.get("facts") or {}).get("us-gaap")
    if not gaap:
        out.fetch_error = "no us-gaap facts in companyfacts response"
        return out

    tags: Dict[str, str] = {}

    # ---- pin the reporting period FIRST (from the most recent Assets fact of form)
    # Every other fact is then selected for THIS period, so a tag whose latest fact
    # is from an old year (e.g. JPM's incl-NCI equity tag stops in 2015, AMD's
    # net-income-to-common stops in 2011) is correctly treated as absent for the
    # current filing rather than returning a stale value.
    out.assets, t = _select_fact(gaap, _ASSETS_TAGS, ["USD"], period_end=period_end, form=form)
    if t: tags["assets"] = t
    if period_end is None and gaap.get("Assets"):
        au = gaap["Assets"]["units"].get("USD", [])
        ff = [f for f in au if f.get("form") == form and "val" in f]
        if ff:
            latest = max(ff, key=lambda f: (f.get("end", ""), f.get("filed", "")))
            period_end = latest.get("end")
            out.fy = latest.get("fy")
            out.fp = latest.get("fp")
    out.period_end = period_end

    # ---- rest of balance sheet (instant facts, USD), pinned to the period -------
    out.liabilities, t = _select_fact(gaap, _LIABILITIES_TAGS, ["USD"], period_end=period_end, form=form)
    if t: tags["liabilities"] = t
    out.equity, t = _select_fact(gaap, _EQUITY_TAGS, ["USD"], period_end=period_end, form=form)
    if t:
        tags["equity"] = t
        out.equity_includes_nci = (t == _EQUITY_TAGS[0])

    # ---- income / EPS (income = duration facts; EPS/shares per-share units) -----
    out.net_income_total, t = _select_fact(gaap, _NI_TOTAL_TAGS, ["USD"],
                                           period_end=period_end, want_duration=True, form=form)
    if t: tags["net_income_total"] = t
    out.net_income_to_common, t = _select_fact(gaap, _NI_COMMON_TAGS, ["USD"],
                                               period_end=period_end, want_duration=True, form=form)
    if t: tags["net_income_to_common"] = t
    out.eps_basic, t = _select_fact(gaap, _EPS_BASIC_TAGS, ["USD/shares"],
                                    period_end=period_end, want_duration=True, form=form)
    if t: tags["eps_basic"] = t
    out.eps_diluted, t = _select_fact(gaap, _EPS_DILUTED_TAGS, ["USD/shares"],
                                      period_end=period_end, want_duration=True, form=form)
    if t: tags["eps_diluted"] = t
    out.shares_basic, t = _select_fact(gaap, _SHARES_BASIC_TAGS, ["shares"],
                                       period_end=period_end, want_duration=True, form=form)
    if t: tags["shares_basic"] = t
    out.shares_diluted, t = _select_fact(gaap, _SHARES_DILUTED_TAGS, ["shares"],
                                         period_end=period_end, want_duration=True, form=form)
    if t: tags["shares_diluted"] = t

    # ---- cash tie-out (instant facts, USD) -------------------------------------
    out.bs_cash, t = _select_fact(gaap, _BS_CASH_TAGS, ["USD"], period_end=period_end, form=form)
    if t: tags["bs_cash"] = t
    out.cf_cash, t = _select_fact(gaap, _CF_CASH_TAGS, ["USD"], period_end=period_end, form=form)
    if t:
        tags["cf_cash"] = t
        out.cf_cash_includes_restricted = (t == _CF_CASH_TAGS[0] or "Restricted" in t)

    out.tags_used = tags
    return out


def facts_to_dict(f: XbrlFacts) -> dict:
    return asdict(f)
