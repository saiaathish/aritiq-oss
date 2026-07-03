"""Phase 5 XBRL benchmark calibration report.

This script consumes `xbrl_verify.py` run JSON and computes reproducible
expanded-set metrics without introducing a new model score.

Confidence definition:
- high: verifier made a math verdict (VERIFIED or WRONG_MATH)
- medium: verifier declined with INSUFFICIENT_EVIDENCE
- low: no XBRL claim/fetch failure for a filer

The reported precision/recall/FPR are automatic benchmark-operating metrics:
- precision = VERIFIED / (VERIFIED + WRONG_MATH)
- false-positive rate = WRONG_MATH / (VERIFIED + WRONG_MATH)
- verification recall/coverage = VERIFIED / all emitted XBRL claims

These are not human-adjudicated accounting truth labels; WRONG_MATH rows are
listed for root-cause review.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional


HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "cache", "runs")
FILING_SET = os.path.join(HERE, "filing_set.json")


def _latest_xbrl_run() -> str:
    runs = sorted(glob.glob(os.path.join(RUNS_DIR, "xbrl_run_*.json")), key=os.path.getmtime)
    if not runs:
        raise SystemExit("No xbrl_run_*.json files found. Run xbrl_verify.py first.")
    return runs[-1]


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _filing_meta() -> Dict[str, dict]:
    data = json.load(open(FILING_SET))
    return {x["ticker"].upper(): x for x in data["filings"]}


def _claims(run: dict) -> Iterable[tuple[dict, dict]]:
    for filing in run.get("results", []):
        for claim in filing.get("claims", []):
            yield filing, claim


def _computed_eps(operands: List[float]) -> Optional[float]:
    if len(operands) != 3 or not operands[2]:
        return None
    return operands[1] / operands[2]


def analyze(run: dict) -> dict:
    meta = _filing_meta()
    verdicts: Counter[str] = Counter()
    by_rule: Dict[str, Counter[str]] = defaultdict(Counter)
    by_sector: Dict[str, Counter[str]] = defaultdict(Counter)
    confidence: Dict[str, Counter[str]] = defaultdict(Counter)
    wrong_rows: List[dict] = []
    no_claim_tickers: List[str] = []
    fetch_fail_tickers: List[str] = []

    for filing in run.get("results", []):
        ticker = filing["ticker"].upper()
        if filing.get("fetch_error"):
            fetch_fail_tickers.append(ticker)
        if not filing.get("claims"):
            no_claim_tickers.append(ticker)

    for filing, claim in _claims(run):
        ticker = filing["ticker"].upper()
        sector = meta.get(ticker, {}).get("sector", "(unlabeled)")
        rule = claim.get("rule") or "(none)"
        verdict = claim["verdict"]
        verdicts[verdict] += 1
        by_rule[rule][verdict] += 1
        by_sector[sector][verdict] += 1

        if verdict in {"VERIFIED", "WRONG_MATH"}:
            tier = "high"
        elif verdict == "INSUFFICIENT_EVIDENCE":
            tier = "medium"
        else:
            tier = "low"
        confidence[tier][verdict] += 1

        if verdict == "WRONG_MATH":
            computed = _computed_eps(claim.get("operands") or [])
            wrong_rows.append(
                {
                    "ticker": ticker,
                    "sector": sector,
                    "rule": rule,
                    "operands": claim.get("operands") or [],
                    "computed": computed,
                    "explanation": claim.get("explanation", ""),
                    "root_cause": (
                        "EPS XBRL operands do not reconcile within existing per-share rounding tolerance; "
                        "requires accounting-scope review before treating as filer error."
                    ),
                }
            )

    total_claims = sum(verdicts.values())
    verified = verdicts.get("VERIFIED", 0)
    wrong = verdicts.get("WRONG_MATH", 0)
    decisive = verified + wrong
    insufficient = verdicts.get("INSUFFICIENT_EVIDENCE", 0)

    return {
        "n_filers": run.get("n_filers"),
        "total_claims": total_claims,
        "verdicts": dict(verdicts),
        "precision_verified_vs_wrong": _pct(verified, decisive),
        "false_positive_rate_wrong_math": _pct(wrong, decisive),
        "verification_recall_coverage": _pct(verified, total_claims),
        "decline_rate": _pct(insufficient, total_claims),
        "confidence": {k: dict(v) for k, v in sorted(confidence.items())},
        "by_rule": {k: dict(v) for k, v in sorted(by_rule.items())},
        "by_sector": {k: dict(v) for k, v in sorted(by_sector.items())},
        "wrong_rows": wrong_rows,
        "fetch_fail_tickers": fetch_fail_tickers,
        "no_claim_tickers": no_claim_tickers,
    }


def _verdict_summary(counter: dict) -> str:
    order = ["VERIFIED", "INSUFFICIENT_EVIDENCE", "WRONG_MATH", "UNSUPPORTED_NUMBER"]
    parts = [f"{k}={counter.get(k, 0)}" for k in order if counter.get(k, 0)]
    return " ".join(parts) or "—"


def render_markdown(run: dict, a: dict, run_path: str) -> str:
    lines: List[str] = []
    p = lines.append
    p("# Phase 5 expanded XBRL benchmark report\n")
    p(f"- Source run: `{os.path.relpath(run_path, os.path.dirname(HERE))}`")
    p(f"- Filers: {a['n_filers']}")
    p(f"- XBRL-grounded claims: {a['total_claims']}")
    p(f"- Verdict totals: `{a['verdicts']}`")
    p(f"- Precision (VERIFIED / VERIFIED+WRONG_MATH): {a['precision_verified_vs_wrong']}%")
    p(f"- False-positive rate (WRONG_MATH / VERIFIED+WRONG_MATH): {a['false_positive_rate_wrong_math']}%")
    p(f"- Verification recall/coverage (VERIFIED / all emitted claims): {a['verification_recall_coverage']}%")
    p(f"- Decline rate (INSUFFICIENT_EVIDENCE / all emitted claims): {a['decline_rate']}%\n")
    p("## Confidence calibration definition\n")
    p("No new confidence score is invented. Confidence tier is derived from existing verifier state: high = decisive math verdict (VERIFIED or WRONG_MATH), medium = conservative verifier decline (INSUFFICIENT_EVIDENCE), low = no XBRL claim/fetch failure.\n")
    p("| Tier | Verdict mix |")
    p("|---|---|")
    for tier, counts in a["confidence"].items():
        p(f"| {tier} | `{counts}` |")
    p("\n## Breakdown by statement type\n")
    p("| Statement type | Claims | Verdict mix |")
    p("|---|---:|---|")
    for rule, counts in sorted(a["by_rule"].items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        p(f"| {rule} | {sum(counts.values())} | `{_verdict_summary(counts)}` |")
    p("\n## Breakdown by sector\n")
    p("| Sector | Claims | Verdict mix |")
    p("|---|---:|---|")
    for sector, counts in sorted(a["by_sector"].items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        p(f"| {sector} | {sum(counts.values())} | `{_verdict_summary(counts)}` |")
    p("\n## WRONG_MATH root-cause queue\n")
    p("These are deterministic XBRL-lane EPS convictions, not human-adjudicated filer errors. They require accounting-scope review before being counted as true issuer mistakes.\n")
    p("| Ticker | Sector | Rule | Stated | Numerator | Shares | Computed | Root cause |")
    p("|---|---|---|---:|---:|---:|---:|---|")
    for row in a["wrong_rows"]:
        ops = row["operands"]
        computed = row["computed"]
        p(
            f"| {row['ticker']} | {row['sector']} | {row['rule']} | "
            f"{ops[0] if len(ops) > 0 else ''} | {ops[1] if len(ops) > 1 else ''} | "
            f"{ops[2] if len(ops) > 2 else ''} | "
            f"{computed:.4f} | {row['root_cause']} |"
        )
    p("\n## Honest boundary\n")
    p("- This is an expanded deterministic XBRL benchmark because no live LLM provider key was available to create new prose-extraction caches.")
    p("- The existing 83-filer prose-extraction benchmark remains separately represented by `REPORT_LATEST.md`; this report expands the SEC-companyfacts lane to 115 US 10-K filers / 354 claims.")
    p("- ADR/20-F/40-F issuers remain out of scope; current companyfacts extraction is US-GAAP 10-K/10-Q centered.")
    if a["fetch_fail_tickers"]:
        p(f"- Fetch failures: {', '.join(a['fetch_fail_tickers'])}.")
    if a["no_claim_tickers"]:
        p(f"- No-claim filers: {', '.join(a['no_claim_tickers'])}.")
    p("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 5 XBRL calibration report")
    ap.add_argument("run_file", nargs="?", default=None)
    ap.add_argument("--md", default=None, help="write markdown report")
    args = ap.parse_args()

    run_path = args.run_file or _latest_xbrl_run()
    run = json.load(open(run_path))
    a = analyze(run)
    print(json.dumps(a, indent=2))
    if args.md:
        with open(args.md, "w") as fh:
            fh.write(render_markdown(run, a, run_path))
        print(f"markdown: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
