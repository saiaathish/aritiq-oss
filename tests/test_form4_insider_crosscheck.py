import json

from aritiq.edgar.form4 import (
    fetch_recent_form4_transactions,
    parse_form4_xml,
    recent_form4_filings,
)
from benchmark.reliability import form4_insider_crosscheck as cross


FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>TEST</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane Insider</rptOwnerName></reportingOwnerId>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-01-02</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>25.50</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-01-03</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10</value></transactionShares>
        <transactionPricePerShare><value>20</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parse_form4_xml_transactions():
    txs = parse_form4_xml(FORM4_XML, ticker="TEST", accession="0001", filing_date="2026-01-04")
    assert len(txs) == 2
    assert txs[0].owner_name == "Jane Insider"
    assert txs[0].transaction_code == "S"
    assert txs[0].direction == "disposition"
    assert txs[0].value == 2550
    assert txs[1].direction == "acquisition"


def test_recent_form4_fetch_uses_accession_index_xml_not_xsl_primary_doc():
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-K", "4"],
                "accessionNumber": ["0000", "0000000000-26-000001"],
                "filingDate": ["2026-01-01", "2026-01-04"],
                "primaryDocument": ["annual.htm", "xslF345X06/form4.xml"],
            }
        }
    }
    ticker_map = {"0": {"cik_str": 1, "ticker": "TEST", "title": "Test Co"}}
    index = {"directory": {"item": [{"name": "form4.xml"}]}}

    def fetch(url):
        if "company_tickers" in url:
            return json.dumps(ticker_map)
        if "submissions" in url:
            return json.dumps(submissions)
        if url.endswith("index.json"):
            return json.dumps(index)
        if url.endswith("/form4.xml"):
            return FORM4_XML
        raise AssertionError(url)

    filings = recent_form4_filings("TEST", fetch=fetch)
    assert len(filings) == 1
    assert filings[0].xml_document == "form4.xml"
    txs = fetch_recent_form4_transactions("TEST", fetch=fetch)
    assert len(txs) == 2


def test_form4_crosscheck_surfaces_neutral_divergence(monkeypatch):
    class Point:
        period_end = "2025-12-31"
        value = 1000.0

    class Series:
        n_points = 1
        points = [Point()]

    txs = parse_form4_xml(FORM4_XML, ticker="TEST", accession="0001", filing_date="2026-01-04")
    monkeypatch.setattr(cross, "get_concept_series", lambda *a, **kw: Series())
    monkeypatch.setattr(cross, "fetch_recent_form4_transactions", lambda *a, **kw: txs)

    out = cross.crosscheck_ticker("TEST")
    assert out.status == "FACTUAL_DIVERGENCE_REVIEW"
    assert out.buyback_value == 1000.0
    assert out.net_disposition_shares == 90.0
    assert "not a legal judgment" in out.explanation
