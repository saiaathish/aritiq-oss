"""
Aritiq reliability REPORT generator.

Consumes a run file produced by harness.py and emits:
  * pass/fail-style verdict counts per filing and overall,
  * the evidence-flag EMISSION rate by rule (the extractor-compliance signal),
  * a FAILURE TAXONOMY that separates EXTRACTION failures from VERIFIER failures,
  * a prioritized list of what to fix before deployment,
  * a manual-review scaffold (CSV) so a human can mark each verdict TP/TN/FP/FN.

Discipline (per the deployment handoff):
  * No accuracy CLAIM is asserted — every number is a count derived from the run.
  * The harness cannot, by itself, know ground truth. So it classifies each
    verdict into an AUTOMATIC bucket based on observable signals (was evidence
    emitted? did the gate run? did the math agree?), and emits a review CSV with
    a blank `human_label` column for true TP/TN/FP/FN adjudication. The taxonomy
    below is the auto-bucketing; the CSV is where a human confirms it.

Buckets (auto):
  VERIFIED                      -> auto:true_positive_candidate (math agreed, gate ran)
  WRONG_MATH                    -> auto:NEEDS_REVIEW_HIGH (a conviction — confirm it's real)
  INSUFFICIENT_EVIDENCE + flags-not-emitted
                                -> extraction_failure:missing_evidence_flags
  INSUFFICIENT_EVIDENCE + flags-emitted-but-decline (restricted cash, incomplete liab)
                                -> verifier_gate_fired:by_design (correct caution)
  AMBIGUOUS                     -> verifier_structural (variant/operand-count/div0)
  UNSUPPORTED_NUMBER            -> extraction_failure:missing_operand

Run:
    python benchmark/reliability/report.py                 # newest run
    python benchmark/reliability/report.py <run_file.json> # specific run
    python benchmark/reliability/report.py --md report.md  # also write Markdown
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "cache", "runs")


def newest_run() -> Optional[str]:
    runs = sorted(glob.glob(os.path.join(RUNS_DIR, "run_*.json")), key=os.path.getmtime)
    return runs[-1] if runs else None


# ---------------------------------------------------------------------------
# Auto-bucketing — observable-signal classification (NOT ground truth).
# ---------------------------------------------------------------------------

def _cf_label_caught(claim: dict) -> bool:
    """Did the explanation indicate the restricted-cash detection fired? The
    verifier's cash-tie-out decline message names 'restricted-cash'."""
    return "restricted-cash" in (claim.get("explanation") or "").lower() \
        or "restricted cash" in (claim.get("explanation") or "").lower()


def auto_bucket(claim: dict) -> str:
    v = claim["verdict"]
    rule = claim.get("rule_name")
    emitted = claim.get("evidence_emitted", False)
    gate_ok = claim.get("evidence_gate_satisfied", False)

    if v == "VERIFIED":
        return "auto:true_positive_candidate"
    if v == "WRONG_MATH":
        return "auto:NEEDS_REVIEW_HIGH(conviction)"
    if v == "INSUFFICIENT_EVIDENCE":
        if not emitted:
            # Special case: the cash tie-out can reach the CORRECT cautious verdict
            # via the deterministic restricted-cash LABEL detector even when the
            # extractor emitted no flag. Credit the safety-net rather than blaming
            # extraction for a verdict that is already right.
            if rule == "cash_flow_tie_out" and _cf_label_caught(claim):
                return "verifier_safety_net:restricted_cash_label_caught"
            return "extraction_failure:missing_evidence_flags"
        # emitted but the gate still declined -> a deliberate by-design decline
        # (incomplete liabilities asserted, restricted cash disclosed, basis mismatch)
        return "verifier_gate_fired:by_design"
    if v == "AMBIGUOUS":
        return "verifier_structural:variant_or_count_or_div0"
    if v == "UNSUPPORTED_NUMBER":
        return "extraction_failure:missing_operand"
    if v == "NEEDS_REVIEW":
        return "verifier_definitional:human_routed"
    return f"other:{v}"


# Which side owns each bucket (for the extraction-vs-verifier split).
_OWNER = {
    "extraction_failure:missing_evidence_flags": "extraction",
    "extraction_failure:missing_operand": "extraction",
    "verifier_gate_fired:by_design": "verifier(by_design)",
    "verifier_safety_net:restricted_cash_label_caught": "verifier(safety_net)",
    "verifier_structural:variant_or_count_or_div0": "verifier(structural)",
    "verifier_definitional:human_routed": "verifier(by_design)",
    "auto:true_positive_candidate": "—(verified)",
    "auto:NEEDS_REVIEW_HIGH(conviction)": "—(needs_human)",
}


