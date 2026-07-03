"""
multi-document end-to-end backend test — the Vesper Materials document pair.

This suite exists because four live runs of a TWO-DOCUMENT input failed in ways
that turned out to share one root cause: the registry / conflict / restatement
layer was built in core/ but never WIRED into the pipeline, and the single-string
`source` gave the extractor no way to route a claim to the document it describes.

These tests drive the deterministic layer directly (NO LLM, NO API key) with
hand-grounded claims carrying explicit doc_ids — i.e. they assume extraction did
its job — and prove that EVERY component then computes the correct verdict on the
Vesper figures:

  summary-audit arithmetic        — revenue growth (against the RESTATED base), margin
  cross-statement internal-consistency — balance-sheet identity, EPS (diluted), cash tie-out
  cross-statement cross-document    — the FY2024 revenue CONFLICT ($740M vs $710M restated)
  multi-document the restatement classifier            — that conflict classified EXPLICIT_RESTATEMENT
  multi-document the provenance graph            — propagation from the disputed base into derived claims
  multi-document the weighted score            — dependency-weighted score reflects the upstream root

The Vesper ground truth (built to be exact):
  Doc A (FY2024 10-K):     revenue 740, COGS 481, GP 259, assets 1950, liab 1120,
                           equity 830, NI 96, diluted EPS 1.20 @ 80.0 dil shares,
                           cash CF 214 == BS 214.
  Doc B (FY2025 10-K):     revenue 851 (vs 710 FY2024 *as restated* from 740),
                           COGS 553, GP 298, assets 2140, liab 1225, equity 915,
                           NI 112, basic EPS 1.40 @ 80.0 basic, diluted 1.36 @ 82.4
                           diluted, cash CF 267 vs BS 241 (26 restricted, Note 9).
"""
import math

import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, EPSVariant,
    DocumentRegistry, SourceDocument, TableCell,
    VerificationStatus, RestatementType,
)
from aritiq.core.verify import verify_claim
from aritiq.core.registry import find_conflicts, operand_conflict_for
from aritiq.core.restatement import classify_restatement
from aritiq.core.graph import propagate_errors, build_dag
from aritiq.core.score import compute_score


# ---------------------------------------------------------------------------
# The Vesper source documents (verbatim enough for the disclosure scan).
# ---------------------------------------------------------------------------

DOC_A_TEXT = (
    "Total revenue for fiscal year 2024 was $740.0 million. Cost of revenue was "
    "$481.0 million, yielding gross profit of $259.0 million. Total assets were "
    "$1,950.0 million, total liabilities were $1,120.0 million, and total "
    "stockholders' equity was $830.0 million. Net income attributable to common "
    "stockholders was $96.0 million. Diluted earnings per share were $1.20, based "
    "on 80.0 million diluted weighted-average shares outstanding. Cash and cash "
    "equivalents at end of period, per the statement of cash flows, were $214.0 "
    "million, consistent with the cash and cash equivalents line on the balance sheet."
)

DOC_B_TEXT = (
    "Total revenue for fiscal year 2025 was $851.0 million, compared to $710.0 "
    "million in fiscal year 2024, as restated. Fiscal 2024 revenue has been "
    "restated from the previously reported $740.0 million to reflect the "
    "deconsolidation of a discontinued joint venture, as disclosed in Note 4. "
    "Cost of revenue for fiscal 2025 was $553.0 million, yielding gross profit of "
    "$298.0 million. Total assets at December 31, 2025 were $2,140.0 million, total "
    "liabilities were $1,225.0 million, and total stockholders' equity was $915.0 "
    "million. Net income attributable to common stockholders for fiscal 2025 was "
    "$112.0 million. Basic earnings per share were $1.40, based on 80.0 million "
    "basic weighted-average shares outstanding; diluted earnings per share were "
    "$1.36, based on 82.4 million diluted weighted-average shares outstanding. Cash "
    "and cash equivalents at end of period, per the statement of cash flows, were "
    "$267.0 million. The balance sheet reflects cash and cash equivalents of $241.0 "
    "million, with the $26.0 million difference attributable to restricted cash held "
    "in escrow under the terms of a pending litigation settlement, as disclosed in Note 9."
)


