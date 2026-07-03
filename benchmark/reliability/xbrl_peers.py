"""
Feature 2 — peer/sector comparison through the EXISTING, unmodified verifier.

Claims like "X has the highest net margin in its peer group" are a `superlative`
check (already in aritiq/core/rules.py) applied ACROSS COMPANIES instead of across
time periods for one company. The metric for every peer is computed with the SAME
XBRL grounding proven for a single company (aritiq.edgar.xbrl_history), and the
peer set is the company's SIC group (aritiq.edgar.sic) — the SEC's own industry
classification, reused rather than invented.

HONESTY — the two things that make cross-company comparison dangerous, and the gates:

  1. PERIOD ALIGNMENT. Two peers' latest filings may end on different dates. Comparing
     peer A's FY2025 margin to peer B's FY2019 margin (because B stopped tagging the
     denominator) is meaningless. We require every peer in a comparison to have BOTH
     operands grounded for a period ending within the SAME recent window (default: the
     max peer period_end, back `PERIOD_TOLERANCE_DAYS`). A peer outside the window is
     EXCLUDED and reported, never compared on a stale figure.

  2. METRIC COMPARABILITY. `net_margin = NetIncomeLoss / Revenues` is only meaningful
     when `Revenues` means the same thing across the group. For REITs and insurers the
     `Revenues` tag captures a partial/idiosyncratic top line (rental income only,
     premiums only), producing absurd margins (>100%). We apply a plausibility bound
     (`|margin| <= MARGIN_SANITY_BOUND`); a peer outside it is EXCLUDED as
     non-comparable and the reason is recorded. If fewer than 2 peers survive both
     gates, we DECLINE the comparison (INSUFFICIENT_EVIDENCE-equivalent) rather than
     crown a "best-in-class" over a group of one.

NAMED LIMITATION (surfaced on every result, not hidden): SIC codes are coarse — same
code ≠ true competitor. The SIC code + description travel with each comparison so a
reviewer sees exactly what "peer group" meant.

Run:
    python benchmark/reliability/xbrl_peers.py                 # all viable SIC groups
    python benchmark/reliability/xbrl_peers.py --sic 3674      # one SIC group
    python benchmark/reliability/xbrl_peers.py --md peers_report.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.core.schema import (  # noqa: E402
    Claim, Operation, Operand, OperandSource, Superlative, VerificationStatus,
)
from aritiq.core.verify import verify_claim  # noqa: E402
from aritiq.core.rules import check_superlative  # noqa: E402
from aritiq.edgar.xbrl_history import get_concept_series  # noqa: E402
from aritiq.edgar.sic import group_by_sic, SicInfo  # noqa: E402

FILING_SET = os.path.join(HERE, "filing_set.json")
RUNS_DIR = os.path.join(HERE, "cache", "runs")

PERIOD_TOLERANCE_DAYS = 200     # peers' latest periods must fall within this window
MARGIN_SANITY_BOUND = 100.0     # |net_margin%| must be <= this to be comparable
MIN_PEERS = 3                   # need at least this many comparable peers to compare
OUTLIER_STDDEV_THRESHOLD = 2.0  # conventional review-cue cutoff, not a verdict

# SIC classes where NetIncomeLoss / Revenues is NOT a defensible net margin because
# the `Revenues` tag captures an idiosyncratic / partial top line that differs across
# filers in the group. REITs tag rental income (not total revenue); insurers tag
# premiums (not total revenue); banks tag net interest income idiosyncratically.
# Observed directly in the data: REIT margins ranged 8%–15280% within one SIC code —
# not a spread of performance, a spread of what "Revenues" means. We decline
# net-margin comparison for these classes rather than crown a meaningless winner.
# This is a NAMED, DOCUMENTED limitation, surfaced on the result — not a silent skip.
_NONCOMPARABLE_MARGIN_SICS = {
    "6798": "REIT — `Revenues` tag captures partial rental income, not total revenue",
    "6331": "P&C insurer — `Revenues` tag captures premiums, not a comparable top line",
    "6021": "commercial bank — net interest income tagged idiosyncratically across filers",
    "6311": "life insurer — premium-based top line, not a comparable net-margin denominator",
    "6141": "personal credit — interest-income top line, not a comparable revenue base",
    "6162": "mortgage banker — gain-on-sale/interest top line, not a comparable revenue base",
}


def _iso(d: str) -> _dt.date:
    return _dt.date.fromisoformat(d)


@dataclass
class PeerMetric:
    ticker: str
    period_end: Optional[str] = None
    net_income: Optional[float] = None
    revenue: Optional[float] = None
    net_margin: Optional[float] = None
    included: bool = False
    exclude_reason: Optional[str] = None


def compute_peer_margins(tickers: List[str], *, use_cache: bool = True) -> List[PeerMetric]:
    """Compute net margin (NetIncomeLoss/Revenues) for each ticker at its latest
    period where BOTH are grounded for the SAME period_end. No gating yet — that is
    applied by `gate_peers` so the exclusion reasons are explicit and reported."""
    out: List[PeerMetric] = []
    for tk in tickers:
        pm = PeerMetric(ticker=tk)
        ni = get_concept_series(tk, "net_income", use_cache=use_cache)
        rev = get_concept_series(tk, "revenue", use_cache=use_cache)
        if not ni.n_points or not rev.n_points:
            pm.exclude_reason = "missing net_income or revenue series"
            out.append(pm)
            continue
        ni_map = {p.period_end: p.value for p in ni.points}
        common = [p.period_end for p in rev.points if p.period_end in ni_map]
        if not common:
            pm.exclude_reason = "no common period for NI and revenue"
            out.append(pm)
            continue
        pe = common[-1]
        r = dict((p.period_end, p.value) for p in rev.points)[pe]
        n = ni_map[pe]
        pm.period_end = pe
        pm.net_income = n
        pm.revenue = r
        if r != 0:
            pm.net_margin = n / r * 100.0
        out.append(pm)
    return out


def gate_peers(metrics: List[PeerMetric]) -> Tuple[List[PeerMetric], List[str]]:
    """Apply period-alignment and metric-plausibility gates. Returns
    (included_metrics, notes). Mutates each PeerMetric's included/exclude_reason."""
    notes: List[str] = []
    dated = [m for m in metrics if m.net_margin is not None and m.period_end]
    if not dated:
        return [], ["no peer had a groundable net margin"]
    latest = max(_iso(m.period_end) for m in dated)
    for m in metrics:
        if m.net_margin is None:
            m.included = False
            m.exclude_reason = m.exclude_reason or "no groundable net margin"
            continue
        age = (latest - _iso(m.period_end)).days
        if age > PERIOD_TOLERANCE_DAYS:
            m.included = False
            m.exclude_reason = (f"period {m.period_end} is {age}d behind peer group "
                                f"latest — stale, excluded")
            continue
        if abs(m.net_margin) > MARGIN_SANITY_BOUND:
            m.included = False
            m.exclude_reason = (f"net_margin {m.net_margin:.1f}% exceeds sanity bound "
                                f"±{MARGIN_SANITY_BOUND:.0f}% — Revenues tag likely "
                                f"partial (REIT/insurer); non-comparable, excluded")
            continue
        m.included = True
    included = [m for m in metrics if m.included]
    return included, notes


