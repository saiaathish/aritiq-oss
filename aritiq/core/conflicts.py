"""
Cross-document conflict surfacing — turn detected disagreements into verdicts.

THIS FILE CONTAINS NO LLM CALLS.  It composes two existing pure-code pieces —
`registry.find_conflicts` (which finds where two documents report the same
labelled figure with different values) and `restatement.classify_restatement`
(which scans the filer's own disclosure language near the figure) — and emits one
`VerificationResult` per conflict with status `CONFLICT`.

Why this module exists
----------------------
The registry, conflict detection, and restatement classification were all built
and unit-tested, but nothing in the live pipeline ever *called* them: `audit()`
took a single concatenated `source` string, so a two-filing input produced no
registry, no `find_conflicts`, and therefore no `CONFLICT` claim — the §7
"never silently pick a winner" guarantee was unreachable in practice.  This
module is the missing bridge.  Given a `DocumentRegistry`, it produces the
`CONFLICT` verdicts the verifier path can hand straight to scoring and the UI.

A `CONFLICT` here is a fact about the SOURCE documents (two filings disagree),
not about the summary, so it is represented as a `Claim` with an `IDENTITY`-style
shell whose `claim_text` describes the disagreement.  It is never "resolved" to a
single value — the verdict's whole content is "these disagree, and here is the
disclosure language found nearby (if any)".
"""
from __future__ import annotations

from typing import List

from .registry import FigureConflict, find_conflicts
from .restatement import classify_restatement
from .schema import (
    Claim,
    DocumentRegistry,
    Operand,
    OperandSource,
    Operation,
    RestatementType,
    VerificationResult,
    VerificationStatus,
)


def _conflict_claim(conflict: FigureConflict) -> Claim:
    """A descriptive Claim shell standing in for a cross-document disagreement.

    The operands record both disputed values (with their doc_ids) so the
    disagreement is fully auditable from the claim alone; stated_value is None
    because there is deliberately no single asserted result — that is the point.
    """
    return Claim(
        claim_text=(
            f"Cross-document conflict on '{conflict.row_label} / "
            f"{conflict.column_label}': {conflict.doc_a}={conflict.value_a}, "
            f"{conflict.doc_b}={conflict.value_b}"
        ),
        operation=Operation.IDENTITY,
        stated_value=None,
        operands=[
            Operand(value=conflict.value_a, source=OperandSource.GROUNDED, doc_id=conflict.doc_a),
            Operand(value=conflict.value_b, source=OperandSource.GROUNDED, doc_id=conflict.doc_b),
        ],
        notes=conflict.describe(),
    )


def conflicts_to_results(
    registry: DocumentRegistry,
    *,
    classify: bool = True,
    rel_tolerance: float = 0.0,
) -> List[VerificationResult]:
    """Detect cross-document conflicts in `registry` and return CONFLICT verdicts.

    For each disagreement `find_conflicts` reports, optionally run the the restatement classifier
    disclosure-language scan against the documents involved, then emit a
    `VerificationResult` with status `CONFLICT` carrying:
      * an auditable claim shell (both values + their doc_ids),
      * `restatement_type` — the disclosure annotation (or None if not classified),
      * an explanation that names both the disagreement and, when found, the
        exact disclosure phrase.

    Returns an empty list when no conflict exists (the common, healthy case).
    """
    results: List[VerificationResult] = []
    for conflict in find_conflicts(registry, rel_tolerance=rel_tolerance):
        rtype = None
        matched = None
        if classify:
            # Scan BOTH documents' prose near the figure; the later/restated one
            # is where "as restated" language typically lives, but we don't assume
            # which doc_id is later, so we let the classifier look at both.
            doc_a = registry.get(conflict.doc_a)
            doc_b = registry.get(conflict.doc_b)
            annotated = conflict
            for doc in (doc_b, doc_a):           # prefer doc_b (often the later filing)
                if doc is None:
                    continue
                cand = classify_restatement(conflict, later_doc=doc)
                if cand.restatement_type != RestatementType.UNCLASSIFIED:
                    annotated = cand
                    if cand.restatement_type == RestatementType.EXPLICIT_RESTATEMENT:
                        break                     # strongest signal; stop early
            rtype = annotated.restatement_type
            matched = annotated.matched_disclosure_text

        explanation = conflict.describe()
        if rtype is not None and rtype != RestatementType.UNCLASSIFIED:
            explanation += f" Disclosure scan: {rtype.value}"
            if matched:
                explanation += f" (matched '{matched}')"
            explanation += "."

        results.append(
            VerificationResult(
                claim=_conflict_claim(conflict),
                status=VerificationStatus.CONFLICT,
                explanation=explanation,
                restatement_type=rtype,
            )
        )
    return results
