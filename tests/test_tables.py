"""
Table extraction + unit normalization test suite (Phase 2, §2.1, §2.2).

Pure deterministic parsing; no LLM. Tests cover:
  - parsing a pipe/markdown table into labelled cells
  - preserving literal header/row strings (so mis-attribution is auditable, §7)
  - scale footnotes ("in thousands") detected and applied
  - parenthesized negatives (accounting convention)
  - money normalization ($1.2B == $1,200M == 1200 in millions)
  - a table-grounded operand verifying through the existing verifier
"""
import pytest

from aritiq.core.schema import (
    TableCell, Operand, OperandSource, Claim, Operation, VerificationStatus,
)
from aritiq.core.tables import (
    parse_markdown_table, find_cell, normalize_money_to_millions,
    apply_scale_footnote_to_millions, normalize_cells_to_millions,
)
from aritiq.core.verify import verify_claim


BALANCE_SHEET = """
(in thousands, except per-share data)

| Line item            | FY2024   | FY2023   |
|----------------------|----------|----------|
| Total assets         | 1,500,000| 1,400,000|
| Total liabilities    | 900,000  | 850,000  |
| Total equity         | 600,000  | 550,000  |
| Net income (loss)    | (50,000) | 120,000  |
"""


class TestTableParsing:
    def test_parses_all_numeric_cells(self):
        cells = parse_markdown_table(BALANCE_SHEET)
        # 4 rows x 2 numeric columns = 8 cells
        assert len(cells) == 8

    def test_preserves_literal_labels(self):
        cells = parse_markdown_table(BALANCE_SHEET)
        c = find_cell(cells, "Total assets", "FY2024")
        assert c is not None
        assert c.row_label == "Total assets"        # literal, for audit
        assert c.column_label == "FY2024"
        assert c.value == 1500000.0

    def test_parenthesized_negative(self):
        cells = parse_markdown_table(BALANCE_SHEET)
        c = find_cell(cells, "Net income", "FY2024")
        assert c is not None
        assert c.value == -50000.0                   # (50,000) -> negative

    def test_scale_footnote_detected(self):
        cells = parse_markdown_table(BALANCE_SHEET)
        assert all(c.unit_footnote == "in thousands" for c in cells)

    def test_not_a_table_returns_empty(self):
        assert parse_markdown_table("just some prose, no pipes here") == []

    def test_doc_id_propagates(self):
        cells = parse_markdown_table(BALANCE_SHEET, doc_id="10K-2024")
        assert all(c.doc_id == "10K-2024" for c in cells)


class TestMoneyNormalization:
    def test_billions(self):
        assert normalize_money_to_millions("$1.2B") == pytest.approx(1200.0)

    def test_explicit_millions(self):
        assert normalize_money_to_millions("$1,200M") == pytest.approx(1200.0)

    def test_bare_number_assumed_millions(self):
        assert normalize_money_to_millions("125") == pytest.approx(125.0)

    def test_thousands_suffix(self):
        assert normalize_money_to_millions("$500,000K") == pytest.approx(500.0)

    def test_unparseable_returns_none(self):
        assert normalize_money_to_millions("about a billion") is None

    def test_equivalence_across_costumes(self):
        # The whole point: same number, three costumes, one canonical value.
        a = normalize_money_to_millions("$1.2B")
        b = normalize_money_to_millions("$1,200M")
        c = normalize_money_to_millions("1200")
        assert a == b == c == pytest.approx(1200.0)


