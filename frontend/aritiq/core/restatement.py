"""
Phase 3 / Move 2 — restatement DISCLOSURE-LANGUAGE classification.

THIS FILE CONTAINS NO LLM CALLS, and — just as importantly — makes no accounting
determination.  It performs a deterministic string/regex lookup for explicit
restatement or reclassification language in the text near an already-grounded,
already-disagreeing figure, and reports which (if any) was found.

What this solves, and what it deliberately does NOT
---------------------------------------------------
Phase 2's registry surfaces a CONFLICT: two documents disagree on a number.  It
does not say *why* — a prior-period correction, a reclassification, and a
segment realignment all look identical as a flat numeric disagreement, yet they
mean very different things to a reader.

The honest, achievable v1 is NOT "pull EDGAR XBRL and diff the taxonomy tags to
determine the restatement type" — that is a large, in-general-unsolved
integration problem (tags get remapped for reasons unrelated to any real
restatement).  The achievable v1 is: look for disclosure language the filer
itself wrote next to the figure.  That is a context-string lookup, 100%
deterministic, and it is reported as exactly that.

Consequently the output is framed narrowly and on purpose:
  * EXPLICIT_RESTATEMENT      — the text literally says "restated"/"as restated".
  * POSSIBLE_RECLASSIFICATION — reclassification language is present nearby.
  * UNEXPLAINED               — a real conflict with NO disclosure language near it.
This says "we found / did not find restatement language near the number".  It
never claims "we determined what kind of restatement this is".

A note on over-firing
---------------------
The single biggest risk here is matching reclassification/restatement words that
appear in an UNRELATED nearby sentence and mis-tagging a plain conflict.  The
mitigation is twofold: (1) a bounded context window around the figure, not the
whole document; (2) word-boundary regexes, so "restated" doesn't match inside
some unrelated token.  The test suite pins the boundary case explicitly.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .registry import FigureConflict
from .schema import RestatementType, SourceDocument


# Explicit prior-period restatement language.  Word-boundary anchored.
# Ordered MOST-SPECIFIC FIRST so the fuller phrase wins the match: "as restated"
# must be reported in preference to the bare "restated" it contains, since the
# matched substring is surfaced to the reviewer as the audit trail.
_RESTATEMENT_PATTERNS: List[str] = [
    r"\bas\s+restated\b",
    r"\bprior[-\s]period\s+adjustment\b",
    r"\bpreviously\s+reported\b",      # "differs from amounts previously reported"
    r"\brestatement\b",
    r"\brestated\b",
]

# Reclassification / structural-presentation-change language.
_RECLASSIFICATION_PATTERNS: List[str] = [
    r"\breclassified\b",
    r"\breclassification\b",
    r"\brecast\b",
    r"\brealigned\b",
    r"\bsegment\s+realignment\b",
    r"\bconformed\s+to\s+(?:the\s+)?current\s+(?:period\s+)?presentation\b",
    r"\bto\s+conform\s+(?:to\s+)?(?:the\s+)?current\s+presentation\b",
]

# How many characters on each side of the figure's appearance count as "nearby".
# Deliberately bounded so language in a faraway, unrelated sentence does not
# get swept in (the over-fire failure mode named in the module docstring).
DEFAULT_CONTEXT_WINDOW: int = 200


def _compiled(patterns: List[str]) -> List[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_RESTATEMENT_RE = _compiled(_RESTATEMENT_PATTERNS)
_RECLASSIFICATION_RE = _compiled(_RECLASSIFICATION_PATTERNS)


def _first_match(text: str, compiled: List[re.Pattern]) -> Optional[str]:
    """Return the literal matched substring of the first pattern that hits."""
    for rx in compiled:
        m = rx.search(text)
        if m:
            return m.group(0)
    return None


def _value_strings(value: float) -> List[str]:
    """Plausible textual renderings of a numeric value, for locating it in prose.

    We try a few common formats (with and without thousands separators, trimmed
    trailing zeros) so the figure can be found in the source text near which we
    then scan for disclosure language.  This is a locating heuristic only — it
    never affects the verdict, only WHERE we read context from.
    """
    out = set()
    # As-is repr and common numeric forms.
    out.add(str(value))
    if value == int(value):
        iv = int(value)
        out.add(str(iv))
        out.add(f"{iv:,}")              # 1,200
    else:
        out.add(f"{value:.2f}")
        out.add(f"{value:,.2f}")
    # Trim trailing zeros / dot.
    trimmed = ("%f" % value).rstrip("0").rstrip(".")
    out.add(trimmed)
    return [s for s in out if s]


def _context_windows(text: str, value: float, window: int) -> List[str]:
    """Every bounded slice of `text` around an occurrence of the figure.

    If the figure can't be located in the text, returns an empty list — and the
    caller treats "figure not found in this document's prose" as "no nearby
    disclosure", i.e. it cannot manufacture an EXPLICIT_RESTATEMENT out of thin
    air.
    """
    if not text:
        return []
    windows: List[str] = []
    low = text
    for vs in _value_strings(value):
        start = 0
        while True:
            idx = low.find(vs, start)
            if idx == -1:
                break
            lo = max(0, idx - window)
            hi = min(len(text), idx + len(vs) + window)
            windows.append(text[lo:hi])
            start = idx + len(vs)
    return windows


def classify_conflict_context(context: str) -> Tuple[RestatementType, Optional[str]]:
    """Classify a single context string by the disclosure language it contains.

    Precedence: explicit restatement language outranks reclassification language
    (a filing that says BOTH "restated" and "reclassified" near the figure is the
    stronger EXPLICIT_RESTATEMENT signal).  No language at all ⇒ UNEXPLAINED.
    """
    m = _first_match(context, _RESTATEMENT_RE)
    if m:
        return RestatementType.EXPLICIT_RESTATEMENT, m
    m = _first_match(context, _RECLASSIFICATION_RE)
    if m:
        return RestatementType.POSSIBLE_RECLASSIFICATION, m
    return RestatementType.UNEXPLAINED, None


def classify_restatement(
    conflict: FigureConflict,
    later_doc: Optional[SourceDocument] = None,
    *,
    context: Optional[str] = None,
    window: int = DEFAULT_CONTEXT_WINDOW,
) -> FigureConflict:
    """Annotate a FigureConflict with the disclosure language found near it.

    Inputs (one source of context is required to produce anything but UNEXPLAINED):
      * `later_doc`  — the SourceDocument whose figure is in question; we scan a
        bounded window of its prose around the figure for disclosure language.
      * `context`    — alternatively, the caller can pass the already-extracted
        nearby text directly (e.g. the grounding context of the operand).  This
        is the path the spec describes: "a context-string lookup near an
        already-grounded operand."

    Returns a NEW FigureConflict with `restatement_type` and
    `matched_disclosure_text` set.  The input is not mutated.

    Outcomes:
      * EXPLICIT_RESTATEMENT      — restatement language found near the figure.
      * POSSIBLE_RECLASSIFICATION — only reclassification language found.
      * UNEXPLAINED               — context available but NO disclosure language.
      * UNCLASSIFIED              — no context at all to inspect (we refuse to
                                    guess; absence of input is not UNEXPLAINED).
    """
    # Gather candidate context strings.
    candidates: List[str] = []
    if context:
        candidates.append(context)
    if later_doc is not None and later_doc.text:
        # Use the conflicting value from the relevant document. We don't know
        # which of doc_a/doc_b is `later_doc`, so try both values' occurrences.
        candidates.extend(_context_windows(later_doc.text, conflict.value_a, window))
        candidates.extend(_context_windows(later_doc.text, conflict.value_b, window))

    if not candidates:
        # Nothing to look at — honestly UNCLASSIFIED, not UNEXPLAINED.
        return _with(conflict, RestatementType.UNCLASSIFIED, None)

    # Scan candidates; take the strongest signal found across all of them.
    best_type = RestatementType.UNEXPLAINED
    best_match: Optional[str] = None
    for ctx in candidates:
        t, m = classify_conflict_context(ctx)
        if t == RestatementType.EXPLICIT_RESTATEMENT:
            return _with(conflict, t, m)   # strongest; short-circuit
        if t == RestatementType.POSSIBLE_RECLASSIFICATION and best_type == RestatementType.UNEXPLAINED:
            best_type, best_match = t, m

    return _with(conflict, best_type, best_match)


def _with(
    conflict: FigureConflict,
    rtype: RestatementType,
    matched: Optional[str],
) -> FigureConflict:
    """Return a copy of `conflict` with the classification fields set."""
    return FigureConflict(
        row_label=conflict.row_label,
        column_label=conflict.column_label,
        doc_a=conflict.doc_a,
        value_a=conflict.value_a,
        doc_b=conflict.doc_b,
        value_b=conflict.value_b,
        restatement_type=rtype,
        matched_disclosure_text=matched,
    )
