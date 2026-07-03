import json

from aritiq.core.schema import Claim, Operation, TrendDir, VerificationStatus
from aritiq.core.verify import verify_claim
from aritiq.extract.mda import (
    MDA_SYSTEM_PROMPT,
    extract_mda_directional_claims,
    parse_mda_directional_claims,
)
from benchmark.reliability.mda_xbrl_consistency import (
    build_mda_xbrl_claim,
    run_gold_replay,
)


def test_mda_xbrl_core_match_conflict_and_ambiguous_band():
    up = Claim("Revenue grew", Operation.MDA_XBRL_CONSISTENCY, None,
               trend_dir=TrendDir.UP, params={"actual_percent_change": 12.0})
    down = Claim("Revenue grew", Operation.MDA_XBRL_CONSISTENCY, None,
                 trend_dir=TrendDir.UP, params={"actual_percent_change": -12.0})
    small = Claim("Revenue grew modestly", Operation.MDA_XBRL_CONSISTENCY, None,
                  trend_dir=TrendDir.UP, params={"actual_percent_change": 1.0})

    assert verify_claim(up).status == VerificationStatus.VERIFIED
    assert verify_claim(down).status == VerificationStatus.CONFLICT
    assert verify_claim(small).status == VerificationStatus.NEEDS_REVIEW


def test_mda_replay_gold_set_all_expected_statuses():
    out = run_gold_replay()
    assert out["n_cases"] == 6
    assert out["passed"] == 6
    assert out["failed"] == 0
    statuses = {r["id"]: r["status"] for r in out["results"]}
    assert statuses["revenue_up_matches"] == "VERIFIED"
    assert statuses["revenue_up_conflicts_decline"] == "CONFLICT"
    assert statuses["flatish_needs_review"] == "NEEDS_REVIEW"


def test_mda_claim_builder_computes_xbrl_percent_change():
    claim = build_mda_xbrl_claim(
        metric="revenue",
        direction="up",
        excerpt="Revenue increased.",
        prior_value=100.0,
        current_value=112.0,
    )
    assert claim.operation == Operation.MDA_XBRL_CONSISTENCY
    assert claim.trend_dir == TrendDir.UP
    assert abs(claim.params["actual_percent_change"] - 12.0) < 1e-9
    assert verify_claim(claim).status == VerificationStatus.VERIFIED


def test_mda_extraction_parser_and_prompt_no_percent_invention():
    raw = json.dumps([
        {
            "metric": "revenue",
            "direction": "up",
            "excerpt": "Revenue increased due to demand.",
            "period": "year ended 2025",
            "confidence": "high",
        }
    ])
    parsed = parse_mda_directional_claims(raw)
    assert parsed[0].metric == "revenue"
    assert parsed[0].direction == TrendDir.UP
    assert "Do not invent percentages" in MDA_SYSTEM_PROMPT


def test_mda_extraction_uses_injected_completion_only():
    def complete(system_prompt, user_prompt):
        assert "MD&A" in user_prompt
        return json.dumps([{
            "metric": "net_income",
            "direction": "down",
            "excerpt": "Net income decreased.",
        }])

    claims = extract_mda_directional_claims("Net income decreased.", complete_fn=complete)
    assert len(claims) == 1
    assert claims[0].direction == TrendDir.DOWN
