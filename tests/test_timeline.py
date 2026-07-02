"""Offline tests for aritiq/edgar/timeline.py — synthetic feed, no network.

Pins the properties that make the timeline honest:
- the coverage mapping never over-claims (unknown forms and ALL amendments are
  LISTED_ONLY; 8-K is PARTIAL only with Item 2.02),
- events sort newest-first with a stable tiebreak,
- filters/limits never poison the cache,
- a fetch failure records fetch_error instead of raising,
- has_older_filings surfaces the recent-window truncation.
"""
import json
import os

import pytest

from aritiq.edgar.timeline import (
    ALL_COVERAGE_LEVELS,
    COVERAGE_FULL,
    COVERAGE_LEGEND,
    COVERAGE_LISTED,
    COVERAGE_OWNERSHIP,
    COVERAGE_PARTIAL,
    CompanyTimeline,
    FilingEvent,
    coverage_for_form,
    get_timeline,
)
from aritiq.edgar.sec import TICKERS_URL, SUBMISSIONS_URL


# ---------------------------------------------------------------------------
# synthetic SEC responses
# ---------------------------------------------------------------------------

_TICKER_MAP = {"0": {"cik_str": 320193, "ticker": "FAKE", "title": "Fake Corp"}}

_RECENT = {
    "form":              ["10-Q", "8-K", "10-K", "4", "DEF 14A", "8-K", "10-K/A"],
    "filingDate":        ["2026-05-01", "2026-04-30", "2026-02-10", "2026-02-10",
                          "2026-03-15", "2026-01-05", "2026-02-20"],
    "reportDate":        ["2026-03-31", "2026-04-28", "2025-12-31", "2026-02-08",
                          "", "2026-01-05", "2025-12-31"],
    "accessionNumber":   ["0001-26-000001", "0001-26-000002", "0001-26-000003",
                          "0001-26-000004", "0001-26-000005", "0001-26-000006",
                          "0001-26-000007"],
    "primaryDocument":   ["q.htm", "ek.htm", "k.htm", "f4.xml", "", "ek2.htm", "ka.htm"],
    "primaryDocDescription": ["10-Q", "8-K", "10-K", "4", "DEF 14A", "8-K", "10-K/A"],
    "items":             ["", "2.02,9.01", "", "", "", "5.02", ""],
}

_SUBMISSIONS = {
    "name": "Fake Corp Inc",
    "filings": {"recent": _RECENT, "files": [{"name": "CIK0000320193-submissions-001.json"}]},
}


def _fake_fetch(url: str) -> str:
    if url == TICKERS_URL:
        return json.dumps(_TICKER_MAP)
    if url == SUBMISSIONS_URL.format(cik10=f"{320193:010d}"):
        return json.dumps(_SUBMISSIONS)
    raise AssertionError(f"unexpected URL fetched: {url}")


@pytest.fixture()
def cache_dir(tmp_path):
    return str(tmp_path / "timeline_cache")


# ---------------------------------------------------------------------------
# coverage mapping — the honesty contract
# ---------------------------------------------------------------------------

def test_coverage_full_forms():
    assert coverage_for_form("10-K") == COVERAGE_FULL
    assert coverage_for_form("10-Q") == COVERAGE_FULL


def test_coverage_8k_partial_only_with_item_202():
    assert coverage_for_form("8-K", "2.02,9.01") == COVERAGE_PARTIAL
    assert coverage_for_form("8-K", "5.02") == COVERAGE_LISTED
    assert coverage_for_form("8-K", "") == COVERAGE_LISTED
    # "2.02" must be an exact item, not a substring of another item
    assert coverage_for_form("8-K", "12.02") == COVERAGE_LISTED


def test_coverage_form4_is_ownership_only():
    assert coverage_for_form("4") == COVERAGE_OWNERSHIP


def test_coverage_never_overclaims_on_amendments_and_unknowns():
    # Amendments do NOT inherit the base form's measured coverage.
    assert coverage_for_form("10-K/A") == COVERAGE_LISTED
    assert coverage_for_form("10-Q/A") == COVERAGE_LISTED
    assert coverage_for_form("DEF 14A") == COVERAGE_LISTED
    assert coverage_for_form("S-1") == COVERAGE_LISTED
    assert coverage_for_form("13F-HR") == COVERAGE_LISTED
    assert coverage_for_form("SC 13D") == COVERAGE_LISTED
    assert coverage_for_form("SOME-FUTURE-FORM") == COVERAGE_LISTED
    assert coverage_for_form("") == COVERAGE_LISTED


def test_legend_covers_every_level():
    assert set(COVERAGE_LEGEND) == set(ALL_COVERAGE_LEVELS)
    for text in COVERAGE_LEGEND.values():
        assert text.strip()


# ---------------------------------------------------------------------------
# parsing / sorting / filtering
# ---------------------------------------------------------------------------

