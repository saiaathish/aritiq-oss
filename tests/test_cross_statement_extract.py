"""
Cross-statement EXTRACTION tests (Phase 2, spec §3).

No LLM / no API key — every model response is injected as a string through a
fake complete_fn, exactly like the Phase 1 extraction tests.

These pin the two things that keep this feature honest:
  1. the new schema fields (rule_name, eps_variant, operand category) survive
     validation and conversion into the verifier's Claim;
  2. the applicability discipline (§3): a rule whose statement is absent yields
     ZERO claims, NOT a claim with all-missing operands masquerading as
     UNSUPPORTED_NUMBER.
Plus a firewall test: the cross_statement extractor must not import the verifier.
"""
import ast
import os

import pytest

from aritiq.core.schema import (
    Operation, OperandSource, EPSVariant, VerificationStatus,
)
from aritiq.core.verify import verify_claim
from aritiq.extract import extract_internal_consistency, parse_claims

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Schema round-trip for internal_consistency claims
# ---------------------------------------------------------------------------

class TestInternalConsistencyParsing:
    def test_balance_sheet_claim_parses_with_rule_name(self):
        raw = (
            '[{"claim_text":"Balance sheet identity","operation":"internal_consistency",'
            '"rule_name":"balance_sheet_identity","stated_value":null,'
            '"params":{"liabilities_complete":true},'
            '"operands":[{"value":1500,"source":"grounded","source_text":"Total assets 1,500"},'
            '{"value":900,"source":"grounded","source_text":"Total liabilities 900"},'
            '{"value":600,"source":"grounded","source_text":"Total equity 600"}],'
            '"unit":"$M"}]'
        )
        claims, issues = parse_claims(raw)
        assert len(claims) == 1 and not issues
        c = claims[0]
        assert c.operation == Operation.INTERNAL_CONSISTENCY
        assert c.rule_name == "balance_sheet_identity"
        assert c.stated_value is None
        # And it verifies through the real verifier:
        assert verify_claim(c).status == VerificationStatus.VERIFIED

    def test_eps_variant_and_category_survive(self):
        raw = (
            '[{"claim_text":"EPS reconciles","operation":"internal_consistency",'
            '"rule_name":"eps_reconciliation","stated_value":null,"eps_variant":"diluted",'
            '"params":{"eps_income_basis":"total","income_operand_basis":"total"},'
            '"operands":[{"value":2.0,"source":"grounded","source_text":"Diluted EPS 2.00"},'
            '{"value":200,"source":"grounded","source_text":"Net income 200"},'
            '{"value":100,"source":"grounded","source_text":"Diluted shares 100","category":"diluted"}],'
            '"unit":null}]'
        )
        claims, issues = parse_claims(raw)
        assert len(claims) == 1 and not issues
        c = claims[0]
        assert c.eps_variant == EPSVariant.DILUTED
        assert c.operands[2].category == "diluted"
        assert verify_claim(c).status == VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# Applicability: rule not present in document -> zero claims
# ---------------------------------------------------------------------------

class TestApplicabilityDiscipline:
    PRESS_RELEASE = (
        "Q3 revenue was $125M, up 12% year over year. The company reiterated "
        "full-year guidance. No balance sheet was included in this release."
    )

    def test_model_returns_empty_when_no_statement(self):
        # A faithful model, told to omit inapplicable rules, returns [].
        out = extract_internal_consistency(self.PRESS_RELEASE, complete_fn=lambda s, u: "[]")
        assert out.n_claims == 0
        assert out.n_issues == 0   # empty is clean, not an error

    def test_all_missing_operands_are_dropped_not_unsupported(self):
        """If a (mis-behaving) model emits a claim with ALL operands missing,
        the extractor DROPS it as not-applicable and records an issue — it must
        NOT pass through to become an UNSUPPORTED_NUMBER verdict."""
        bad = (
            '[{"claim_text":"Balance sheet identity","operation":"internal_consistency",'
            '"rule_name":"balance_sheet_identity","stated_value":null,'
            '"operands":[{"value":null,"source":"missing"},'
            '{"value":null,"source":"missing"},'
            '{"value":null,"source":"missing"}]}]'
        )
        out = extract_internal_consistency(self.PRESS_RELEASE, complete_fn=lambda s, u: bad)
        assert out.n_claims == 0                      # dropped
        assert out.n_issues == 1                      # and recorded as an issue
        assert "not applicable" in out.issues[0].reason.lower() or \
               "omitted" in out.issues[0].reason.lower()

    def test_partial_missing_still_emitted(self):
        """A claim with SOME operands present is genuinely 'unsupported', not
        'inapplicable' — it should survive and let the verifier judge it."""
        partial = (
            '[{"claim_text":"Balance sheet identity","operation":"internal_consistency",'
            '"rule_name":"balance_sheet_identity","stated_value":null,'
            '"operands":[{"value":1500,"source":"grounded"},'
            '{"value":null,"source":"missing"},'
            '{"value":600,"source":"grounded"}]}]'
        )
        out = extract_internal_consistency("doc with partial bs", complete_fn=lambda s, u: partial)
        assert out.n_claims == 1                      # survives
        assert verify_claim(out.claims[0]).status == VerificationStatus.UNSUPPORTED_NUMBER


# ---------------------------------------------------------------------------
# Firewall: the cross-statement extractor must not import the verifier
# ---------------------------------------------------------------------------

class TestCrossStatementFirewall:
    def _imports_in(self, path):
        tree = ast.parse(open(path).read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add(("." * (node.level or 0)) + (node.module or ""))
        return mods

    def test_no_verifier_import(self):
        path = os.path.join(REPO, "aritiq", "extract", "cross_statement.py")
        mods = self._imports_in(path)
        bad = [m for m in mods if "verify" in m or m.endswith(".score") or m == "score"]
        assert not bad, f"cross_statement extraction must not import verification code: {bad}"
