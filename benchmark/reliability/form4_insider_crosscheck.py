"""Factual Form 4 insider-flow vs corporate buyback cross-check.

This is not insider-trading detection. It only places two disclosed facts next
to each other: latest annual stock repurchase cash outflow and recent Form 4
reported acquisition/disposition share flow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.edgar.form4 import fetch_recent_form4_transactions  # noqa: E402
from aritiq.edgar.xbrl_history import get_concept_series  # noqa: E402


BUYBACK_TAGS = [
    "PaymentsForRepurchaseOfCommonStock",
    "PaymentsForRepurchaseOfCommonStockIncludingTaxWithholding",
    "PaymentsForRepurchaseOfEquity",
]


@dataclass
class InsiderCrosscheckResult:
    ticker: str
    buyback_tag: Optional[str]
    buyback_period_end: Optional[str]
    buyback_value: Optional[float]
    form4_transactions: int
    acquisition_shares: float
    disposition_shares: float
    other_shares: float
    net_disposition_shares: float
    status: str
    explanation: str


def latest_buyback(ticker: str, *, use_cache: bool = True) -> tuple[Optional[str], Optional[str], Optional[float]]:
    for tag in BUYBACK_TAGS:
        series = get_concept_series(ticker, tag, use_cache=use_cache)
        if series.n_points:
            point = series.points[-1]
            return tag, point.period_end, point.value
    return None, None, None


def crosscheck_ticker(
    ticker: str,
    *,
    form4_limit: int = 10,
    use_cache: bool = True,
) -> InsiderCrosscheckResult:
    tag, period_end, buyback_value = latest_buyback(ticker, use_cache=use_cache)
    txs = fetch_recent_form4_transactions(ticker, limit=form4_limit)
    acq = sum(t.shares for t in txs if t.direction == "acquisition")
    disp = sum(t.shares for t in txs if t.direction == "disposition")
    other = sum(t.shares for t in txs if t.direction == "other")
    net_disp = disp - acq

    if buyback_value is None:
        status = "INSUFFICIENT_EVIDENCE"
        explanation = "No stock-repurchase XBRL tag found in latest annual companyfacts series."
    elif not txs:
        status = "INSUFFICIENT_EVIDENCE"
        explanation = "No parseable recent Form 4 non-derivative transactions found."
    elif buyback_value > 0 and net_disp > 0:
        status = "FACTUAL_DIVERGENCE_REVIEW"
        explanation = (
            "Company reports stock repurchases while recent Form 4 flow is net "
            "share disposition. This is a neutral cross-reference, not a legal judgment."
        )
    else:
        status = "FACTUAL_CONTEXT"
        explanation = (
            "Buyback and recent Form 4 flow parsed; no net-disposition/buyback "
            "divergence surfaced by this narrow check."
        )

    return InsiderCrosscheckResult(
        ticker=ticker.upper(),
        buyback_tag=tag,
        buyback_period_end=period_end,
        buyback_value=buyback_value,
        form4_transactions=len(txs),
        acquisition_shares=acq,
        disposition_shares=disp,
        other_shares=other,
        net_disposition_shares=net_disp,
        status=status,
        explanation=explanation,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Form 4 insider-flow cross-check")
    ap.add_argument("tickers", nargs="*", default=["AAPL", "MSFT", "AMZN"])
    ap.add_argument("--form4-limit", type=int, default=10)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    results: List[InsiderCrosscheckResult] = []
    for ticker in args.tickers:
        results.append(crosscheck_ticker(
            ticker,
            form4_limit=args.form4_limit,
            use_cache=not args.no_cache,
        ))
    print(json.dumps({
        "schema": "aritiq.form4_insider_crosscheck/v1",
        "tickers": args.tickers,
        "results": [r.__dict__ for r in results],
    }, indent=2))


if __name__ == "__main__":
    main()
