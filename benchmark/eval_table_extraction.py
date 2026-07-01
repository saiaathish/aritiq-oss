"""
Aritiq Phase 2 — end-to-end table-grounded verification benchmark.

Takes a 10-K-SHAPED fixture (pipe tables, "(in thousands)" footnote,
parenthesized negatives, multiple period columns) and runs the WHOLE
deterministic pipeline on it:

    raw text
      -> parse_markdown_table          (§2.1 structured extraction)
      -> normalize_cells_to_millions   (§2.2 unit normalization)
      -> find_cell                     (deterministic label lookup)
      -> verify_claim                  (§3.3 rules, UNCHANGED from before tables)

The point it demonstrates (roadmap §2.3): verify.py did not change at all to
support tables. A grounded, normalized operand is a grounded, normalized operand
whether it came from clean prose or a 10-K table. The same three cross-statement
rules verify table-grounded claims with no new verifier code.

This is a CONSTRUCTED fixture with fabricated-but-internally-consistent numbers,
so the expected verdicts are exact. It is explicitly NOT a real-filing accuracy
measurement — that gap is named in the README and the Phase 2 writeup.

Run:
    python benchmark/eval_table_extraction.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, EPSVariant, VerificationStatus,
)
from aritiq.core.tables import (
    parse_markdown_table, normalize_cells_to_millions, find_cell,
)
from aritiq.core.verify import verify_claim

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "table_fixtures", "AAPL_style_10k_excerpt.md")

PERIOD = "FY2024"


def _op(cell, variant_tag=None):
    op = Operand(
        value=cell.value,
        source=OperandSource.GROUNDED_TABLE_CELL,
        source_text=f"{cell.row_label} / {cell.column_label} = {cell.value}",
        doc_id=cell.doc_id,
        table_cell=cell,
    )
    if variant_tag:
        op.category = variant_tag
    return op


def build_claims_from_fixture(text: str):
    cells = normalize_cells_to_millions(parse_markdown_table(text, doc_id="10K-FY2024"))

    assets = find_cell(cells, "Total assets", PERIOD)
    liab = find_cell(cells, "Total liabilities", PERIOD)
    equity = find_cell(cells, "Total shareholders equity", PERIOD)
    net_income = find_cell(cells, "Net income", PERIOD)
    dil_shares = find_cell(cells, "Diluted shares outstanding", PERIOD)
    dil_eps = find_cell(cells, "Diluted earnings per share", PERIOD)
    cf_cash = find_cell(cells, "Cash and cash equivalents, end", PERIOD)
    bs_cash = find_cell(cells, "Cash and cash equivalents", PERIOD)

    claims = []
    if None not in (assets, liab, equity):
        claims.append(("balance_sheet_identity", Claim(
            claim_text="Balance sheet identity (FY2024, from table)",
            operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
            operands=[_op(assets), _op(liab), _op(equity)],
            rule_name="balance_sheet_identity",
        ), "VERIFIED"))
    if None not in (dil_eps, net_income, dil_shares):
        claims.append(("eps_reconciliation", Claim(
            claim_text="Diluted EPS reconciliation (FY2024, from table)",
            operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
            operands=[_op(dil_eps), _op(net_income), _op(dil_shares, "diluted")],
            rule_name="eps_reconciliation", eps_variant=EPSVariant.DILUTED,
        ), "VERIFIED"))
    if None not in (cf_cash, bs_cash):
        claims.append(("cash_flow_tie_out", Claim(
            claim_text="Cash flow tie-out (FY2024, from table)",
            operation=Operation.INTERNAL_CONSISTENCY, stated_value=None,
            operands=[_op(cf_cash), _op(bs_cash)],
            rule_name="cash_flow_tie_out",
        ), "VERIFIED"))
    return claims


def main() -> bool:
    text = open(FIXTURE).read()
    print("=" * 74)
    print("  ARITIQ — Phase 2 end-to-end TABLE-grounded verification")
    print("  (parse -> normalize -> ground from cells -> verify; verify.py UNCHANGED)")
    print("=" * 74)

    claims = build_claims_from_fixture(text)
    if not claims:
        print("  ERROR: no claims could be grounded from the fixture.")
        return False

    all_ok = True
    for rule, claim, expected in claims:
        r = verify_claim(claim)
        ok = (r.status.value == expected)
        all_ok = all_ok and ok
        prov = claim.operands[0].source.value
        print(f"    [{'ok ' if ok else 'FAIL'}] {rule:<24} provenance={prov:<20} "
              f"expected={expected:<10} got={r.status.value}")
        print(f"           {r.explanation}")

    print("-" * 74)
    print(f"  RESULT: {'all table-grounded claims verified end-to-end' if all_ok else 'FAILED'}")
    print("  This proves §2.3: the verifier did not change to handle tables.")
    print("  It is a constructed fixture, NOT a real-filing accuracy number.")
    print("=" * 74)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
