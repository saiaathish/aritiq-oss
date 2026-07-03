"""
Evidence-completeness gating regression suite (the AMD-class bug defense).

The bug class: the verifier's math is correct, but the EXTRACTOR supplies an
incomplete or wrong-scope operand set (current-only liabilities, total income
paired with a continuing-ops EPS, restricted-cash gap). The old code convicted
with a confident WRONG_MATH. The fix: each rule gates on deterministic,
extractor-supplied completeness/scope evidence and returns INSUFFICIENT_EVIDENCE
(never WRONG_MATH) when that evidence is missing or contradictory.

Every test here is constructed ground truth, no LLM. The three reported AMD
scenarios are pinned explicitly as before/after regression guards.
"""
import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, EPSVariant, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.core.rules import (
    check_balance_sheet_identity,
    check_balance_sheet_identity_itemized,
    check_eps_reconciliation,
    check_cash_flow_tie_out,
)


def ic(rule_name, vals, *, params=None, eps_variant=None, shares_category=None,
       income_basis=None):
    ops = []
    for i, v in enumerate(vals):
        o = Operand(value=v, source=OperandSource.GROUNDED, source_text=str(v))
        if shares_category and i == 2:
            o.category = shares_category
        if income_basis and i == 1:
            o.category = income_basis
        ops.append(o)
    return Claim(claim_text=f"{rule_name}", operation=Operation.INTERNAL_CONSISTENCY,
                 stated_value=None, operands=ops, rule_name=rule_name,
                 eps_variant=eps_variant, params=params or {})


# ===========================================================================
# AMD #1 — balance-sheet tie-out missed long-term liabilities
# ===========================================================================

class TestAMD1BalanceSheetCompleteness:
    def test_current_only_liabilities_is_insufficient_not_wrong_math(self):
        # AMD shape: assets=100, but liabilities operand is CURRENT-only (=30),
        # equity=40. 30+40=70 != 100. OLD behavior: WRONG_MATH (false positive).
        # NEW: extractor flags incomplete -> INSUFFICIENT_EVIDENCE.
        r = verify_claim(ic("balance_sheet_identity", [100.0, 30.0, 40.0],
                            params={"liabilities_complete": False}))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert r.status != VerificationStatus.WRONG_MATH

    def test_no_completeness_evidence_is_insufficient(self):
        # Absence of evidence must NOT default to convicting.
        r = verify_claim(ic("balance_sheet_identity", [100.0, 30.0, 40.0]))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_complete_total_liabilities_balances_verifies(self):
        # Same assets, but now TOTAL liabilities (=60) flagged complete: 60+40=100.
        r = verify_claim(ic("balance_sheet_identity", [100.0, 60.0, 40.0],
                            params={"liabilities_complete": True}))
        assert r.status == VerificationStatus.VERIFIED

    def test_complete_but_genuinely_unbalanced_is_wrong_math(self):
        # Completeness asserted, but the numbers really don't balance -> a REAL
        # WRONG_MATH must still fire (we didn't blunt the true-positive).
        r = verify_claim(ic("balance_sheet_identity", [100.0, 70.0, 40.0],
                            params={"liabilities_complete": True}))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_itemized_components_complete_verifies(self):
        # Itemized: current 30 + long-term 30 = 60; + equity 40 = 100.
        r = check_balance_sheet_identity_itemized(
            100.0, [30.0, 30.0], 40.0, components_complete=True)
        assert r.status == VerificationStatus.VERIFIED

    def test_itemized_not_flagged_complete_is_insufficient(self):
        r = check_balance_sheet_identity_itemized(
            100.0, [30.0], 40.0, components_complete=None)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE


# ===========================================================================
# AMD #2 — EPS used total net income vs. continuing-operations EPS
# ===========================================================================

