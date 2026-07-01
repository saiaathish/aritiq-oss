"""Structured SEC Form 4 ownership-transaction fetch/parse.

Form 4 filings include a raw XML document in the EDGAR accession directory.
SEC's `primaryDocument` may point to an HTML/XSL rendering path, so this module
uses the accession `index.json` to find the real `.xml` ownership document.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

from .sec import (
    ARCHIVE_DOC_URL,
    SUBMISSIONS_URL,
    FetchFn,
    _default_fetch,
    lookup_cik,
)


@dataclass
class Form4Filing:
    ticker: str
    cik: int
    accession: str
    filing_date: str
    xml_document: Optional[str]

    @property
    def accession_nodashes(self) -> str:
        return self.accession.replace("-", "")

    @property
    def xml_url(self) -> Optional[str]:
        if not self.xml_document:
            return None
        return ARCHIVE_DOC_URL.format(
            cik_int=self.cik,
            accn_nodashes=self.accession_nodashes,
            primary_doc=self.xml_document,
        )


@dataclass
class Form4Transaction:
    ticker: str
    accession: str
    filing_date: str
    owner_name: Optional[str]
    transaction_date: Optional[str]
    transaction_code: Optional[str]
    shares: float
    price: Optional[float]
    security_title: Optional[str]

    @property
    def value(self) -> Optional[float]:
        if self.price is None:
            return None
        return self.shares * self.price

    @property
    def direction(self) -> str:
        if self.transaction_code in {"P", "A", "M"}:
            return "acquisition"
        if self.transaction_code in {"S", "F", "D"}:
            return "disposition"
        return "other"


def _float_or_none(text: Optional[str]) -> Optional[float]:
    if text in (None, ""):
        return None
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def _archive_index_url(cik: int, accession: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/index.json"
    )


def _find_ownership_xml(cik: int, accession: str, *, fetch: FetchFn) -> Optional[str]:
    data = json.loads(fetch(_archive_index_url(cik, accession)))
    for item in data.get("directory", {}).get("item", []):
        name = item.get("name", "")
        if name.lower().endswith(".xml") and not name.lower().startswith("xsl"):
            return name
    return None


def recent_form4_filings(
    ticker: str,
    *,
    limit: int = 10,
    fetch: Optional[FetchFn] = None,
) -> List[Form4Filing]:
    fetch = fetch or _default_fetch
    cik, _company = lookup_cik(ticker, fetch=fetch)
    data = json.loads(fetch(SUBMISSIONS_URL.format(cik10=f"{cik:010d}")))
    recent = data.get("filings", {}).get("recent", {})
    out: List[Form4Filing] = []
    for i, form in enumerate(recent.get("form", [])):
        if form != "4":
            continue
        accession = recent["accessionNumber"][i]
        xml_doc = _find_ownership_xml(cik, accession, fetch=fetch)
        out.append(Form4Filing(
            ticker=ticker.upper(),
            cik=cik,
            accession=accession,
            filing_date=recent.get("filingDate", [""])[i],
            xml_document=xml_doc,
        ))
        if len(out) >= limit:
            break
    return out


def parse_form4_xml(xml_text: str, *, ticker: str, accession: str, filing_date: str) -> List[Form4Transaction]:
    root = ET.fromstring(xml_text)
    owner_name = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName")
    transactions: List[Form4Transaction] = []
    for node in root.findall(".//nonDerivativeTransaction"):
        shares = _float_or_none(node.findtext(".//transactionShares/value"))
        if shares is None:
            continue
        price = _float_or_none(node.findtext(".//transactionPricePerShare/value"))
        transactions.append(Form4Transaction(
            ticker=ticker.upper(),
            accession=accession,
            filing_date=filing_date,
            owner_name=owner_name,
            transaction_date=node.findtext(".//transactionDate/value"),
            transaction_code=node.findtext(".//transactionCoding/transactionCode"),
            shares=shares,
            price=price,
            security_title=node.findtext(".//securityTitle/value"),
        ))
    return transactions


def fetch_recent_form4_transactions(
    ticker: str,
    *,
    limit: int = 10,
    fetch: Optional[FetchFn] = None,
) -> List[Form4Transaction]:
    fetch = fetch or _default_fetch
    out: List[Form4Transaction] = []
    for filing in recent_form4_filings(ticker, limit=limit, fetch=fetch):
        if not filing.xml_url:
            continue
        xml_text = fetch(filing.xml_url)
        out.extend(parse_form4_xml(
            xml_text,
            ticker=ticker,
            accession=filing.accession,
            filing_date=filing.filing_date,
        ))
    return out