@dataclass
class PeerComparisonResult:
    sic: str
    sic_description: str
    all_members: List[str]
    included: List[dict] = field(default_factory=list)
    excluded: List[dict] = field(default_factory=list)
    winner: Optional[str] = None
    winner_margin: Optional[float] = None
    verdict: Optional[str] = None          # verifier verdict on the superlative claim
    outliers: List[dict] = field(default_factory=list)
    outlier_threshold_stddev: float = OUTLIER_STDDEV_THRESHOLD
    decline_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _op(value: float, category: str, source_text: str) -> Operand:
    return Operand(value=value, source=OperandSource.GROUNDED,
                   category=category, source_text=source_text)


def detect_margin_outliers(
    metrics: List[PeerMetric],
    *,
    threshold_stddev: float = OUTLIER_STDDEV_THRESHOLD,
) -> List[dict]:
    """Flag included peers more than N population stddevs from peer mean.

    N=2 is a conventional review-cue cutoff. It is not an accounting verdict,
    especially for small peer sets, so every result carries the peer count,
    mean, stddev, z-score, and threshold used.
    """
    included = [m for m in metrics if m.included and m.net_margin is not None]
    if len(included) < MIN_PEERS:
        return []
    values = [m.net_margin for m in included]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stddev = math.sqrt(variance)
    if stddev == 0:
        return []
    outliers = []
    for m in included:
        z_score = (m.net_margin - mean) / stddev
        if abs(z_score) > threshold_stddev:
            outliers.append({
                "ticker": m.ticker,
                "period_end": m.period_end,
                "net_margin": round(m.net_margin, 2),
                "peer_mean": round(mean, 2),
                "peer_stddev": round(stddev, 2),
                "z_score": round(z_score, 3),
                "threshold_stddev": threshold_stddev,
                "peer_count": len(included),
                "metric": "net_margin",
                "interpretation": (
                    "statistical outlier within the gated SIC peer group; "
                    "review cue, not an accounting verdict"
                ),
            })
    return outliers


