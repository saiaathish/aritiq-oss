"""
SEC XBRL multi-period history — the time-series operand source for temporal checks.

WHY THIS EXISTS
---------------
`aritiq/edgar/xbrl.py` pins ONE reporting period (the latest, or a specified
`period_end`) and returns a single `XbrlFacts` for the internal-consistency checks.
But the SEC `companyfacts` endpoint already returns a company's FULL reporting
history for every tagged concept in that same response — multiple years of
`Assets`, `NetIncomeLoss`, `Revenues`, etc. Multi-period claims ("revenue grew 12%
YoY", "net income rose for three consecutive years", "this is the highest margin in
five years") can therefore be verified with ZERO new data fetching: the series is
already in the cached JSON, just not yet read across periods.

This module reads that time series and hands it to the EXISTING, unmodified
temporal check functions in `aritiq/core/rules.py`
(`check_trend_direction`, `check_superlative`, `check_consecutive_count`) and the
EXISTING `percent_change` arithmetic. No new verifier logic, no new arithmetic.

FIREWALL: plain HTTP / cached JSON against the SEC's free no-auth API, exactly like
xbrl.py. NO model SDK is imported here, and nothing in aritiq/core/ imports this.

HONESTY DISCIPLINE — the hard part of multi-period comparison
-------------------------------------------------------------
Comparing a concept across periods is only valid when the periods are COMPARABLE.
Two real, well-known ways this breaks, and how each is gated (never silently
mis-compared):

  1. FISCAL-YEAR-END CHANGE / STUB PERIODS. If a filer changes its fiscal year end,
     one "annual" span is not ~365 days (it's a short stub or a long transition
     year). Comparing a stub year's revenue against a full year's as if they were
     both "FY" is a silent apples-to-oranges error. We therefore keep only spans in
     a tight annual window (see `_ANNUAL_MIN_DAYS`/`_ANNUAL_MAX_DAYS`) and record
     each retained point's span; a series that had to drop points for this reason is
     marked so the caller can gate to INSUFFICIENT_EVIDENCE rather than compare a
     non-comparable pair.

  2. SHARE-COUNT COMPARABILITY ACROSS SPLITS. Per-share concepts (EPS, shares
     outstanding) are NOT comparable across a stock split unless the filer
     retroactively restated them. XBRL facts are as-filed; a split between two
     filings makes a raw EPS/shares series non-comparable. We flag per-share
     concepts as split-sensitive so the caller can decline rather than emit a
     confident (and wrong) "shares fell 75%" when the company merely did a 4-for-1
     split. We do NOT attempt to detect or adjust for the split — that would be
     guessing; we surface the risk and let the gate decline.

A concept the filer never tagged, or a series with fewer than 2 comparable points,
becomes an empty/short series — never an interpolated value.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .sec import lookup_cik, _default_fetch, FetchFn, EdgarError
from .xbrl import _load_companyfacts, _span_days, _DEFAULT_CACHE

# Comparable-annual window. A full fiscal year is ~365 days; 52/53-week filers land
# at 358-371. We accept 340-380 so ordinary calendars pass but a fiscal-year-change
# stub (short) or transition year (long) is excluded and recorded as dropped.
_ANNUAL_MIN_DAYS = 340
_ANNUAL_MAX_DAYS = 380

# Comparable-quarter window (standalone quarter, never the YTD cumulative).
_QUARTER_MIN_DAYS = 80
_QUARTER_MAX_DAYS = 100

# Per-share / share-count concepts whose raw XBRL series is NOT comparable across a
# stock split unless restated. Presence of any of these tags => split_sensitive.
_PER_SHARE_TAGS = {
    "EarningsPerShareBasic", "EarningsPerShareDiluted",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    "CommonStockSharesOutstanding", "CommonStockSharesIssued",
}

# Convenience concept groups the benchmark and API use. Each entry is a priority
# list of equivalent tags; the FIRST tag that yields a usable series wins.
CONCEPT_TAGS: Dict[str, List[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_basic": [
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    ],
}


@dataclass
class SeriesPoint:
    """One comparable data point in a concept's time series."""
    period_end: str          # ISO date the period ends on
    value: float             # the value the SEC tagged
    fy: Optional[int] = None
    fp: Optional[str] = None
    span_days: int = 0       # duration span (0 for instant facts like Assets)
    form: str = "10-K"


@dataclass
class ConceptSeries:
    """The full comparable time series for one concept, with comparability flags.

    Everything downstream (the temporal checks, percent_change) consumes
    `points` — an ordered, chronological list of comparable (period_end, value).
    The flags exist so a caller can decline (INSUFFICIENT_EVIDENCE) instead of
    comparing across a fiscal-year change or an unadjusted split.
    """
    ticker: str
    concept: str                       # the logical name ("revenue")
    tag_used: Optional[str] = None     # the actual XBRL tag that supplied the series
    form: str = "10-K"
    points: List[SeriesPoint] = field(default_factory=list)

    # comparability gates (see module docstring)
    dropped_noncomparable_spans: int = 0   # points excluded for being non-annual/-quarter
    split_sensitive: bool = False          # per-share concept: raw series unsafe across splits
    fetch_error: Optional[str] = None

    @property
    def series(self) -> List[Tuple[str, float]]:
        """(period_end, value) pairs in chronological order — the operand form the
        temporal checks and percent_change consume directly."""
        return [(p.period_end, p.value) for p in self.points]

    @property
    def n_points(self) -> int:
        return len(self.points)


