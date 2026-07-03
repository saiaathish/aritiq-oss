"""Offline tests for GET /dashboard/{ticker} — monkeypatched data, no network.

Pins the surfacing contract of the risk dashboard: five deterministic panels, the
restatement panel UNASSESSED on single-filing data, and a clean 404 (not a
fabricated dashboard) when no cached verdicts exist.
"""
import pytest
from fastapi.testclient import TestClient

import backend.app as app_module


_RECORDS = [
    {
        "rule_name": "balance_sheet_identity", "operation": "internal_consistency",
        "verdict": "VERIFIED", "prose_verdict": "VERIFIED", "adjudication": None,
        "operand_values": [100.0, 60.0, 40.0], "evidence_emitted": True,
        "evidence_gate_satisfied": True, "node_id": None, "depends_on": [],
        "explanation": "ok",
    },
    {
        "rule_name": "cash_flow_tie_out", "operation": "internal_consistency",
        "verdict": "INSUFFICIENT_EVIDENCE", "prose_verdict": "INSUFFICIENT_EVIDENCE",
        "adjudication": None, "operand_values": [10.0, 11.0],
        "evidence_emitted": True, "evidence_gate_satisfied": True,
        "node_id": None, "depends_on": [], "explanation": "restricted cash disclosed",
    },
]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(app_module, "_latest_replay_claim_records",
                        lambda ticker: _RECORDS if ticker == "FAKE" else None)
    monkeypatch.setattr(app_module, "build_company_memory",
                        lambda ticker: (_ for _ in ()).throw(RuntimeError("no cache")))
    return TestClient(app_module.app)


def test_dashboard_shape_and_honesty(client):
    r = client.get("/dashboard/FAKE")
    assert r.status_code == 200
    d = r.json()
    assert d["ticker"] == "FAKE"
    keys = [p["key"] for p in d["panels"]]
    assert keys == ["verification_score", "evidence_coverage",
                    "disclosure_quality", "consistency_score", "restatement_risk"]
    panels = {p["key"]: p for p in d["panels"]}
    # single-filing input → restatement UNASSESSED, never a number
    assert panels["restatement_risk"]["state"] == "unassessed"
    assert panels["restatement_risk"]["value"] is None
    # memory build failed → consistency unassessed, endpoint still 200
    assert panels["consistency_score"]["state"] == "unassessed"
    # verification reflects the records (1 VERIFIED checkable → 100.0)
    assert panels["verification_score"]["value"] == 100.0
    assert panels["verification_score"]["components"]["insufficient_evidence"] == 1
    # the explained decline drives disclosure quality
    assert panels["disclosure_quality"]["components"]["explained"] == 1
    assert d["boundary"].startswith("All panels are deterministic")


def test_dashboard_404_when_no_cached_verdicts(client):
    r = client.get("/dashboard/ZZZQ")
    assert r.status_code == 404
    assert "No cached benchmark verdicts" in r.json()["detail"]
