"""
System 3 (peer/anomaly layer) — MULTI-METRIC peer coverage across the 83-filer set.

WHY THIS EXISTS (what it adds over the net-margin peer comparison)
-----------------------------------------------------------------
`xbrl_peers.py` compares peers on ONE metric — net margin (NetIncome / Revenues) —
and correctly DECLINES the SIC classes where that metric is meaningless (REITs, banks,
insurers all tag a partial/idiosyncratic `Revenues` line). That left those large,
important sectors with no peer comparison at all.

This module closes that coverage gap by adding metrics whose operands those sectors
DO tag cleanly and comparably:

  * return_on_assets = NetIncomeLoss / Assets        (comparable incl. financials/REITs)
  * debt_ratio       = Liabilities / Assets          (leverage; comparable broadly)
  * net_margin       = NetIncomeLoss / Revenues      (operating cos only; excluded for
                                                       the partial-revenue SIC classes)

Each metric carries an explicit comparability rule (which SIC classes it is valid for)
and a sanity band, in the same honest spirit as the net-margin gates. Within each SIC
peer group, per metric, a filer more than `OUTLIER_STDDEV` population standard
deviations from the group mean is flagged as a REVIEW CUE — never a verdict. A z-score
outlier means "look at this," not "this is wrong."

Everything reuses `aritiq.edgar.xbrl_history` (grounded, multi-period) and
`aritiq.edgar.sic` (peer grouping). No `aritiq/core` or `aritiq/edgar` code is
modified; no model SDK is imported. This module does NOT import xbrl_peers.py, so the
two peer layers evolve independently.

Run:
    python benchmark/reliability/peer_metrics.py                 # all viable SIC groups
    python benchmark/reliability/peer_metrics.py --sic 6021      # one SIC group
    python benchmark/reliability/peer_metrics.py --md peer_metrics_report.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.edgar.xbrl_history import get_concept_series  # noqa: E402
from aritiq.edgar.sic import group_by_sic, SicInfo  # noqa: E402

FILING_SET = os.path.join(HERE, "filing_set.json")
RUNS_DIR = os.path.join(HERE, "cache", "runs")

PERIOD_TOLERANCE_DAYS = 200     # peers' aligned periods must fall within this window
OUTLIER_STDDEV = 2.0            # review-cue cutoff (population stddev), NOT a verdict
MIN_PEERS = 3                   # need >= this many comparable peers to compare


# SIC classes where NetIncome/Revenues is not a defensible margin (partial revenue
# tag). Mirrors the rationale in xbrl_peers.py but kept local so this module has no
# dependency on that file. Only net_margin is gated by this; ROA/leverage are not,
# because Assets/Liabilities are tagged comparably by these filers.
_NONCOMPARABLE_MARGIN_SICS = frozenset({"6798", "6331", "6021", "6311", "6141", "6162"})


@dataclass(frozen=True)
class Metric:
    name: str
    numerator: str          # concept name in xbrl_history.CONCEPT_TAGS
    denominator: str
    as_percent: bool
    higher_is_better: Optional[bool]   # None => "neither" (e.g. leverage: context-dependent)
    sane_lo: float
    sane_hi: float
    excluded_sics: frozenset
    note: str


METRICS: Dict[str, Metric] = {
    "net_margin": Metric(
        "net_margin", "net_income", "revenue", True, True, -100.0, 100.0,
        _NONCOMPARABLE_MARGIN_SICS,
        "NetIncome / Revenues; excluded for REIT/bank/insurer SICs (partial revenue tag)."),
    "return_on_assets": Metric(
        "return_on_assets", "net_income", "assets", True, True, -60.0, 60.0,
        frozenset(),
        "NetIncome / Assets; comparable across sectors including financials and REITs."),
    "debt_ratio": Metric(
        "debt_ratio", "liabilities", "assets", True, None, 0.0, 200.0,
        frozenset(),
        "Liabilities / Assets (leverage); >100% implies negative equity (flagged)."),
}


def _iso(d: str) -> _dt.date:
    return _dt.date.fromisoformat(d)


@dataclass
class FilerMetric:
    ticker: str
    period_end: Optional[str] = None
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    value: Optional[float] = None
    included: bool = False
    exclude_reason: Optional[str] = None
    outlier: bool = False
    zscore: Optional[float] = None


def compute_filer_metric(ticker: str, metric: Metric, *, use_cache: bool = True) -> FilerMetric:
    """Compute one metric for one filer at the latest period where BOTH operands are
    grounded for the SAME period_end. No interpolation — a missing operand yields a
    FilerMetric with value None and a reason."""
    fm = FilerMetric(ticker=ticker)
    num = get_concept_series(ticker, metric.numerator, use_cache=use_cache)
    den = get_concept_series(ticker, metric.denominator, use_cache=use_cache)
    if not num.n_points or not den.n_points:
        fm.exclude_reason = f"missing {metric.numerator} or {metric.denominator} series"
        return fm
    num_map = {p.period_end: p.value for p in num.points}
    common = [p.period_end for p in den.points if p.period_end in num_map]
    if not common:
        fm.exclude_reason = "no common period for numerator and denominator"
        return fm
    pe = sorted(common)[-1]
    d = {p.period_end: p.value for p in den.points}[pe]
    n = num_map[pe]
    fm.period_end = pe
    fm.numerator = n
    fm.denominator = d
    if d != 0:
        fm.value = (n / d * 100.0) if metric.as_percent else (n / d)
    return fm


def _population_stddev(vals: List[float]) -> Tuple[float, float]:
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return mean, math.sqrt(var)


def gate_and_flag(metrics: List[FilerMetric], metric: Metric) -> Tuple[List[FilerMetric], List[str]]:
    """Apply period-alignment + sanity gating, then flag z-score outliers (review
    cues). Mutates each FilerMetric's included/exclude_reason/outlier/zscore."""
    notes: List[str] = []
    dated = [m for m in metrics if m.value is not None and m.period_end]
    if not dated:
        return [], ["no filer had a groundable value for this metric"]
    latest = max(_iso(m.period_end) for m in dated)
    for m in metrics:
        if m.value is None:
            m.included = False
            m.exclude_reason = m.exclude_reason or "no groundable value"
            continue
        age = (latest - _iso(m.period_end)).days
        if age > PERIOD_TOLERANCE_DAYS:
            m.included = False
            m.exclude_reason = f"period {m.period_end} is {age}d behind group latest — stale"
            continue
        if not (metric.sane_lo <= m.value <= metric.sane_hi):
            m.included = False
            m.exclude_reason = (f"{metric.name} {m.value:.1f} outside sanity band "
                                f"[{metric.sane_lo:g},{metric.sane_hi:g}] — non-comparable")
            continue
        m.included = True
    included = [m for m in metrics if m.included]
    if len(included) >= MIN_PEERS:
        mean, sd = _population_stddev([m.value for m in included])
        for m in included:
            if sd > 0:
                m.zscore = round((m.value - mean) / sd, 2)
                m.outlier = abs(m.zscore) >= OUTLIER_STDDEV
        n_out = sum(1 for m in included if m.outlier)
        notes.append(f"group mean={mean:.2f} stddev={sd:.2f}; {n_out} outlier(s) "
                     f"beyond {OUTLIER_STDDEV:g}σ (review cues, not verdicts)")
    return included, notes


