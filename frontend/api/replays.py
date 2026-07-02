"""
Example documents + OFFLINE replay fixtures for the Aritiq UI.

Text and saved model output live together here so they never drift apart. Each
example carries:
  - source / summary            : the inputs shown in the UI
  - summary_extraction          : saved Phase 1 (summary-audit) model JSON
  - cross_statement_extraction  : saved Phase 2 (cross-statement) model JSON,
                                  or None when the document has no statements

Same replay discipline as benchmark/runs/: deterministic, key-free fixtures, so
the demo is reproducible. Fixtures are written to match each document's ACTUAL
numbers, so the verifier (not a model) produces the verdicts — including a real
Phase 2 internal-consistency catch in example D.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass
class Example:
    id: str
    name: str
    source: str
    summary: str
    summary_extraction: str
    cross_statement_extraction: Optional[str] = None


# ===========================================================================
# A — Meridian SaaS (arithmetic only). Errors: margin 70% stated as 60%,
#     customers 980 stated as 1,020. ARR +50% verifies.
# ===========================================================================

_A_SOURCE = """Meridian SaaS Corp — Q2 FY2026 Financial Summary

ARR (Annual Recurring Revenue): $48.0 million
Prior year Q2 ARR: $32.0 million

Q2 Revenue: $12.0 million
Q2 Cost of Revenue: $3.6 million
Q2 Gross Profit: $8.4 million

Sales & Marketing spend: $5.0 million
R&D spend: $3.0 million
G&A spend: $1.5 million
Total Operating Expenses: $9.5 million

Net Loss: $1.1 million

New customers acquired Q2: 140
Total customers end of Q2: 980
Churned customers Q2: 20

Average Revenue Per Account (ARPA): $48,980"""

_A_SUMMARY = """Meridian SaaS Corp posted solid Q2 FY2026 results. ARR grew 50% year-over-year from $32.0 million to $48.0 million. Quarterly revenue was $12.0 million with a gross margin of 60%, generating $8.4 million in gross profit. Total operating expenses were $9.5 million, leading to a net loss of $1.1 million. The company added 140 new customers while losing 20, bringing the total customer base to 1,020. Customer ARPA stands at $48,980."""

_A_SUMMARY_EXTRACTION = """[
  {"claim_text": "ARR grew 50% year-over-year from $32.0 million to $48.0 million",
   "operation": "percent_change", "stated_value": 50,
   "operands": [{"value": 32, "source": "grounded", "source_text": "Prior year Q2 ARR: $32.0 million"},
                {"value": 48, "source": "grounded", "source_text": "ARR (Annual Recurring Revenue): $48.0 million"}],
   "unit": "%", "source_text": "ARR $48.0 million; Prior year Q2 ARR $32.0 million"},
  {"claim_text": "gross margin of 60%", "operation": "margin_percent", "stated_value": 60,
   "operands": [{"value": 8.4, "source": "grounded", "source_text": "Q2 Gross Profit: $8.4 million"},
                {"value": 12, "source": "grounded", "source_text": "Q2 Revenue: $12.0 million"}],
   "unit": "%", "source_text": "Gross Profit $8.4M on Revenue $12.0M"},
  {"claim_text": "total operating expenses were $9.5 million", "operation": "identity", "stated_value": 9.5,
   "operands": [{"value": 9.5, "source": "grounded", "source_text": "Total Operating Expenses: $9.5 million"}],
   "unit": "$M", "source_text": "Total Operating Expenses: $9.5 million"},
  {"claim_text": "bringing the total customer base to 1,020", "operation": "identity", "stated_value": 1020,
   "operands": [{"value": 980, "source": "grounded", "source_text": "Total customers end of Q2: 980"}],
   "unit": null, "source_text": "Total customers end of Q2: 980"}
]"""


# ===========================================================================
# B — TechVenture (arithmetic only). Errors: op margin 42.86% stated as 57%,
#     headcount +19.4% stated as 25%. Revenue +20% and subs-sum verify.
# ===========================================================================

_B_SOURCE = """TechVenture Inc — FY2025 Annual Report Highlights

Total Revenue: $84.0 million
Prior Year Revenue: $70.0 million

Subscription Revenue: $60.0 million
Professional Services Revenue: $24.0 million

R&D Expenses: $18.0 million
Sales & Marketing: $22.0 million
G&A: $8.0 million
Total Operating Expenses: $48.0 million

Operating Income: $36.0 million
Interest Expense: $4.0 million
Net Income: $32.0 million

