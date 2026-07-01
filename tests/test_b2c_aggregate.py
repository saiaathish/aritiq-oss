"""
B2C aggregate_filter test suite (Phase 2, Axis C).

aggregate_filter sums/counts an already-filtered transaction subset, then that
result composes into the existing percent_change.  The categorization JUDGMENT
lives upstream and is surfaced via OperandSource.CATEGORY_INFERRED — these tests
confirm that a category-inferred operand is visibly different from a clean one,
so a "verified-but-recategorized" claim never quietly looks clean.
"""
import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.core.rules import check_aggregate_filter


def agg_claim(values, stated, *, mode="sum", category_inferred=False):
    ops = []
    for v in values:
        src = OperandSource.CATEGORY_INFERRED if category_inferred else OperandSource.GROUNDED
        op = Operand(value=float(v), source=src, source_text=str(v))
        if category_inferred:
            op.category = "dining"
            op.category_scheme_version = "v1.0"
        ops.append(op)
    return Claim(
        claim_text="aggregate claim",
        operation=Operation.AGGREGATE_FILTER,
        stated_value=float(stated) if stated is not None else None,
        operands=ops,
        params={"mode": mode},
    )


class TestAggregateSum:
    def test_sum_verified(self):
        # dining transactions summing to 420
        r = verify_claim(agg_claim([120, 80, 95, 125], 420))
        assert r.status == VerificationStatus.VERIFIED

    def test_sum_wrong(self):
        r = verify_claim(agg_claim([120, 80, 95, 125], 500))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_no_stated_value_ambiguous(self):
        r = verify_claim(agg_claim([120, 80], None))
        assert r.status == VerificationStatus.AMBIGUOUS

    def test_empty_operands_ambiguous(self):
        cr = check_aggregate_filter([], 0.0, mode="sum")
        assert cr.status == VerificationStatus.AMBIGUOUS


class TestAggregateCount:
    def test_count_verified(self):
        r = verify_claim(agg_claim([120, 80, 95, 125], 4, mode="count"))
        assert r.status == VerificationStatus.VERIFIED

    def test_count_wrong(self):
        r = verify_claim(agg_claim([120, 80, 95, 125], 5, mode="count"))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_unknown_mode_ambiguous(self):
        cr = check_aggregate_filter([1, 2, 3], 6.0, mode="median")
        assert cr.status == VerificationStatus.AMBIGUOUS


class TestCategoryInferredSurfaced:
    def test_category_inferred_is_flagged_in_explanation(self):
        """A correct sum over category-inferred operands still VERIFIES, but the
        explanation must SAY the verdict is conditional on categorization."""
        r = verify_claim(agg_claim([120, 80, 95, 125], 420, category_inferred=True))
        assert r.status == VerificationStatus.VERIFIED
        assert "category_inferred" in r.explanation
        assert "conditional" in r.explanation.lower()

    def test_clean_operand_has_no_conditional_note(self):
        r = verify_claim(agg_claim([120, 80, 95, 125], 420, category_inferred=False))
        assert r.status == VerificationStatus.VERIFIED
        assert "conditional" not in r.explanation.lower()

    def test_category_metadata_is_recorded(self):
        c = agg_claim([120, 80], 200, category_inferred=True)
        assert c.operands[0].source == OperandSource.CATEGORY_INFERRED
        assert c.operands[0].category == "dining"
        assert c.operands[0].category_scheme_version == "v1.0"


class TestCompositionIntoPercentChange:
    def test_aggregate_then_percent_change(self):
        """The roadmap's compositional pattern: an aggregate result feeds
        percent_change. Here we verify both stages independently with code."""
        # This month's dining = 420, last month's = 350.
        this_month = verify_claim(agg_claim([120, 80, 95, 125], 420))
        last_month = verify_claim(agg_claim([100, 90, 80, 80], 350))
        assert this_month.status == VerificationStatus.VERIFIED
        assert last_month.status == VerificationStatus.VERIFIED
        # "You spent 20% more on dining": (420-350)/350*100 = 20%
        pc = Claim(
            claim_text="20% more on dining",
            operation=Operation.PERCENT_CHANGE,
            stated_value=20.0,
            operands=[Operand(350.0, source=OperandSource.INFERRED, source_text="last-month dining aggregate"),
                      Operand(420.0, source=OperandSource.INFERRED, source_text="this-month dining aggregate")],
            unit="%",
        )
        assert verify_claim(pc).status == VerificationStatus.VERIFIED