@dataclass
class GroupMetricResult:
    sic: str
    sic_description: str
    metric: str
    all_members: List[str]
    included: List[dict] = field(default_factory=list)
    excluded: List[dict] = field(default_factory=list)
    outliers: List[dict] = field(default_factory=list)
    decline_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def compare_group_metric(sic: str, members: List[SicInfo], metric: Metric, *,
                         use_cache: bool = True) -> GroupMetricResult:
    desc = members[0].sic_description if members else ""
    tickers = [m.ticker for m in members]
    res = GroupMetricResult(sic=sic, sic_description=desc, metric=metric.name,
                            all_members=tickers)
    if sic in metric.excluded_sics:
        res.decline_reason = (f"{metric.name} not comparable for SIC {sic}: {metric.note}")
        return res
    fms = [compute_filer_metric(t, metric, use_cache=use_cache) for t in tickers]
    included, notes = gate_and_flag(fms, metric)
    res.notes.extend(notes)
    res.included = [{"ticker": m.ticker, "period_end": m.period_end,
                     "value": round(m.value, 2), "zscore": m.zscore, "outlier": m.outlier}
                    for m in included]
    res.excluded = [{"ticker": m.ticker, "reason": m.exclude_reason}
                    for m in fms if not m.included]
    res.outliers = [{"ticker": m.ticker, "value": round(m.value, 2), "zscore": m.zscore}
                    for m in included if m.outlier]
    if len(included) < MIN_PEERS:
        res.decline_reason = (f"only {len(included)} comparable peer(s) (need >= {MIN_PEERS})")
    return res


def viable_groups(use_cache: bool = True) -> Dict[str, List[SicInfo]]:
    tickers = [x["ticker"] for x in json.load(open(FILING_SET))["filings"]]
    groups = group_by_sic(tickers, use_cache=use_cache)
    return {k: v for k, v in groups.items() if k != "UNKNOWN" and len(v) >= MIN_PEERS}


