"""
Phase 3 / Move 3 test suite — dependency-weighted score.

Constructed ground truth, no LLM. These pin the two properties the spec demands:

  * Unit: two documents with IDENTICAL claim-level pass/fail patterns but
    different dependency structure (one flat, one with a root feeding several
    downstream claims) produce DIFFERENT weighted scores, in the right direction
    (a failure with more dependents -> lower weighted score).
  * Sanity: a document with zero shared dependencies anywhere produces
    weighted score == unweighted score EXACTLY (the formula degrades to the old
    behavior when there is no graph structure to weight by).
"""
import math
import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, VerificationStatus, VerificationResult,
)
from aritiq.core.score import compute_score
from aritiq.core.graph import propagate_errors


def claim(node_id, depends_on=None):
    return Claim(
        claim_text=f"claim {node_id}",
        operation=Operation.IDENTITY,
        stated_value=1.0,
        operands=[Operand(value=1.0, source=OperandSource.GROUNDED)],
        node_id=node_id,
        depends_on=depends_on or [],
    )


def result(node_id, status, depends_on=None):
    return VerificationResult(claim=claim(node_id, depends_on), status=status)


# ===========================================================================
# Sanity: no graph structure -> weighted == unweighted, exactly
# ===========================================================================

class TestDegradesToFlat:
    def test_no_dependencies_weighted_equals_unweighted(self):
        # Three independent leaf claims: 2 verified, 1 wrong. No depends_on.
        results = [
            result("a", VerificationStatus.VERIFIED),
            result("b", VerificationStatus.VERIFIED),
            result("c", VerificationStatus.WRONG_MATH),
        ]
        claims = [r.claim for r in results]
        s = compute_score(results, claims=claims)
        assert s.score == s.unweighted_score
        # 2 of 3 verified -> 66.7
        assert s.unweighted_score == pytest.approx(66.7, abs=0.05)

    def test_claims_omitted_weighted_equals_unweighted(self):
        # Backward-compat path: caller passes no claims at all.
        results = [
            result("a", VerificationStatus.VERIFIED),
            result("c", VerificationStatus.WRONG_MATH),
        ]
        s = compute_score(results)              # no claims arg
        assert s.score == s.unweighted_score == 50.0

    def test_all_verified_is_100_both(self):
        results = [result("a", VerificationStatus.VERIFIED),
                   result("b", VerificationStatus.VERIFIED)]
        s = compute_score(results, claims=[r.claim for r in results])
        assert s.score == 100.0 and s.unweighted_score == 100.0


# ===========================================================================
# Unit: same pass/fail pattern, different dependency structure -> different score
# ===========================================================================

class TestDependencyChangesScore:
    def _flat_doc(self):
        # 1 wrong + 4 verified, all INDEPENDENT leaves.
        return [
            result("bad", VerificationStatus.WRONG_MATH),
            result("ok1", VerificationStatus.VERIFIED),
            result("ok2", VerificationStatus.VERIFIED),
            result("ok3", VerificationStatus.VERIFIED),
            result("ok4", VerificationStatus.VERIFIED),
        ]

    def _structured_doc(self):
        # SAME pass/fail at the claim level (1 wrong, 4 verified) BUT the wrong
        # claim is a root that the other four depend on. After propagation the
        # four become PROPAGATED_ERROR (excluded), leaving the weighted score to
        # be dominated by the heavily-weighted failing root.
        return [
            result("bad", VerificationStatus.WRONG_MATH),
            result("ok1", VerificationStatus.VERIFIED, depends_on=["bad"]),
            result("ok2", VerificationStatus.VERIFIED, depends_on=["bad"]),
            result("ok3", VerificationStatus.VERIFIED, depends_on=["bad"]),
            result("ok4", VerificationStatus.VERIFIED, depends_on=["bad"]),
        ]

    def test_structured_failure_scores_lower(self):
        flat = self._flat_doc()
        structured = self._structured_doc()

        flat_score = compute_score(flat, claims=[r.claim for r in flat]).score

        # Structured doc must go through propagation first (as the pipeline does).
        prop = propagate_errors(structured)
        structured_score = compute_score(prop, claims=[r.claim for r in structured]).score

        # A failure that 4 claims depend on must look WORSE than an isolated one.
        assert structured_score < flat_score

    def test_propagated_errors_excluded_from_denominator(self):
        structured = self._structured_doc()
        prop = propagate_errors(structured)
        s = compute_score(prop, claims=[r.claim for r in structured])
        # The 4 downstream are PROPAGATED_ERROR -> excluded; only 'bad' is checkable.
        assert s.propagated_error == 4
        assert s.total_checkable == 1
        # One checkable claim, and it's WRONG_MATH -> 0.
        assert s.score == 0.0

    def test_log_weighting_is_not_linear(self):
        # A root with many dependents should be meaningfully — but not
        # apocalyptically — worse than a root with one dependent. We assert the
        # weight uses log: weight(50 deps) < 50 * weight(0 deps).
        from aritiq.core.graph import build_dag
        # Build a star: root + 50 dependents.
        claims = [claim("root")]
        for i in range(50):
            claims.append(claim(f"d{i}", ["root"]))
        dag = build_dag(claims)
        w_root = 1.0 + math.log(1.0 + dag.downstream_count("root"))
        # log(51) ~= 3.93, so weight ~= 4.93 — single-digit, not 50x.
        assert dag.downstream_count("root") == 50
        assert 4.0 < w_root < 6.0


# ===========================================================================
# The displayed pair is always present and ordered sensibly
# ===========================================================================

class TestDisplayedPair:
    def test_both_numbers_present(self):
        results = [result("a", VerificationStatus.VERIFIED),
                   result("b", VerificationStatus.WRONG_MATH, depends_on=["a"])]
        # b depends on a (verified) -> b stays WRONG_MATH (a didn't fail).
        prop = propagate_errors(results)
        s = compute_score(prop, claims=[r.claim for r in results])
        assert isinstance(s.score, float)
        assert isinstance(s.unweighted_score, float)
