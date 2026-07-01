"""
Aritiq Day 2 — extraction evaluation harness.

Runs the LLM extractor against the hand-labeled gold set and measures how often
extraction is right, broken down the way the build guide asks for:

    * claim recall        — did it find every numeric claim?
    * operation accuracy  — did it pick the right operation?
    * operand-order acc.  — did it get [old, new] etc. in the right order?
    * grounding accuracy  — grounded / inferred / missing labeled correctly?

It also reports two roll-ups that make the number meaningful:

    * fully-correct rate  — claim matched AND operation, stated_value, operand
                            values+order, and grounding ALL correct.
    * verdict agreement   — does the FINAL verifier verdict come out the same
                            whether you feed it the gold operands or the
                            extracted ones?  This is what actually matters: an
                            extraction slip only counts against the product if
                            it changes the verdict.

Matching is deterministic (no LLM): predicted claims are aligned to gold by
claim-text overlap plus stated-value proximity, so the score never depends on a
model grading a model.

Run modes
---------
    python benchmark/eval_extraction.py            # replay saved model outputs
    python benchmark/eval_extraction.py --live     # call the real LLM (needs key)
    python benchmark/eval_extraction.py --runs DIR # replay from a chosen dir
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# Make the package importable when run as a script from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aritiq.core.schema import Claim, Operand, Operation, OperandSource
from aritiq.core.verify import verify_claim
from aritiq.extract import extract_claims
from aritiq.extract.schema import parse_claims

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD_PATH = os.path.join(HERE, "gold_set.json")
RUNS_DIR = os.path.join(HERE, "runs")

ORDER_SENSITIVE = {
    Operation.PERCENT_CHANGE,
    Operation.ABSOLUTE_CHANGE,
    Operation.DIFFERENCE,
    Operation.RATIO,
    Operation.MARGIN_PERCENT,
}

_STOP = {"the", "was", "were", "and", "a", "an", "of", "to", "in", "at", "is",
         "its", "over", "year", "with", "for", "on", "from"}


# ---------------------------------------------------------------------------
# Numeric comparison
# ---------------------------------------------------------------------------

def _num_eq(a: Optional[float], b: Optional[float], rel: float = 0.01, abs_floor: float = 0.05) -> bool:
    """Sign-aware numeric equality with a small relative tolerance."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs(b) * rel, abs_floor)


def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 2 and t not in _STOP}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


# ---------------------------------------------------------------------------
# Gold loading
# ---------------------------------------------------------------------------

@dataclass
class GoldClaim:
    id: str
    claim_text: str
    operation: Operation
    stated_value: Optional[float]
    operands: List[Operand]
    unit: Optional[str]
    expected_status: str
    trap: str

    def as_claim(self) -> Claim:
        return Claim(
            claim_text=self.claim_text,
            operation=self.operation,
            stated_value=self.stated_value,
            operands=self.operands,
            unit=self.unit,
        )


@dataclass
class GoldDoc:
    id: str
    name: str
    source: str
    summary: str
    claims: List[GoldClaim]


def _operand_from_json(o: dict) -> Operand:
    v = o["value"]
    return Operand(
        value=v if v is not None else 0.0,
        source=OperandSource(o["source"]),
        source_text=o.get("source_text"),
    )


def load_gold(path: str = GOLD_PATH) -> List[GoldDoc]:
    data = json.load(open(path))
    docs = []
    for d in data["documents"]:
        claims = [
            GoldClaim(
                id=g["id"],
                claim_text=g["claim_text"],
                operation=Operation(g["operation"]),
                stated_value=g["stated_value"],
                operands=[_operand_from_json(o) for o in g["operands"]],
                unit=g.get("unit"),
                expected_status=g["expected_status"],
                trap=g.get("trap", ""),
            )
            for g in d["gold_claims"]
        ]
        docs.append(GoldDoc(id=d["id"], name=d["name"], source=d["source"],
                            summary=d["summary"], claims=claims))
    return docs


# ---------------------------------------------------------------------------
# Matching (deterministic): align predicted claims to gold claims
# ---------------------------------------------------------------------------

