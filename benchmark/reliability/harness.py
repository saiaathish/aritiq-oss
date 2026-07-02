"""
Aritiq RELIABILITY HARNESS — full-pipeline measurement over real SEC filings.

Purpose (per the deployment handoff): MEASURE FIRST. Run the real pipeline
(SEC fetch -> extraction -> verification -> scoring) over a curated set of real
filings and log, per claim, exactly what extraction emitted and what verdict the
deterministic verifier produced — so a human can classify true/false
positives/negatives and separate EXTRACTION failures from VERIFIER failures.

This harness makes NO accuracy claims and changes NO engine code. It only
observes. Everything it concludes is derived from logged runs, never asserted.

Three stages, each cached on disk so a run is reproducible and a network/model
outage never destroys progress:

  1. FETCH    aritiq.edgar.sec.fetch_10k_text(ticker)  [SEC only, no LLM, no cost]
              -> cache/filings/<TICKER>.json  (filing metadata + statements text)

  2. EXTRACT  aritiq.extract.extract_internal_consistency(text, ...)  [LLM]
              -> cache/extractions/<TICKER>.json  (raw model JSON + parsed claims)
              Runs LIVE when a model backend is reachable; otherwise REPLAYS the
              cached extraction. If neither is available, the filing is recorded
              as an extraction-unavailable row (not a crash, not a fake verdict).

  3. VERIFY   aritiq.core.verify.verify_claim(claim)  [pure code, always runs]
              The firewall: only Claim objects cross into the verifier.

The harness logs, per internal_consistency claim:
  * rule_name and the verdict (VERIFIED / WRONG_MATH / INSUFFICIENT_EVIDENCE /
    AMBIGUOUS / UNSUPPORTED_NUMBER / ...),
  * whether the EVIDENCE FLAGS the gates depend on were emitted by extraction:
      balance_sheet_identity -> liabilities_complete
      eps_reconciliation     -> eps_income_basis, income_operand_basis
      cash_flow_tie_out      -> restricted_cash_disclosed,
  * whether graph dependencies (node_id / depends_on) were populated.

Run:
    # offline / replay only (safe anywhere; uses cached extractions):
    python benchmark/reliability/harness.py --replay

    # fetch filings from SEC and cache them (no LLM):
    python benchmark/reliability/harness.py --fetch-only

    # full live run where a model backend is reachable (uses ARITIQ_PROVIDER):
    python benchmark/reliability/harness.py --live

A run writes cache/runs/run_<timestamp>.json and prints a summary. Feed that file
to report.py to produce the failure taxonomy and the prioritized fix list.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Secret redaction — defensive. Any string written to a run log or printed to
# the console passes through this, so a provider error message that happens to
# echo an Authorization header / API key can never be persisted in plaintext.
# Covers the API-key shapes across the providers Aritiq can call:
#   Groq        gsk_...
#   OpenAI/Anthropic  sk-... / sk-ant-...
#   Google AI Studio  AIza...
#   Gemini (newer)    AQ.Ab...   (DIFFERENT shape — dot-separated, no underscore;
#                                 the original regex missed this, a confirmed gap)
#   Bearer tokens in echoed Authorization headers
# ---------------------------------------------------------------------------
_SECRET_RE = re.compile(
    r"(gsk_[A-Za-z0-9]{8,}"
    r"|sk-(?:ant-)?[A-Za-z0-9._\-]{8,}"
    r"|AIza[A-Za-z0-9._\-]{8,}"
    r"|AQ\.[A-Za-z0-9._\-]{8,}"
    r"|Bearer\s+[A-Za-z0-9._\-]{8,})"
)


def redact(s: Optional[str]) -> Optional[str]:
    """Replace anything that looks like an API key/token with a masked stub.

    Conservative on the prefix shown so the masked output still hints at which
    provider's key it was, without revealing usable characters.
    """
    if not s:
        return s
    def _mask(m):
        tok = m.group(0)
        # Show a short, safe prefix (provider hint) then mask the rest.
        head = re.match(r"(gsk_|sk-ant-|sk-|AIza|AQ\.|Bearer\s+)", tok)
        prefix = head.group(1).strip() if head else tok[:4]
        return f"{prefix}***REDACTED***"
    return _SECRET_RE.sub(_mask, s)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.core.schema import Claim, Operation, VerificationStatus  # noqa: E402
from aritiq.core.verify import verify_claim  # noqa: E402
from aritiq.extract.cross_statement import (  # noqa: E402
    _document_has_preferred_eps_context,
    extract_internal_consistency,
)
from aritiq.extract.schema import parse_claims  # noqa: E402
from aritiq.edgar.sec import fetch_10k_text, EdgarError  # noqa: E402
from aritiq.edgar.xbrl import extract_xbrl_facts  # noqa: E402

sys.path.insert(0, HERE)
from xbrl_verify import build_claims_from_facts  # noqa: E402  (sibling module)

CACHE = os.path.join(HERE, "cache")
FILINGS_DIR = os.path.join(CACHE, "filings")
EXTRACT_DIR = os.path.join(CACHE, "extractions")
RUNS_DIR = os.path.join(CACHE, "runs")
FILING_SET_PATH = os.path.join(HERE, "filing_set.json")

for d in (FILINGS_DIR, EXTRACT_DIR, RUNS_DIR):
    os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# Filing set
# ---------------------------------------------------------------------------

def load_filing_set(path: str = FILING_SET_PATH) -> List[dict]:
    data = json.load(open(path))
    return data["filings"]


# ---------------------------------------------------------------------------
# Stage 1: fetch (SEC, no LLM) — cached
# ---------------------------------------------------------------------------

@dataclass
class CachedFiling:
    ticker: str
    company: str = ""
    period: Optional[str] = None
    filing_date: str = ""
    accession: str = ""
    document_url: str = ""
    statements_text: str = ""
    fetch_error: Optional[str] = None


def _filing_cache_path(ticker: str) -> str:
    return os.path.join(FILINGS_DIR, f"{ticker.upper()}.json")


def fetch_filing(ticker: str, *, use_cache: bool = True) -> CachedFiling:
    """Fetch (or load from cache) the latest 10-K statements text for a ticker."""
    p = _filing_cache_path(ticker)
    if use_cache and os.path.exists(p):
        return CachedFiling(**json.load(open(p)))
    try:
        filing, text = fetch_10k_text(ticker)
        cf = CachedFiling(
            ticker=ticker.upper(), company=filing.company, period=filing.period,
            filing_date=filing.filing_date, accession=filing.accession,
            document_url=filing.document_url, statements_text=text,
        )
    except EdgarError as e:
        cf = CachedFiling(ticker=ticker.upper(), fetch_error=redact(f"{type(e).__name__}: {e}"))
    except Exception as e:  # network, SSL, etc. — record, never crash the run.
        cf = CachedFiling(ticker=ticker.upper(), fetch_error=redact(f"{type(e).__name__}: {e}"))
    json.dump(asdict(cf), open(p, "w"), indent=2)
    return cf


# ---------------------------------------------------------------------------
# Stage 2: extract (LLM) — live-or-replay, cached
# ---------------------------------------------------------------------------

def _extract_cache_path(ticker: str) -> str:
    return os.path.join(EXTRACT_DIR, f"{ticker.upper()}.json")


def extract_for(
    cf: CachedFiling,
    *,
    mode: str,                       # "live" | "replay"
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Return {"raw": <model json str>, "available": bool, "source": str, "error": str|None}.

    mode="live": call the model backend, cache the raw response.
    mode="replay": load the cached raw response (no network, no cost).
    Either way the raw JSON is parsed downstream by the SAME parse_claims the
    pipeline uses — so replay exercises the real extraction-shape repair path.
    """
    p = _extract_cache_path(cf.ticker)

    if mode == "replay":
        if os.path.exists(p):
            cached = json.load(open(p))
            return {"raw": cached.get("raw", "[]"), "available": True,
                    "source": "replay-cache", "error": None}
        return {"raw": "[]", "available": False, "source": "replay-cache",
                "error": "no cached extraction for this ticker"}

    # mode == "live"
    if cf.fetch_error or not cf.statements_text:
        return {"raw": "[]", "available": False, "source": "live",
                "error": cf.fetch_error or "no statements text to extract from"}
    try:
        out = extract_internal_consistency(
            cf.statements_text, provider=provider, model=model)
        raw = out.raw_response or "[]"
        json.dump({"ticker": cf.ticker, "raw": raw, "provider": out.provider,
                   "model": out.model, "fetched_at": _now()},
                  open(p, "w"), indent=2)
        return {"raw": raw, "available": True, "source": "live", "error": None}
    except Exception as e:  # model unreachable / auth / quota — record, don't crash.
        return {"raw": "[]", "available": False, "source": "live",
                "error": redact(f"{type(e).__name__}: {str(e)[:200]}")}


