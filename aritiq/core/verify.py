"""
Aritiq deterministic verifier.

THIS FILE CONTAINS NO LLM CALLS.
Every function here is pure arithmetic + classification logic.
A reviewer can read this top-to-bottom and confirm no model is involved.
"""
from __future__ import annotations

import math
import re
from typing import Optional

from .schema import (
    Claim,
    Operation,
    Operand,
    OperandSource,
    Superlative,
    TrendDir,
    VerificationResult,
    VerificationStatus,
)
from .rules import (
    CheckResult,
    check_aggregate_filter,
    check_consecutive_count,
    check_mda_xbrl_consistency,
    check_superlative,
    check_trend_direction,
    eps_variant_consistent,
    flag_definitional,
    run_internal_consistency_rule,
)

# cross-statement operations are dispatched to rules.py and bypass the summary-audit
# stated_value/operand-count assumptions, which were written when every claim
# was a two-or-three-operand arithmetic statement.  Keeping them in this set
# lets the summary-audit code path below stay byte-for-byte unchanged.
_PHASE2_OPERATIONS = {
    Operation.INTERNAL_CONSISTENCY,
    Operation.TREND_DIRECTION,
    Operation.SUPERLATIVE,
    Operation.CONSECUTIVE_COUNT,
    Operation.AGGREGATE_FILTER,
    Operation.MDA_XBRL_CONSISTENCY,
    Operation.DEFINITIONAL_FLAG,
}

# ---------------------------------------------------------------------------
# Tolerance defaults
# ---------------------------------------------------------------------------
# These are module-level defaults; callers can override per-invocation.
# Percent-unit operations: absolute slack in percentage points.
DEFAULT_PCT_TOLERANCE_PP: float = 0.5
# Currency / raw-value operations: relative tolerance.
DEFAULT_REL_TOLERANCE: float = 0.005   # 0.5 %


# ---------------------------------------------------------------------------
# Internal arithmetic helpers
# ---------------------------------------------------------------------------

def _recompute(operation: Operation, vals: list[float]) -> Optional[float]:
    """Return the recomputed value, or None if the operation is unsupported."""
    n = len(vals)
    op = operation

    if op == Operation.PERCENT_CHANGE:
        if n != 2:
            return None
        old, new = vals
        if old == 0:
            return None
        return (new - old) / old * 100.0

    if op == Operation.ABSOLUTE_CHANGE:
        if n != 2:
            return None
        old, new = vals
        return new - old

    if op == Operation.SUM:
        if n < 2:
            return None
        return sum(vals)

    if op == Operation.DIFFERENCE:
        if n != 2:
            return None
        a, b = vals
        return a - b

    if op == Operation.RATIO:
        if n != 2:
            return None
        a, b = vals
        if b == 0:
            return None
        return a / b

    if op == Operation.MARGIN_PERCENT:
        if n != 2:
            return None
        numerator, denominator = vals
        if denominator == 0:
            return None
        return numerator / denominator * 100.0

    if op == Operation.AVERAGE:
        if n < 1:
            return None
        return sum(vals) / len(vals)

    if op == Operation.PRODUCT:
        if n < 2:
            return None
        result = 1.0
        for v in vals:
            result *= v
        return result

    if op == Operation.IDENTITY:
        if n != 1:
            return None
        return vals[0]

    return None   # UNSUPPORTED


def _within_tolerance(
    stated: float,
    recomputed: float,
    operation: Operation,
    pct_tolerance: float,
    rel_tolerance: float,
) -> bool:
    """True if stated and recomputed agree within the appropriate tolerance."""
    delta = abs(stated - recomputed)

    if operation in (Operation.PERCENT_CHANGE, Operation.MARGIN_PERCENT):
        return delta <= pct_tolerance

    # For everything else use relative tolerance, with a tiny absolute floor
    # to avoid division-by-zero on near-zero values.
    denom = max(abs(recomputed), 1e-9)
    return delta / denom <= rel_tolerance


# ---------------------------------------------------------------------------
# cross-statement dispatch — each branch delegates to a pure function in rules.py.
# This function never touches an LLM; it only routes a Claim to the right
# deterministic rule and wraps the CheckResult in a VerificationResult.
# ---------------------------------------------------------------------------

