import json

from benchmark.reliability.segment_companyfacts_premise import scan_companyfacts_segments


def test_segment_scanner_reports_absent_dimension_data(tmp_path):
    (tmp_path / "_raw_TEST.json").write_text(json.dumps({
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2024-01-01", "end": "2024-12-31", "val": 100}
                        ]
                    }
                }
            }
        }
    }))
    out = scan_companyfacts_segments(str(tmp_path))
    assert out["files_scanned"] == 1
    assert out["segment_fact_rows"] == 0
    assert out["filers_with_segment_facts"] == 0
    assert "does not expose dimensional segment facts" in out["conclusion"]


def test_segment_scanner_surfaces_segment_shaped_fact_if_present(tmp_path):
    (tmp_path / "_raw_TEST.json").write_text(json.dumps({
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 40,
                                "segments": [{"axis": "BusinessSegmentsAxis"}],
                            }
                        ]
                    }
                }
            }
        }
    }))
    out = scan_companyfacts_segments(str(tmp_path))
    assert out["segment_fact_rows"] == 1
    assert out["filers_with_segment_facts"] == 1
    assert out["filers"][0]["ticker"] == "TEST"