def test_timeline_parses_and_sorts_newest_first(cache_dir):
    tl = get_timeline("FAKE", fetch=_fake_fetch, cache_dir=cache_dir)
    assert tl.fetch_error is None
    assert tl.cik == 320193
    assert tl.name == "Fake Corp Inc"
    dates = [e.filing_date for e in tl.events]
    assert dates == sorted(dates, reverse=True)
    # same-day tiebreak (2026-02-10 has a 10-K and a Form 4): stable by accession desc
    same_day = [e for e in tl.events if e.filing_date == "2026-02-10"]
    assert [e.accession for e in same_day] == ["0001-26-000004", "0001-26-000003"]
    assert tl.has_older_filings is True


def test_every_event_has_a_known_coverage_level(cache_dir):
    tl = get_timeline("FAKE", fetch=_fake_fetch, cache_dir=cache_dir)
    assert tl.events
    for e in tl.events:
        assert e.verification_coverage in ALL_COVERAGE_LEVELS


def test_event_coverage_matches_form_rules(cache_dir):
    tl = get_timeline("FAKE", fetch=_fake_fetch, cache_dir=cache_dir)
    by_accession = {e.accession: e for e in tl.events}
    assert by_accession["0001-26-000003"].verification_coverage == COVERAGE_FULL      # 10-K
    assert by_accession["0001-26-000001"].verification_coverage == COVERAGE_FULL      # 10-Q
    assert by_accession["0001-26-000002"].verification_coverage == COVERAGE_PARTIAL   # 8-K w/ 2.02
    assert by_accession["0001-26-000006"].verification_coverage == COVERAGE_LISTED    # 8-K w/o 2.02
    assert by_accession["0001-26-000004"].verification_coverage == COVERAGE_OWNERSHIP # Form 4
    assert by_accession["0001-26-000005"].verification_coverage == COVERAGE_LISTED    # DEF 14A
    assert by_accession["0001-26-000007"].verification_coverage == COVERAGE_LISTED    # 10-K/A


def test_forms_filter_and_limit(cache_dir):
    tl = get_timeline("FAKE", forms=["10-K", "10-Q"], fetch=_fake_fetch,
                      cache_dir=cache_dir)
    assert {e.form for e in tl.events} == {"10-K", "10-Q"}
    tl2 = get_timeline("FAKE", limit=3, fetch=_fake_fetch, cache_dir=cache_dir)
    assert len(tl2.events) == 3


def test_filtered_call_does_not_poison_cache(cache_dir):
    get_timeline("FAKE", forms=["4"], limit=1, fetch=_fake_fetch, cache_dir=cache_dir)
    # cache must hold the FULL timeline, not the filtered view
    raw = json.load(open(os.path.join(cache_dir, "FAKE.json")))
    assert len(raw["events"]) == len(_RECENT["form"])


def test_cache_hit_does_not_refetch(cache_dir):
    get_timeline("FAKE", fetch=_fake_fetch, cache_dir=cache_dir)
    calls = []

    def counting_fetch(url):
        calls.append(url)
        return _fake_fetch(url)

    tl = get_timeline("FAKE", fetch=counting_fetch, cache_dir=cache_dir)
    assert calls == []
    assert len(tl.events) == len(_RECENT["form"])


def test_document_url(cache_dir):
    tl = get_timeline("FAKE", fetch=_fake_fetch, cache_dir=cache_dir)
    e = next(x for x in tl.events if x.accession == "0001-26-000003")
    assert e.document_url(tl.cik) == (
        "https://www.sec.gov/Archives/edgar/data/320193/000126000003/k.htm"
    )
    # missing primary document -> index directory link, never a broken URL
    e5 = next(x for x in tl.events if x.accession == "0001-26-000005")
    assert e5.document_url(tl.cik).endswith("/000126000005/")


# ---------------------------------------------------------------------------
# failure behaviour
# ---------------------------------------------------------------------------

def test_fetch_failure_records_error_never_raises(cache_dir):
    def broken_fetch(url):
        raise OSError("network down")

    tl = get_timeline("FAKE", fetch=broken_fetch, cache_dir=cache_dir)
    assert tl.fetch_error is not None
    assert tl.events == []
    # a failure is NOT cached
    assert not os.path.exists(os.path.join(cache_dir, "FAKE.json"))


def test_ragged_feed_columns_do_not_crash(cache_dir):
    ragged = {
        "name": "Ragged Corp",
        "filings": {"recent": {
            "form": ["10-K", "8-K"],
            "filingDate": ["2026-01-01", "2026-01-02"],
            "accessionNumber": ["0001-26-000001"],  # shorter on purpose
        }},
    }

    def ragged_fetch(url):
        if url == TICKERS_URL:
            return json.dumps(_TICKER_MAP)
        return json.dumps(ragged)

    tl = get_timeline("FAKE", fetch=ragged_fetch, cache_dir=cache_dir)
    assert tl.fetch_error is None
    assert len(tl.events) == 2
    for e in tl.events:
        assert e.accession == ""  # blanked, not misaligned
        assert e.verification_coverage in ALL_COVERAGE_LEVELS
