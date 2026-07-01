"""
Cross-statement consistency test suite (Phase 2, spec §5).

Day-1-style discipline: these tests are written against the rule functions and
the verifier directly, with constructed ground truth.  No LLM, no API key.

Every rule is tested in the VERIFIED and WRONG_MATH direction, plus the edge
cases the spec enumerates:
  - within-tolerance rounding VERIFIES
  - divide-by-zero -> AMBIGUOUS (not a crash)
  - stated_value is None is handled for internal_consistency
  - a rule that doesn't apply emits no claim (extraction-side; see test below)
  - the EPS basic/diluted confound does NOT produce a false WRONG_MATH

The last one is, per the spec, "the most important test in the whole suite —
it's the test that proves you actually solved the confound in §4."
"""
import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, EPSVariant, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.core.rules import (
    check_balance_sheet_identity,
    check_eps_reconciliation,
    check_cash_flow_tie_out,
    run_internal_consistency_rule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ic_claim(rule_name, operand_values, *, eps_variant=None, shares_category=None,
             params=None):
    """Build an internal_consistency claim with grounded operands.

    By default this represents a claim with COMPLETE, well-scoped evidence (the
    normal correct-extraction case): balance-sheet liabilities flagged complete,
    EPS income bases matched as total/total. Pass `params` to override and
    exercise the evidence-gating (incomplete liabilities, mismatched basis, etc.).
    """
    ops = []
    for i, v in enumerate(operand_values):
        op = Operand(value=v, source=OperandSource.GROUNDED, source_text=str(v))
        # tag the shares operand (index 2) with a variant category if asked
        if shares_category and i == 2:
            op.category = shares_category
        ops.append(op)

    # Default completeness/scope evidence so a plain ic_claim represents a
    # correctly-extracted, complete claim. Tests override via `params`.
    default_params = {}
    if rule_name == "balance_sheet_identity":
        default_params = {"liabilities_complete": True}
    elif rule_name == "eps_reconciliation":
        default_params = {"eps_income_basis": "total", "income_operand_basis": "total"}
    if params:
        default_params.update(params)

    return Claim(
        claim_text=f"{rule_name} check",
        operation=Operation.INTERNAL_CONSISTENCY,
        stated_value=None,
        operands=ops,
        rule_name=rule_name,
        eps_variant=eps_variant,
        params=default_params,
    )


# ===========================================================================
# balance_sheet_identity
# ===========================================================================

class TestBalanceSheetIdentity:
    def test_verified(self):
        # 1500 == 900 + 600 exactly
        r = verify_claim(ic_claim("balance_sheet_identity", [1500.0, 900.0, 600.0]))
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong_math(self):
        # 1500 != 900 + 650
        r = verify_claim(ic_claim("balance_sheet_identity", [1500.0, 900.0, 650.0]))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_within_tolerance_verifies(self):
        # rounding-sized noise in millions: 1500.0 vs 899.4 + 600.5 = 1499.9 -> 0.0067% < 0.1%
        r = verify_claim(ic_claim("balance_sheet_identity", [1500.0, 899.4, 600.5]))
        assert r.status == VerificationStatus.VERIFIED

    def test_tolerance_fails_real_gap(self):
        # 0.5% gap is beyond the tight 0.1% balance-sheet tolerance
        r = verify_claim(ic_claim("balance_sheet_identity", [1500.0, 900.0, 592.0]))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_wrong_operand_count_ambiguous(self):
        cr = check_balance_sheet_identity([1500.0, 900.0])
        assert cr.status == VerificationStatus.AMBIGUOUS


# ===========================================================================
# eps_reconciliation
# ===========================================================================

class TestEPSReconciliation:
    def test_verified(self):
        # EPS 2.00 == 200M net income / 100M shares; variants must match to run.
        r = verify_claim(ic_claim("eps_reconciliation", [2.00, 200.0, 100.0],
                                  eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong_math(self):
        # stated 2.50 but 200/100 = 2.00, off by 50c >> 0.5c tolerance
        r = verify_claim(ic_claim("eps_reconciliation", [2.50, 200.0, 100.0],
                                  eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_half_cent_tolerance(self):
        # 200/99.8 = 2.004... ; stated 2.00 -> ~0.4c drift, within 0.5c -> VERIFIED
        r = verify_claim(ic_claim("eps_reconciliation", [2.00, 200.0, 99.8],
                                  eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.VERIFIED

    def test_two_cent_drift_fails(self):
        # 200/98 = 2.04 ; stated 2.00 -> 4c drift, beyond 0.5c -> WRONG_MATH
        r = verify_claim(ic_claim("eps_reconciliation", [2.00, 200.0, 98.0],
                                  eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_zero_shares_ambiguous(self):
        # divide-by-zero must be AMBIGUOUS, not a crash
        r = verify_claim(ic_claim("eps_reconciliation", [2.00, 200.0, 0.0],
                                  eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.AMBIGUOUS

    def test_no_variant_recorded_is_ambiguous(self):
        # THE BUG FIX: when neither eps_variant nor shares category is tagged,
        # the verifier must refuse to run rather than emit a WRONG_MATH that
        # cannot be distinguished from a basic/diluted mismatch.
        r = verify_claim(ic_claim("eps_reconciliation", [2.10, 240.0, 100.0]))
        assert r.status == VerificationStatus.AMBIGUOUS
        assert "unrecorded" in r.explanation.lower()


# ===========================================================================
# cash_flow_tie_out
# ===========================================================================

class TestCashFlowTieOut:
    def test_verified(self):
        # identical figures
        r = verify_claim(ic_claim("cash_flow_tie_out", [130.0, 130.0]))
        assert r.status == VerificationStatus.VERIFIED

    def test_wrong_math(self):
        # a real gap between the two statements' cash lines
        r = verify_claim(ic_claim("cash_flow_tie_out", [130.0, 125.0]))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_float_noise_verifies(self):
        # 0.001% gap is float noise, within the 0.01% tie-out tolerance
        r = verify_claim(ic_claim("cash_flow_tie_out", [130.000, 130.001]))
        assert r.status == VerificationStatus.VERIFIED


# ===========================================================================
# Schema wrinkle: stated_value is None for internal_consistency
# ===========================================================================

class TestStatedValueNone:
    def test_internal_consistency_stated_value_is_none(self):
        c = ic_claim("balance_sheet_identity", [1500.0, 900.0, 600.0])
        assert c.stated_value is None          # confirm the schema allows it
        r = verify_claim(c)
        # ... and it does NOT collapse to the Phase 1 "no stated_value" AMBIGUOUS.
        assert r.status == VerificationStatus.VERIFIED


# ===========================================================================
# Unknown rule name never guesses
# ===========================================================================

class TestUnknownRule:
    def test_unknown_rule_is_ambiguous(self):
        r = verify_claim(ic_claim("not_a_real_rule", [1.0, 2.0, 3.0]))
        assert r.status == VerificationStatus.AMBIGUOUS


# ===========================================================================
# The §4 confound — THE most important test in the suite
# ===========================================================================

class TestEPSVariantConfound:
    def test_eps_basic_diluted_mismatch_does_not_false_flag(self):
        """A stated BASIC eps compared against DILUTED shares must NOT WRONG_MATH.

        Diluted shares are larger, so net_income / diluted_shares < basic EPS.
        Without the §4 guard this would look like a wrong number. With the guard,
        the verifier refuses the apples-to-oranges comparison and returns
        AMBIGUOUS with an explanation — never a false WRONG_MATH.
        """
        # stated basic EPS = 2.00; basic shares would be 100M -> 200/100 = 2.00.
        # But we grounded DILUTED shares (110M) and tagged them as such.
        c = ic_claim(
            "eps_reconciliation",
            [2.00, 200.0, 110.0],
            eps_variant=EPSVariant.BASIC,
            shares_category="diluted",
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS
        assert "variant" in r.explanation.lower()
        # Crucially, NOT a false WRONG_MATH:
        assert r.status != VerificationStatus.WRONG_MATH

    def test_eps_matching_variant_still_verifies(self):
        """When the variants DO match, the check runs normally and verifies."""
        c = ic_claim(
            "eps_reconciliation",
            [2.00, 200.0, 100.0],
            eps_variant=EPSVariant.BASIC,
            shares_category="basic",
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED

    def test_eps_unknown_shares_variant_blocks_to_ambiguous(self):
        """If the shares variant is unknown (eps_variant set but shares untagged),
        the verifier must block to AMBIGUOUS — not run blind and risk a false
        WRONG_MATH that is actually a basic/diluted mismatch in disguise.

        This test was previously named test_eps_unknown_shares_variant_does_not_block
        and asserted VERIFIED — that was the bug. The fix (spec §4) requires
        AMBIGUOUS whenever variant information is incomplete on either side.
        """
        c = ic_claim("eps_reconciliation", [2.00, 200.0, 100.0],
                     eps_variant=EPSVariant.DILUTED, shares_category=None)
        r = verify_claim(c)
        assert r.status == VerificationStatus.AMBIGUOUS
        assert "unrecorded" in r.explanation.lower()
