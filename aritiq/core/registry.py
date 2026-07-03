"""
Registry-level deterministic checks (§2.2, §7).

THIS FILE CONTAINS NO LLM CALLS.  Like verify.py, it is pure logic a reviewer
can read top to bottom.

The one genuinely new failure mode the registry introduces is named in roadmap
§7: "The source registry makes 'which document is authoritative' ambiguous. If
a 10-Q and a press release disagree on a number ... which one is 'the source'?"
The mandated mitigation is: "never silently pick one; surface the conflict as
part of the verdict, don't resolve it on the system's behalf."

So this module's job is detection, not resolution.  It finds where two
registry documents report the *same labelled figure* with *different values*,
and hands that back as a structured conflict.  It never decides a winner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .schema import DocumentRegistry, RestatementType, TableCell


@dataclass
class FigureConflict:
    """Two documents disagree on what should be the same labelled figure."""
    row_label: str
    column_label: str
    doc_a: str
    value_a: float
    doc_b: str
    value_b: float

    # ---- the restatement classifier fields (optional; default = unclassified) --------
    # The disclosure-language annotation, set by classify_restatement().  Default
    # UNCLASSIFIED until classification runs.  This is NOT a determination of what
    # kind of restatement occurred — see RestatementType's docstring.
    restatement_type: RestatementType = RestatementType.UNCLASSIFIED
    # The exact substring that triggered the classification (e.g. "as restated"),
    # so the annotation is auditable — a reviewer can see precisely what word
    # drove it.  None when UNCLASSIFIED/UNEXPLAINED.
    matched_disclosure_text: Optional[str] = None

    def describe(self) -> str:
        base = (
            f"Conflict on '{self.row_label} / {self.column_label}': "
            f"{self.doc_a} reports {self.value_a}, {self.doc_b} reports {self.value_b}. "
            f"Not resolved automatically — authoritative source is a human decision."
        )
        if self.restatement_type != RestatementType.UNCLASSIFIED:
            base += f" [disclosure scan: {self.restatement_type.value}"
            if self.matched_disclosure_text:
                base += f" — matched '{self.matched_disclosure_text}'"
            base += "]"
        return base


def _key(cell: TableCell) -> Tuple[str, str]:
    return (cell.row_label.strip().lower(), cell.column_label.strip().lower())


def find_conflicts(
    registry: DocumentRegistry,
    rel_tolerance: float = 0.0,
    abs_floor: float = 1e-9,
) -> List[FigureConflict]:
    """Return every (label-matched, value-disagreeing) figure pair across docs.

    Default tolerance is ZERO: any disagreement beyond float noise is a real
    conflict worth surfacing.  Callers may loosen it, but the default refuses to
    paper over restatements.

    Detection is symmetric and label-based: two cells conflict iff they share a
    (row_label, column_label) key but their values differ.  We deliberately do
    NOT try to reconcile unit footnotes here — a cell in thousands vs one in
    millions under the same label is exactly the kind of thing a human should
    look at, and silently rescaling it would be the system "resolving on its own
    behalf", which §7 forbids.
    """
    conflicts: List[FigureConflict] = []
    doc_ids = list(registry.documents.keys())

    for i in range(len(doc_ids)):
        for j in range(i + 1, len(doc_ids)):
            a = registry.documents[doc_ids[i]]
            b = registry.documents[doc_ids[j]]
            # Index B's cells by label for O(n+m) comparison.
            b_index = {}
            for cb in b.tables:
                b_index.setdefault(_key(cb), []).append(cb)
            for ca in a.tables:
                for cb in b_index.get(_key(ca), []):
                    delta = abs(ca.value - cb.value)
                    denom = max(abs(cb.value), abs_floor)
                    if delta / denom > rel_tolerance:
                        conflicts.append(
                            FigureConflict(
                                row_label=ca.row_label,
                                column_label=ca.column_label,
                                doc_a=a.doc_id,
                                value_a=ca.value,
                                doc_b=b.doc_id,
                                value_b=cb.value,
                            )
                        )
    return conflicts


def operand_conflict_for(
    registry: DocumentRegistry,
    row_label: str,
    column_label: str,
    rel_tolerance: float = 0.0,
    abs_floor: float = 1e-9,
) -> Optional[FigureConflict]:
    """If the named figure is reported inconsistently across the registry,
    return the first such conflict; else None.

    This is the hook a verifier uses before trusting a cross-document operand:
    if the very figure you're about to compute with is disputed between filings,
    the honest verdict is CONFLICT, not a confident number.
    """
    target = (row_label.strip().lower(), column_label.strip().lower())
    for c in find_conflicts(registry, rel_tolerance=rel_tolerance, abs_floor=abs_floor):
        if (c.row_label.strip().lower(), c.column_label.strip().lower()) == target:
            return c
    return None
