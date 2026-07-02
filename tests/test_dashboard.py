"""Offline tests for aritiq/dashboard.py — synthetic records, no network.

Pins the dashboard's honesty contract:
- Verification panel is core/score.py's number (reused, not re-derived), and
  the vacuous-score guard passes through as UNASSESSED, never a clean 100.
- Evidence Coverage / Disclosure Quality follow their stated deterministic
  definitions exactly.
- Consistency penalizes only detected friction (dropped spans, fallback tag),
  never the per-share split_sensitive class flag.
- Restatement Risk with no cross-document input is UNASSESSED — absence of
  comparison is never rendered as low risk — and never fabricates a 0-100.
"""
import pytest

from aritiq.dashboard import build_dashboard, DETERMINISTIC
from aritiq.edgar.company_memory import (
    CompanyMemory,
    ComparabilitySignal,
    MetricMemory,
)


def _rec(verdict="VERIFIED", *, rule="balance_sheet_identity",
         evidence_emitted=True, gate=True, adjudication=None,
         node_id=None, depends_on=None):
    return {
        "rule_name": rule,
        "operation": "internal_consistency",
        "verdict": verdict,
        "prose_verdict": verdict,
        "adjudication": adjudication,
        "operand_values": [100.0, 60.0, 40.0],
        "evidence_emitted": evidence_emitted,
        "evidence_gate_satisfied": gate,
        "node_id": node_id,
        "depends_on": depends_on or [],
        "explanation": "test",
    }


# ---------------------------------------------------------------------------
# Panel 1 — verification score
# ---------------------------------------------------------------------------

def test_verification_panel_matches_core_score_weights():
    # 2 VERIFIED (1.0) + 1 WRONG_MATH (0.0), no graph → 2/3 → 66.7 both ways
    d = build_dashboard("TEST", [_rec(), _rec(), _rec("WRONG_MATH")])
    p = d.panel("verification_score")
    assert p.state == "ok"
    assert p.value == pytest.approx(66.7, abs=0.05)
    assert p.components["unweighted_score"] == pytest.approx(66.7, abs=0.05)
    assert p.components["verified"] == 2
    assert p.components["wrong_math"] == 1


def test_verification_vacuous_guard_passes_through():
    # every claim declined → core's no_checkable_claims guard → UNASSESSED here
    d = build_dashboard("TEST", [_rec("INSUFFICIENT_EVIDENCE"),
                                 _rec("INSUFFICIENT_EVIDENCE")])
    p = d.panel("verification_score")
    assert p.state == "unassessed"
    assert p.value is None
    assert p.components["score_state"] == "no_checkable_claims"


def test_verification_no_data():
    p = build_dashboard("TEST", []).panel("verification_score")
    assert p.state == "no_data" and p.value is None


# ---------------------------------------------------------------------------
# Panel 2 — evidence coverage
# ---------------------------------------------------------------------------

def test_evidence_coverage_definition():
    recs = [_rec(evidence_emitted=True), _rec(evidence_emitted=True),
            _rec(evidence_emitted=False), _rec(evidence_emitted=True, gate=False)]
    p = build_dashboard("TEST", recs).panel("evidence_coverage")
    assert p.state == "ok"
    assert p.value == 75.0                      # 3/4 emitted
    assert p.components["evidence_gate_satisfied"] == 3
    assert p.components["gate_satisfied_pct"] == 75.0


# ---------------------------------------------------------------------------
# Panel 3 — disclosure quality
# ---------------------------------------------------------------------------

def test_disclosure_quality_explained_vs_unexplained():
    recs = [
        _rec(),  # VERIFIED — not a decline
        _rec("INSUFFICIENT_EVIDENCE", evidence_emitted=True),          # explained: disclosure present
        _rec("INSUFFICIENT_EVIDENCE", evidence_emitted=False,
             adjudication="xbrl reconciles"),                          # explained: XBRL adjudication
        _rec("INSUFFICIENT_EVIDENCE", evidence_emitted=False),         # UNEXPLAINED
    ]
    p = build_dashboard("TEST", recs).panel("disclosure_quality")
    assert p.state == "ok"
    assert p.components["declines"] == 3
    assert p.components["explained"] == 2
    assert p.components["unexplained"] == 1
    assert p.value == pytest.approx(66.7, abs=0.05)


