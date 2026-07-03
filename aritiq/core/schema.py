"""
Aritiq claim schema — the atomic unit the verifier operates on.
No LLM is imported or referenced anywhere in this file or the verifier.

Design note
------------
This file grew in the cross-statement pass, but only additively.  Every new Operation, every new
OperandSource, and every new optional Claim field defaults so that a summary-audit
Claim constructed exactly as before behaves exactly as before.  The summary-audit
test suite passes untouched; that invariance is the evidence the firewall design
held.  Nothing below imports an LLM, and nothing below ever will — the whole
point of the cross-statement pass is to *widen* the deterministic zone, not to smuggle judgment
into it.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


class Operation(str, Enum):
    # ---- summary-audit arithmetic operations (unchanged) ------------------------
    PERCENT_CHANGE  = "percent_change"
    ABSOLUTE_CHANGE = "absolute_change"
    SUM             = "sum"
    DIFFERENCE      = "difference"
    RATIO           = "ratio"
    MARGIN_PERCENT  = "margin_percent"
    AVERAGE         = "average"
    PRODUCT         = "product"
    IDENTITY        = "identity"
    UNSUPPORTED     = "unsupported"   # qualitative / no formula

    # ---- cross-statement additions (each still a pure function, no model) ---------
    # §3.3 Cross-statement consistency: "do the document's own numbers agree?"
    INTERNAL_CONSISTENCY = "internal_consistency"
    # §3.2 Temporal consistency over an ordered (period, value) series.
    TREND_DIRECTION  = "trend_direction"    # asserted up/down/flat over a window
    SUPERLATIVE      = "superlative"         # is this the max/min over the window
    CONSECUTIVE_COUNT = "consecutive_count"  # how many periods in a row satisfy a direction
    # Axis C B2C: sum/count over a filtered transaction subset.
    AGGREGATE_FILTER = "aggregate_filter"
    # MD&A prose direction (extracted outside core) checked against XBRL trend.
    MDA_XBRL_CONSISTENCY = "mda_xbrl_consistency"
    # §3.4 Logical/definitional: detected, never numerically resolved.
    DEFINITIONAL_FLAG = "definitional_flag"


class OperandSource(str, Enum):
    # ---- summary-audit provenance (unchanged) -----------------------------------
    GROUNDED = "grounded"   # found verbatim in source document
    INFERRED = "inferred"   # derived (e.g. unit conversion) but traceable
    MISSING  = "missing"    # extractor could not locate it

    # ---- cross-statement provenance (§2.2, §3.4, Axis C) --------------------------
    # A grounding against a structured TABLE CELL is a stronger, more auditable
    # claim than a prose-string match, so it gets its own provenance type
    # (roadmap §2.2: "grounded_table_cell vs grounded_prose").
    GROUNDED_TABLE_CELL = "grounded_table_cell"
    GROUNDED_PROSE      = "grounded_prose"
    # Axis C: a value whose meaning depends on an LLM categorization decision
    # (e.g. this transaction is "dining").  The category is a judgment call that
    # can be wrong invisibly downstream, so it is flagged here, never silently
    # collapsed into a clean GROUNDED match.
    CATEGORY_INFERRED   = "category_inferred"


class TrendDir(str, Enum):
    """Direction predicate for temporal claims (§3.2)."""
    UP   = "up"     # strictly increasing
    DOWN = "down"   # strictly decreasing
    FLAT = "flat"   # unchanged within tolerance


class Superlative(str, Enum):
    """Which extreme a superlative claim asserts (§3.2)."""
    MAX = "max"
    MIN = "min"


class EPSVariant(str, Enum):
    """Which EPS measure an eps_reconciliation claim is about (§4 of the spec).

    Recording this is mandatory: without it, eps_reconciliation produces false
    WRONG_MATH whenever the document quotes basic EPS but diluted shares were
    grounded (or vice versa).
    """
    BASIC   = "basic"
    DILUTED = "diluted"


class RestatementType(str, Enum):
    """the restatement classifier — how a cross-document CONFLICT is annotated.

    IMPORTANT framing: this enum does NOT determine *what kind of restatement*
    occurred.  It records whether explicit restatement/reclassification DISCLOSURE
    LANGUAGE was found in the text near the conflicting figure — a deterministic
    string/regex lookup, not a model judgment and not an accounting determination.
    The two "no explicit language" outcomes are deliberately phrased as the
    narrow, honest claim they are.
    """
    # Default: the conflict has not been run through classification, or no
    # context text was available to inspect.
    UNCLASSIFIED            = "UNCLASSIFIED"
    # The later document's text explicitly says "restated" / "as restated" /
    # "restatement" near the figure.  Detected by literal string match against
    # extracted context — the strongest, most auditable signal.
    EXPLICIT_RESTATEMENT    = "EXPLICIT_RESTATEMENT"
    # Reclassification / segment-realignment language ("reclassified",
    # "recast", "realigned", "conformed to current presentation") appears near
    # the figure.  NOT proof of a reclassification — proof that reclassification
    # language is present near a disagreeing number.
    POSSIBLE_RECLASSIFICATION = "POSSIBLE_RECLASSIFICATION"
    # A real conflict with NO nearby disclosure of any kind.  This is the
    # narrowest, most honest label: "the numbers disagree and we found no
    # explanation next to them" — never "we determined this is an error".
    UNEXPLAINED             = "UNEXPLAINED"


class VerificationStatus(str, Enum):
    # ---- summary-audit statuses (unchanged) -------------------------------------
    VERIFIED            = "VERIFIED"             # math checks out within tolerance
    WRONG_MATH          = "WRONG_MATH"           # grounded operands, recomputation disagrees
    UNSUPPORTED_NUMBER  = "UNSUPPORTED_NUMBER"   # at least one operand is missing
    AMBIGUOUS           = "AMBIGUOUS"            # divide-by-zero, bad operand count, multi-reading
    UNCHECKED           = "UNCHECKED"            # operation is UNSUPPORTED (qualitative)

    # ---- cross-statement statuses -------------------------------------------------
    # §3.4 / §7: a qualitative word sits next to a number ("costs were flat" +
    # a 4% table delta).  We do NOT invent a numeric threshold; we surface it
    # for a human.  This is deliberately distinct from UNCHECKED: UNCHECKED is
    # "no arithmetic exists", NEEDS_REVIEW is "arithmetic might exist but the
    # claim's own words don't define it precisely enough to judge by code".
    NEEDS_REVIEW        = "NEEDS_REVIEW"
    # §7: two source documents disagree on a number (restatement, typo).  The
    # system must never silently pick a winner — it surfaces the conflict.
    CONFLICT            = "CONFLICT"

    # A formula's required operands are present individually but the EVIDENCE that
    # they are the COMPLETE, correctly-scoped set for the formula is missing or
    # ambiguous — e.g. a balance-sheet tie-out grounded on current liabilities
    # only (long-term rows not captured), or an EPS reconciliation mixing a
    # continuing-operations EPS with total net income.  This is deliberately
    # DISTINCT from WRONG_MATH: WRONG_MATH means "complete, grounded operands,
    # recomputation disagrees" — a real contradiction.  INSUFFICIENT_EVIDENCE
    # means "we cannot responsibly run this formula on what was extracted, so we
    # decline to convict."  Surfaced for a human; never counted as a proven error.
    # It exists because the verifier's credibility rests on WRONG_MATH meaning
    # exactly one thing; an operand-selection mistake must not masquerade as one.
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

    # ---- multi-document statuses -------------------------------------------------
    # the provenance graph (provenance graph): this claim is not independently broken — its
    # operands traced back, through the depends_on graph, to a claim that IS
    # broken (WRONG_MATH / UNSUPPORTED_NUMBER).  It is a CONSEQUENCE of a root
    # failure, not a separate failure.  Carrying it as its own status lets a
    # reviewer see "one root cause, N consequences" instead of N flat flags, and
    # lets scoring (the weighted score) avoid double-penalizing the same root error N times.
    # A claim that ALSO fails independently keeps its own WRONG_MATH — we never
    # overwrite a genuinely-broken claim with a label implying its only problem
    # is upstream.
    PROPAGATED_ERROR    = "PROPAGATED_ERROR"


@dataclass
class TableCell:
    """A single grounded cell of a parsed financial table (§2.1).

    A number's meaning depends on its row label, column header, and sometimes a
    unit footnote three rows down.  Flat-text extraction loses this; a cell that
    carries its labels with it is auditable in a way a bare prose match is not.
    The literal matched header/row strings are stored so a header mis-attribution
    (off-by-one row in a dense table — named failure mode §7) is itself auditable.
    """
    row_label: str
    column_label: str
    value: float
    unit_footnote: Optional[str] = None   # e.g. "in thousands, except per-share"
    doc_id: Optional[str] = None          # which registry document this came from


@dataclass
class Operand:
    value: float
    source: OperandSource = OperandSource.GROUNDED
    source_text: Optional[str] = None   # verbatim string from source document
    source_span: Optional[tuple] = None # (start, end) char offsets if available

    # ---- cross-statement provenance extensions (all optional, default off) --------
    doc_id: Optional[str] = None        # §2.2: which registry document the operand came from
    table_cell: Optional[TableCell] = None  # §2.1: the grounded cell, if grounded against a table
    category: Optional[str] = None      # Axis C: the inferred category, when source == CATEGORY_INFERRED
    category_scheme_version: Optional[str] = None  # §7: version-stamp so categorization drift is detectable


@dataclass
class Claim:
    claim_text: str                          # the sentence making the assertion
    operation: Operation                     # what arithmetic is implied
    stated_value: Optional[float]            # the number the summary asserts
    operands: List[Operand] = field(default_factory=list)
    unit: Optional[str] = None              # "%" | "$M" | etc.
    source_text: Optional[str] = None       # relevant excerpt from source doc
    notes: Optional[str] = None

    # ---- cross-statement fields (all optional; summary-audit claims never set them) ------
    # §3.3: which named internal-consistency rule this claim checks.  Used only
    # when operation == INTERNAL_CONSISTENCY.
    rule_name: Optional[str] = None
    # §4: which EPS measure an eps_reconciliation claim concerns.
    eps_variant: Optional[EPSVariant] = None
    # §3.2: the asserted trend direction / superlative / window, for temporal ops.
    trend_dir: Optional[TrendDir] = None
    superlative: Optional[Superlative] = None
    # Free-form bag for operation-specific parameters that don't deserve a
    # promoted field (e.g. the filter predicate description for aggregate_filter,
    # the detected qualitative word for definitional_flag).  Kept transparent and
    # human-readable; never consulted to *decide* a verdict beyond what the typed
    # verifier logic reads explicitly.
    params: Dict[str, Any] = field(default_factory=dict)

    # ---- multi-document fields (provenance graph; all optional) ----------
    # A stable identifier for THIS claim's output value, usable as a dependency
    # target by other claims.  Optional: a claim with no node_id simply cannot
    # be depended upon (it can still depend on others, but in practice the
    # extractor assigns node_ids to any claim whose output is reused).
    node_id: Optional[str] = None
    # The node_ids this claim's operands were sourced from, WHEN an operand is
    # itself the stated output of another claim rather than a raw source figure.
    # Empty (the default) ⇒ this is a LEAF claim: it depends only on raw grounded
    # numbers and behaves exactly as it did before the multi-document pass.  This field is the
    # entire input to graph construction; everything else about the provenance graph is derived
    # from it.  It is supplied by EXTRACTION (the extractor decides two claims
    # share a number), never inferred by the verifier.
    depends_on: List[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    claim: Claim
    status: VerificationStatus
    recomputed_value: Optional[float] = None
    delta: Optional[float] = None           # stated_value - recomputed_value
    explanation: str = ""

    # ---- multi-document field (provenance graph; optional) ---------------
    # When status == PROPAGATED_ERROR, this points at the node_id of the ROOT
    # claim whose failure caused this one, so the UI can render "this number is
    # wrong because claim X is wrong" instead of another flat flag.  None for
    # every other status.
    caused_by: Optional[str] = None

    # ---- multi-document field (restatement classification; optional) -----
    # When status == CONFLICT, this carries the disclosure-language annotation
    # (EXPLICIT_RESTATEMENT / POSSIBLE_RECLASSIFICATION / UNEXPLAINED) for the
    # cross-document disagreement.  None for every other status.  Remember this
    # records what language was found near the figure, NOT a determination of
    # restatement type.
    restatement_type: Optional["RestatementType"] = None


# ---------------------------------------------------------------------------
# Source registry (§2.2) — infrastructure, not a feature.
# ---------------------------------------------------------------------------
# summary-audit assumed "the source document": a single text string both operands of
# a claim live in.  That assumption breaks the moment a claim spans filings
# ("revenue grew 12% YoY": this year is the current 10-Q, last year a prior
# one).  The registry replaces the single string with a small keyed collection
# so an operand can name *which* document it came from (Operand.doc_id).
#
# This file only DEFINES the registry data structures.  No LLM, no arithmetic.

@dataclass
class SourceDocument:
    """One document in the registry."""
    doc_id: str
    text: str = ""
    tables: List[TableCell] = field(default_factory=list)
    filing_date: Optional[str] = None   # ISO date string, if known
    period: Optional[str] = None        # e.g. "FY2024", "Q3-2025"
    doc_type: Optional[str] = None      # "10-K" | "10-Q" | "press_release" | ...


@dataclass
class DocumentRegistry:
    """A keyed collection of source documents a claim's operands can reference.

    Intentionally tiny.  The value of the registry is representational: it makes
    multi-document claims *expressible* (Operand.doc_id can point at a member).
    It does not itself decide anything.
    """
    documents: Dict[str, SourceDocument] = field(default_factory=dict)

    def add(self, doc: SourceDocument) -> None:
        self.documents[doc.doc_id] = doc

    def get(self, doc_id: str) -> Optional[SourceDocument]:
        return self.documents.get(doc_id)

    def __contains__(self, doc_id: str) -> bool:
        return doc_id in self.documents

    def __len__(self) -> int:
        return len(self.documents)