# ---------------------------------------------------------------------------
# Per-sector / per-statement-type aggregation (Perplexity metric shape).
# ---------------------------------------------------------------------------
# These summarize verdicts ALREADY produced by the pipeline into the exact shape
# the reviewer feedback asked for: "X% of in-scope claims verified, Y% gated
# insufficient-evidence, Z% clear extraction misses, broken down by sector /
# statement type." They ONLY aggregate — they do NOT recompute a single verdict.
# `extraction_miss` == UNSUPPORTED_NUMBER (a missing operand — the clean extraction
# failure per the owner taxonomy above). WRONG_MATH (a conviction) is surfaced as
# its own raw count, never folded into a percentage, because a single false
# conviction is the worst-case failure and must stay visible.

def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def summarize_verdicts(counter: Counter) -> dict:
    """Collapse a verdict Counter into the reviewer-requested metric shape.

    Pure function of the counts — no verdict is recomputed. Percentages are over
    the total in-scope claims in this slice (the group's own denominator).
    """
    total = sum(counter.values())
    verified = counter.get("VERIFIED", 0)
    insuff = counter.get("INSUFFICIENT_EVIDENCE", 0)
    unsupported = counter.get("UNSUPPORTED_NUMBER", 0)
    wrong = counter.get("WRONG_MATH", 0)
    ambiguous = counter.get("AMBIGUOUS", 0)
    return {
        "n": total,
        "counts": dict(counter),
        "verified": verified,
        "insufficient_evidence": insuff,
        "extraction_miss": unsupported,   # UNSUPPORTED_NUMBER == missing operand
        "wrong_math": wrong,              # conviction — raw count, kept visible
        "ambiguous": ambiguous,
        "pct_verified": _pct(verified, total),
        "pct_insufficient_evidence": _pct(insuff, total),
        "pct_extraction_miss": _pct(unsupported, total),
    }


def breakdown_by_sector(filings: List[dict]) -> Dict[str, dict]:
    """Group every in-scope claim by its filing's sector, then summarize.

    Sector is a FILING attribute (present on each run-file filing); it is applied
    to each of that filing's claims. Filings with no claims contribute nothing.
    """
    by_sector: Dict[str, Counter] = defaultdict(Counter)
    for f in filings:
        sector = f.get("sector") or "(unlabeled)"
        for c in f.get("claims", []):
            by_sector[sector][c["verdict"]] += 1
    return {s: summarize_verdicts(vc) for s, vc in by_sector.items()}


def breakdown_by_statement_type(filings: List[dict]) -> Dict[str, dict]:
    """Group every in-scope claim by its statement-type rule_name, then summarize.

    rule_name is a CLAIM attribute (balance_sheet_identity / eps_reconciliation /
    cash_flow_tie_out). This is the 'X% of EPS reconciliations verified across all
    sectors' view.
    """
    by_rule: Dict[str, Counter] = defaultdict(Counter)
    for f in filings:
        for c in f.get("claims", []):
            rule = c.get("rule_name") or "(none)"
            by_rule[rule][c["verdict"]] += 1
    return {r: summarize_verdicts(vc) for r, vc in by_rule.items()}