Headcount: 430 employees
Prior Year Headcount: 360 employees"""

_B_SUMMARY = """TechVenture Inc closed FY2025 with total revenue of $84.0 million, a 20% increase over the prior year. Subscription revenue accounted for $60.0 million of the total, with professional services contributing $24.0 million, combining for $84.0 million. Operating expenses totaled $48.0 million, yielding an operating margin of 57%. Net income was $32.0 million. Headcount grew 25% year-over-year from 360 to 430 employees."""

_B_SUMMARY_EXTRACTION = """[
  {"claim_text": "total revenue of $84.0 million, a 20% increase over the prior year",
   "operation": "percent_change", "stated_value": 20,
   "operands": [{"value": 70, "source": "grounded", "source_text": "Prior Year Revenue: $70.0 million"},
                {"value": 84, "source": "grounded", "source_text": "Total Revenue: $84.0 million"}],
   "unit": "%", "source_text": "Total Revenue $84.0M; Prior Year $70.0M"},
  {"claim_text": "subscription $60.0 million ... professional services $24.0 million, combining for $84.0 million",
   "operation": "sum", "stated_value": 84,
   "operands": [{"value": 60, "source": "grounded", "source_text": "Subscription Revenue: $60.0 million"},
                {"value": 24, "source": "grounded", "source_text": "Professional Services Revenue: $24.0 million"}],
   "unit": "$M", "source_text": "Subscription $60.0M + Professional Services $24.0M"},
  {"claim_text": "operating expenses totaled $48.0 million, yielding an operating margin of 57%",
   "operation": "margin_percent", "stated_value": 57,
   "operands": [{"value": 36, "source": "grounded", "source_text": "Operating Income: $36.0 million"},
                {"value": 84, "source": "grounded", "source_text": "Total Revenue: $84.0 million"}],
   "unit": "%", "source_text": "Operating Income $36.0M on Revenue $84.0M"},
  {"claim_text": "Headcount grew 25% year-over-year from 360 to 430 employees",
   "operation": "percent_change", "stated_value": 25,
   "operands": [{"value": 360, "source": "grounded", "source_text": "Prior Year Headcount: 360 employees"},
                {"value": 430, "source": "grounded", "source_text": "Headcount: 430 employees"}],
   "unit": "%", "source_text": "Headcount 430; Prior Year 360"}
]"""


# ===========================================================================
# C — Northwind Logistics (arithmetic only). Errors: revenue +25% stated as
#     30%, margin 40% stated as 45%. Net-income +50% and revenue-sum verify.
# ===========================================================================

_C_SOURCE = """Northwind Logistics Q3 FY2025 Earnings Release

Revenue: $125.0 million
Prior year Q3 revenue: $100.0 million

Gross profit: $50.0 million
Operating expenses: $30.0 million
Operating income: $20.0 million

Net income: $15.0 million
Net income prior year Q3: $10.0 million

Domestic revenue: $75.0 million
International revenue: $50.0 million

Gross margin calculated on $125.0 million revenue base.
Total headcount: 1,200 employees."""

_C_SUMMARY = """Northwind Logistics delivered strong Q3 FY2025 results. Total revenue reached $125.0 million, representing a 30% increase over the prior year. Gross profit was $50.0 million, yielding a gross margin of 45%. Operating income came in at $20.0 million. Net income grew from $10.0 million to $15.0 million, a 50% increase. Domestic revenue was $75.0 million and international revenue was $50.0 million, combining for total revenue of $125.0 million."""

_C_SUMMARY_EXTRACTION = """[
  {"claim_text": "total revenue reached $125.0 million, representing a 30% increase over the prior year",
   "operation": "percent_change", "stated_value": 30,
   "operands": [{"value": 100, "source": "grounded", "source_text": "Prior year Q3 revenue: $100.0 million"},
                {"value": 125, "source": "grounded", "source_text": "Revenue: $125.0 million"}],
   "unit": "%", "source_text": "Revenue $125.0M; Prior year $100.0M"},
  {"claim_text": "gross profit was $50.0 million, yielding a gross margin of 45%",
   "operation": "margin_percent", "stated_value": 45,
   "operands": [{"value": 50, "source": "grounded", "source_text": "Gross profit: $50.0 million"},
                {"value": 125, "source": "grounded", "source_text": "Revenue: $125.0 million"}],
   "unit": "%", "source_text": "Gross profit $50.0M on Revenue $125.0M"},
  {"claim_text": "net income grew from $10.0 million to $15.0 million, a 50% increase",
   "operation": "percent_change", "stated_value": 50,
   "operands": [{"value": 10, "source": "grounded", "source_text": "Net income prior year Q3: $10.0 million"},
                {"value": 15, "source": "grounded", "source_text": "Net income: $15.0 million"}],
   "unit": "%", "source_text": "Net income $15.0M; prior year $10.0M"},
  {"claim_text": "domestic $75.0 million and international $50.0 million, combining for total revenue of $125.0 million",
   "operation": "sum", "stated_value": 125,
   "operands": [{"value": 75, "source": "grounded", "source_text": "Domestic revenue: $75.0 million"},
                {"value": 50, "source": "grounded", "source_text": "International revenue: $50.0 million"}],
   "unit": "$M", "source_text": "Domestic $75.0M + International $50.0M"}
]"""


# ===========================================================================
# D — Northwind Industries 10-K (PHASE 2 SHOWCASE). Full statements, so the
#     cross-statement checks run: balance sheet balances (VERIFIED), EPS does
#     NOT reconcile — stated 2.10 but 240/100 = 2.40 (WRONG_MATH), cash ties
#     out (VERIFIED). Plus a Phase 1 revenue claim that verifies.
# ===========================================================================

_D_SOURCE = """Northwind Industries — Form 10-K (excerpt), fiscal year 2024
(US$ millions, except per-share data)