def match_claims(pred: List[Claim], gold: List[GoldClaim]) -> List[Tuple[Optional[int], int]]:
    """
    Return a list of (pred_index_or_None, gold_index) pairs covering every gold
    claim, plus (pred_index, None) for spurious predictions.

    Greedy maximum-similarity assignment on claim-text overlap with a stated-value
    tie-breaker.  Each predicted claim matches at most one gold claim.
    """
    scored = []
    for gi, g in enumerate(gold):
        gtok = _tokens(g.claim_text)
        for pi, p in enumerate(pred):
            sim = 3.0 * _jaccard(_tokens(p.claim_text), gtok)
            if _num_eq(p.stated_value, g.stated_value):
                sim += 1.0
            if p.operation == g.operation:
                sim += 0.3
            scored.append((sim, pi, gi))
    scored.sort(reverse=True)

    used_pred, used_gold = set(), set()
    pairs: List[Tuple[Optional[int], int]] = []
    for sim, pi, gi in scored:
        if sim <= 0.15:
            continue
        if pi in used_pred or gi in used_gold:
            continue
        used_pred.add(pi)
        used_gold.add(gi)
        pairs.append((pi, gi))

    for gi in range(len(gold)):
        if gi not in used_gold:
            pairs.append((None, gi))   # missed gold claim
    for pi in range(len(pred)):
        if pi not in used_pred:
            pairs.append((pi, None))   # spurious prediction
    return pairs


# ---------------------------------------------------------------------------
# Per-claim scoring of a matched pair
# ---------------------------------------------------------------------------

@dataclass
class ClaimEval:
    gold_id: Optional[str]
    matched: bool
    operation_ok: Optional[bool] = None
    stated_ok: Optional[bool] = None
    order_ok: Optional[bool] = None         # None when not applicable
    order_flip: bool = False
    grounding_ok: Optional[bool] = None
    fully_correct: bool = False
    verdict_gold: Optional[str] = None
    verdict_pred: Optional[str] = None
    verdict_agree: bool = False
    spurious: bool = False
    detail: str = ""


def _operand_values(c: Claim) -> List[Optional[float]]:
    out = []
    for o in c.operands:
        out.append(None if o.source == OperandSource.MISSING else o.value)
    return out


def _grounding_labels(c: Claim) -> List[str]:
    return [o.source.value for o in c.operands]


def _eval_pair(pred: Optional[Claim], g: GoldClaim) -> ClaimEval:
    if pred is None:
        ev = ClaimEval(gold_id=g.id, matched=False, detail="not extracted (missed)")
        ev.verdict_gold = verify_claim(g.as_claim()).status.value
        ev.verdict_pred = None
        ev.verdict_agree = False
        return ev

    ev = ClaimEval(gold_id=g.id, matched=True)
    ev.operation_ok = (pred.operation == g.operation)
    ev.stated_ok = _num_eq(pred.stated_value, g.stated_value)

    gvals = _operand_values(g.as_claim())
    pvals = _operand_values(pred)

    # Operand order (only meaningful for order-sensitive ops with matching counts
    # and no missing gold operands).
    if g.operation in ORDER_SENSITIVE and None not in gvals and len(pvals) == len(gvals):
        ev.order_ok = all(_num_eq(pv, gv) for pv, gv in zip(pvals, gvals))
        if not ev.order_ok and sorted(x for x in pvals if x is not None) == \
                sorted(x for x in gvals if x is not None) and len(pvals) == len(gvals):
            ev.order_flip = True

    # Grounding: align by value (so an order flip doesn't double-penalize), then
    # compare source labels.
    ev.grounding_ok = _grounding_match(pred, g)

    # Fully correct (strict): everything that applies must be right.
    operands_ok = (len(pvals) == len(gvals)) and _multiset_eq(pvals, gvals)
    order_component = (ev.order_ok is None) or ev.order_ok
    ev.fully_correct = bool(
        ev.operation_ok and ev.stated_ok and operands_ok and order_component and ev.grounding_ok
    )

    # Downstream verdict agreement.
    ev.verdict_gold = verify_claim(g.as_claim()).status.value
    ev.verdict_pred = verify_claim(pred).status.value
    ev.verdict_agree = (ev.verdict_gold == ev.verdict_pred)

    bits = []
    if not ev.operation_ok:
        bits.append(f"op {pred.operation.value}!={g.operation.value}")
    if not ev.stated_ok:
        bits.append(f"stated {pred.stated_value}!={g.stated_value}")
    if ev.order_flip:
        bits.append("operand ORDER flipped")
    elif ev.order_ok is False:
        bits.append("operand values wrong")
    if not ev.grounding_ok:
        bits.append(f"grounding {_grounding_labels(pred)}!={_grounding_labels(g.as_claim())}")
    ev.detail = "; ".join(bits) if bits else "correct"
    return ev