def analyze(run: dict) -> dict:
    filings = run["filings"]
    verdicts = Counter()
    buckets = Counter()
    owner = Counter()
    by_rule_emission = defaultdict(lambda: {"emitted": 0, "total": 0})
    by_rule_verdict = defaultdict(Counter)
    by_stress = defaultdict(Counter)
    graph_dep_claims = 0
    total_claims = 0

    fetch_fail = [f["ticker"] for f in filings if f["fetch_error"]]
    extract_unavail = [f["ticker"] for f in filings
                       if not f["fetch_error"] and not f["extraction_available"]]

    # ---- Pipeline-level outcome tally (the Item-4 headline) ------------------
    pipeline_status = Counter()
    status_tickers = defaultdict(list)
    for f in filings:
        st = f.get("pipeline_status", "ok")
        pipeline_status[st] += 1
        status_tickers[st].append(f["ticker"])
    n = len(filings) or 1
    unavailable = (pipeline_status.get("fetch_failed", 0)
                   + pipeline_status.get("extraction_unavailable", 0))
    # Honest denominator: completion rate is computed over filings that ACTUALLY
    # had an extraction attempt (live or cached). Filings marked
    # extraction_unavailable were never run (e.g. no reachable backend) and are
    # reported separately, NOT counted as failures.
    attempted = max(n - unavailable, 0)
    completion = {
        "total_filings": n,
        "extraction_attempted": attempted,
        "not_run_unavailable": unavailable,
        "completed_with_checkable": pipeline_status.get("ok", 0),
        "silently_degraded": (pipeline_status.get("silent_degradation", 0)
                              + pipeline_status.get("vacuous_no_checkable", 0)),
        "extraction_empty": pipeline_status.get("extraction_empty", 0),
        "pct_of_attempted_completed": round(100.0 * pipeline_status.get("ok", 0) / attempted, 1)
        if attempted else None,
    }

    per_filing = []
    for f in filings:
        fv = Counter()
        for c in f["claims"]:
            total_claims += 1
            v = c["verdict"]
            verdicts[v] += 1
            fv[v] += 1
            b = auto_bucket(c)
            buckets[b] += 1
            owner[_OWNER.get(b, "other")] += 1
            rule = c.get("rule_name") or "?"
            by_rule_verdict[rule][v] += 1
            if c.get("evidence_flags_required"):
                by_rule_emission[rule]["total"] += 1
                if c.get("evidence_emitted"):
                    by_rule_emission[rule]["emitted"] += 1
            if c.get("has_graph_dep"):
                graph_dep_claims += 1
            for s in f.get("stress", []):
                by_stress[s][v] += 1
        per_filing.append({
            "ticker": f["ticker"], "company": f["company"], "period": f["period"],
            "available": f["extraction_available"], "source": f["extraction_source"],
            "n_claims": f["n_claims"], "verdicts": dict(fv),
            "fetch_error": f["fetch_error"], "extraction_error": f["extraction_error"],
        })

    return {
        "n_filings": len(filings),
        "n_with_extraction": sum(1 for f in filings if f["extraction_available"]),
        "pipeline_status": dict(pipeline_status),
        "status_tickers": {k: v for k, v in status_tickers.items()},
        "completion": completion,
        "fetch_fail": fetch_fail,
        "extract_unavail": extract_unavail,
        "total_claims": total_claims,
        "verdicts": dict(verdicts),
        "buckets": dict(buckets),
        "owner_split": dict(owner),
        "by_rule_emission": {k: dict(v) for k, v in by_rule_emission.items()},
        "by_rule_verdict": {k: dict(v) for k, v in by_rule_verdict.items()},
        "by_stress": {k: dict(v) for k, v in by_stress.items()},
        # Perplexity metric shape: same verdicts, aggregated per sector / statement type.
        "by_sector": breakdown_by_sector(filings),
        "by_statement_type": breakdown_by_statement_type(filings),
        "graph_dep_claims": graph_dep_claims,
        "per_filing": per_filing,
    }


# ---------------------------------------------------------------------------
# Prioritized fix list — derived from the analysis, not hardcoded.
# ---------------------------------------------------------------------------

def prioritized_fixes(a: dict) -> List[str]:
    fixes = []
    em = a["by_rule_emission"]

    # 1. Evidence-flag emission gaps are the #1 deployment blocker: they convert
    #    fine math into INSUFFICIENT_EVIDENCE (false negatives for the user).
    for rule, c in sorted(em.items()):
        if c["total"] and c["emitted"] < c["total"]:
            rate = 100.0 * c["emitted"] / c["total"]
            fixes.append(
                f"[P1 extraction] {rule}: evidence flags emitted on only "
                f"{c['emitted']}/{c['total']} claims ({rate:.0f}%). Each un-tagged claim "
                f"gates to INSUFFICIENT_EVIDENCE even when the math is correct. Fix in the "
                f"extraction prompt (require the flag), NOT by loosening the gate.")

    # 2. Convictions must be human-confirmed before trusting them.
    wm = a["verdicts"].get("WRONG_MATH", 0)
    if wm:
        fixes.append(
            f"[P1 review] {wm} WRONG_MATH conviction(s). Manually confirm each is a real "
            f"arithmetic disagreement with complete, correctly-scoped operands before "
            f"shipping — a single false conviction is the worst-case failure.")

    # 3. Fetch/slice problems starve the extractor of inputs.
    if a["fetch_fail"]:
        fixes.append(f"[P2 ingest] Fetch failed for: {', '.join(a['fetch_fail'])}. "
                     f"No filing text -> no claims. Investigate ticker/CIK/UA/network.")

    # 4. Structural AMBIGUOUS usually means missing variant/basis tags upstream.
    amb = a["verdicts"].get("AMBIGUOUS", 0)
    if amb:
        fixes.append(
            f"[P2 extraction] {amb} AMBIGUOUS verdict(s) (EPS variant unrecorded, operand "
            f"count, or div-by-zero). Where it's an unrecorded EPS variant, the fix is the "
            f"extractor emitting eps_variant + shares category — not a verifier change.")

    # 5. Graph dependency population.
    if a["total_claims"] and a["graph_dep_claims"] == 0:
        fixes.append(
            "[P3 extraction] No claims carried graph dependencies (depends_on). Cross-statement "
            "claims are leaf-level by nature, so this is expected here; revisit only when the "
            "summary-audit pass (derived figures) is added to this harness.")

    if not fixes:
        fixes.append("[none] No blocking issues detected in this run.")
    return fixes


