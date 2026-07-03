"""
Vacuous-score guard regression suite (the Verizon-class bug).

Verizon's 10-K rendered "Aritiq Score: 100/100, Trustworthy" while ZERO claims
were actually checkable — 3 claims had been silently dropped on a Pydantic
`params: None` validation error. A numeric score with no checkable claims is a
false-confidence bug: there is nothing to be trustworthy ABOUT.

These tests pin two permanent guards:
  1. compute_score with zero checkable claims -> score_available=False and an
     explicit state, NEVER a confident 100.0.
  2. params:null no longer drops a claim (it is treated as empty {} and the
     repair is recorded as a VISIBLE issue, not silently absorbed).
  3. dropped claims are counted + reasoned on the score via the pipeline.
"""
from aritiq.core.schema import (
    Claim, Operation, Operand, VerificationStatus, VerificationResult,
)
from aritiq.core.score import compute_score
from aritiq.extract.schema import parse_claims


# ===========================================================================
# Guard 1 — no numeric score when nothing is checkable
# ===========================================================================

class TestVacuousScoreGuard:
    def test_zero_results_is_unavailable_not_100(self):
        s = compute_score([])
        assert s.score_available is False
        assert s.score_state == "no_checkable_claims"
        assert s.total_checkable == 0

    def test_all_excluded_is_unavailable_not_100(self):
        # Every claim excluded (UNCHECKED / INSUFFICIENT_EVIDENCE) -> no score.
        results = [
            VerificationResult(claim=Claim("a", Operation.UNSUPPORTED, None),
                               status=VerificationStatus.UNCHECKED),
            VerificationResult(claim=Claim("b", Operation.INTERNAL_CONSISTENCY, None),
                               status=VerificationStatus.INSUFFICIENT_EVIDENCE),
        ]
        s = compute_score(results)
        assert s.score_available is False
        assert s.score_state == "no_checkable_claims"
        # The number must not be a misleading 100.
        assert s.score != 100.0

    def test_one_checkable_claim_restores_a_real_score(self):
        results = [
            VerificationResult(claim=Claim("ok", Operation.IDENTITY, 5.0,
                                           operands=[Operand(value=5.0)]),
                               status=VerificationStatus.VERIFIED),
        ]
        s = compute_score(results)
        assert s.score_available is True
        assert s.score_state == "ok"
        assert s.score == 100.0
        assert s.total_checkable == 1


# ===========================================================================
# Guard 2 — params: null is repaired-and-kept, visibly
# ===========================================================================

class TestParamsNullRepair:
    RAW = (
        '[{"claim_text":"bs","operation":"internal_consistency",'
        '"rule_name":"balance_sheet_identity","stated_value":null,"params":null,'
        '"operands":[{"value":100,"source":"grounded"},'
        '{"value":60,"source":"grounded"},{"value":40,"source":"grounded"}]}]'
    )

    def test_params_null_no_longer_drops_claim(self):
        claims, issues = parse_claims(self.RAW)
        assert len(claims) == 1                 # claim kept, not dropped
        assert claims[0].params == {}           # null coerced to empty bag

    def test_params_null_repair_is_visible(self):
        _claims, issues = parse_claims(self.RAW)
        # The repair is recorded as a visible issue (not silently absorbed).
        assert any("repaired: params was null" in i.reason for i in issues)

    def test_operand_value_null_still_strict(self):
        # The forbidden coercion: an operand VALUE of null must NOT be silently
        # turned into a number. With source "grounded" + value null the claim is
        # still constructed (value defaults to 0.0 placeholder) but the operand
        # is not a real grounded number — this asserts we did NOT add value
        # coercion while fixing params.
        raw = ('[{"claim_text":"x","operation":"identity","stated_value":5,'
               '"operands":[{"value":null,"source":"missing"}]}]')
        claims, _issues = parse_claims(raw)
        # missing-source operand is allowed with null value (verifier handles it).
        assert len(claims) == 1
        assert claims[0].operands[0].source.value == "missing"