def _registry() -> DocumentRegistry:
    """Both documents, with the FY2024 revenue figure as a labelled table cell in
    each so the cross-document conflict is detectable."""
    reg = DocumentRegistry()
    reg.add(SourceDocument(
        doc_id="A_FY2024_10K", text=DOC_A_TEXT, period="FY2024", doc_type="10-K",
        tables=[TableCell(row_label="Total revenue", column_label="FY2024", value=740.0)],
    ))
    reg.add(SourceDocument(
        doc_id="B_FY2025_10K", text=DOC_B_TEXT, period="FY2025", doc_type="10-K",
        tables=[
            TableCell(row_label="Total revenue", column_label="FY2024", value=710.0),
            TableCell(row_label="Total revenue", column_label="FY2025", value=851.0),
        ],
    ))
    return reg


# ===========================================================================
# summary-audit — arithmetic on the summary's own claims (grounded to the RIGHT doc)
# ===========================================================================

class TestPhase1Arithmetic:
    def test_revenue_growth_against_restated_base_verifies(self):
        # Summary: "grew 20% to $851.0M". Correct base is the RESTATED 710 (Doc B),
        # NOT the original 740 (Doc A). (851-710)/710 = 19.86% ~= 20%.
        c = Claim(
            claim_text="revenue grew 20% year-over-year to $851.0M",
            operation=Operation.PERCENT_CHANGE, stated_value=20.0,
            operands=[
                Operand(value=710.0, source=OperandSource.GROUNDED,
                        source_text="$710.0 million in fiscal year 2024, as restated",
                        doc_id="B_FY2025_10K"),
                Operand(value=851.0, source=OperandSource.GROUNDED,
                        source_text="$851.0 million", doc_id="B_FY2025_10K"),
            ],
            unit="%",
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED, r.explanation

    def test_revenue_growth_against_stale_base_is_wrong_math(self):
        # The bug's signature: if grounded against the ORIGINAL 740 (Doc A),
        # (851-740)/740 = 15.0% != stated 20% -> WRONG_MATH. This is the FALSE
        # POSITIVE we must avoid by grounding to the right document.
        c = Claim(
            claim_text="revenue grew 20% year-over-year to $851.0M",
            operation=Operation.PERCENT_CHANGE, stated_value=20.0,
            operands=[
                Operand(value=740.0, source=OperandSource.GROUNDED, doc_id="A_FY2024_10K"),
                Operand(value=851.0, source=OperandSource.GROUNDED, doc_id="B_FY2025_10K"),
            ],
            unit="%",
        )
        r = verify_claim(c)
        # Demonstrates the failure mode explicitly: wrong base -> false WRONG_MATH.
        assert r.status == VerificationStatus.WRONG_MATH
        assert abs(r.recomputed_value - 15.0) < 0.05

    def test_gross_margin_is_margin_percent_not_identity(self):
        # Summary: "gross margin expanding to 35.0%". 298/851 = 35.02%.
        # MUST be margin_percent (two operands -> ratio), NOT identity (which
        # expects one operand and chokes on two -> the AMBIGUOUS bug we saw).
        c = Claim(
            claim_text="gross margin expanding to 35.0%",
            operation=Operation.MARGIN_PERCENT, stated_value=35.0,
            operands=[
                Operand(value=298.0, source=OperandSource.GROUNDED,
                        source_text="gross profit of $298.0 million", doc_id="B_FY2025_10K"),
                Operand(value=851.0, source=OperandSource.GROUNDED,
                        source_text="$851.0 million", doc_id="B_FY2025_10K"),
            ],
            unit="%",
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED, r.explanation

    def test_net_income_grounds_to_doc_b_not_doc_a(self):
        # Summary: "Net income rose to $112.0M". The TRUE FY2025 figure is 112
        # (Doc B). Grounding to Doc A's 96 (FY2024) is the false-positive bug.
        # As an identity restatement of Doc B's own figure, it verifies.
        c = Claim(
            claim_text="Net income rose to $112.0M",
            operation=Operation.IDENTITY, stated_value=112.0,
            operands=[Operand(value=112.0, source=OperandSource.GROUNDED,
                              source_text="$112.0 million", doc_id="B_FY2025_10K")],
            unit="$M",
        )
        r = verify_claim(c)
        assert r.status == VerificationStatus.VERIFIED, r.explanation


# ===========================================================================
# cross-statement — internal consistency on the correct document
# ===========================================================================

class TestPhase2InternalConsistency:
    def _ic(self, rule_name, vals, **kw):
        ops = [Operand(value=v, source=OperandSource.GROUNDED) for v in vals]
        cat = kw.pop("shares_category", None)
        if cat and len(ops) >= 3:
            ops[2].category = cat
        params = kw.pop("params", None) or {}
        # Default to complete/well-scoped evidence unless a test overrides.
        if rule_name == "balance_sheet_identity":
            params.setdefault("liabilities_complete", True)
        elif rule_name == "eps_reconciliation":
            params.setdefault("eps_income_basis", "total")
            params.setdefault("income_operand_basis", "total")
        return Claim(claim_text=f"{rule_name}", operation=Operation.INTERNAL_CONSISTENCY,
                     stated_value=None, operands=ops, rule_name=rule_name, params=params, **kw)

    def test_balance_sheet_identity_fy2025_verifies(self):
        # 1225 + 915 = 2140 exactly.
        r = verify_claim(self._ic("balance_sheet_identity", [2140.0, 1225.0, 915.0]))
        assert r.status == VerificationStatus.VERIFIED, r.explanation

    def test_eps_diluted_reconciles(self):
        # 112 / 82.4 = 1.3592 ~= 1.36 (diluted), variants tagged & matching.
        r = verify_claim(self._ic("eps_reconciliation", [1.36, 112.0, 82.4],
                                  eps_variant=EPSVariant.DILUTED, shares_category="diluted"))
        assert r.status == VerificationStatus.VERIFIED, r.explanation

    def test_eps_basic_would_also_reconcile_but_must_not_cross_wire(self):
        # 112 / 80.0 = 1.40 (basic). If the summary's diluted claim were
        # cross-wired to basic shares, the guard must catch it as AMBIGUOUS,
        # never silently verify a diluted EPS against basic shares.
        r = verify_claim(self._ic("eps_reconciliation", [1.36, 112.0, 80.0],
                                  eps_variant=EPSVariant.DILUTED, shares_category="basic"))
        assert r.status == VerificationStatus.AMBIGUOUS
        assert "variant" in r.explanation.lower()

    def test_cash_tie_out_doc_b_is_the_real_gap(self):
        # Doc B: CF 267 vs BS 241 -> a real 26 gap (restricted cash). This must
        # NOT verify clean. The earlier run only ever ran this on Doc A (214==214).
        r = verify_claim(self._ic("cash_flow_tie_out", [267.0, 241.0]))
        assert r.status == VerificationStatus.WRONG_MATH, r.explanation

    def test_cash_tie_out_doc_a_is_clean_control(self):
        # Doc A: CF 214 == BS 214 -> clean. (The control the bug accidentally ran.)
        r = verify_claim(self._ic("cash_flow_tie_out", [214.0, 214.0]))
        assert r.status == VerificationStatus.VERIFIED


# ===========================================================================
# cross-statement cross-document — the FY2024 revenue CONFLICT (failed 4x live)
# ===========================================================================

class TestCrossDocumentConflict:
    def test_fy2024_revenue_conflict_is_detected(self):
        reg = _registry()
        conflicts = find_conflicts(reg)
        # Exactly the FY2024 revenue disagreement: 740 (Doc A) vs 710 (Doc B).
        assert len(conflicts) == 1, [c.describe() for c in conflicts]
        c = conflicts[0]
        assert {c.value_a, c.value_b} == {740.0, 710.0}
        assert c.row_label.lower() == "total revenue"

    def test_operand_conflict_hook_finds_it(self):
        reg = _registry()
        c = operand_conflict_for(reg, "Total revenue", "FY2024")
        assert c is not None
        assert {c.value_a, c.value_b} == {740.0, 710.0}

    def test_fy2025_revenue_does_not_conflict(self):
        # Only Doc B reports FY2025 revenue -> no disagreement, no false conflict.
        reg = _registry()
        assert operand_conflict_for(reg, "Total revenue", "FY2025") is None


# ===========================================================================
# multi-document the restatement classifier — classify that conflict via the filer's disclosure language
# ===========================================================================

class TestRestatementClassification:
    def test_fy2024_conflict_classified_explicit_restatement(self):
        reg = _registry()
        conflict = find_conflicts(reg)[0]
        later = reg.get("B_FY2025_10K")   # the document carrying "as restated"
        annotated = classify_restatement(conflict, later_doc=later)
        assert annotated.restatement_type == RestatementType.EXPLICIT_RESTATEMENT
        assert annotated.matched_disclosure_text is not None
        # describe() should still say it is not auto-resolved.
        assert "human" in annotated.describe().lower()


# ===========================================================================
# multi-document the provenance graph + the weighted score — propagation from the disputed base, weighted score
# ===========================================================================

class TestPropagationAndScore:
    def _derived_claim_set(self):
        """A small claim set where revenue growth and gross margin both derive
        from the FY2024 base whose cross-document value is disputed.

        We model the disputed base as a root claim that fails verification (its
        cross-document conflict makes the honest verdict not-VERIFIED), and the
        two derived claims depend on it.
        """
        # Root: the FY2024 revenue base, flagged because the registry disputes it.
        base = Claim(
            claim_text="FY2024 revenue base (disputed across filings)",
            operation=Operation.IDENTITY, stated_value=710.0,
            operands=[Operand(value=740.0, source=OperandSource.GROUNDED, doc_id="A_FY2024_10K")],
            node_id="fy2024_revenue",
        )
        growth = Claim(
            claim_text="revenue grew 20% to $851.0M",
            operation=Operation.PERCENT_CHANGE, stated_value=20.0,
            operands=[
                Operand(value=710.0, source=OperandSource.GROUNDED, doc_id="B_FY2025_10K"),
                Operand(value=851.0, source=OperandSource.GROUNDED, doc_id="B_FY2025_10K"),
            ],
            node_id="revenue_growth", depends_on=["fy2024_revenue"],
        )
        margin = Claim(
            claim_text="gross margin 35.0%",
            operation=Operation.MARGIN_PERCENT, stated_value=35.0,
            operands=[
                Operand(value=298.0, source=OperandSource.GROUNDED, doc_id="B_FY2025_10K"),
                Operand(value=851.0, source=OperandSource.GROUNDED, doc_id="B_FY2025_10K"),
            ],
            node_id="gross_margin", depends_on=["fy2024_revenue"],
        )
        return [base, growth, margin]

    def test_propagation_marks_downstream_of_disputed_base(self):
        claims = self._derived_claim_set()
        # Verify each independently; force the base to a failing verdict to model
        # "this base is not trustworthy" (a conflict-driven WRONG_MATH).
        results = []
        for c in claims:
            r = verify_claim(c)
            if c.node_id == "fy2024_revenue":
                r = type(r)(claim=c, status=VerificationStatus.WRONG_MATH,
                            explanation="disputed across filings (740 vs 710 restated)")
            results.append(r)

        propagated = propagate_errors(results)
        by_id = {r.claim.node_id: r for r in propagated}
        assert by_id["fy2024_revenue"].status == VerificationStatus.WRONG_MATH
        # Both derived claims should now show they rest on the disputed base.
        for nid in ("revenue_growth", "gross_margin"):
            assert by_id[nid].status == VerificationStatus.PROPAGATED_ERROR, nid
            assert by_id[nid].caused_by == "fy2024_revenue", nid

    def test_weighted_score_reflects_upstream_root(self):
        claims = self._derived_claim_set()
        results = []
        for c in claims:
            r = verify_claim(c)
            if c.node_id == "fy2024_revenue":
                r = type(r)(claim=c, status=VerificationStatus.WRONG_MATH,
                            explanation="disputed across filings")
            results.append(r)
        propagated = propagate_errors(results)
        s = compute_score(propagated, claims=claims)
        # The two downstream are PROPAGATED_ERROR -> excluded; the root counts once.
        assert s.propagated_error == 2
        assert s.total_checkable == 1
        # And both numbers are present (weighted shown beside unweighted).
        assert isinstance(s.score, float) and isinstance(s.unweighted_score, float)
