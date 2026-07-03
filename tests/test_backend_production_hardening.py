"""Backend hardening that still applies in the local-first build:
request size limits, and per-request BYOK that never persists a key.
"""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import backend.app as app_mod  # noqa: E402


def test_request_size_limit_rejects_large_summary(monkeypatch):
    monkeypatch.setattr(app_mod, "MAX_SUMMARY_CHARS", 5)
    client = TestClient(app_mod.app)
    r = client.post(
        "/audit",
        json={"source": "source", "summary": "too long"},
    )
    assert r.status_code == 422


def test_temporary_byok_does_not_persist(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with app_mod._temporary_byok("gemini", "request-key"):
        assert os.environ["GEMINI_API_KEY"] == "request-key"
    assert "GEMINI_API_KEY" not in os.environ
