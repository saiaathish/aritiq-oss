"""
Regression tests for the per-sector / per-statement-type aggregation added to
benchmark/reliability/report.py (the Perplexity metric shape).

These use a CACHED run JSON as a fixture — NO live API, NO SEC fetch. They assert
that the new aggregations ONLY re-shape verdicts the pipeline already produced:
every breakdown must reconcile back to the overall verdict totals, so a bug in the
aggregation can't silently invent or drop a claim.
"""
import json
import os
from collections import Counter

import pytest

# report.py lives in benchmark/reliability; import it by path.
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "benchmark", "reliability"))

import report  # noqa: E402

FIXTURE = os.path.join(_REPO, "benchmark", "reliability", "cache", "runs",
                       "run_1782874387.json")

# This large benchmark run is a local cache artifact (git-ignored, regenerated
# by the reliability harness), so skip these checks when it isn't present.
pytestmark = pytest.mark.skipif(
    not os.path.exists(FIXTURE),
    reason="reliability run cache not present (regenerate with the harness)",
)


@pytest.fixture(scope="module")
def run():
    return json.load(open(FIXTURE))


@pytest.fixture(scope="module")
def a(run):
    return report.analyze(run)


# ---- summarize_verdicts (pure) --------------------------------------------

def test_summarize_verdicts_shape_and_percentages():
    c = Counter({"VERIFIED": 8, "INSUFFICIENT_EVIDENCE": 1, "UNSUPPORTED_NUMBER": 1})
    s = report.summarize_verdicts(c)
    assert s["n"] == 10
    assert s["verified"] == 8
    assert s["insufficient_evidence"] == 1
    assert s["extraction_miss"] == 1            # UNSUPPORTED_NUMBER
    assert s["pct_verified"] == 80.0
    assert s["pct_insufficient_evidence"] == 10.0
    assert s["pct_extraction_miss"] == 10.0


def test_summarize_verdicts_empty_is_safe():
    s = report.summarize_verdicts(Counter())
    assert s["n"] == 0
    assert s["pct_verified"] == 0.0
    assert s["pct_insufficient_evidence"] == 0.0
    assert s["pct_extraction_miss"] == 0.0


def test_wrong_math_is_raw_count_never_a_percentage():
    """A conviction must stay visible as a raw count and never be folded into a
    percentage (a single false conviction is the worst-case failure)."""
    c = Counter({"VERIFIED": 1, "WRONG_MATH": 1})
    s = report.summarize_verdicts(c)
    assert s["wrong_math"] == 1
    assert "pct_wrong_math" not in s
    # WRONG_MATH is not counted as verified or as an extraction miss
    assert s["pct_verified"] == 50.0
    assert s["pct_extraction_miss"] == 0.0


# ---- breakdown_by_statement_type ------------------------------------------

def test_statement_type_breakdown_matches_known_totals(run):
    bt = report.breakdown_by_statement_type(run["filings"])
    # The fixture is the 30-filing slice with these exact rule totals.
    assert bt["eps_reconciliation"]["n"] == 35
    assert bt["balance_sheet_identity"]["n"] == 30
    assert bt["cash_flow_tie_out"]["n"] == 23
    # Only the three internal-consistency rules should appear.
    assert set(bt) == {"eps_reconciliation", "balance_sheet_identity", "cash_flow_tie_out"}
    # The single WRONG_MATH in this run is an EPS reconciliation.
    assert bt["eps_reconciliation"]["wrong_math"] == 1
    assert bt["balance_sheet_identity"]["wrong_math"] == 0


def test_statement_type_verified_counts_reconcile(run, a):
    bt = report.breakdown_by_statement_type(run["filings"])
    total_verified = sum(s["verified"] for s in bt.values())
    assert total_verified == a["verdicts"]["VERIFIED"]  # 64


# ---- breakdown_by_sector ---------------------------------------------------

def test_sector_breakdown_reconciles_to_overall(run, a):
    bs = report.breakdown_by_sector(run["filings"])
    # Sum of every sector's claim count == total in-scope claims.
    assert sum(s["n"] for s in bs.values()) == a["total_claims"]
    # Per-verdict reconciliation across sectors.
    for verdict in ("VERIFIED", "INSUFFICIENT_EVIDENCE", "UNSUPPORTED_NUMBER", "WRONG_MATH"):
        summed = sum(s["counts"].get(verdict, 0) for s in bs.values())
        assert summed == a["verdicts"].get(verdict, 0), verdict


def test_sector_breakdown_uses_filing_sector_labels(run):
    bs = report.breakdown_by_sector(run["filings"])
    # Every sector key must be a real sector label present on a filing (no invented
    # buckets). The fixture contains Software, Banking, etc.
    sectors_in_run = {f.get("sector") for f in run["filings"] if f.get("claims")}
    assert set(bs) <= sectors_in_run
    assert "Banking" in bs and "Software" in bs
    # The Banking group carries the JPM WRONG_MATH.
    assert bs["Banking"]["wrong_math"] == 1


def test_wfc_zero_claim_filing_does_not_break_aggregation(run):
    """WFC returns 0 claims in this run (the incorporate-by-reference bug codex is
    fixing). Aggregation must simply contribute nothing for it, not crash."""
    wfc = [f for f in run["filings"] if f["ticker"] == "WFC"]
    assert wfc and wfc[0]["n_claims"] == 0
    bs = report.breakdown_by_sector(run["filings"])
    # Banking group still aggregates the OTHER banks' claims fine.
    assert bs["Banking"]["n"] >= 1


# ---- analyze() integration -------------------------------------------------

def test_analyze_exposes_both_breakdowns(a):
    assert "by_sector" in a and "by_statement_type" in a
    assert a["by_statement_type"]["eps_reconciliation"]["n"] == 35


def test_markdown_render_includes_breakdown_sections(run, a):
    md = report.render_markdown(run, a)
    assert "## Breakdown by statement type" in md
    assert "## Breakdown by sector" in md
    assert "eps_reconciliation" in md
    # the WRONG_MATH column header is present
    assert "WRONG_MATH" in md


def test_text_render_includes_breakdown_sections(run, a):
    txt = report.render(run, a)
    assert "BREAKDOWN BY STATEMENT TYPE" in txt
    assert "BREAKDOWN BY SECTOR" in txt
