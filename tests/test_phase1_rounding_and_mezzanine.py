"""
Phase-1 closure tests: the per-share rounding tolerance (Wayfair / SO / TRV class)
and the mezzanine / temporary-equity completeness gate (Welltower / UPREIT class).

Both fixes only ever RELAX a would-be WRONG_MATH into VERIFIED (rounding-explained)
or INSUFFICIENT_EVIDENCE (incomplete equity picture) — never the other way — and each
ships with a NON-WEAKENING guard proving a genuine error still convicts. See
benchmark/reliability/STATUS.md ("Phase 1 — closing the 7 WRONG_MATH cases").
"""
from aritiq.core.schema import (
    Claim, Operation, Operand, EPSVariant, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.core.rules import (
    check_eps_reconciliation,
    check_balance_sheet_identity,
    eps_rounding_tolerance,
    _decimal_half_ulp,
)


# ---------------------------------------------------------------------------
# Per-share rounding tolerance
# ---------------------------------------------------------------------------

class TestDecimalHalfUlp:
    def test_two_decimals(self):
        assert _decimal_half_ulp(3.31) == 0.005

    def test_one_decimal(self):
        assert abs(_decimal_half_ulp(224.2) - 0.05) < 1e-12

    def test_small_whole_number_is_half(self):
        # 6288 (millions-scale, no trailing zeros) -> ULP 1 -> half 0.5
        assert _decimal_half_ulp(6288.0) == 0.5

    def test_trailing_zeros_capped_relative(self):
        # 128000000 has six trailing zeros (reported to the nearest million) but the
        # inferred ULP is capped at 0.1% of the value so it can never blow up.
        hu = _decimal_half_ulp(128000000.0)
        assert hu <= 0.001 * 128000000.0
        assert hu > 0.0


class TestEpsRoundingTolerance:
    def test_wayfair_class_millions_scale_verifies(self):
        # W: -313 / 128 = -2.4453 vs published -2.44. Operands at millions scale;
        # the 0.0053 gap is inside the propagated rounding band -> VERIFIED.
        r = check_eps_reconciliation([-2.44, -313.0, 128.0],
                                     eps_income_basis="total", income_operand_basis="total")
        assert r.status == VerificationStatus.VERIFIED

    def test_wayfair_class_raw_units_verifies(self):
        # Same figure grounded in raw dollars/shares (the XBRL lane): trailing-zero
        # granularity recovers the same rounding band -> VERIFIED.
        r = check_eps_reconciliation([-2.44, -313000000.0, 128000000.0],
                                     eps_income_basis="total", income_operand_basis="total")
        assert r.status == VerificationStatus.VERIFIED

    def test_never_tighter_than_flat_floor(self):
        # Non-weakening: the effective tolerance is never below the pre-existing flat
        # half-cent floor, so nothing that verified before can flip to WRONG_MATH.
        assert eps_rounding_tolerance(3.31, 6835.0, 2064.5) >= 0.005

    def test_genuine_multicent_error_still_convicts(self):
        # A real ~7-cent discrepancy is far beyond any input-rounding band -> WRONG_MATH.
        r = check_eps_reconciliation([3.99, 4341.0, 1109.0],
                                     eps_income_basis="total", income_operand_basis="total")
        assert r.status == VerificationStatus.WRONG_MATH

    def test_gross_error_still_convicts(self):
        # 5.00 stated vs 3.91 computed — an unmistakable error, must convict.
        r = check_eps_reconciliation([5.00, 4341.0, 1109.0],
                                     eps_income_basis="total", income_operand_basis="total")
        assert r.status == VerificationStatus.WRONG_MATH


# ---------------------------------------------------------------------------
# Mezzanine / temporary-equity completeness gate
# ---------------------------------------------------------------------------

def _bs_claim(assets, liab, equity, *, context="", redeemable=None):
    params = {"liabilities_complete": True}
    if redeemable is not None:
        params["redeemable_equity_present"] = redeemable
    return Claim(
        claim_text="balance sheet identity",
        operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
        rule_name="balance_sheet_identity", params=params,
        operands=[
            Operand(value=assets, category="total_assets", source_text="assets"),
            Operand(value=liab, category="total_liabilities", source_text="liabilities"),
            Operand(value=equity, category="total_equity", source_text="equity"),
        ],
        source_text=context,
    )


class TestMezzanineGate:
    # Welltower: assets exceed liabilities + permanent equity by the redeemable/
    # mezzanine block (~0.39%). With the block disclosed, decline rather than convict.
    WELL = (67303047.0, 24100108.0, 42939716.0)

    def test_flag_declines_failing_tieout(self):
        r = check_balance_sheet_identity(list(self.WELL), liabilities_complete=True,
                                         redeemable_equity_present=True)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_context_phrase_declines_failing_tieout(self):
        c = _bs_claim(*self.WELL, context="redeemable noncontrolling interests")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_no_signal_still_convicts(self):
        # NON-WEAKENING: the same failing tie-out with NO mezzanine signal must still
        # convict — the gate never blanket-suppresses a balance-sheet failure.
        r = check_balance_sheet_identity(list(self.WELL), liabilities_complete=True,
                                         redeemable_equity_present=False)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_flag_does_not_touch_a_balanced_sheet(self):
        # A sheet that ties must still VERIFY even with the mezzanine flag set.
        r = check_balance_sheet_identity([100.0, 60.0, 40.0], liabilities_complete=True,
                                         redeemable_equity_present=True)
        assert r.status == VerificationStatus.VERIFIED
