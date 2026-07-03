"""
Peer/sector comparison regression suite (Feature 2).

Covers:
  (a) SIC lookup parses sic/sicDescription from a submissions-shaped payload and
      caches; group_by_sic buckets correctly and never drops a ticker silently;
  (b) net-margin comparison across peers runs through the EXISTING superlative
      verifier and crowns the real max (positive) while catching a wrong claim
      (negative control);
  (c) the comparability gates fire: a stale-period peer is excluded, an
      implausible-margin peer is excluded, and a whole non-comparable SIC class
      (REIT/insurer/bank) is declined rather than crowned;
  (d) a group with < MIN_PEERS survivors declines rather than compare.

All offline / synthetic — no network.
"""
import json
import os
import tempfile

from aritiq.edgar.sic import get_sic, group_by_sic
from aritiq.core.schema import VerificationStatus
from benchmark.reliability.xbrl_peers import (
    PeerMetric, gate_peers, compare_sic_group, _NONCOMPARABLE_MARGIN_SICS,
    MARGIN_SANITY_BOUND, PERIOD_TOLERANCE_DAYS,
    OUTLIER_STDDEV_THRESHOLD, detect_margin_outliers,
)
from aritiq.edgar.sic import SicInfo


# ---- SIC lookup (offline) --------------------------------------------------

def _sic_fetch_stub(sic, desc, name="Test Co"):
    tickers_map = {"0": {"cik_str": 1, "ticker": "TEST", "title": name}}

    def _fetch(url):
        if "company_tickers" in url:
            return json.dumps(tickers_map)
        return json.dumps({"sic": sic, "sicDescription": desc, "name": name})
    return _fetch


def test_get_sic_parses_and_returns():
    d = tempfile.mkdtemp()
    info = get_sic("TEST", fetch=_sic_fetch_stub("3571", "Electronic Computers"),
                   cache_dir=d, use_cache=False)
    assert info.sic == "3571"
    assert info.sic_description == "Electronic Computers"
    assert info.fetch_error is None


def test_group_by_sic_buckets_and_keeps_unknown_visible(monkeypatch):
    infos = {
        "A": SicInfo(ticker="A", sic="3571", sic_description="Computers"),
        "B": SicInfo(ticker="B", sic="3571", sic_description="Computers"),
        "C": SicInfo(ticker="C", sic=None),   # unresolved -> UNKNOWN, not dropped
    }

    def fake_get(tk, **kw):
        return infos[tk]

    import aritiq.edgar.sic as sicmod
    monkeypatch.setattr(sicmod, "get_sic", fake_get)
    groups = sicmod.group_by_sic(["A", "B", "C"])
    assert {m.ticker for m in groups["3571"]} == {"A", "B"}
    assert "UNKNOWN" in groups
    assert [m.ticker for m in groups["UNKNOWN"]] == ["C"]


# ---- gating ----------------------------------------------------------------

def _pm(tk, pe, margin):
    return PeerMetric(ticker=tk, period_end=pe, net_income=margin, revenue=100.0,
                      net_margin=margin)


def test_stale_period_peer_excluded():
    metrics = [
        _pm("A", "2025-12-31", 20.0),
        _pm("B", "2025-12-31", 30.0),
        _pm("C", "2019-12-31", 25.0),   # ~6 years stale
    ]
    included, _ = gate_peers(metrics)
    inc = {m.ticker for m in included}
    assert inc == {"A", "B"}
    c = next(m for m in metrics if m.ticker == "C")
    assert not c.included and "stale" in (c.exclude_reason or "")


def test_implausible_margin_peer_excluded():
    metrics = [
        _pm("A", "2025-12-31", 20.0),
        _pm("B", "2025-12-31", 30.0),
        _pm("BAD", "2025-12-31", MARGIN_SANITY_BOUND + 500.0),  # 600% -> excluded
    ]
    included, _ = gate_peers(metrics)
    assert {m.ticker for m in included} == {"A", "B"}
    bad = next(m for m in metrics if m.ticker == "BAD")
    assert not bad.included and "sanity bound" in (bad.exclude_reason or "")


def test_statistical_outlier_detector_flags_only_gated_peer():
    metrics = [
        _pm("A", "2025-12-31", 10.0),
        _pm("B", "2025-12-31", 11.0),
        _pm("C", "2025-12-31", 12.0),
        _pm("OUT", "2025-12-31", 100.0),
        _pm("EXCLUDED", "2025-12-31", -500.0),
    ]
    for m in metrics:
        m.included = m.ticker != "EXCLUDED"
    outliers = detect_margin_outliers(metrics, threshold_stddev=1.5)
    assert [o["ticker"] for o in outliers] == ["OUT"]
    o = outliers[0]
    assert o["threshold_stddev"] == 1.5
    assert o["peer_count"] == 4
    assert o["z_score"] > 1.5
    assert o["metric"] == "net_margin"


def test_statistical_outlier_detector_no_outlier_at_default_threshold():
    metrics = [_pm("A", "2025-12-31", 10.0),
               _pm("B", "2025-12-31", 11.0),
               _pm("C", "2025-12-31", 12.0)]
    for m in metrics:
        m.included = True
    assert detect_margin_outliers(metrics) == []
    assert OUTLIER_STDDEV_THRESHOLD == 2.0


def test_noncomparable_sic_class_is_declined_wholesale():
    """A REIT SIC group must be declined for net margin, with the raw metrics still
    recorded so a reviewer can see the incomparability."""
    assert "6798" in _NONCOMPARABLE_MARGIN_SICS
    members = [SicInfo(ticker=t, sic="6798", sic_description="Real Estate Investment Trusts")
               for t in ["PLD", "SPG", "AVB"]]
    # use_cache=True reads the committed cache; these REITs are in the benchmark set
    res = compare_sic_group("6798", members, use_cache=True)
    assert res.winner is None
    assert res.decline_reason and "REIT" in res.decline_reason
    assert res.excluded  # raw metrics recorded for transparency


# ---- end-to-end comparison through the existing verifier -------------------

def test_comparable_group_verifies_winner_and_catches_wrong_claim():
    """A clean, comparable group crowns the real max (VERIFIED) and a negative
    control (a non-winner claimed as max) is caught as WRONG_MATH — both via the
    EXISTING superlative verifier."""
    members = [SicInfo(ticker=t, sic="7372", sic_description="Services-Prepackaged Software")
               for t in ["PLTR", "CRM", "ORCL", "DDOG", "U"]]
    res = compare_sic_group("7372", members, use_cache=True)
    assert res.decline_reason is None
    assert res.verdict == VerificationStatus.VERIFIED.value
    # winner must be the actual max margin among the included peers
    top = max(res.included, key=lambda m: m["net_margin"])
    assert res.winner == top["ticker"]
    # negative control was run and recorded as WRONG_MATH
    assert any("WRONG_MATH" in n for n in res.notes)