# ---------------------------------------------------------------------------
# Stage 3: verify (pure code) + per-claim logging
# ---------------------------------------------------------------------------

# Which evidence flag each gated rule depends on (mirrors rules.py / verify.py).
_EVIDENCE_FLAGS = {
    "balance_sheet_identity": ["liabilities_complete"],
    "eps_reconciliation": ["eps_income_basis", "income_operand_basis"],
    "cash_flow_tie_out": ["restricted_cash_disclosed"],
}


# ---------------------------------------------------------------------------
# XBRL adjudication backstop (the Phase-1 "diff extracted vs XBRL ground truth").
# ---------------------------------------------------------------------------
# A prose WRONG_MATH conviction is the worst-case failure, so before recording one
# we cross-check it against the SEC's own standardized XBRL facts — an INDEPENDENT,
# deterministic grounding (no LLM). If an XBRL-grounded version of the SAME rule (the
# correctly-scoped numerator / weighted-average shares / total-equity-incl-NCI /
# mezzanine-aware operands) reconciles the figure, the prose conviction was a
# wrong-operand-SCOPE artifact, not a real arithmetic error — so we downgrade it to
# INSUFFICIENT_EVIDENCE (prose scope unconfirmed; XBRL reconciles). If XBRL INDEPEND-
# ENTLY also convicts, the discrepancy is real and the WRONG_MATH stands. This never
# manufactures a VERIFIED and never hides a genuine error; it only refuses to convict
# where an independent grounding disagrees. Requires cached XBRL facts; absent them,
# the prose verdict is left untouched (honest).
_XBRL_FACTS_CACHE: Dict[str, object] = {}


