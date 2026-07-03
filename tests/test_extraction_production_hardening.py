import json
import math

from aritiq.core.schema import Claim, Operand, Operation, VerificationStatus
from aritiq.core.verify import verify_claim
from aritiq.extract.schema import MAX_EXTRACTED_CLAIMS, parse_claims


def test_operation_and_source_aliases_normalized_before_validation():
    raw = json.dumps([{
        "claim_text": "Gross margin was 40%",
        "operation": "margin",
        "stated_value": 40,
        "operands": [
            {"value": 40, "source": "grounded_text"},
            {"value": 100, "source": "table_cell"},
        ],
    }])
    claims, issues = parse_claims(raw)
    assert not issues
    assert claims[0].operation == Operation.MARGIN_PERCENT
    assert claims[0].operands[0].source.value == "grounded"
    assert claims[0].operands[1].source.value == "grounded_table_cell"


def test_nonfinite_model_numbers_rejected_before_verifier():
    claims, issues = parse_claims('[{"claim_text":"x","operation":"sum","stated_value":NaN,"operands":[]}]')
    assert claims == []
    assert issues
    assert "non-finite" in issues[0].reason


def test_claim_count_cap_prevents_unbounded_model_output():
    item = {"claim_text": "x", "operation": "identity", "stated_value": 1,
            "operands": [{"value": 1, "source": "grounded"}]}
    raw = json.dumps([item for _ in range(MAX_EXTRACTED_CLAIMS + 5)])
    claims, issues = parse_claims(raw)
    assert len(claims) == MAX_EXTRACTED_CLAIMS
    assert any("capped" in i.reason for i in issues)


def test_verifier_rejects_programmatic_nan_claims_as_ambiguous():
    c = Claim(
        claim_text="bad",
        operation=Operation.SUM,
        stated_value=math.nan,
        operands=[Operand(1.0), Operand(2.0)],
    )
    r = verify_claim(c)
    assert r.status == VerificationStatus.AMBIGUOUS
    assert "Non-finite" in r.explanation