def _multiset_eq(a: List[Optional[float]], b: List[Optional[float]]) -> bool:
    an = sorted(x for x in a if x is not None)
    bn = sorted(x for x in b if x is not None)
    am = sum(1 for x in a if x is None)
    bm = sum(1 for x in b if x is None)
    if am != bm or len(an) != len(bn):
        return False
    return all(_num_eq(x, y) for x, y in zip(an, bn))


def _grounding_match(pred: Claim, g: GoldClaim) -> bool:
    """Compare grounding labels after aligning predicted operands to gold by value."""
    gold_ops = g.operands
    pred_ops = list(pred.operands)
    if len(pred_ops) != len(gold_ops):
        return False
    used = set()
    for go in gold_ops:
        gv = None if go.source == OperandSource.MISSING else go.value
        best = None
        for i, po in enumerate(pred_ops):
            if i in used:
                continue
            pv = None if po.source == OperandSource.MISSING else po.value
            if _num_eq(pv, gv):
                best = i
                break
        if best is None:
            return False
        used.add(best)
        if pred_ops[best].source != go.source:
            return False
    return True


# ---------------------------------------------------------------------------
# Run a document through the extractor and score it
# ---------------------------------------------------------------------------

@dataclass
class DocResult:
    doc: GoldDoc
    pred: List[Claim]
    n_issues: int
    evals: List[ClaimEval]
    spurious: int


def evaluate_doc(doc: GoldDoc, complete_fn: Optional[Callable]) -> DocResult:
    out = extract_claims(doc.source, doc.summary, complete_fn=complete_fn)
    pred = out.claims
    pairs = match_claims(pred, doc.claims)

    evals: List[ClaimEval] = []
    spurious = 0
    for pi, gi in pairs:
        if gi is None:
            spurious += 1
            continue
        g = doc.claims[gi]
        p = pred[pi] if pi is not None else None
        evals.append(_eval_pair(p, g))
    return DocResult(doc=doc, pred=pred, n_issues=out.n_issues, evals=evals, spurious=spurious)


# ---------------------------------------------------------------------------
# Aggregate + report
# ---------------------------------------------------------------------------

def _pct(num: int, den: int) -> str:
    return f"{(100.0 * num / den):.1f}%" if den else "n/a"


def summarize(results: List[DocResult]) -> Dict[str, object]:
    all_evals = [e for r in results for e in r.evals]
    total_gold = len(all_evals)
    matched = [e for e in all_evals if e.matched]

    recall_n = len(matched)
    op_den = [e for e in matched if e.operation_ok is not None]
    op_n = sum(1 for e in op_den if e.operation_ok)
    stated_den = [e for e in matched if e.stated_ok is not None]
    stated_n = sum(1 for e in stated_den if e.stated_ok)
    order_den = [e for e in matched if e.order_ok is not None]
    order_n = sum(1 for e in order_den if e.order_ok)
    ground_den = [e for e in matched if e.grounding_ok is not None]
    ground_n = sum(1 for e in ground_den if e.grounding_ok)
    full_n = sum(1 for e in matched if e.fully_correct)
    verdict_n = sum(1 for e in all_evals if e.verdict_agree)
    spurious = sum(r.spurious for r in results)
    issues = sum(r.n_issues for r in results)

    return {
        "total_gold": total_gold,
        "recall": (recall_n, total_gold),
        "operation": (op_n, len(op_den)),
        "stated_value": (stated_n, len(stated_den)),
        "operand_order": (order_n, len(order_den)),
        "grounding": (ground_n, len(ground_den)),
        "fully_correct": (full_n, len(matched)),
        "verdict_agreement": (verdict_n, total_gold),
        "spurious": spurious,
        "schema_issues": issues,
    }


