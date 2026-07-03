"""
Multi-period XBRL history regression suite (Feature 1).

Covers:
  (a) get_concept_series builds a chronological, comparable time series and drops
      non-comparable spans (quarters / YTD-cumulatives / fiscal-year-change stubs);
  (b) per-share concepts are flagged split_sensitive;
  (c) claims built from a real-shaped series flow through the EXISTING temporal
      verifier and percent_change and produce the right verdicts (positive claims
      VERIFY, wrong claims are caught as WRONG_MATH);
  (d) the split-comparability gate prevents a percent_change claim from being built
      on a split-sensitive series (no silent wrong comparison).

All offline / synthetic — no network — mirroring test_xbrl_grounding.py.
"""
import json
import os
import sys
import tempfile

from aritiq.edgar.xbrl_history import get_concept_series
from aritiq.core.schema import Operation, TrendDir, Superlative, VerificationStatus
from aritiq.core.verify import verify_claim

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmark", "reliability"))
from xbrl_trends import build_trend_claims  # noqa: E402


def _annual(end, val, start=None, form="10-K"):
    """A full-fiscal-year duration fact (~365 day span)."""
    if start is None:
        y, m, d = map(int, end.split("-"))
        start = f"{y-1}-{m:02d}-{d:02d}"
    return {"end": end, "start": start, "val": val, "form": form, "filed": end}


def _instant(end, val, form="10-K"):
    """An instant (balance-sheet) fact — no start, so no span policing."""
    return {"end": end, "val": val, "form": form, "filed": end}


def _quarter(end, val, form="10-K"):
    """A ~90-day standalone-quarter fact that must be DROPPED from an annual series."""
    y, m, d = map(int, end.split("-"))
    sm = m - 3 if m > 3 else 12
    sy = y if m > 3 else y - 1
    return {"end": end, "start": f"{sy}-{sm:02d}-{d:02d}", "val": val,
            "form": form, "filed": end}


def _payload(concepts, cik=1, company="Test Co"):
    us_gaap = {}
    for tag, facts in concepts.items():
        if tag.startswith("EarningsPerShare"):
            uk = "USD/shares"
        elif tag.startswith("WeightedAverage"):
            uk = "shares"
        else:
            uk = "USD"
        us_gaap[tag] = {"units": {uk: facts}}
    return {"facts": {"us-gaap": us_gaap}, "_resolved_cik": cik,
            "_resolved_company": company}


def _fetch_stub(payload):
    tickers_map = {"0": {"cik_str": 1, "ticker": "TEST", "title": "Test Co"}}

    def _fetch(url):
        if "company_tickers" in url:
            return json.dumps(tickers_map)
        return json.dumps(payload)
    return _fetch


def _series(payload, concept, **kw):
    d = tempfile.mkdtemp()
    return get_concept_series("TEST", concept, fetch=_fetch_stub(payload),
                              cache_dir=d, use_cache=False, **kw)


# ---------------------------------------------------------------------------
# (a) chronological comparable series; non-annual spans dropped
# ---------------------------------------------------------------------------

def test_series_is_chronological_and_annual_only():
    payload = _payload({"Revenues": [
        _annual("2021-12-31", 100.0),
        _annual("2023-12-31", 130.0),   # out of order on purpose
        _annual("2022-12-31", 115.0),
        _quarter("2023-09-30", 33.0),   # a quarter — must be dropped
    ]})
    s = _series(payload, "revenue")
    assert s.tag_used == "Revenues"
    assert [p.period_end for p in s.points] == ["2021-12-31", "2022-12-31", "2023-12-31"]
    assert [p.value for p in s.points] == [100.0, 115.0, 130.0]
    assert s.dropped_noncomparable_spans == 1   # the quarter
    assert s.split_sensitive is False


def test_fiscal_year_change_stub_is_dropped():
    """A short 'stub' period from a fiscal-year-end change is not comparable and
    must be excluded, not compared against full years as if it were a full year."""
    payload = _payload({"Revenues": [
        _annual("2021-12-31", 100.0),
        _annual("2022-12-31", 110.0),
        # fiscal year end moves to June: a 6-month stub period (non-annual span)
        {"end": "2023-06-30", "start": "2023-01-01", "val": 55.0,
         "form": "10-K", "filed": "2023-06-30"},
        _annual("2024-06-30", 120.0, start="2023-07-01"),
    ]})
    s = _series(payload, "revenue")
    ends = [p.period_end for p in s.points]
    assert "2023-06-30" not in ends          # stub dropped
    assert s.dropped_noncomparable_spans >= 1
    assert ends == ["2021-12-31", "2022-12-31", "2024-06-30"]


