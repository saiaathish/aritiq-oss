"""
Aritiq verifier demo — runs the deterministic verifier on a realistic set of
claims extracted from a fictional earnings summary, and prints the Aritiq Score.
No API key needed: this exercises the verifier only.

Run:  python demo.py
"""
from aritiq.core.schema import Claim, Operation, Operand, OperandSource
from aritiq.core.verify import verify_claim
from aritiq.core.score import compute_score


def grounded(value: float, text: str = "") -> Operand:
    return Operand(value=value, source=OperandSource.GROUNDED,
                   source_text=text or str(value))

def missing_op() -> Operand:
    return Operand(value=0.0, source=OperandSource.MISSING)


# ---------------------------------------------------------------------------
# Fictional AI-generated summary claims (mix of right, wrong, unverifiable)
# ---------------------------------------------------------------------------
CLAIMS = [
    # 1. THE MOTIVATING EXAMPLE — stated 30%, real 25%. Should be WRONG_MATH.
    Claim(
        claim_text="Revenue rose from $100M to $125M, a 30% increase.",
        operation=Operation.PERCENT_CHANGE,
        stated_value=30.0,
        operands=[grounded(100, "$100M"), grounded(125, "$125M")],
        unit="%",
    ),

    # 2. Correct percent change.
    Claim(
        claim_text="Operating income grew 20% year-over-year, from $50M to $60M.",
        operation=Operation.PERCENT_CHANGE,
        stated_value=20.0,
        operands=[grounded(50, "$50M"), grounded(60, "$60M")],
        unit="%",
    ),

    # 3. Correct gross margin.
    Claim(
        claim_text="Gross margin was 40%, with gross profit of $50M on $125M revenue.",
        operation=Operation.MARGIN_PERCENT,
        stated_value=40.0,
        operands=[grounded(50, "$50M"), grounded(125, "$125M")],
        unit="%",
    ),

    # 4. Wrong margin — stated 45%, actual 40%.
    Claim(
        claim_text="Net margin reached 45%, reflecting strong cost discipline.",
        operation=Operation.MARGIN_PERCENT,
        stated_value=45.0,
        operands=[grounded(50, "$50M"), grounded(125, "$125M")],
        unit="%",
    ),

    # 5. Correct identity — source and stated match.
    Claim(
        claim_text="Total revenue for the quarter was $125M.",
        operation=Operation.IDENTITY,
        stated_value=125.0,
        operands=[grounded(125, "$125M")],
        unit="$M",
    ),

    # 6. Identity mismatch — stated $130M, source says $125M.
    Claim(
        claim_text="Cash on hand was $130M at quarter end.",
        operation=Operation.IDENTITY,
        stated_value=130.0,
        operands=[grounded(125, "$125M")],
        unit="$M",
    ),

    # 7. Missing operand — cannot verify.
    Claim(
        claim_text="International revenue grew 15% compared to last quarter.",
        operation=Operation.PERCENT_CHANGE,
        stated_value=15.0,
        operands=[missing_op(), grounded(28.75)],
        unit="%",
    ),

    # 8. Qualitative — excluded from score.
    Claim(
        claim_text="The company strengthened its competitive position in key markets.",
        operation=Operation.UNSUPPORTED,
        stated_value=None,
        operands=[],
    ),

    # 9. Correct absolute change.
    Claim(
        claim_text="Operating expenses increased by $10M, from $40M to $50M.",
        operation=Operation.ABSOLUTE_CHANGE,
        stated_value=10.0,
        operands=[grounded(40, "$40M"), grounded(50, "$50M")],
        unit="$M",
    ),

    # 10. Correct sum.
    Claim(
        claim_text="Combined segment revenues totalled $125M ($75M domestic + $50M international).",
        operation=Operation.SUM,
        stated_value=125.0,
        operands=[grounded(75, "$75M"), grounded(50, "$50M")],
        unit="$M",
    ),
]


# ---------------------------------------------------------------------------
# Run verification
# ---------------------------------------------------------------------------
STATUS_ICONS = {
    "VERIFIED":           "✅",
    "WRONG_MATH":         "❌",
    "UNSUPPORTED_NUMBER": "⚠️ ",
    "AMBIGUOUS":          "🔷",
    "UNCHECKED":          "—",
}

def main():
    results = [verify_claim(c) for c in CLAIMS]
    score = compute_score(results)

    print("=" * 70)
    print("  ARITIQ  —  AI Financial Summary Verifier")
    print("=" * 70)
    print()

    for i, r in enumerate(results, 1):
        icon = STATUS_ICONS.get(r.status.value, "?")
        print(f"  [{i:02d}] {icon} {r.status.value}")
        print(f"        Claim : {r.claim.claim_text}")
        if r.recomputed_value is not None:
            print(f"        Stated: {r.claim.stated_value}  |  Recomputed: {r.recomputed_value:.4f}  |  Δ={r.delta:+.4f}")
        print(f"        Note  : {r.explanation}")
        print()

    print("=" * 70)
    print(f"  ARITIQ SCORE : {score.score} / 100")
    print(f"  Checkable claims : {score.total_checkable}")
    print(f"    ✅  Verified            : {score.verified}")
    print(f"    ❌  Wrong math          : {score.wrong_math}")
    print(f"    ⚠️   Unsupported number  : {score.unsupported}")
    print(f"    🔷  Ambiguous           : {score.ambiguous}")
    print(f"    —   Unchecked (qualit.) : {score.unchecked}")
    print("=" * 70)
    print()
    print("  Verifier: pure deterministic code. No LLM in verify.py.")
    print("  Tolerance: ±0.5pp for % operations, ±0.5% relative for others.")
    print()


if __name__ == "__main__":
    main()