def print_report(results: List[DocResult], mode: str) -> Dict[str, object]:
    print("=" * 74)
    print("  ARITIQ — Day 2 extraction benchmark")
    print(f"  mode: {mode}")
    print("=" * 74)

    for r in results:
        print(f"\n  Document {r.doc.id}: {r.doc.name}")
        print(f"    extracted {len(r.pred)} claims | {r.spurious} spurious | {r.n_issues} schema-rejected")
        for e in r.evals:
            tag = "ok " if (e.matched and e.detail == "correct") else "MISS" if not e.matched else "ERR "
            agree = "=" if e.verdict_agree else "≠"
            vg = e.verdict_gold or "-"
            vp = e.verdict_pred or "-"
            print(f"      [{tag}] {e.gold_id:<3} verdict gold={vg:<18} pred={vp:<18} {agree}  {e.detail}")

    s = summarize(results)
    print("\n" + "=" * 74)
    print("  EXTRACTION ACCURACY (the Day 2 numbers)")
    print("=" * 74)
    print(f"    Claim recall          : {_pct(*s['recall'])}   ({s['recall'][0]}/{s['recall'][1]} gold claims found)")
    print(f"    Operation accuracy    : {_pct(*s['operation'])}   ({s['operation'][0]}/{s['operation'][1]} matched)")
    print(f"    Stated-value accuracy : {_pct(*s['stated_value'])}   ({s['stated_value'][0]}/{s['stated_value'][1]} matched)")
    print(f"    Operand-order accuracy: {_pct(*s['operand_order'])}   ({s['operand_order'][0]}/{s['operand_order'][1]} order-sensitive)")
    print(f"    Grounding accuracy    : {_pct(*s['grounding'])}   ({s['grounding'][0]}/{s['grounding'][1]} matched)")
    print(f"    Fully-correct claims  : {_pct(*s['fully_correct'])}   ({s['fully_correct'][0]}/{s['fully_correct'][1]} matched)")
    print(f"    Spurious extractions  : {s['spurious']}")
    print(f"    Schema-rejected items : {s['schema_issues']}")
    print("-" * 74)
    print(f"    VERDICT AGREEMENT     : {_pct(*s['verdict_agreement'])}   ({s['verdict_agreement'][0]}/{s['verdict_agreement'][1]} gold claims)")
    print("      (does the final verifier verdict match when fed extracted vs gold operands?)")

    # Name the failures explicitly — the honest, useful part.
    fails = [e for r in results for e in r.evals if (not e.matched) or (not e.verdict_agree) or (e.detail != "correct")]
    print("\n  FAILURE CASES (named):")
    if not fails:
        print("    none")
    for e in fails:
        why = e.detail if e.matched else "missed entirely"
        flag = "" if e.verdict_agree else "  <-- changes the verdict"
        print(f"    - {e.gold_id}: {why}{flag}")
    print("=" * 74)
    return s


# ---------------------------------------------------------------------------
# Completion backends for the harness
# ---------------------------------------------------------------------------

def replay_complete_fn(runs_dir: str):
    """Return a complete_fn that serves the saved raw model output per document.

    The harness sets the 'current document id' before each call so the right
    artifact is returned.  Artifacts live in runs_dir/<doc_id>.json as
    {"raw": "<model text>"}.
    """
    state = {"doc_id": None}

    def setter(doc_id: str):
        state["doc_id"] = doc_id

    def complete(system_prompt: str, user_prompt: str) -> str:
        path = os.path.join(runs_dir, f"{state['doc_id']}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"No replay artifact for document {state['doc_id']} at {path}. "
                f"Run with --live (and an API key) to generate fresh extractions."
            )
        return json.load(open(path))["raw"]

    complete.setter = setter  # type: ignore[attr-defined]
    return complete


def _underlying_array(runs_dir: str, doc_id: str) -> list:
    raw = json.load(open(os.path.join(runs_dir, f"{doc_id}.json")))["raw"]
    from aritiq.extract.schema import _extract_json_array
    return json.loads(_extract_json_array(raw))


