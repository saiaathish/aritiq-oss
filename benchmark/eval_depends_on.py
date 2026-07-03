"""
Phase 2 / item 1 — depends_on graph-structure measurement.

Proves that the deterministic linker (aritiq/extract/linker.py) populates real
provenance-graph structure on REAL extraction output — not just hand-built fixtures —
and that the previously-inert graph machinery (core/graph.py) is now driven by it.

What it measures, per gold document (source + AI summary, replayed from the cached
model output in benchmark/runs/), with no LLM call:
  * edges       — depends_on edges the linker inferred (output->input links)
  * DAG         — build_dag succeeds (acyclic) and how many nodes carry structure
  * propagation — for each source (root) node, fault-inject a WRONG_MATH and confirm
                  propagate_errors relabels its downstream consumers PROPAGATED_ERROR
  * false edges — docs whose claims only SHARE RAW INPUTS must stay all-leaf (0 edges)

This is a self-consistency + structure measurement, not an accuracy score against
hand-labeled edges (the gold set has no depends_on labels). Every number is
reproducible:  python benchmark/eval_depends_on.py

Run modes:
  python benchmark/eval_depends_on.py            # replay cached model outputs (default)
  python benchmark/eval_depends_on.py --md OUT    # also write a markdown summary
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from aritiq.extract.schema import parse_claims  # noqa: E402
from aritiq.extract.linker import link_claims  # noqa: E402
from aritiq.core.verify import verify_claim  # noqa: E402
from aritiq.core.graph import build_dag, propagate_errors  # noqa: E402
from aritiq.core.schema import VerificationStatus, VerificationResult  # noqa: E402

GOLD = os.path.join(HERE, "gold_set.json")
# A dedicated corpus of real model output under the SHIPPED (depends_on-hardened)
# prompt. Kept SEPARATE from benchmark/runs/ — that directory is the frozen
# gold-aligned extraction-accuracy regression baseline (test_faithful_replay), and
# must not be perturbed. These fixtures are regenerable with:
#   python benchmark/eval_depends_on.py --regen   (needs a model key)
RUNS = os.path.join(HERE, "runs_graph")

# Docs whose summaries only chain SHARED RAW INPUTS (no output->input derivation).
# The linker MUST leave these all-leaf — a non-zero edge here would be a false edge.
_NEGATIVE_CONTROL_DOCS = {"A", "C"}


def _load_doc_claims(doc):
    """Replay a doc's cached extraction, parse, and run the depends_on linker."""
    run_path = os.path.join(RUNS, f"{doc['id']}.json")
    raw = json.load(open(run_path))["raw"]
    claims, _issues = parse_claims(raw)
    claims = link_claims(claims, source_text=doc.get("source"))
    return claims


def _fault_inject_propagation(claims):
    """For each source (root) node, force WRONG_MATH and confirm downstream nodes
    become PROPAGATED_ERROR. Returns (n_roots_tested, n_downstream_relabeled)."""
    base_results = [verify_claim(c) for c in claims]
    dag = build_dag(claims)
    roots = [nid for nid in dag.nodes() if dag.direct_dependents(nid)]
    total_relabeled = 0
    for root in roots:
        injected = []
        for c, r in zip(claims, base_results):
            if c.node_id == root:
                injected.append(VerificationResult(
                    claim=c, status=VerificationStatus.WRONG_MATH,
                    explanation="[fault-injected root failure]"))
            else:
                injected.append(r)
        propagated = propagate_errors(injected)
        total_relabeled += sum(
            1 for pr in propagated
            if pr.status == VerificationStatus.PROPAGATED_ERROR and pr.caused_by == root
        )
    return len(roots), total_relabeled