class TestAMD2EpsIncomeBasis:
    def test_continuing_eps_vs_total_income_is_insufficient(self):
        # stated EPS is continuing-ops (1.50), but net income is TOTAL (incl.
        # discontinued, =200) over 100 shares = 2.00. OLD: WRONG_MATH (false).
        # NEW: basis mismatch -> INSUFFICIENT_EVIDENCE.
        r = verify_claim(ic("eps_reconciliation", [1.50, 200.0, 100.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="diluted",
                            params={"eps_income_basis": "continuing",
                                    "income_operand_basis": "total"}))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert r.status != VerificationStatus.WRONG_MATH

    def test_matched_continuing_basis_verifies(self):
        # continuing EPS 1.50 vs continuing income 150 / 100 = 1.50.
        r = verify_claim(ic("eps_reconciliation", [1.50, 150.0, 100.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="diluted",
                            params={"eps_income_basis": "continuing",
                                    "income_operand_basis": "continuing"}))
        assert r.status == VerificationStatus.VERIFIED

    def test_matched_total_basis_verifies(self):
        r = verify_claim(ic("eps_reconciliation", [2.00, 200.0, 100.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="diluted",
                            params={"eps_income_basis": "total",
                                    "income_operand_basis": "total"}))
        assert r.status == VerificationStatus.VERIFIED

    def test_basis_on_one_side_only_is_insufficient(self):
        # Only the EPS side names a basis; cannot confirm the income matches.
        r = verify_claim(ic("eps_reconciliation", [1.50, 150.0, 100.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="diluted",
                            params={"eps_income_basis": "continuing"}))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_no_basis_tags_is_insufficient_not_blind_run(self):
        # THE GATE-GAP FIX: with NO income-basis tags at all, the check must NOT
        # run blind. A missing tag means the extractor didn't comply with the
        # prompt; running anyway is exactly how AMD #2 produced a false WRONG_MATH
        # when the income happened to be total but the EPS was continuing-ops.
        # The honest verdict is INSUFFICIENT_EVIDENCE — refuse to convict.
        r = verify_claim(ic("eps_reconciliation", [2.00, 200.0, 100.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert r.status != VerificationStatus.WRONG_MATH

    def test_amd2_untagged_income_basis_no_longer_false_wrong_math(self):
        # The precise AMD shape with NO basis tags (the real-world case): a
        # continuing-ops EPS of 1.50 sitting next to total net income 200 over
        # 100 shares (=2.00). Untagged, the OLD code ran and emitted WRONG_MATH.
        # Now it gates to INSUFFICIENT_EVIDENCE.
        r = verify_claim(ic("eps_reconciliation", [1.50, 200.0, 100.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_income_basis_via_operand_category(self):
        # The income basis can be tagged on the net-income operand's category,
        # not just params. continuing EPS vs total income (operand-tagged) -> gate.
        r = verify_claim(ic("eps_reconciliation", [1.50, 200.0, 100.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="diluted",
                            income_basis="total income",
                            params={"eps_income_basis": "continuing"}))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE


# ===========================================================================
# AMD #3 — restricted cash tie-out
# ===========================================================================

class TestAMD3RestrictedCash:
    def test_restricted_cash_flag_blocks_conviction(self):
        # Even a SMALL gap (within what might be tolerance for some) must not
        # convict once restricted cash is disclosed.
        r = check_cash_flow_tie_out([267.0, 241.0], restricted_cash_disclosed=True)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_disclosed_via_source_text_blocks_conviction(self):
        # The verifier's safety-net: disclosure in grounded context (no explicit
        # flag) still triggers the gate.
        c = ic("cash_flow_tie_out", [267.0, 241.0])
        c.source_text = "$26.0M difference attributable to restricted cash in escrow."
        r = verify_claim(c)
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_undisclosed_gap_is_still_wrong_math(self):
        # No restricted-cash signal: a real tie-out failure is still caught.
        r = verify_claim(ic("cash_flow_tie_out", [267.0, 241.0]))
        assert r.status == VerificationStatus.WRONG_MATH

    def test_clean_tie_out_verifies(self):
        r = verify_claim(ic("cash_flow_tie_out", [241.0, 241.0]))
        assert r.status == VerificationStatus.VERIFIED


# ===========================================================================
# Adjacent classes named in the audit brief
# ===========================================================================

class TestRelatedFinancialLines:
    def test_diluted_vs_basic_shares_still_guarded(self):
        # Regression: the existing basic/diluted guard must still hold alongside
        # the new income-basis guard. Diluted EPS vs basic shares -> AMBIGUOUS.
        r = verify_claim(ic("eps_reconciliation", [1.36, 112.0, 80.0],
                            eps_variant=EPSVariant.DILUTED, shares_category="basic",
                            params={"eps_income_basis": "total",
                                    "income_operand_basis": "total"}))
        assert r.status == VerificationStatus.AMBIGUOUS

    def test_margin_percent_unaffected(self):
        # Margins are a 2-operand ratio and are not evidence-gated; a correct one
        # still verifies, a wrong one still fails.
        good = Claim(claim_text="gross margin 35%", operation=Operation.MARGIN_PERCENT,
                     stated_value=35.0,
                     operands=[Operand(value=298.0), Operand(value=851.0)], unit="%")
        assert verify_claim(good).status == VerificationStatus.VERIFIED
        bad = Claim(claim_text="gross margin 50%", operation=Operation.MARGIN_PERCENT,
                    stated_value=50.0,
                    operands=[Operand(value=298.0), Operand(value=851.0)], unit="%")
        assert verify_claim(bad).status == VerificationStatus.WRONG_MATH

    def test_growth_rate_unaffected(self):
        good = Claim(claim_text="revenue grew 20%", operation=Operation.PERCENT_CHANGE,
                     stated_value=20.0,
                     operands=[Operand(value=710.0), Operand(value=851.0)], unit="%")
        assert verify_claim(good).status == VerificationStatus.VERIFIED


# ===========================================================================
# Real-filing regression scenarios (AMD and PLTR), exact reported figures.
# These pin the six manual-verification cases from the audit brief as unit tests.
# Money figures are in $M for AMD and $K for PLTR — scale is internally
# consistent within each scenario, which is all the ratio/identity checks need.
# ===========================================================================

class TestAMDRealFilingScenarios:
    def test_amd_balance_sheet_current_only_no_flag_is_insufficient(self):
        # AMD: assets=76,926, liabilities operand is CURRENT-only (=9,455),
        # equity=62,999. No liabilities_complete flag (extractor grabbed the
        # current subtotal and never confirmed completeness). 9455+62999=72454
        # != 76926. OLD: false WRONG_MATH. NEW: INSUFFICIENT_EVIDENCE.
        r = verify_claim(ic("balance_sheet_identity", [76926.0, 9455.0, 62999.0]))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert r.status != VerificationStatus.WRONG_MATH

    def test_amd_balance_sheet_complete_total_liabilities_verifies(self):
        # With the explicit Total liabilities row grounded (=13,927) and flagged
        # complete: 13927 + 62999 = 76926 == assets -> VERIFIED.
        r = verify_claim(ic("balance_sheet_identity", [76926.0, 13927.0, 62999.0],
                            params={"liabilities_complete": True}))
        assert r.status == VerificationStatus.VERIFIED

    def test_amd_eps_total_income_no_basis_tags_is_insufficient(self):
        # AMD EPS basic: stated=2.63, net_income=4,335 (TOTAL, incl. discontinued),
        # shares=1,624, NO basis tags. 4335/1624 = 2.669 != 2.63. Running blind
        # would emit a false WRONG_MATH; the gate returns INSUFFICIENT_EVIDENCE.
        r = verify_claim(ic("eps_reconciliation", [2.63, 4335.0, 1624.0],
                            eps_variant=EPSVariant.BASIC, shares_category="basic"))
        assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert r.status != VerificationStatus.WRONG_MATH

    def test_amd_eps_continuing_matched_basis_verifies(self):
        # AMD EPS continuing: stated=2.63, net_income=4,269 (continuing ops),
        # shares=1,624, matching continuing basis tags. 4269/1624 = 2.6287,
        # within 0.5c of 2.63 -> VERIFIED.
        r = verify_claim(ic("eps_reconciliation", [2.63, 4269.0, 1624.0],
                            eps_variant=EPSVariant.BASIC, shares_category="basic",
                            params={"eps_income_basis": "continuing",
                                    "income_operand_basis": "continuing"}))
        assert r.status == VerificationStatus.VERIFIED


class TestPLTRRealFilingScenarios:
    def test_pltr_balance_sheet_complete_verifies(self):
        # PLTR: assets=8,900,392, total_liabilities=1,412,381, equity=7,488,011,
        # liabilities_complete=true. 1,412,381 + 7,488,011 = 8,900,392 -> VERIFIED.
        r = verify_claim(ic("balance_sheet_identity",
                            [8900392.0, 1412381.0, 7488011.0],
                            params={"liabilities_complete": True}))
        assert r.status == VerificationStatus.VERIFIED

    def test_pltr_eps_basic_matched_basis_verifies(self):
        # PLTR EPS basic: stated=0.69, net_income=1,625,033, shares=2,369,612,
        # matching basis tags. 1,625,033 / 2,369,612 = 0.6858, rounds to 0.69
        # (within 0.5c) -> VERIFIED.
        r = verify_claim(ic("eps_reconciliation",
                            [0.69, 1625033.0, 2369612.0],
                            eps_variant=EPSVariant.BASIC, shares_category="basic",
                            params={"eps_income_basis": "total",
                                    "income_operand_basis": "total"}))
        assert r.status == VerificationStatus.VERIFIED


# ===========================================================================
# Scoring: INSUFFICIENT_EVIDENCE is excluded, never penalizes the summary
# ===========================================================================

class TestScoringExclusion:
    def test_insufficient_evidence_excluded_from_score(self):
        from aritiq.core.score import compute_score
        results = [
            verify_claim(Claim(claim_text="ok", operation=Operation.IDENTITY,
                               stated_value=5.0, operands=[Operand(value=5.0)])),
            verify_claim(ic("balance_sheet_identity", [100.0, 30.0, 40.0],
                            params={"liabilities_complete": False})),
        ]
        s = compute_score(results)
        # The INSUFFICIENT_EVIDENCE claim is excluded; only the VERIFIED counts.
        assert s.insufficient_evidence == 1
        assert s.total_checkable == 1
        assert s.score == 100.0


def test_jpm_preferred_stock_eps_total_income_gates_insufficient():
    r = verify_claim(ic(
        "eps_reconciliation",
        [20.02, 57048.0, 2781.5],
        eps_variant=EPSVariant.DILUTED,
        shares_category="diluted",
        params={
            "eps_income_basis": "total",
            "income_operand_basis": "total",
            "preferred_dividends_present": True,
        },
    ))
    assert r.status == VerificationStatus.INSUFFICIENT_EVIDENCE
    assert r.status != VerificationStatus.WRONG_MATH


def test_total_eps_can_reconcile_to_common_income_when_preferred_exists():
    r = verify_claim(ic(
        "eps_reconciliation",
        [20.02, 55668.0, 2780.6193806193808],
        eps_variant=EPSVariant.DILUTED,
        shares_category="diluted",
        params={
            "eps_income_basis": "total",
            "income_operand_basis": "common",
            "preferred_dividends_present": True,
        },
    ))
    assert r.status == VerificationStatus.VERIFIED
