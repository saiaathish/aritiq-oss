"""Offline tests for POST /analyst — monkeypatched data, no network, no key.

Pins the endpoint contract: refusals are decided pre-model and work keyless;
an answerable question without a configured key is a clear 503 (never a
keyless hallucination); unknown tickers 404.
"""
import pytest
from fastapi.testclient import TestClient

import backend.app as app_module


_RECORDS = [
    {"rule_name": "balance_sheet_identity", "operation": "internal_consistency",
     "verdict": "VERIFIED", "adjudication": None,
     "operand_values": [100.0, 60.0, 40.0], "evidence_emitted": True,
     "evidence_gate_satisfied": True, "node_id": None, "depends_on": [],
     "explanation": "within tolerance"},
    {"rule_name": "cash_flow_tie_out", "operation": "internal_consistency",
     "verdict": "INSUFFICIENT_EVIDENCE", "adjudication": None,
     "operand_values": [10.0, 11.0], "evidence_emitted": True,
     "evidence_gate_satisfied": True, "node_id": None, "depends_on": [],
     "explanation": "restricted cash 1.1B disclosed"},
]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(app_module, "_latest_replay_claim_records",
                        lambda ticker: _RECORDS if ticker == "FAKE" else None)
    monkeypatch.setattr(app_module, "_has_live_key", lambda: False)
    return TestClient(app_module.app)


def test_blocked_question_refuses_keyless_and_pre_model(client):
    r = client.post("/analyst", json={
        "ticker": "FAKE",
        "question": "Does the cash flow statement tie out to balance sheet cash?",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "refused_blocked"
    assert d["model_called"] is False
    assert d["answer"] is None
    assert d["blocking"] == [{"topic": "cash_flow_tie_out",
                              "status": "INSUFFICIENT_EVIDENCE"}]
    # the blocked claim's numbers never appear anywhere in the response
    body = r.text
    assert "1.1" not in body and '"10.0"' not in body


def test_answerable_question_without_key_is_503_not_a_guess(client):
    r = client.post("/analyst", json={
        "ticker": "FAKE", "question": "Does the balance sheet balance?",
    })
    assert r.status_code == 503
    assert "answerable from verified claims" in r.json()["detail"]


def test_unknown_ticker_404(client):
    r = client.post("/analyst", json={"ticker": "ZZZQ", "question": "EPS?"})
    assert r.status_code == 404


def test_answerable_question_with_key_returns_cited_answer(client, monkeypatch):
    monkeypatch.setattr(app_module, "_has_live_key", lambda: True)

    from aritiq.analyst import AnalystAnswer, ask_analyst as _real

    def fake_ask(question, ledger, complete_fn=None):
        if complete_fn is not None:
            # the endpoint's gate probe: run the REAL gates (the sentinel
            # complete_fn raises _NeedsModel when the question is answerable)
            return _real(question, ledger, complete_fn=complete_fn)
        # the narration call: stand in for the live model
        return AnalystAnswer(mode="answered", answer="Assets 100 [F1].",
                             citations=["F1"], model_called=True, guard="ok")

    monkeypatch.setattr(app_module, "ask_analyst", fake_ask)
    r = client.post("/analyst", json={
        "ticker": "FAKE", "question": "Does the balance sheet balance?",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "answered"
    assert d["citations"] == ["F1"]
