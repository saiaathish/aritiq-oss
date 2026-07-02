import json
import tempfile

from aritiq.edgar.company_memory import build_company_memory


def _annual(end, val, start=None, form="10-K"):
    if start is None:
        y, m, d = map(int, end.split("-"))
        start = f"{y-1}-{m:02d}-{d:02d}"
    return {"end": end, "start": start, "val": val, "form": form, "filed": end}


def _payload(concepts):
    return {
        "facts": {
            "us-gaap": {
                tag: {"units": {unit: facts}}
                for tag, unit, facts in concepts
            }
        }
    }


def _write_cache(cache_dir, ticker, payload):
    path = f"{cache_dir}/_raw_{ticker}.json"
    with open(path, "w") as fh:
        json.dump(payload, fh)


def test_company_memory_builds_yoy_trajectory_from_cached_series():
    payload = _payload([
        ("Revenues", "USD", [
            _annual("2022-12-31", 100.0),
            _annual("2023-12-31", 125.0),
            _annual("2024-12-31", 150.0),
        ]),
    ])
    with tempfile.TemporaryDirectory() as d:
        _write_cache(d, "TEST", payload)
        mem = build_company_memory("TEST", concepts=["revenue"], cache_dir=d)

    metric = mem.metrics[0]
    assert metric.concept == "revenue"
    assert metric.n_points == 3
    assert [p.period_end for p in metric.points] == ["2022-12-31", "2023-12-31", "2024-12-31"]
    assert metric.points[1].yoy_change_pct == 25.0
    assert metric.latest_yoy_change_pct == 20.0
    assert [(s.concept, s.signal) for s in mem.signals] == [("revenue", "fallback_xbrl_tag_used")]


def test_company_memory_surfaces_existing_comparability_gates():
    payload = _payload([
        ("Revenues", "USD", [
            _annual("2022-12-31", 100.0),
            {"end": "2023-06-30", "start": "2023-01-01", "val": 50.0, "form": "10-K", "filed": "2023-06-30"},
            _annual("2024-12-31", 140.0),
        ]),
        ("EarningsPerShareBasic", "USD/shares", [
            _annual("2023-12-31", 2.0),
            _annual("2024-12-31", 3.0),
        ]),
    ])
    with tempfile.TemporaryDirectory() as d:
        _write_cache(d, "TEST", payload)
        mem = build_company_memory("TEST", concepts=["revenue", "eps_basic"], cache_dir=d)

    signals = {(s.concept, s.signal) for s in mem.signals}
    assert ("revenue", "noncomparable_spans_dropped") in signals
    assert ("eps_basic", "split_sensitive_series") in signals
    assert all(s.deterministic for s in mem.signals)
    assert "footnote-language" in mem.boundary
