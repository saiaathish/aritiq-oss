"""
Aritiq extraction package — the ONLY place an LLM runs.

This package turns messy prose (a source document + an AI-generated summary)
into structured, schema-valid Claim objects.  It is firewalled from the
verifier: it imports the core schema to *produce* Claim objects, but it never
imports or calls verify.py, and verify.py never imports anything from here.

    LLM parses (here)  →  code verifies (aritiq.core.verify)

Public surface:
    extract_claims        — end-to-end: (source, summary) -> ExtractionOutput
    parse_claims          — text -> (claims, issues), no LLM, fully testable
    RawClaim, RawOperand  — the strict JSON contract (Pydantic)
    ExtractionOutput, ExtractionIssue
"""
from .schema import (
    RawClaim,
    RawOperand,
    ExtractionIssue,
    parse_claims,
    raw_to_claim,
)
from .extractor import (
    ExtractionOutput,
    extract_claims,
    CompletionFn,
)
from .cross_statement import (
    extract_internal_consistency,
    CROSS_STATEMENT_SYSTEM_PROMPT,
    RULE_REQUIREMENTS,
)

__all__ = [
    "RawClaim",
    "RawOperand",
    "ExtractionIssue",
    "parse_claims",
    "raw_to_claim",
    "ExtractionOutput",
    "extract_claims",
    "CompletionFn",
    # cross-statement cross-statement extraction
    "extract_internal_consistency",
    "CROSS_STATEMENT_SYSTEM_PROMPT",
    "RULE_REQUIREMENTS",
]
