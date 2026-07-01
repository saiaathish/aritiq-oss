"""
Phase 3 / Move 1 test suite — provenance graph + propagated error.

Day-1-style discipline: constructed ground truth, no LLM, no API key. The graph
logic is pure code over depends_on edges, so these tests pin exact propagation
behavior on hand-built claim sets.

The spec's three required cases are all here:
  * Unit: small hand-built DAG (one root failure, two downstream, one of which
    is ALSO independently wrong) — propagation marks the right nodes and does
    NOT overwrite the independently-wrong one.
  * Integration: a misstated revenue figure feeds a margin claim and a
    growth-rate claim — both surface as PROPAGATED_ERROR with correct caused_by.
  * Negative: no shared operands -> all-leaf graph, zero propagation.
"""
import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, VerificationStatus, VerificationResult,
)
from aritiq.core.graph import (
    build_dag, propagate_errors, DAG, GraphCycleError,
)


# ---------------------------------------------------------------------------
# Helpers — build VerificationResults directly so we control each claim's
# INDEPENDENT verdict, then run propagation over them.
# ---------------------------------------------------------------------------

def claim(node_id, depends_on=None, text=None):
    return Claim(
        claim_text=text or f"claim {node_id}",
        operation=Operation.IDENTITY,
        stated_value=1.0,
        operands=[Operand(value=1.0, source=OperandSource.GROUNDED)],
        node_id=node_id,
        depends_on=depends_on or [],
    )


def result(node_id, status, depends_on=None):
    return VerificationResult(claim=claim(node_id, depends_on), status=status)


# ===========================================================================
# DAG construction
# ===========================================================================

class TestDAGConstruction:
    def test_leaf_only_graph_has_no_edges(self):
        c1 = claim("a")
        c2 = claim("b")
        dag = build_dag([c1, c2])
        assert dag.is_root("a")
        assert dag.is_root("b")
        assert dag.downstream("a") == set()

    def test_simple_chain_downstream(self):
        # a <- b <- c  (c depends on b depends on a)
        dag = build_dag([claim("a"), claim("b", ["a"]), claim("c", ["b"])])
        assert dag.is_root("a")
        assert not dag.is_root("b")
        assert dag.downstream("a") == {"b", "c"}
        assert dag.downstream("b") == {"c"}
        assert dag.downstream("c") == set()
        assert dag.downstream_count("a") == 2

    def test_diamond_downstream_no_double_count(self):
        # a feeds b and c; both feed d. downstream(a) = {b,c,d}, counted once.
        dag = build_dag([
            claim("a"),
            claim("b", ["a"]),
            claim("c", ["a"]),
            claim("d", ["b", "c"]),
        ])
        assert dag.downstream("a") == {"b", "c", "d"}
        assert dag.downstream_count("a") == 3

    def test_cycle_raises(self):
        # a -> b -> a is impossible from real extraction; must be caught.
        with pytest.raises(GraphCycleError):
            build_dag([claim("a", ["b"]), claim("b", ["a"])])

    def test_dangling_dependency_is_ignored(self):
        # b depends on a node_id that doesn't exist; graph still builds.
        dag = build_dag([claim("b", ["does_not_exist"])])
        # No crash; b has no real upstream so nothing propagates to it.
        assert dag.downstream("does_not_exist") == set()


# ===========================================================================
# Propagation — the core Move 1 behavior
# ===========================================================================

