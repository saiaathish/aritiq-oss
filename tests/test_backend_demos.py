"""Backend-surface demo tests across Aritiq phases.

These hit the FastAPI app through TestClient. The extractor/model call is
monkeypatched so tests stay deterministic and do not spend live API tokens.
"""

from fastapi.testclient import TestClient

import backend.app as backend
from aritiq.core.graph import propagate_errors
from aritiq.core.score import compute_score
from aritiq.core.schema import (
    Claim,
    Operation,
    Operand,
    OperandSource,
    RestatementType,
    VerificationResult,
    VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.pipeline import AuditResult


def _op(value: float, *, source_text: str = "") -> Operand:
    return Operand(value=value, source=OperandSource.GROUNDED, source_text=source_text)


def _fake_all_phase_audit(documents, summary):
    # summary-audit: clean arithmetic.
    revenue_growth = Claim(
        claim_text="Revenue grew 20% to $120M",
        operation=Operation.PERCENT_CHANGE,
        stated_value=20.0,
        operands=[_op(100, source_text="$100M"), _op(120, source_text="$120M")],
        unit="%",
        node_id="revenue_growth",
    )

    # cross-statement: disclosed restricted-cash tie-out should be INSUFFICIENT_EVIDENCE
    # (the evidence gate declines to convict), never a confident WRONG_MATH.
    cash_tie = Claim(
        claim_text="cash_flow_tie_out",
        operation=Operation.INTERNAL_CONSISTENCY,
        rule_name="cash_flow_tie_out",
        stated_value=None,
        operands=[
            _op(267, source_text="Cash and cash equivalents end of period $267M"),
            _op(
                241,
                source_text=(
                    "Balance sheet cash $241M. $26M difference attributable "
                    "to restricted cash held in escrow."
                ),
            ),
        ],
        unit="$M",
    )

    # multi-document the provenance graph: root failure with downstream propagated consequence.
    bad_base = Claim(
        claim_text="Base revenue was $999M",
        operation=Operation.IDENTITY,
        stated_value=999.0,
        operands=[_op(900, source_text="$900M")],
        node_id="bad_base",
        unit="$M",
    )
    downstream = Claim(
        claim_text="Downstream margin claim using bad base",
        operation=Operation.MARGIN_PERCENT,
        stated_value=10.0,
        operands=[_op(90, source_text="$90M"), _op(900, source_text="$900M")],
        node_id="downstream_margin",
        depends_on=["bad_base"],
        unit="%",
    )

    claims = [revenue_growth, cash_tie, bad_base, downstream]
    results = propagate_errors([verify_claim(c) for c in claims])

    # cross-statement/3 cross-document conflict + restatement disclosure annotation.
    conflict_claim = Claim(
        claim_text="Cross-document conflict on 'Total revenue / FY2024': A=740, B=710",
        operation=Operation.IDENTITY,
        stated_value=None,
        operands=[
            Operand(value=740, source=OperandSource.GROUNDED, doc_id="A_FY2024"),
            Operand(value=710, source=OperandSource.GROUNDED, doc_id="B_FY2025"),
        ],
    )
    conflict = VerificationResult(
        claim=conflict_claim,
        status=VerificationStatus.CONFLICT,
        explanation="Conflict on FY2024 revenue. Disclosure scan: EXPLICIT_RESTATEMENT.",
        restatement_type=RestatementType.EXPLICIT_RESTATEMENT,
    )
    results = list(results) + [conflict]
    score = compute_score(results, claims=claims)

    return AuditResult(
        score=score,
        results=results,
        claims=claims,
        issues=[],
        raw_response="deterministic backend demo",
        provider="test",
        model="test",
        conflicts=[conflict],
    )


def test_backend_audit_multi_serializes_all_phase_categories(monkeypatch):
    monkeypatch.setattr(backend, "_has_live_key", lambda: True)
    monkeypatch.setattr(backend, "run_audit_documents", _fake_all_phase_audit)

    client = TestClient(backend.app)
    response = client.post(
        "/audit-multi",
        json={
            "documents": [
                {"doc_id": "A_FY2024", "text": "Document A", "period": "FY2024"},
                {"doc_id": "B_FY2025", "text": "Document B", "period": "FY2025"},
            ],
            "summary": "demo summary",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    statuses = {r["status"] for r in data["results"]}

    assert "VERIFIED" in statuses
    assert "INSUFFICIENT_EVIDENCE" in statuses  # disclosed restricted-cash tie-out
    assert "WRONG_MATH" in statuses
    assert "PROPAGATED_ERROR" in statuses
    assert "CONFLICT" in statuses

    propagated = [r for r in data["results"] if r["status"] == "PROPAGATED_ERROR"]
    assert propagated[0]["caused_by"] == "bad_base"

    conflicts = data["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["restatement_type"] == "EXPLICIT_RESTATEMENT"

    score = data["score"]
    assert "score" in score
    assert "unweighted_score" in score
    assert score["propagated_error"] == 1
    assert score["conflict"] == 1
