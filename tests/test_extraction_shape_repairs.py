"""Regression tests for narrow extraction-shape repairs found in multi-document live demo.

The verifier stays strict. These tests pin parser-side cleanup for cases where
the live model provides the right grounded numbers but the wrong operation shape.
"""

from aritiq.core.schema import Operation, VerificationStatus
from aritiq.core.verify import verify_claim
from aritiq.extract import parse_claims


def test_repairs_gross_margin_identity_with_two_operands():
    raw = (
        '[{"claim_text":"Gross margin expanded to 35.0%",'
        '"operation":"identity","stated_value":35,'
        '"operands":[{"value":298,"source":"grounded"},'
        '{"value":851,"source":"grounded"}],"unit":"%"}]'
    )

    claims, issues = parse_claims(raw)

    assert not issues
    assert len(claims) == 1
    assert claims[0].operation == Operation.MARGIN_PERCENT
    assert [o.value for o in claims[0].operands] == [298, 851]
    assert verify_claim(claims[0]).status == VerificationStatus.VERIFIED


def test_repairs_eps_identity_with_contextual_share_operand():
    raw = (
        '[{"claim_text":"Diluted EPS was $1.36 on 82.4 million diluted shares",'
        '"operation":"identity","stated_value":1.36,'
        '"operands":[{"value":1.36,"source":"grounded","source_text":"$1.36"},'
        '{"value":82.4,"source":"grounded","source_text":"82.4 million"}]}]'
    )

    claims, issues = parse_claims(raw)

    assert not issues
    assert len(claims) == 1
    assert claims[0].operation == Operation.IDENTITY
    assert [o.value for o in claims[0].operands] == [1.36]
    assert verify_claim(claims[0]).status == VerificationStatus.VERIFIED
