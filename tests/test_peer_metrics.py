"""
Tests for the multi-metric peer coverage / anomaly layer
(benchmark/reliability/peer_metrics.py).

The pure aggregation + gating + outlier logic is tested with synthetic FilerMetric
objects (no cache, no network). A couple of end-to-end checks against the real cached
XBRL are guarded by tests/conftest so a fresh clone (no raw cache) skips them.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "benchmark", "reliability"))

import peer_metrics as pm  # noqa: E402

_XBRL_CACHE = os.path.join(_REPO, "benchmark", "reliability", "cache", "xbrl")


def _need(*tickers):
    miss = [t for t in tickers
            if not os.path.exists(os.path.join(_XBRL_CACHE, f"_raw_{t}.json"))]
    if miss:
        pytest.skip(f"raw XBRL cache absent for {miss}")


def _fm(ticker, value, period="2025-12-31"):
    m = pm.FilerMetric(ticker=ticker, period_end=period, value=value,
                       numerator=value, denominator=100.0)
    return m


# ---- pure stats ------------------------------------------------------------

def test_population_stddev():
    mean, sd = pm._population_stddev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert mean == 5.0
    assert round(sd, 3) == 2.0


def test_population_stddev_empty():
    assert pm._population_stddev([]) == (0.0, 0.0)


# ---- gate_and_flag ---------------------------------------------------------

def test_outlier_flagged_beyond_threshold():
    metric = pm.METRICS["return_on_assets"]
    # cluster near 3, one clear outlier at 13
    metrics = [_fm("A", 3.0), _fm("B", 3.2), _fm("C", 2.8), _fm("D", 3.1), _fm("E", 13.0)]
    included, notes = pm.gate_and_flag(metrics, metric)
    assert len(included) == 5
    out = [m for m in included if m.outlier]
    assert len(out) == 1 and out[0].ticker == "E"
    assert out[0].zscore >= pm.OUTLIER_STDDEV


def test_no_outlier_when_tight_cluster():
    metric = pm.METRICS["return_on_assets"]
    metrics = [_fm("A", 3.0), _fm("B", 3.1), _fm("C", 2.9), _fm("D", 3.05)]
    included, _ = pm.gate_and_flag(metrics, metric)
    assert all(not m.outlier for m in included)


def test_stale_period_peer_excluded():
    metric = pm.METRICS["return_on_assets"]
    metrics = [_fm("A", 3.0, "2025-12-31"), _fm("B", 3.2, "2025-12-31"),
               _fm("C", 3.1, "2025-12-31"), _fm("OLD", 3.0, "2019-12-31")]
    included, _ = pm.gate_and_flag(metrics, metric)
    inc = {m.ticker for m in included}
    assert "OLD" not in inc
    old = next(m for m in metrics if m.ticker == "OLD")
    assert "stale" in (old.exclude_reason or "")


def test_out_of_sanity_band_excluded():
    metric = pm.METRICS["return_on_assets"]   # band -60..60
    metrics = [_fm("A", 3.0), _fm("B", 3.2), _fm("C", 3.1), _fm("BAD", 999.0)]
    included, _ = pm.gate_and_flag(metrics, metric)
    assert {m.ticker for m in included} == {"A", "B", "C"}
    bad = next(m for m in metrics if m.ticker == "BAD")
    assert "sanity band" in (bad.exclude_reason or "")


def test_zscore_needs_min_peers():
    metric = pm.METRICS["return_on_assets"]
    metrics = [_fm("A", 3.0), _fm("B", 13.0)]   # only 2 -> below MIN_PEERS
    included, _ = pm.gate_and_flag(metrics, metric)
    assert all(m.zscore is None for m in included)


# ---- excluded SIC classes (net_margin) ------------------------------------

def test_net_margin_declined_for_reit_sic():
    metric = pm.METRICS["net_margin"]
    from aritiq.edgar.sic import SicInfo
    members = [SicInfo(ticker=t, sic="6798", sic_description="REIT") for t in ["A", "B", "C"]]
    res = pm.compare_group_metric("6798", members, metric, use_cache=False)
    assert res.decline_reason and "not comparable" in res.decline_reason


def test_roa_not_excluded_for_reit_sic():
    """The whole point of the coverage expansion: ROA IS comparable for REITs."""
    assert "6798" not in pm.METRICS["return_on_assets"].excluded_sics
    assert "6021" not in pm.METRICS["return_on_assets"].excluded_sics  # banks too


# ---- compare_group_metric with monkeypatched compute (no cache) -----------

def test_compare_group_metric_flags_outlier(monkeypatch):
    metric = pm.METRICS["return_on_assets"]
    vals = {"A": 3.0, "B": 3.1, "C": 2.9, "D": 3.0, "E": 13.0}

    def fake_compute(ticker, m, *, use_cache=True):
        return _fm(ticker, vals[ticker])

    monkeypatch.setattr(pm, "compute_filer_metric", fake_compute)
    from aritiq.edgar.sic import SicInfo
    members = [SicInfo(ticker=t, sic="1234", sic_description="Test") for t in vals]
    res = pm.compare_group_metric("1234", members, metric, use_cache=False)
    assert res.decline_reason is None
    assert [o["ticker"] for o in res.outliers] == ["E"]


# ---- real-cache coverage check (guarded) ----------------------------------

def test_roa_expands_coverage_beyond_net_margin_realcache():
    _need("JPM", "BAC", "WFC", "PLD", "SPG", "AVB")
    data = pm.run_all(use_cache=True)
    nm = data["coverage"]["net_margin"]["compared"]
    roa = data["coverage"]["return_on_assets"]["compared"]
    # ROA must reach strictly more SIC groups than net margin (the coverage gain).
    assert roa > nm