# ---------------------------------------------------------------------------
# Manual-review CSV scaffold
# ---------------------------------------------------------------------------

def write_review_csv(run: dict, path: str) -> int:
    rows = 0
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "rule_name", "verdict", "auto_bucket", "owner",
                    "operands", "evidence_flags_emitted", "explanation",
                    "human_label(TP/TN/FP/FN)", "human_notes"])
        for f in run["filings"]:
            for c in f["claims"]:
                b = auto_bucket(c)
                w.writerow([
                    f["ticker"], c.get("rule_name"), c["verdict"], b,
                    _OWNER.get(b, "other"),
                    "|".join(str(x) for x in c.get("operand_values", [])),
                    json.dumps(c.get("evidence_flags_emitted", {})),
                    (c.get("explanation") or "")[:200], "", "",
                ])
                rows += 1
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(run: dict, a: dict) -> str:
    L = []
    p = L.append
    p("=" * 78)
    p("  ARITIQ RELIABILITY REPORT")
    p("=" * 78)
    p(f"  mode={run.get('mode')}  filings={a['n_filings']}  "
      f"with_extraction={a['n_with_extraction']}  in-scope_claims={a['total_claims']}")
    p(f"  run started {run.get('started_at')}  finished {run.get('finished_at')}")
    p("  NOTE: counts are observations from this run. No real-filing accuracy is")
    p("  claimed; FP/FN adjudication requires the human review CSV.")
    p("")

    c = a["completion"]
    p("-" * 78)
    p("  PIPELINE OUTCOME  (the headline: did each filing produce a real result?)")
    p("-" * 78)
    for st, n in sorted(a["pipeline_status"].items(), key=lambda kv: -kv[1]):
        tks = ", ".join(a["status_tickers"].get(st, [])[:12])
        p(f"    {n:>3}  {st:<24} {tks}")
    p("")
    pct = c["pct_of_attempted_completed"]
    pct_s = f"{pct}%" if pct is not None else "n/a"
    p(f"    extraction ATTEMPTED on {c['extraction_attempted']}/{c['total_filings']} "
      f"filings ({c['not_run_unavailable']} not run — no reachable backend / unavailable).")
    p(f"    COMPLETION RATE among attempted (>=1 checkable claim): "
      f"{c['completed_with_checkable']}/{c['extraction_attempted']}  ({pct_s})")
    p(f"    silently degraded (0 checkable): {c['silently_degraded']}   "
      f"extraction empty: {c['extraction_empty']}")
    p("")

    p("-" * 78)
    p("  VERDICT DISTRIBUTION (in-scope internal_consistency claims)")
    p("-" * 78)
    for v, n in sorted(a["verdicts"].items(), key=lambda kv: -kv[1]):
        p(f"    {v:<24} {n}")
    if a["fetch_fail"]:
        p(f"    [fetch failed]          {len(a['fetch_fail'])}  ({', '.join(a['fetch_fail'])})")
    if a["extract_unavail"]:
        p(f"    [extraction unavailable]{len(a['extract_unavail'])}  "
          f"({', '.join(a['extract_unavail'])})")
    p("")

    p("-" * 78)
    p("  EVIDENCE-FLAG EMISSION BY RULE  (extractor-compliance signal)")
    p("  Low emission => fine math wrongly gated to INSUFFICIENT_EVIDENCE.")
    p("-" * 78)
    for rule, c in sorted(a["by_rule_emission"].items()):
        rate = 100.0 * c["emitted"] / c["total"] if c["total"] else 0.0
        p(f"    {rule:<26} {c['emitted']}/{c['total']} emitted ({rate:.0f}%)")
    if not a["by_rule_emission"]:
        p("    (no gated-rule claims in this run)")
    p("")

    p("-" * 78)
    p("  BREAKDOWN BY STATEMENT TYPE  (% of in-scope claims, aggregation only)")
    p("-" * 78)
    p(f"    {'statement type':<24} {'N':>4}  {'%VER':>6} {'%INSUF':>7} {'%XMISS':>7}  {'WM':>3}")
    for rule, s in sorted(a["by_statement_type"].items(),
                          key=lambda kv: -kv[1]["n"]):
        p(f"    {rule:<24} {s['n']:>4}  {s['pct_verified']:>5}% "
          f"{s['pct_insufficient_evidence']:>6}% {s['pct_extraction_miss']:>6}%  "
          f"{s['wrong_math']:>3}")
    p("    (%VER verified · %INSUF insufficient-evidence gated · %XMISS extraction "
      "miss=UNSUPPORTED_NUMBER · WM WRONG_MATH convictions, raw)")
    p("")

    p("-" * 78)
    p("  BREAKDOWN BY SECTOR  (% of in-scope claims, aggregation only)")
    p("-" * 78)
    p(f"    {'sector':<24} {'N':>4}  {'%VER':>6} {'%INSUF':>7} {'%XMISS':>7}  {'WM':>3}")
    for sector, s in sorted(a["by_sector"].items(),
                            key=lambda kv: (-kv[1]["n"], kv[0])):
        p(f"    {sector[:24]:<24} {s['n']:>4}  {s['pct_verified']:>5}% "
          f"{s['pct_insufficient_evidence']:>6}% {s['pct_extraction_miss']:>6}%  "
          f"{s['wrong_math']:>3}")
    p("")

    p("-" * 78)
    p("  FAILURE TAXONOMY  (auto-bucketed; confirm in review CSV)")
    p("-" * 78)
    for b, n in sorted(a["buckets"].items(), key=lambda kv: -kv[1]):
        p(f"    {n:>3}  {b}")
    p("")
    p("  EXTRACTION vs VERIFIER ownership:")
    for o, n in sorted(a["owner_split"].items(), key=lambda kv: -kv[1]):
        p(f"    {n:>3}  {o}")
    p("")

    p("-" * 78)
    p("  VERDICTS BY STRESS DIMENSION  (priors only — not ground truth)")
    p("-" * 78)
    for s, vc in sorted(a["by_stress"].items()):
        inner = " ".join(f"{k}={v}" for k, v in sorted(vc.items()))
        p(f"    {s:<22} {inner}")
    p("")

    p("-" * 78)
    p("  PER-FILING")
    p("-" * 78)
    for pf in a["per_filing"]:
        if pf["fetch_error"]:
            p(f"    {pf['ticker']:<6} FETCH-FAIL: {pf['fetch_error'][:50]}")
        elif not pf["available"]:
            p(f"    {pf['ticker']:<6} extraction unavailable ({pf['extraction_error']})")
        else:
            vs = " ".join(f"{k}={v}" for k, v in sorted(pf["verdicts"].items()))
            p(f"    {pf['ticker']:<6} {pf['company'][:24]:24} [{pf['source']}] "
              f"claims={pf['n_claims']} {vs}")
    p("")

    p("-" * 78)
    p("  PRIORITIZED FIX LIST (pre-deployment)")
    p("-" * 78)
    for fx in prioritized_fixes(a):
        p(f"    - {fx}")
    p("=" * 78)
    return "\n".join(L)