def _comparable_window(form: str) -> Tuple[int, int]:
    if form == "10-Q":
        return _QUARTER_MIN_DAYS, _QUARTER_MAX_DAYS
    return _ANNUAL_MIN_DAYS, _ANNUAL_MAX_DAYS


def _extract_series_for_tag(
    concept_facts: dict, unit_keys: List[str], *, form: str,
) -> Tuple[List[SeriesPoint], int]:
    """Pull the comparable time series for a single XBRL concept.

    Returns (points, n_dropped_for_noncomparable_span). A concept can be a duration
    fact (income, EPS — carries start/end) or an instant fact (balance-sheet totals
    — end only). For duration facts we keep only spans inside the comparable window
    for the form (annual or quarter) and count anything outside it as dropped. For
    instant facts every period-end is comparable (there is no span to police), and
    we dedupe to one value per period_end (the latest-filed, i.e. as-most-recently
    reported).
    """
    dropped = 0
    # one value per period_end; prefer the most recently filed fact for that end
    by_end: Dict[str, dict] = {}
    lo, hi = _comparable_window(form)
    for uk in unit_keys:
        for fact in concept_facts.get("units", {}).get(uk, []):
            if fact.get("form") != form or "val" not in fact:
                continue
            end = fact.get("end")
            if not end:
                continue
            is_duration = bool(fact.get("start"))
            if is_duration:
                span = _span_days(fact)
                if not (lo <= span <= hi):
                    dropped += 1
                    continue
            prev = by_end.get(end)
            if prev is None or fact.get("filed", "") >= prev.get("filed", ""):
                by_end[end] = fact
    points: List[SeriesPoint] = []
    for end, fact in by_end.items():
        points.append(SeriesPoint(
            period_end=end, value=float(fact["val"]),
            fy=fact.get("fy"), fp=fact.get("fp"),
            span_days=_span_days(fact), form=form,
        ))
    points.sort(key=lambda p: p.period_end)
    return points, dropped


def get_concept_series(
    ticker: str,
    concept: str,
    *,
    form: str = "10-K",
    unit_keys: Optional[List[str]] = None,
    fetch: Optional[FetchFn] = None,
    cache_dir: str = _DEFAULT_CACHE,
    use_cache: bool = True,
) -> ConceptSeries:
    """Return the comparable time series for `concept` for `ticker`.

    `concept` may be a logical name from CONCEPT_TAGS ("revenue", "net_income", ...)
    or a raw US-GAAP tag. Tags in a logical group are tried in priority order; the
    first that yields >= 1 comparable point wins. Never raises: a missing concept or
    a fetch failure returns a ConceptSeries with an empty series and (for fetch
    failures) `fetch_error` set, so a benchmark loop never crashes.
    """
    fetch = fetch or _default_fetch
    out = ConceptSeries(ticker=ticker.upper(), concept=concept, form=form)
    try:
        data = _load_companyfacts(ticker, fetch=fetch, cache_dir=cache_dir, use_cache=use_cache)
    except EdgarError as e:
        out.fetch_error = f"{type(e).__name__}: {e}"
        return out
    except Exception as e:
        out.fetch_error = f"{type(e).__name__}: {str(e)[:180]}"
        return out

    gaap = (data.get("facts") or {}).get("us-gaap")
    if not gaap:
        out.fetch_error = "no us-gaap facts in companyfacts response"
        return out

    tag_candidates = CONCEPT_TAGS.get(concept, [concept])
    # Default unit selection: per-share concepts use USD/shares, share counts use
    # shares, everything else USD. Caller may override via unit_keys.
    if unit_keys is None:
        if concept in ("eps_basic", "eps_diluted") or "EarningsPerShare" in concept:
            unit_keys = ["USD/shares"]
        elif concept in ("shares_basic", "shares_diluted") or "SharesOutstanding" in concept:
            unit_keys = ["shares"]
        else:
            unit_keys = ["USD"]

    for tag in tag_candidates:
        concept_facts = gaap.get(tag)
        if not concept_facts:
            continue
        points, dropped = _extract_series_for_tag(concept_facts, unit_keys, form=form)
        if not points:
            continue
        out.tag_used = tag
        out.points = points
        out.dropped_noncomparable_spans = dropped
        out.split_sensitive = tag in _PER_SHARE_TAGS
        return out

    # No tag in the group produced a usable series — honest empty result.
    return out


def facts_to_dict(s: ConceptSeries) -> dict:
    d = asdict(s)
    d["n_points"] = s.n_points
    return d
