"""
SEC EDGAR ingestion test suite.

NO NETWORK: every test injects a fake `fetch` callable returning canned SEC
responses, so the whole pipeline (ticker -> CIK -> latest 10-K -> strip ->
extract statements) is exercised deterministically and offline. A separate,
opt-in live smoke test (skipped by default) hits the real SEC endpoints.
"""
import json
import os

import pytest

from aritiq.edgar import (
    EdgarError, UnknownTickerError, NoFilingError, Filing,
    lookup_cik, latest_10k_filing, strip_html, extract_financial_statements,
    fetch_10k_text,
)


# ---------------------------------------------------------------------------
# Canned SEC responses + a router fetch fn
# ---------------------------------------------------------------------------

_TICKERS = json.dumps({
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
})

_SUBMISSIONS_AAPL = json.dumps({
    "filings": {"recent": {
        "form": ["8-K", "10-K", "4", "10-Q"],
        "accessionNumber": ["0000320193-25-000001", "0000320193-25-000079",
                            "0000320193-25-000002", "0000320193-25-000050"],
        "primaryDocument": ["x.htm", "aapl-20250927.htm", "y.htm", "q.htm"],
        "filingDate": ["2025-11-01", "2025-10-31", "2025-10-15", "2025-08-01"],
        "reportDate": ["2025-11-01", "2025-09-27", "2025-10-15", "2025-06-28"],
    }},
})

# A company that files no 10-K (e.g. a foreign filer with only 20-F).
_SUBMISSIONS_NO10K = json.dumps({
    "filings": {"recent": {
        "form": ["20-F", "6-K"],
        "accessionNumber": ["a", "b"],
        "primaryDocument": ["a.htm", "b.htm"],
        "filingDate": ["2025-03-01", "2025-02-01"],
        "reportDate": ["2024-12-31", "2025-01-31"],
    }},
})

# A realistic-shape fixture: the statement NAMES appear first in a table of
# contents and in MD&A prose (with few numbers), then the REAL statements appear
# later as dense number tables, then the notes. This mirrors how actual EDGAR
# 10-Ks are laid out and exercises the numeric-density anchor + min-gap logic.
_TOC_AND_MDA = (
    "<p>Table of Contents: Consolidated Statements of Operations 30; "
    "Consolidated Balance Sheets 31; Notes to Consolidated Financial Statements 34</p>"
    "<p>Item 7. Management Discussion and Analysis. " + ("Net sales grew steadily. " * 60) + "</p>"
)
# ~4000 chars of filler so the real statements are a meaningful distance from the
# TOC mentions and from the notes (exercises _MIN_SECTION_CHARS).
_FILLER = "<p>" + ("Additional discussion of results and risk factors. " * 90) + "</p>"

# Realistically-sized statements: a full income statement, balance sheet, and
# cash-flow statement with many line items — large enough (>2000 chars) that the
# notes heading sits beyond the min-useful-slice threshold, exactly like a real
# 10-K where the statements span several thousand characters.
_INCOME_ROWS = "".join(
    f"<tr><td>Line item {i}</td><td>${1000 + i},035</td><td>${900 + i},285</td><td>${800 + i},328</td></tr>"
    for i in range(40)
)
_BALANCE_ROWS = "".join(
    f"<tr><td>Asset/liab line {i}</td><td>${300 + i},980</td><td>${290 + i},583</td></tr>"
    for i in range(30)
)
_REAL_STATEMENTS = (
    "<h2>CONSOLIDATED STATEMENTS OF OPERATIONS</h2>"
    "<table><tr><td></td><td>2025</td><td>2024</td><td>2023</td></tr>"
    "<tr><td>Total net sales</td><td>$391,035</td><td>$383,285</td><td>$394,328</td></tr>"
    "<tr><td>Cost of sales</td><td>$210,352</td><td>$214,137</td><td>$223,546</td></tr>"
    "<tr><td>Net income</td><td>$93,736</td><td>$96,995</td><td>$99,803</td></tr>"
    + _INCOME_ROWS + "</table>"
    "<h2>CONSOLIDATED BALANCE SHEETS</h2>"
    "<table><tr><td></td><td>2025</td><td>2024</td></tr>"
    "<tr><td>Total assets</td><td>$364,980</td><td>$352,583</td></tr>"
    "<tr><td>Total liabilities</td><td>$308,030</td><td>$308,030</td></tr>"
    + _BALANCE_ROWS + "</table>"
    "<h2>CONSOLIDATED STATEMENTS OF CASH FLOWS</h2>"
    "<table><tr><td>Cash, ending balances</td><td>$29,943</td><td>$30,737</td></tr></table>"
)

