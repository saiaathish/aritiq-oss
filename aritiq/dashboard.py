"""
Institutional risk dashboard — Phase 3 item 2.

PRESENTATION LOGIC OVER NUMBERS THAT ALREADY EXIST. This module computes
nothing that is already computed elsewhere:

- Verification Score  → `core/score.py`'s `compute_score` (weighted +
  unweighted AritiqScore), called on the recorded verdicts — the weights and
  exclusion rules live in exactly one place and it is not here.
- Restatement Risk    → counts of `core/restatement.py`'s RestatementType
  labels on CONFLICT results. Per Move 2's meaning, these are
  disclosure-LANGUAGE classifications, never accounting determinations.
- Consistency Score   → `company_memory.py`'s deterministic comparability
  signals over cached multi-year XBRL series.

The two genuinely NEW metrics are BOTH deterministic (decided explicitly, per
the roadmap; nothing here is model-assisted and nothing imports a model SDK):

- Evidence Coverage   := share of claims whose rule-REQUIRED evidence flags
  were all present in the extracted claim (the harness's `evidence_emitted`).
  A claim whose rule requires no flags counts as covered. This is a property
  of extraction grounding, stated as such.
- Disclosure Quality  := of the claims Aritiq DECLINED to certify
  (INSUFFICIENT_EVIDENCE), the share whose decline is *explained* — either the
  required disclosure context was present in the grounded claim
  (evidence-gated decline, e.g. the filer's own restricted-cash / mezzanine /
  preferred-dividend language) or SEC XBRL independently adjudicated the
  figure. An UNEXPLAINED decline means the needed disclosure never reached the
  claim. This is a JOINT property of the filer's disclosure and extraction
  grounding — not a pure filer attribute; the panel says so.

THE NO-FABRICATION RULE: a panel with nothing to measure reports
`state="unassessed"` with `value=None` — it never renders a clean-looking
number. A single-filing audit has no cross-document comparison, so Restatement
Risk on it is UNASSESSED, not "low". (The same discipline as the vacuous-score
guard.)

FIREWALL: imports `aritiq.core` types and functions (schema, score,
restatement) and `aritiq.edgar.company_memory` — no model SDK. Lives OUTSIDE
`aritiq/core/` because it is presentation, not verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence

from .core.schema import (
    Claim,
    Operand,
    OperandSource,
    Operation,
    VerificationResult,
    VerificationStatus,
)
from .core.score import compute_score
from .core.restatement import RestatementType
from .edgar.company_memory import CompanyMemory

DETERMINISTIC = "deterministic"  # every v1 panel; a model-assisted panel would
                                 # be labeled and would live with the extract side


@dataclass
class DashboardPanel:
    key: str
    title: str
    basis: str                       # "deterministic" (all of v1)
    state: str                       # "ok" | "unassessed" | "no_data"
    value: Optional[float]           # 0-100 when state == "ok" and numeric; else None
    detail: str                      # what the number MEANS, incl. its honest boundary
    components: Dict[str, object] = field(default_factory=dict)


@dataclass
class RiskDashboard:
    ticker: str
    panels: List[DashboardPanel] = field(default_factory=list)
    boundary: str = (
        "All panels are deterministic aggregations of verdicts, evidence flags, "
        "XBRL comparability gates, and disclosure-language classifications that "
        "already exist upstream. No model grades anything here. A panel with "
        "nothing to measure says UNASSESSED — it never fabricates a clean number."
    )

    def to_dict(self) -> dict:
        return asdict(self)

    def panel(self, key: str) -> DashboardPanel:
        for p in self.panels:
            if p.key == key:
                return p
        raise KeyError(key)


# ---------------------------------------------------------------------------
# Panel 1 — Verification Score (reuses core/score.py, nothing re-derived)
# ---------------------------------------------------------------------------

def _results_from_records(records: Sequence[dict]):
    """Rebuild minimal (VerificationResult, Claim) pairs from harness claim
    records so the REAL `compute_score` runs — weights/exclusions stay in
    core/score.py. Only the fields scoring reads are populated."""
    results: List[VerificationResult] = []
    claims: List[Claim] = []
    for r in records:
        claim = Claim(
            claim_text=f"[{r.get('rule_name') or r.get('operation', 'claim')}]",
            operation=Operation(r.get("operation", "internal_consistency")),
            stated_value=None,
            operands=[
                Operand(value=v, source=OperandSource.GROUNDED)
                for v in (r.get("operand_values") or [])
                if v is not None
            ],
            unit=None,
            rule_name=r.get("rule_name"),
            node_id=r.get("node_id"),
            depends_on=list(r.get("depends_on") or []),
        )
        results.append(VerificationResult(
            claim=claim,
            status=VerificationStatus(r["verdict"]),
            recomputed_value=None,
            explanation=r.get("explanation", ""),
        ))
        claims.append(claim)
    return results, claims


def _panel_verification(records: Sequence[dict]) -> DashboardPanel:
    if not records:
        return DashboardPanel(
            key="verification_score", title="Verification Score",
            basis=DETERMINISTIC, state="no_data", value=None,
            detail="No verified claims exist for this input.",
        )
    results, claims = _results_from_records(records)
    s = compute_score(results, claims)
    if not s.score_available:
        return DashboardPanel(
            key="verification_score", title="Verification Score",
            basis=DETERMINISTIC, state="unassessed", value=None,
            detail=("No checkable claims — rendering a score here would be the "
                    "vacuous-100 bug. State shown instead of a number."),
            components={"score_state": s.score_state,
                        "insufficient_evidence": s.insufficient_evidence},
        )
    return DashboardPanel(
        key="verification_score", title="Verification Score",
        basis=DETERMINISTIC, state="ok", value=s.score,
        detail=(f"Weighted {s.score} · Unweighted {s.unweighted_score} — "
                "core/score.py's AritiqScore over recorded verdicts; shown as a "
                "pair so the dependency weighting stays auditable."),
        components={
            "weighted_score": s.score,
            "unweighted_score": s.unweighted_score,
            "verified": s.verified,
            "wrong_math": s.wrong_math,
            "unsupported": s.unsupported,
            "ambiguous": s.ambiguous,
            "insufficient_evidence": s.insufficient_evidence,
            "total_checkable": s.total_checkable,
        },
    )


# ---------------------------------------------------------------------------
# Panel 2 — Evidence Coverage (new; deterministic by explicit decision)
# ---------------------------------------------------------------------------

def _panel_evidence_coverage(records: Sequence[dict]) -> DashboardPanel:
    if not records:
        return DashboardPanel(
            key="evidence_coverage", title="Evidence Coverage",
            basis=DETERMINISTIC, state="no_data", value=None,
            detail="No claims to measure evidence coverage over.",
        )
    covered = sum(1 for r in records if r.get("evidence_emitted"))
    gate_ok = sum(1 for r in records if r.get("evidence_gate_satisfied"))
    value = round(covered / len(records) * 100.0, 1)
    return DashboardPanel(
        key="evidence_coverage", title="Evidence Coverage",
        basis=DETERMINISTIC, state="ok", value=value,
        detail=("Share of claims whose rule-required evidence flags were all "
                "present in the extracted claim. A property of extraction "
                "grounding — NOT a statement that the underlying numbers are "
                "right (that is the Verification panel's job)."),
        components={
            "claims": len(records),
            "evidence_emitted": covered,
            "evidence_gate_satisfied": gate_ok,
            "gate_satisfied_pct": round(gate_ok / len(records) * 100.0, 1),
        },
    )


# ---------------------------------------------------------------------------
# Panel 3 — Disclosure Quality (new; deterministic by explicit decision)
# ---------------------------------------------------------------------------

def _panel_disclosure_quality(records: Sequence[dict]) -> DashboardPanel:
    declines = [r for r in records
                if r.get("verdict") == VerificationStatus.INSUFFICIENT_EVIDENCE.value]
    if not records:
        return DashboardPanel(
            key="disclosure_quality", title="Disclosure Quality",
            basis=DETERMINISTIC, state="no_data", value=None,
            detail="No claims to assess.",
        )
    if not declines:
        return DashboardPanel(
            key="disclosure_quality", title="Disclosure Quality",
            basis=DETERMINISTIC, state="ok", value=100.0,
            detail=("No declines to explain — every checkable claim ran without "
                    "evidence gating. (100 here means 'nothing needed explaining', "
                    "not 'perfect disclosure'.)"),
            components={"declines": 0, "explained": 0, "unexplained": 0},
        )
    explained = sum(
        1 for r in declines
        if r.get("evidence_emitted") or r.get("adjudication")
    )
    unexplained = len(declines) - explained
    value = round(explained / len(declines) * 100.0, 1)
    return DashboardPanel(
        key="disclosure_quality", title="Disclosure Quality",
        basis=DETERMINISTIC, state="ok", value=value,
        detail=("Of the claims Aritiq DECLINED to certify, the share whose "
                "decline is explained — required disclosure context present in "
                "the grounded claim (e.g. the filer's own restricted-cash / "
                "mezzanine / preferred-dividend language) or independently "
                "adjudicated by SEC XBRL. A JOINT property of filer disclosure "
                "and extraction grounding, not a pure filer attribute."),
        components={
            "declines": len(declines),
            "explained": explained,
            "unexplained": unexplained,
            "explained_via_adjudication": sum(1 for r in declines if r.get("adjudication")),
        },
    )


# ---------------------------------------------------------------------------
# Panel 4 — Consistency Score (derived from company_memory's existing signals)
# ---------------------------------------------------------------------------

def _panel_consistency(memory: Optional[CompanyMemory]) -> DashboardPanel:
    if memory is None:
        return DashboardPanel(
            key="consistency_score", title="Cross-Year Consistency",
            basis=DETERMINISTIC, state="unassessed", value=None,
            detail="No company memory supplied (needs cached multi-year XBRL).",
        )
    usable = [m for m in memory.metrics if m.n_points >= 2 and not m.fetch_error]
    if not usable:
        return DashboardPanel(
            key="consistency_score", title="Cross-Year Consistency",
            basis=DETERMINISTIC, state="no_data", value=None,
            detail="No usable multi-year series in cached XBRL for this company.",
        )
    # "Clean" = no comparability friction the gates actually detected:
    # no non-comparable spans dropped, no fallback-tag definition risk.
    # split_sensitive is deliberately NOT a penalty: it flags every per-share
    # concept as a CLASS (handle-with-care across splits), so penalizing it
    # would deduct the same points from every filer that reports EPS.
    def _clean(m) -> bool:
        return (m.dropped_noncomparable_spans == 0
                and not any(s.signal == "fallback_xbrl_tag_used" for s in m.signals))

    clean = [m for m in usable if _clean(m)]
    value = round(len(clean) / len(usable) * 100.0, 1)
    return DashboardPanel(
        key="consistency_score", title="Cross-Year Consistency",
        basis=DETERMINISTIC, state="ok", value=value,
        detail=("Share of this company's usable multi-year XBRL series with no "
                "detected comparability friction (no non-comparable spans "
                "dropped, no fallback-tag definition risk). Signals mean a gate "
                "FIRED — they do not interpret footnotes or prove an accounting "
                "change (company_memory.py's stated boundary)."),
        components={
            "usable_series": len(usable),
            "clean_series": len(clean),
            "series_with_dropped_spans": sum(
                1 for m in usable if m.dropped_noncomparable_spans > 0),
            "series_with_fallback_tag": sum(
                1 for m in usable
                if any(s.signal == "fallback_xbrl_tag_used" for s in m.signals)),
            "split_sensitive_series_surfaced_not_penalized": sum(
                1 for m in usable if m.split_sensitive),
        },
    )


# ---------------------------------------------------------------------------
# Panel 5 — Restatement Risk (reuses core/restatement.py's classifications)
# ---------------------------------------------------------------------------

def _panel_restatement(conflicts: Optional[Sequence[dict]]) -> DashboardPanel:
    """`conflicts`: dicts with a `restatement_type` key (the serialized CONFLICT
    results from a MULTI-document audit). None => no cross-document comparison
    was run, which is UNASSESSED — never 'low risk'."""
    if conflicts is None:
        return DashboardPanel(
            key="restatement_risk", title="Restatement Risk",
            basis=DETERMINISTIC, state="unassessed", value=None,
            detail=("UNASSESSED: no cross-document comparison in this input. A "
                    "single filing cannot show a restatement conflict, so no "
                    "risk number is fabricated from its absence."),
        )
    counts: Dict[str, int] = {t.value: 0 for t in RestatementType}
    for c in conflicts:
        t = c.get("restatement_type") or RestatementType.UNCLASSIFIED.value
        counts[t] = counts.get(t, 0) + 1
    n = len(conflicts)
    if n == 0:
        detail = ("Cross-document comparison ran and found no figure conflicts. "
                  "This means no conflicts were DETECTED in the compared "
                  "documents — not that no restatement ever occurred.")
    else:
        detail = ("Disclosure-language classification of detected figure "
                  "conflicts (core/restatement.py). Labels describe the TEXT "
                  "near the conflict — never a determination of what kind of "
                  "restatement occurred. UNEXPLAINED conflicts (no disclosure "
                  "language found) warrant the most attention.")
    return DashboardPanel(
        key="restatement_risk", title="Restatement Risk",
        basis=DETERMINISTIC, state="ok", value=None,  # counts, not a 0-100 score
        detail=detail,
        components={"conflicts": n, **counts},
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_dashboard(
    ticker: str,
    claim_records: Sequence[dict],
    *,
    memory: Optional[CompanyMemory] = None,
    conflicts: Optional[Sequence[dict]] = None,
) -> RiskDashboard:
    """Assemble the five-panel dashboard.

    `claim_records`: harness-format claim dicts (the reliability benchmark's
    committed per-claim records — verdict, evidence flags, adjudication).
    `memory`: CompanyMemory from cached companyfacts (None => panel unassessed).
    `conflicts`: serialized CONFLICT results from a multi-document audit
    (None => restatement panel unassessed; [] => comparison ran, none found).
    """
    return RiskDashboard(
        ticker=ticker.upper(),
        panels=[
            _panel_verification(claim_records),
            _panel_evidence_coverage(claim_records),
            _panel_disclosure_quality(claim_records),
            _panel_consistency(memory),
            _panel_restatement(conflicts),
        ],
    )