def run_selftest(runs_dir: str) -> bool:
    """
    Prove the harness DETECTS extraction errors — so a high score reflects good
    extraction, not a blind grader.

    We take the faithful replay outputs, inject a battery of named faults (the
    exact failure modes the build guide lists), and assert each one is caught by
    the corresponding metric.  This is fault injection, clearly labeled — it is
    NOT a model run.
    """
    import copy
    print("=" * 74)
    print("  ARITIQ — Day 2 harness self-test (fault injection)")
    print("  Injecting known extraction errors; each must be detected.")
    print("=" * 74)

    docs = {d.id: d for d in load_gold()}

    # Start from faithful arrays, then corrupt specific claims.
    A = _underlying_array(runs_dir, "A")
    C = _underlying_array(runs_dir, "C")

    # Fault 1: operand-order flip on A3 (25,30)->(30,25). Flips VERIFIED->WRONG_MATH.
    A[2]["operands"] = list(reversed(A[2]["operands"]))
    # Fault 2: operation error on A2 (margin_percent -> ratio).
    A[1]["operation"] = "ratio"
    # Fault 3: stated-value error on A7 (80 -> 85).
    A[6]["stated_value"] = 85
    # Fault 4: dropped claim — remove A6 (recall miss).
    dropped = A.pop(5)
    # Fault 5: schema-malformed extra item (bad operation enum) — must be rejected.
    A.append({"claim_text": "garbage", "operation": "growth", "stated_value": 1, "operands": []})
    # Fault 6: guessed operands turning a MISSING case into a false VERIFIED (C4).
    C[3]["operands"] = [{"value": 10, "source": "grounded", "source_text": "fabricated"},
                        {"value": 11.2, "source": "grounded", "source_text": "fabricated"}]

    corrupt = {"A": json.dumps(A), "C": json.dumps(C),
               "B": json.dumps(_underlying_array(runs_dir, "B")),
               "D": json.dumps(_underlying_array(runs_dir, "D"))}

    def fn_factory(doc_id):
        return lambda s, u: corrupt[doc_id]

    results = [evaluate_doc(docs[i], fn_factory(i)) for i in ["A", "B", "C", "D"]]
    s = summarize(results)

    checks = [
        ("recall detects dropped claim",      s["recall"][0] < s["recall"][1]),
        ("operation accuracy detects op error", s["operation"][0] < s["operation"][1]),
        ("operand-order detects flip",        s["operand_order"][0] < s["operand_order"][1]),
        ("stated-value detects misread",      s["stated_value"][0] < s["stated_value"][1]),
        ("grounding detects guessed operand", s["grounding"][0] < s["grounding"][1]),
        ("verdict agreement drops",           s["verdict_agreement"][0] < s["verdict_agreement"][1]),
        ("schema validation rejects bad enum", s["schema_issues"] > 0),
    ]
    print()
    all_ok = True
    for name, ok in checks:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")
        all_ok = all_ok and ok
    print()
    print(f"    injected faults -> recall {_pct(*s['recall'])}, operation {_pct(*s['operation'])}, "
          f"order {_pct(*s['operand_order'])}, grounding {_pct(*s['grounding'])},")
    print(f"    stated {_pct(*s['stated_value'])}, verdict-agreement {_pct(*s['verdict_agreement'])}, "
          f"schema-rejected {s['schema_issues']}")
    print()
    print(f"  SELF-TEST {'PASSED — the harness catches extraction errors.' if all_ok else 'FAILED.'}")
    print("=" * 74)
    return all_ok


def main():
    ap = argparse.ArgumentParser(description="Aritiq Day 2 extraction benchmark")
    ap.add_argument("--live", action="store_true", help="call the real LLM (needs API key)")
    ap.add_argument("--runs", default=RUNS_DIR, help="directory of replay artifacts")
    ap.add_argument("--selftest", action="store_true", help="inject faults to prove the harness detects errors")
    args = ap.parse_args()

    if args.selftest:
        ok = run_selftest(args.runs)
        sys.exit(0 if ok else 1)

    docs = load_gold()

    if args.live:
        complete_fn = None  # extractor builds the real client from env
        results = [evaluate_doc(d, complete_fn) for d in docs]
        mode = "LIVE (real LLM via aritiq.extract)"
    else:
        replay = replay_complete_fn(args.runs)
        results = []
        for d in docs:
            replay.setter(d.id)
            results.append(evaluate_doc(d, replay))
        mode = f"REPLAY (saved model outputs in {os.path.relpath(args.runs, HERE)}/)"

    print_report(results, mode)


if __name__ == "__main__":
    main()
