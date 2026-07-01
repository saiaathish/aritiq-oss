"""
Phase 3 / Move 1 — provenance graph + propagated-error logic.

THIS FILE CONTAINS NO LLM CALLS.  It is pure graph code over data the extractor
already produced (Claim.node_id, Claim.depends_on).  A reviewer can read it top
to bottom and confirm no model decision enters; the graph's *edges* are supplied
by extraction, and this module only walks them.

Why this exists (problem statement, written down, not reverse-engineered)
-------------------------------------------------------------------------
Before Phase 3, claims were verified in isolation.  If one claim's input number
was wrong, every claim derived from it was flagged (or not) on its own, with no
record that they share a cause.  A reviewer saw N separate WRONG_MATH flags
instead of ONE root cause and N consequences.

Move 1 adds the missing structure: a directed acyclic graph whose nodes are
claims (keyed by Claim.node_id) and whose edges are Claim.depends_on.  After the
verifier runs unchanged on every claim independently, we walk the graph and
relabel the *downstream consequences* of a root failure as PROPAGATED_ERROR,
pointing each back at the root that caused it.

The §3.1 discipline still holds: nothing here introduces model judgment.  Given
the same claims and the same depends_on edges, the propagation output is exactly
one deterministic result.  The hard part Move 1 depends on — deciding that two
claims share a number — is EXTRACTION work, surfaced as depends_on edges; this
module trusts those edges exactly as the verifier trusts grounded operands.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from .schema import (
    Claim,
    VerificationResult,
    VerificationStatus,
)


class GraphCycleError(ValueError):
    """Raised when depends_on edges form a cycle.

    This should be impossible from correctly-formed extraction (a claim's
    operands are sourced from claims computed *before* it), but the check is
    cheap and catches an extractor bug early instead of letting propagation spin
    forever or silently misbehave.
    """


# Statuses that make a claim a ROOT failure whose error should propagate
# downstream.  A wrong or unsupportable number poisons everything derived from
# it.  (CONFLICT is deliberately NOT here: a cross-document disagreement is a
# property of the source registry, not a derivation this claim got wrong, and
# its downstream handling is a separate concern — see Move 2.)
_PROPAGATING_FAILURES = {
    VerificationStatus.WRONG_MATH,
    VerificationStatus.UNSUPPORTED_NUMBER,
}


@dataclass
class DAG:
    """A directed acyclic graph of claims, keyed by node_id.

    Construction validates acyclicity.  The graph stores forward edges
    (node -> the nodes it depends on) and is queried for downstream reachability
    (which nodes depend, transitively, on a given node).
    """
    # node_id -> the node_ids it directly depends on (its operands' sources).
    _depends_on: Dict[str, List[str]] = field(default_factory=dict)
    # reverse adjacency: node_id -> node_ids that directly depend on it.
    _dependents: Dict[str, List[str]] = field(default_factory=dict)

    # ---- queries ----------------------------------------------------------

    def nodes(self) -> List[str]:
        return list(self._depends_on.keys())

    def is_root(self, node_id: str) -> bool:
        """A claim is a root iff it depends on nothing (only raw grounded nums)."""
        return not self._depends_on.get(node_id)

    def direct_dependents(self, node_id: str) -> List[str]:
        return list(self._dependents.get(node_id, []))

    def downstream(self, node_id: str) -> Set[str]:
        """Every node reachable FROM `node_id` via reverse (dependents) edges.

        i.e. the full set of claims that depend — directly or transitively — on
        this one.  Excludes `node_id` itself.  This is the blast radius of a
        failure at `node_id`.
        """
        seen: Set[str] = set()
        stack = list(self._dependents.get(node_id, []))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(self._dependents.get(n, []))
        return seen

    def downstream_count(self, node_id: str) -> int:
        """Number of claims that depend (transitively) on this one.

        Used by Move 3 to weight a root claim's importance: a number fourteen
        other claims rest on matters more than an isolated leaf.
        """
        return len(self.downstream(node_id))


def build_dag(claims: Sequence[Claim]) -> DAG:
    """Build a DAG from a list of claims using their depends_on edges.

    * A claim participates as a node iff it has a node_id OR is referenced as a
      dependency by another claim.  Claims with neither are pure leaves that no
      one depends on — they're irrelevant to propagation and simply omitted from
      the graph (their verdict stands alone, exactly as before Phase 3).
    * Edges that point at an unknown node_id are tolerated but ignored with the
      edge dropped — a dangling dependency can't propagate anything, and refusing
      to build the whole graph over one stray reference would be brittle.  (The
      acyclicity guarantee is unaffected.)
    * Raises GraphCycleError if the edges form a cycle.
    """
    # Collect the set of real node_ids.
    node_ids: Set[str] = {c.node_id for c in claims if c.node_id}

    depends_on: Dict[str, List[str]] = {}
    dependents: Dict[str, List[str]] = {}

    # Ensure every known node has entries (so roots with no deps still appear).
    for nid in node_ids:
        depends_on.setdefault(nid, [])
        dependents.setdefault(nid, [])

    for c in claims:
        if not c.node_id:
            # A claim with no node_id can still declare depends_on, but since
            # nothing can target it, it cannot be part of a propagation chain
            # as an intermediate.  We still record its edges so a leaf that
            # depends on a failing root gets marked.  Give it a synthetic key.
            if not c.depends_on:
                continue
            key = _synthetic_key(c)
            depends_on.setdefault(key, [])
            dependents.setdefault(key, [])
            node_ids.add(key)
            src_nid = key
        else:
            src_nid = c.node_id

        for dep in c.depends_on:
            if dep not in node_ids:
                # Dangling reference: target claim has no node_id we know about.
                continue
            depends_on[src_nid].append(dep)
            dependents.setdefault(dep, []).append(src_nid)

    dag = DAG(_depends_on=depends_on, _dependents=dependents)
    _assert_acyclic(dag)
    return dag


def _synthetic_key(claim: Claim) -> str:
    """A stable-ish key for a node_id-less claim that nonetheless has edges.

    Uses object identity so two distinct claims never collide.  Such a claim is
    only ever a *sink* (nothing targets it), so the key never needs to be
    referenceable by another claim's depends_on.
    """
    return f"__anon_{id(claim):x}"


def _assert_acyclic(dag: DAG) -> None:
    """DFS-based cycle detection over the depends_on edges.

    Three-color marking: white (unvisited), grey (on the current DFS stack),
    black (fully explored).  A grey node reached again is a back edge -> cycle.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in dag._depends_on}

    def visit(node: str, path: List[str]) -> None:
        color[node] = GREY
        path.append(node)
        for dep in dag._depends_on.get(node, []):
            if color.get(dep, WHITE) == GREY:
                cycle = " -> ".join(path + [dep])
                raise GraphCycleError(
                    f"Cycle detected in claim dependency graph: {cycle}. "
                    f"depends_on edges must form a DAG (a claim cannot, even "
                    f"transitively, depend on its own output)."
                )
            if color.get(dep, WHITE) == WHITE:
                visit(dep, path)
        path.pop()
        color[node] = BLACK

    for n in list(dag._depends_on.keys()):
        if color[n] == WHITE:
            visit(n, [])


