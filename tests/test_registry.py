"""
Source registry test suite (Phase 2, §2.2 and §7).

The registry makes multi-document claims *representable* and surfaces the one
new failure mode it introduces: two documents disagreeing on the same figure
(§7). The mandated behavior is to SURFACE the conflict, never silently pick a
winner. These tests pin that.
"""
import pytest

from aritiq.core.schema import (
    DocumentRegistry, SourceDocument, TableCell, Operand, OperandSource,
    Claim, Operation, VerificationStatus,
)
from aritiq.core.registry import find_conflicts, operand_conflict_for
from aritiq.core.verify import verify_claim


def _doc(doc_id, cells, **kw):
    return SourceDocument(
        doc_id=doc_id,
        tables=[TableCell(row_label=r, column_label=c, value=v) for r, c, v in cells],
        **kw,
    )


class TestRegistryBasics:
    def test_add_and_get(self):
        reg = DocumentRegistry()
        reg.add(_doc("10K-2024", [("Total revenue", "FY2024", 1000.0)], period="FY2024"))
        assert "10K-2024" in reg
        assert len(reg) == 1
        assert reg.get("10K-2024").period == "FY2024"

    def test_operand_can_name_doc(self):
        # An operand carrying a doc_id is the whole point: cross-document claims
        # become expressible.
        op = Operand(value=1000.0, source=OperandSource.GROUNDED, doc_id="10K-2024")
        assert op.doc_id == "10K-2024"


class TestConflictDetection:
    def test_no_conflict_when_figures_agree(self):
        reg = DocumentRegistry()
        reg.add(_doc("10Q", [("Net income", "Q3", 200.0)]))
        reg.add(_doc("PR",  [("Net income", "Q3", 200.0)]))
        assert find_conflicts(reg) == []

    def test_conflict_surfaced_when_figures_disagree(self):
        # A 10-Q and a press release disagree on net income (the §7 example).
        reg = DocumentRegistry()
        reg.add(_doc("10Q", [("Net income", "Q3", 200.0)]))
        reg.add(_doc("PR",  [("Net income", "Q3", 210.0)]))
        conflicts = find_conflicts(reg)
        assert len(conflicts) == 1
        c = conflicts[0]
        assert {c.value_a, c.value_b} == {200.0, 210.0}
        # The description must make clear it's NOT auto-resolved.
        assert "human" in c.describe().lower()

    def test_operand_conflict_lookup(self):
        reg = DocumentRegistry()
        reg.add(_doc("10Q", [("Cash", "Q3", 130.0)]))
        reg.add(_doc("PR",  [("Cash", "Q3", 131.0)]))
        c = operand_conflict_for(reg, "Cash", "Q3")
        assert c is not None and {c.value_a, c.value_b} == {130.0, 131.0}

    def test_no_conflict_for_unrelated_label(self):
        reg = DocumentRegistry()
        reg.add(_doc("10Q", [("Cash", "Q3", 130.0)]))
        reg.add(_doc("PR",  [("Cash", "Q3", 130.0)]))
        assert operand_conflict_for(reg, "Revenue", "Q3") is None


class TestCrossDocumentVerdict:
    def test_cross_document_percent_change_verifies(self):
        """The end-to-end point of the registry: a claim whose two operands live
        in different filings is verifiable with pure code once each operand names
        its doc_id. Revenue grew from 1000 (prior 10-K) to 1120 (current 10-Q)
        = 12%."""
        prior = Operand(value=1000.0, source=OperandSource.GROUNDED, doc_id="10K-2023",
                        source_text="Total revenue 1,000")
        current = Operand(value=1120.0, source=OperandSource.GROUNDED, doc_id="10Q-2024",
                          source_text="Total revenue 1,120")
        c = Claim(
            claim_text="Revenue grew 12% year-over-year",
            operation=Operation.PERCENT_CHANGE,
            stated_value=12.0,
            operands=[prior, current],
            unit="%",
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED
        # And the provenance survived: each operand still knows its source filing.
        assert c.operands[0].doc_id == "10K-2023"
        assert c.operands[1].doc_id == "10Q-2024"