CONSOLIDATED BALANCE SHEET
  Total assets ................................ 1,500
  Total liabilities ........................... 900
  Total shareholders' equity .................. 600
  Cash and cash equivalents ................... 130

CONSOLIDATED STATEMENT OF OPERATIONS
  Net income .................................. 240
  Diluted weighted-average shares ............. 100
  Diluted earnings per share .................. 2.10

CONSOLIDATED STATEMENT OF CASH FLOWS
  Cash and cash equivalents, end of period .... 130

Full-year revenue was 1,120, up from 1,000 the prior year."""

_D_SUMMARY = """Northwind Industries grew revenue 12% year over year to $1,120M and reported diluted EPS of $2.10 for fiscal 2024."""

_D_SUMMARY_EXTRACTION = """[
  {"claim_text": "grew revenue 12% year over year to $1,120M",
   "operation": "percent_change", "stated_value": 12,
   "operands": [{"value": 1000, "source": "grounded", "source_text": "1,000 the prior year"},
                {"value": 1120, "source": "grounded", "source_text": "Full-year revenue was 1,120"}],
   "unit": "%", "source_text": "Full-year revenue was 1,120, up from 1,000 the prior year"}
]"""

_D_CROSS_STATEMENT_EXTRACTION = """[
  {"claim_text": "Balance sheet identity (FY2024)",
   "operation": "internal_consistency", "rule_name": "balance_sheet_identity", "stated_value": null,
   "operands": [{"value": 1500, "source": "grounded", "source_text": "Total assets 1,500"},
                {"value": 900, "source": "grounded", "source_text": "Total liabilities 900"},
                {"value": 600, "source": "grounded", "source_text": "Total shareholders' equity 600"}],
   "unit": "$M", "source_text": "CONSOLIDATED BALANCE SHEET"},
  {"claim_text": "Diluted EPS reconciliation (FY2024)",
   "operation": "internal_consistency", "rule_name": "eps_reconciliation", "stated_value": null,
   "eps_variant": "diluted",
   "operands": [{"value": 2.10, "source": "grounded", "source_text": "Diluted earnings per share 2.10"},
                {"value": 240, "source": "grounded", "source_text": "Net income 240"},
                {"value": 100, "source": "grounded", "source_text": "Diluted weighted-average shares 100", "category": "diluted"}],
   "unit": null, "source_text": "CONSOLIDATED STATEMENT OF OPERATIONS"},
  {"claim_text": "Cash flow tie-out (FY2024)",
   "operation": "internal_consistency", "rule_name": "cash_flow_tie_out", "stated_value": null,
   "operands": [{"value": 130, "source": "grounded", "source_text": "Cash and cash equivalents, end of period 130"},
                {"value": 130, "source": "grounded", "source_text": "Cash and cash equivalents 130"}],
   "unit": "$M", "source_text": "CONSOLIDATED STATEMENT OF CASH FLOWS"}
]"""


EXAMPLES = [
    Example("A", "Meridian SaaS — Q2 FY2026 (2 errors: margin + customer count)",
            _A_SOURCE, _A_SUMMARY, _A_SUMMARY_EXTRACTION, None),
    Example("B", "TechVenture Inc — FY2025 Annual (2 errors: margin + headcount growth)",
            _B_SOURCE, _B_SUMMARY, _B_SUMMARY_EXTRACTION, None),
    Example("C", "Northwind Logistics — Q3 FY2025 (1 error: revenue growth)",
            _C_SOURCE, _C_SUMMARY, _C_SUMMARY_EXTRACTION, None),
    Example("D", "Northwind Industries 10-K — internal consistency (EPS doesn't reconcile)",
            _D_SOURCE, _D_SUMMARY, _D_SUMMARY_EXTRACTION, _D_CROSS_STATEMENT_EXTRACTION),
]


def menu() -> list[dict]:
    """The list the /examples endpoint returns (no fixtures, just inputs)."""
    return [
        {"id": ex.id, "name": ex.name, "source": ex.source, "summary": ex.summary}
        for ex in EXAMPLES
    ]


CompleteFn = Callable[[str, str], str]


def find_replay(source: str, summary: str) -> Optional[Tuple[CompleteFn, Optional[CompleteFn]]]:
    """If source+summary match a known example, return (summary_fn, cs_fn).

    summary_fn replays the Phase 1 extraction; cs_fn replays the Phase 2
    cross-statement extraction (or None when the document has no statements).
    Returns None when nothing matches, so the caller falls through to the live
    backend. Match is on trimmed text for deterministic offline behavior.
    """
    s, m = source.strip(), summary.strip()
    for ex in EXAMPLES:
        if ex.source.strip() == s and ex.summary.strip() == m:
            summary_fn: CompleteFn = lambda sp, up, _x=ex.summary_extraction: _x
            cs_fn: Optional[CompleteFn] = (
                (lambda sp, up, _x=ex.cross_statement_extraction: _x)
                if ex.cross_statement_extraction
                else None
            )
            return summary_fn, cs_fn
    return None
