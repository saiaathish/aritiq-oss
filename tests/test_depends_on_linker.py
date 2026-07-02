"""
Phase 2 / item 1 — deterministic depends_on linker.

Every test pins one safety property. The linker's whole job is to add output->input
edges where a claim's operand is another claim's COMPUTED output, while never adding a
false edge on a shared raw input — because a wrong edge propagates a failure where no
derivation exists (PHASE3_PROGRESS.md). The negative tests are the load-bearing ones.
"""
from aritiq.core.schema import Claim, Operation, Operand, OperandSource
from aritiq.extract.linker import link_claims


def _c(op, stated, operand_values, *, node_id=None, depends_on=None, text=""):
    return Claim(
        claim_text=text or f"{op.value} -> {stated}",
        operation=op, stated_value=stated,
        operands=[Operand(value=v, source=OperandSource.GROUNDED) for v in operand_values],
        node_id=node_id, depends_on=list(depends_on or []),
    )


def _edges(claims):
    return {(c.node_id, tuple(c.depends_on)) for c in claims if c.depends_on}


class TestPositiveLinks:
    def test_subtotal_feeds_total(self):
        # combined = 12 + 8 = 20 (a derived value, NOT in source); total = 30 + 20.
        combined = _c(Operation.SUM, 20, [12, 8])
        total = _c(Operation.SUM, 50, [30, 20])
        out = link_claims([combined, total], source_text="Sales 12, Support 8, Marketing 30")
        # total depends on combined
        assert out[1].depends_on == [out[0].node_id]
        assert out[0].node_id is not None

    def test_multi_level_chain(self):
        # a=diff(100-40=60) [derived], b=sum(60+? ) ... build a 3-level chain on
        # derived-only values not present in source.
        a = _c(Operation.DIFFERENCE, 60, [100, 40])     # 60 derived
        b = _c(Operation.SUM, 90, [60, 30])             # uses 60 -> depends on a
        d = _c(Operation.PRODUCT, 180, [90, 2])         # uses 90 -> depends on b
        out = link_claims([a, b, d], source_text="figures 100 40 30 2")
        assert out[1].depends_on == [out[0].node_id]     # b -> a
        assert out[2].depends_on == [out[1].node_id]     # d -> b

    def test_difference_output_consumed(self):
        # The gold doc B edge: tax base 4500 is the difference output (5000-500),
        # and 4500 is not printed in the source.
        net = _c(Operation.DIFFERENCE, 4500, [5000, 500])
        tax = _c(Operation.MARGIN_PERCENT, 10, [450, 4500])
        out = link_claims([net, tax], source_text="Subtotal 5000, Discount 500, Tax 450")
        assert out[1].depends_on == [out[0].node_id]


class TestNegativeControls:
    def test_shared_raw_input_no_edge(self):
        # Two margins dividing by the SAME reported revenue 1200 share a raw input;
        # neither is the other's output -> no edges (gold doc C).
        m1 = _c(Operation.MARGIN_PERCENT, 20, [240, 1200])
        m2 = _c(Operation.MARGIN_PERCENT, 15, [180, 1200])
        out = link_claims([m1, m2], source_text="Revenue 1200, Net income 240, R&D 180")
        assert _edges(out) == set()

    def test_value_in_source_is_raw_not_output(self):
        # A sum computes 125 from two segments, and a margin divides by 125 — but 125
        # is the REPORTED revenue (appears in source), so it is a raw figure, not the
        # sum's output. No edge (gold doc A's 125 collision).
        seg_sum = _c(Operation.SUM, 125, [75, 50])
        margin = _c(Operation.MARGIN_PERCENT, 40, [50, 125])
        out = link_claims([seg_sum, margin],
                          source_text="Total revenue was $125.0 million; segments 75 and 50")
        assert _edges(out) == set()

    def test_identity_is_not_a_source(self):
        # An identity restates a number; it is never a dependency SOURCE. A later
        # claim whose operand equals an identity's value must NOT link to it — that
        # would be depending on a raw restatement, not a computed output.
        ident = _c(Operation.IDENTITY, 20, [20])          # restates 20; not a source
        consumer = _c(Operation.SUM, 50, [30, 20])        # uses 20
        out = link_claims([ident, consumer], source_text="marketing 30 (no 20 here)")
        assert out[1].depends_on == []

    def test_percent_output_not_a_dollar_source(self):
        # A percent_change outputs 20 (%). A later dollar operand of value 20 ($M)
        # must NOT link to it (kind mismatch) — the gold doc A opex-20 vs growth-20%
        # false-edge trap.
        growth = _c(Operation.PERCENT_CHANGE, 20, [25, 30])   # outputs 20 (%)
        ratio = _c(Operation.RATIO, 2.5, [50, 20])            # 20 is $ opex
        out = link_claims([growth, ratio], source_text="op income 25 to 30; opex 20; gross 50")
        assert _edges(out) == set()

    def test_ambiguous_source_not_guessed(self):
        # Two computations both output 20; a consumer using 20 must NOT be linked to
        # either (we never guess which). 20 is derived-only (not in source).
        s1 = _c(Operation.SUM, 20, [12, 8])
        s2 = _c(Operation.SUM, 20, [15, 5])
        consumer = _c(Operation.SUM, 50, [30, 20])
        out = link_claims([s1, s2, consumer], source_text="a 12 b 8 c 15 d 5 e 30")
        assert out[2].depends_on == []


class TestSafety:
    def test_no_cycle_created(self):
        # Two sums that each output the other's operand value would be a cycle; the
        # linker must not create one. a=sum->20 (ops 5,15), b=sum->5 (ops 20, -15):
        # b uses 20 (a's output) and a uses 5? construct mutual reference.
        a = _c(Operation.SUM, 20, [5, 15])     # outputs 20, uses 5
        b = _c(Operation.SUM, 5, [20, -15])    # outputs 5, uses 20
        # both 20 and 5 are derived-only relative to this source
        out = link_claims([a, b], source_text="only 15 and -15 appear")
        # At most one direction may link; never both (that would be a cycle).
        linked = sum(1 for c in out if c.depends_on)
        assert linked <= 1

    def test_llm_edges_preserved(self):
        # An edge the LLM already tagged must survive the linker (union, not clobber).
        a = _c(Operation.SUM, 20, [12, 8], node_id="A")
        b = _c(Operation.SUM, 999, [1, 2], node_id="B", depends_on=["A"])
        out = link_claims([a, b], source_text="nothing relevant")
        assert "A" in out[1].depends_on

    def test_idempotent(self):
        combined = _c(Operation.SUM, 20, [12, 8])
        total = _c(Operation.SUM, 50, [30, 20])
        once = link_claims([combined, total], source_text="12 8 30")
        edges_once = _edges(once)
        twice = link_claims(once, source_text="12 8 30")
        assert _edges(twice) == edges_once

    def test_single_claim_noop(self):
        out = link_claims([_c(Operation.SUM, 20, [12, 8])], source_text="x")
        assert out[0].depends_on == []