def compare_sic_group(sic: str, members: List[SicInfo], *,
                      use_cache: bool = True) -> PeerComparisonResult:
    """Run the peer margin comparison for one SIC group through the existing verifier.

    Builds a `superlative` claim asserting the highest-margin peer is the window max,
    and verifies it via verify_claim (the SAME check used for temporal superlatives).
    """
    desc = members[0].sic_description if members else ""
    tickers = [m.ticker for m in members]
    res = PeerComparisonResult(sic=sic, sic_description=desc, all_members=tickers)

    # Whole-group gate: some SIC classes have a non-comparable revenue denominator.
    # Decline net-margin comparison for the entire group, with the reason surfaced.
    if sic in _NONCOMPARABLE_MARGIN_SICS:
        res.decline_reason = (
            f"net-margin comparison declined for this SIC class: "
            f"{_NONCOMPARABLE_MARGIN_SICS[sic]}. NI/Revenues is not a defensible "
            f"cross-peer metric here (observed in-group margin spread was driven by "
            f"tag meaning, not performance).")
        # still record the raw metrics so a reviewer can SEE the incomparability
        metrics = compute_peer_margins(tickers, use_cache=use_cache)
        res.excluded = [{"ticker": m.ticker, "period_end": m.period_end,
                         "raw_net_margin": None if m.net_margin is None else round(m.net_margin, 1),
                         "reason": "SIC-class non-comparable revenue denominator"}
                        for m in metrics]
        return res

    metrics = compute_peer_margins(tickers, use_cache=use_cache)
    included, notes = gate_peers(metrics)
    res.notes.extend(notes)
    res.included = [{"ticker": m.ticker, "period_end": m.period_end,
                     "net_margin": round(m.net_margin, 2)} for m in included]
    res.excluded = [{"ticker": m.ticker, "reason": m.exclude_reason}
                    for m in metrics if not m.included]

    if len(included) < MIN_PEERS:
        res.decline_reason = (
            f"only {len(included)} peer(s) survived comparability gating "
            f"(need >= {MIN_PEERS}); declining rather than crown 'best-in-class' "
            f"over a non-comparable group")
        return res

    res.outliers = detect_margin_outliers(included)
    if res.outliers:
        res.notes.append(
            f"statistical outlier check: {len(res.outliers)} peer(s) beyond "
            f"{OUTLIER_STDDEV_THRESHOLD:g} population stddevs from gated-group mean"
        )
    else:
        res.notes.append(
            f"statistical outlier check: no peer beyond "
            f"{OUTLIER_STDDEV_THRESHOLD:g} population stddevs from gated-group mean"
        )

    # Build the series-across-companies and the superlative claim.
    series = [(m.ticker, m.net_margin) for m in included]
    winner = max(included, key=lambda m: m.net_margin)
    res.winner = winner.ticker
    res.winner_margin = round(winner.net_margin, 2)

    claim = Claim(
        claim_text=f"[XBRL peer] within SIC {sic} ({desc}), {winner.ticker} has the "
                   f"highest net margin ({winner.net_margin:.1f}%)",
        operation=Operation.SUPERLATIVE, stated_value=None,
        operands=[_op(v, f"peer:{t}", f"XBRL net margin {t}") for t, v in series],
        superlative=Superlative.MAX,
        params={"series": series, "target_period": winner.ticker,
                "sic": sic, "sic_description": desc,
                "peer_group_note": "SIC-based peer set — coarse; same code != always "
                                   "a true competitor (named limitation)"},
        source_text=f"XBRL NetIncomeLoss / Revenues per peer, SIC {sic}",
    )
    r = verify_claim(claim)
    res.verdict = r.status.value

    # Negative control: assert a NON-winner is the max; must be caught as WRONG_MATH.
    losers = [m for m in included if m.ticker != winner.ticker]
    if losers:
        loser = min(included, key=lambda m: m.net_margin)
        neg = Claim(
            claim_text=f"[XBRL peer neg-ctrl] {loser.ticker} claimed highest margin in SIC {sic}",
            operation=Operation.SUPERLATIVE, stated_value=None,
            operands=[_op(v, f"peer:{t}", "") for t, v in series],
            superlative=Superlative.MAX,
            params={"series": series, "target_period": loser.ticker},
        )
        res.notes.append(f"neg-control ({loser.ticker} as max): "
                         f"{verify_claim(neg).status.value}")
    return res


