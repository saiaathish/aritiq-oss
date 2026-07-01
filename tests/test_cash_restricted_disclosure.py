"""Cash-flow tie-out disclosure handling.

A cash-flow statement can include restricted cash while the balance sheet cash
line excludes it. If the source explicitly discloses that reconciliation, Aritiq
should not emit a confident WRONG_MATH on the document itself.
"""

from aritiq.core.schema import Claim, Operation, Operand, OperandSource, VerificationStatus
from aritiq.core.verify import verify_claim


def _cash_claim(statement_cash: float, balance_sheet_cash: float, *, disclosure: str = "") -> Claim:
    return Claim(
        claim_text="cash_flow_tie_out",
        operation=Operation.INTERNAL_CONSISTENCY,
        stated_value=None,
        rule_name="cash_flow_tie_out",
        operands=[
            Operand(
                value=statement_cash,
                source=OperandSource.GROUNDED,
                source_text=f"Cash and cash equivalents at end of period ${statement_cash} million",
            ),
            Operand(
                value=balance_sheet_cash,
                source=OperandSource.GROUNDED,
                source_text=(
                    f"Balance sheet cash and cash equivalents ${balance_sheet_cash} million. "
                    + disclosure
                ).strip(),
            ),
        ],
        source_text=disclosure or None,
        unit="$M",
    )


def test_restricted_cash_disclosure_blocks_confident_wrong_math():
    # A disclosed restricted-cash reconciliation means the cash-flow ending cash
    # and the balance-sheet cash line are NOT expected to tie. The gate declines
    # to convict and returns INSUFFICIENT_EVIDENCE (a more precise verdict than
    # the old AMBIGUOUS) — never a confident WRONG_MATH.
    claim = _cash_claim(
        267.0,
        241.0,
        disclosure=(
            "$26.0 million difference attributable to restricted cash held in escrow "
            "under the terms of a pending litigation settlement."
        ),
    )

    result = verify_claim(claim)

    assert result.status == VerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.status != VerificationStatus.WRONG_MATH
    assert "restricted cash" in result.explanation.lower()


def test_undisclosed_cash_gap_remains_wrong_math():
    # No restricted-cash signal anywhere: a genuine mismatch is still WRONG_MATH.
    claim = _cash_claim(267.0, 241.0)

    result = verify_claim(claim)

    assert result.status == VerificationStatus.WRONG_MATH


# ===========================================================================
# Bug C / PLTR — restricted cash named in the CF LINE LABEL itself.
# The cash-flow statement labels its ending-cash line
#   "Cash, cash equivalents, and restricted cash — end of period"
# while the balance sheet reports plain "Cash and cash equivalents". These are
# DIFFERENT SCOPES by definition; the label alone is sufficient evidence, with no
# adjacent prose disclosure required. The detection must fire on the label.
# ===========================================================================

def _pltr_cash_claim(cf_source_text: str, bs_source_text: str, *, params=None) -> Claim:
    return Claim(
        claim_text="cash_flow_tie_out",
        operation=Operation.INTERNAL_CONSISTENCY,
        stated_value=None,
        rule_name="cash_flow_tie_out",
        operands=[
            Operand(value=1_451_425.0, source=OperandSource.GROUNDED,
                    source_text=cf_source_text),
            Operand(value=1_423_796.0, source=OperandSource.GROUNDED,
                    source_text=bs_source_text),
        ],
        params=params or {},
        unit="$K",
    )


def test_pltr_restricted_cash_in_cf_label_is_insufficient():
    # CF=1,451,425 vs BS=1,423,796. The CF operand source_text is exactly the
    # PLTR label naming restricted cash. No params flag, no adjacent prose.
    # Must return INSUFFICIENT_EVIDENCE, never WRONG_MATH.
    claim = _pltr_cash_claim(
        "Cash, cash equivalents, and restricted cash — end of period $1,451,425",
        "Cash and cash equivalents $1,423,796",
    )
    result = verify_claim(claim)
    assert result.status == VerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.status != VerificationStatus.WRONG_MATH


def test_pltr_label_overrides_explicit_false_flag():
    # The deterministic normalization pass is AUTHORITATIVE: even if the extractor
    # wrongly emitted restricted_cash_disclosed=False, the label in the source
    # document forces the gate. (The label is fact, not inference.)
    claim = _pltr_cash_claim(
        "Cash, cash equivalents, and restricted cash — end of period $1,451,425",
        "Cash and cash equivalents $1,423,796",
        params={"restricted_cash_disclosed": False},
    )
    result = verify_claim(claim)
    assert result.status == VerificationStatus.INSUFFICIENT_EVIDENCE


def test_pltr_no_restricted_label_same_gap_is_wrong_math():
    # Same numeric gap, but the CF line label is plain "Cash and cash equivalents
    # end of period" with NO restricted-cash language anywhere. A genuine tie-out
    # failure must still be caught -> WRONG_MATH.
    claim = _pltr_cash_claim(
        "Cash and cash equivalents end of period $1,451,425",
        "Cash and cash equivalents $1,423,796",
    )
    result = verify_claim(claim)
    assert result.status == VerificationStatus.WRONG_MATH
