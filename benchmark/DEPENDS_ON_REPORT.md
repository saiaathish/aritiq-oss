# depends_on graph-structure measurement (Phase 2, item 1)

Replay over gold_set A–D (cached model output, no LLM). The deterministic linker infers output→input edges; the graph machinery propagates a fault-injected root failure.

| Doc | Claims | Edges | Graph nodes | Roots | Propagated on fault | Note |
|---|---|---|---|---|---|---|
| A Northwind Logistics — Q3 FY2025 earnings release | 8 | 0 | 0 | 0 | 0 | negative control (0 edges required) |
| B Acme Corp — Invoice #4471 | 5 | 1 | 4 | 1 | 1 |  |
| C Globex Corp — FY2024 annual highlights | 5 | 0 | 0 | 0 | 0 | negative control (0 edges required) |
| D Meridian Inc — Cost report | 3 | 1 | 2 | 1 | 1 |  |

- Total depends_on edges inferred on real extraction: **2**
- Downstream claims relabeled PROPAGATED_ERROR under fault injection: **2**
- False edges on shared-raw-input negative controls: **0**
- Result: **PASS**