def viable_groups(use_cache: bool = True) -> Dict[str, List[SicInfo]]:
    tickers = [x["ticker"] for x in json.load(open(FILING_SET))["filings"]]
    groups = group_by_sic(tickers, use_cache=use_cache)
    return {k: v for k, v in groups.items() if k != "UNKNOWN" and len(v) >= MIN_PEERS}


def main():
    ap = argparse.ArgumentParser(description="XBRL SIC-based peer comparison")
    ap.add_argument("--sic", default=None, help="only this SIC code")
    ap.add_argument("--md", default=None)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    use_cache = not args.no_cache

    groups = viable_groups(use_cache=use_cache)
    if args.sic:
        groups = {k: v for k, v in groups.items() if k == args.sic}

    results: List[PeerComparisonResult] = []
    compared = declined = 0
    verdicts = Counter()
    for sic, members in sorted(groups.items(), key=lambda x: -len(x[1])):
        r = compare_sic_group(sic, members, use_cache=use_cache)
        results.append(r)
        if r.decline_reason:
            declined += 1
            print(f"  [DECLINE] SIC {sic} {r.sic_description[:28]:28} "
                  f"incl={len(r.included)} — {r.decline_reason[:50]}")
        else:
            compared += 1
            verdicts[r.verdict] += 1
            print(f"  [{r.verdict:>10}] SIC {sic} {r.sic_description[:28]:28} "
                  f"winner={r.winner} ({r.winner_margin}%) over {len(r.included)} peers")

    print("\n" + "=" * 74)
    print(f"  PEER COMPARISON over {len(groups)} viable SIC groups "
          f"({compared} compared, {declined} declined for non-comparability)")
    print("=" * 74)
    print(f"  verifier verdicts on peer-superlative claims: {dict(verdicts)}")

    os.makedirs(RUNS_DIR, exist_ok=True)
    out = os.path.join(RUNS_DIR, f"xbrl_peers_{int(time.time())}.json")
    json.dump({"schema": "aritiq.xbrl_peers.run/v1",
               "n_groups": len(groups), "compared": compared, "declined": declined,
               "verdicts": dict(verdicts),
               "results": [vars(r) for r in results]}, open(out, "w"), indent=2)
    print(f"\n  written: {out}")

    if args.md:
        with open(args.md, "w") as fh:
            fh.write("# Peer / sector comparison (SIC-based, XBRL-grounded)\n\n")
            fh.write("Peer sets are the SEC's own SIC industry codes — reused, not "
                     "invented. **Named limitation:** SIC codes are coarse; the same "
                     "code is not always a true competitor. Every comparison carries "
                     "its SIC code so the judgment is explicit.\n\n")
            fh.write(f"- Viable SIC groups (>= {MIN_PEERS} members): {len(groups)}\n")
            fh.write(f"- Compared: {compared} | Declined for non-comparability: {declined}\n")
            fh.write(f"- Comparability gates: period alignment (<= {PERIOD_TOLERANCE_DAYS}d "
                     f"apart), margin sanity (|margin| <= {MARGIN_SANITY_BOUND:.0f}%)\n\n")
            for r in results:
                fh.write(f"## SIC {r.sic} — {r.sic_description}\n\n")
                fh.write(f"Members: {', '.join(r.all_members)}\n\n")
                if r.decline_reason:
                    fh.write(f"**DECLINED:** {r.decline_reason}\n\n")
                else:
                    fh.write(f"**Winner:** {r.winner} ({r.winner_margin}% net margin) — "
                             f"verifier verdict `{r.verdict}`\n\n")
                if r.included:
                    fh.write("| Peer | Period | Net margin % |\n|---|---|---|\n")
                    for m in sorted(r.included, key=lambda x: -x["net_margin"]):
                        fh.write(f"| {m['ticker']} | {m['period_end']} | {m['net_margin']} |\n")
                    fh.write("\n")
                if r.excluded:
                    fh.write("Excluded (gated, not compared):\n\n")
                    for m in r.excluded:
                        fh.write(f"- `{m['ticker']}`: {m['reason']}\n")
                    fh.write("\n")
                if r.notes:
                    for n in r.notes:
                        fh.write(f"> {n}\n")
                    fh.write("\n")
        print(f"  markdown: {args.md}")


if __name__ == "__main__":
    main()
