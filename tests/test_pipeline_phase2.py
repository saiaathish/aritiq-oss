"""
End-to-end wiring tests: Phase 2 claims must actually reach the AuditResult.

The bug these guard against: the verifier and UI both supported
internal_consistency, but the audit() pipeline never RAN cross-statement
extraction, so a real audit produced zero Phase 2 claims and every new UI
section was permanently empty. These tests prove the pipeline now emits them —
and that Phase 1-only inputs are unchanged.

No API key / no network — everything goes through injected replay fixtures.
"""
import pytest

from aritiq.pipeline import audit
from aritiq.core.schema import Operation, VerificationStatus


# A document WITH financial statements + its two replay fixtures.
SOURCE_WITH_STATEMENTS = """\
CONSOLIDATED BALANCE SHEET
  Total assets 1,500
  Total liabilities 900
  Total shareholders' equity 600
  Cash and cash equivalents 130
STATEMENT OF OPERATIONS
  Net income 240
  Diluted shares 100
  Diluted EPS 2.10
STATEMENT OF CASH FLOWS
  Cash and cash equivalents, end of period 130
Revenue was 1,120, up from 1,000."""

SUMMARY = "Revenue grew 12% to $1,120M with diluted EPS of $2.10."

SUMMARY_FIXTURE = """[
  {"claim_text": "Revenue grew 12% to $1,120M", "operation": "percent_change", "stated_value": 12,
   "operands": [{"value": 1000, "source": "grounded"}, {"value": 1120, "source": "grounded"}], "unit": "%"}
]"""

CS_FIXTURE = """[
  {"claim_text": "BS identity", "operation": "internal_consistency", "rule_name": "balance_sheet_identity",
   "stated_value": null, "params": {"liabilities_complete": true},
   "operands": [{"value": 1500, "source": "grounded"}, {"value": 900, "source": "grounded"}, {"value": 600, "source": "grounded"}]},
  {"claim_text": "EPS recon", "operation": "internal_consistency", "rule_name": "eps_reconciliation",
   "stated_value": null, "eps_variant": "diluted",
   "params": {"eps_income_basis": "total", "income_operand_basis": "total"},
   "operands": [{"value": 2.10, "source": "grounded"}, {"value": 240, "source": "grounded"},
                {"value": 100, "source": "grounded", "category": "diluted"}]},
  {"claim_text": "Cash tie", "operation": "internal_consistency", "rule_name": "cash_flow_tie_out",
   "stated_value": null,
   "operands": [{"value": 130, "source": "grounded"}, {"value": 130, "source": "grounded"}]}
]"""


class TestCrossStatementReachesPipeline:
    def test_internal_consistency_claims_are_emitted(self):
        res = audit(
            SOURCE_WITH_STATEMENTS, SUMMARY,
            complete_fn=lambda s, u: SUMMARY_FIXTURE,
            cs_complete_fn=lambda s, u: CS_FIXTURE,
        )
        internal = [r for r in res.results if r.claim.operation == Operation.INTERNAL_CONSISTENCY]
        assert len(internal) == 3, "all three cross-statement rules should reach the result"

    def test_verdicts_are_correct_end_to_end(self):
        res = audit(
            SOURCE_WITH_STATEMENTS, SUMMARY,
            complete_fn=lambda s, u: SUMMARY_FIXTURE,
            cs_complete_fn=lambda s, u: CS_FIXTURE,
        )
        by_rule = {
            r.claim.rule_name: r.status
            for r in res.results
            if r.claim.operation == Operation.INTERNAL_CONSISTENCY
        }
        assert by_rule["balance_sheet_identity"] == VerificationStatus.VERIFIED
        # stated EPS 2.10 but 240/100 = 2.40 -> caught by code
        assert by_rule["eps_reconciliation"] == VerificationStatus.WRONG_MATH
        assert by_rule["cash_flow_tie_out"] == VerificationStatus.VERIFIED

    def test_phase1_claim_still_present_alongside(self):
        res = audit(
            SOURCE_WITH_STATEMENTS, SUMMARY,
            complete_fn=lambda s, u: SUMMARY_FIXTURE,
            cs_complete_fn=lambda s, u: CS_FIXTURE,
        )
        arith = [r for r in res.results if r.claim.operation != Operation.INTERNAL_CONSISTENCY]
        assert len(arith) == 1 and arith[0].status == VerificationStatus.VERIFIED


class TestPhase1Unchanged:
    def test_no_cs_fixture_means_no_internal_claims(self):
        """A Phase 1 replay (summary fixture only, no cs fixture) must behave
        exactly as before: zero internal_consistency claims, no accidental
        cross-statement run."""
        res = audit(
            SOURCE_WITH_STATEMENTS, SUMMARY,
            complete_fn=lambda s, u: SUMMARY_FIXTURE,
            # no cs_complete_fn -> cross-statement is skipped on the replay path
        )
        internal = [r for r in res.results if r.claim.operation == Operation.INTERNAL_CONSISTENCY]
        assert internal == []
        assert len(res.results) == 1

    def test_check_flag_off_disables_cross_statement(self):
        res = audit(
            SOURCE_WITH_STATEMENTS, SUMMARY,
            complete_fn=lambda s, u: SUMMARY_FIXTURE,
            cs_complete_fn=lambda s, u: CS_FIXTURE,
            check_internal_consistency=False,
        )
        internal = [r for r in res.results if r.claim.operation == Operation.INTERNAL_CONSISTENCY]
        assert internal == []
