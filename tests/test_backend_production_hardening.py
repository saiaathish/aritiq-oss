import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import backend.app as app_mod  # noqa: E402


@pytest.fixture(autouse=True)
def clear_rate_buckets():
    app_mod._RATE_BUCKETS.clear()
    yield
    app_mod._RATE_BUCKETS.clear()


def test_api_key_required_when_configured(monkeypatch):
    monkeypatch.setenv("ARITIQ_API_KEYS", "secret")
    client = TestClient(app_mod.app)
    ex = app_mod.EXAMPLES[0]
    r = client.post("/audit", json={"source": ex["source"], "summary": ex["summary"]})
    assert r.status_code == 401
    r = client.post(
        "/audit",
        headers={"x-api-key": "secret"},
        json={"source": ex["source"], "summary": ex["summary"]},
    )
    assert r.status_code == 200


def test_rate_limit_applies_to_mutating_endpoints(monkeypatch):
    monkeypatch.delenv("ARITIQ_API_KEYS", raising=False)
    monkeypatch.setattr(app_mod, "RATE_LIMIT_PER_MINUTE", 1)
    client = TestClient(app_mod.app)
    ex = app_mod.EXAMPLES[0]
    payload = {"source": ex["source"], "summary": ex["summary"]}
    assert client.post("/audit", json=payload).status_code == 200
    assert client.post("/audit", json=payload).status_code == 429


def test_request_size_limit_rejects_large_summary(monkeypatch):
    monkeypatch.delenv("ARITIQ_API_KEYS", raising=False)
    monkeypatch.setattr(app_mod, "MAX_SUMMARY_CHARS", 5)
    client = TestClient(app_mod.app)
    r = client.post("/audit", json={"source": "source", "summary": "too long"})
    assert r.status_code == 422


def test_temporary_byok_does_not_persist(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with app_mod._temporary_byok("gemini", "request-key"):
        assert os.environ["GEMINI_API_KEY"] == "request-key"
    assert "GEMINI_API_KEY" not in os.environ