def render_markdown(run: dict, a: dict) -> str:
    L = []
    p = L.append
    p("# Aritiq Reliability Report\n")
    p(f"- **Mode:** `{run.get('mode')}`")
    p(f"- **Filings:** {a['n_filings']} ({a['n_with_extraction']} with extraction)")
    p(f"- **In-scope claims:** {a['total_claims']}")
    p(f"- **Run:** {run.get('started_at')} → {run.get('finished_at')}")
    p("\n> Counts are observations from this run. No real-filing accuracy is claimed; "
      "FP/FN adjudication requires the human review CSV.\n")

    p("## Verdict distribution\n")
    p("| Verdict | Count |\n|---|---|")
    for v, n in sorted(a["verdicts"].items(), key=lambda kv: -kv[1]):
        p(f"| {v} | {n} |")
    if a["extract_unavail"]:
        p(f"| _extraction unavailable_ | {len(a['extract_unavail'])} |")
    if a["fetch_fail"]:
        p(f"| _fetch failed_ | {len(a['fetch_fail'])} |")

    p("\n## Evidence-flag emission by rule\n")
    p("Low emission means correct math is wrongly gated to INSUFFICIENT_EVIDENCE.\n")
    p("| Rule | Emitted / Total | Rate |\n|---|---|---|")
    for rule, c in sorted(a["by_rule_emission"].items()):
        rate = 100.0 * c["emitted"] / c["total"] if c["total"] else 0.0
        p(f"| {rule} | {c['emitted']}/{c['total']} | {rate:.0f}% |")

    p("\n## Breakdown by statement type\n")
    p("Share of in-scope claims by verdict, aggregated across all sectors. "
      "Aggregation only — no verdict is recomputed. "
      "`%X-miss` = UNSUPPORTED_NUMBER (missing operand); "
      "`WRONG_MATH` convictions are shown as a raw count and never folded into a percentage.\n")
    p("| Statement type | N | % verified | % insufficient-evidence | % extraction-miss | WRONG_MATH |")
    p("|---|---|---|---|---|---|")
    for rule, s in sorted(a["by_statement_type"].items(), key=lambda kv: -kv[1]["n"]):
        p(f"| {rule} | {s['n']} | {s['pct_verified']}% | "
          f"{s['pct_insufficient_evidence']}% | {s['pct_extraction_miss']}% | {s['wrong_math']} |")

    p("\n## Breakdown by sector\n")
    p("Share of in-scope claims by verdict, grouped by the filer's sector. Aggregation only.\n")
    p("| Sector | N | % verified | % insufficient-evidence | % extraction-miss | WRONG_MATH |")
    p("|---|---|---|---|---|---|")
    for sector, s in sorted(a["by_sector"].items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        p(f"| {sector} | {s['n']} | {s['pct_verified']}% | "
          f"{s['pct_insufficient_evidence']}% | {s['pct_extraction_miss']}% | {s['wrong_math']} |")

    p("\n## Failure taxonomy (auto-bucketed)\n")
    p("| Count | Bucket | Owner |\n|---|---|---|")
    for b, n in sorted(a["buckets"].items(), key=lambda kv: -kv[1]):
        p(f"| {n} | `{b}` | {_OWNER.get(b, 'other')} |")

    p("\n## Per-filing\n")
    p("| Ticker | Company | Source | Claims | Verdicts |\n|---|---|---|---|---|")
    for pf in a["per_filing"]:
        if pf["fetch_error"]:
            p(f"| {pf['ticker']} | {pf['company']} | FETCH-FAIL | 0 | {pf['fetch_error'][:40]} |")
        elif not pf["available"]:
            p(f"| {pf['ticker']} | {pf['company']} | unavailable | 0 | {pf['extraction_error']} |")
        else:
            vs = " ".join(f"{k}={v}" for k, v in sorted(pf["verdicts"].items()))
            p(f"| {pf['ticker']} | {pf['company']} | {pf['source']} | {pf['n_claims']} | {vs} |")

    p("\n## Prioritized fix list (pre-deployment)\n")
    for fx in prioritized_fixes(a):
        p(f"- {fx}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Aritiq reliability report")
    ap.add_argument("run_file", nargs="?", default=None, help="run json (default: newest)")
    ap.add_argument("--md", default=None, help="also write a Markdown report to this path")
    ap.add_argument("--csv", default=None, help="write the manual-review CSV to this path "
                                                "(default: alongside the run file)")
    args = ap.parse_args()

    run_path = args.run_file or newest_run()
    if not run_path or not os.path.exists(run_path):
        print("No run file found. Run harness.py first.", file=sys.stderr)
        sys.exit(2)

    run = json.load(open(run_path))
    a = analyze(run)
    print(render(run, a))

    csv_path = args.csv or (os.path.splitext(run_path)[0] + "_review.csv")
    n = write_review_csv(run, csv_path)
    print(f"\n  Manual-review CSV ({n} rows) -> {csv_path}")

    if args.md:
        open(args.md, "w").write(render_markdown(run, a))
        print(f"  Markdown report -> {args.md}")


if __name__ == "__main__":
    main()