def _wrap(claim: Claim, cr: CheckResult, prefix: str = "") -> VerificationResult:
    return VerificationResult(
        claim=claim,
        status=cr.status,
        recomputed_value=cr.recomputed_value,
        delta=cr.delta,
        explanation=(prefix + cr.reason) if prefix else cr.reason,
    )


# Disclosure language that explains WHY a cash tie-out legitimately differs
# (restricted cash held separately, escrow, an explicit reconciling note, etc.).
# This is the broader "adjacent prose" signal.
_RESTRICTED_CASH_RE = re.compile(
    r"\b(restricted\s+cash|escrow|reconcil(?:e|ed|iation|ing)|"
    r"difference\s+attribut(?:able|ed)|included\s+in\s+cash\s+and\s+cash\s+equivalents)\b",
    re.IGNORECASE,
)

# The NARROWER, label-level signal (Bug C / PLTR): the cash-flow statement's own
# line label literally names restricted cash, e.g.
#   "Cash, cash equivalents, and restricted cash — end of period"
#   "cash equivalents and restricted cash"
#   "and restricted cash"
# When this phrasing appears in the CF operand's own source_text (or the claim
# text), the cash-flow figure is, BY DEFINITION, a different scope than a balance
# sheet "Cash and cash equivalents" line — no adjacent prose disclosure is needed.
# This is the source document's own wording, not an inference.
_RESTRICTED_CASH_LABEL_RE = re.compile(
    r"(and\s+restricted\s+cash|restricted\s+cash)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Wrong-line-item safety-net signals (confirmed across 3 models).
# ---------------------------------------------------------------------------
# Mechanism 1 (EPS): filers with preferred stock compute EPS against NET INCOME
# APPLICABLE/AVAILABLE TO COMMON shareholders (total net income minus preferred
# dividends), not total net income. If the grounded context names that adjusted
# line — or a preferred-dividend deduction — but the extractor used total net
# income, the failed reconciliation is a wrong-line-item artifact, not wrong math.
_NET_TO_COMMON_RE = re.compile(
    r"(net\s+income\s+(?:applicable|available|attributable)\s+(?:to\s+)?common"
    r"|net\s+income\s+applicable\s+common"
    r"|(?:income|earnings)\s+available\s+to\s+common"
    r"|preferred\s+(?:stock\s+)?dividend"
    r"|preferred\s+(?:stock\s+)?(?:distributions|redemption))",
    re.IGNORECASE,
)

# Mechanism 2 (balance sheet): the identity Assets = Liabilities + Total Equity
# holds against TOTAL equity INCLUDING noncontrolling interest AND any mezzanine
# (redeemable / partnership) interest line that sits between liabilities and
# equity. If the grounded context shows such a line but the extractor grounded
# "stockholders' equity attributable to the parent" (or even "Total equity" that
# excludes a redeemable/LP mezzanine line) only, the failed tie-out is a
# wrong-line-item artifact, not wrong math.
#
# Generalized to cover UPREIT / partnership structures (e.g. Simon Property Group):
#   - "noncontrolling interest(s)" in either word order, incl. "noncontrolling
#     redeemable interests" and "redeemable noncontrolling interest"
#   - "minority interest"
#   - "limited partners' ... interest in the Operating Partnership" (UPREIT
#     mezzanine line common to REITs structured as an umbrella partnership)
#   - a generic "redeemable ... interest" mezzanine line
_NCI_RE = re.compile(
    r"(noncontrolling\s+(?:redeemable\s+)?interest"
    r"|redeemable\s+noncontrolling\s+interest"
    r"|non-controlling\s+interest"
    r"|minority\s+interest"
    r"|limited\s+partners[’']?\s+\w*\s*interest"
    r"|interest\s+in\s+the\s+operating\s+partnership"
    r"|redeemable\s+\w*\s*interest)",
    re.IGNORECASE,
)


# Mezzanine / TEMPORARY equity: redeemable noncontrolling interests, redeemable
# operating-partnership units (UPREITs), or any line the filer parks in temporary
# equity between liabilities and permanent equity. Distinct from _NCI_RE: this is
# specifically the REDEEMABLE/temporary block that is outside BOTH the Liabilities
# and StockholdersEquity tags, so the two-term identity legitimately falls short.
_REDEEMABLE_EQUITY_RE = re.compile(
    r"(redeemable\s+noncontrolling\s+interest"
    r"|redeemable\s+operating\s+partnership"
    r"|redeemable\s+(?:limited\s+)?partnership\s+units?"
    r"|temporary\s+equity"
    r"|mezzanine\s+equity"
    r"|redeemable\s+\w*\s*units?)",
    re.IGNORECASE,
)


def _context_names_redeemable_equity(claim: Claim) -> bool:
    """True when grounded context names a redeemable/temporary (mezzanine) equity
    line (Welltower / UPREIT). Pure string matching over source text."""
    return bool(_REDEEMABLE_EQUITY_RE.search(_claim_context(claim)))


def _claim_context(claim: Claim) -> str:
    """Concatenate all grounded text on a claim (claim/source/notes + operands)."""
    parts = [claim.claim_text, claim.source_text, claim.notes]
    parts.extend(o.source_text for o in claim.operands)
    return " ".join(p for p in parts if p)


def _context_names_net_to_common(claim: Claim) -> bool:
    """True when the grounded context names a net-income-to-common / preferred
    dividend line (Mechanism 1). Pure string matching over source text."""
    return bool(_NET_TO_COMMON_RE.search(_claim_context(claim)))


def _context_names_nci(claim: Claim) -> bool:
    """True when the grounded context names a noncontrolling-interest line
    (Mechanism 2). Pure string matching over source text."""
    return bool(_NCI_RE.search(_claim_context(claim)))


def _cf_label_names_restricted_cash(claim: Claim) -> bool:
    """True when the cash-flow line LABEL itself names restricted cash (Bug C).

    Scans the claim's own text and every operand's grounded source_text for the
    label phrasing. Pure deterministic string matching over text that came from
    the source document — no model judgment, and it only ever makes the verifier
    MORE cautious (declines to convict), never more accusatory.
    """
    parts = [claim.claim_text, claim.source_text, claim.notes]
    parts.extend(o.source_text for o in claim.operands)
    context = " ".join(p for p in parts if p)
    return bool(_RESTRICTED_CASH_LABEL_RE.search(context))


def _has_disclosed_cash_reconciliation(claim: Claim) -> bool:
    """Return True when source context explains cash tie-out difference.

    Cash-flow statements often include restricted cash; balance sheets often
    show cash and cash equivalents excluding it. If the extracted context says
    that, a mismatch is not a clean arithmetic error. This remains deterministic
    string matching over grounded context; no model judgment.
    """
    parts = [claim.claim_text, claim.source_text, claim.notes]
    parts.extend(o.source_text for o in claim.operands)
    context = " ".join(p for p in parts if p)
    return bool(_RESTRICTED_CASH_RE.search(context))


def _internal_consistency_evidence(claim: Claim) -> dict:
    """Assemble the deterministic completeness/scope evidence a gated rule needs.

    Primary source is the extractor's explicit flags in `claim.params`:
      balance_sheet_identity: params["liabilities_complete"] (bool)
      eps_reconciliation:     params["eps_income_basis"], params["income_operand_basis"]
      cash_flow_tie_out:      params["restricted_cash_disclosed"] (bool)

    As a SAFETY-NET fallback, if the extractor didn't set the cash flag but the
    grounded source context plainly discloses restricted-cash / reconciling-item
    language, we set restricted_cash_disclosed=True so the tie-out declines to
    convict.  This is still deterministic string matching over grounded text — no
    model judgment — and it only ever makes the verifier MORE cautious, never
    more accusatory.  The income-basis tags are likewise read from operands'
    `category` field if not in params, so the extractor can tag them at either level.
    """
    p = claim.params or {}
    ev: dict = {}

    if claim.rule_name == "balance_sheet_identity":
        ev["liabilities_complete"] = p.get("liabilities_complete")
        # Mechanism 2 safety net: the grounded context names a noncontrolling-
        # interest line. The rule consults this ONLY when the tie-out fails
        # tolerance, to downgrade a likely wrong-line-item (parent-only equity)
        # conviction to INSUFFICIENT_EVIDENCE. Evidence-required, never blanket.
        ev["nci_in_context"] = _context_names_nci(claim)
        # Mezzanine / temporary-equity completeness (the Welltower / UPREIT fix):
        # a disclosed REDEEMABLE noncontrolling-interest / temporary-equity line
        # sits outside both the liabilities and the equity operand. Set from the
        # extractor's explicit flag (e.g. the filer's XBRL Redeemable.../Temporary...
        # tag) or from redeemable/mezzanine language in the grounded context. The
        # rule consults it ONLY on a failing tie-out, to decline rather than convict.
        ev["redeemable_equity_present"] = (
            bool(p.get("redeemable_equity_present"))
            or _context_names_redeemable_equity(claim)
        )

    elif claim.rule_name == "eps_reconciliation":
        ev["eps_income_basis"] = p.get("eps_income_basis")
        # income operand (index 1) may carry its basis as a category tag.
        income_basis = p.get("income_operand_basis")
        if income_basis is None and len(claim.operands) >= 2:
            income_basis = claim.operands[1].category
        ev["income_operand_basis"] = income_basis
        # Mechanism 1 safety net: the grounded context names a net-income-to-common
        # / preferred-dividend line. Consulted ONLY when EPS fails tolerance, to
        # downgrade a likely wrong-numerator (total net income vs applicable-to-
        # common) conviction to INSUFFICIENT_EVIDENCE. Evidence-required.
        ev["net_to_common_in_context"] = (
            _context_names_net_to_common(claim)
            or bool(p.get("preferred_dividends_present"))
        )

    elif claim.rule_name == "cash_flow_tie_out":
        flag = p.get("restricted_cash_disclosed")
        # DETERMINISTIC NORMALIZATION PASS (Bug C / PLTR). The cash-flow line's own
        # label naming restricted cash is the source document's own wording, not an
        # inference. It is therefore AUTHORITATIVE: if the CF operand source_text (or
        # the claim text) contains restricted-cash label phrasing, we force the flag
        # True regardless of what the extractor emitted — including overriding an
        # explicit `False`, which would otherwise let a label like "Cash, cash
        # equivalents, and restricted cash" be reconciled against a balance-sheet
        # "Cash and cash equivalents" line (different scopes) and produce a false
        # WRONG_MATH. This only ever makes the verdict MORE cautious.
        if _cf_label_names_restricted_cash(claim):
            flag = True
        # Broader safety-net: adjacent prose disclosure (escrow, reconciling note)
        # still upgrades an UNSET flag, exactly as before.
        elif flag is None and _has_disclosed_cash_reconciliation(claim):
            flag = True
        ev["restricted_cash_disclosed"] = flag

    return ev


def _verify_phase2(claim: Claim) -> VerificationResult:
    op = claim.operation
    vals = [o.value for o in claim.operands]

    # ---- §3.3 internal consistency ---------------------------------------
    if op == Operation.INTERNAL_CONSISTENCY:
        # §4 confound guard: for eps_reconciliation, refuse to compare a stated
        # EPS variant against a mismatched shares variant.  This is the guard
        # that makes the basic/diluted limitation *handled*, not ignored.
        if claim.rule_name == "eps_reconciliation" and len(claim.operands) == 3:
            shares_operand = claim.operands[2]
            consistency = eps_variant_consistent(claim.eps_variant, shares_operand)
            if consistency is None:
                return VerificationResult(
                    claim=claim,
                    status=VerificationStatus.AMBIGUOUS,
                    explanation=(
                        "EPS variant unrecorded: neither the claim nor the shares operand "
                        "carries a basic/diluted tag, so a WRONG_MATH verdict cannot be "
                        "distinguished from a variant-mismatch. Arithmetic not run (spec §4). "
                        "Fix: extractor must tag eps_variant on the claim and category on "
                        "the shares operand."
                    ),
                )
            if not consistency:
                return VerificationResult(
                    claim=claim,
                    status=VerificationStatus.AMBIGUOUS,
                    explanation=(
                        "EPS variant mismatch: stated EPS is "
                        f"{claim.eps_variant.value if claim.eps_variant else '?'} but the "
                        "grounded shares figure is the other variant. Comparison would "
                        "be apples-to-oranges; not run (spec §4)."
                    ),
                )
        # Evidence-completeness gating (the operand-selection-bug defense): the
        # extractor supplies deterministic completeness/scope flags in params,
        # and the gated rules return INSUFFICIENT_EVIDENCE rather than a false
        # WRONG_MATH when those flags are absent or contradictory. The verifier
        # only READS the flags — it never decides accounting scope itself.
        evidence = _internal_consistency_evidence(claim)
        cr = run_internal_consistency_rule(claim.rule_name, vals, evidence)
        rn = claim.rule_name or "internal_consistency"
        return _wrap(claim, cr, prefix=f"[{rn}] ")

    # ---- §3.2 temporal ----------------------------------------------------
    if op in (Operation.TREND_DIRECTION, Operation.SUPERLATIVE, Operation.CONSECUTIVE_COUNT):
        # The series is carried as (period, value) pairs in params["series"];
        # operands hold the same values for grounding/audit.
        series = claim.params.get("series")
        if not series:
            # Fall back to bare operand values with positional period labels.
            series = [(str(i), v) for i, v in enumerate(vals)]
        series = [(str(p), float(v)) for p, v in series]

        if op == Operation.TREND_DIRECTION:
            if claim.trend_dir is None:
                return VerificationResult(claim=claim, status=VerificationStatus.AMBIGUOUS,
                                          explanation="trend_direction claim has no asserted direction.")
            cr = check_trend_direction(series, claim.trend_dir)
            return _wrap(claim, cr, prefix="[trend_direction] ")

        if op == Operation.SUPERLATIVE:
            if claim.superlative is None:
                return VerificationResult(claim=claim, status=VerificationStatus.AMBIGUOUS,
                                          explanation="superlative claim has no asserted extreme (max/min).")
            cr = check_superlative(series, claim.superlative, claim.params.get("target_period"))
            return _wrap(claim, cr, prefix="[superlative] ")

        # consecutive_count
        if claim.trend_dir is None or claim.stated_value is None:
            return VerificationResult(claim=claim, status=VerificationStatus.AMBIGUOUS,
                                      explanation="consecutive_count needs a direction and a stated count.")
        cr = check_consecutive_count(series, claim.trend_dir, claim.stated_value)
        return _wrap(claim, cr, prefix="[consecutive_count] ")

    # ---- MD&A prose direction vs XBRL ---------------------------------
    if op == Operation.MDA_XBRL_CONSISTENCY:
        pct_change = claim.params.get("actual_percent_change", claim.stated_value)
        flat_band = float(claim.params.get("flat_band_pct", 2.0))
        cr = check_mda_xbrl_consistency(claim.trend_dir, pct_change,
                                        flat_band_pct=flat_band)
        return _wrap(claim, cr, prefix="[mda_xbrl_consistency] ")

    # ---- Axis C aggregate_filter -----------------------------------------
    if op == Operation.AGGREGATE_FILTER:
        if claim.stated_value is None:
            return VerificationResult(claim=claim, status=VerificationStatus.AMBIGUOUS,
                                      explanation="aggregate_filter needs a stated_value to check against.")
        mode = claim.params.get("mode", "sum")
        cr = check_aggregate_filter(vals, claim.stated_value, mode=mode)
        # If any operand was category-inferred, surface that the verdict is
        # conditional on a categorization judgment (Axis C, §4.2).
        cat_inferred = any(o.source == OperandSource.CATEGORY_INFERRED for o in claim.operands)
        note = (" (note: one or more operands are category_inferred; verdict is "
                "conditional on the categorization scheme)") if cat_inferred else ""
        return _wrap(claim, cr, prefix=f"[aggregate_filter:{mode}] ") if not note else VerificationResult(
            claim=claim, status=cr.status, recomputed_value=cr.recomputed_value,
            delta=cr.delta, explanation=f"[aggregate_filter:{mode}] {cr.reason}{note}")

    # ---- §3.4 definitional flag ------------------------------------------
    if op == Operation.DEFINITIONAL_FLAG:
        nearby = claim.params.get("nearby_number", claim.stated_value)
        cr = flag_definitional(claim.claim_text, nearby)
        return _wrap(claim, cr)

    # Should be unreachable (op was in _PHASE2_OPERATIONS).
    return VerificationResult(claim=claim, status=VerificationStatus.AMBIGUOUS,
                              explanation=f"unhandled cross-statement operation {op}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_claim(
    claim: Claim,
    pct_tolerance: float = DEFAULT_PCT_TOLERANCE_PP,
    rel_tolerance: float = DEFAULT_REL_TOLERANCE,
) -> VerificationResult:
    """
    Verify a single Claim deterministically.

    Returns a VerificationResult with status, recomputed_value, delta,
    and a human-readable explanation.  Never raises — all edge cases map
    to a typed status.
    """
    op = claim.operation

    # ---- UNCHECKED: qualitative claim, no formula -------------------------
    if op == Operation.UNSUPPORTED:
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.UNCHECKED,
            explanation="Operation is qualitative; no arithmetic check possible.",
        )

    # ---- UNSUPPORTED_NUMBER: missing operand(s) ---------------------------
    # This guard is universal (both the per-claim and cross-statement passes): a missing operand can never
    # be computed with, whatever the operation.
    missing = [o for o in claim.operands if o.source == OperandSource.MISSING]
    if missing:
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.UNSUPPORTED_NUMBER,
            explanation=f"{len(missing)} operand(s) could not be located in the source document.",
        )

    # ---- cross-statement operations: dispatch to rules.py BEFORE the summary-audit
    # stated_value assumption (internal_consistency legitimately has none). ---
    if op in _PHASE2_OPERATIONS:
        return _verify_phase2(claim)

    # ---- No stated value to check against ---------------------------------
    if claim.stated_value is None:
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.AMBIGUOUS,
            explanation="No stated_value provided; nothing to verify against.",
        )

    vals = [o.value for o in claim.operands]
    check_values = vals + [claim.stated_value]
    if any(not math.isfinite(float(v)) for v in check_values):
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.AMBIGUOUS,
            explanation="Non-finite numeric value (NaN/Infinity) cannot be verified.",
        )

    # ---- Validate operand count before arithmetic -------------------------
    expected_counts = {
        Operation.PERCENT_CHANGE:  2,
        Operation.ABSOLUTE_CHANGE: 2,
        Operation.DIFFERENCE:      2,
        Operation.RATIO:           2,
        Operation.MARGIN_PERCENT:  2,
        Operation.IDENTITY:        1,
    }
    if op in expected_counts and len(vals) != expected_counts[op]:
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.AMBIGUOUS,
            explanation=(
                f"Operation {op.value} expects {expected_counts[op]} operand(s), "
                f"got {len(vals)}."
            ),
        )
    if op in (Operation.SUM, Operation.AVERAGE, Operation.PRODUCT) and len(vals) < 2:
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.AMBIGUOUS,
            explanation=f"Operation {op.value} requires ≥2 operands, got {len(vals)}.",
        )

    # ---- Recompute --------------------------------------------------------
    try:
        recomputed = _recompute(op, vals)
    except Exception as exc:
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.AMBIGUOUS,
            explanation=f"Arithmetic error during recomputation: {exc}",
        )

    # ---- Divide-by-zero or other non-finite result ------------------------
    if recomputed is None or not math.isfinite(recomputed):
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.AMBIGUOUS,
            explanation="Recomputation produced a non-finite value (e.g. divide-by-zero).",
        )

    delta = claim.stated_value - recomputed

    # ---- Compare ----------------------------------------------------------
    if _within_tolerance(claim.stated_value, recomputed, op, pct_tolerance, rel_tolerance):
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.VERIFIED,
            recomputed_value=recomputed,
            delta=delta,
            explanation=(
                f"Stated {claim.stated_value}, recomputed {recomputed:.4f} "
                f"(Δ={delta:+.4f}) — within tolerance."
            ),
        )
    else:
        return VerificationResult(
            claim=claim,
            status=VerificationStatus.WRONG_MATH,
            recomputed_value=recomputed,
            delta=delta,
            explanation=(
                f"Stated {claim.stated_value}, recomputed {recomputed:.4f} "
                f"(Δ={delta:+.4f}) — exceeds tolerance."
            ),
        )
