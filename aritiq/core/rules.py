"""
Phase 2 deterministic rule functions.

THIS FILE CONTAINS NO LLM CALLS.  Every function here is a pure function:
grounded numbers in, a typed verdict out.  A reviewer can read it top to bottom
and confirm no model is involved.  This is the heart of the Phase 2 thesis — the
moat got *wider* (more kinds of claim it can check by code) without getting
*smarter* (no model-judgment step ever enters).

Each operation below passes the §3.1 test: "given grounded inputs, there is one
objectively correct verdict, computable by a pure function, with no model-
judgment step."  Where a candidate FAILED that test (logical/definitional
"flat", §3.4), it is deliberately routed to a human, not resolved — see
`flag_definitional`.

Status convention reused from Phase 1:
  VERIFIED / WRONG_MATH        — comparison within / outside tolerance
  AMBIGUOUS                    — structural problem (divide-by-zero, bad count)
  UNSUPPORTED_NUMBER           — a required operand is missing
  NEEDS_REVIEW                 — claim's own words don't define a numeric test
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .schema import (
    EPSVariant,
    Operand,
    OperandSource,
    Superlative,
    TrendDir,
    VerificationStatus,
)


# ---------------------------------------------------------------------------
# A tiny result carrier so rules can return a status + explanation uniformly.
# (verify.py maps this onto the full VerificationResult.)
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    status: VerificationStatus
    recomputed_value: Optional[float] = None
    delta: Optional[float] = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Shared classifier — the same "within tolerance -> VERIFIED else WRONG_MATH"
# decision Phase 1 makes, reused so cross-statement checks don't reinvent it.
# Supports either an absolute tolerance or a relative one (exactly one is set).
# ---------------------------------------------------------------------------

def _classify(
    stated: float,
    computed: float,
    *,
    abs_tolerance: Optional[float] = None,
    rel_tolerance: Optional[float] = None,
    rel_floor: float = 1e-9,
) -> CheckResult:
    if not math.isfinite(stated) or not math.isfinite(computed):
        return CheckResult(
            status=VerificationStatus.AMBIGUOUS,
            reason="non-finite value in comparison",
        )
    delta = stated - computed
    if abs_tolerance is not None:
        ok = abs(delta) <= abs_tolerance
    elif rel_tolerance is not None:
        denom = max(abs(computed), rel_floor)
        ok = abs(delta) / denom <= rel_tolerance
    else:  # pragma: no cover - caller error
        raise ValueError("exactly one of abs_tolerance / rel_tolerance required")

    status = VerificationStatus.VERIFIED if ok else VerificationStatus.WRONG_MATH
    return CheckResult(status=status, recomputed_value=computed, delta=delta,
                       reason=("within tolerance" if ok else "exceeds tolerance"))


# ===========================================================================
# §3.3  Cross-statement internal-consistency rules
# ===========================================================================
# Tighter tolerances than Phase 1 (spec §2.3): a document's own table should
# add up far more precisely than a human writer's prose rounds.

DEFAULT_BS_REL_TOLERANCE: float = 0.001     # balance sheet identity: 0.1%
DEFAULT_EPS_ABS_TOLERANCE: float = 0.005    # eps reconciliation: 0.5 cents
DEFAULT_CASH_REL_TOLERANCE: float = 0.0001  # cash tie-out: 0.01% (defined-equal)


def check_balance_sheet_identity(
    operands: Sequence[float],
    rel_tolerance: float = DEFAULT_BS_REL_TOLERANCE,
    *,
    liabilities_complete: Optional[bool] = None,
    nci_in_context: bool = False,
) -> CheckResult:
    """Assets == Liabilities + Equity.  Operand order: [assets, liabilities, equity].

    EVIDENCE GATE (the AMD #1 fix).  A balance sheet only balances when the
    `liabilities` operand is TOTAL liabilities — current AND long-term.  A very
    common extraction mistake is to ground only "Total current liabilities" (a
    visually prominent subtotal) and miss the long-term rows below it; the sum
    then falls short of assets and the verifier would, wrongly, cry WRONG_MATH on
    a perfectly correct balance sheet.

    So we require an explicit completeness signal:
      * liabilities_complete is True  -> the extractor confirms this is TOTAL
        liabilities; run the check.
      * liabilities_complete is False -> the extractor knows it is a partial
        (e.g. current-only); we DECLINE to convict -> INSUFFICIENT_EVIDENCE.
      * liabilities_complete is None  -> completeness was never established; we
        also decline -> INSUFFICIENT_EVIDENCE.  Absence of evidence is not a
        license to emit a confident WRONG_MATH.
    This is a deterministic flag check, not an accounting judgment — the verifier
    never decides what "total liabilities" is, it only refuses to run the formula
    until the extractor has asserted the operand is the complete one.
    """
    if len(operands) != 3:
        return CheckResult(
            status=VerificationStatus.AMBIGUOUS,
            reason=f"balance_sheet_identity expects 3 operands, got {len(operands)}",
        )

    assets, liabilities, equity = operands
    # ZERO-LIABILITIES GATE (the live-benchmark AMD #B2 fix). A liabilities operand
    # of exactly 0 while assets AND equity are both non-zero is never a genuine
    # balance-sheet value — a real company with assets has liabilities. It is always
    # a grounding failure (the extractor dropped/zeroed the Total liabilities line),
    # so a `liabilities_complete: true` flag on it is untrustworthy regardless of
    # what the extractor emitted. We override to INSUFFICIENT_EVIDENCE rather than
    # convict (precedent: the restricted-cash label override). This is a NEW gate,
    # it never lets a real WRONG_MATH through — it only declines an impossible operand.
    if liabilities == 0 and assets != 0 and equity != 0:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason=("balance_sheet_identity not run: liabilities operand is exactly 0 "
                    "while assets and equity are non-zero — impossible for a real "
                    "balance sheet, so this is a grounding failure (the Total "
                    "liabilities line was not captured), not a genuine disagreement. "
                    "The liabilities_complete flag cannot be trusted here. Fix: "
                    "extractor must ground the explicit Total liabilities figure."),
        )

    if liabilities_complete is not True:
        why = ("liabilities operand is flagged incomplete (e.g. current-only; "
               "long-term rows not captured)" if liabilities_complete is False
               else "no evidence the liabilities operand is TOTAL liabilities "
                    "(current + long-term)")
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason=(f"balance_sheet_identity not run: {why}. A short liabilities "
                    f"figure would cause a false WRONG_MATH. Fix: extractor must "
                    f"ground TOTAL liabilities and set liabilities_complete=true."),
        )
    expected = liabilities + equity
    result = _classify(stated=assets, computed=expected, rel_tolerance=rel_tolerance)

    # WRONG-LINE-ITEM SAFETY NET (Mechanism 2). A common extraction error is to
    # ground "stockholders' equity attributable to the parent" instead of TOTAL
    # equity including noncontrolling interest — the identity Assets = Liabilities
    # + Total Equity (incl. NCI) is what actually holds on the face of the balance
    # sheet. When the tie-out FAILS and the grounded context names a separate NCI
    # line that plausibly accounts for the gap, the failure is far more likely a
    # wrong-line-item artifact than a genuine imbalance, so we decline to convict.
    # Evidence-required (NCI phrase must be present) and scoped to the failing case
    # only — it never changes a VERIFIED result and never fires without the phrase.
    if result.status == VerificationStatus.WRONG_MATH and nci_in_context:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            recomputed_value=expected,
            delta=result.delta,
            reason=("balance_sheet_identity tie-out failed, but the grounded context "
                    "names a noncontrolling-interest line not reflected in the equity "
                    "operand. The identity holds against TOTAL equity INCLUDING NCI; "
                    "the extractor likely grounded parent-only stockholders' equity. "
                    "Declining to convict — fix: ground the filer's 'Total equity' "
                    "(incl. noncontrolling interests) line."),
        )
    return result


def check_balance_sheet_identity_itemized(
    assets: float,
    liability_components: Sequence[float],
    equity: float,
    rel_tolerance: float = DEFAULT_BS_REL_TOLERANCE,
    *,
    components_complete: Optional[bool] = None,
) -> CheckResult:
    """Assets == sum(liability_components) + Equity, from ITEMIZED liability rows.

    The stronger, more auditable form of the tie-out: instead of trusting a
    single "total liabilities" figure, the extractor supplies the individual
    liability rows it found (current + long-term) and asserts whether that list
    is the COMPLETE set (`components_complete`).  We sum them ourselves.

    Same evidence gate: without an explicit completeness assertion we return
    INSUFFICIENT_EVIDENCE rather than risk convicting on a partial row set.
    """
    if not liability_components:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason="no liability components supplied for itemized balance-sheet tie-out",
        )
    if components_complete is not True:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason=("itemized balance_sheet_identity not run: the liability row set "
                    "is not asserted complete (components_complete is not true). "
                    "A missing long-term row would force a false WRONG_MATH."),
        )
    expected = sum(liability_components) + equity
    return _classify(stated=assets, computed=expected, rel_tolerance=rel_tolerance)


def check_eps_reconciliation(
    operands: Sequence[float],
    abs_tolerance: float = DEFAULT_EPS_ABS_TOLERANCE,
    *,
    eps_income_basis: Optional[str] = None,
    income_operand_basis: Optional[str] = None,
    net_to_common_in_context: bool = False,
) -> CheckResult:
    """stated_eps == net_income / shares.  Order: [stated_eps, net_income, shares].

    INCOME-BASIS GATE (the AMD #2 fix).  Companies report EPS on more than one
    income base: total net income, and income from CONTINUING OPERATIONS only
    (excluding discontinued operations).  An EPS quoted "from continuing
    operations" reconciles against continuing-operations income — NOT total net
    income.  Pairing a continuing-ops EPS with total net income (a very easy
    extraction slip when both numbers sit in the same statement) makes the
    division disagree and would trigger a false WRONG_MATH.

    The basis must be POSITIVELY CONFIRMED to match before we run — absence of
    tags is NOT permission to run.  The extractor prompt requires both basis tags
    for every eps_reconciliation claim, so a missing tag means the extractor did
    not comply, and the honest response is to refuse to convict rather than guess:
      * both recorded and equal      -> run the check.
      * both recorded and different  -> INSUFFICIENT_EVIDENCE (apples-to-oranges).
      * either side unrecorded        -> INSUFFICIENT_EVIDENCE (cannot confirm a
        continuing-ops EPS isn't being compared against total net income — the
        exact AMD #2 false-WRONG_MATH this gate exists to prevent).
    Deterministic string comparison of basis tags; no judgment about which basis
    is "right".
    """
    if len(operands) != 3:
        return CheckResult(
            status=VerificationStatus.AMBIGUOUS,
            reason=f"eps_reconciliation expects 3 operands, got {len(operands)}",
        )

    basis_check = _income_basis_consistent(eps_income_basis, income_operand_basis)
    if basis_check is False:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason=(f"EPS income-basis mismatch: stated EPS basis "
                    f"{eps_income_basis!r} vs net-income basis {income_operand_basis!r} "
                    f"(e.g. continuing-operations EPS compared against total net income). "
                    f"Not run — would be a false WRONG_MATH."),
        )
    if basis_check is None:
        # Either or both bases unrecorded. We do NOT run blind: a continuing-ops
        # EPS silently paired with total net income would otherwise produce a
        # confident false WRONG_MATH (AMD #2). The extractor must tag the income
        # basis on BOTH the stated EPS and the net-income operand.
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason=("EPS income basis not established on both sides (got eps_basis="
                    f"{eps_income_basis!r}, income_basis={income_operand_basis!r}). "
                    "Cannot confirm the stated EPS and the net-income operand share "
                    "an income base (continuing-ops vs total net income). Not run — "
                    "fix: extractor must tag eps_income_basis and income_operand_basis."),
        )

    stated_eps, net_income, shares = operands
    if shares == 0:
        return CheckResult(status=VerificationStatus.AMBIGUOUS,
                           reason="shares_outstanding is zero (divide-by-zero)")
    computed = net_income / shares

    # SCALE-MISMATCH GATE (the live-benchmark EPS #B1 fix). When net_income and
    # shares are grounded at DIFFERENT unit scales (e.g. net income in $M but
    # shares in raw units, or vice versa), the quotient is off from the stated EPS
    # by orders of magnitude — AAPL 112010/14,948,500 = 0.0075 vs 7.49 (~1000x),
    # CRM 7,457,000/950 = 7849 vs 7.85 (~1000x). A GENUINE filer arithmetic error
    # is never off by an order of magnitude; only a unit-scale extraction artifact
    # produces that signature. So when stated and computed differ by >= the
    # order-of-magnitude threshold, we decline (INSUFFICIENT_EVIDENCE) rather than
    # emit a false WRONG_MATH. This is a NEW gate and is deliberately CONSERVATIVE:
    # the threshold is far beyond any plausible human/rounding margin, so it cannot
    # swallow a real off-by-a-few-percent WRONG_MATH (which still convicts below).
    if _is_order_of_magnitude_off(stated_eps, computed):
        ratio = (max(abs(stated_eps), abs(computed))
                 / max(min(abs(stated_eps), abs(computed)), 1e-9))
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            recomputed_value=computed,
            reason=(f"EPS reconciliation not run: stated EPS {stated_eps} vs "
                    f"net_income/shares {computed:.4f} differ by ~{ratio:.0f}x — an "
                    f"order-of-magnitude gap that signals a unit-scale extraction "
                    f"artifact (net income and shares grounded at different scales, "
                    f"e.g. $M vs raw), not a genuine arithmetic disagreement. Declining "
                    f"to convict. Fix: ground net_income and shares at the SAME unit "
                    f"scale stated in the filing's '(in millions...)' header."),
        )

    result = _classify(stated=stated_eps, computed=computed, abs_tolerance=abs_tolerance)

    # WRONG-NUMERATOR SAFETY NET (Mechanism 1). Filers with preferred stock compute
    # EPS against NET INCOME APPLICABLE TO COMMON shareholders (total net income
    # minus preferred dividends), not total net income. A very common extraction
    # slip is to ground the total-net-income line above the EPS calc. When the
    # reconciliation FAILS and the grounded context names a net-income-to-common /
    # preferred-dividend line, the failure is far more likely that wrong-numerator
    # artifact than a genuine arithmetic disagreement, so we decline to convict.
    # Evidence-required (the phrase must be present in grounded context) and scoped
    # to the failing case only — it never changes a VERIFIED result.
    if result.status == VerificationStatus.WRONG_MATH and net_to_common_in_context:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            recomputed_value=computed,
            delta=result.delta,
            reason=("eps_reconciliation failed, but the grounded context names a "
                    "net-income-applicable-to-common / preferred-dividend line. EPS "
                    "for a filer with preferred stock is computed on net income net "
                    "of preferred dividends, not total net income; the extractor "
                    "likely grounded total net income. Declining to convict — fix: "
                    "ground the 'net income applicable to common' numerator."),
        )
    return result


def _normalize_basis(tag: Optional[str]) -> Optional[str]:
    """Map free-text income-basis tags to a canonical {continuing, common, total}.

    Pure string matching; returns None when the tag is absent or unrecognized
    (so the caller treats it as 'unknown', never guesses).

    "common" is the net-income-APPLICABLE-TO-COMMON basis (total net income minus
    preferred dividends) — the correct EPS numerator for filers with preferred
    stock, and the exact XBRL `NetIncomeLossAvailableToCommonStockholdersBasic`
    tag. It is DISTINCT from "total": a "common" EPS reconciled against a "total"
    numerator still mismatches (they differ by preferred dividends), so the gate
    still fires there. Recognizing "common" only lets a correctly-paired
    common/common reconciliation RUN — it never makes the gate more permissive
    about a genuine total-vs-common mismatch.
    """
    if not tag:
        return None
    t = tag.strip().lower()
    if "continu" in t:
        return "continuing"
    if "common" in t or "available to common" in t or "applicable to common" in t:
        return "common"
    if "total" in t or "net income" in t or "including" in t or "consolidated" in t:
        return "total"
    return None


def _income_basis_consistent(eps_basis: Optional[str], income_basis: Optional[str]) -> Optional[bool]:
    """True if both bases recorded and equal; False if recorded and different;
    None if either side is unknown."""
    a = _normalize_basis(eps_basis)
    b = _normalize_basis(income_basis)
    if a is None or b is None:
        return None
    if a == "total" and b == "common":
        return True
    return a == b


# Conservative order-of-magnitude threshold for the EPS scale-mismatch gate.
# 20x is far beyond any plausible human/rounding/typo margin on a per-share figure
# (those are off by a few percent), but well below the ~1000x (millions-vs-raw) or
# ~100x signature of a unit-scale extraction artifact. Calibrated from the live
# benchmark: AAPL/CRM/SPG land at ~1000x (caught); BAC 3.91-vs-3.81, PLTR
# 0.637-vs-0.63, SO 3.78-vs-3.94 are all <1.1x (NOT caught — they stay subject to
# the normal tolerance check, so a genuine small disagreement still convicts).
_EPS_SCALE_MISMATCH_RATIO = 20.0


def _is_order_of_magnitude_off(stated: float, computed: float) -> bool:
    """True when stated and computed differ by >= the scale-mismatch ratio.

    Pure arithmetic, symmetric. If either side is ~0 the ratio is meaningless, so
    we only fire when BOTH are non-trivially non-zero (a real EPS and a real
    quotient); a zero/near-zero stated EPS is handled by the normal tolerance path.
    """
    a, b = abs(stated), abs(computed)
    if a < 1e-9 or b < 1e-9:
        return False
    ratio = max(a, b) / min(a, b)
    return ratio >= _EPS_SCALE_MISMATCH_RATIO


def check_cash_flow_tie_out(
    operands: Sequence[float],
    rel_tolerance: float = DEFAULT_CASH_REL_TOLERANCE,
    *,
    restricted_cash_disclosed: Optional[bool] = None,
) -> CheckResult:
    """Cash-flow ending cash == balance-sheet cash.  Order: [statement_cash, bs_cash].

    RESTRICTED-CASH GATE (the AMD #3 fix, made explicit).  The cash-flow
    statement's ending cash often INCLUDES restricted cash, while the balance
    sheet reports unrestricted "cash and cash equivalents" on a separate line —
    so the two legitimately differ by the restricted amount.  AMD's case landed
    in AMBIGUOUS only because that gap happened to exceed tolerance; a smaller
    restricted balance would have slipped through as a false WRONG_MATH.

    When the extractor has detected a restricted-cash disclosure tied to this
    figure, we decline the naive tie-out -> INSUFFICIENT_EVIDENCE, regardless of
    the gap size.  Without that signal the rule behaves exactly as before.
    """
    if len(operands) != 2:
        return CheckResult(
            status=VerificationStatus.AMBIGUOUS,
            reason=f"cash_flow_tie_out expects 2 operands, got {len(operands)}",
        )
    if restricted_cash_disclosed is True:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason=("cash_flow_tie_out not run: a restricted-cash disclosure was "
                    "detected, so the cash-flow ending cash (which may include "
                    "restricted cash) and the balance-sheet unrestricted cash line "
                    "are not expected to be equal. A human should reconcile them."),
        )
    statement_cash, balance_sheet_cash = operands
    return _classify(stated=statement_cash, computed=balance_sheet_cash,
                     rel_tolerance=rel_tolerance)


# Registry of cross-statement rules: name -> (function, expected operand count).
INTERNAL_CONSISTENCY_RULES = {
    "balance_sheet_identity": (check_balance_sheet_identity, 3),
    "eps_reconciliation":     (check_eps_reconciliation, 3),
    "cash_flow_tie_out":      (check_cash_flow_tie_out, 2),
}


def run_internal_consistency_rule(
    rule_name: Optional[str],
    operands: Sequence[float],
    evidence: Optional[dict] = None,
) -> CheckResult:
    """Dispatch to the named rule, forwarding completeness/scope EVIDENCE.

    `evidence` is the deterministic, extractor-supplied metadata the gated rules
    need to decide whether they can responsibly run (vs. INSUFFICIENT_EVIDENCE):
      balance_sheet_identity: {"liabilities_complete": bool}
      eps_reconciliation:     {"eps_income_basis": str, "income_operand_basis": str}
      cash_flow_tie_out:      {"restricted_cash_disclosed": bool}
    Unknown rule -> AMBIGUOUS (never guesses).
    """
    if rule_name not in INTERNAL_CONSISTENCY_RULES:
        return CheckResult(
            status=VerificationStatus.AMBIGUOUS,
            reason=f"unknown internal_consistency rule_name {rule_name!r}",
        )
    ev = evidence or {}
    if rule_name == "balance_sheet_identity":
        return check_balance_sheet_identity(
            operands, liabilities_complete=ev.get("liabilities_complete"),
            nci_in_context=ev.get("nci_in_context", False))
    if rule_name == "eps_reconciliation":
        return check_eps_reconciliation(
            operands,
            eps_income_basis=ev.get("eps_income_basis"),
            income_operand_basis=ev.get("income_operand_basis"),
            net_to_common_in_context=ev.get("net_to_common_in_context", False))
    if rule_name == "cash_flow_tie_out":
        return check_cash_flow_tie_out(
            operands, restricted_cash_disclosed=ev.get("restricted_cash_disclosed"))
    fn, _expected = INTERNAL_CONSISTENCY_RULES[rule_name]  # pragma: no cover
    return fn(operands)


# ---------------------------------------------------------------------------
# §4 confound helper: the EPS variant must match the shares variant.
# This is the test that proves we *solved* the basic/diluted confound rather
# than ignoring it.  It is a structural guard, not a numeric judgment.
# ---------------------------------------------------------------------------

def eps_variant_consistent(eps_variant: Optional[EPSVariant], shares_operand: Operand) -> Optional[bool]:
    """Check whether the shares operand variant matches the EPS variant.

    Returns:
        True   — variants are recorded and match; arithmetic may proceed.
        False  — variants are recorded and disagree; block to AMBIGUOUS.
        None   — variant is unrecorded on either side; caller must block to
                 AMBIGUOUS rather than run blind.  A WRONG_MATH produced from
                 untagged operands cannot be distinguished from a variant-
                 mismatch masquerading as wrong math — so it must not be emitted.

    Previously this returned True when variants were unknown (conservative
    default = don't block).  That was wrong: it allowed a confident WRONG_MATH
    verdict on claims where the operand variant was never recorded, exactly the
    false-positive the guard was designed to prevent.
    """
    shares_variant = None
    tag = (shares_operand.category or "")
    if "basic" in tag.lower():
        shares_variant = EPSVariant.BASIC
    elif "diluted" in tag.lower():
        shares_variant = EPSVariant.DILUTED

    # Both sides unrecorded — cannot determine consistency.
    if eps_variant is None and shares_variant is None:
        return None  # caller blocks to AMBIGUOUS

    # One side unrecorded — still cannot confirm they match.
    if eps_variant is None or shares_variant is None:
        return None  # caller blocks to AMBIGUOUS

    return shares_variant == eps_variant


# ===========================================================================
# §3.2  Temporal consistency over an ordered (period, value) series
# ===========================================================================
# Operands for these ops are a series; ordering is by the period labels the
# extractor supplies.  The verifier does NOT parse dates from prose (that would
# be extraction work) — it trusts the (period, value) pairs it is handed and
# checks the asserted predicate over them as pure computation.

def _ordered_values(series: Sequence[Tuple[str, float]]) -> List[float]:
    """Return values in the given series order (already chronological by contract)."""
    return [v for _, v in series]


def check_trend_direction(
    series: Sequence[Tuple[str, float]],
    direction: TrendDir,
    flat_rel_tolerance: float = 0.001,
) -> CheckResult:
    """Does the ordered series move strictly up / strictly down / stay flat?"""
    vals = _ordered_values(series)
    if len(vals) < 2:
        return CheckResult(status=VerificationStatus.AMBIGUOUS,
                           reason="trend_direction needs >= 2 data points")
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    if direction == TrendDir.UP:
        ok = all(d > 0 for d in diffs)
    elif direction == TrendDir.DOWN:
        ok = all(d < 0 for d in diffs)
    elif direction == TrendDir.FLAT:
        # Flat HERE is well-defined: the claim asserts no change, and we test it
        # against an explicit tolerance the caller controls.  (Contrast §3.4,
        # where "flat" is the SUMMARY's vague word with no stated threshold.)
        ok = all(abs(d) <= max(abs(a), 1e-9) * flat_rel_tolerance
                 for d, a in zip(diffs, vals))
    else:  # pragma: no cover
        return CheckResult(status=VerificationStatus.AMBIGUOUS,
                           reason=f"unknown trend direction {direction!r}")
    status = VerificationStatus.VERIFIED if ok else VerificationStatus.WRONG_MATH
    return CheckResult(status=status,
                       reason=f"series {[round(v,4) for v in vals]} vs asserted {direction.value}")


def check_superlative(
    series: Sequence[Tuple[str, float]],
    which: Superlative,
    target_period: Optional[str] = None,
) -> CheckResult:
    """Is the target period's value the max/min over the window?

    If target_period is None, the LAST point in the series is taken as the
    subject ("this is the highest in five years" → the latest period).
    """
    if len(series) < 1:
        return CheckResult(status=VerificationStatus.AMBIGUOUS,
                           reason="superlative needs >= 1 data point")
    vals = _ordered_values(series)
    if target_period is None:
        subject_val = vals[-1]
    else:
        matches = [v for p, v in series if p == target_period]
        if not matches:
            return CheckResult(status=VerificationStatus.AMBIGUOUS,
                               reason=f"target period {target_period!r} not in series")
        subject_val = matches[0]
    extreme = max(vals) if which == Superlative.MAX else min(vals)
    ok = subject_val == extreme
    status = VerificationStatus.VERIFIED if ok else VerificationStatus.WRONG_MATH
    return CheckResult(status=status, recomputed_value=extreme,
                       reason=f"subject {subject_val} vs window {which.value} {extreme}")


def check_consecutive_count(
    series: Sequence[Tuple[str, float]],
    direction: TrendDir,
    stated_count: float,
) -> CheckResult:
    """How many periods in a row (counting back from the end) satisfy `direction`?

    "Revenue grew for the third consecutive quarter" → stated_count = 3, the
    number of trailing step-overs that are increases.  We count CONSECUTIVE
    qualifying steps from the most recent backward, then compare to stated.
    """
    vals = _ordered_values(series)
    if len(vals) < 2:
        return CheckResult(status=VerificationStatus.AMBIGUOUS,
                           reason="consecutive_count needs >= 2 data points")
    diffs = [b - a for a, b in zip(vals, vals[1:])]

    def qualifies(d: float) -> bool:
        if direction == TrendDir.UP:
            return d > 0
        if direction == TrendDir.DOWN:
            return d < 0
        return d == 0

    run = 0
    for d in reversed(diffs):
        if qualifies(d):
            run += 1
        else:
            break
    return _classify(stated=stated_count, computed=float(run), abs_tolerance=0.0)


# ===========================================================================
# Axis C  aggregate_filter  — sum / count over a filtered transaction subset
# ===========================================================================
# Compositional, not a new kind of math: aggregate_filter produces a number
# (a filtered sum or count) that then feeds the existing percent_change.  The
# filtering itself is deterministic set selection over operands the extractor
# already tagged; the categorization JUDGMENT lives upstream in extraction and
# is surfaced via OperandSource.CATEGORY_INFERRED, never hidden here.

def check_aggregate_filter(
    operand_values: Sequence[float],
    stated_value: float,
    mode: str = "sum",
    rel_tolerance: float = 0.005,
) -> CheckResult:
    """Sum or count the (already-filtered) operand values, compare to stated.

    The operands handed in are the subset that passed the filter (the extractor
    selects them; the verifier does not re-decide membership).  `mode` is "sum"
    or "count".
    """
    if not operand_values:
        return CheckResult(status=VerificationStatus.AMBIGUOUS,
                           reason="aggregate_filter received no operands")
    if mode == "sum":
        computed = float(sum(operand_values))
    elif mode == "count":
        computed = float(len(operand_values))
    else:
        return CheckResult(status=VerificationStatus.AMBIGUOUS,
                           reason=f"unknown aggregate mode {mode!r}")
    return _classify(stated=stated_value, computed=computed, rel_tolerance=rel_tolerance)


# ===========================================================================
# §3.4  Logical / definitional flagging — DETECT, never resolve
# ===========================================================================
# This is the one candidate that FAILS the §3.1 test, and the discipline is to
# say so.  "Costs were flat" next to a 4% table delta is a judgment call dressed
# as a fact: "flat" has no universal numeric threshold.  We refuse to invent one.
#
# The honest, useful move (cheap, deterministic): detect that a qualitative word
# sits near a number and route to NEEDS_REVIEW with a note.  No threshold, no
# verdict on correctness.

# Words that assert approximate constancy/смallness without a number.
_QUALITATIVE_CONSTANCY_WORDS = {
    "flat", "stable", "steady", "unchanged", "roughly", "approximately",
    "about", "around", "in line", "consistent", "comparable", "similar",
    "modest", "slight", "marginal", "minimal", "negligible",
}


def detect_definitional_word(text: str) -> Optional[str]:
    """Return the first qualitative-constancy word found in `text`, else None.

    Pure regex word-boundary search; no model.  Used as a flag, not a verdict.
    Multi-word phrases like "in line" are matched as substrings on word
    boundaries too.
    """
    low = (text or "").lower()
    for w in sorted(_QUALITATIVE_CONSTANCY_WORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(w)}\b", low):
            return w
    return None


def flag_definitional(claim_text: str, nearby_number: Optional[float]) -> CheckResult:
    """Route a qualitative-word-plus-number claim to human review.

    We do NOT decide whether "flat" is true of a 4% change.  We state that the
    claim pairs an undefined qualitative term with a number and needs a human.
    """
    word = detect_definitional_word(claim_text)
    if word is None:
        # Nothing qualitative detected — caller shouldn't have routed here, but
        # be safe: it's simply unchecked rather than reviewed.
        return CheckResult(status=VerificationStatus.UNCHECKED,
                           reason="no qualitative term detected; nothing to flag")
    num_part = f" near the figure {nearby_number}" if nearby_number is not None else ""
    return CheckResult(
        status=VerificationStatus.NEEDS_REVIEW,
        reason=(f"Claim uses the qualitative term '{word}'{num_part}, which has no "
                f"universal numeric threshold. Routed to human review rather than "
                f"resolved with an invented cutoff (roadmap §3.4)."),
    )


# ===========================================================================
# MD&A prose direction vs XBRL trend
# ===========================================================================

def check_mda_xbrl_consistency(
    asserted_direction: TrendDir,
    actual_percent_change: float,
    *,
    flat_band_pct: float = 2.0,
) -> CheckResult:
    """Compare extracted MD&A direction against XBRL-grounded percent change.

    The extractor supplies only the prose direction. Core compares that tag to
    numeric XBRL movement. Small actual moves stay NEEDS_REVIEW because terms
    like "significant" or "flat" require a policy threshold, not hidden code
    judgment.
    """
    if asserted_direction is None:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason="MD&A direction claim missing asserted prose direction",
        )
    if actual_percent_change is None:
        return CheckResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reason="XBRL percent change missing; cannot compare prose direction",
        )
    if abs(actual_percent_change) <= flat_band_pct:
        return CheckResult(
            status=VerificationStatus.NEEDS_REVIEW,
            recomputed_value=actual_percent_change,
            reason=(
                f"XBRL change {actual_percent_change:.2f}% is within "
                f"±{flat_band_pct:.2f}% flat/ambiguous band; qualitative "
                "MD&A wording needs human threshold judgment"
            ),
        )
    actual_direction = TrendDir.UP if actual_percent_change > 0 else TrendDir.DOWN
    if asserted_direction == TrendDir.FLAT:
        return CheckResult(
            status=VerificationStatus.NEEDS_REVIEW,
            recomputed_value=actual_percent_change,
            reason=(
                f"MD&A asserted flat but XBRL changed {actual_percent_change:.2f}%; "
                "flat is a definitional threshold, so route to review"
            ),
        )
    ok = asserted_direction == actual_direction
    return CheckResult(
        status=VerificationStatus.VERIFIED if ok else VerificationStatus.CONFLICT,
        recomputed_value=actual_percent_change,
        reason=(
            f"MD&A asserted {asserted_direction.value}; XBRL grounded "
            f"period-over-period change is {actual_percent_change:.2f}% "
            f"({actual_direction.value})"
        ),
    )
