"""
Multi-document pipeline test suite (multi-document wiring).

This pins the FIX for the cross-document grounding failure: `audit_documents`
builds a registry, routes per-document, and surfaces cross-document CONFLICTs.

Everything runs offline via injected completion functions (no LLM, no API key):
  * `summary_fn`  — the summary-audit summary-grounding pass.
  * `cs_fn`       — the cross-statement per-document cross-statement pass; it returns
                    DIFFERENT claims depending on which document it is handed,
                    which is exactly the per-document routing the bug lacked.

The scenario is the Vesper Materials pair the failures were reported against, so
a green run here is the direct regression guard for "the FY2024 conflict never
appeared" and "claims grounded to the wrong document."
"""
import json

import pytest

from aritiq.pipeline import audit_documents, SourceDoc
from aritiq.core.schema import TableCell, VerificationStatus, RestatementType


DOC_A = (
    "Total revenue for fiscal year 2024 was $740.0 million. Net income was $96.0 "
    "million. Diluted EPS were $1.20 on 80.0 million diluted shares. Cash per the "
    "cash flow statement was $214.0 million, consistent with the balance sheet."
)
DOC_B = (
    "Total revenue for fiscal year 2025 was $851.0 million, compared to $710.0 "
    "million in fiscal year 2024, as restated. Fiscal 2024 revenue has been "
    "restated from the previously reported $740.0 million per Note 4. Gross profit "
    "was $298.0 million. Total assets $2,140.0 million, total liabilities $1,225.0 "
    "million, total equity $915.0 million. Net income for fiscal 2025 was $112.0 "
    "million. Diluted EPS were $1.36 on 82.4 million diluted shares. Cash per the "
    "cash flow statement $267.0 million; balance sheet cash $241.0 million (Note 9)."
)


def _docs():
    return [
        SourceDoc(doc_id="A_FY2024_10K", text=DOC_A, period="FY2024", doc_type="10-K",
                  tables=[TableCell(row_label="Total revenue", column_label="FY2024", value=740.0)]),
        SourceDoc(doc_id="B_FY2025_10K", text=DOC_B, period="FY2025", doc_type="10-K",
                  tables=[TableCell(row_label="Total revenue", column_label="FY2024", value=710.0),
                          TableCell(row_label="Total revenue", column_label="FY2025", value=851.0)]),
    ]


def _summary_fn(system_prompt, user_prompt):
    # Correctly-routed grounding: FY2025 claims ground to Doc B's figures, and
    # the growth base is the RESTATED 710, not the stale 740.
    return json.dumps([
        {"claim_text": "revenue grew 20% to $851.0M", "operation": "percent_change", "stated_value": 20,
         "operands": [{"value": 710, "source": "grounded", "source_text": "$710.0 million ... as restated"},
                      {"value": 851, "source": "grounded", "source_text": "$851.0 million"}], "unit": "%"},
        {"claim_text": "gross margin expanding to 35.0%", "operation": "margin_percent", "stated_value": 35,
         "operands": [{"value": 298, "source": "grounded", "source_text": "gross profit ... $298.0 million"},
                      {"value": 851, "source": "grounded", "source_text": "$851.0 million"}], "unit": "%"},
        {"claim_text": "Net income rose to $112.0M", "operation": "identity", "stated_value": 112,
         "operands": [{"value": 112, "source": "grounded", "source_text": "$112.0 million"}], "unit": "$M"},
        {"claim_text": "diluted EPS came in at $1.36", "operation": "identity", "stated_value": 1.36,
         "operands": [{"value": 1.36, "source": "grounded", "source_text": "$1.36"}], "unit": None},
    ])