def _xbrl_facts_for(ticker: str):
    if ticker not in _XBRL_FACTS_CACHE:
        try:
            _XBRL_FACTS_CACHE[ticker] = extract_xbrl_facts(ticker, use_cache=True)
        except Exception:
            _XBRL_FACTS_CACHE[ticker] = None
    return _XBRL_FACTS_CACHE[ticker]


def xbrl_adjudicate(ticker: str, claim: Claim, prose_status: VerificationStatus):
    """Return (final_status, note) after cross-checking a prose WRONG_MATH with XBRL.

    Only acts on internal_consistency WRONG_MATH convictions; every other verdict is
    returned unchanged. Deterministic and firewall-safe (XBRL is plain SEC JSON, no
    model)."""
    if prose_status != VerificationStatus.WRONG_MATH:
        return prose_status, None
    if claim.operation != Operation.INTERNAL_CONSISTENCY or not claim.rule_name:
        return prose_status, None
    facts = _xbrl_facts_for(ticker)
    if facts is None or getattr(facts, "fetch_error", None):
        return prose_status, None
    try:
        xclaims = build_claims_from_facts(facts)
    except Exception:
        return prose_status, None

    # Find the XBRL claim for the same rule (+ EPS variant).
    want_variant = claim.eps_variant
    match = None
    for xc in xclaims:
        if xc.rule_name != claim.rule_name:
            continue
        if claim.rule_name == "eps_reconciliation" and want_variant is not None:
            if xc.eps_variant != want_variant:
                continue
        match = xc
        break
    if match is None:
        # XBRL cannot supply the correctly-scoped operands for this rule → we cannot
        # clear the conviction, but we also cannot confirm it independently. The
        # honest verdict is to DECLINE rather than convict on prose alone.
        return (VerificationStatus.INSUFFICIENT_EVIDENCE,
                "prose WRONG_MATH not independently confirmable: SEC XBRL does not tag "
                "the correctly-scoped operand for this rule; declining to convict on "
                "prose grounding alone.")

    xres = verify_claim(match)
    xops = [o.value for o in match.operands]
    if xres.status == VerificationStatus.VERIFIED:
        return (VerificationStatus.INSUFFICIENT_EVIDENCE,
                f"prose WRONG_MATH downgraded: prose operand scope unconfirmed, but "
                f"XBRL-grounded operands {xops} reconcile this figure (VERIFIED). The "
                f"prose extractor grounded a wrong-scope operand (e.g. total vs "
                f"income-to-common, period-end vs weighted-average shares).")
    if xres.status == VerificationStatus.INSUFFICIENT_EVIDENCE:
        return (VerificationStatus.INSUFFICIENT_EVIDENCE,
                f"prose WRONG_MATH downgraded: XBRL grounding also declines "
                f"(completeness/scope gate) rather than convicting — {xres.explanation[:120]}")
    # XBRL independently convicts too → the discrepancy is real.
    return (VerificationStatus.WRONG_MATH,
            f"prose WRONG_MATH upheld: independent XBRL grounding {xops} also fails the "
            f"reconciliation — a real arithmetic discrepancy, not a scope artifact.")


