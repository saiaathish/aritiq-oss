"""
Aritiq verifier test suite.
Every operation is tested in both the VERIFIED and WRONG_MATH direction.
Edge cases (divide-by-zero, wrong operand counts, missing operands, qualitative)
are all covered.
"""
import pytest
from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, VerificationStatus
)
from aritiq.core.verify import verify_claim

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def grounded(value: float, text: str = "") -> Operand:
    return Operand(value=value, source=OperandSource.GROUNDED, source_text=text or str(value))

def missing_op() -> Operand:
    return Operand(value=0.0, source=OperandSource.MISSING)

def claim(text, op, stated, operands, unit=None):
    return Claim(
        claim_text=text,
        operation=op,
        stated_value=stated,
        operands=operands,
        unit=unit,
    )


# ---------------------------------------------------------------------------
# percent_change
# ---------------------------------------------------------------------------

class TestPercentChange:
    def test_correct(self):
        # (125 - 100) / 100 * 100 = 25%
        c = claim("Revenue rose 25%", Operation.PERCENT_CHANGE, 25.0,
                  [grounded(100), grounded(125)], unit="%")
        r = verify_claim(c, pct_tolerance=0.5, rel_tolerance=0.005)
        assert r.status == VerificationStatus.VERIFIED

    def test_motivating_example_wrong(self):
        # The build guide example: stated 30%, actual 25%
        c = claim("Revenue rose 30%", Operation.PERCENT_CHANGE, 30.0,
                  [grounded(100), grounded(125)], unit="%")
        r = verify_claim(c, pct_tolerance=0.5, rel_tolerance=0.005)
        assert r.status == VerificationStatus.WRONG_MATH
        assert abs(r.recomputed_value - 25.0) < 1e-9
        assert abs(r.delta - 5.0) < 1e-9

    def test_tolerance_passes_rounding(self):
        # Rounded source: $99.6M → $124.8M, stated 25.3% — within 0.5pp
        c = claim("~25% rise", Operation.PERCENT_CHANGE, 25.3,
                  [grounded(99.6), grounded(124.8)], unit="%")
        r = verify_claim(c, pct_tolerance=0.5, rel_tolerance=0.005)
        assert r.status == VerificationStatus.VERIFIED

    def test_tolerance_fails_real_error(self):
        # Stated 30%, actual 25.3% — delta 4.7pp, well outside 0.5pp
        c = claim("Revenue rose 30%", Operation.PERCENT_CHANGE, 30.0,
                  [grounded(99.6), grounded(124.8)], unit="%")
        r = verify_claim(c, pct_tolerance=0.5, rel_tolerance=0.005)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_divide_by_zero(self):
        c = claim("N/A", Operation.PERCENT_CHANGE, 10.0,
                  [grounded(0), grounded(10)], unit="%")
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS

    def test_wrong_operand_count(self):
        c = claim("N/A", Operation.PERCENT_CHANGE, 10.0,
                  [grounded(100)], unit="%")
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS

    def test_missing_operand(self):
        c = claim("N/A", Operation.PERCENT_CHANGE, 25.0,
                  [missing_op(), grounded(125)], unit="%")
        r = verify_claim(c)
        assert r.status == VerificationStatus.UNSUPPORTED_NUMBER


# ---------------------------------------------------------------------------
# absolute_change
# ---------------------------------------------------------------------------

