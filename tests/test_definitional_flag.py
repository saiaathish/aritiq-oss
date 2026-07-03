"""
Logical / definitional flagging test suite (cross-statement, §3.4).

This feature is a FLAG, not a verifier.  The discipline under test: a
qualitative word ("flat") next to a number is detected and routed to
NEEDS_REVIEW with a note — never resolved with an invented numeric threshold.

These tests pin that discipline so a future change can't quietly turn the flag
into a fake verdict.
"""
import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.core.rules import detect_definitional_word, flag_definitional


class TestDetection:
    def test_detects_flat(self):
        assert detect_definitional_word("costs were flat year over year") == "flat"

    def test_detects_stable(self):
        assert detect_definitional_word("margins remained stable") == "stable"

    def test_detects_roughly(self):
        assert detect_definitional_word("revenue was roughly $1.2B") == "roughly"

    def test_no_false_positive_on_plain_number(self):
        assert detect_definitional_word("revenue grew 12% to $1.2B") is None

    def test_word_boundary_not_substring(self):
        # "flatten" should not match "flat"
        assert detect_definitional_word("the curve will flatten next year") is None


class TestRouting:
    def test_flat_with_number_needs_review(self):
        c = Claim(
            claim_text="costs were flat but the table shows a 4% increase",
            operation=Operation.DEFINITIONAL_FLAG,
            stated_value=None,
            operands=[],
            params={"nearby_number": 4.0},
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.NEEDS_REVIEW
        assert "flat" in r.explanation
        assert "4" in r.explanation

    def test_does_not_invent_a_verdict(self):
        """The crucial discipline: NEEDS_REVIEW is NOT VERIFIED or WRONG_MATH.
        We never decide whether 4% counts as 'flat'."""
        c = Claim(
            claim_text="spending was stable",
            operation=Operation.DEFINITIONAL_FLAG,
            stated_value=None,
            operands=[],
            params={"nearby_number": 4.0},
        )
        r = verify_claim(c)
        assert r.status not in (VerificationStatus.VERIFIED, VerificationStatus.WRONG_MATH)
        assert r.status == VerificationStatus.NEEDS_REVIEW

    def test_no_qualitative_word_is_unchecked(self):
        # If routed here by mistake but no qualitative word exists, it's UNCHECKED
        c = Claim(
            claim_text="revenue grew 12%",
            operation=Operation.DEFINITIONAL_FLAG,
            stated_value=None,
            operands=[],
            params={},
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.UNCHECKED

    def test_review_status_excluded_from_being_a_pass_or_fail(self):
        cr = flag_definitional("costs were flat", 4.0)
        assert cr.status == VerificationStatus.NEEDS_REVIEW
        assert cr.recomputed_value is None   # we computed nothing — that's the point
