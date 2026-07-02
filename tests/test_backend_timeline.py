"""Offline tests for GET /timeline/{ticker} — synthetic timeline, no network.

Pins the surfacing contract of Phase 3 item 1: the coverage label travels WITH
every event and the legend ships in the response, so no client can imply
verification coverage that doesn't exist.
"""
import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from aritiq.edgar.timeline import (
    ALL_COVERAGE_LEVELS,
    COVERAGE_FULL,
    COVERAGE_LISTED,
    COVERAGE_OWNERSHIP,
    COVERAGE_PARTIAL,
    CompanyTimeline,
    FilingEvent,
)


def _event(form, date, accn, items="", cov=COVERAGE_LISTED):
    return FilingEvent(
        form=form, filing_date=date, report_date="", accession=accn,
        primary_document="doc.htm", primary_doc_description=form,
        items=items, verification_coverage=cov,
    )


_FAKE_TL = CompanyTimeline(
    ticker="FAKE", cik=320193, name="Fake Corp Inc",
    events=[
        _event("10-K", "2026-02-10", "0001-26-000003", cov=COVERAGE_FULL),
        _event("8-K", "2026-01-30", "0001-26-000002", items="2.02,9.01",
               cov=COVERAGE_PARTIAL),
        _event("4", "2026-01-15", "0001-26-000004", cov=COVERAGE_OWNERSHIP),
        _event("DEF 14A", "2026-01-02", "0001-26-000005", cov=COVERAGE_LISTED),
    ],
    has_older_filings=True,
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ARITIQ_API_KEYS", "test-secret")

    def fake_get_timeline(ticker, *, forms=None, limit=None, **kw):
        tl = _FAKE_TL
        events = tl.events
        if forms:
            wanted = {f.strip().upper() for f in forms}
            events = [e for e in events if e.form.upper() in wanted]
        if limit is not None:
            events = events[:limit]
        return CompanyTimeline(
            ticker=tl.ticker, cik=tl.cik, name=tl.name, events=events,
            has_older_filings=tl.has_older_filings,
        )

    monkeypatch.setattr(app_module, "get_timeline", fake_get_timeline)
    return TestClient(app_module.app)


AUTH_HEADERS = {"x-api-key": "test-secret"}


def test_timeline_response_shape_and_legend(client):
    r = client.get("/timeline/FAKE", headers=AUTH_HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert d["ticker"] == "FAKE"
    assert d["cik"] == 320193
    assert d["has_older_filings"] is True
    # the legend ships with the data and covers the full closed enum
    assert set(d["coverage_legend"]) == set(ALL_COVERAGE_LEVELS)
    # every event carries its own coverage label
    assert len(d["events"]) == 4
    for e in d["events"]:
        assert e["verification_coverage"] in ALL_COVERAGE_LEVELS
        assert e["document_url"].startswith("https://www.sec.gov/Archives/")
    by_form = {e["form"]: e for e in d["events"]}
    assert by_form["10-K"]["verification_coverage"] == COVERAGE_FULL
    assert by_form["8-K"]["verification_coverage"] == COVERAGE_PARTIAL
    assert by_form["4"]["verification_coverage"] == COVERAGE_OWNERSHIP
    assert by_form["DEF 14A"]["verification_coverage"] == COVERAGE_LISTED


def test_timeline_forms_filter_and_limit(client):
    r = client.get(
        "/timeline/FAKE",
        params={"forms": "10-K,8-K", "limit": 1},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    d = r.json()
    assert len(d["events"]) == 1
    assert d["events"][0]["form"] == "10-K"


def test_timeline_bad_limit_rejected(client):
    assert client.get("/timeline/FAKE", params={"limit": 0}, headers=AUTH_HEADERS).status_code == 400
    assert client.get("/timeline/FAKE", params={"limit": 999999}, headers=AUTH_HEADERS).status_code == 400


def test_timeline_unknown_ticker_404(monkeypatch):
    monkeypatch.setenv("ARITIQ_API_KEYS", "test-secret")

    def failing_get_timeline(ticker, **kw):
        return CompanyTimeline(
            ticker=ticker.upper(),
            fetch_error="UnknownTickerError: Ticker 'ZZZQ' was not found",
        )

    monkeypatch.setattr(app_module, "get_timeline", failing_get_timeline)
    client = TestClient(app_module.app)
    assert client.get("/timeline/ZZZQ", headers=AUTH_HEADERS).status_code == 404


def test_timeline_requires_auth(client):
    assert client.get("/timeline/FAKE").status_code == 401
