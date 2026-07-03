"""
SEC EDGAR fetch + strip — ticker → clean financial-statements text.

NO LLM.  NO COST.  Talks only to the SEC's free public endpoints:

    ticker  --(www.sec.gov/files/company_tickers.json)-->  CIK
    CIK     --(data.sec.gov/submissions/CIK##########.json)-->  latest 10-K
    filing  --(www.sec.gov/Archives/edgar/data/...)-->  raw HTML
    HTML    --(strip tags, extract statements section)-->  clean source text

Design choices that matter
--------------------------
* SEC requires a descriptive User-Agent on every request (they 403 generic
  clients).  It is set on every call and configurable via the ARITIQ_SEC_UA env
  var so a deployer can put their own contact in.
* Every network call goes through an injectable `fetch` callable
  (`(url) -> str`).  Tests pass a fake one, so the whole module runs with NO
  network — the same firewall-friendly pattern the extractor uses for the LLM.
* Stripping is deliberately conservative: drop <script>/<style>, convert tags to
  spaces, decode the handful of entities SEC filings actually use, collapse
  whitespace.  No external HTML library required, so deployment has zero extra
  dependencies.
* The financial-statements EXTRACTION narrows a ~200k-char 10-K down to the
  income statement / balance sheet / cash-flow region.  A full 10-K is too large
  and too noisy to audit whole; the statements are where every figure Aritiq
  checks actually lives.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

# (url) -> response body text.  Injectable for tests.
FetchFn = Callable[[str], str]

# SEC asks for a descriptive UA with contact info; they 403 without one.
SEC_USER_AGENT = os.environ.get(
    "ARITIQ_SEC_UA", "Aritiq Financial Auditor (contact: aritiq@example.com)"
)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
ARCHIVE_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodashes}/{primary_doc}"
ARCHIVE_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodashes}/index.json"


# ---------------------------------------------------------------------------
# Errors — typed so the API/UI can give a precise, friendly message.
# ---------------------------------------------------------------------------

class EdgarError(Exception):
    """Base class for any EDGAR ingestion failure."""


class UnknownTickerError(EdgarError):
    """The ticker isn't in SEC's ticker→CIK map (typo, foreign, delisted)."""


class NoFilingError(EdgarError):
    """The company exists but has no 10-K on file (e.g. files 20-F or 40-F)."""


@dataclass
class Filing:
    """The located latest 10-K and everything needed to fetch + label it."""
    ticker: str
    cik: int
    company: str
    accession: str          # e.g. "0000320193-25-000079"
    primary_document: str   # e.g. "aapl-20250927.htm"
    filing_date: str        # ISO date string
    period: Optional[str] = None  # report period (YYYYMMDD) if available

    @property
    def document_url(self) -> str:
        return ARCHIVE_DOC_URL.format(
            cik_int=self.cik,
            accn_nodashes=self.accession.replace("-", ""),
            primary_doc=self.primary_document,
        )


# ---------------------------------------------------------------------------
# Default network fetcher (urllib, no third-party deps beyond optional certifi)
# ---------------------------------------------------------------------------

def _ssl_context() -> "ssl.SSLContext":
    """Build an SSL context that can verify sec.gov's certificate.

    Some environments (minimal containers, certain CI/host images, fresh
    deploys) ship without a system CA bundle wired into Python's default SSL
    context, which makes verification fail with:

        [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate

    The fix is to point verification at a known-good CA bundle.  We use the
    `certifi` bundle when it's installed (the standard, portable source of CA
    roots), and otherwise fall back to Python's default context.  We never
    DISABLE verification — that would trade an SSL error for an insecure
    connection, which is the wrong fix for a tool that fetches financial filings.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        # certifi not installed (or unreadable): use the platform default, which
        # works wherever the system CA store is properly configured.
        return ssl.create_default_context()


# Built once and reused; cheap, and avoids re-reading the CA bundle per request.
_SSL_CONTEXT = _ssl_context()


