"""
Phase 2 — XBRL-grounded verification through the EXISTING, unmodified verifier.

This builds Claim/operand objects from standardized XBRL facts (aritiq.edgar.xbrl)
and runs them through the SAME check_balance_sheet_identity / check_eps_reconciliation
/ check_cash_flow_tie_out functions the LLM path uses. No new arithmetic; no change
to aritiq/core. The only difference from the LLM path is where the operands come
from — the SEC's standardized tagging instead of prose grounding.

Because an XBRL fact carries an unambiguous concept tag, the evidence flags the
verifier gates on can be set DEFINITIVELY and correctly:
  * liabilities_complete = True  — the value came from the literal `Liabilities`
    total tag, not inferred from prose. (If the filer doesn't tag total Liabilities,
    the fact is None and we emit NO claim -> the gate never runs on a guess.)
  * eps_income_basis / income_operand_basis — set to "total" or "continuing"/"common"
    consistently from whichever income tag supplied the numerator.
  * restricted_cash_disclosed — True when the cash-flow figure came from the
    "...RestrictedCash..." tag (which by definition is a different scope than the
    balance-sheet cash tag), exactly the PLTR restricted-cash case, resolved by tag.

Run:
    python benchmark/reliability/xbrl_verify.py                 # full filing set
    python benchmark/reliability/xbrl_verify.py AMD TSLA JPM    # subset
    python benchmark/reliability/xbrl_verify.py --md xbrl_report.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.core.schema import Claim, Operation, Operand, OperandSource, EPSVariant, VerificationStatus  # noqa: E402
from aritiq.core.verify import verify_claim  # noqa: E402
from aritiq.edgar.xbrl import extract_xbrl_facts, XbrlFacts  # noqa: E402

FILING_SET = os.path.join(HERE, "filing_set.json")
RUNS_DIR = os.path.join(HERE, "cache", "runs")


# ---------------------------------------------------------------------------
# Build Claims from XBRL facts (only when the required facts are present).
# ---------------------------------------------------------------------------

def _op(value, category=None, source_text=None):
    return Operand(value=value, source=OperandSource.GROUNDED,
                   category=category, source_text=source_text)


def build_claims_from_facts(f: XbrlFacts) -> List[Claim]:
    """Return the internal_consistency claims XBRL facts can support for this filer.

    Emits a claim ONLY when every operand it needs is present in the facts. A
    missing fact means no claim (not a claim with a guessed operand) — so the
    verifier never runs on interpolated data.
    """
    claims: List[Claim] = []

    # ---- balance sheet identity: Assets == Liabilities + Equity ----------------
    # Requires the LITERAL total-liabilities tag. If the filer only tags liability
    # components (e.g. AMD, DUK), we emit no claim rather than derive Liabilities
    # (which would make the identity tautological). Equity prefers the incl-NCI tag.
    if f.assets is not None and f.liabilities is not None and f.equity is not None:
        eq_note = ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
                   if f.equity_includes_nci else "StockholdersEquity")
        # Mezzanine completeness: if the filer tags a redeemable/temporary-equity
        # block that plausibly accounts for a two-term shortfall (Assets exceed
        # Liabilities + Equity by roughly the temporary-equity amount), flag it so
        # the completeness gate declines rather than convicts. Deterministic: we
        # compare the disclosed temp-equity fact to the actual gap; we never add it
        # into the identity (that would beg the question of where mezzanine belongs).
        redeemable_present = False
        if f.temp_equity:
            gap = f.assets - (f.liabilities + f.equity)
            if gap > 0 and abs(gap - f.temp_equity) <= 0.10 * abs(f.temp_equity):
                redeemable_present = True
        claims.append(Claim(
            claim_text=f"[XBRL] {f.ticker} balance sheet identity",
            operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
            rule_name="balance_sheet_identity",
            params={"liabilities_complete": True,   # definitive: literal Liabilities tag
                    "redeemable_equity_present": redeemable_present},
            operands=[
                _op(f.assets, "total_assets", f"XBRL Assets"),
                _op(f.liabilities, "total_liabilities", f"XBRL Liabilities"),
                _op(f.equity, "total_equity", f"XBRL {eq_note}"),
            ],
            source_text=f"XBRL tags: Assets, Liabilities, {eq_note}",
            unit="$",
        ))

    # ---- EPS reconciliation (basic and diluted) --------------------------------
    # Numerator prefers net income AVAILABLE TO COMMON (the exact preferred-dividend
    # tag); falls back to total net income when the filer has no preferred stock.
    numerator = f.net_income_to_common if f.net_income_to_common is not None else f.net_income_total
    num_basis = "common" if f.net_income_to_common is not None else "total"
    num_tag = ("NetIncomeLossAvailableToCommonStockholdersBasic"
               if f.net_income_to_common is not None else "NetIncomeLoss")

    for variant, eps, shares, vtag in (
        ("basic", f.eps_basic, f.shares_basic, "Basic"),
        ("diluted", f.eps_diluted, f.shares_diluted, "Diluted"),
    ):
        # SCOPE GUARD (UPREIT / two-class diluted numerator). The only machine-readable
        # income-to-common tag is `...AvailableToCommonStockholdersBasic` — a BASIC-scope
        # numerator. For filers with a redeemable-NCI / operating-partnership structure
        # (equity_includes_nci and a preferred/participating numerator), diluted EPS is
        # computed on a DIFFERENT numerator (OP-unit income added back), which is not
        # separately tagged. Pairing the basic numerator with diluted shares is a scope
        # mismatch, so we DECLINE to emit the diluted claim rather than convict on it
        # (the Welltower diluted case). Basic still verifies; total-net-income filers
        # (no preferred) are unaffected.
        if (variant == "diluted" and num_basis == "common"
                and f.equity_includes_nci and f.shares_diluted != f.shares_basic):
            continue
        if eps is not None and numerator is not None and shares is not None and shares != 0:
            claims.append(Claim(
                claim_text=f"[XBRL] {f.ticker} {variant} EPS reconciliation",
                operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
                rule_name="eps_reconciliation",
                eps_variant=EPSVariant.BASIC if variant == "basic" else EPSVariant.DILUTED,
                params={"eps_income_basis": num_basis, "income_operand_basis": num_basis},
                operands=[
                    _op(eps, variant, f"XBRL EarningsPerShare{vtag}"),
                    _op(numerator, num_basis, f"XBRL {num_tag}"),
                    _op(shares, variant, f"XBRL WeightedAverageNumberOf...{vtag}"),
                ],
                source_text=f"XBRL tags: EarningsPerShare{vtag}, {num_tag}, shares {vtag}",
                unit=None,
            ))

    # ---- cash tie-out ----------------------------------------------------------
    # CF ending cash prefers the "...RestrictedCash..." tag; when it supplied the
    # value, restricted_cash_disclosed=True (different scope than BS cash by tag).
    if f.bs_cash is not None and f.cf_cash is not None:
        # The CF figure came from a "...RestrictedCash..." tag, but that only makes
        # the two scopes DIFFERENT when there is an actual restricted component
        # (cf_cash != bs_cash). When they're equal, there is no restricted cash to
        # disclose and the tie-out should genuinely verify. So disclose-flag only
        # when the tagged scopes actually differ.
        restricted = bool(f.cf_cash_includes_restricted) and (
            abs(f.cf_cash - f.bs_cash) > 1e-6 * max(abs(f.bs_cash), 1.0))
        claims.append(Claim(
            claim_text=f"[XBRL] {f.ticker} cash tie-out",
            operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
            rule_name="cash_flow_tie_out",
            params={"restricted_cash_disclosed": restricted},
            operands=[
                _op(f.cf_cash, "statement_ending_cash",
                    "XBRL CashCashEquivalentsRestrictedCash..." if f.cf_cash_includes_restricted
                    else "XBRL CashAndCashEquivalentsAtCarryingValue"),
                _op(f.bs_cash, "balance_sheet_cash", "XBRL CashAndCashEquivalentsAtCarryingValue"),
            ],
            source_text="XBRL cash tags",
            unit="$",
        ))

    return claims


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

@dataclass
class XbrlFilingResult:
    ticker: str
    company: str
    period_end: Optional[str]
    fetch_error: Optional[str]
    facts_present: dict = field(default_factory=dict)
    n_claims: int = 0
    verdicts: dict = field(default_factory=dict)
    claims: List[dict] = field(default_factory=list)


def run_ticker(ticker: str, *, period_end: Optional[str] = None,
               form: str = "10-K", use_cache: bool = True) -> XbrlFilingResult:
    f = extract_xbrl_facts(ticker, period_end=period_end, form=form, use_cache=use_cache)
    if f.fetch_error:
        return XbrlFilingResult(ticker=ticker, company=f.company,
                                period_end=f.period_end, fetch_error=f.fetch_error)
    claims = build_claims_from_facts(f)
    vc = Counter()
    rows = []
    for c in claims:
        r = verify_claim(c)
        vc[r.status.value] += 1
        rows.append({"rule": c.rule_name, "verdict": r.status.value,
                     "operands": [o.value for o in c.operands],
                     "explanation": r.explanation[:160]})
    present = {k: (v is not None) for k, v in {
        "assets": f.assets, "liabilities": f.liabilities, "equity": f.equity,
        "ni_total": f.net_income_total, "ni_common": f.net_income_to_common,
        "eps_basic": f.eps_basic, "shares_basic": f.shares_basic,
        "bs_cash": f.bs_cash, "cf_cash": f.cf_cash,
    }.items()}
    return XbrlFilingResult(
        ticker=ticker, company=f.company, period_end=f.period_end, fetch_error=None,
        facts_present=present, n_claims=len(claims), verdicts=dict(vc), claims=rows,
    )


def _export_ticker(ticker: str, *, form: str, use_cache: bool, export_dir: str) -> None:
    """Feature 3: write the audit-trail CSV (+ PDF if available) for one ticker,
    from the SAME facts and verdicts the run just produced."""
    from aritiq.export import export_csv, export_pdf, PDF_AVAILABLE  # local: optional dep
    f = extract_xbrl_facts(ticker, form=form, use_cache=use_cache)
    claims = build_claims_from_facts(f)
    vresults = [verify_claim(c) for c in claims]
    meta = {"ticker": ticker, "form": form, "period_end": f.period_end,
            "company": f.company, "n_claims": len(claims),
            "source": "XBRL-grounded (SEC companyfacts)"}
    base = os.path.join(export_dir, f"{ticker.upper()}_{form.replace('-', '')}_audit")
    export_csv(vresults, base + ".csv", meta=meta)
    tag = "CSV"
    if PDF_AVAILABLE:
        export_pdf(vresults, base + ".pdf",
                   title=f"Aritiq Audit — {ticker} ({form})", meta=meta)
        tag = "CSV+PDF"
    print(f"      [export:{tag}] {base}.*")


def load_tickers() -> List[str]:
    return [x["ticker"] for x in json.load(open(FILING_SET))["filings"]]


def main():
    ap = argparse.ArgumentParser(description="XBRL-grounded verification")
    ap.add_argument("tickers", nargs="*", help="tickers (default: full filing set)")
    ap.add_argument("--form", default="10-K", choices=["10-K", "10-Q", "8-K"],
                    help="SEC form type to verify (default 10-K)")
    ap.add_argument("--md", default=None, help="write a markdown summary here")
    ap.add_argument("--export-dir", default=None,
                    help="write a per-ticker audit-trail CSV (and PDF if reportlab is "
                         "installed) into this directory — Feature 3 compliance export")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    tickers = args.tickers or load_tickers()
    results: List[XbrlFilingResult] = []
    total = Counter()
    wrong = []
    ok_filers = 0
    if args.export_dir:
        os.makedirs(args.export_dir, exist_ok=True)
    for tk in tickers:
        r = run_ticker(tk, form=args.form, use_cache=not args.no_cache)
        results.append(r)
        if r.fetch_error:
            print(f"  [FETCH-FAIL] {tk:6} {r.fetch_error[:60]}")
            continue
        if args.export_dir and r.n_claims:
            _export_ticker(tk, form=args.form, use_cache=not args.no_cache,
                           export_dir=args.export_dir)
        if r.n_claims and any(v not in ("",) for v in r.verdicts):
            checkable = sum(n for k, n in r.verdicts.items()
                            if k not in ("INSUFFICIENT_EVIDENCE", "AMBIGUOUS",
                                         "UNSUPPORTED_NUMBER", "UNCHECKED", "NEEDS_REVIEW"))
            if checkable:
                ok_filers += 1
        for k, n in r.verdicts.items():
            total[k] += n
        for c in r.claims:
            if c["verdict"] == "WRONG_MATH":
                wrong.append((tk, c["rule"], c["operands"]))
        vs = " ".join(f"{k}={v}" for k, v in sorted(r.verdicts.items()))
        print(f"  [{('ok' if r.n_claims else 'no-claims'):>9}] {tk:6} claims={r.n_claims} {vs}")

    print("\n" + "=" * 70)
    print(f"  XBRL-GROUNDED RESULTS ({args.form}) over {len(tickers)} filers")
    print("=" * 70)
    print(f"  verdict totals: {dict(total)}")
    print(f"  WRONG_MATH: {len(wrong)}")
    for t, r, ov in wrong:
        print(f"    {t:6} {r:24} {ov}")
    fetch_fail = [r.ticker for r in results if r.fetch_error]
    if fetch_fail:
        print(f"  fetch failures ({len(fetch_fail)}): {', '.join(fetch_fail)}")

    os.makedirs(RUNS_DIR, exist_ok=True)
    out = os.path.join(RUNS_DIR, f"xbrl_run_{int(time.time())}.json")
    json.dump({"schema": "aritiq.xbrl.run/v1", "n_filers": len(tickers),
               "verdict_totals": dict(total), "wrong_math": wrong,
               "results": [vars(r) for r in results]}, open(out, "w"), indent=2)
    print(f"\n  written: {out}")

    if args.md:
        with open(args.md, "w") as fh:
            fh.write(f"# XBRL-grounded verification\n\n")
            fh.write(f"- Filers: {len(tickers)}\n- Verdict totals: `{dict(total)}`\n")
            fh.write(f"- WRONG_MATH: {len(wrong)}\n\n")
            fh.write("| Ticker | Claims | Verdicts |\n|---|---|---|\n")
            for r in results:
                if r.fetch_error:
                    fh.write(f"| {r.ticker} | — | FETCH-FAIL |\n")
                else:
                    vs = " ".join(f"{k}={v}" for k, v in sorted(r.verdicts.items()))
                    fh.write(f"| {r.ticker} | {r.n_claims} | {vs} |\n")
        print(f"  markdown: {args.md}")


if __name__ == "__main__":
    main()
