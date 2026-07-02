"""
Phase 3 item 3 — AI Analyst Mode: measurement over the real 83-filer replay
run, plus (when a live key is reachable) live model narration through the
deterministic guards.

What this measures (and what it does NOT):

DETERMINISTIC SWEEP (no model, no key — the boundary itself):
- For every filer with claims in the newest replay run, ask three questions
  ("Does the balance sheet balance?", "Does EPS reconcile?", "Does cash tie
  out?") against the filer's REAL recorded verdicts.
- The answer path is exercised end-to-end with a deterministic citing stub
  (it answers by citing a provided fact and repeating one of its values), so
  "answered" outcomes also prove the post-model whitelist passes on real fact
  values.
- HARD GATES:
    1. Every (filer, question) whose topic has NO verified claim but >=1
       blocked claim must come back `refused_blocked` with
       `model_called=False` — the real-data version of the adversarial test,
       at scale (TSLA/META/KO cash among them).
    2. Zero `answered` outcomes for topics with zero verified facts.
    3. Every `answered` outcome carries >=1 citation naming a provided fact.
- NOT measured by the sweep: answer PROSE quality — the stub is deliberately
  trivial. The sweep measures the boundary, which is the point.

LIVE NARRATION (only when the configured provider is reachable):
- A handful of real questions on real filers through the REAL model, counting
  answered / rejected-by-guard outcomes. Plus one live adversarial case
  (TSLA cash) that must refuse BEFORE the model call — zero tokens spent.

Run:
    python benchmark/reliability/analyst_eval.py
    python benchmark/reliability/analyst_eval.py --live          # + live narration
    python benchmark/reliability/analyst_eval.py --md benchmark/reliability/ANALYST_REPORT.md
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

from aritiq.analyst import (  # noqa: E402
    ask_analyst,
    ledger_from_records,
)

RUNS_DIR = os.path.join(HERE, "cache", "runs")

QUESTIONS = {
    "balance_sheet_identity": "Does the balance sheet balance?",
    "eps_reconciliation": "Does the reported EPS reconcile with net income and share count?",
    "cash_flow_tie_out": "Does the cash flow statement tie out to balance sheet cash?",
}

LIVE_CASES = [
    ("AAPL", "Does the balance sheet balance?"),
    ("AAPL", "Does the reported EPS reconcile with net income and share count?"),
    ("JPM", "Does the balance sheet balance?"),
    ("PLTR", "Does the reported EPS reconcile with net income and share count?"),
    # the live adversarial: TSLA's cash tie-out is INSUFFICIENT_EVIDENCE in the
    # replay run, so this must refuse BEFORE any model call (zero tokens).
    ("TSLA", "Does the cash flow statement tie out to balance sheet cash?"),
]


def _load_env():
    env_path = os.path.join(REPO, ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _latest_replay_run() -> dict:
    candidates = sorted(glob.glob(os.path.join(RUNS_DIR, "run_*.json")),
                        key=os.path.getmtime, reverse=True)
    for p in candidates:
        d = json.load(open(p))
        if d.get("schema") == "aritiq.reliability.run/v1" and d.get("mode") == "replay":
            d["_path"] = p
            return d
    raise SystemExit("no replay run found")


def _citing_stub(system_prompt: str, user_prompt: str) -> str:
    """Deterministic stand-in model: cite the first provided fact and repeat
    one of its values. Exists to exercise the FULL answer path (including the
    whitelist) without a model."""
    import re
    m = re.search(r"(F\d+) \[[^\]]+\]:.*?values: ([-\d.]+)", user_prompt)
    if not m:
        return '[{"answer": "The facts provided are not sufficient.", "citations": []}]'
    fid, val = m.group(1), m.group(2)
    return json.dumps([{
        "answer": f"Yes — the verified check passed; key value {val} [{fid}].",
        "citations": [fid],
    }])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also run live narration")
    ap.add_argument("--md", help="write a markdown report to this path")
    args = ap.parse_args()

    run = _latest_replay_run()
    filings = [f for f in run["filings"] if f.get("claims")]

    gate_failures: List[str] = []
    outcomes: Counter = Counter()
    refusal_statuses: Counter = Counter()
    adversarial_refusals = 0
    expected_adversarial = 0
    rows: List[str] = []

    for f in filings:
        tk = f["ticker"]
        records = f["claims"]
        ledger = ledger_from_records(records)
        cell = {}
        for topic, question in QUESTIONS.items():
            has_verified = any(r.get("verdict") == "VERIFIED"
                               and (r.get("rule_name") == topic) for r in records)
            has_blocked = any(r.get("verdict") != "VERIFIED"
                              and (r.get("rule_name") == topic) for r in records)

            out = ask_analyst(question, ledger, complete_fn=_citing_stub)
            outcomes[out.mode] += 1
            cell[topic] = out.mode

            # Gate 1: blocked-only topic must refuse pre-model.
            if not has_verified and has_blocked:
                expected_adversarial += 1
                if out.mode == "refused_blocked" and out.model_called is False:
                    adversarial_refusals += 1
                    for b in out.blocking:
                        refusal_statuses[b["status"]] += 1
                else:
                    gate_failures.append(
                        f"{tk}/{topic}: expected pre-model refusal, got "
                        f"{out.mode} (model_called={out.model_called})")
            # Gate 2: no answers out of thin air.
            if out.mode == "answered" and not has_verified:
                gate_failures.append(
                    f"{tk}/{topic}: answered with zero verified {topic} claims")
            # Gate 3: answers must cite.
            if out.mode == "answered" and not out.citations:
                gate_failures.append(f"{tk}/{topic}: answered without citations")

        rows.append(f"| {tk} | {cell.get('balance_sheet_identity', '-')} "
                    f"| {cell.get('eps_reconciliation', '-')} "
                    f"| {cell.get('cash_flow_tie_out', '-')} |")

    # ---- live narration --------------------------------------------------
    live_lines: List[str] = []
    if args.live:
        _load_env()
        by_ticker = {f["ticker"]: f["claims"] for f in filings}
        try:
            from aritiq.analyst import _default_complete_fn
            live_fn = _default_complete_fn()
        except Exception as e:
            live_fn = None
            live_lines.append(f"- live narration UNAVAILABLE: {type(e).__name__}: {e}")
        if live_fn:
            for tk, question in LIVE_CASES:
                ledger = ledger_from_records(by_ticker[tk])
                try:
                    out = ask_analyst(question, ledger, complete_fn=live_fn)
                except Exception as e:
                    live_lines.append(f"- {tk}: PROVIDER ERROR {type(e).__name__}: "
                                      f"{str(e)[:120]}")
                    continue
                ans = (out.answer or "").replace("\n", " ")[:140]
                live_lines.append(
                    f"- {tk} — {question!r} → **{out.mode}** "
                    f"(model_called={out.model_called}"
                    + (f", citations={out.citations}" if out.citations else "")
                    + (f"): “{ans}”" if ans else f"): {out.guard[:140]}"))
                if tk == "TSLA" and (out.mode != "refused_blocked" or out.model_called):
                    gate_failures.append(
                        "LIVE adversarial (TSLA cash): expected pre-model refusal, "
                        f"got {out.mode} model_called={out.model_called}")

    lines = []
    lines.append("# AI Analyst Mode — measurement report\n")
    lines.append(f"Generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
                 f"from replay run `{os.path.basename(run['_path'])}` "
                 f"({len(filings)} filers, {len(filings) * len(QUESTIONS)} "
                 f"question/filer pairs).\n")
    lines.append("## Deterministic boundary sweep (no model needed)\n")
    lines.append(f"- Outcomes: {dict(outcomes)}")
    lines.append(f"- Blocked-only topics correctly refused pre-model: "
                 f"**{adversarial_refusals}/{expected_adversarial}** "
                 f"(the at-scale adversarial test; every one is a real filer whose "
                 f"only relevant verdicts did not pass verification)")
    lines.append(f"- Refusals named these blocking statuses: {dict(refusal_statuses)}")
    lines.append(f"- Hard-gate failures: **{len(gate_failures)}**"
                 + (f" — {gate_failures}" if gate_failures else ""))
    if args.live:
        lines.append("\n## Live narration (real model through the same guards)\n")
        lines.extend(live_lines or ["- (no live cases ran)"])
    lines.append("")
    lines.append("## Per-filer outcomes\n")
    lines.append("| Ticker | balance sheet Q | EPS Q | cash Q |")
    lines.append("|---|---|---|---|")
    lines.extend(rows)
    lines.append("")
    lines.append("## Honest boundary\n")
    lines.append("- The sweep proves the BOUNDARY (refuse on blocked, cite on answer, "
                 "whitelist on numbers) over real verdicts. The stub's prose is "
                 "trivial by design; prose quality is a model property, not a "
                 "guarantee this system makes.")
    lines.append("- `answered` here means the topic had verified facts and the cited "
                 "answer passed the whitelist — not that the answer is insightful.")
    lines.append("- Relevance matching is deterministic keyword/overlap (v1); a "
                 "question phrased entirely without topic words would refuse as "
                 "no-data rather than risk a wrong route. That failure mode is "
                 "closed-world by construction.")

    report = "\n".join(lines)
    print(report)
    if args.md:
        with open(args.md, "w") as fp:
            fp.write(report + "\n")
        print(f"\n[written to {args.md}]", file=sys.stderr)

    return 1 if gate_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