def propagate_errors(
    results: Sequence[VerificationResult],
) -> List[VerificationResult]:
    """Relabel downstream consequences of root failures as PROPAGATED_ERROR.

    Algorithm (run AFTER normal independent verification, never instead of it):
      1. Build the DAG from the claims attached to `results`.
      2. Find every node whose INDEPENDENT verdict is a propagating failure
         (WRONG_MATH / UNSUPPORTED_NUMBER).
      3. For each such root, mark every node reachable downstream of it with
         PROPAGATED_ERROR and caused_by = root's node_id — UNLESS that
         downstream node independently failed too, in which case its own verdict
         stands (we don't mask a genuinely-broken claim).
      4. When a node is downstream of several distinct roots, attribute it to
         the NEAREST one (the most direct cause), so "wrong because of X" names
         the proximate cause a reviewer would chase first.

    Returns a NEW list of VerificationResult; inputs are not mutated.  Results
    whose claims aren't in the graph (pure leaves) pass through untouched.
    """
    results = list(results)
    claims = [r.claim for r in results]
    dag = build_dag(claims)

    # Map node_id -> index into results (only for claims that are graph nodes).
    nid_for_result: List[Optional[str]] = []
    for c in claims:
        if c.node_id:
            nid_for_result.append(c.node_id)
        elif c.depends_on:
            nid_for_result.append(_synthetic_key(c))
        else:
            nid_for_result.append(None)

    index_by_nid: Dict[str, int] = {}
    for i, nid in enumerate(nid_for_result):
        if nid is not None:
            index_by_nid[nid] = i

    # Roots: nodes whose independent status is a propagating failure.
    root_nids = [
        nid for nid, i in index_by_nid.items()
        if results[i].status in _PROPAGATING_FAILURES
    ]

    # For each downstream node, find its nearest propagating root (BFS distance).
    # caused_by[node] = (distance, root_nid)
    nearest: Dict[str, tuple] = {}
    for root in root_nids:
        # BFS over reverse edges from root, recording distance.
        frontier = [(d, 1) for d in dag.direct_dependents(root)]
        visited_local: Set[str] = set()
        while frontier:
            node, dist = frontier.pop(0)
            if node in visited_local:
                continue
            visited_local.add(node)
            prev = nearest.get(node)
            if prev is None or dist < prev[0]:
                nearest[node] = (dist, root)
            for d in dag.direct_dependents(node):
                frontier.append((d, dist + 1))

    # Apply relabeling.
    out: List[VerificationResult] = []
    for i, r in enumerate(results):
        nid = nid_for_result[i]
        if nid is None or nid not in nearest:
            out.append(r)
            continue
        # This node is downstream of some root failure.
        if r.status in _PROPAGATING_FAILURES:
            # Independently broken too — keep its own verdict, do not mask it.
            out.append(r)
            continue
        # Don't relabel a node that itself is one of the roots (can't happen,
        # since roots are propagating failures handled just above, but explicit).
        _dist, root_nid = nearest[nid]
        out.append(
            VerificationResult(
                claim=r.claim,
                status=VerificationStatus.PROPAGATED_ERROR,
                recomputed_value=r.recomputed_value,
                delta=r.delta,
                explanation=(
                    f"Downstream of a failed claim: this value is derived from "
                    f"claim '{root_nid}', which did not verify. Its own arithmetic "
                    f"was not independently flagged — the problem is upstream. "
                    f"(caused_by={root_nid})"
                ),
                caused_by=root_nid,
            )
        )
    return out
