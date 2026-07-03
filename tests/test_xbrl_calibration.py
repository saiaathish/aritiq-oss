import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "benchmark", "reliability"))

import xbrl_calibration  # noqa: E402


def test_phase5_xbrl_calibration_math_reconciles_on_synthetic_run():
    run = {
        "n_filers": 2,
        "results": [
            {
                "ticker": "AAPL",
                "fetch_error": None,
                "claims": [
                    {"rule": "eps_reconciliation", "verdict": "VERIFIED", "operands": [1.0, 10.0, 10.0]},
                    {"rule": "cash_flow_tie_out", "verdict": "INSUFFICIENT_EVIDENCE", "operands": [1.0, 2.0]},
                ],
            },
            {
                "ticker": "JPM",
                "fetch_error": None,
                "claims": [
                    {
                        "rule": "eps_reconciliation",
                        "verdict": "WRONG_MATH",
                        "operands": [1.0, 12.0, 10.0],
                        "explanation": "exceeds tolerance",
                    }
                ],
            },
        ],
    }
    a = xbrl_calibration.analyze(run)

    assert a["n_filers"] == 2
    assert a["total_claims"] == 3
    assert a["verdicts"] == {
        "VERIFIED": 1,
        "INSUFFICIENT_EVIDENCE": 1,
        "WRONG_MATH": 1,
    }
    assert a["precision_verified_vs_wrong"] == 50.0
    assert a["false_positive_rate_wrong_math"] == 50.0
    assert a["verification_recall_coverage"] == 33.3
    assert a["decline_rate"] == 33.3
    assert len(a["wrong_rows"]) == 1


def test_phase5_xbrl_report_names_confidence_boundary():
    report_path = os.path.join(
        _REPO,
        "benchmark",
        "reliability",
        "PHASE5_XBRL_CALIBRATION.md",
    )
    md = open(report_path).read()

    assert "Confidence calibration definition" in md
    assert "No new confidence score is invented" in md
    assert "These are deterministic XBRL-lane EPS convictions" in md
    assert "Filers: 115" in md
    assert "XBRL-grounded claims: 354" in md
    assert "96.6%" in md