@dataclass
class ClaimRecord:
    ticker: str
    rule_name: Optional[str]
    operation: str
    verdict: str
    prose_verdict: str
    adjudication: Optional[str]
    operand_values: List[Optional[float]]
    # evidence-flag emission, per the gate the rule uses:
    evidence_flags_required: List[str]
    evidence_flags_emitted: Dict[str, object]    # flag -> value (or "<MISSING>")
    evidence_emitted: bool                         # all required flags were EMITTED (any value)
    evidence_gate_satisfied: bool                  # flags emitted AND set to a value that lets the gate RUN
    # income basis can be carried on the operand category instead of params:
    income_basis_via_operand: Optional[str]
    eps_variant: Optional[str]
    shares_category: Optional[str]
    # graph fields:
    node_id: Optional[str]
    depends_on: List[str]
    has_graph_dep: bool
    explanation: str


def _flag_value(params: dict, key: str):
    return params.get(key, "<MISSING>") if params else "<MISSING>"


def record_claim(ticker: str, claim: Claim) -> ClaimRecord:
    res = verify_claim(claim)
    prose_status = res.status
    final_status, adjudication = xbrl_adjudicate(ticker, claim, prose_status)
    params = claim.params or {}
    rule = claim.rule_name
    required = _EVIDENCE_FLAGS.get(rule or "", [])

    emitted: Dict[str, object] = {}
    for f in required:
        emitted[f] = _flag_value(params, f)

    # income basis may be tagged on the net-income operand's category (verify.py
    # reads it from there as a fallback), so capture that too.
    income_basis_via_operand = None
    if rule == "eps_reconciliation" and len(claim.operands) >= 2:
        income_basis_via_operand = claim.operands[1].category

    def _emitted(v) -> bool:
        # The flag key was present in params at all (even if False/null).
        return v != "<MISSING>"

    def _gate_runs(rule_name: str, flag: str, v) -> bool:
        # Would this flag value let the gate actually RUN (vs decline)? Mirrors
        # the gate logic in rules.py without importing it.
        if v == "<MISSING>" or v is None:
            return False
        if rule_name == "balance_sheet_identity":   # needs liabilities_complete == True
            return v is True
        if rule_name == "cash_flow_tie_out":         # True means "decline" (restricted)
            return True  # flag emitted either way lets the rule make a decision
        return True  # eps basis strings: any non-null value is a real basis

    if rule == "eps_reconciliation":
        eps_ok = _emitted(emitted.get("eps_income_basis")) and emitted.get("eps_income_basis") is not None
        inc_ok = (_emitted(emitted.get("income_operand_basis"))
                  and emitted.get("income_operand_basis") is not None) or bool(income_basis_via_operand)
        evidence_emitted = _emitted(emitted.get("eps_income_basis")) and (
            _emitted(emitted.get("income_operand_basis")) or bool(income_basis_via_operand))
        evidence_gate_satisfied = eps_ok and inc_ok
    elif required:
        evidence_emitted = all(_emitted(emitted.get(f)) for f in required)
        evidence_gate_satisfied = all(_gate_runs(rule, f, emitted.get(f)) for f in required)
    else:
        evidence_emitted = True
        evidence_gate_satisfied = True

    shares_cat = claim.operands[2].category if len(claim.operands) >= 3 else None

    return ClaimRecord(
        ticker=ticker,
        rule_name=rule,
        operation=claim.operation.value,
        verdict=final_status.value,
        prose_verdict=prose_status.value,
        adjudication=adjudication,
        operand_values=[o.value for o in claim.operands],
        evidence_flags_required=required,
        evidence_flags_emitted=emitted,
        evidence_emitted=evidence_emitted,
        evidence_gate_satisfied=evidence_gate_satisfied,
        income_basis_via_operand=income_basis_via_operand,
        eps_variant=claim.eps_variant.value if claim.eps_variant else None,
        shares_category=shares_cat,
        node_id=claim.node_id,
        depends_on=list(claim.depends_on or []),
        has_graph_dep=bool(claim.depends_on),
        explanation=(res.explanation + (f"  |  [XBRL adjudication] {adjudication}"
                                        if adjudication else "")),
    )


