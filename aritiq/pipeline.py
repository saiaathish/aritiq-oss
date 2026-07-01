"""
The Aritiq pipeline: source document + AI summary  ->  audited result.

This is the seam where the two halves meet, and it is written to make the
firewall obvious:

    extract_claims(...)  ── returns Claim objects ──►  verify_claim(...)

Extraction (LLM) produces structured Claims; verification (pure code) consumes
ONLY those Claims.  No summary prose is passed into the verifier, and the
extractor never sees a verdict.  Read top to bottom: the LLM output crosses into
verification as plain data, nothing more.

Two entry points:
  * audit(source, summary)            — single-document (Phase 1/2).
  * audit_documents(documents, summary) — multi-document (Phase 3): builds a
    registry, routes grounding per document, and surfaces cross-document
    CONFLICT verdicts with restatement-disclosure classification.

Both share one tail (_verify_propagate_score): verify each claim independently,
propagate root failures through the dependency graph (Move 1), then score with
dependency weighting (Move 3).  The verifier remains model-free throughout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .core.schema import (
    Claim,
    DocumentRegistry,
    SourceDocument,
    VerificationResult,
)
from .core.score import AritiqScore, compute_score
from .core.graph import propagate_errors
from .core.conflicts import conflicts_to_results
from .core.verify import (
    DEFAULT_PCT_TOLERANCE_PP,
    DEFAULT_REL_TOLERANCE,
    verify_claim,
)
from .extract import (
    CompletionFn,
    ExtractionIssue,
    extract_claims,
    extract_internal_consistency,
)
from .extract.conflict_figures import extract_conflict_figures


@dataclass
class SourceDoc:
    """One labeled source document for the multi-document audit path.

    `doc_id` is how a claim's operand names which filing it came from; `period`
    and `doc_type` are optional context the extractor and conflict scan can use.
    `tables` are pre-parsed labelled cells (row/column/value) used for
    cross-document conflict detection — when omitted, conflict detection simply
    has nothing structured to compare and finds none.
    """
    doc_id: str
    text: str
    period: Optional[str] = None
    doc_type: Optional[str] = None
    tables: Optional[list] = None


@dataclass
class AuditResult:
    score: AritiqScore
    results: List[VerificationResult]
    claims: List[Claim]
    issues: List[ExtractionIssue] = field(default_factory=list)
    raw_response: str = ""
    provider: str = ""
    model: str = ""
    # ---- Phase 3: cross-document conflict verdicts (may be empty) ----------
    # Surfaced separately so the UI can render "two filings disagree" distinctly
    # from per-claim arithmetic verdicts.  These are ALSO included in `results`
    # (so they count toward the score) — this list is a convenience view.
    conflicts: List[VerificationResult] = field(default_factory=list)


def audit(
    source: str,
    summary: str,
    *,
    complete_fn: Optional[CompletionFn] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    pct_tolerance: float = DEFAULT_PCT_TOLERANCE_PP,
    rel_tolerance: float = DEFAULT_REL_TOLERANCE,
    check_internal_consistency: bool = True,
    cs_complete_fn: Optional[CompletionFn] = None,
) -> AuditResult:
    """
    Run the full audit in one call.

    Two extraction passes, both behind the same firewall (only Claim objects
    cross into the deterministic verifier):

      1. SUMMARY AUDIT (Phase 1): trace the numeric claims in `summary` back to
         `source` and recompute them.
      2. CROSS-STATEMENT (Phase 2): check whether `source`'s own numbers agree
         with each other (balance sheet balances, EPS reconciles, cash ties).
         Runs when `check_internal_consistency` is True (the default) and the
         document actually supports a rule — if not, it simply contributes zero
         claims, so Phase-1-only inputs behave exactly as before.

    Offline / replay note: the two passes use DIFFERENT prompts, so a single
    replayed `complete_fn` can't serve both. Tests and offline demos pass a
    dedicated `cs_complete_fn` for the cross-statement pass. If `complete_fn` is
    given (Phase-1 replay) but `cs_complete_fn` is not, the cross-statement pass
    is skipped rather than fed the wrong fixture — keeping existing behavior and
    every Phase 1 test byte-for-byte identical.

    Pass `complete_fn=None` (the live path) to use the default backend selected
    by provider/model for BOTH passes.
    """
    extraction = extract_claims(
        source, summary,
        complete_fn=complete_fn, provider=provider, model=model,
    )

    claims: List[Claim] = list(extraction.claims)
    issues: List[ExtractionIssue] = list(extraction.issues)

    # ---- Phase 2: cross-statement consistency on the SOURCE document ----------
    # Decide whether to run, and with which completion backend:
    #   * live path (complete_fn is None): reuse the default backend.
    #   * replay path (complete_fn given): only run if a dedicated cs fixture is
    #     supplied; otherwise skip so we never feed summary-audit JSON to the
    #     cross-statement parser.
    run_cs = check_internal_consistency and (complete_fn is None or cs_complete_fn is not None)
    if run_cs:
        cs = extract_internal_consistency(
            source,
            complete_fn=cs_complete_fn if cs_complete_fn is not None else complete_fn,
            provider=provider,
            model=model,
        )
        claims.extend(cs.claims)
        issues.extend(cs.issues)

    # ---- FIREWALL: only Claim objects cross from extraction into verification.
    results, score = _verify_propagate_score(
        claims, pct_tolerance=pct_tolerance, rel_tolerance=rel_tolerance,
    )
    _annotate_dropped(score, issues)

    return AuditResult(
        score=score,
        results=results,
        claims=claims,
        issues=issues,
        raw_response=extraction.raw_response,
        provider=extraction.provider,
        model=extraction.model,
    )


# Issue-reason prefixes that mean a claim was genuinely DROPPED (never reached
# the verifier), as opposed to a benign repair that was kept. Surfacing the drop
# count + reasons on the score is what stops a hollow result hiding WHY it's hollow.
_DROP_PREFIXES = (
    "schema validation failed",
    "JSON decode error",
    "no JSON array",
    "array element is not an object",
    "top-level JSON is not an array",
    "unterminated JSON array",
    "empty model response",
)


def _annotate_dropped(score, issues: List[ExtractionIssue]) -> None:
    """Attach dropped-claim count + reasons to the score (visibility, not silence).

    Pure bookkeeping over already-recorded ExtractionIssues; no model, no verdict
    change. Lets the UI render "N claims were dropped: <reasons>" next to (or
    instead of) the score, so a 0-checkable result can never look clean.
    """
    dropped = [i for i in issues
               if any((i.reason or "").startswith(p) for p in _DROP_PREFIXES)]
    score.dropped_claims = len(dropped)
    score.dropped_reasons = [(i.reason or "")[:200] for i in dropped]


def _verify_propagate_score(
    claims: List[Claim],
    *,
    pct_tolerance: float,
    rel_tolerance: float,
    extra_results: Optional[List[VerificationResult]] = None,
):
    """Shared tail of every audit: verify each claim, propagate, then score.

    `extra_results` are pre-built VerificationResults (e.g. cross-document
    CONFLICT verdicts) that did NOT come from a per-claim arithmetic check but
    must still count toward the score and appear in the output.  They are added
    AFTER propagation (a CONFLICT is not a graph-propagated consequence) and
    BEFORE scoring (so a source disagreement lowers the trust score).
    """
    # Each claim is verified INDEPENDENTLY (Phase 1/2 logic, unchanged).
    results = [
        verify_claim(claim, pct_tolerance=pct_tolerance, rel_tolerance=rel_tolerance)
        for claim in claims
    ]

    # ---- Phase 3 / Move 1: provenance-graph propagation -----------------------
    # Walk the depends_on graph and relabel downstream consequences of any root
    # failure as PROPAGATED_ERROR.  Pure graph code; leaf claims pass through
    # untouched, so Phase 1/2 inputs behave exactly as before.
    results = propagate_errors(results)

    # ---- Cross-document CONFLICT verdicts (already-built) ---------------------
    if extra_results:
        results = list(results) + list(extra_results)

    # ---- Phase 3 / Move 3: dependency-weighted score --------------------------
    # compute_score reports BOTH the dependency-weighted score and the flat one.
    # When there is no graph structure, the weighted score degrades exactly to
    # the flat one.
    score = compute_score(results, claims=claims)
    return results, score


def audit_documents(
    documents: List[SourceDoc],
    summary: str,
    *,
    complete_fn: Optional[CompletionFn] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    pct_tolerance: float = DEFAULT_PCT_TOLERANCE_PP,
    rel_tolerance: float = DEFAULT_REL_TOLERANCE,
    check_internal_consistency: bool = True,
    cs_complete_fn: Optional[CompletionFn] = None,
    detect_conflicts: bool = True,
    cf_complete_fn: Optional[CompletionFn] = None,
) -> AuditResult:
    """Audit a summary against MULTIPLE labeled source documents (Phase 3).

    This is the multi-filing path the single-string `audit()` could not express.
    It does three things `audit()` does not:

      1. Builds a DocumentRegistry from the labeled documents, so a claim's
         operand can name WHICH filing it came from (doc_id) and so the
         document each fiscal-year figure belongs to is unambiguous.
      2. Runs cross-statement (internal-consistency) extraction PER DOCUMENT, so
         e.g. the cash tie-out is checked on each filing's OWN cash lines — not
         on whichever document happened to appear first in a concatenated blob.
      3. Detects cross-document CONFLICTs (the same labelled figure reported
         differently across filings) and classifies the disclosure language near
         each — surfacing them as CONFLICT verdicts, never silently picking a
         winner (§7).  This is the piece the single-string path could not reach.

    The summary grounding pass still runs once against the concatenated document
    text (the summary's claims may legitimately reference any filing); the
    registry + per-document passes are what make the year/document routing and
    the conflict detection work.  Offline/replay is supported exactly as in
    `audit()` via `complete_fn` / `cs_complete_fn`.
    """
    # ---- Build the registry from the labeled documents -----------------------
    # Conflict detection compares labelled figures (TableCells). When a document
    # ships pre-parsed tables, use them. Otherwise — the common case for prose
    # pasted into the UI — run the conflict-figure extractor to GROUND a small set
    # of comparable headline figures from the prose into cells, so find_conflicts
    # has something to compare. This is the step that makes cross-document
    # CONFLICT actually fire on real prose input rather than only on table input.
    run_cf = detect_conflicts and (complete_fn is None or cf_complete_fn is not None)
    registry = DocumentRegistry()
    for d in documents:
        cells = list(d.tables) if d.tables else []
        if not cells and run_cf:
            cells = extract_conflict_figures(
                d.text, d.doc_id,
                complete_fn=cf_complete_fn if cf_complete_fn is not None else complete_fn,
                provider=provider, model=model,
            )
        registry.add(SourceDocument(
            doc_id=d.doc_id, text=d.text, period=d.period, doc_type=d.doc_type,
            tables=cells,
        ))

    # ---- Summary grounding pass (Phase 1) ------------------------------------
    # The summary may reference any filing, so it sees all document text. We tag
    # each document with its id/period so the extractor can route a fiscal-year
    # claim to the correct figure rather than first-match.
    combined_source = _labeled_source(documents)
    extraction = extract_claims(
        combined_source, summary,
        complete_fn=complete_fn, provider=provider, model=model,
    )
    claims: List[Claim] = list(extraction.claims)
    issues: List[ExtractionIssue] = list(extraction.issues)

    # ---- Per-document cross-statement (Phase 2) ------------------------------
    run_cs = check_internal_consistency and (complete_fn is None or cs_complete_fn is not None)
    if run_cs:
        for d in documents:
            cs = extract_internal_consistency(
                d.text,
                complete_fn=cs_complete_fn if cs_complete_fn is not None else complete_fn,
                provider=provider, model=model,
            )
            # Stamp each cross-statement operand with the document it came from,
            # so its provenance is unambiguous in the output.
            for c in cs.claims:
                for op in c.operands:
                    if op.doc_id is None:
                        op.doc_id = d.doc_id
            claims.extend(cs.claims)
            issues.extend(cs.issues)

    # ---- Cross-document CONFLICT detection + restatement classification ------
    conflict_results = (
        conflicts_to_results(registry, rel_tolerance=rel_tolerance)
        if detect_conflicts else []
    )

    # ---- Verify, propagate, fold in conflicts, score -------------------------
    results, score = _verify_propagate_score(
        claims, pct_tolerance=pct_tolerance, rel_tolerance=rel_tolerance,
        extra_results=conflict_results,
    )
    _annotate_dropped(score, issues)

    return AuditResult(
        score=score,
        results=results,
        claims=claims,
        issues=issues,
        raw_response=extraction.raw_response,
        provider=extraction.provider,
        model=extraction.model,
        conflicts=conflict_results,
    )


def _labeled_source(documents: List[SourceDoc]) -> str:
    """Concatenate documents with explicit id/period headers.

    Giving each document a labeled header is what lets the extractor ground a
    "fiscal 2025" claim against the FY2025 filing rather than first-match across
    an undifferentiated blob — the routing failure behind the stale-document
    false positives.
    """
    parts = []
    for d in documents:
        header = f"=== DOCUMENT {d.doc_id}"
        if d.period:
            header += f" (period: {d.period}"
            if d.doc_type:
                header += f", type: {d.doc_type}"
            header += ")"
        elif d.doc_type:
            header += f" (type: {d.doc_type})"
        header += " ==="
        parts.append(f"{header}\n{d.text.strip()}")
    return "\n\n".join(parts)
