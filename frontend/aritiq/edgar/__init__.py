"""
Aritiq EDGAR ingestion — fetch a public 10-K by ticker and strip it to the
financial-statements section Aritiq can audit.

THIS PACKAGE CONTAINS NO LLM CALLS and costs nothing to run: it talks only to
the SEC's free public JSON/HTML endpoints on sec.gov / data.sec.gov.  It is the
input pipeline the rest of Aritiq was missing — turning a ticker a user types
into clean source text the extractor + verifier can consume.

Firewall note: like the rest of the non-extraction code, nothing here imports an
LLM.  It is pure fetching + regex/HTML stripping.
"""
from .sec import (
    EdgarError,
    UnknownTickerError,
    NoFilingError,
    Filing,
    fetch_10k_text,
    lookup_cik,
    latest_10k_filing,
    strip_html,
    extract_financial_statements,
    SEC_USER_AGENT,
)

__all__ = [
    "EdgarError",
    "UnknownTickerError",
    "NoFilingError",
    "Filing",
    "fetch_10k_text",
    "lookup_cik",
    "latest_10k_filing",
    "strip_html",
    "extract_financial_statements",
    "SEC_USER_AGENT",
]
