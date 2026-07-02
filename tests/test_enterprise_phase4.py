"""Phase 4 enterprise features: identity, audit history, watchlists, API keys, webhooks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import aritiq.enterprise as enterprise
import backend.app as app_module
from aritiq.edgar.timeline import COVERAGE_FULL, CompanyTimeline, FilingEvent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARITIQ_ENTERPRISE_DB", str(tmp_path / "enterprise.sqlite"))
    monkeypatch.delenv("ARITIQ_API_KEYS", raising=False)
    app_module._RATE_BUCKETS.clear()
    return TestClient(app_module.app)


def _bootstrap(client, *, limit=30):
    r = client.post(
        "/enterprise/bootstrap",
        json={
            "org_name": "Phase 4 QA",
            "user_email": "qa@example.com",
            "key_label": "qa",
            "limit_per_minute": limit,
        },
    )
    assert r.status_code == 200
    return r.json()["api_key"]["key"]


def _headers(key):
    return {"X-API-Key": key}


def _timeline(accession):
    return CompanyTimeline(
        ticker="FAKE",
        cik=320193,
        name="Fake Corp",
        events=[
            FilingEvent(
                form="10-K",
                filing_date="2026-02-01",
                report_date="2025-12-31",
                accession=accession,
                primary_document="fake.htm",
                primary_doc_description="10-K",
                items="",
                verification_coverage=COVERAGE_FULL,
            )
        ],
    )


def test_team_api_key_dashboard_and_per_key_rate_limit(client):
    key = _bootstrap(client, limit=1)

    first = client.get("/enterprise/team", headers=_headers(key))
    assert first.status_code == 200
    assert first.json()["org"]["name"] == "Phase 4 QA"

    second = client.get("/enterprise/team", headers=_headers(key))
    assert second.status_code == 429

    app_module._RATE_BUCKETS.clear()
    dashboard = client.get("/enterprise/api-keys", headers=_headers(key))
    assert dashboard.status_code == 200
    keys = dashboard.json()["api_keys"]
    assert keys[0]["label"] == "qa"
    assert keys[0]["usage"]["calls"] >= 1


def test_rotation_disables_old_key_and_returns_new_key(client):
    key = _bootstrap(client)
    key_id = client.get("/enterprise/api-keys", headers=_headers(key)).json()["api_keys"][0]["id"]

    rotated = client.post(f"/enterprise/api-keys/{key_id}/rotate", headers=_headers(key))
    assert rotated.status_code == 200
    new_key = rotated.json()["key"]

    assert client.get("/enterprise/team", headers=_headers(key)).status_code == 401
    assert client.get("/enterprise/team", headers=_headers(new_key)).status_code == 200


def test_audit_history_persists_completed_replay_audit(client):
    key = _bootstrap(client)
    example = app_module.EXAMPLES[0]

    audit = client.post(
        "/audit",
        json={"source": example["source"], "summary": example["summary"]},
        headers=_headers(key),
    )
    assert audit.status_code == 200
    audit_id = audit.json()["audit_history_id"]

    history = client.get("/enterprise/audits", headers=_headers(key))
    assert history.status_code == 200
    assert history.json()["audits"][0]["id"] == audit_id
    assert history.json()["audits"][0]["verdict_counts"]

    detail = client.get(f"/enterprise/audits/{audit_id}", headers=_headers(key))
    assert detail.status_code == 200
    assert detail.json()["result"]["score"] == audit.json()["score"]


def test_watchlist_check_reuses_timeline_and_queues_webhooks(client, monkeypatch):
    key = _bootstrap(client)
    calls = {"n": 0}

    def fake_timeline(ticker, *, limit=None, **kwargs):
        calls["n"] += 1
        return _timeline("0001-26-000001" if calls["n"] == 1 else "0001-26-000002")

    monkeypatch.setattr(app_module, "get_timeline", fake_timeline)

    assert client.post("/enterprise/webhooks", json={"url": "https://example.com/hook"}, headers=_headers(key)).status_code == 200
    assert client.post("/enterprise/watchlists", json={"ticker": "FAKE"}, headers=_headers(key)).status_code == 200

    first = client.post("/enterprise/watchlists/check", headers=_headers(key))
    assert first.status_code == 200
    assert first.json()["detected"] == []

    second = client.post("/enterprise/watchlists/check", headers=_headers(key))
    assert second.status_code == 200
    detected = second.json()["detected"]
    assert detected[0]["ticker"] == "FAKE"
    assert detected[0]["filing"]["accession"] == "0001-26-000002"
    assert detected[0]["webhooks_queued"] == 1


def test_webhook_dispatch_retry_then_success(tmp_path, monkeypatch):
    path = str(tmp_path / "enterprise.sqlite")
    created = enterprise.create_workspace("Org", "u@example.com", path=path)
    org_id = created["org"]["id"]
    hook = enterprise.add_webhook(org_id, "https://example.com/hook", path=path)
    wl = enterprise.add_watchlist(org_id, "FAKE", path=path)
    enterprise.enqueue_webhook_deliveries(
        org_id,
        watchlist_id=wl["id"],
        ticker="FAKE",
        accession="0001",
        filing={"accession": "0001"},
        path=path,
    )

    def fail(_url, _payload):
        raise RuntimeError("temporary failure")

    failed = enterprise.dispatch_due_webhooks(org_id, deliver=fail, path=path)
    assert failed == {"delivered": 0, "failed_or_retrying": 1}

    with enterprise.connect(path) as conn:
        conn.execute("UPDATE webhook_deliveries SET next_attempt_at = 0")
        conn.commit()

    sent_payloads = []
    ok = enterprise.dispatch_due_webhooks(
        org_id,
        deliver=lambda url, payload: sent_payloads.append((url, payload)),
        path=path,
    )
    assert ok == {"delivered": 1, "failed_or_retrying": 0}
    assert sent_payloads == [(hook["url"], {"accession": "0001", "event": "filing_detected", "filing": {"accession": "0001"}, "ticker": "FAKE"})]


def test_sqlite_wal_and_busy_timeout(tmp_path):
    import sqlite3
    import time
    path = str(tmp_path / "enterprise.sqlite")

    # 1. Verify PRAGMA journal_mode is WAL on a fresh connection
    conn_a = enterprise.connect(path)
    res = conn_a.execute("PRAGMA journal_mode").fetchone()
    assert res[0].lower() == "wal"

    # 2. Verify busy_timeout is set to 5000ms by default
    res_timeout = conn_a.execute("PRAGMA busy_timeout").fetchone()
    assert res_timeout[0] == 5000

    # 3. Test concurrent write contention and busy_timeout waiting
    conn_b = enterprise.connect(path)
    
    # Start a write transaction on connection A
    conn_a.execute("BEGIN IMMEDIATE")
    conn_a.execute("INSERT INTO orgs (name, created_at) VALUES ('Org A', '2026-07-02')")
    
    # Configure B to have a shorter timeout for testing purposes
    conn_b.execute("PRAGMA busy_timeout = 200")
    
    t0 = time.time()
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        conn_b.execute("BEGIN IMMEDIATE")
    duration = time.time() - t0
    
    # Confirm it failed due to locking
    assert "locked" in str(exc_info.value)
    # Confirm it waited/blocked for the duration of the timeout (~200ms) rather than failing instantly
    assert duration >= 0.15

    # Clean up transactions
    conn_a.execute("ROLLBACK")
    conn_a.close()
    conn_b.close()


