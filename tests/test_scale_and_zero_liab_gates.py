"""
Regression suite for the two gates added after the real 50-filer live benchmark.

Both gates were prompted by FALSE WRONG_MATH convictions produced from BAD
extractor operands (the verifier was correctly flagging real disagreement given
the operands it was handed; the operands were the problem). Each gate converts a
provably-impossible operand pattern into INSUFFICIENT_EVIDENCE instead of a false
conviction — a NEW gate, never a weakening of an existing one.

  Gate 1 — EPS unit-scale mismatch: net_income/shares off from stated_eps by an
           ORDER OF MAGNITUDE (>=20x) is a units artifact, not wrong math.
  Gate 2 — balance-sheet liabilities == 0 with non-zero assets & equity is an
           impossible value (always a grounding failure), so liabilities_complete
           cannot be trusted.

All values below are the REAL operands logged in
benchmark/reliability/cache/runs/run_1782857466_review.csv.
"""
from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, EPSVariant, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.core.rules import check_eps_reconciliation, check_balance_sheet_identity


def _eps(stated, ni, sh, *, basis_ok=True):
    return check_eps_reconciliation(
        [stated, ni, sh],
        eps_income_basis="total" if basis_ok else None,
        income_operand_basis="total" if basis_ok else None,
    )


def _bs(a, l, e, *, complete=True):
    return check_balance_sheet_identity([a, l, e], liabilities_complete=complete)


# ===========================================================================
# Gate 1 — EPS unit-scale mismatch (AAPL / CRM / SPG real values)
# ===========================================================================

class TestEPSScaleMismatchGate:
    def test_aapl_thousandfold_shares_is_insufficient(self):
        # AAPL: 112010 / 14,948,500 = 0.0075 vs stated 7.49 (~1000x off).
        r = _eps(7.49, 112010.0, 14948500.0)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert r.status != VerificationStatus.WRONG_MATH

    def test_crm_thousandfold_income_is_insufficient(self):
        # CRM: 7,457,000 / 950 = 7849 vs stated 7.85 (~1000x off).
        r = _eps(7.85, 7457000.0, 950.0)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_spg_thousandfold_income_is_insufficient(self):
        # SPG: 4,624,275 / 326.106 = 14181 vs stated 14.17 (~1000x off).
        r = _eps(14.17, 4624275.0, 326.106)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    # --- The gate must NOT swallow small, plausibly-genuine disagreements ---

    def test_bac_small_margin_still_wrong_math(self):
        # BAC: 30.0509e9 / 7.6809e9 = 3.91 vs stated 3.81 (~1.03x). Real
        # disagreement / wrong-line, NOT an order-of-magnitude artifact -> convict.
        r = _eps(3.81, 30050900000.0, 7680900000.0)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_pltr_diluted_small_margin_still_wrong_math(self):
        # PLTR diluted: 1,634,064 / 2,565,197 = 0.637 vs stated 0.63 (~1.01x).
        r = _eps(0.63, 1634064.0, 2565197.0)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_so_small_margin_still_wrong_math(self):
        # SO: 4171 / 1103 = 3.78 vs stated 3.94 (~1.04x).
        r = _eps(3.94, 4171.0, 1103.0)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_correct_pairing_still_verifies(self):
        # NVDA real basic: 120067 / 24359 = 4.929 vs 4.93 -> VERIFIED.
        r = _eps(4.93, 120067.0, 24359.0)
        assert r.status == VerificationStatus.VERIFIED

    def test_just_under_threshold_still_convicts(self):
        # 19x off is below the 20x gate -> normal tolerance path -> WRONG_MATH.
        # stated 1.00 vs computed 19.0 (190/10).
        r = _eps(1.00, 190.0, 10.0)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_at_threshold_is_gated(self):
        # exactly 20x off -> gated to INSUFFICIENT_EVIDENCE.
        r = _eps(1.00, 200.0, 10.0)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE


# ===========================================================================
# Gate 2 — zero-liabilities balance sheet (AMD real values)
# ===========================================================================

class TestZeroLiabilitiesGate:
    def test_amd_zero_liabilities_is_insufficient_not_wrong_math(self):
        # AMD: assets=76,926, liabilities=0, equity=62,936, liabilities_complete=true.
        # Liabilities of exactly 0 with real assets is impossible -> gate.
        r = _bs(76926.0, 0.0, 62936.0, complete=True)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert r.status != VerificationStatus.WRONG_MATH

    def test_zero_liab_gate_fires_even_through_verify_claim(self):
        c = Claim(
            claim_text="amd bs", operation=Operation.INTERNAL_CONSISTENCY,
            stated_value=None, rule_name="balance_sheet_identity",
            params={"liabilities_complete": True},
            operands=[Operand(value=76926.0), Operand(value=0.0), Operand(value=62936.0)],
        )
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_nonzero_mismatch_still_wrong_math(self):
        # TSLA: 137806 vs 54941+82137=137078 (off by 728, a real ~0.5% gap, likely a
        # dropped NCI/redeemable-equity line). NOT papered over -> stays WRONG_MATH.
        r = _bs(137806.0, 54941.0, 82137.0, complete=True)
        assert r.status == VerificationStatus.WRONG_MATH

    def test_zero_liab_but_zero_assets_not_falsely_gated(self):
        # If assets are also 0 (e.g. an empty/placeholder claim) the zero-liab gate
        # does NOT fire — it only targets the impossible "real assets, 0 liabilities"
        # pattern. With assets=0 it falls through to the normal completeness path.
        r = _bs(0.0, 0.0, 0.0, complete=True)
        assert r.status != VerificationStatus.INSUFFICIENT_EVIDENCE or True  # documents intent
        # (0==0+0 is within tolerance -> VERIFIED; the point is the zero-liab gate
        #  did not hijack it.)
        assert r.status == VerificationStatus.VERIFIED

    def test_real_balanced_sheet_still_verifies(self):
        # PLTR real: 8,900,392 = 1,412,381 + 7,488,011 exactly.
        r = _bs(8900392.0, 1412381.0, 7488011.0, complete=True)
        assert r.status == VerificationStatus.VERIFIED
