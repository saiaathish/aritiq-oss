"""
Backend /audit-ticker endpoint test suite.

No network, no LLM: the EDGAR fetch and the audit are both monkeypatched, so
these pin the ENDPOINT's behavior (status codes, the `filing` block, error
mapping) deterministically. The fetch/strip logic itself is covered by
test_edgar.py; the audit logic by the pipeline suites.
"""
import json
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import backend.app as app_mod  # noqa: E402
from aritiq.edgar import Filing, UnknownTickerError, NoFilingError  # noqa: E402
from aritiq.pipeline import audit as real_audit  # noqa: E402


_FILING = Filing(
    ticker="AAPL", cik=320193, company="Apple Inc.",
    accession="0000320193-25-000079", primary_document="aapl-20250927.htm",
    filing_date="2025-10-31", period="20250927",
)
_SOURCE = "Total assets were $100M, total liabilities $60M, total equity $40M."


def _bs_audit(source, summary, **kw):
    """Run the real pipeline with an injected (no-LLM) cross-statement fixture."""
    cs = lambda s, u: json.dumps([{
        "claim_text": "BS identity", "operation": "internal_consistency",
        "rule_name": "balance_sheet_identity", "stated_value": None,
        "params": {"liabilities_complete": True},
        "operands": [{"value": 100, "source": "grounded"},
                     {"value": 60, "source": "grounded"},
                     {"value": 40, "source": "grounded"}], "unit": "$M",
    }])
    return real_audit(source, summary, complete_fn=lambda s, u: "[]", cs_complete_fn=cs)


# Endpoints require auth (anonymous access was removed); use a legacy test key.
_AUTH = {"X-API-Key": "test-secret"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    # A live key must appear present so the endpoint proceeds past the 503 guard.
    monkeypatch.setenv("ARITIQ_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("ARITIQ_API_KEYS", "test-secret")
    monkeypatch.setenv("ARITIQ_ENTERPRISE_DB", str(tmp_path / "enterprise.sqlite"))
    app_mod._RATE_BUCKETS.clear()
    return TestClient(app_mod.app)


def test_ticker_audit_returns_filing_block(client, monkeypatch):
    monkeypatch.setattr(app_mod, "fetch_10k_text", lambda t: (_FILING, _SOURCE))
    monkeypatch.setattr(app_mod, "run_audit", _bs_audit)

    r = client.post("/audit-ticker", headers=_AUTH, json={"ticker": "AAPL"})
    assert r.status_code == 200, r.text
    data = r.json()

    # The filing block describes what was fetched.
    assert data["filing"]["company"] == "Apple Inc."
    assert data["filing"]["ticker"] == "AAPL"
    assert data["filing"]["filing_date"] == "2025-10-31"
    assert data["filing"]["document_url"].startswith("https://www.sec.gov/Archives/edgar/data/")

    # The internal-consistency audit actually ran on the filing's numbers.
    statuses = [x["status"] for x in data["results"]]
    assert "VERIFIED" in statuses


def test_unknown_ticker_is_404(client, monkeypatch):
    def boom(t):
        raise UnknownTickerError("Ticker ZZZZ was not found in SEC's EDGAR database.")
    monkeypatch.setattr(app_mod, "fetch_10k_text", boom)
    r = client.post("/audit-ticker", headers=_AUTH, json={"ticker": "ZZZZ"})
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_no_10k_is_404(client, monkeypatch):
    def boom(t):
        raise NoFilingError("Foreign Co has no 10-K on file.")
    monkeypatch.setattr(app_mod, "fetch_10k_text", boom)
    r = client.post("/audit-ticker", headers=_AUTH, json={"ticker": "FORGN"})
    assert r.status_code == 404


def test_empty_ticker_is_400(client):
    r = client.post("/audit-ticker", headers=_AUTH, json={"ticker": "   "})
    assert r.status_code == 400


def test_missing_key_is_503(monkeypatch, tmp_path):
    # No key configured: the fetch succeeds but the audit can't run.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ARITIQ_PROVIDER", "anthropic")
    monkeypatch.setenv("ARITIQ_API_KEYS", "test-secret")
    monkeypatch.setenv("ARITIQ_ENTERPRISE_DB", str(tmp_path / "enterprise.sqlite"))
    monkeypatch.setattr(app_mod, "fetch_10k_text", lambda t: (_FILING, _SOURCE))
    app_mod._RATE_BUCKETS.clear()
    client = TestClient(app_mod.app)
    r = client.post("/audit-ticker", headers=_AUTH, json={"ticker": "AAPL"})
    assert r.status_code == 503
    # The message should confirm the fetch worked even though the audit couldn't.
    assert "EDGAR" in r.json()["detail"] or "key" in r.json()["detail"].lower()
