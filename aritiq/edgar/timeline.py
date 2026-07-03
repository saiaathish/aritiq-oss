"""
SEC filing timeline — sequence a company's filings by type and date.

WHY THIS EXISTS
---------------
Aritiq verifies numbers inside individual filings (10-K/10-Q, partially 8-K).
An institutional reviewer also needs the SEQUENCE: what did this company file,
when, in what order — annual reports, quarterlies, current reports, proxies,
insider transactions. The SEC already publishes exactly this in the submissions
feed (`data.sec.gov/submissions/CIK{cik}.json` → `filings.recent`), the same
endpoint `sic.py` already uses for SIC lookup. This module reuses that pattern:
plain HTTP, cached JSON, no model, never raises out of a batch loop.

THE HONEST-COVERAGE RULE (the point of this module, not a footnote)
-------------------------------------------------------------------
Every timeline event carries an explicit `verification_coverage` label stating
what Aritiq can actually verify for that filing type. Implying verification
coverage that doesn't exist is exactly the overclaim this project's discipline
exists to prevent. The deterministic mapping:

- FULL  ("10-K", "10-Q"): measured financial verification — the benchmark's
  balance-sheet / EPS / cash-tie-out checks run against these (README table).
- PARTIAL ("8-K" WITH Item 2.02 in the feed's `items` field): only 8-Ks carrying
  an earnings exhibit have XBRL financials; verification is experimental/partial
  by nature of the form (STATUS.md Round 7). An 8-K WITHOUT Item 2.02 is
  LISTED_ONLY — no financial data to verify.
- OWNERSHIP ("4"): `form4.py` parses the ownership-transaction XML (who bought/
  sold what), but no financial-statement verification applies. The transaction
  figures are transcribed from the filer's XML, not independently verified.
- LISTED_ONLY (everything else — DEF 14A, S-1, 13D/13G, 13F, Forms 3/5, 144,
  and ALL amendments like 10-K/A): a dated entry with a link. Nothing more is
  claimed. Amendments are deliberately NOT given the base form's coverage —
  the benchmark measured "10-K", not "10-K/A".

NAMED LIMITATION: the submissions feed's `recent` block holds the most recent
1,000 filings OR the last full year, whichever is more (measured: AAPL/WELL get
exactly ~1,000 reaching back to 2015; JPM gets 25,252 covering one year, its
structured-notes prospectuses dominating). Older filings live in paginated
archive files this module does NOT fetch in v1; `has_older_filings` records
when they exist so the truncation is visible, never silent.

FIREWALL: no model SDK here; nothing in aritiq/core/ imports this.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .sec import lookup_cik, _default_fetch, FetchFn, EdgarError, SUBMISSIONS_URL

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)),
    "benchmark", "reliability", "cache", "timeline",
)

# --- verification-coverage labels (a closed enum, tested) -------------------
COVERAGE_FULL = "full_financial_verification"
COVERAGE_PARTIAL = "partial_financial_verification"
COVERAGE_OWNERSHIP = "ownership_data_only"
COVERAGE_LISTED = "listed_only"

ALL_COVERAGE_LEVELS = (
    COVERAGE_FULL, COVERAGE_PARTIAL, COVERAGE_OWNERSHIP, COVERAGE_LISTED,
)

# Human copy for UIs — ships with the data so no client invents its own claim.
COVERAGE_LEGEND: Dict[str, str] = {
    COVERAGE_FULL: (
        "Measured financial verification: balance-sheet identity, EPS "
        "reconciliation and cash tie-out run against this form (10-K/10-Q)."
    ),
    COVERAGE_PARTIAL: (
        "Partial/experimental: this 8-K carries an Item 2.02 earnings exhibit, "
        "the only 8-K variant with XBRL financials. Coverage is inherently "
        "partial — a property of the form, not a promise."
    ),
    COVERAGE_OWNERSHIP: (
        "Ownership data only: Form 4 insider transactions are parsed from the "
        "filer's XML but are not financially verified."
    ),
    COVERAGE_LISTED: (
        "Listed only: a dated entry with a link to EDGAR. Aritiq performs no "
        "verification on this filing type."
    ),
}

_FULL_FORMS = {"10-K", "10-Q"}
_ITEM_202 = "2.02"


def coverage_for_form(form: str, items: str = "") -> str:
    """Deterministic form → coverage mapping. Unknown forms are LISTED_ONLY —
    the safe default is to claim nothing."""
    form = (form or "").strip()
    if form in _FULL_FORMS:
        return COVERAGE_FULL
    if form == "8-K":
        item_list = [i.strip() for i in (items or "").split(",") if i.strip()]
        return COVERAGE_PARTIAL if _ITEM_202 in item_list else COVERAGE_LISTED
    if form == "4":
        return COVERAGE_OWNERSHIP
    return COVERAGE_LISTED


@dataclass
class FilingEvent:
    form: str
    filing_date: str            # ISO yyyy-mm-dd, from the feed
    report_date: str            # period of report ("" when the feed omits it)
    accession: str
    primary_document: str
    primary_doc_description: str
    items: str                  # 8-K item list as filed, e.g. "2.02,9.01"
    verification_coverage: str

    def document_url(self, cik: int) -> str:
        accn = self.accession.replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}"
        return f"{base}/{self.primary_document}" if self.primary_document else f"{base}/"


@dataclass
class CompanyTimeline:
    ticker: str
    cik: Optional[int] = None
    name: str = ""
    events: List[FilingEvent] = field(default_factory=list)
    has_older_filings: bool = False   # paginated archive files exist, not fetched (v1)
    fetch_error: Optional[str] = None

    def form_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self.events:
            out[e.form] = out.get(e.form, 0) + 1
        return out

    def coverage_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {c: 0 for c in ALL_COVERAGE_LEVELS}
        for e in self.events:
            out[e.verification_coverage] += 1
        return out


def _parse_recent(recent: dict) -> List[FilingEvent]:
    """Parse the parallel arrays of `filings.recent` into events, newest first."""
    forms = recent.get("form", []) or []
    n = len(forms)

    def col(name: str) -> list:
        c = recent.get(name, []) or []
        return c if len(c) == n else [""] * n  # ragged feed → blanks, never a crash

    filing_dates = col("filingDate")
    report_dates = col("reportDate")
    accessions = col("accessionNumber")
    primary_docs = col("primaryDocument")
    primary_descs = col("primaryDocDescription")
    items_col = col("items")

    events = [
        FilingEvent(
            form=str(forms[i] or ""),
            filing_date=str(filing_dates[i] or ""),
            report_date=str(report_dates[i] or ""),
            accession=str(accessions[i] or ""),
            primary_document=str(primary_docs[i] or ""),
            primary_doc_description=str(primary_descs[i] or ""),
            items=str(items_col[i] or ""),
            verification_coverage=coverage_for_form(str(forms[i] or ""),
                                                    str(items_col[i] or "")),
        )
        for i in range(n)
    ]
    # newest first; accession as a stable tiebreak for same-day filings
    events.sort(key=lambda e: (e.filing_date, e.accession), reverse=True)
    return events


def get_timeline(
    ticker: str,
    *,
    forms: Optional[List[str]] = None,
    limit: Optional[int] = None,
    fetch: Optional[FetchFn] = None,
    cache_dir: str = _DEFAULT_CACHE,
    use_cache: bool = True,
) -> CompanyTimeline:
    """Return the filing timeline for a ticker (cached, never raises).

    `forms`/`limit` filter AFTER the full parse so the cache always holds the
    complete recent window and a filtered call can't poison it.
    """
    fetch = fetch or _default_fetch
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{ticker.upper()}.json")

    tl: Optional[CompanyTimeline] = None
    if use_cache and os.path.exists(path):
        d = json.load(open(path))
        tl = CompanyTimeline(
            ticker=d["ticker"], cik=d.get("cik"), name=d.get("name", ""),
            events=[FilingEvent(**e) for e in d.get("events", [])],
            has_older_filings=d.get("has_older_filings", False),
        )

    if tl is None:
        tl = CompanyTimeline(ticker=ticker.upper())
        try:
            cik, company = lookup_cik(ticker, fetch=fetch)
            tl.cik = cik
            tl.name = company
            d = json.loads(fetch(SUBMISSIONS_URL.format(cik10=f"{cik:010d}")))
            if d.get("name"):
                tl.name = d["name"]
            filings = d.get("filings", {}) or {}
            tl.events = _parse_recent(filings.get("recent", {}) or {})
            tl.has_older_filings = bool(filings.get("files"))
            time.sleep(0.12)  # under SEC 10 req/sec, same as sic.py
        except EdgarError as e:
            tl.fetch_error = f"{type(e).__name__}: {e}"
        except Exception as e:
            tl.fetch_error = f"{type(e).__name__}: {str(e)[:180]}"

        # cache successful fetches only (don't pin a transient failure)
        if tl.fetch_error is None and tl.events:
            json.dump(
                {
                    "ticker": tl.ticker, "cik": tl.cik, "name": tl.name,
                    "has_older_filings": tl.has_older_filings,
                    "events": [asdict(e) for e in tl.events],
                },
                open(path, "w"),
            )

    if forms:
        wanted = {f.strip().upper() for f in forms}
        tl = CompanyTimeline(
            ticker=tl.ticker, cik=tl.cik, name=tl.name,
            events=[e for e in tl.events if e.form.upper() in wanted],
            has_older_filings=tl.has_older_filings, fetch_error=tl.fetch_error,
        )
    if limit is not None and limit >= 0:
        tl.events = tl.events[:limit]
    return tl


def form4_events_with_ownership(
    ticker: str,
    *,
    limit: int = 10,
    fetch: Optional[FetchFn] = None,
) -> List[dict]:
    """Form 4 timeline entries enriched with parsed ownership transactions.

    REUSES `form4.py` (per the roadmap: don't rebuild ownership parsing).
    Returns plain dicts: {event-fields..., transactions: [...]}. The
    transactions are parsed disclosures, not verified figures — the coverage
    label on the event stays OWNERSHIP_DATA_ONLY.
    """
    from .form4 import fetch_recent_form4_transactions  # lazy: network-heavy path

    txns = fetch_recent_form4_transactions(ticker, limit=limit, fetch=fetch)
    by_accession: Dict[str, List[dict]] = {}
    for t in txns:
        by_accession.setdefault(t.accession, []).append({
            "owner_name": t.owner_name,
            "transaction_date": t.transaction_date,
            "transaction_code": t.transaction_code,
            "direction": t.direction,
            "shares": t.shares,
            "price": t.price,
            "value": t.value,
            "security_title": t.security_title,
        })
    tl = get_timeline(ticker, forms=["4"], fetch=fetch)
    out = []
    for e in tl.events:
        if e.accession in by_accession:
            d = asdict(e)
            d["transactions"] = by_accession[e.accession]
            out.append(d)
    return out