class TestPropagation:
    def test_unit_root_failure_marks_downstream_not_independent(self):
        """The spec's headline unit test.

        a (WRONG_MATH, root) feeds b and c.
        b verified independently -> becomes PROPAGATED_ERROR (caused_by a).
        c is ALSO independently WRONG_MATH -> keeps its own WRONG_MATH, NOT masked.
        """
        results = [
            result("a", VerificationStatus.WRONG_MATH),
            result("b", VerificationStatus.VERIFIED, depends_on=["a"]),
            result("c", VerificationStatus.WRONG_MATH, depends_on=["a"]),
        ]
        out = {r.claim.node_id: r for r in propagate_errors(results)}

        # root keeps its WRONG_MATH
        assert out["a"].status == VerificationStatus.WRONG_MATH
        # b is now a propagated consequence, pointing at a
        assert out["b"].status == VerificationStatus.PROPAGATED_ERROR
        assert out["b"].caused_by == "a"
        # c is independently broken — must NOT be overwritten
        assert out["c"].status == VerificationStatus.WRONG_MATH
        assert out["c"].caused_by is None

    def test_transitive_propagation(self):
        # a (root WRONG_MATH) -> b -> c, both b and c independently verified.
        results = [
            result("a", VerificationStatus.WRONG_MATH),
            result("b", VerificationStatus.VERIFIED, depends_on=["a"]),
            result("c", VerificationStatus.VERIFIED, depends_on=["b"]),
        ]
        out = {r.claim.node_id: r for r in propagate_errors(results)}
        assert out["b"].status == VerificationStatus.PROPAGATED_ERROR
        assert out["c"].status == VerificationStatus.PROPAGATED_ERROR
        # nearest-root attribution: both chase back to a (the only root)
        assert out["b"].caused_by == "a"
        assert out["c"].caused_by == "a"

    def test_unsupported_number_also_propagates(self):
        # A missing operand at the root is just as poisoning as wrong math.
        results = [
            result("a", VerificationStatus.UNSUPPORTED_NUMBER),
            result("b", VerificationStatus.VERIFIED, depends_on=["a"]),
        ]
        out = {r.claim.node_id: r for r in propagate_errors(results)}
        assert out["b"].status == VerificationStatus.PROPAGATED_ERROR
        assert out["b"].caused_by == "a"

    def test_nearest_root_attribution(self):
        # a (root) -> b (root) -> c. c should be attributed to b (the NEAREST
        # failing ancestor), not a.
        results = [
            result("a", VerificationStatus.WRONG_MATH),
            result("b", VerificationStatus.WRONG_MATH, depends_on=["a"]),
            result("c", VerificationStatus.VERIFIED, depends_on=["b"]),
        ]
        out = {r.claim.node_id: r for r in propagate_errors(results)}
        # b is independently broken -> keeps WRONG_MATH
        assert out["b"].status == VerificationStatus.WRONG_MATH
        # c is a consequence; nearest failing root is b
        assert out["c"].status == VerificationStatus.PROPAGATED_ERROR
        assert out["c"].caused_by == "b"

    def test_verified_root_propagates_nothing(self):
        # If the root verified, downstream claims keep their own verdicts.
        results = [
            result("a", VerificationStatus.VERIFIED),
            result("b", VerificationStatus.VERIFIED, depends_on=["a"]),
        ]
        out = {r.claim.node_id: r for r in propagate_errors(results)}
        assert out["b"].status == VerificationStatus.VERIFIED


# ===========================================================================
# Integration — a realistic derivation chain
# ===========================================================================

class TestIntegrationDerivation:
    def test_misstated_revenue_feeds_margin_and_growth(self):
        """A misstated revenue figure feeds a margin claim and a growth-rate
        claim. Both must surface as PROPAGATED_ERROR with caused_by = revenue.

        revenue (WRONG_MATH, root)
          ├── gross_margin  (depends on revenue) — independently verified
          └── revenue_growth (depends on revenue) — independently verified
        """
        results = [
            result("revenue", VerificationStatus.WRONG_MATH),
            result("gross_margin", VerificationStatus.VERIFIED, depends_on=["revenue"]),
            result("revenue_growth", VerificationStatus.VERIFIED, depends_on=["revenue"]),
        ]
        out = {r.claim.node_id: r for r in propagate_errors(results)}

        assert out["revenue"].status == VerificationStatus.WRONG_MATH
        for nid in ("gross_margin", "revenue_growth"):
            assert out[nid].status == VerificationStatus.PROPAGATED_ERROR, nid
            assert out[nid].caused_by == "revenue", nid
            # The explanation must read as "wrong because revenue is wrong".
            assert "revenue" in out[nid].explanation


# ===========================================================================
# Negative — no shared operands means no propagation (no false grouping)
# ===========================================================================

class TestNegativeNoFalseGrouping:
    def test_no_shared_operands_zero_propagation(self):
        # Three unrelated leaf claims, one of them wrong. No depends_on edges.
        results = [
            result("a", VerificationStatus.WRONG_MATH),
            result("b", VerificationStatus.VERIFIED),
            result("c", VerificationStatus.VERIFIED),
        ]
        out = {r.claim.node_id: r for r in propagate_errors(results)}
        # Nobody depends on a, so nothing becomes PROPAGATED_ERROR.
        assert out["a"].status == VerificationStatus.WRONG_MATH
        assert out["b"].status == VerificationStatus.VERIFIED
        assert out["c"].status == VerificationStatus.VERIFIED
        assert all(r.status != VerificationStatus.PROPAGATED_ERROR for r in out.values())

    def test_claims_without_node_ids_pass_through(self):
        # Phase 1/2 claims have no node_id and no depends_on — untouched.
        r = VerificationResult(
            claim=Claim(claim_text="legacy", operation=Operation.PERCENT_CHANGE,
                        stated_value=10.0,
                        operands=[Operand(value=100.0), Operand(value=110.0)]),
            status=VerificationStatus.VERIFIED,
        )
        out = propagate_errors([r])
        assert out[0].status == VerificationStatus.VERIFIED
        assert out[0].caused_by is None
