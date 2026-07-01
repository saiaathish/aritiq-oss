"""
Temporal consistency test suite (Phase 2, §3.2).

trend_direction, superlative, consecutive_count — each tested in the VERIFIED
and WRONG_MATH directions plus edge cases.  Pure computation over an ordered
(period, value) series; no LLM.
"""
import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, TrendDir, Superlative, VerificationStatus,
)
from aritiq.core.verify import verify_claim


def temporal_claim(op, series, *, trend_dir=None, superlative=None,
                   stated_value=None, target_period=None):
    ops = [Operand(value=float(v), source=OperandSource.GROUNDED, source_text=str(v))
           for _, v in series]
    params = {"series": series}
    if target_period is not None:
        params["target_period"] = target_period
    return Claim(
        claim_text=f"{op.value} claim",
        operation=op,
        stated_value=stated_value,
        operands=ops,
        trend_dir=trend_dir,
        superlative=superlative,
        params=params,
    )


# ===========================================================================
# trend_direction
# ===========================================================================

class TestTrendDirection:
    def test_up_verified(self):
        s = [("Q1", 100), ("Q2", 110), ("Q3", 125)]
        r = verify_claim(temporal_claim(Operation.TREND_DIRECTION, s, trend_dir=TrendDir.UP))
        assert r.status == VerificationStatus.VERIFIED

    def test_up_wrong_when_a_dip(self):
        s = [("Q1", 100), ("Q2", 95), ("Q3", 125)]  # not strictly increasing
        r = verify_claim(temporal_claim(Operation.TREND_DIRECTION, s, trend_dir=TrendDir.UP))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_down_verified(self):
        s = [("Q1", 125), ("Q2", 110), ("Q3", 100)]
        r = verify_claim(temporal_claim(Operation.TREND_DIRECTION, s, trend_dir=TrendDir.DOWN))
        assert r.status == VerificationStatus.VERIFIED

    def test_flat_verified_within_tolerance(self):
        s = [("Q1", 100.0), ("Q2", 100.05), ("Q3", 99.97)]
        r = verify_claim(temporal_claim(Operation.TREND_DIRECTION, s, trend_dir=TrendDir.FLAT))
        assert r.status == VerificationStatus.VERIFIED

    def test_flat_wrong_when_real_move(self):
        s = [("Q1", 100), ("Q2", 130)]
        r = verify_claim(temporal_claim(Operation.TREND_DIRECTION, s, trend_dir=TrendDir.FLAT))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_single_point_ambiguous(self):
        s = [("Q1", 100)]
        r = verify_claim(temporal_claim(Operation.TREND_DIRECTION, s, trend_dir=TrendDir.UP))
        assert r.status == VerificationStatus.AMBIGUOUS

    def test_no_direction_ambiguous(self):
        s = [("Q1", 100), ("Q2", 110)]
        r = verify_claim(temporal_claim(Operation.TREND_DIRECTION, s, trend_dir=None))
        assert r.status == VerificationStatus.AMBIGUOUS


# ===========================================================================
# superlative
# ===========================================================================

class TestSuperlative:
    def test_max_verified_latest_is_highest(self):
        s = [("FY21", 50), ("FY22", 60), ("FY23", 75)]  # latest is the max
        r = verify_claim(temporal_claim(Operation.SUPERLATIVE, s, superlative=Superlative.MAX))
        assert r.status == VerificationStatus.VERIFIED

    def test_max_wrong_when_not_highest(self):
        s = [("FY21", 80), ("FY22", 60), ("FY23", 75)]  # latest (75) is NOT the max (80)
        r = verify_claim(temporal_claim(Operation.SUPERLATIVE, s, superlative=Superlative.MAX))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_min_verified(self):
        s = [("FY21", 80), ("FY22", 60), ("FY23", 40)]  # latest is the min
        r = verify_claim(temporal_claim(Operation.SUPERLATIVE, s, superlative=Superlative.MIN))
        assert r.status == VerificationStatus.VERIFIED

    def test_target_period_max(self):
        s = [("FY21", 80), ("FY22", 95), ("FY23", 75)]  # FY22 is the max
        r = verify_claim(temporal_claim(Operation.SUPERLATIVE, s, superlative=Superlative.MAX,
                                        target_period="FY22"))
        assert r.status == VerificationStatus.VERIFIED

    def test_target_period_not_found_ambiguous(self):
        s = [("FY21", 80), ("FY22", 95)]
        r = verify_claim(temporal_claim(Operation.SUPERLATIVE, s, superlative=Superlative.MAX,
                                        target_period="FY99"))
        assert r.status == VerificationStatus.AMBIGUOUS


# ===========================================================================
# consecutive_count
# ===========================================================================

class TestConsecutiveCount:
    def test_three_consecutive_increases_verified(self):
        # diffs: +, +, + -> trailing run of 3 up-steps
        s = [("Q1", 80), ("Q2", 90), ("Q3", 100), ("Q4", 110)]
        r = verify_claim(temporal_claim(Operation.CONSECUTIVE_COUNT, s,
                                        trend_dir=TrendDir.UP, stated_value=3))
        assert r.status == VerificationStatus.VERIFIED

    def test_count_wrong(self):
        # only the last 2 steps are up (90->85 breaks it); stated 3 is wrong
        s = [("Q1", 80), ("Q2", 90), ("Q3", 85), ("Q4", 95), ("Q5", 100)]
        r = verify_claim(temporal_claim(Operation.CONSECUTIVE_COUNT, s,
                                        trend_dir=TrendDir.UP, stated_value=3))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_count_correct_after_break(self):
        # trailing run of exactly 2 up-steps
        s = [("Q1", 80), ("Q2", 90), ("Q3", 85), ("Q4", 95), ("Q5", 100)]
        r = verify_claim(temporal_claim(Operation.CONSECUTIVE_COUNT, s,
                                        trend_dir=TrendDir.UP, stated_value=2))
        assert r.status == VerificationStatus.VERIFIED

    def test_no_stated_count_ambiguous(self):
        s = [("Q1", 80), ("Q2", 90)]
        r = verify_claim(temporal_claim(Operation.CONSECUTIVE_COUNT, s,
                                        trend_dir=TrendDir.UP, stated_value=None))
        assert r.status == VerificationStatus.AMBIGUOUS