_TENK_HTML = (
    "<html><head><style>.x{color:red}</style><script>var a=1;</script></head><body>"
    + _TOC_AND_MDA + _FILLER + _REAL_STATEMENTS
    + "<h2>NOTES TO CONSOLIDATED FINANCIAL STATEMENTS</h2>"
    + "<p>Note 1 — Summary of Significant Accounting Policies. Lots of prose here.</p>"
    + "</body></html>"
)


def make_fetch(tickers=_TICKERS, submissions=_SUBMISSIONS_AAPL, html=_TENK_HTML):
    def fetch(url: str) -> str:
        if "company_tickers.json" in url:
            return tickers
        if "submissions/CIK" in url:
            return submissions
        if url.endswith(".htm"):
            return html
        raise AssertionError(f"unexpected URL fetched: {url}")
    return fetch


# ===========================================================================
# ticker -> CIK
# ===========================================================================

class TestLookupCik:
    def test_resolves_known_ticker(self):
        cik, name = lookup_cik("AAPL", fetch=make_fetch())
        assert cik == 320193
        assert "Apple" in name

    def test_case_insensitive(self):
        cik, _ = lookup_cik("aapl", fetch=make_fetch())
        assert cik == 320193

    def test_unknown_ticker_raises(self):
        with pytest.raises(UnknownTickerError):
            lookup_cik("NOTATICKER", fetch=make_fetch())

    def test_empty_ticker_raises(self):
        with pytest.raises(UnknownTickerError):
            lookup_cik("  ", fetch=make_fetch())


# ===========================================================================
# CIK -> latest 10-K
# ===========================================================================

class TestLatest10K:
    def test_picks_the_10k_not_other_forms(self):
        f = latest_10k_filing("AAPL", 320193, "Apple Inc.", fetch=make_fetch())
        assert f.accession == "0000320193-25-000079"
        assert f.primary_document == "aapl-20250927.htm"
        assert f.filing_date == "2025-10-31"

    def test_document_url_is_well_formed(self):
        f = latest_10k_filing("AAPL", 320193, "Apple Inc.", fetch=make_fetch())
        assert f.document_url == (
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019325000079/aapl-20250927.htm"
        )

    def test_no_10k_raises(self):
        with pytest.raises(NoFilingError):
            latest_10k_filing("FORGN", 1, "Foreign Co",
                              fetch=make_fetch(submissions=_SUBMISSIONS_NO10K))


# ===========================================================================
# HTML stripping
# ===========================================================================

class TestStripHtml:
    def test_drops_script_and_style(self):
        out = strip_html(_TENK_HTML)
        assert "var a=1" not in out
        assert "color:red" not in out

    def test_keeps_figures_and_labels(self):
        out = strip_html(_TENK_HTML)
        assert "391,035" in out
        assert "Total net sales" in out
        assert "Net income" in out

    def test_decodes_entities(self):
        assert strip_html("<p>A&nbsp;&amp;&nbsp;B</p>").replace(" ", "") == "A&B"

    def test_empty_is_safe(self):
        assert strip_html("") == ""


# ===========================================================================
# financial-statements extraction
# ===========================================================================