class TestAbsoluteChange:
    def test_correct(self):
        c = claim("Revenue increased by $25M", Operation.ABSOLUTE_CHANGE, 25.0,
                  [grounded(100), grounded(125)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        c = claim("Revenue increased by $30M", Operation.ABSOLUTE_CHANGE, 30.0,
                  [grounded(100), grounded(125)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_wrong_operand_count(self):
        c = claim("N/A", Operation.ABSOLUTE_CHANGE, 25.0, [grounded(100)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# sum
# ---------------------------------------------------------------------------

class TestSum:
    def test_correct(self):
        c = claim("Total $300M", Operation.SUM, 300.0,
                  [grounded(100), grounded(125), grounded(75)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        c = claim("Total $310M", Operation.SUM, 310.0,
                  [grounded(100), grounded(125), grounded(75)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_too_few_operands(self):
        c = claim("N/A", Operation.SUM, 100.0, [grounded(100)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# difference
# ---------------------------------------------------------------------------

class TestDifference:
    def test_correct(self):
        c = claim("Net $75M", Operation.DIFFERENCE, 75.0,
                  [grounded(100), grounded(25)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        c = claim("Net $80M", Operation.DIFFERENCE, 80.0,
                  [grounded(100), grounded(25)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH


# ---------------------------------------------------------------------------
# ratio
# ---------------------------------------------------------------------------

class TestRatio:
    def test_correct(self):
        c = claim("Debt/equity ratio of 2.0", Operation.RATIO, 2.0,
                  [grounded(200), grounded(100)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        c = claim("Debt/equity ratio of 3.0", Operation.RATIO, 3.0,
                  [grounded(200), grounded(100)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_divide_by_zero(self):
        c = claim("N/A", Operation.RATIO, 2.0, [grounded(200), grounded(0)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# margin_percent
# ---------------------------------------------------------------------------

class TestMarginPercent:
    def test_correct(self):
        c = claim("Gross margin 40%", Operation.MARGIN_PERCENT, 40.0,
                  [grounded(40), grounded(100)], unit="%")
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        c = claim("Gross margin 45%", Operation.MARGIN_PERCENT, 45.0,
                  [grounded(40), grounded(100)], unit="%")
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_divide_by_zero(self):
        c = claim("N/A", Operation.MARGIN_PERCENT, 40.0,
                  [grounded(40), grounded(0)], unit="%")
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# average
# ---------------------------------------------------------------------------

class TestAverage:
    def test_correct(self):
        c = claim("Average $100M", Operation.AVERAGE, 100.0,
                  [grounded(80), grounded(100), grounded(120)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        c = claim("Average $110M", Operation.AVERAGE, 110.0,
                  [grounded(80), grounded(100), grounded(120)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_too_few_operands(self):
        c = claim("N/A", Operation.AVERAGE, 100.0, [grounded(100)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# product
# ---------------------------------------------------------------------------

class TestProduct:
    def test_correct(self):
        c = claim("Volume × price = $500M", Operation.PRODUCT, 500.0,
                  [grounded(50), grounded(10)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        c = claim("Volume × price = $600M", Operation.PRODUCT, 600.0,
                  [grounded(50), grounded(10)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_too_few_operands(self):
        c = claim("N/A", Operation.PRODUCT, 50.0, [grounded(50)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_correct(self):
        c = claim("Total revenue was $130M", Operation.IDENTITY, 130.0,
                  [grounded(130)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong(self):
        # Summary says $130M but source says $125M
        c = claim("Total revenue was $130M", Operation.IDENTITY, 130.0,
                  [grounded(125)], unit="$M")
        r = verify_claim(c)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_wrong_operand_count(self):
        c = claim("N/A", Operation.IDENTITY, 100.0,
                  [grounded(100), grounded(100)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# unsupported / qualitative
# ---------------------------------------------------------------------------

class TestUnsupported:
    def test_qualitative_is_unchecked(self):
        c = claim("The company improved its market position significantly.",
                  Operation.UNSUPPORTED, None, [])
        r = verify_claim(c)
        assert r.status == VerificationStatus.UNCHECKED


# ---------------------------------------------------------------------------
# No stated_value
# ---------------------------------------------------------------------------

class TestNoStatedValue:
    def test_no_stated_value_is_ambiguous(self):
        c = claim("Revenue increased", Operation.PERCENT_CHANGE, None,
                  [grounded(100), grounded(125)])
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS
