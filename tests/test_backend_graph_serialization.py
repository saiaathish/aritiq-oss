from aritiq.core.schema import Claim, Operand, Operation, VerificationResult, VerificationStatus
from backend.app import _serialize_result


def test_backend_serializes_claim_source_text_for_graph_detail():
    result = VerificationResult(
        claim=Claim(
            claim_text="tax is 10% of taxable base",
            operation=Operation.MARGIN_PERCENT,
            stated_value=10.0,
            operands=[Operand(450.0, source_text="Tax (10%): $450")],
            unit="%",
            source_text="Tax (10%): $450.00",
            node_id="tax_rate",
            depends_on=["net_pre_tax"],
        ),
        status=VerificationStatus.VERIFIED,
        recomputed_value=10.0,
    )

    out = _serialize_result(result)
    assert out["claim"]["source_text"] == "Tax (10%): $450.00"
    assert out["claim"]["depends_on"] == ["net_pre_tax"]
    assert out["claim"]["operands"][0]["source_text"] == "Tax (10%): $450"
