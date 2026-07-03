import json

from benchmark.reliability.guidance_xbrl_premise import scan_companyfacts_cache


def _write_raw(path, ticker, concepts):
    path.mkdir(parents=True, exist_ok=True)
    (path / f"_raw_{ticker}.json").write_text(json.dumps({
        "facts": {
            "us-gaap": concepts
        }
    }))


def test_guidance_premise_filters_forecasted_hedge_false_positive(tmp_path):
    _write_raw(tmp_path, "TEST", {
        "GainLossOnDiscontinuationOfCashFlowHedgeDueToForecastedTransaction": {
            "label": "Gain Loss on Forecasted Transaction Hedge",
            "description": "forecasted transaction derivative hedge",
            "units": {},
        }
    })
    out = scan_companyfacts_cache(str(tmp_path))
    assert out["files_scanned"] == 1
    assert out["raw_forward_term_hits"] == 1
    assert out["issuer_guidance_candidates"] == 0
    assert "does not reliably expose" in out["conclusion"]


def test_guidance_premise_surfaces_true_candidate_if_present(tmp_path):
    _write_raw(tmp_path, "TEST", {
        "RevenueGuidanceHigh": {
            "label": "Revenue Guidance High",
            "description": "issuer revenue guidance high end",
            "units": {},
        }
    })
    out = scan_companyfacts_cache(str(tmp_path))
    assert out["issuer_guidance_candidates"] == 1
    assert out["candidate_hits"][0]["tag"] == "RevenueGuidanceHigh"