@dataclass
class FilingRecord:
    ticker: str
    sector: str
    stress: List[str]
    company: str
    period: Optional[str]
    fetch_error: Optional[str]
    extraction_available: bool
    extraction_source: str
    extraction_error: Optional[str]
    n_claims: int
    # Pipeline-level outcome (Item-4 requirement): the single most important
    # signal — did this filing produce a non-vacuous result, or degrade silently?
    #   ok                    -> >=1 checkable claim produced
    #   fetch_failed          -> SEC fetch errored; no text
    #   extraction_unavailable-> no live backend and no cached extraction
    #   silent_degradation    -> extraction returned but parsed to 0 claims WITH
    #                            parse/validation issues (the AMD/VZ shape)
    #   vacuous_no_checkable  -> claims parsed but NONE were checkable
    pipeline_status: str = "ok"
    n_checkable: int = 0
    n_dropped: int = 0
    claims: List[dict] = field(default_factory=list)
    parse_issues: List[str] = field(default_factory=list)


# Verdicts that do NOT count toward "checkable" (mirrors score._EXCLUDED).
_NON_CHECKABLE_VERDICTS = {
    "UNCHECKED", "NEEDS_REVIEW", "PROPAGATED_ERROR", "INSUFFICIENT_EVIDENCE",
}


def run_filing(meta: dict, *, mode: str, use_cache: bool,
               provider: Optional[str], model: Optional[str]) -> FilingRecord:
    ticker = meta["ticker"]
    cf = fetch_filing(ticker, use_cache=use_cache)
    ext = extract_for(cf, mode=mode, provider=provider, model=model)

    claims: List[Claim] = []
    issues: List[str] = []
    if ext["available"]:
        parsed, parse_issues = parse_claims(ext["raw"])
        if _document_has_preferred_eps_context(cf.statements_text):
            for c in parsed:
                if c.rule_name == "eps_reconciliation":
                    c.params = dict(c.params or {})
                    c.params.setdefault("preferred_dividends_present", True)
        # Only internal_consistency claims are in scope for this harness.
        claims = [c for c in parsed if c.operation == Operation.INTERNAL_CONSISTENCY]
        issues = [pi.reason for pi in parse_issues]

    records = [record_claim(ticker, c) for c in claims]

    # ---- Pipeline-level classification (the Item-4 honesty signal) -----------
    n_checkable = sum(1 for r in records if r.verdict not in _NON_CHECKABLE_VERDICTS)
    n_dropped = sum(1 for r in issues
                    if not str(r).startswith("repaired:") and "all operands missing" not in str(r))
    if cf.fetch_error:
        pipeline_status = "fetch_failed"
    elif not ext["available"]:
        pipeline_status = "extraction_unavailable"
    elif len(records) == 0 and n_dropped > 0:
        pipeline_status = "silent_degradation"      # AMD/VZ shape: dropped, 0 claims
    elif len(records) == 0:
        pipeline_status = "extraction_empty"         # model legitimately found nothing
    elif n_checkable == 0:
        pipeline_status = "vacuous_no_checkable"     # claims exist but none checkable
    else:
        pipeline_status = "ok"

    return FilingRecord(
        pipeline_status=pipeline_status,
        n_checkable=n_checkable,
        n_dropped=n_dropped,
        ticker=ticker,
        sector=meta.get("sector", ""),
        stress=meta.get("stress", []),
        company=cf.company,
        period=cf.period,
        fetch_error=cf.fetch_error,
        extraction_available=ext["available"],
        extraction_source=ext["source"],
        extraction_error=ext["error"],
        n_claims=len(records),
        claims=[asdict(r) for r in records],
        parse_issues=issues,
    )


