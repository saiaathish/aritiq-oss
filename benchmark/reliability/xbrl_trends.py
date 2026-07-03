"""
Feature 1 — multi-period trend verification through the EXISTING, unmodified verifier.

This builds Claim objects whose operands are XBRL-grounded values from MULTIPLE
reporting periods (via aritiq.edgar.xbrl_history) and runs them through the SAME
check_trend_direction / check_superlative / check_consecutive_count functions and
the SAME percent_change arithmetic the single-period path uses. No new verifier
logic; no change to aritiq/core.

The claims tested here are GENERATED FROM THE REAL DATA (compute the actual YoY %
from two real periods, then assert it and confirm Aritiq VERIFIES it; likewise for
"revenue rose N years in a row" using the real run length). This proves the
mechanism end-to-end on real numbers before worrying about extracting such claims
from prose. It also plants NEGATIVE controls (assert a wrong direction / wrong
count) to confirm the verifier returns WRONG_MATH, not a false VERIFIED.

Comparability gates are honoured: a per-share (split-sensitive) series or a series
that had to drop non-comparable spans is reported, and split-sensitive series are
NOT used for confident percent_change (they route to a declared skip) — never a
silent wrong comparison.

Run:
    python benchmark/reliability/xbrl_trends.py                  # default ticker set
    python benchmark/reliability/xbrl_trends.py AAPL NVDA MSFT   # subset
    python benchmark/reliability/xbrl_trends.py --md trends_report.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.core.schema import (  # noqa: E402
    Claim, Operation, Operand, OperandSource, TrendDir, Superlative, VerificationStatus,
)
from aritiq.core.verify import verify_claim  # noqa: E402
from aritiq.edgar.xbrl_history import get_concept_series, ConceptSeries  # noqa: E402

FILING_SET = os.path.join(HERE, "filing_set.json")
RUNS_DIR = os.path.join(HERE, "cache", "runs")

# Concepts we build trend claims over (all $-denominated, split-INsensitive).
TREND_CONCEPTS = ["revenue", "net_income"]

# A reasonable default window: verify claims over the most recent N annual points.
DEFAULT_WINDOW = 5


def _op(value: float, category: str, source_text: str) -> Operand:
    return Operand(value=value, source=OperandSource.GROUNDED,
                   category=category, source_text=source_text)


def _series_operands(window: List[Tuple[str, float]]) -> List[Operand]:
    return [_op(v, f"period:{p}", f"XBRL fact @ {p}") for p, v in window]


def build_trend_claims(s: ConceptSeries, window: int = DEFAULT_WINDOW) -> List[Claim]:
    """Build multi-period claims from a real XBRL series, generated from the data.

    Each claim's asserted answer is COMPUTED FROM THE REAL VALUES, so a correct
    verifier must return VERIFIED. A negative-control variant asserts the opposite
    and must return WRONG_MATH. Split-sensitive series are excluded from
    percent_change (declared, not silently compared).
    """
    claims: List[Claim] = []
    pts = s.series[-window:]
    if len(pts) < 2:
        return claims
    concept = s.concept
    tick = s.ticker

    # ---- 1. percent_change: latest vs prior period (real YoY), reuses existing op.
    # Skip for split-sensitive per-share series (comparability gate).
    if not s.split_sensitive:
        (p_old, v_old), (p_new, v_new) = pts[-2], pts[-1]
        if v_old != 0:
            real_pct = (v_new - v_old) / v_old * 100.0
            claims.append(Claim(
                claim_text=f"[XBRL] {tick} {concept} {p_new} vs {p_old}: {real_pct:+.1f}%",
                operation=Operation.PERCENT_CHANGE, stated_value=round(real_pct, 2),
                operands=[_op(v_old, f"period:{p_old}", f"XBRL {concept} @ {p_old}"),
                          _op(v_new, f"period:{p_new}", f"XBRL {concept} @ {p_new}")],
                unit="%", source_text=f"XBRL {s.tag_used} two-period",
                params={"generated_from_real_data": True, "control": "positive"},
            ))
            # negative control: assert a value that is genuinely wrong
            claims.append(Claim(
                claim_text=f"[XBRL neg-ctrl] {tick} {concept} pct wrong",
                operation=Operation.PERCENT_CHANGE, stated_value=round(real_pct + 25.0, 2),
                operands=[_op(v_old, f"period:{p_old}", ""), _op(v_new, f"period:{p_new}", "")],
                unit="%", source_text="negative control",
                params={"control": "negative"},
            ))

    # ---- 2. trend_direction over the window (real observed direction), reuses op.
    vals = [v for _, v in pts]
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    if all(d > 0 for d in diffs):
        real_dir = TrendDir.UP
    elif all(d < 0 for d in diffs):
        real_dir = TrendDir.DOWN
    else:
        real_dir = None  # mixed — no monotone claim to make (honest: skip)
    if real_dir is not None:
        claims.append(Claim(
            claim_text=f"[XBRL] {tick} {concept} trend over {len(pts)} yrs: {real_dir.value}",
            operation=Operation.TREND_DIRECTION, stated_value=None,
            operands=_series_operands(pts), trend_dir=real_dir,
            params={"series": pts, "control": "positive"},
            source_text=f"XBRL {s.tag_used} window",
        ))
        # negative control: assert the opposite direction
        opp = TrendDir.DOWN if real_dir == TrendDir.UP else TrendDir.UP
        claims.append(Claim(
            claim_text=f"[XBRL neg-ctrl] {tick} {concept} trend claimed {opp.value}",
            operation=Operation.TREND_DIRECTION, stated_value=None,
            operands=_series_operands(pts), trend_dir=opp,
            params={"series": pts, "control": "negative"},
        ))

    # ---- 3. consecutive_count of trailing increases (real run length), reuses op.
    run = 0
    for d in reversed(diffs):
        if d > 0:
            run += 1
        else:
            break
    if run >= 1:
        claims.append(Claim(
            claim_text=f"[XBRL] {tick} {concept} rose {run} consecutive yrs",
            operation=Operation.CONSECUTIVE_COUNT, stated_value=float(run),
            operands=_series_operands(pts), trend_dir=TrendDir.UP,
            params={"series": pts, "control": "positive"},
            source_text=f"XBRL {s.tag_used} window",
        ))
        # negative control: overstate the run by 2
        claims.append(Claim(
            claim_text=f"[XBRL neg-ctrl] {tick} {concept} claimed {run+2} consec yrs",
            operation=Operation.CONSECUTIVE_COUNT, stated_value=float(run + 2),
            operands=_series_operands(pts), trend_dir=TrendDir.UP,
            params={"series": pts, "control": "negative"},
        ))

    # ---- 4. superlative: is the latest period the max over the window? (real).
    latest_period, latest_val = pts[-1]
    is_max = latest_val == max(v for _, v in pts)
    which = Superlative.MAX
    claims.append(Claim(
        claim_text=f"[XBRL] {tick} {concept} {latest_period} is{'' if is_max else ' NOT'} window max",
        operation=Operation.SUPERLATIVE, stated_value=None,
        operands=_series_operands(pts), superlative=which,
        params={"series": pts, "target_period": latest_period,
                "expected_verified": is_max, "control": "positive"},
        source_text=f"XBRL {s.tag_used} window",
    ))
    return claims


@dataclass
class TrendFilingResult:
    ticker: str
    concept_series: dict = field(default_factory=dict)   # concept -> {n_points, dropped, split}
    n_claims: int = 0
    verdicts: dict = field(default_factory=dict)
    control_check: dict = field(default_factory=dict)     # positive/negative correctness
    claims: List[dict] = field(default_factory=list)
    fetch_error: Optional[str] = None


def run_ticker(ticker: str, *, window: int = DEFAULT_WINDOW,
               use_cache: bool = True) -> TrendFilingResult:
    res = TrendFilingResult(ticker=ticker)
    vc = Counter()
    pos_ok = pos_total = neg_ok = neg_total = 0
    any_error = None
    for concept in TREND_CONCEPTS:
        s = get_concept_series(ticker, concept, use_cache=use_cache)
        if s.fetch_error:
            any_error = s.fetch_error
            continue
        res.concept_series[concept] = {
            "n_points": s.n_points, "dropped_noncomparable": s.dropped_noncomparable_spans,
            "split_sensitive": s.split_sensitive, "tag": s.tag_used,
        }
        for c in build_trend_claims(s, window=window):
            r = verify_claim(c)
            vc[r.status.value] += 1
            control = c.params.get("control")
            row = {"concept": concept, "op": c.operation.value,
                   "claim": c.claim_text, "verdict": r.status.value,
                   "control": control, "explanation": r.explanation[:140]}
            # Correctness of controls: positives should VERIFY, negatives should be
            # caught (WRONG_MATH). Superlative positives carry expected_verified.
            if control == "positive":
                pos_total += 1
                expect = c.params.get("expected_verified", True)
                want = VerificationStatus.VERIFIED if expect else VerificationStatus.WRONG_MATH
                row["control_pass"] = (r.status == want)
                pos_ok += int(row["control_pass"])
            elif control == "negative":
                neg_total += 1
                row["control_pass"] = (r.status == VerificationStatus.WRONG_MATH)
                neg_ok += int(row["control_pass"])
            res.claims.append(row)
    res.n_claims = len(res.claims)
    res.verdicts = dict(vc)
    res.control_check = {"positive_ok": pos_ok, "positive_total": pos_total,
                         "negative_ok": neg_ok, "negative_total": neg_total}
    if any_error and not res.concept_series:
        res.fetch_error = any_error
    return res


def load_tickers() -> List[str]:
    return [x["ticker"] for x in json.load(open(FILING_SET))["filings"]]


def main():
    ap = argparse.ArgumentParser(description="XBRL multi-period trend verification")
    ap.add_argument("tickers", nargs="*", help="tickers (default: filing set)")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--md", default=None)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    tickers = args.tickers or load_tickers()
    results: List[TrendFilingResult] = []
    total = Counter()
    pos_ok = pos_total = neg_ok = neg_total = 0
    filers_with_series = 0
    for tk in tickers:
        r = run_ticker(tk, window=args.window, use_cache=not args.no_cache)
        results.append(r)
        if r.fetch_error:
            print(f"  [FETCH-FAIL] {tk:6} {r.fetch_error[:50]}")
            continue
        if r.concept_series:
            filers_with_series += 1
        for k, n in r.verdicts.items():
            total[k] += n
        cc = r.control_check
        pos_ok += cc["positive_ok"]; pos_total += cc["positive_total"]
        neg_ok += cc["negative_ok"]; neg_total += cc["negative_total"]
        vs = " ".join(f"{k}={v}" for k, v in sorted(r.verdicts.items()))
        print(f"  [{'ok':>9}] {tk:6} claims={r.n_claims:2} "
              f"pos={cc['positive_ok']}/{cc['positive_total']} "
              f"neg={cc['negative_ok']}/{cc['negative_total']}  {vs}")

    print("\n" + "=" * 72)
    print(f"  MULTI-PERIOD TREND RESULTS over {len(tickers)} filers "
          f"({filers_with_series} with usable series)")
    print("=" * 72)
    print(f"  verdict totals: {dict(total)}")
    print(f"  POSITIVE controls (real claim -> should VERIFY): {pos_ok}/{pos_total}")
    print(f"  NEGATIVE controls (wrong claim -> should be caught): {neg_ok}/{neg_total}")
    completion = pos_ok / pos_total * 100 if pos_total else 0.0
    catch = neg_ok / neg_total * 100 if neg_total else 0.0
    print(f"  positive-control completion: {completion:.1f}%   "
          f"negative-control catch rate: {catch:.1f}%")
    fetch_fail = [r.ticker for r in results if r.fetch_error]
    if fetch_fail:
        print(f"  fetch failures ({len(fetch_fail)}): {', '.join(fetch_fail)}")

    os.makedirs(RUNS_DIR, exist_ok=True)
    out = os.path.join(RUNS_DIR, f"xbrl_trends_{int(time.time())}.json")
    json.dump({"schema": "aritiq.xbrl_trends.run/v1", "n_filers": len(tickers),
               "verdict_totals": dict(total),
               "positive_ok": pos_ok, "positive_total": pos_total,
               "negative_ok": neg_ok, "negative_total": neg_total,
               "results": [vars(r) for r in results]}, open(out, "w"), indent=2)
    print(f"\n  written: {out}")

    if args.md:
        with open(args.md, "w") as fh:
            fh.write("# Multi-period trend verification (XBRL-grounded)\n\n")
            fh.write(f"- Filers: {len(tickers)} ({filers_with_series} with usable multi-year series)\n")
            fh.write(f"- Verdict totals: `{dict(total)}`\n")
            fh.write(f"- Positive controls (real claims that must VERIFY): **{pos_ok}/{pos_total}** "
                     f"({completion:.1f}%)\n")
            fh.write(f"- Negative controls (wrong claims that must be caught as WRONG_MATH): "
                     f"**{neg_ok}/{neg_total}** ({catch:.1f}%)\n\n")
            fh.write("| Ticker | Series (concept: points, dropped) | Claims | pos | neg |\n")
            fh.write("|---|---|---|---|---|\n")
            for r in results:
                if r.fetch_error:
                    fh.write(f"| {r.ticker} | FETCH-FAIL | — | — | — |\n")
                    continue
                cs = "; ".join(f"{k}: {v['n_points']}pt/{v['dropped_noncomparable']}drop"
                               for k, v in r.concept_series.items())
                cc = r.control_check
                fh.write(f"| {r.ticker} | {cs} | {r.n_claims} | "
                         f"{cc['positive_ok']}/{cc['positive_total']} | "
                         f"{cc['negative_ok']}/{cc['negative_total']} |\n")
        print(f"  markdown: {args.md}")


if __name__ == "__main__":
    main()
