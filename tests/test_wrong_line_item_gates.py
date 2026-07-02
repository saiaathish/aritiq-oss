"""
Regression suite for the wrong_line_item safety nets (confirmed across 3 models:
Groq llama-4-scout, Gemini 2.5 Flash, Gemini 3.1 Flash Lite).

Two mechanisms, each a NEW verifier safety net following the restricted-cash
"trust the document over the extractor" precedent. Each fires ONLY when (a) the
deterministic check fails tolerance AND (b) the specific phrase is present in the
grounded context — never a blanket suppression, never touching a VERIFIED result.

  Mechanism 1 (EPS numerator): filers with preferred stock compute EPS on net
    income APPLICABLE TO COMMON (net of preferred dividends), not total net income.
  Mechanism 2 (BS equity): the identity holds against TOTAL equity INCLUDING
    noncontrolling interest, not parent-only stockholders' equity.

Real numbers from the latest live run.
"""
from aritiq.core.schema import (
    Claim, Operation, Operand, EPSVariant, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.core.rules import check_eps_reconciliation


def _eps_claim(stated, ni, shares, *, context, ni_text="Net income", basis="total"):
    return Claim(
        claim_text="EPS reconciliation",
        operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
        rule_name="eps_reconciliation", eps_variant=EPSVariant.BASIC,
        params={"eps_income_basis": basis, "income_operand_basis": basis},
        operands=[
            Operand(value=stated, category="basic", source_text=f"Basic EPS {stated}"),
            Operand(value=ni, source_text=f"{ni_text} {ni}"),
            Operand(value=shares, category="basic", source_text=f"shares {shares}"),
        ],
        source_text=context,
    )


def _bs_claim(assets, liab, equity, *, context, complete=True):
    return Claim(
        claim_text="balance sheet identity",
        operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
        rule_name="balance_sheet_identity",
        params={"liabilities_complete": complete},
        operands=[
            Operand(value=assets, category="total_assets", source_text=f"Total assets {assets}"),
            Operand(value=liab, category="total_liabilities", source_text=f"Total liabilities {liab}"),
            Operand(value=equity, category="total_equity", source_text=f"equity {equity}"),
        ],
        source_text=context,
    )


# ===========================================================================
# Mechanism 1 — EPS net income applicable to common (JPM)
# ===========================================================================

class TestEPSNetToCommonNet:
    def test_jpm_total_net_income_with_preferred_phrase_gates(self):
        # JPM: total NI 57,048 / 2,776.5 = 20.55 vs stated 20.05 -> fails tolerance.
        # Context names 'net income applicable to common' -> wrong-numerator artifact.
        c = _eps_claim(20.05, 57048.0, 2776.5,
                       context="Net income applicable to common stockholders 55,668")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_preferred_dividend_phrase_also_triggers(self):
        c = _eps_claim(20.05, 57048.0, 2776.5,
                       context="Less: Preferred stock dividends 1,380")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_jpm_correct_applicable_numerator_verifies(self):
        # When extraction grounds the RIGHT numerator (55,668), it reconciles.
        c = _eps_claim(20.05, 55668.0, 2776.5,
                       context="Net income applicable to common stockholders 55,668")
        assert verify_claim(c).status == VerificationStatus.VERIFIED

    def test_no_preferred_phrase_same_gap_still_wrong_math(self):
        # No preferred / applicable-to-common language anywhere -> a genuine
        # disagreement must still convict (net must be evidence-gated, not blanket).
        c = _eps_claim(20.05, 57048.0, 2776.5,
                       context="ordinary income statement, no preferred stock")
        assert verify_claim(c).status == VerificationStatus.WRONG_MATH

    def test_passing_eps_with_preferred_phrase_unaffected(self):
        # A correct EPS with preferred language present must STILL verify — the net
        # only ever downgrades a FAILING check.
        c = _eps_claim(4.93, 120067.0, 24359.0,
                       context="Net income applicable to common shareholders 120,067")
        assert verify_claim(c).status == VerificationStatus.VERIFIED


# ===========================================================================
# Mechanism 2 — balance sheet total equity incl. NCI (TSLA)
# ===========================================================================

class TestBSTotalEquityNCI:
    def test_tsla_parent_only_equity_with_nci_phrase_gates(self):
        # TSLA: 54,941 + 82,137 = 137,078 vs assets 137,806 -> fails (parent-only
        # equity). Context names noncontrolling interest -> wrong-line-item artifact.
        c = _bs_claim(137806.0, 54941.0, 82137.0,
                      context="Noncontrolling interests in subsidiaries 728")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_redeemable_nci_phrase_also_triggers(self):
        c = _bs_claim(137806.0, 54941.0, 82137.0,
                      context="Redeemable noncontrolling interests 555")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_tsla_total_equity_incl_nci_verifies(self):
        # Grounding TOTAL equity incl. NCI (82,865) ties exactly.
        c = _bs_claim(137806.0, 54941.0, 82865.0,
                      context="Total equity including noncontrolling interests 82,865")
        assert verify_claim(c).status == VerificationStatus.VERIFIED

    def test_no_nci_phrase_same_gap_still_wrong_math(self):
        # No NCI language -> a genuine imbalance must still convict.
        c = _bs_claim(137806.0, 54941.0, 82137.0,
                      context="plain balance sheet with a real imbalance")
        assert verify_claim(c).status == VerificationStatus.WRONG_MATH

    def test_balanced_sheet_with_nci_phrase_unaffected(self):
        # A balanced sheet with NCI language present must STILL verify.
        c = _bs_claim(100.0, 60.0, 40.0,
                      context="noncontrolling interest line present but it balances")
        assert verify_claim(c).status == VerificationStatus.VERIFIED


# ===========================================================================
# The prior-round gates must remain intact (no interaction regressions)
# ===========================================================================

class TestUPREITMezzanineNCI:
    """SPG (Simon Property Group) — UPREIT mezzanine interest between liabilities
    and equity. Assets exceed liabilities + total equity by exactly the
    'limited partners' preferred interest in the Operating Partnership and
    noncontrolling redeemable interests' line. Real operands from the live run."""

    def test_spg_upreit_redeemable_phrase_gates(self):
        c = _bs_claim(40606466.0, 33901073.0, 6472087.0,
                      context="Limited partners' preferred interest in the Operating "
                              "Partnership and noncontrolling redeemable interests 233,306")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_noncontrolling_redeemable_word_order_gates(self):
        # The regex must catch "noncontrolling redeemable" (SPG's order), not only
        # "redeemable noncontrolling".
        c = _bs_claim(40606466.0, 33901073.0, 6472087.0,
                      context="noncontrolling redeemable interests 233,306")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_limited_partners_operating_partnership_gates(self):
        c = _bs_claim(40606466.0, 33901073.0, 6472087.0,
                      context="Limited partners' interest in the Operating Partnership")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_upreit_phrase_does_not_affect_balanced_sheet(self):
        # A balanced REIT sheet with UPREIT language present must STILL verify.
        c = _bs_claim(100.0, 60.0, 40.0,
                      context="limited partners' interest in the Operating Partnership")
        assert verify_claim(c).status == VerificationStatus.VERIFIED


class TestSORoundingBoundary:
    """SO (Southern Company) diluted EPS — the per-share rounding-tolerance fix.

    The filer publishes net income and shares rounded to whole millions and EPS to
    two decimals: 4,341 / 1,109 = 3.9143, which the filer's precise internal figures
    round to 3.92. The 0.0057 gap is FULLY EXPLAINED by the rounding of the published
    operands propagated through the division (Phase-1 `eps_rounding_tolerance`), so
    convicting it would be a false WRONG_MATH — exactly the over-conviction the Phase-1
    adjudication flagged for SO. The verifier now VERIFIES it, because the discrepancy
    is indistinguishable from input rounding, NOT because tolerance was blanket-widened:
    a genuine multi-cent error still convicts (see test_genuine_eps_error_still_convicts).
    """

    def test_so_diluted_within_published_rounding_band_verifies(self):
        # 4,341 / 1,109 = 3.9143; published 3.92. The gap (0.0057) is inside the
        # rounding band implied by operands rounded to whole millions -> VERIFIED.
        r = check_eps_reconciliation([3.92, 4341.0, 1109.0],
                                     eps_income_basis="total", income_operand_basis="total")
        assert r.status == VerificationStatus.VERIFIED

    def test_so_basic_verifies(self):
        # SO basic: 4,341 / 1,103 = 3.9347 ≈ 3.94 -> VERIFIED (within tolerance).
        r = check_eps_reconciliation([3.94, 4341.0, 1103.0],
                                     eps_income_basis="total", income_operand_basis="total")
        assert r.status == VerificationStatus.VERIFIED

    def test_genuine_eps_error_still_convicts(self):
        # NON-WEAKENING GUARD: a real multi-cent discrepancy (published 3.99 vs
        # 4,341 / 1,109 = 3.9143, a ~7.6-cent gap) is far beyond any input-rounding
        # band and MUST still convict. Proves the rounding tolerance only forgives
        # sub-rounding gaps, never a genuine arithmetic error.
        r = check_eps_reconciliation([3.99, 4341.0, 1109.0],
                                     eps_income_basis="total", income_operand_basis="total")
        assert r.status == VerificationStatus.WRONG_MATH


class TestPriorGatesIntact:
    def test_scale_gate_still_fires(self):
        c = _eps_claim(7.49, 112010.0, 14948500.0, context="in millions except per share")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_zero_liab_gate_still_fires(self):
        c = _bs_claim(76926.0, 0.0, 62936.0, context="balance sheet")
        assert verify_claim(c).status == VerificationStatus.INSUFFICIENT_EVIDENCE