def _cs_fn(system_prompt, user_prompt):
    # Per-document routing: the cross-statement pass returns the rule claims that
    # belong to whichever document it is handed. Doc B has the full statements;
    # Doc A only supports the (clean) cash tie-out.
    if "2,140" in user_prompt:  # Document B
        return json.dumps([
            {"claim_text": "BS identity", "operation": "internal_consistency",
             "rule_name": "balance_sheet_identity", "stated_value": None,
             "operands": [{"value": 2140, "source": "grounded"}, {"value": 1225, "source": "grounded"},
                          {"value": 915, "source": "grounded"}], "unit": "$M"},
            {"claim_text": "EPS diluted", "operation": "internal_consistency",
             "rule_name": "eps_reconciliation", "stated_value": None, "eps_variant": "diluted",
             "operands": [{"value": 1.36, "source": "grounded"}, {"value": 112, "source": "grounded"},
                          {"value": 82.4, "source": "grounded", "category": "diluted"}], "unit": None},
            {"claim_text": "cash tie B", "operation": "internal_consistency",
             "rule_name": "cash_flow_tie_out", "stated_value": None,
             "operands": [{"value": 267, "source": "grounded"}, {"value": 241, "source": "grounded"}], "unit": "$M"},
        ])
    return json.dumps([  # Document A
        {"claim_text": "cash tie A", "operation": "internal_consistency",
         "rule_name": "cash_flow_tie_out", "stated_value": None,
         "operands": [{"value": 214, "source": "grounded"}, {"value": 214, "source": "grounded"}], "unit": "$M"},
    ])


@pytest.fixture
def audit():
    return audit_documents(_docs(), "Vesper summary", complete_fn=_summary_fn, cs_complete_fn=_cs_fn)


# ===========================================================================
# The four reported failures, each now a passing regression guard
# ===========================================================================

class TestNoStaleDocFalsePositives:
    def test_net_income_verifies_not_false_wrong_math(self, audit):
        r = _by_text(audit, "Net income rose to $112.0M")
        assert r.status == VerificationStatus.VERIFIED, r.explanation

    def test_diluted_eps_control_case_verifies(self, audit):
        r = _by_text(audit, "diluted EPS came in at $1.36")
        assert r.status == VerificationStatus.VERIFIED, r.explanation

    def test_revenue_growth_against_restated_base_verifies(self, audit):
        r = _by_text(audit, "revenue grew 20% to $851.0M")
        assert r.status == VerificationStatus.VERIFIED, r.explanation

    def test_gross_margin_verifies_as_margin_percent(self, audit):
        r = _by_text(audit, "gross margin expanding to 35.0%")
        assert r.status == VerificationStatus.VERIFIED, r.explanation


class TestCrossDocumentConflictSurfaces:
    def test_fy2024_conflict_appears(self, audit):
        # The piece that failed four times. It must now be present.
        assert len(audit.conflicts) == 1
        c = audit.conflicts[0]
        assert c.status == VerificationStatus.CONFLICT
        assert {audit_conflict_values(c)} != {None}

    def test_conflict_classified_explicit_restatement(self, audit):
        c = audit.conflicts[0]
        assert c.restatement_type == RestatementType.EXPLICIT_RESTATEMENT

    def test_conflict_is_also_in_results_and_scored(self, audit):
        # The conflict counts toward the score (a source disagreement is a red flag).
        statuses = [r.status for r in audit.results]
        assert VerificationStatus.CONFLICT in statuses
        assert audit.score.conflict == 1


class TestPerDocumentCashTieOut:
    def test_doc_b_real_gap_is_wrong_math(self, audit):
        # Doc B's 267 vs 241 gap must be caught — the rule must run on Doc B,
        # not only on Doc A as in the bug.
        r = _by_text(audit, "cash tie B")
        assert r.status == VerificationStatus.WRONG_MATH, r.explanation

    def test_doc_a_clean_tie_still_verifies(self, audit):
        r = _by_text(audit, "cash tie A")
        assert r.status == VerificationStatus.VERIFIED


class TestNoRegressionSingleDoc:
    def test_single_document_list_still_works(self):
        # A one-document list must behave like an ordinary audit (no conflict).
        res = audit_documents([_docs()[1]], "s", complete_fn=_summary_fn, cs_complete_fn=_cs_fn)
        assert res.conflicts == []
        assert any(r.status == VerificationStatus.VERIFIED for r in res.results)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _by_text(audit, needle):
    for r in audit.results:
        if needle in r.claim.claim_text:
            return r
    raise AssertionError(f"no result whose claim_text contains {needle!r}")


def audit_conflict_values(result):
    return tuple(o.value for o in result.claim.operands)
