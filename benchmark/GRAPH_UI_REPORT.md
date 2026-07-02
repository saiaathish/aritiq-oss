# graph UI data measurement (Phase 2, item 4)

Replay over real `benchmark/runs_graph/` extraction output; no synthetic all-leaf graph.

| Doc | Claims | Edges | Upstream nodes | Downstream nodes | Evidence nodes | caused_by hits | Missing refs | Note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A Northwind Logistics — Q3 FY2025 earnings release | 8 | 0 | 0 | 0 | 8 | 0 | 0 | negative control (0 edges required) |
| B Acme Corp — Invoice #4471 | 5 | 1 | 1 | 1 | 5 | 1 | 0 | real edge structure expected |
| C Globex Corp — FY2024 annual highlights | 5 | 0 | 0 | 0 | 4 | 0 | 0 | negative control (0 edges required) |
| D Meridian Inc — Cost report | 3 | 1 | 1 | 1 | 3 | 1 | 0 | real edge structure expected |

- Total real depends_on edges: **2**
- Nodes with downstream dependents: **2**
- PROPAGATED_ERROR caused_by hits under fault injection: **2**
- Missing dependency refs: **0**
- False edges on negative controls: **0**
- Result: **PASS**