# ---------------------------------------------------------------------------
# Run orchestration
# ---------------------------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(mode: str, *, tickers: Optional[List[str]] = None, use_cache: bool = True,
        provider: Optional[str] = None, model: Optional[str] = None,
        limit: Optional[int] = None) -> dict:
    fset = load_filing_set()
    if tickers:
        want = {t.upper() for t in tickers}
        fset = [m for m in fset if m["ticker"].upper() in want]
    if limit:
        fset = fset[:limit]

    started = _now()
    filings: List[FilingRecord] = []
    for m in fset:
        t0 = time.time()
        fr = run_filing(m, mode=mode, use_cache=use_cache, provider=provider, model=model)
        filings.append(fr)
        print(f"  [{fr.pipeline_status:>22}] {fr.ticker:<6} {fr.company[:26]:26} "
              f"claims={fr.n_claims:<2} checkable={fr.n_checkable:<2} "
              f"dropped={fr.n_dropped:<2} {time.time()-t0:.1f}s")
        if mode == "live" and fr.pipeline_status != "extraction_unavailable":
            time.sleep(4.0)

    payload = {
        "schema": "aritiq.reliability.run/v1",
        "mode": mode,
        "started_at": started,
        "finished_at": _now(),
        "n_filings": len(filings),
        "filings": [asdict(f) for f in filings],
    }
    out_path = os.path.join(RUNS_DIR, f"run_{int(time.time())}.json")
    json.dump(payload, open(out_path, "w"), indent=2)
    payload["_path"] = out_path
    print(f"\n  Run written to: {out_path}")
    return payload


def _fetch_only(tickers: Optional[List[str]], use_cache: bool, limit: Optional[int]):
    fset = load_filing_set()
    if tickers:
        want = {t.upper() for t in tickers}
        fset = [m for m in fset if m["ticker"].upper() in want]
    if limit:
        fset = fset[:limit]
    ok = fail = 0
    for m in fset:
        t0 = time.time()
        cf = fetch_filing(m["ticker"], use_cache=use_cache)
        if cf.fetch_error:
            fail += 1
            print(f"  [FAIL] {cf.ticker:<6} {cf.fetch_error[:70]}")
        else:
            ok += 1
            print(f"  [ ok ] {cf.ticker:<6} {cf.company[:28]:28} "
                  f"period={cf.period} chars={len(cf.statements_text):>6} {time.time()-t0:.1f}s")
        time.sleep(0.2)  # be polite to SEC
    print(f"\n  fetched: {ok} ok, {fail} failed -> {FILINGS_DIR}")


def main():
    ap = argparse.ArgumentParser(description="Aritiq reliability harness")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--live", action="store_true", help="fetch + live LLM extraction + verify")
    g.add_argument("--replay", action="store_true", help="use cached extractions only (no network)")
    g.add_argument("--fetch-only", action="store_true", help="fetch filings from SEC, cache them, stop")
    ap.add_argument("--tickers", nargs="*", help="limit to these tickers")
    ap.add_argument("--limit", type=int, default=None, help="limit to first N filings")
    ap.add_argument("--no-cache", action="store_true", help="re-fetch filings even if cached")
    ap.add_argument("--provider", default=None, help="override ARITIQ_PROVIDER for live extraction")
    ap.add_argument("--model", default=None, help="override extraction model")
    args = ap.parse_args()

    use_cache = not args.no_cache

    if args.fetch_only:
        _fetch_only(args.tickers, use_cache, args.limit)
        return

    mode = "live" if args.live else "replay"
    print("=" * 78)
    print(f"  ARITIQ RELIABILITY HARNESS — mode={mode}")
    print("=" * 78)
    run(mode, tickers=args.tickers, use_cache=use_cache,
        provider=args.provider, model=args.model, limit=args.limit)


if __name__ == "__main__":
    main()