def test_instant_facts_keep_all_periods():
    payload = _payload({"Assets": [
        _instant("2022-12-31", 500.0),
        _instant("2023-12-31", 550.0),
        _instant("2024-12-31", 600.0),
    ]})
    s = _series(payload, "assets")
    assert s.n_points == 3
    assert s.dropped_noncomparable_spans == 0


# ---------------------------------------------------------------------------
# (b) per-share concepts are split-sensitive
# ---------------------------------------------------------------------------

def test_per_share_series_flagged_split_sensitive():
    payload = _payload({"EarningsPerShareBasic": [
        {"end": "2022-12-31", "start": "2022-01-01", "val": 2.0, "form": "10-K", "filed": "2022-12-31"},
        {"end": "2023-12-31", "start": "2023-01-01", "val": 2.5, "form": "10-K", "filed": "2023-12-31"},
    ]})
    s = _series(payload, "eps_basic")
    assert s.split_sensitive is True


# ---------------------------------------------------------------------------
# (c) claims flow through the EXISTING verifier with correct verdicts
# ---------------------------------------------------------------------------

def test_positive_claims_verify_and_negatives_caught():
    payload = _payload({"Revenues": [
        _annual("2021-12-31", 100.0),
        _annual("2022-12-31", 120.0),
        _annual("2023-12-31", 150.0),
        _annual("2024-12-31", 200.0),
    ]})
    s = _series(payload, "revenue")
    claims = build_trend_claims(s, window=5)
    assert claims, "expected claims to be built from a clean multi-year series"
    for c in claims:
        r = verify_claim(c)
        control = c.params.get("control")
        if control == "positive":
            expect = c.params.get("expected_verified", True)
            want = VerificationStatus.VERIFIED if expect else VerificationStatus.WRONG_MATH
            assert r.status == want, (c.claim_text, r.status, r.explanation)
        elif control == "negative":
            assert r.status == VerificationStatus.WRONG_MATH, (c.claim_text, r.status)


def test_real_percent_change_verifies():
    payload = _payload({"Revenues": [
        _annual("2023-12-31", 100.0),
        _annual("2024-12-31", 112.0),   # exactly +12%
    ]})
    s = _series(payload, "revenue")
    pc = [c for c in build_trend_claims(s, window=5)
          if c.operation == Operation.PERCENT_CHANGE and c.params.get("control") == "positive"]
    assert len(pc) == 1
    assert abs(pc[0].stated_value - 12.0) < 1e-6
    assert verify_claim(pc[0]).status == VerificationStatus.VERIFIED


def test_consecutive_count_matches_real_run():
    payload = _payload({"NetIncomeLoss": [
        _annual("2021-12-31", 10.0),
        _annual("2022-12-31", 9.0),     # a dip breaks the run
        _annual("2023-12-31", 12.0),
        _annual("2024-12-31", 15.0),    # trailing run of increases = 2
    ]})
    s = _series(payload, "net_income")
    cc = [c for c in build_trend_claims(s, window=5)
          if c.operation == Operation.CONSECUTIVE_COUNT and c.params.get("control") == "positive"]
    assert len(cc) == 1
    assert cc[0].stated_value == 2.0
    assert verify_claim(cc[0]).status == VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# (d) the split gate blocks a percent_change on a split-sensitive series
# ---------------------------------------------------------------------------

def test_split_sensitive_series_builds_no_percent_change():
    """A per-share series that spans a stock split must NOT produce a confident
    percent_change claim — that would be a silent wrong comparison. The gate
    routes to a skip (no percent_change claim built)."""
    payload = _payload({"EarningsPerShareBasic": [
        {"end": "2022-12-31", "start": "2022-01-01", "val": 8.0, "form": "10-K", "filed": "2022-12-31"},
        {"end": "2023-12-31", "start": "2023-01-01", "val": 2.0, "form": "10-K", "filed": "2023-12-31"},
    ]})
    s = _series(payload, "eps_basic")
    assert s.split_sensitive is True
    ops = [c.operation for c in build_trend_claims(s, window=5)]
    assert Operation.PERCENT_CHANGE not in ops


def test_short_series_builds_no_claims():
    payload = _payload({"Revenues": [_annual("2024-12-31", 100.0)]})
    s = _series(payload, "revenue")
    assert s.n_points == 1
    assert build_trend_claims(s, window=5) == []


def test_missing_concept_returns_empty_series_not_error():
    payload = _payload({"Assets": [_instant("2024-12-31", 500.0)]})
    s = _series(payload, "revenue")   # no revenue tag present
    assert s.fetch_error is None
    assert s.n_points == 0
    assert s.tag_used is None
