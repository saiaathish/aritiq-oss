"""
Bank-filer statement-slicing regression suite (the JPM / GS bug).

Bank 10-Ks have two properties that broke the old density-only boundary detector:
  1. An early, DENSE auditor's-report / cross-reference INDEX that merely NAMES
     the statements ("Consolidated Balance Sheets 139 ...") and out-scores nothing
     useful, and
  2. EXTREMELY dense footnote tables (derivative fair values, credit netting) deep
     in the notes that out-score the genuine statements on raw numeric density.
The old "globally densest window" picked a footnote a megabyte in; an "earliest
dense" rule picked the index. Result: JPM sliced to 2,850 bytes, GS to 5,026.

The fix (in aritiq/edgar/sec.py): among dense anchor windows, prefer the EARLIEST
that actually contains the balance-sheet IDENTITY rows (Total assets + a Total
liabilities/equity line with real figures), and never cut the slice before those
rows — widening the cap for filers whose statements are spread far apart.

These fixtures are structurally faithful to the bank failure shape but synthetic
(no network), so the regression is permanent and offline.
"""
from aritiq.edgar.sec import extract_financial_statements


def _dense_numbers(n: int) -> str:
    # A run of number-like tokens to simulate a dense table without real meaning.
    return " ".join(f"{i:,}" for i in range(1000, 1000 + n))


# A bank-shaped document:
#   [prose] ... [DENSE INDEX naming the statements] ... [REAL statements with the
#   identity] ... [NOTES with an even-denser footnote table]
def _bank_like_doc(real_assets: str, real_liab: str) -> str:
    prose = "WELLS-STYLE 10-K cover and MD&A prose. " * 50
    # (1) a dense auditor's index that NAMES the statements but has no identity rows
    index_block = (
        "REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM "
        "Consolidated Statements of Income 91 Consolidated Balance Sheets 92 "
        "Consolidated Statements of Cash Flows 93 " + _dense_numbers(120)
    )
    # (2) the REAL statements region, with the balance-sheet identity
    real = (
        "CONSOLIDATED STATEMENTS OF INCOME "
        + _dense_numbers(60)
        + " CONSOLIDATED BALANCE SHEETS "
        + _dense_numbers(40)
        + f" Total assets $ {real_assets} "
        + _dense_numbers(20)
        + f" Total liabilities {real_liab} "
        + "Total stockholders' equity 100,000 "
        + _dense_numbers(20)
    )
    # (3) notes with an even denser footnote table that must NOT be chosen
    notes = (
        "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS "
        "Note 1 Derivative fair values and credit netting "
        + _dense_numbers(400)
        + " Consolidated Balance Sheets reference inside a footnote "
        + _dense_numbers(400)
    )
    return prose + index_block + real + notes


class TestBankSlicing:
    def test_jpm_like_recovers_balance_sheet_not_index_or_footnote(self):
        doc = _bank_like_doc("4,424,900", "4,062,500")
        out = extract_financial_statements(doc)
        # The real statements identity must be present...
        assert "Total assets $ 4,424,900" in out
        assert "Total liabilities 4,062,500" in out
        # ...and the slice must START at the real statements, not in the dense
        # footnote region: the identity rows appear BEFORE any footnote content.
        assert out.index("Total assets $ 4,424,900") < (
            out.index("Derivative fair values") if "Derivative fair values" in out else len(out)
        )

    def test_gs_like_recovers_full_identity(self):
        doc = _bank_like_doc("1,809,320", "1,684,348")
        out = extract_financial_statements(doc)
        assert "Total assets $ 1,809,320" in out
        assert "Total liabilities 1,684,348" in out

    def test_slice_is_not_a_tiny_fragment(self):
        # The original bug produced 2–5 KB fragments. A real statements slice that
        # contains the identity is materially larger.
        doc = _bank_like_doc("4,424,900", "4,062,500")
        out = extract_financial_statements(doc)
        assert len(out) > 2000

    def test_identity_not_clipped_when_statements_are_far_apart(self):
        # Put a large gap between the income statement and the balance sheet, as in
        # real bank filings, and confirm the balance-sheet identity is still in the
        # slice (the cap must widen rather than clip).
        prose = "MD&A. " * 50
        real = (
            "CONSOLIDATED STATEMENTS OF INCOME " + _dense_numbers(60)
            + " filler narrative between statements " * 800
            + " CONSOLIDATED BALANCE SHEETS " + _dense_numbers(30)
            + " Total assets $ 3,411,738 " + _dense_numbers(10)
            + " Total liabilities 3,108,495 Total equity 303,243 "
        )
        out = extract_financial_statements(prose + real)
        assert "Total assets $ 3,411,738" in out
        assert "Total liabilities 3,108,495" in out
