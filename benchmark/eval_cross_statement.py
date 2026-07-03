"""
Aritiq Phase 2 — cross-statement consistency benchmark.

Two layers, reported SEPARATELY (the §6/§8 discipline: never blend a per-rule
number into one headline):

  1. RULE-FUNCTION PRECISION (synthetic, tolerance-as-shipped).
     Construct small statements with known-correct/known-broken relationships,
     run them through the actual rule functions, and confirm every verdict
     matches the constructed ground truth. This is pure arithmetic on pure
     inputs, so it should be exact — and it is measured per rule, not blended.

  2. HARNESS SELF-TEST (fault injection).
     Corrupt each gold case the "wrong" way and assert the verdict flips, so a
     perfect score reflects a real check, not a blind grader. Clearly labelled
     fault injection — NOT a model run.

There is deliberately NO fabricated real-10-K accuracy number here. Real-document
extraction accuracy is the honest gap; it is named in the README and the Phase 2
writeup, and would require live extraction over hand-labelled filings to measure.
This harness proves the part that IS provable: the verifier logic.

Run:
    python benchmark/eval_cross_statement.py
    python benchmark/eval_cross_statement.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, EPSVariant, VerificationStatus,
)
from aritiq.core.verify import verify_claim

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD_PATH = os.path.join(HERE, "cross_statement_gold.json")


@dataclass
class GoldCase:
    doc_id: str
    name: str
    rule_name: str
    operands: List[float]
    eps_variant: Optional[str]
    shares_category: Optional[str]
    expected_status: str
    note: str


def load_gold(path: str = GOLD_PATH) -> List[GoldCase]:
    data = json.load(open(path))
    cases: List[GoldCase] = []
    for d in data["documents"]:
        for g in d["gold_claims"]:
            cases.append(GoldCase(
                doc_id=d["id"],
                name=d["name"],
                rule_name=g["rule_name"],
                operands=[float(x) for x in g["operands"]],
                eps_variant=g.get("eps_variant"),
                shares_category=g.get("shares_category"),
                expected_status=g["expected_status"],
                note=g.get("note", ""),
            ))
    return cases


def build_claim(case: GoldCase) -> Claim:
    ops = []
    for i, v in enumerate(case.operands):
        op = Operand(value=v, source=OperandSource.GROUNDED, source_text=str(v))
        if case.shares_category and i == 2:
            op.category = case.shares_category
        ops.append(op)
    return Claim(
        claim_text=f"{case.rule_name} ({case.doc_id})",
        operation=Operation.INTERNAL_CONSISTENCY,
        stated_value=None,
        operands=ops,
        rule_name=case.rule_name,
        eps_variant=EPSVariant(case.eps_variant) if case.eps_variant else None,
    )


def run(path: str = GOLD_PATH) -> Dict[str, Dict[str, int]]:
    """Return per-rule {correct, total} for the synthetic gold set."""
    cases = load_gold(path)
    per_rule: Dict[str, Dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    rows = []
    for case in cases:
        result = verify_claim(build_claim(case))
        ok = (result.status.value == case.expected_status)
        per_rule[case.rule_name]["total"] += 1
        per_rule[case.rule_name]["correct"] += int(ok)
        rows.append((case, result.status.value, ok))
    return per_rule, rows


def print_report(path: str = GOLD_PATH) -> bool:
    per_rule, rows = run(path)
    print("=" * 74)
    print("  ARITIQ — Phase 2 cross-statement benchmark (synthetic, per-rule)")
    print("=" * 74)
    for case, got, ok in rows:
        tag = "ok " if ok else "FAIL"
        print(f"    [{tag}] {case.doc_id:<4} {case.rule_name:<24} "
              f"expected={case.expected_status:<14} got={got:<14}")
    print("-" * 74)
    print("  PER-RULE PRECISION (never blended):")
    all_ok = True
    for rule, c in sorted(per_rule.items()):
        pct = 100.0 * c["correct"] / c["total"] if c["total"] else 0.0
        print(f"    {rule:<26}: {c['correct']}/{c['total']}  ({pct:.1f}%)")
        all_ok = all_ok and (c["correct"] == c["total"])
    print("=" * 74)
    print(f"  RESULT: {'all synthetic cases correct' if all_ok else 'SOME CASES FAILED'}")
    print("  NOTE: this is verifier-logic precision on constructed inputs. It is")
    print("  NOT a real-10-K accuracy claim — that gap is named in the README.")
    print("=" * 74)
    return all_ok


def run_selftest(path: str = GOLD_PATH) -> bool:
    """Fault injection: flip each VERIFIED case's math and assert it's caught.

    Proves the harness detects errors rather than rubber-stamping. Clearly
    labelled fault injection, NOT a model run.
    """
    print("=" * 74)
    print("  ARITIQ — cross-statement harness self-test (fault injection)")
    print("=" * 74)
    cases = load_gold(path)
    checks = []

    for case in cases:
        if case.expected_status != "VERIFIED":
            continue
        # Corrupt the first operand by a clearly-out-of-tolerance amount.
        bad = list(case.operands)
        bad[0] = bad[0] * 1.5 + 7.0
        corrupted = GoldCase(
            doc_id=case.doc_id, name=case.name, rule_name=case.rule_name,
            operands=bad, eps_variant=case.eps_variant,
            shares_category=case.shares_category,
            expected_status="WRONG_MATH", note="injected fault",
        )
        got = verify_claim(build_claim(corrupted)).status.value
        detected = got in ("WRONG_MATH", "AMBIGUOUS")
        checks.append((f"{case.doc_id}/{case.rule_name}: corrupting a VERIFIED case is caught", detected))

    # Also assert the §4 confound case is AMBIGUOUS (not WRONG_MATH).
    for case in cases:
        if case.shares_category and case.eps_variant and case.shares_category != case.eps_variant:
            got = verify_claim(build_claim(case)).status.value
            checks.append((f"{case.doc_id}: EPS variant confound -> AMBIGUOUS not WRONG_MATH",
                           got == "AMBIGUOUS"))

    print()
    all_ok = True
    for name, ok in checks:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")
        all_ok = all_ok and ok
    print()
    print(f"  SELF-TEST {'PASSED — the harness catches broken statements.' if all_ok else 'FAILED.'}")
    print("=" * 74)
    return all_ok


def main():
    ap = argparse.ArgumentParser(description="Aritiq Phase 2 cross-statement benchmark")
    ap.add_argument("--selftest", action="store_true", help="inject faults to prove detection")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if run_selftest() else 1)
    ok = print_report()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