def _default_fetch(url: str, *, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_USER_AGENT,
                                               "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
        raw = resp.read()
        enc = resp.headers.get("Content-Encoding", "")
        if enc == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            import zlib
            raw = zlib.decompress(raw)
        return raw.decode("utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Step 1: ticker -> CIK
# ---------------------------------------------------------------------------

def lookup_cik(ticker: str, *, fetch: Optional[FetchFn] = None) -> tuple[int, str]:
    """Resolve a ticker to its (CIK, company name).

    Raises UnknownTickerError if the ticker isn't in SEC's map.
    """
    fetch = fetch or _default_fetch
    norm = (ticker or "").strip().upper()
    if not norm:
        raise UnknownTickerError("No ticker provided.")
    try:
        data = json.loads(fetch(TICKERS_URL))
    except Exception as exc:  # network / parse
        raise EdgarError(f"Could not load SEC ticker list: {exc}") from exc

    # data is {"0": {"cik_str": int, "ticker": str, "title": str}, ...}
    for entry in data.values():
        if str(entry.get("ticker", "")).upper() == norm:
            return int(entry["cik_str"]), str(entry.get("title", norm))
    raise UnknownTickerError(
        f"Ticker {norm!r} was not found in SEC's EDGAR database. Check the symbol "
        f"(US-listed companies only; foreign filers that don't file a 10-K won't appear)."
    )


# ---------------------------------------------------------------------------
# Step 2: CIK -> latest 10-K filing
# ---------------------------------------------------------------------------

def latest_10k_filing(
    ticker: str,
    cik: int,
    company: str,
    *,
    fetch: Optional[FetchFn] = None,
) -> Filing:
    """Find the most recent 10-K for a CIK from the submissions feed.

    Raises NoFilingError if the company has no 10-K on file.
    """
    fetch = fetch or _default_fetch
    cik10 = f"{cik:010d}"
    try:
        data = json.loads(fetch(SUBMISSIONS_URL.format(cik10=cik10)))
    except Exception as exc:
        raise EdgarError(f"Could not load SEC submissions for CIK {cik}: {exc}") from exc

    recent = data.get("filings", {}).get("recent", {})
    forms: List[str] = recent.get("form", [])
    accns: List[str] = recent.get("accessionNumber", [])
    docs: List[str] = recent.get("primaryDocument", [])
    dates: List[str] = recent.get("filingDate", [])
    periods: List[str] = recent.get("reportDate", []) or recent.get("periodOfReport", [])

    for i, form in enumerate(forms):
        # Exact "10-K" only — exclude amendments (10-K/A) and 10-KSB variants so
        # we always audit a clean annual report.
        if form == "10-K":
            return Filing(
                ticker=ticker.upper(),
                cik=cik,
                company=company,
                accession=accns[i],
                primary_document=docs[i],
                filing_date=dates[i] if i < len(dates) else "",
                period=periods[i] if i < len(periods) else None,
            )
    raise NoFilingError(
        f"{company} (CIK {cik}) has no 10-K on file in its recent EDGAR submissions. "
        f"Foreign private issuers file 20-F/40-F instead, which Aritiq doesn't ingest yet."
    )


# ---------------------------------------------------------------------------
# Step 3: HTML -> clean text
# ---------------------------------------------------------------------------

# A few named entities SEC filings actually use; everything else is dropped.
_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&apos;": "'", "&#160;": " ", "&mdash;": "—", "&ndash;": "–", "&#8217;": "'",
    "&#8220;": '"', "&#8221;": '"', "&#8212;": "—", "&#8211;": "–",
}


def strip_html(html: str) -> str:
    """Strip an EDGAR HTML filing to readable plain text.

    Conservative and dependency-free: remove <script>/<style> blocks, convert
    every remaining tag to a space (so adjacent cells don't fuse), decode the
    handful of entities filings use, and collapse whitespace. Table structure is
    flattened to spaced numbers — which is exactly what the downstream extractor
    expects to read figures from.
    """
    if not html:
        return ""
    # Drop script/style wholesale (case-insensitive, across newlines).
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    # Treat block boundaries as spaces; tags become a single space.
    html = re.sub(r"(?i)<br\s*/?>", " ", html)
    html = re.sub(r"(?i)</(p|div|tr|table|td|th|li|h[1-6])>", " ", html)
    html = re.sub(r"<[^>]+>", " ", html)
    # Decode entities.
    for ent, rep in _ENTITIES.items():
        html = html.replace(ent, rep)
    # Remaining numeric/hex entities -> drop to space.
    html = re.sub(r"&#x?[0-9a-fA-F]+;", " ", html)
    html = re.sub(r"&[a-zA-Z]+;", " ", html)
    # Collapse whitespace.
    html = re.sub(r"[ \t ]+", " ", html)
    html = re.sub(r"\s*\n\s*", "\n", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


# ---------------------------------------------------------------------------
# Step 4: extract the financial-statements section
# ---------------------------------------------------------------------------

# Headings that mark the start of the primary financial statements. Ordered by
# how reliably they appear; the FIRST one found anchors the start.
_STATEMENT_START_ANCHORS = [
    "CONSOLIDATED STATEMENTS OF OPERATIONS",
    "CONSOLIDATED STATEMENT OF OPERATIONS",
    "CONSOLIDATED STATEMENTS OF INCOME",
    "CONSOLIDATED STATEMENT OF INCOME",
    "CONSOLIDATED BALANCE SHEETS",
    "CONSOLIDATED BALANCE SHEET",
    "STATEMENTS OF OPERATIONS",
    "BALANCE SHEETS",
]

# Headings that typically mark the END of the statements region (notes begin).
_STATEMENT_END_ANCHORS = [
    "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS",
    "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS",
    "NOTES TO FINANCIAL STATEMENTS",
    "REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
]

# The statements region is dense but bounded. Cap the slice so we never return
# the whole filing.
# Default cap for most filers. Banks/insurers run longer statements (the balance
# sheet sits far below the income statement), so the cap is raised when the slice
# still hasn't reached the balance-sheet identity (see extract_financial_statements).
_MAX_SECTION_CHARS = 24000
_MAX_SECTION_CHARS_WIDE = 60000   # bank/insurer fallback so the BS isn't cut off
# A statements slice shorter than this is almost certainly truncated by an end
# anchor that is really a sub-heading or cross-reference inside the statements
# (not the start of the notes).  When that happens we keep looking for a later
# end anchor, falling back to the max window — so we never hand back a slice too
# small to contain all three statements.
_MIN_USEFUL_CHARS = 2000


# A run of digits (with optional thousands separators / decimals), used to score
# how "tabular" a region is. The real statements are dense with these; the TOC
# and prose mentions of the same headings are not.
_NUMBER_RE = re.compile(r"\d[\d,]{2,}(?:\.\d+)?")
# Window after a heading used to judge numeric density.
_DENSITY_WINDOW = 2500


def _numeric_density(segment: str) -> int:
    """Count number-like tokens in a segment — a proxy for 'this is a real table'."""
    return len(_NUMBER_RE.findall(segment))


# A heading window must contain at least this many number-like tokens to count
# as a REAL primary statement rather than a table-of-contents / prose mention.
# Calibrated from real filings: TOC/prose mentions score ~2–11; the genuine
# income statement / balance sheet score ~50–120. A threshold in between cleanly
# separates them.  (Verified against AAPL TOC=11 vs real=97, GS real=51, MSFT=116.)
_MIN_STATEMENT_DENSITY = 25

# How far past an anchor to look when deciding whether this is the REAL statements
# region. The primary statements run several pages, so the balance-sheet identity
# rows can sit well after the first (income-statement) anchor. Large enough to
# span income statement -> balance sheet, bounded so the probe stays cheap.
_SECTION_PROBE = 20000

# A "Total assets" row followed by a large (>=6-digit) figure — the unmistakable
# signature of a real balance-sheet table, as opposed to a TOC/index that merely
# lists the statement names with page numbers.
_TOTAL_ASSETS_RE = re.compile(r"total\s+assets[^0-9]{0,40}\$?\s*[0-9][0-9,]{4,}", re.IGNORECASE)
_TOTAL_LIAB_OR_EQUITY_RE = re.compile(
    r"(total\s+liabilities|total\s+(?:stockholders|shareholders|shareowners)['’]?\s+equity|"
    r"total\s+equity|liabilities\s+and\s+(?:stockholders|shareholders|shareowners|equity))"
    r"[^0-9]{0,40}\$?\s*[0-9][0-9,]{4,}",
    re.IGNORECASE,
)


def _window_has_bs_identity(window: str) -> bool:
    """True if the window contains the balance-sheet identity rows with real
    figures (Total assets AND a Total liabilities / Total equity line). This is
    the content signature that distinguishes the genuine statements from a dense
    index or cross-reference list that only names them."""
    return bool(_TOTAL_ASSETS_RE.search(window)) and bool(_TOTAL_LIAB_OR_EQUITY_RE.search(window))


def _find_statements_start(text: str, upper: str) -> int:
    """Locate the REAL primary-statements heading.

    Failure mode this fixes (the JPM/GS bank-filer bug): bank 10-Ks contain
    EXTREMELY dense footnote tables (derivative fair values, credit netting) deep
    in the notes that out-score the genuine statements on raw numeric density. The
    old "globally densest window" rule therefore picked a footnote a megabyte into
    the document instead of the real balance sheet.

    Correct rule, in priority order:
      1. Among all start-anchor occurrences, keep only those whose following
         window is genuinely tabular (density >= _MIN_STATEMENT_DENSITY). This
         discards TOC and prose mentions, which have near-zero density.
      2. Of those, take the EARLIEST in document order. The primary statements
         always precede the notes/footnotes, so the first dense statements block
         is the real one — robust to filers that place statements inline (MSFT) or
         after the auditor's report (AAPL), and to banks whose footnotes are denser
         than their statements (JPM/GS).
      3. Fallback: if NOTHING clears the density threshold (an unusual filer), fall
         back to the globally densest window, preserving the old behavior rather
         than returning nothing.
    """
    qualifying = []   # (index, density, contains_bs_identity)
    densest_idx, densest_density = -1, -1
    for anchor in _STATEMENT_START_ANCHORS:
        i = upper.find(anchor)
        while i != -1:
            window = text[i:i + _SECTION_PROBE]
            density = _numeric_density(window[:_DENSITY_WINDOW])
            if density > densest_density:
                densest_density, densest_idx = density, i
            if density >= _MIN_STATEMENT_DENSITY:
                qualifying.append((i, density, _window_has_bs_identity(window)))
            i = upper.find(anchor, i + 1)

    if qualifying:
        # PREFER a window that actually contains the balance-sheet identity rows
        # ("Total assets ..." AND a "Total liabilities"/"equity" line with real
        # figures). This is what separates the GENUINE statements from a dense
        # auditor's-report index or a forward cross-reference list that merely
        # NAMES the statements (the GS failure: an early dense index out-ranked the
        # real balance-sheet table further down). Among windows that contain the
        # identity, take the EARLIEST; only if none do, fall back to the earliest
        # dense window, then to the globally densest.
        with_identity = [t for t in qualifying if t[2]]
        if with_identity:
            return min(with_identity, key=lambda t: t[0])[0]
        return min(qualifying, key=lambda t: t[0])[0]
    return densest_idx


def extract_financial_statements(text: str) -> str:
    """From stripped 10-K text, return just the primary financial-statements region.

    Strategy:
      1. Among ALL occurrences of the statement headings, pick the one actually
         followed by dense tabular numbers (not a table-of-contents or prose
         mention of the same name).  This is what makes it work on filers that
         put the statements at the end after the auditor's report (e.g. Apple)
         as well as inline (e.g. Microsoft).
      2. From there, slice forward to the first notes/auditor heading that is a
         meaningful distance past the start, bounded by a max width.
      3. Fall back to a capped head of the document if no heading is found, so
         the caller always gets auditable text, never an exception.
    """
    if not text:
        return ""
    upper = text.upper()

    start = _find_statements_start(text, upper)
    if start == -1:
        return text[:_MAX_SECTION_CHARS].strip()

    # Where does the balance-sheet identity finish, measured from `start`? The
    # slice MUST reach past it, or a bank's far-apart income-statement and balance
    # sheet get cut between (the JPM/BAC failure: Total assets captured but Total
    # liabilities cut off). We find the end of the identity region and never cut
    # before it.
    probe = text[start:start + _MAX_SECTION_CHARS_WIDE]
    identity_end = 0
    for rx in (_TOTAL_ASSETS_RE, _TOTAL_LIAB_OR_EQUITY_RE):
        for m in rx.finditer(probe):
            identity_end = max(identity_end, m.end())
    # Give a little trailing room so the last identity row isn't clipped.
    min_slice = max(_MIN_USEFUL_CHARS, identity_end + 500 if identity_end else 0)

    # Collect every end-anchor position after `start` and choose the EARLIEST one
    # that leaves a slice big enough to contain the full balance-sheet identity.
    # `start` is the real statements heading, but the first notes/auditor reference
    # after it is often a sub-heading or cross-reference INSIDE the statements; if
    # cutting there would drop part of the identity, we skip to the next end anchor.
    candidates = sorted(
        idx for anchor in _STATEMENT_END_ANCHORS
        for idx in [upper.find(anchor, start + 1)]
        if idx != -1
    )
    end = -1
    for idx in candidates:
        if idx - start >= min_slice:
            end = idx
            break
    # Cap: use the wide cap when the identity sits beyond the default cap (banks),
    # otherwise the default. Never return a slice that clips the identity.
    cap = _MAX_SECTION_CHARS_WIDE if min_slice > _MAX_SECTION_CHARS else _MAX_SECTION_CHARS
    if end == -1 or end - start > cap:
        end = min(len(text), start + cap)

    return text[start:end].strip()


_STATEMENT_FALLBACK_TERMS = (
    "consolidated balance sheet",
    "consolidated statement income",
    "consolidated statements of income",
    "consolidated statement of operations",
    "consolidated statements of operations",
    "consolidated statement of cash flows",
    "consolidated statements of cash flows",
    "total assets",
    "net income",
    "earnings per common share",
    "weighted average",
    "cash and cash equivalents",
)


def _statement_fallback_score(text: str) -> int:
    low = (text or "").lower()
    return sum(1 for term in _STATEMENT_FALLBACK_TERMS if term in low)


def _report_doc_order(name: str) -> int:
    m = re.fullmatch(r"r(\d+)\.htm", (name or "").lower())
    return int(m.group(1)) if m else 10_000


def _filing_doc_url(filing: Filing, primary_doc: str) -> str:
    return ARCHIVE_DOC_URL.format(
        cik_int=filing.cik,
        accn_nodashes=filing.accession.replace("-", ""),
        primary_doc=primary_doc,
    )


def _fetch_statement_exhibit_text(filing: Filing, fetch: FetchFn) -> Optional[str]:
    """Fallback for 10-Ks incorporating Item 8 by reference / report docs.

    Some filings' primary 10-K contains only cover/business text while the
    financial statements live in accession companion HTML reports (often
    SEC-generated R*.htm interactive-data reports, sometimes exhibits). We score
    sibling HTML docs and concatenate the best statement-bearing slices.
    """
    try:
        index = json.loads(fetch(ARCHIVE_INDEX_URL.format(
            cik_int=filing.cik,
            accn_nodashes=filing.accession.replace("-", ""),
        )))
    except Exception:
        return None

    candidates = []
    for item in index.get("directory", {}).get("item", []):
        name = item.get("name", "")
        low = name.lower()
        if not (low.endswith(".htm") or low.endswith(".html")):
            continue
        if "index" in low or low == filing.primary_document.lower():
            continue
        # R*.htm are SEC interactive-data report pages; exhibits may contain
        # incorporated annual-report statements for some filers.
        if not (re.fullmatch(r"r\d+\.htm", low) or "ex13" in low or "annual" in low):
            continue
        try:
            html = fetch(_filing_doc_url(filing, name))
            text = strip_html(html)
            section = extract_financial_statements(text)
        except Exception:
            continue
        score = _statement_fallback_score(section)
        if score >= 2:
            candidates.append((score, name, section))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (_report_doc_order(x[1]), -x[0], x[1]))
    parts = []
    total = 0
    for score, name, section in candidates[:8]:
        section = section[:15000]
        chunk = f"\n\n=== INCORPORATED STATEMENT REPORT {name} score={score} ===\n{section}"
        if total + len(chunk) > _MAX_SECTION_CHARS_WIDE:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts).strip() if parts else None


# ---------------------------------------------------------------------------
# The one public convenience: ticker -> (Filing, clean statements text)
# ---------------------------------------------------------------------------

def fetch_10k_text(
    ticker: str,
    *,
    fetch: Optional[FetchFn] = None,
    statements_only: bool = True,
) -> tuple[Filing, str]:
    """Resolve a ticker, locate its latest 10-K, fetch + strip it, and return
    (Filing metadata, source text ready for Aritiq).

    With `statements_only=True` (default) the text is narrowed to the financial-
    statements region; set False to get the full stripped filing.

    Raises UnknownTickerError / NoFilingError / EdgarError with messages suitable
    for showing the user directly.
    """
    fetch = fetch or _default_fetch
    cik, company = lookup_cik(ticker, fetch=fetch)
    filing = latest_10k_filing(ticker, cik, company, fetch=fetch)
    try:
        html = fetch(filing.document_url)
    except Exception as exc:
        raise EdgarError(f"Could not download the 10-K document: {exc}") from exc
    text = strip_html(html)
    if statements_only:
        text = extract_financial_statements(text)
        if _statement_fallback_score(text) < 2:
            fallback = _fetch_statement_exhibit_text(filing, fetch)
            if fallback:
                text = fallback
    return filing, text
