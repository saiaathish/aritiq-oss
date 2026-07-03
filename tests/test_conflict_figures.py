"""
Cross-document conflict-figure extraction tests (multi-document prose path).

This is the step that makes a cross-document CONFLICT fire on PROSE input (the
live UI case), not only on pre-parsed TableCells. The extractor is an LLM step,
but its parsing/normalization is pure code and is what these tests pin via
injected model output — no network, no key.

Covered:
  * metric + period normalization (controlled vocabulary; FY<year> canonical)
  * a restated prior-year figure is captured with the PRIOR period (so it can
    conflict with the original filing's value)
  * junk / unknown metric / unparseable period are dropped, never guessed
  * the full audit_documents prose path surfaces the FY2024 conflict
"""
import json

import pytest

from aritiq.extract.conflict_figures import (
    parse_conflict_figures,
    extract_conflict_figures,
)
from aritiq.pipeline import audit_documents, SourceDoc
from aritiq.core.schema import VerificationStatus, RestatementType


# ===========================================================================
# Parsing / normalization (pure code)
# ===========================================================================

class TestParseAndNormalize:
    def test_metric_and_period_normalized(self):
        raw = json.dumps([
            {"metric": "total_revenue", "period": "fiscal year 2024", "value": 740.0, "source_text": "x"},
            {"metric": "Net Income", "period": "FY2024", "value": 96.0, "source_text": "x"},
        ])
        cells = parse_conflict_figures(raw, "DOC_A")
        keys = {(c.row_label, c.column_label, c.value) for c in cells}
        assert ("Total revenue", "FY2024", 740.0) in keys
        assert ("Net income", "FY2024", 96.0) in keys
        assert all(c.doc_id == "DOC_A" for c in cells)

    def test_restated_prior_year_captured_with_prior_period(self):
        # The crucial one: a FY2025 filing reporting FY2024 revenue "as restated"
        # must yield a FY2024-labelled cell so it can conflict with the FY2024 10-K.
        raw = json.dumps([
            {"metric": "total_revenue", "period": "FY2025", "value": 851.0, "source_text": "x"},
            {"metric": "total_revenue", "period": "FY2024", "value": 710.0, "source_text": "as restated"},
        ])
        cells = parse_conflict_figures(raw, "DOC_B")
        fy24 = [c for c in cells if c.column_label == "FY2024"]
        assert len(fy24) == 1 and fy24[0].value == 710.0

    def test_unknown_metric_dropped(self):
        raw = json.dumps([{"metric": "vibes", "period": "FY2024", "value": 1.0, "source_text": "x"}])
        assert parse_conflict_figures(raw, "D") == []

    def test_unparseable_period_dropped(self):
        raw = json.dumps([{"metric": "total_revenue", "period": "sometime", "value": 1.0, "source_text": "x"}])
        assert parse_conflict_figures(raw, "D") == []

    def test_non_numeric_value_dropped(self):
        raw = json.dumps([{"metric": "total_revenue", "period": "FY2024", "value": "lots", "source_text": "x"}])
        assert parse_conflict_figures(raw, "D") == []

    def test_garbage_response_is_empty_not_crash(self):
        assert parse_conflict_figures("not json at all", "D") == []
        assert parse_conflict_figures("", "D") == []

    def test_injected_completion_fn_path(self):
        def fn(system_prompt, user_prompt):
            return json.dumps([{"metric": "total_revenue", "period": "FY2024", "value": 740.0, "source_text": "x"}])
        cells = extract_conflict_figures("prose...", "DOC_A", complete_fn=fn)
        assert len(cells) == 1 and cells[0].value == 740.0


# ===========================================================================
# Full prose path — the FY2024 conflict fires WITHOUT pre-parsed tables
# ===========================================================================

DOC_A = (
    "Source Document A — Vesper FY2024 10-K. Total revenue for fiscal year 2024 "
    "was $740.0 million. Net income was $96.0 million."
)
DOC_B = (
    "Source Document B — Vesper FY2025 10-K. Total revenue for fiscal year 2025 "
    "was $851.0 million, compared to $710.0 million in fiscal year 2024, as "
    "restated. Fiscal 2024 revenue has been restated from the previously reported "
    "$740.0 million per Note 4."
)


def _summary_fn(s, u):
    return json.dumps([])  # no summary claims needed for this test


def _cs_fn(s, u):
    return json.dumps([])  # no internal-consistency claims needed here


def _cf_fn(system_prompt, user_prompt):
    # Per-document figure extraction from prose.
    if "fiscal year 2025" in user_prompt:  # Doc B
        return json.dumps([
            {"metric": "total_revenue", "period": "FY2025", "value": 851.0, "source_text": "x"},
            {"metric": "total_revenue", "period": "FY2024", "value": 710.0, "source_text": "as restated"},
        ])
    return json.dumps([  # Doc A
        {"metric": "total_revenue", "period": "FY2024", "value": 740.0, "source_text": "x"},
    ])


class TestProseConflictPath:
    def test_fy2024_conflict_fires_from_prose(self):
        docs = [
            SourceDoc("A_FY2024_10K", DOC_A, period="FY2024", doc_type="10-K"),  # no tables=
            SourceDoc("B_FY2025_10K", DOC_B, period="FY2025", doc_type="10-K"),
        ]
        res = audit_documents(docs, "summary", complete_fn=_summary_fn,
                              cs_complete_fn=_cs_fn, cf_complete_fn=_cf_fn)
        assert len(res.conflicts) == 1
        c = res.conflicts[0]
        assert c.status == VerificationStatus.CONFLICT
        assert c.restatement_type == RestatementType.EXPLICIT_RESTATEMENT
        vals = {o.value for o in c.claim.operands}
        assert vals == {740.0, 710.0}

    def test_no_conflict_when_figures_agree(self):
        # If both filings report FY2024 revenue identically, no conflict.
        def cf_agree(s, u):
            return json.dumps([{"metric": "total_revenue", "period": "FY2024", "value": 740.0, "source_text": "x"}])
        docs = [
            SourceDoc("A", DOC_A, period="FY2024"),
            SourceDoc("B", DOC_B, period="FY2025"),
        ]
        res = audit_documents(docs, "s", complete_fn=_summary_fn,
                              cs_complete_fn=_cs_fn, cf_complete_fn=cf_agree)
        assert res.conflicts == []