def run_all(use_cache: bool = True, only_sic: Optional[str] = None) -> dict:
    groups = viable_groups(use_cache=use_cache)
    if only_sic:
        groups = {k: v for k, v in groups.items() if k == only_sic}
    out = {"metrics": {}, "coverage": {}}
    for mname, metric in METRICS.items():
        results = []
        compared = 0
        for sic, members in sorted(groups.items(), key=lambda x: -len(x[1])):
            r = compare_group_metric(sic, members, metric, use_cache=use_cache)
            results.append(r)
            if r.decline_reason is None:
                compared += 1
        out["metrics"][mname] = results
        out["coverage"][mname] = {"viable_groups": len(groups), "compared": compared}
    return out


def main():
    ap = argparse.ArgumentParser(description="Multi-metric peer coverage + anomaly scan")
    ap.add_argument("--sic", default=None, help="only this SIC code")
    ap.add_argument("--md", default=None)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    use_cache = not args.no_cache

    data = run_all(use_cache=use_cache, only_sic=args.sic)

    print("=" * 76)
    print("  MULTI-METRIC PEER COVERAGE + ANOMALY SCAN")
    print("=" * 76)
    for mname, cov in data["coverage"].items():
        print(f"\n  METRIC: {mname}  — comparable in {cov['compared']}/{cov['viable_groups']} "
              f"viable SIC groups")
        for r in data["metrics"][mname]:
            if r.decline_reason:
                print(f"    [decline] SIC {r.sic} {r.sic_description[:26]:26} {r.decline_reason[:44]}")
            else:
                out = ", ".join(f"{o['ticker']}({o['value']}, z={o['zscore']})" for o in r.outliers)
                print(f"    [ok {len(r.included):2}] SIC {r.sic} {r.sic_description[:26]:26} "
                      f"outliers: {out or 'none'}")

    # Coverage headline: net_margin alone vs +ROA +leverage
    nm = data["coverage"]["net_margin"]["compared"]
    roa = data["coverage"]["return_on_assets"]["compared"]
    lev = data["coverage"]["debt_ratio"]["compared"]
    union_groups = set()
    for mname in METRICS:
        for r in data["metrics"][mname]:
            if r.decline_reason is None:
                union_groups.add(r.sic)
    print("\n" + "=" * 76)
    print(f"  COVERAGE EXPANSION: net_margin alone reaches {nm} SIC groups; adding "
          f"return_on_assets ({roa}) and debt_ratio ({lev})")
    print(f"  gives defensible peer comparison in {len(union_groups)} SIC groups total.")
    print("=" * 76)

    os.makedirs(RUNS_DIR, exist_ok=True)
    outp = os.path.join(RUNS_DIR, f"peer_metrics_{int(time.time())}.json")
    ser = {"schema": "aritiq.peer_metrics/v1", "coverage": data["coverage"],
           "metrics": {mn: [vars(r) for r in rs] for mn, rs in data["metrics"].items()}}
    json.dump(ser, open(outp, "w"), indent=2)
    print(f"\n  written: {outp}")

    if args.md:
        _write_md(data, args.md, union_groups)
        print(f"  markdown: {args.md}")


def _write_md(data: dict, path: str, union_groups) -> None:
    with open(path, "w") as fh:
        fh.write("# Multi-metric peer coverage + anomaly scan\n\n")
        fh.write("Adds return-on-assets and leverage to net-margin peer comparison so "
                 "the SIC classes where net margin is non-comparable (REITs, banks, "
                 "insurers) still get a defensible peer view. Outliers are z-score "
                 "**review cues (≥2σ), never verdicts**.\n\n")
        for mname, metric in METRICS.items():
            cov = data["coverage"][mname]
            fh.write(f"## {mname} — comparable in {cov['compared']}/{cov['viable_groups']} groups\n\n")
            fh.write(f"_{metric.note}_\n\n")
            fh.write("| SIC | Description | Peers | Outliers (value, z) |\n|---|---|---|---|\n")
            for r in data["metrics"][mname]:
                if r.decline_reason:
                    fh.write(f"| {r.sic} | {r.sic_description} | — | declined: {r.decline_reason} |\n")
                else:
                    out = ", ".join(f"{o['ticker']} ({o['value']}, z={o['zscore']})"
                                    for o in r.outliers) or "none"
                    fh.write(f"| {r.sic} | {r.sic_description} | {len(r.included)} | {out} |\n")
            fh.write("\n")
        fh.write(f"**Coverage:** union of the three metrics gives a defensible peer "
                 f"comparison in {len(union_groups)} SIC groups.\n")


if __name__ == "__main__":
    main()
