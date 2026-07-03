# Full benchmark run — staged, ready to fire

Everything below is staged so the full 83-filer benchmark can be run in **one
command** the moment codex confirms the JPM (income-to-common EPS) and WFC
(incorporate-by-reference → 0 claims) fixes are merged.

## Do NOT run yet

Running a live benchmark *right now* would just re-measure the two known,
in-flight bugs (JPM EPS false-positive `WRONG_MATH`, WFC 0 extracted claims). Wait
for codex to confirm the fixes land in `aritiq/extract/`, `aritiq/core/verify.py`,
`aritiq/core/rules.py`, `aritiq/edgar/sec.py`.

## Fire the full run (once fixes are in)

```bash
# 1. Full live run over ALL filers in filing_set.json (no --limit ⇒ all 83).
python benchmark/reliability/harness.py --live

# 2. Generate the report with the new per-sector / per-statement-type breakdowns
#    (--md also writes Markdown; the newest run is picked up automatically).
python benchmark/reliability/report.py --md benchmark/reliability/REPORT_LATEST.md
```

`--live` with no `--limit` uses the entire set (`harness.py` slices only when
`--limit N` is passed). The previous "30 filings" figure in `REPORT_LATEST.md` was a
`--limit 30` slice, not the full set.

## What changed this round (reporting layer only)

- `report.py` now emits two additional aggregations, **built from the same verdicts
  the pipeline already produced — no verdict is recomputed**:
  - **Breakdown by statement type** — `balance_sheet_identity` /
    `eps_reconciliation` / `cash_flow_tie_out`: N, % verified, % insufficient-
    evidence (gated), % extraction-miss (`UNSUPPORTED_NUMBER`), and raw
    `WRONG_MATH` count.
  - **Breakdown by sector** — same columns, grouped by each filer's `sector`.
  - This is the exact metric shape the reviewer feedback asked for: "X% verified,
    Y% gated insufficient-evidence, Z% extraction misses, by sector / statement
    type." `WRONG_MATH` (a conviction) is always a raw count, never a percentage,
    so a single false conviction stays visible.
- `filing_set.json` grew from 78 → 83 to close two genuine sector gaps that had no
  representation (not padding):
  - Healthcare **payer/provider**: `UNH` (managed care), `HCA` (hospitals) — all
    prior "healthcare" was pharma/devices/REIT.
  - **Transportation**: `UNP` (rail), `DAL` (airline), `UPS` (parcel) — none
    previously (`UHAL` is truck-rental logistics).

## Expected effect of codex's fixes on the breakdowns

Once merged, re-running the two commands above should show, in the new tables:
- **Banking** sector and **eps_reconciliation** statement type: the `WRONG_MATH`
  count drops from 1 → 0 (JPM now uses income-to-common).
- **Banking / WFC**: WFC moves from 0 claims to a non-empty claim set, raising the
  Banking `N` and the overall completion rate.

Both are directly readable from the new per-sector / per-statement-type tables —
which is the point of adding them.
