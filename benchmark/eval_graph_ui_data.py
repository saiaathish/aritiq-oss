"""Measure graph UI data availability from real depends_on replay fixtures.

This is intentionally data-level: the React component consumes the same fields
(`node_id`, `depends_on`, `caused_by`, source/evidence text) through
frontend/lib/graph.ts. The measurement proves real extraction output has
non-empty neighborhoods where item 1 produced edges, and no false edges in
negative controls.

Run:
    python benchmark/eval_graph_ui_data.py
    python benchmark/eval_graph_ui_data.py --md benchmark/GRAPH_UI_REPORT.md
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
from aritiq.core.graph import propagate_errors  # noqa: E402
from aritiq.core.schema import VerificationResult, VerificationStatus  # noqa: E402

GOLD = os.path.join(HERE, "gold_set.json")
RUNS = os.path.join(HERE, "runs_graph")
NEGATIVE_CONTROLS = {"A", "C"}


def _load_claims(doc: dict):
    raw = json.load(open(os.path.join(RUNS, f"{doc['id']}.json")))["raw"]
    claims, issues = parse_claims(raw)
    if issues:
        raise RuntimeError(f"{doc['id']} parse issues: {[i.reason for i in issues]}")
    return link_claims(claims, source_text=doc["source"])


def _node_id(claim, idx: int) -> str:
    return claim.node_id or f"claim-{idx + 1}"


def _measure_doc(doc: dict) -> dict:
    claims = _load_claims(doc)
    ids = [_node_id(c, i) for i, c in enumerate(claims)]
    id_set = set(ids)
    edges = []
    missing = []
    for idx, c in enumerate(claims):
        target = ids[idx]
        for dep in c.depends_on:
            if dep in id_set:
                edges.append((dep, target))
            else:
                missing.append((target, dep))
    downstream = {nid: 0 for nid in ids}
    upstream = {nid: 0 for nid in ids}
    for source, target in edges:
        downstream[source] += 1
        upstream[target] += 1

    # Prove caused_by can be populated for the same real graph structure UI consumes.
    base_results = [verify_claim(c) for c in claims]
    root_ids = [nid for nid in ids if downstream[nid] > 0]
    caused_by_hits = 0
    for root in root_ids:
        injected = []
        for c, r in zip(claims, base_results):
            injected.append(
                VerificationResult(c, VerificationStatus.WRONG_MATH, explanation="[fault-injected root]")
                if c.node_id == root
                else r
            )
        propagated = propagate_errors(injected)
        caused_by_hits += sum(
            1
            for r in propagated
            if r.status == VerificationStatus.PROPAGATED_ERROR and r.caused_by == root
        )

    nodes_with_evidence = sum(1 for c in claims if c.source_text or any(o.source_text for o in c.operands))
    return {
        "id": doc["id"],
        "name": doc["name"],
        "claims": len(claims),
        "edges": len(edges),
        "nodes_with_upstream": sum(1 for n in ids if upstream[n] > 0),
        "nodes_with_downstream": sum(1 for n in ids if downstream[n] > 0),
        "nodes_with_evidence": nodes_with_evidence,
        "missing_refs": len(missing),
        "caused_by_hits": caused_by_hits,
        "negative_control": doc["id"] in NEGATIVE_CONTROLS,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="graph UI data measurement")
    ap.add_argument("--md", default=None, help="write markdown summary")
    args = ap.parse_args()

    docs = json.load(open(GOLD))["documents"]
    rows = [_measure_doc(doc) for doc in docs]
    total_edges = sum(r["edges"] for r in rows)
    total_downstream = sum(r["nodes_with_downstream"] for r in rows)
    total_caused_by = sum(r["caused_by_hits"] for r in rows)
    false_edges = sum(r["edges"] for r in rows if r["negative_control"])
    missing_refs = sum(r["missing_refs"] for r in rows)

    for r in rows:
        tag = "NEG" if r["negative_control"] else "EDGE"
        print(
            f"[{tag}] {r['id']} {r['name']}: claims={r['claims']} edges={r['edges']} "
            f"up={r['nodes_with_upstream']} down={r['nodes_with_downstream']} "
            f"evidence={r['nodes_with_evidence']} caused_by={r['caused_by_hits']} "
            f"missing={r['missing_refs']}"
        )

    print("\n" + "=" * 72)
    print(" GRAPH UI DATA RESULTS over runs_graph A-D")
    print("=" * 72)
    print(f" total real depends_on edges: {total_edges}")
    print(f" nodes with downstream dependents: {total_downstream}")
    print(f" PROPAGATED_ERROR caused_by hits under fault injection: {total_caused_by}")
    print(f" missing dependency refs: {missing_refs}")
    print(f" false edges on shared-raw-input negative controls: {false_edges}")

    ok = total_edges > 0 and total_downstream > 0 and total_caused_by > 0 and missing_refs == 0 and false_edges == 0

    if args.md:
        with open(args.md, "w") as fh:
            fh.write("# graph UI data measurement (Phase 2, item 4)\n\n")
            fh.write("Replay over real `benchmark/runs_graph/` extraction output; no synthetic all-leaf graph.\n\n")
            fh.write("| Doc | Claims | Edges | Upstream nodes | Downstream nodes | Evidence nodes | caused_by hits | Missing refs | Note |\n")
            fh.write("|---|---:|---:|---:|---:|---:|---:|---:|---|\n")
            for r in rows:
                note = "negative control (0 edges required)" if r["negative_control"] else "real edge structure expected"
                fh.write(
                    f"| {r['id']} {r['name']} | {r['claims']} | {r['edges']} | "
                    f"{r['nodes_with_upstream']} | {r['nodes_with_downstream']} | "
                    f"{r['nodes_with_evidence']} | {r['caused_by_hits']} | {r['missing_refs']} | {note} |\n"
                )
            fh.write(f"\n- Total real depends_on edges: **{total_edges}**\n")
            fh.write(f"- Nodes with downstream dependents: **{total_downstream}**\n")
            fh.write(f"- PROPAGATED_ERROR caused_by hits under fault injection: **{total_caused_by}**\n")
            fh.write(f"- Missing dependency refs: **{missing_refs}**\n")
            fh.write(f"- False edges on negative controls: **{false_edges}**\n")
            fh.write(f"- Result: **{'PASS' if ok else 'FAIL'}**\n")
        print(f" markdown: {args.md}")

    print("-" * 72)
    print(f" RESULT: {'PASS' if ok else 'FAIL'} — real graph neighborhoods available to UI")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
