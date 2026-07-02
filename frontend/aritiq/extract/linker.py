"""
Deterministic depends_on linker (Phase 2, item 1).

WHY THIS EXISTS
---------------
The provenance graph (`core/graph.py`), weighted score (`core/score.py`), and
restatement classification (`core/restatement.py`) are all built and tested, but
they are INERT until claims actually carry `depends_on` edges — an edge exists when
one claim's operand IS another claim's *computed output* (not merely the same raw
source figure). PHASE3_PROGRESS.md names this exact gap: "the graph does nothing
unless the extractor actually tags when one claim's operand is another claim's
stated output."

This module closes that gap on the extraction side, deterministically, so the edges
populate on real extraction output and not just in hand-built test fixtures. It runs
AFTER `parse_claims`, alongside the prompt-level instruction that asks the LLM to tag
edges itself: whatever the model tagged is preserved, and this pass only ADDS edges
the model missed (belt-and-suspenders). It is pure code — no model — and lives in
`aritiq/extract/`, never in `aritiq/core/`, so the firewall is untouched: the verifier
still only ever consumes edges, never invents them.

THE OUTPUT->INPUT SEMANTIC (and the false-edge trap it avoids)
-------------------------------------------------------------
A `depends_on` edge is an output->input relationship: claim B depends on claim A when
one of B's operands is the *stated output of A's computation*. It is NOT a shared raw
input: three claims that each divide by the same reported revenue share a raw number,
they do not depend on each other's outputs (gold doc C). Linking those would be a
false edge that propagates a failure where no derivation exists — the precise hazard
PHASE3 warns about. Two conservative rules keep the linker on the right side:

  1. Only a genuine COMPUTATION can be a dependency source: operations that produce a
     derived dollar quantity — sum / difference / product / average. An `identity` or
     a raw grounded figure is a raw number, never a source. (percent_change and
     margin_percent produce a %, a different kind than the $ operands that consume
     derived figures here, so they are not $-sources; %→% chains are left to the
     prompt path and documented as a scoped boundary.)

  2. The matched value must be DERIVED-ONLY — it must not also appear as a raw figure
     in the source document. Gold doc A reports "$125.0 million" revenue AND also has
     a sum that computes 125 from two segments; the margin's denominator 125 is the
     raw reported revenue, not the segment sum's output, so linking margin->sum would
     be wrong. Requiring the value to be absent from the source excludes exactly this
     case. A value produced only by computation (gold doc B's net-before-tax 4,500 =
     5,000 − 500, which is never printed in the invoice) is unambiguously an output.

Plus: exact value match (tight tolerance), a UNIQUE source (if two computations yield
the same value we do not guess), and an acyclicity check. Every one of these only ever
*withholds* an edge in case of doubt — a missing edge fails silently and safely; a
wrong edge does not.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..core.schema import Claim, Operation


# Operations whose stated_value is a DERIVED DOLLAR quantity — the only claims that
# can be a dependency source for a dollar operand. Deliberately excludes identity
# (raw restatement), percent_change/margin_percent (produce a %), ratio (a multiple),
# and the temporal/internal-consistency ops (not part of derivation chains here).
_DOLLAR_COMPUTATION_OPS = {
    Operation.SUM,
    Operation.DIFFERENCE,
    Operation.PRODUCT,
    Operation.AVERAGE,
}

# Relative tolerance for deciding an operand value equals a claim's output value.
# Tight on purpose: these are the same number flowing through a chain, not an
# approximate reconciliation.
_MATCH_REL_TOL = 1e-6


def _values_match(a: float, b: float) -> bool:
    if a is None or b is None:
        return False
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom <= _MATCH_REL_TOL


# ---------------------------------------------------------------------------
# Source-number scan — generous on purpose (over-inclusion only ever WITHHOLDS
# an edge, which is the safe direction).
# ---------------------------------------------------------------------------

_NUM_UNIT_RE = re.compile(
    r"(-?\$?\s*\d[\d,]*(?:\.\d+)?)\s*(billion|bn|million|mm|m|thousand|k)?",
    re.IGNORECASE,
)
_UNIT_SCALE = {
    "billion": 1000.0, "bn": 1000.0,            # normalized to $M
    "million": 1.0, "mm": 1.0, "m": 1.0,
    "thousand": 0.001, "k": 0.001,
}


def _source_numbers(source_text: Optional[str]) -> Set[float]:
    """Return the set of numeric values appearing in the source, at plausible scales.

    Generous by design: for each number token we add the bare value AND, when a
    magnitude word follows, the value normalized to $M. Over-inclusion is safe — a
    value wrongly believed to be "in the source" merely suppresses a candidate edge,
    never creates one.
    """
    nums: Set[float] = set()
    if not source_text:
        return nums
    for m in _NUM_UNIT_RE.finditer(source_text):
        raw = m.group(1).replace("$", "").replace(",", "").strip()
        try:
            v = float(raw)
        except ValueError:
            continue
        nums.add(v)
        unit = (m.group(2) or "").lower()
        if unit in _UNIT_SCALE:
            nums.add(v * _UNIT_SCALE[unit])
    return nums


def _value_in_source(value: float, source_nums: Set[float]) -> bool:
    return any(_values_match(value, s) for s in source_nums)


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------

def _stable_node_id(index: int) -> str:
    """Deterministic, position-based id so a re-run yields identical graphs."""
    return f"c{index}"


def link_claims(claims: Sequence[Claim], source_text: Optional[str] = None) -> List[Claim]:
    """Populate node_id / depends_on with output->input edges, in place, and return the list.

    Conservative: adds an edge B -> A only when one of B's operands equals the derived
    output of exactly one dollar-computation claim A, that value does not appear as a
    raw figure in `source_text`, and the edge introduces no cycle. Any edges the LLM
    already tagged are preserved; this pass is additive. Deterministic and model-free.
    """
    claims = list(claims)
    if len(claims) < 2:
        return claims

    source_nums = _source_numbers(source_text)

    # Candidate sources: dollar-computation claims with a usable stated_value, indexed
    # by the value they output. A value produced by >1 computation is ambiguous and is
    # dropped from the index (we never guess which one an operand came from).
    value_to_sources: Dict[float, List[int]] = {}
    for i, c in enumerate(claims):
        if c.operation in _DOLLAR_COMPUTATION_OPS and c.stated_value is not None:
            value_to_sources.setdefault(round(float(c.stated_value), 6), []).append(i)

    def _find_unique_source(value: float, consumer_idx: int) -> Optional[int]:
        hits: List[int] = []
        for key, idxs in value_to_sources.items():
            if _values_match(value, key):
                hits.extend(idxs)
        hits = [j for j in hits if j != consumer_idx]
        # De-dup and require a single distinct source.
        distinct = sorted(set(hits))
        return distinct[0] if len(distinct) == 1 else None

    # Collect edges as (consumer_idx, source_idx) pairs under all the safety filters.
    edges: List[Tuple[int, int]] = []
    for bi, b in enumerate(claims):
        for o in b.operands:
            if o.value is None:
                continue
            # Rule 2: a value that appears in the source is a raw figure, not an output.
            if _value_in_source(o.value, source_nums):
                continue
            ai = _find_unique_source(o.value, bi)
            if ai is None:
                continue
            edges.append((bi, ai))

    if not edges:
        return claims

    # Assign stable node_ids to every claim that is an edge endpoint (preserving any
    # id the LLM already set), then wire depends_on as the union of existing + inferred.
    involved: Set[int] = set()
    for bi, ai in edges:
        involved.add(bi)
        involved.add(ai)
    for i in involved:
        if not claims[i].node_id:
            claims[i].node_id = _stable_node_id(i)

    # Build a would-be adjacency to reject any edge that closes a cycle. Start from the
    # edges the LLM already provided so we never introduce a cycle against those either.
    adj: Dict[str, Set[str]] = {}
    for c in claims:
        if c.node_id:
            adj.setdefault(c.node_id, set()).update(d for d in (c.depends_on or []))

    def _reachable(start: str, target: str) -> bool:
        """Is `target` reachable from `start` following depends_on edges?"""
        stack = [start]
        seen: Set[str] = set()
        while stack:
            n = stack.pop()
            if n == target:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(adj.get(n, ()))
        return False

    for bi, ai in edges:
        b_id = claims[bi].node_id
        a_id = claims[ai].node_id
        if not b_id or not a_id or b_id == a_id:
            continue
        existing = list(claims[bi].depends_on or [])
        if a_id in existing:
            continue
        # Adding b -> a is a cycle iff a can already reach b.
        if _reachable(a_id, b_id):
            continue
        claims[bi].depends_on = existing + [a_id]
        adj.setdefault(b_id, set()).add(a_id)

    return claims
