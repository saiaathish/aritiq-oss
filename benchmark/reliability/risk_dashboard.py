"""
Phase 3 item 2 — institutional risk dashboard: measurement over the real
83-filer replay run + cached company memory.

What this measures (and what it does NOT):
- Builds `aritiq.dashboard.build_dashboard` for every filer in the newest
  committed replay run (`cache/runs/run_*.json`, schema
  aritiq.reliability.run/v1), with CompanyMemory from cached companyfacts.
- AGREEMENT GATES — the dashboard must AGREE with what STATUS.md and
  REPORT_LATEST.md already established about these filers (hard failures):
    1. Aggregate verdict counts recovered through the dashboard's verification
       panels equal the run's own totals (the REPORT_LATEST numbers:
       VERIFIED 159 / INSUFFICIENT_EVIDENCE 70 / UNSUPPORTED 9 / WRONG_MATH 0).
    2. Known-decline filers (TSLA, META, KO — the XBRL-confirmed restricted-
       cash scope differences from STATUS.md item 2) must NOT show as clean:
       their verification components must carry >=1 INSUFFICIENT_EVIDENCE and
       their disclosure-quality panel must classify those declines as
       EXPLAINED (the restricted-cash disclosure reached the claim).
    3. Every filer's restatement panel is UNASSESSED on this single-filing
       run — the dashboard must never fabricate a restatement-risk number
       from the absence of a cross-document comparison.
    4. Every dashboard has exactly the five panels, all deterministic.
- NOT measured here: any new verification. The dashboard is presentation over
  verdicts/gates that already exist; this script proves the presentation
  doesn't distort them.

Run:
    python benchmark/reliability/risk_dashboard.py
    python benchmark/reliability/risk_dashboard.py --md benchmark/reliability/DASHBOARD_REPORT.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from collections import Counter
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.dashboard import build_dashboard, DETERMINISTIC  # noqa: E402
from aritiq.edgar.company_memory import build_company_memory  # noqa: E402

RUNS_DIR = os.path.join(HERE, "cache", "runs")
KNOWN_DECLINE_FILERS = ["TSLA", "META", "KO"]  # STATUS.md item 2's named cases


def _latest_replay_run(path_override: Optional[str]) -> dict:
    if path_override:
        return json.load(open(path_override))
    candidates = sorted(glob.glob(os.path.join(RUNS_DIR, "run_*.json")),
                        key=os.path.getmtime, reverse=True)
    for p in candidates:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        if d.get("schema") == "aritiq.reliability.run/v1" and d.get("mode") == "replay":
            d["_path"] = p
            return d
    raise SystemExit("no replay run found under cache/runs/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="explicit run_*.json path (default: newest replay)")
    ap.add_argument("--md", help="write a markdown report to this path")
    args = ap.parse_args()

    run = _latest_replay_run(args.run)
    filings = [f for f in run["filings"] if f.get("claims")]

    gate_failures: List[str] = []
    verdict_totals: Counter = Counter()
    dashboard_totals: Counter = Counter()
    rows: List[str] = []

    for f in filings:
        tk = f["ticker"]
        records = f["claims"]
        for c in records:
            verdict_totals[c["verdict"]] += 1

        memory = build_company_memory(tk)
        d = build_dashboard(tk, records, memory=memory)

        # Gate 4: five deterministic panels, always.
        if [p.key for p in d.panels] != ["verification_score", "evidence_coverage",
                                         "disclosure_quality", "consistency_score",
                                         "restatement_risk"]:
            gate_failures.append(f"{tk}: wrong panel set")
        if any(p.basis != DETERMINISTIC for p in d.panels):
            gate_failures.append(f"{tk}: non-deterministic panel basis")

        v = d.panel("verification_score")
        ev = d.panel("evidence_coverage")
        dq = d.panel("disclosure_quality")
        cs = d.panel("consistency_score")
        rr = d.panel("restatement_risk")

        # Gate 3: restatement must be UNASSESSED on a single-filing run.
        if rr.state != "unassessed":
            gate_failures.append(f"{tk}: restatement panel {rr.state!r}, expected unassessed")

        # Gate 1 bookkeeping: recover verdict counts through the panel.
        if v.state == "ok":
            dashboard_totals["VERIFIED"] += v.components["verified"]
            dashboard_totals["WRONG_MATH"] += v.components["wrong_math"]
            dashboard_totals["UNSUPPORTED_NUMBER"] += v.components["unsupported"]
            dashboard_totals["INSUFFICIENT_EVIDENCE"] += v.components["insufficient_evidence"]
        elif v.state == "unassessed":
            dashboard_totals["INSUFFICIENT_EVIDENCE"] += v.components.get(
                "insufficient_evidence", 0)

        # Gate 2: known-decline filers must not present as clean.
        if tk in KNOWN_DECLINE_FILERS:
            ie = (v.components.get("insufficient_evidence", 0)
                  if v.state in ("ok", "unassessed") else 0)
            if ie < 1:
                gate_failures.append(
                    f"{tk}: known INSUFFICIENT_EVIDENCE history but dashboard shows none")
            if dq.state != "ok" or dq.components.get("explained", 0) < 1:
                gate_failures.append(
                    f"{tk}: known evidence-gated decline not classified as explained")

        rows.append(
            f"| {tk} | {v.value if v.state == 'ok' else v.state} "
            f"| {ev.value if ev.state == 'ok' else ev.state} "
            f"| {dq.value if dq.state == 'ok' else dq.state} "
            f"({dq.components.get('declines', 0)} declines) "
            f"| {cs.value if cs.state == 'ok' else cs.state} "
            f"| {rr.state} |"
        )

    # Gate 1: the dashboard-recovered totals equal the run's own totals.
    for verdict in ("VERIFIED", "WRONG_MATH", "UNSUPPORTED_NUMBER",
                    "INSUFFICIENT_EVIDENCE"):
        if dashboard_totals.get(verdict, 0) != verdict_totals.get(verdict, 0):
            gate_failures.append(
                f"TOTALS: dashboard {verdict} {dashboard_totals.get(verdict, 0)} "
                f"!= run {verdict_totals.get(verdict, 0)}")

    lines = []
    lines.append("# Institutional Risk Dashboard — measurement report\n")
    lines.append(f"Generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
                 f"from replay run `{os.path.basename(run.get('_path', args.run or '?'))}` "
                 f"({len(filings)} filers with claims) + cached company memory.\n")
    lines.append(f"- Filers dashboarded: **{len(filings)}**")
    lines.append(f"- Run verdict totals: {dict(verdict_totals)}")
    lines.append(f"- Dashboard-recovered totals: {dict(dashboard_totals)} "
                 f"(**{'AGREE' if not any(g.startswith('TOTALS') for g in gate_failures) else 'DISAGREE'}** "
                 f"with the run — REPORT_LATEST's established numbers)")
    lines.append(f"- Known-decline filers checked (STATUS.md item 2): {KNOWN_DECLINE_FILERS} — "
                 f"must show declines AND classify them explained")
    lines.append(f"- Agreement-gate failures: **{len(gate_failures)}**"
                 + (f" — {gate_failures}" if gate_failures else ""))
    lines.append("")
    lines.append("## Per-filer dashboard\n")
    lines.append("| Ticker | Verification (weighted) | Evidence coverage % | "
                 "Disclosure quality % | Consistency % | Restatement |")
    lines.append("|---|---|---|---|---|---|")
    lines.extend(rows)
    lines.append("")
    lines.append("## Honest boundary\n")
    lines.append("- Presentation only: every number is an aggregation of verdicts, "
                 "evidence flags, XBRL comparability gates, or disclosure-language "
                 "classifications that already existed upstream. No new verification.")
    lines.append("- Restatement Risk is UNASSESSED for all filers here because a "
                 "single-filing replay has no cross-document comparison. That is the "
                 "correct output, not a gap: no number is fabricated from absence.")
    lines.append("- Disclosure Quality is a JOINT property of filer disclosure and "
                 "extraction grounding, as its panel copy states.")
    lines.append("- Consistency penalizes only detected friction (dropped spans, "
                 "fallback tags); the per-share split_sensitive class flag is "
                 "surfaced, not penalized.")

    report = "\n".join(lines)
    print(report)
    if args.md:
        with open(args.md, "w") as fp:
            fp.write(report + "\n")
        print(f"\n[written to {args.md}]", file=sys.stderr)

    return 1 if gate_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