class TestScaleFootnoteApplication:
    def test_thousands_to_millions(self):
        assert apply_scale_footnote_to_millions(1_500_000.0, "in thousands") == pytest.approx(1500.0)

    def test_billions_to_millions(self):
        assert apply_scale_footnote_to_millions(1.5, "in billions") == pytest.approx(1500.0)

    def test_no_footnote_unchanged(self):
        assert apply_scale_footnote_to_millions(125.0, None) == 125.0

    def test_normalize_cells_rescales_values_keeps_labels(self):
        cells = parse_markdown_table(BALANCE_SHEET)
        norm = normalize_cells_to_millions(cells)
        c = find_cell(norm, "Total assets", "FY2024")
        assert c.value == pytest.approx(1500.0)       # 1,500,000 thousands -> 1500 millions
        assert c.row_label == "Total assets"          # label preserved for audit
        assert c.unit_footnote == "in thousands"      # original footnote preserved

    def test_per_share_rows_not_rescaled(self):
        """'in thousands, EXCEPT per-share data' — EPS must NOT be rescaled.

        Blindly multiplying EPS by 1e-3 would turn 2.00 into 0.002 and produce a
        false WRONG_MATH on eps_reconciliation. This pins the exception.
        """
        eps_table = (
            "(in thousands, except per-share data)\n"
            "| Line item                  | FY2024 |\n"
            "|----------------------------|--------|\n"
            "| Net income                 | 200000 |\n"
            "| Diluted earnings per share | 2.00   |\n"
        )
        norm = normalize_cells_to_millions(parse_markdown_table(eps_table))
        ni = find_cell(norm, "Net income", "FY2024")
        eps = find_cell(norm, "Diluted earnings per share", "FY2024")
        assert ni.value == pytest.approx(200.0)       # 200,000 thousands -> 200 millions
        assert eps.value == pytest.approx(2.00)       # per-share: UNCHANGED, not 0.002


class TestFindCellPrecision:
    def test_exact_match_wins_over_substring(self):
        cells = [
            TableCell(row_label="Cash and cash equivalents, end", column_label="FY24", value=29.9),
            TableCell(row_label="Cash and cash equivalents", column_label="FY24", value=30.1),
        ]
        c = find_cell(cells, "Cash and cash equivalents", "FY24")
        assert c.value == 30.1   # the exact balance-sheet row, not the cash-flow row

    def test_substring_fallback_still_works(self):
        cells = [TableCell(row_label="Total assets, net", column_label="FY24", value=500.0)]
        c = find_cell(cells, "Total assets", "FY24")
        assert c is not None and c.value == 500.0


class TestTableGroundedOperandVerifies:
    def test_balance_sheet_identity_from_parsed_table(self):
        """End-to-end: parse a 10-K balance sheet, normalize, ground the three
        operands from TABLE CELLS, and verify the identity with pure code.
        This is the §2.3 invariance: verify.py didn't change, yet a
        table-grounded claim verifies just like a prose-grounded one."""
        cells = normalize_cells_to_millions(parse_markdown_table(BALANCE_SHEET, doc_id="10K-2024"))
        assets = find_cell(cells, "Total assets", "FY2024")
        liab = find_cell(cells, "Total liabilities", "FY2024")
        equity = find_cell(cells, "Total equity", "FY2024")
        assert None not in (assets, liab, equity)

        def op_from(cell):
            return Operand(
                value=cell.value,
                source=OperandSource.GROUNDED_TABLE_CELL,
                source_text=f"{cell.row_label} / {cell.column_label} = {cell.value}",
                doc_id=cell.doc_id,
                table_cell=cell,
            )

        c = Claim(
            claim_text="Balance sheet identity (FY2024)",
            operation=Operation.INTERNAL_CONSISTENCY,
            stated_value=None,
            operands=[op_from(assets), op_from(liab), op_from(equity)],
            rule_name="balance_sheet_identity",
            params={"liabilities_complete": True},  # TOTAL liabilities cell
        )
        r = verify_claim(c)
        # 1500 == 900 + 600 -> VERIFIED, and the operand provenance is table-cell.
        assert r.status == VerificationStatus.VERIFIED
        assert c.operands[0].source == OperandSource.GROUNDED_TABLE_CELL
        assert c.operands[0].table_cell.row_label == "Total assets"