def main():
    ap = argparse.ArgumentParser(description="depends_on graph-structure measurement")
    ap.add_argument("--md", default=None, help="write a markdown summary here")
    ap.add_argument("--regen", action="store_true",
                    help="regenerate the runs_graph/ corpus via a live model call (needs a key)")
    args = ap.parse_args()

    docs = json.load(open(GOLD))["documents"]

    if args.regen:
        os.makedirs(RUNS, exist_ok=True)
        for line in open(os.path.join(REPO, ".env")):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
        from aritiq.extract.extractor import _default_complete_fn, DEFAULT_MAX_TOKENS
        from aritiq.extract.prompt import build_system_prompt, build_user_prompt
        import time as _t
        fn, prov, model = _default_complete_fn(None, None, DEFAULT_MAX_TOKENS)
        for d in docs:
            raw = fn(build_system_prompt(True), build_user_prompt(d["source"], d["summary"]))
            json.dump({"raw": raw, "_generated_by": f"{prov}:{model} depends_on-hardened prompt"},
                      open(os.path.join(RUNS, f"{d['id']}.json"), "w"), indent=1)
            print(f"  regenerated {d['id']}")
            _t.sleep(2)
    rows = []
    total_edges = 0
    false_edges = 0
    total_propagated = 0
    docs_with_structure = 0

    for doc in docs:
        claims = _load_doc_claims(doc)
        n_edges = sum(len(c.depends_on) for c in claims)
        total_edges += n_edges
        # build_dag must not raise (acyclicity holds).
        dag = build_dag(claims)
        n_nodes = len(dag.nodes())
        n_roots, n_relabeled = _fault_inject_propagation(claims) if n_edges else (0, 0)
        total_propagated += n_relabeled
        if n_edges:
            docs_with_structure += 1
        if doc["id"] in _NEGATIVE_CONTROL_DOCS and n_edges:
            false_edges += n_edges
        rows.append({
            "id": doc["id"], "name": doc.get("name", ""), "n_claims": len(claims),
            "edges": n_edges, "graph_nodes": n_nodes, "roots": n_roots,
            "propagated_on_fault": n_relabeled,
            "negative_control": doc["id"] in _NEGATIVE_CONTROL_DOCS,
        })

    print("=" * 74)
    print("  depends_on GRAPH-STRUCTURE MEASUREMENT (replay, no LLM)")
    print("=" * 74)
    print(f"  {'doc':4} {'claims':>6} {'edges':>5} {'nodes':>5} {'roots':>5} "
          f"{'propagated':>10}  note")
    for r in rows:
        note = "negative control (must be 0 edges)" if r["negative_control"] else ""
        print(f"  {r['id']:4} {r['n_claims']:6} {r['edges']:5} {r['graph_nodes']:5} "
              f"{r['roots']:5} {r['propagated_on_fault']:10}  {note}")
    print("-" * 74)
    print(f"  total depends_on edges inferred on real extraction : {total_edges}")
    print(f"  documents with non-zero graph structure            : {docs_with_structure}")
    print(f"  downstream claims relabeled PROPAGATED_ERROR (fault): {total_propagated}")
    print(f"  FALSE edges on shared-raw-input negative controls   : {false_edges}")
    ok = total_edges > 0 and total_propagated > 0 and false_edges == 0
    print("-" * 74)
    print(f"  RESULT: {'PASS' if ok else 'FAIL'} — "
          f"{'non-zero structure + working propagation + no false edges' if ok else 'see above'}")

    if args.md:
        with open(args.md, "w") as fh:
            fh.write("# depends_on graph-structure measurement (Phase 2, item 1)\n\n")
            fh.write("Replay over gold_set A–D (cached model output, no LLM). The "
                     "deterministic linker infers output→input edges; the graph "
                     "machinery propagates a fault-injected root failure.\n\n")
            fh.write("| Doc | Claims | Edges | Graph nodes | Roots | Propagated on fault | Note |\n")
            fh.write("|---|---|---|---|---|---|---|\n")
            for r in rows:
                note = "negative control (0 edges required)" if r["negative_control"] else ""
                fh.write(f"| {r['id']} {r['name']} | {r['n_claims']} | {r['edges']} | "
                         f"{r['graph_nodes']} | {r['roots']} | {r['propagated_on_fault']} | {note} |\n")
            fh.write(f"\n- Total depends_on edges inferred on real extraction: **{total_edges}**\n")
            fh.write(f"- Downstream claims relabeled PROPAGATED_ERROR under fault "
                     f"injection: **{total_propagated}**\n")
            fh.write(f"- False edges on shared-raw-input negative controls: "
                     f"**{false_edges}**\n")
            fh.write(f"- Result: **{'PASS' if ok else 'FAIL'}**\n")
        print(f"  markdown: {args.md}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