class TestExtractStatements:
    def test_extracts_statements_drops_notes(self):
        text = strip_html(_TENK_HTML)
        section = extract_financial_statements(text)
        # statements present...
        assert "STATEMENTS OF OPERATIONS" in section.upper()
        assert "391,035" in section
        # ...notes prose excluded (it's after the end anchor)
        assert "Significant Accounting Policies" not in section

    def test_falls_back_when_no_anchor(self):
        # No statements heading at all -> capped head, never an exception.
        text = "Just some prose with a number 123 and no statement headings."
        section = extract_financial_statements(text)
        assert "123" in section

    def test_empty_is_safe(self):
        assert extract_financial_statements("") == ""


# ===========================================================================
# end-to-end (offline) ticker -> clean statements text
# ===========================================================================

class TestFetch10kText:
    def test_full_pipeline_offline(self):
        filing, text = fetch_10k_text("AAPL", fetch=make_fetch())
        assert isinstance(filing, Filing)
        assert filing.company == "Apple Inc."
        assert filing.ticker == "AAPL"
        assert "391,035" in text                 # a real figure survived
        assert "Significant Accounting Policies" not in text  # notes trimmed

    def test_statements_only_false_returns_more(self):
        _, full = fetch_10k_text("AAPL", fetch=make_fetch(), statements_only=False)
        _, trimmed = fetch_10k_text("AAPL", fetch=make_fetch(), statements_only=True)
        assert len(full) >= len(trimmed)
        # MD&A prose is in the full text but trimmed out of statements-only.
        assert "Management Discussion" in full

    def test_unknown_ticker_propagates(self):
        with pytest.raises(UnknownTickerError):
            fetch_10k_text("ZZZZ", fetch=make_fetch())


def test_fetch_10k_falls_back_to_statement_report_docs():
    submissions = json.dumps({
        "filings": {"recent": {
            "form": ["10-K"],
            "accessionNumber": ["0000000001-25-000001"],
            "primaryDocument": ["base10k.htm"],
            "filingDate": ["2025-03-01"],
            "reportDate": ["2024-12-31"],
        }},
    })
    index = json.dumps({"directory": {"item": [
        {"name": "base10k.htm"},
        {"name": "R3.htm"},
        {"name": "R5.htm"},
    ]}})
    base = "<html><body>PART I Business narrative only. No financial statements here.</body></html>"
    r3 = """
    <html><body><h1>Consolidated Statement Income</h1>
    Net income 57,048 Earnings per common share Diluted 20.02
    Weighted average shares outstanding diluted 2,781.5
    </body></html>
    """
    r5 = """
    <html><body><h1>Consolidated Balance Sheet</h1>
    Total assets 4,000,000 Total liabilities 3,700,000 Cash and cash equivalents 10,000
    </body></html>
    """

    def fetch(url):
        if "company_tickers" in url:
            return _TICKERS
        if "submissions" in url:
            return submissions
        if url.endswith("index.json"):
            return index
        if url.endswith("base10k.htm"):
            return base
        if url.endswith("R3.htm"):
            return r3
        if url.endswith("R5.htm"):
            return r5
        raise AssertionError(url)

    filing, text = fetch_10k_text("AAPL", fetch=fetch)
    assert filing.accession == "0000000001-25-000001"
    assert "INCORPORATED STATEMENT REPORT R3.htm" in text
    assert "Consolidated Statement Income" in text
    assert "Consolidated Balance Sheet" in text


# ===========================================================================
# Opt-in LIVE smoke test (hits real SEC; skipped unless ARITIQ_LIVE_SEC=1)
# ===========================================================================

@pytest.mark.skipif(os.environ.get("ARITIQ_LIVE_SEC") != "1",
                    reason="set ARITIQ_LIVE_SEC=1 to run the live SEC smoke test")
def test_live_sec_fetch_aapl():
    filing, text = fetch_10k_text("AAPL")
    assert filing.cik == 320193
    assert filing.primary_document.endswith(".htm")
    assert len(text) > 500
    # The statements region should contain Apple's net sales line.
    assert "net sales" in text.lower()
