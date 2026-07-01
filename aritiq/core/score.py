"""
Aritiq scoring — aggregates per-claim verification results into a 0–100 score.

Scoring purpose (written down, not reverse-engineered):
  The score is a TRUST signal for a reader: "how much should I trust the
  numeric claims in this AI-generated summary?"

  Consequence: WRONG_MATH carries the heaviest penalty because a confidently-
  wrong derived number is more misleading than an unverifiable one.

Weight table:
  VERIFIED           → 1.0   (full credit)
  WRONG_MATH         → 0.0   (zero credit — the scariest failure)
  UNSUPPORTED_NUMBER → 0.4   (partial; can't verify but not proven wrong)
  AMBIGUOUS          → 0.4   (partial; structural issue)
  UNCHECKED          → excluded from denominator entirely

Phase 2 statuses:
  NEEDS_REVIEW → excluded from the denominator, like UNCHECKED. The claim was
                 routed to a human precisely because code can't (and shouldn't)
                 judge it; scoring it either way would fabricate a verdict where
                 we deliberately declined to give one (§3.4).
  CONFLICT     → 0.0, same as WRONG_MATH. If two source documents disagree on a
                 figure, a derived number built on it is not trustworthy — the
                 reader should treat it as a red flag, not a partial pass.

Phase 3 statuses (Move 1 + Move 3):
  PROPAGATED_ERROR → EXCLUDED from independent scoring entirely. It is a
                 CONSEQUENCE of a root failure, not a separate failure; counting
                 it would penalize the same root error N times. Its cost is paid
                 once, at the root, via the dependency weight below.

Dependency weighting (Move 3)
-----------------------------
The flat score above weights every claim equally regardless of where it sits in
a derivation chain.  But a WRONG_MATH on a number fourteen other claims depend on
is worse than one on an isolated leaf.  Move 1's graph lets us measure that, so
`compute_score` ALSO produces a dependency-weighted score:

  * each root claim's contribution is weighted by
        base_weight * (1 + log(1 + downstream_count))
    — logarithmic, so one number with 50 dependents looks meaningfully worse
    than an isolated error, not apocalyptically worse (a single error must not
    crater the whole score to ~0).
  * PROPAGATED_ERROR claims are excluded (their cost is already counted at the
    root).
  * With NO graph structure (no depends_on anywhere), downstream_count is 0 for
    every claim, the log term vanishes, and the weighted score degrades EXACTLY
    to the flat score.  That equality is a tested invariant.

Both numbers are returned and meant to be shown together
("Weighted: 62 · Unweighted: 81") so the weighting stays auditable and the score
never becomes a black box.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .schema import Claim, VerificationResult, VerificationStatus

WEIGHTS = {
    VerificationStatus.VERIFIED:           1.0,
    VerificationStatus.WRONG_MATH:         0.0,
    VerificationStatus.UNSUPPORTED_NUMBER: 0.4,
    VerificationStatus.AMBIGUOUS:          0.4,
    VerificationStatus.UNCHECKED:          None,  # excluded
    # ---- Phase 2 ----
    VerificationStatus.NEEDS_REVIEW:       None,  # excluded — a human decides
    VerificationStatus.CONFLICT:           0.0,   # source disagreement = red flag
    # ---- Phase 3 ----
    VerificationStatus.PROPAGATED_ERROR:   None,  # excluded — counted at the root
    # Excluded from the denominator, like NEEDS_REVIEW: the formula could not be
    # responsibly run on the evidence extracted, so scoring it either way would
    # fabricate a verdict. Not a proven error, not the summary's fault.
    VerificationStatus.INSUFFICIENT_EVIDENCE: None,
}


@dataclass
class AritiqScore:
    score: float                    # 0–100 — the dependency-weighted score (primary)
    verified: int
    wrong_math: int
    unsupported: int
    ambiguous: int
    unchecked: int
    total_checkable: int            # excludes UNCHECKED / NEEDS_REVIEW / PROPAGATED_ERROR
    needs_review: int = 0
    conflict: int = 0
    # ---- Phase 3 ----
    propagated_error: int = 0
    insufficient_evidence: int = 0
    # The original flat (unweighted) score, kept as a secondary displayed number
    # so the new weighting is auditable and comparable.  When there is no graph
    # structure, unweighted_score == score exactly.
    unweighted_score: float = 0.0

    # ---- Vacuous-score guard (the Verizon fix) -----------------------------
    # A numeric score is only meaningful when at least one claim was actually
    # checkable. When total_checkable == 0 — every claim was excluded, dropped at
    # extraction, or unverifiable — there is NOTHING to be trustworthy or
    # untrustworthy ABOUT, and rendering "100/100 Trustworthy" is a false-
    # confidence bug (exactly what this product exists to prevent). Callers MUST
    # check `score_available` before displaying `score`; when it is False they
    # must show `score_state` instead of a number.
    score_available: bool = True
    score_state: str = "ok"        # "ok" | "no_checkable_claims"
    # How many claims were DROPPED before scoring (schema/parse failures, etc.),
    # with reasons — so a hollow result can never hide WHY it is hollow. Populated
    # by the pipeline/harness, surfaced alongside the score.
    dropped_claims: int = 0
    dropped_reasons: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.dropped_reasons is None:
            self.dropped_reasons = []


# Statuses excluded from the score denominator entirely (weight is None).
_EXCLUDED = {
    VerificationStatus.UNCHECKED,
    VerificationStatus.NEEDS_REVIEW,
    VerificationStatus.PROPAGATED_ERROR,
    VerificationStatus.INSUFFICIENT_EVIDENCE,
}


def compute_score(
    results: List[VerificationResult],
    claims: Optional[Sequence[Claim]] = None,
) -> AritiqScore:
    """Compute the Aritiq trust score from per-claim verification results.

    Returns BOTH a dependency-weighted score (`.score`, primary) and the flat
    unweighted score (`.unweighted_score`, secondary).  Pass `claims` to enable
    dependency weighting via the Move 1 graph; omit it (or pass None) and the
    weighted score simply equals the flat score — so every Phase 1/2 caller that
    calls `compute_score(results)` keeps identical behavior.
    """
    counts = {s: 0 for s in VerificationStatus}
    for r in results:
        counts[r.status] += 1

    checkable = [r for r in results if r.status not in _EXCLUDED]

    if not checkable:
        # VACUOUS-SCORE GUARD (the Verizon fix). With zero checkable claims there
        # is nothing to score. We MUST NOT return a confident 100.0 — that is the
        # hollow "100/100 Trustworthy" false-confidence bug. Return an explicit
        # unavailable state; callers render `score_state`, never the number.
        return AritiqScore(
            score=0.0,
            verified=0, wrong_math=0, unsupported=0, ambiguous=0,
            unchecked=counts[VerificationStatus.UNCHECKED],
            total_checkable=0,
            needs_review=counts[VerificationStatus.NEEDS_REVIEW],
            conflict=counts[VerificationStatus.CONFLICT],
            propagated_error=counts[VerificationStatus.PROPAGATED_ERROR],
            insufficient_evidence=counts[VerificationStatus.INSUFFICIENT_EVIDENCE],
            unweighted_score=0.0,
            score_available=False,
            score_state="no_checkable_claims",
        )

    # ---- Flat (unweighted) score: the original Phase 1/2 behavior -------------
    flat_earned = sum(WEIGHTS[r.status] for r in checkable)
    flat_score = (flat_earned / len(checkable)) * 100.0

    # ---- Dependency-weighted score (Move 3) -----------------------------------
    weighted_score = _weighted_score(checkable, claims, fallback=flat_score)

    return AritiqScore(
        score=round(weighted_score, 1),
        verified=counts[VerificationStatus.VERIFIED],
        wrong_math=counts[VerificationStatus.WRONG_MATH],
        unsupported=counts[VerificationStatus.UNSUPPORTED_NUMBER],
        ambiguous=counts[VerificationStatus.AMBIGUOUS],
        unchecked=counts[VerificationStatus.UNCHECKED],
        total_checkable=len(checkable),
        needs_review=counts[VerificationStatus.NEEDS_REVIEW],
        conflict=counts[VerificationStatus.CONFLICT],
        propagated_error=counts[VerificationStatus.PROPAGATED_ERROR],
        insufficient_evidence=counts[VerificationStatus.INSUFFICIENT_EVIDENCE],
        unweighted_score=round(flat_score, 1),
    )


def _weighted_score(
    checkable: Sequence[VerificationResult],
    claims: Optional[Sequence[Claim]],
    *,
    fallback: float,
) -> float:
    """Dependency-weighted score over the checkable results.

    Each checkable claim contributes (weight_i * credit_i) / sum(weight_i) * 100,
    where credit_i is its status weight (VERIFIED=1.0, WRONG_MATH=0.0, ...) and
    weight_i = 1 + log(1 + downstream_count_i).  A leaf (downstream_count 0) has
    weight 1, so with no graph structure this reduces to the flat mean — which is
    `fallback`, returned directly when `claims` is absent to keep that path
    trivially identical.
    """
    if not claims:
        return fallback

    # Build the DAG lazily here to avoid a hard import cycle at module load.
    from .graph import build_dag

    dag = build_dag(claims)

    # node_id -> downstream_count, for claims that are graph nodes.
    def downstream_for(claim: Claim) -> int:
        nid = claim.node_id
        if not nid:
            return 0
        if nid not in dag.nodes():
            return 0
        return dag.downstream_count(nid)

    num = 0.0
    den = 0.0
    for r in checkable:
        credit = WEIGHTS[r.status]
        if credit is None:  # defensive; excluded statuses shouldn't reach here
            continue
        dc = downstream_for(r.claim)
        weight = 1.0 + math.log(1.0 + dc)
        num += weight * credit
        den += weight

    if den == 0:
        return fallback
    return (num / den) * 100.0
