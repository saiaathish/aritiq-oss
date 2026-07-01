"""Replay MD&A prose-direction claims against deterministic XBRL movement."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.core.schema import Claim, Operation, TrendDir  # noqa: E402
from aritiq.core.verify import verify_claim  # noqa: E402
from aritiq.edgar.xbrl_history import ConceptSeries  # noqa: E402


GOLD_PATH = os.path.join(REPO, "benchmark", "mda_xbrl_gold.json")


@dataclass
class MdaReplayResult:
    id: str
    metric: str
    direction: str
    actual_percent_change: float
    status: str
    expected_status: Optional[str]
    passed: Optional[bool]
    explanation: str


def _trend_dir(value: str) -> TrendDir:
    v = (value or "").strip().lower()
    if v == "up":
        return TrendDir.UP
    if v == "down":
        return TrendDir.DOWN
    if v == "flat":
        return TrendDir.FLAT
    raise ValueError(f"unknown direction {value!r}")


def percent_change(prior: float, current: float) -> float:
    if prior == 0:
        raise ValueError("prior value zero; percent change undefined")
    return (current - prior) / abs(prior) * 100.0


def build_mda_xbrl_claim(
    *,
    metric: str,
    direction: str,
    excerpt: str,
    prior_value: float,
    current_value: float,
    flat_band_pct: float = 2.0,
) -> Claim:
    pct = percent_change(prior_value, current_value)
    return Claim(
        claim_text=excerpt,
        operation=Operation.MDA_XBRL_CONSISTENCY,
        stated_value=None,
        trend_dir=_trend_dir(direction),
        params={
            "metric": metric,
            "actual_percent_change": pct,
            "flat_band_pct": flat_band_pct,
            "source": "mda_direction_vs_xbrl_replay",
        },
        source_text=excerpt,
    )


def build_mda_xbrl_claim_from_series(
    *,
    metric: str,
    direction: str,
    excerpt: str,
    series: ConceptSeries,
    flat_band_pct: float = 2.0,
) -> Claim:
    if len(series.points) < 2:
        return Claim(
            claim_text=excerpt,
            operation=Operation.MDA_XBRL_CONSISTENCY,
            stated_value=None,
            trend_dir=_trend_dir(direction),
            params={"metric": metric, "flat_band_pct": flat_band_pct},
            source_text=excerpt,
        )
    prior = series.points[-2].value
    current = series.points[-1].value
    return build_mda_xbrl_claim(
        metric=metric,
        direction=direction,
        excerpt=excerpt,
        prior_value=prior,
        current_value=current,
        flat_band_pct=flat_band_pct,
    )


def run_gold_replay(path: str = GOLD_PATH) -> Dict[str, object]:
    cases = json.load(open(path))
    results: List[MdaReplayResult] = []
    for case in cases:
        claim = build_mda_xbrl_claim(
            metric=case["metric"],
            direction=case["direction"],
            excerpt=case["excerpt"],
            prior_value=float(case["prior_value"]),
            current_value=float(case["current_value"]),
            flat_band_pct=float(case.get("flat_band_pct", 2.0)),
        )
        r = verify_claim(claim)
        expected = case.get("expected_status")
        results.append(MdaReplayResult(
            id=case["id"],
            metric=case["metric"],
            direction=case["direction"],
            actual_percent_change=round(claim.params["actual_percent_change"], 4),
            status=r.status.value,
            expected_status=expected,
            passed=None if expected is None else r.status.value == expected,
            explanation=r.explanation,
        ))
    return {
        "schema": "aritiq.mda_xbrl_replay/v1",
        "n_cases": len(results),
        "passed": sum(1 for r in results if r.passed is True),
        "failed": sum(1 for r in results if r.passed is False),
        "results": [r.__dict__ for r in results],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay MD&A-vs-XBRL gold cases")
    ap.add_argument("--gold", default=GOLD_PATH)
    args = ap.parse_args()
    out = run_gold_replay(args.gold)
    print(json.dumps(out, indent=2))
    if out["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