def test_disclosure_quality_no_declines_is_labeled_trivial():
    p = build_dashboard("TEST", [_rec(), _rec()]).panel("disclosure_quality")
    assert p.value == 100.0
    assert "nothing needed explaining" in p.detail


# ---------------------------------------------------------------------------
# Panel 4 — consistency
# ---------------------------------------------------------------------------

def _metric(concept, *, n=5, dropped=0, fallback=False, split=False, err=None):
    signals = []
    if dropped:
        signals.append(ComparabilitySignal(concept, "noncomparable_spans_dropped", "d"))
    if fallback:
        signals.append(ComparabilitySignal(concept, "fallback_xbrl_tag_used", "f"))
    if split:
        signals.append(ComparabilitySignal(concept, "split_sensitive_series", "s"))
    return MetricMemory(concept=concept, tag_used="T", n_points=n,
                        dropped_noncomparable_spans=dropped,
                        split_sensitive=split, signals=signals, fetch_error=err)


def test_consistency_penalizes_friction_not_split_class():
    mem = CompanyMemory(ticker="TEST", metrics=[
        _metric("revenue"),                       # clean
        _metric("net_income", dropped=3),         # friction
        _metric("assets", fallback=True),         # friction
        _metric("eps_basic", split=True),         # split-sensitive only → CLEAN
        _metric("equity", n=1),                   # not usable (1 point)
        _metric("gross_profit", err="fetch"),     # not usable (error)
    ])
    p = build_dashboard("TEST", [_rec()], memory=mem).panel("consistency_score")
    assert p.state == "ok"
    assert p.components["usable_series"] == 4
    assert p.components["clean_series"] == 2      # revenue + eps_basic
    assert p.value == 50.0
    assert p.components["split_sensitive_series_surfaced_not_penalized"] == 1


def test_consistency_unassessed_without_memory():
    p = build_dashboard("TEST", [_rec()]).panel("consistency_score")
    assert p.state == "unassessed" and p.value is None


def test_consistency_no_usable_series():
    mem = CompanyMemory(ticker="TEST", metrics=[_metric("revenue", n=1)])
    p = build_dashboard("TEST", [_rec()], memory=mem).panel("consistency_score")
    assert p.state == "no_data" and p.value is None


# ---------------------------------------------------------------------------
# Panel 5 — restatement risk
# ---------------------------------------------------------------------------

def test_restatement_unassessed_when_no_cross_document_input():
    p = build_dashboard("TEST", [_rec()]).panel("restatement_risk")
    assert p.state == "unassessed"
    assert p.value is None
    assert "UNASSESSED" in p.detail
    # the absence of comparison must never read as low risk
    assert "low" not in p.detail.lower().replace("cannot show", "")


def test_restatement_ran_and_found_none_is_distinct_from_unassessed():
    p = build_dashboard("TEST", [_rec()], conflicts=[]).panel("restatement_risk")
    assert p.state == "ok"
    assert p.components["conflicts"] == 0
    assert "not that no restatement ever occurred" in p.detail


def test_restatement_counts_by_language_classification_never_a_score():
    conflicts = [
        {"restatement_type": "EXPLICIT_RESTATEMENT"},
        {"restatement_type": "UNEXPLAINED"},
        {"restatement_type": None},  # → UNCLASSIFIED
    ]
    p = build_dashboard("TEST", [_rec()], conflicts=conflicts).panel("restatement_risk")
    assert p.state == "ok"
    assert p.value is None                        # counts, never a fabricated 0-100
    assert p.components["conflicts"] == 3
    assert p.components["EXPLICIT_RESTATEMENT"] == 1
    assert p.components["UNEXPLAINED"] == 1
    assert p.components["UNCLASSIFIED"] == 1


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def test_dashboard_has_five_deterministic_panels():
    d = build_dashboard("TEST", [_rec()])
    assert [p.key for p in d.panels] == [
        "verification_score", "evidence_coverage", "disclosure_quality",
        "consistency_score", "restatement_risk",
    ]
    assert all(p.basis == DETERMINISTIC for p in d.panels)
    assert "No model grades anything here" in d.boundary
    out = d.to_dict()
    assert out["ticker"] == "TEST" and len(out["panels"]) == 5
