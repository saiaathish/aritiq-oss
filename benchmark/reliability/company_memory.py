"""Measure Phase 2 item 5: deterministic multi-filing company memory.

Run:
    python benchmark/reliability/company_memory.py
    python benchmark/reliability/company_memory.py AAPL NVDA MSFT --md benchmark/COMPANY_MEMORY_REPORT.md

Uses cached SEC companyfacts via aritiq.edgar.xbrl_history. No model calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.edgar.company_memory import (  # noqa: E402
    DEFAULT_MEMORY_CONCEPTS,
    build_company_memory,
)


def load_tickers() -> list[str]:
    path = os.path.join(HERE, "filing_set.json")
    data = json.load(open(path))
    return [x["ticker"] for x in data["filings"]]


def main() -> int:
    ap = argparse.ArgumentParser(description="company-memory measurement")
    ap.add_argument("tickers", nargs="*", help="tickers to measure; default filing_set.json")
    ap.add_argument("--concept", action="append", dest="concepts", help="concept to include; repeatable")
    ap.add_argument("--md", default=None, help="write markdown summary")
    ap.add_argument("--no-cache", action="store_true", help="allow network fetches")
    args = ap.parse_args()

    tickers = args.tickers or load_tickers()
    concepts = tuple(args.concepts or DEFAULT_MEMORY_CONCEPTS)
    rows = []
    signal_counts = Counter()
    companies_with_series = 0
    companies_with_signals = 0
    total_metric_series = 0
    total_points = 0

    for ticker in tickers:
        mem = build_company_memory(ticker, concepts=concepts, use_cache=not args.no_cache)
        usable = [m for m in mem.metrics if m.n_points >= 2]
        signals = mem.signals
        if usable:
            companies_with_series += 1
        if signals:
            companies_with_signals += 1
        total_metric_series += len(usable)
        total_points += sum(m.n_points for m in usable)
        for sig in signals:
            signal_counts[sig.signal] += 1
        rows.append(
            {
                "ticker": mem.ticker,
                "usable_metrics": len(usable),
                "points": sum(m.n_points for m in usable),
                "signals": len(signals),
                "signal_types": sorted({s.signal for s in signals}),
                "examples": [
                    {
                        "concept": m.concept,
                        "tag": m.tag_used,
                        "n_points": m.n_points,
                        "latest_yoy": m.latest_yoy_change_pct,
                        "signals": [s.signal for s in m.signals],
                    }
                    for m in usable[:5]
                ],
            }
        )
        types = ",".join(rows[-1]["signal_types"]) or "-"
        print(
            f"[ok] {mem.ticker:6} metrics={len(usable):2} "
            f"points={rows[-1]['points']:3} signals={len(signals):2} {types}"
        )

    print("\n" + "=" * 72)
    print(f" COMPANY MEMORY RESULTS over {len(tickers)} filers")
    print("=" * 72)
    print(f" companies with usable multi-year series: {companies_with_series}/{len(tickers)}")
    print(f" usable metric series: {total_metric_series}")
    print(f" total cross-year points: {total_points}")
    print(f" companies with deterministic comparability signals: {companies_with_signals}")
    print(f" signal counts: {dict(signal_counts)}")
    print(" boundary: deterministic XBRL gates only; no footnote-language read.")

    ok = companies_with_series > 0 and total_metric_series > 0 and companies_with_signals > 0

    if args.md:
        with open(args.md, "w") as fh:
            fh.write("# company-memory measurement (Phase 2, item 5)\n\n")
            fh.write("Cached SEC companyfacts only; no model calls.\n\n")
            fh.write(f"- Filers measured: **{len(tickers)}**\n")
            fh.write(f"- Companies with usable multi-year series: **{companies_with_series}/{len(tickers)}**\n")
            fh.write(f"- Usable metric series: **{total_metric_series}**\n")
            fh.write(f"- Total cross-year points: **{total_points}**\n")
            fh.write(f"- Companies with deterministic comparability signals: **{companies_with_signals}**\n")
            fh.write(f"- Signal counts: **{dict(signal_counts)}**\n")
            fh.write("- Boundary: deterministic XBRL gates only; no footnote-language read.\n\n")
            fh.write("| Ticker | Usable metrics | Points | Signals | Signal types |\n")
            fh.write("|---|---:|---:|---:|---|\n")
            for row in rows:
                fh.write(
                    f"| {row['ticker']} | {row['usable_metrics']} | {row['points']} | "
                    f"{row['signals']} | {', '.join(row['signal_types']) or '-'} |\n"
                )
        print(f" markdown: {args.md}")

    print("-" * 72)
    print(f" RESULT: {'PASS' if ok else 'FAIL'} — usable series plus real deterministic signals")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
