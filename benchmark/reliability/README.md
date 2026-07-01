# Aritiq Reliability Harness

Full-pipeline measurement over real SEC filings: **SEC fetch → extraction → verification → scoring**, logging exactly what the extractor emitted and what verdict the deterministic verifier produced — so a human can separate **extraction failures** from **verifier failures** before deployment.

**Measurement first.** This harness makes no accuracy claims and changes no engine code (`aritiq/core/` is untouched). It only observes and counts.

## Layout

```
benchmark/reliability/
  filing_set.json     30 large-cap US filers, tagged by sector + stress dimension
  harness.py          fetch -> extract -> verify, with on-disk caching + replay
  report.py           verdict counts, evidence-flag emission, failure taxonomy,
                      extraction-vs-verifier split, prioritized fix list, review CSV
  cache/
    filings/          cached SEC statement text (no LLM, reproducible)
    extractions/      cached model output per ticker (live runs OR seeded fixtures)
    runs/             timestamped run results + per-run manual-review CSV
  REPORT.md           latest rendered report
```

## Three stages, each cached

1. **Fetch** — `aritiq.edgar.sec.fetch_10k_text(ticker)`. SEC only, no cost. Cached to `cache/filings/`.
2. **Extract** — `aritiq.extract.extract_internal_consistency(text)`. The LLM stage. Runs **live** when a model backend is reachable; **replays** the cached raw JSON otherwise. Either path parses through the same `parse_claims` the real pipeline uses.
3. **Verify** — `aritiq.core.verify.verify_claim(claim)`. Pure code; always runs. The firewall: only `Claim` objects cross in.

## Usage

```bash
# Fetch all 30 filings from SEC and cache them (no LLM):
python benchmark/reliability/harness.py --fetch-only

# Offline / replay (safe anywhere; uses cached extractions):
python benchmark/reliability/harness.py --replay

# Full live run where a model backend is reachable (uses ARITIQ_PROVIDER + key):
python benchmark/reliability/harness.py --live

# Generate the report + manual-review CSV from the newest run:
python benchmark/reliability/report.py --md benchmark/reliability/REPORT.md
```

Useful flags: `--tickers AMD PLTR ...` (subset), `--limit N`, `--no-cache` (re-fetch), `--provider/--model` (override backend).

## What it logs per claim

`rule_name`, `verdict`, operand values, whether each gate's **evidence flags** were emitted (`liabilities_complete`; `eps_income_basis` + `income_operand_basis`; `restricted_cash_disclosed`), whether the gate could **run** vs **declined**, income basis carried on the operand category, EPS variant + shares category, and graph fields (`node_id`, `depends_on`).

## Failure taxonomy (auto-bucketed; confirm in the review CSV)

| Bucket | Owner | Meaning |
|---|---|---|
| `auto:true_positive_candidate` | verified | math agreed, gate ran |
| `auto:NEEDS_REVIEW_HIGH(conviction)` | needs human | a WRONG_MATH — confirm it's real |
| `extraction_failure:missing_evidence_flags` | extraction | gate declined because flags weren't emitted |
| `extraction_failure:missing_operand` | extraction | an operand could not be located |
| `verifier_gate_fired:by_design` | verifier (by design) | flags emitted, gate correctly declined (incomplete liab / basis mismatch / restricted cash) |
| `verifier_safety_net:restricted_cash_label_caught` | verifier (safety net) | flag missing, but the CF restricted-cash label detector reached the correct cautious verdict |
| `verifier_structural:variant_or_count_or_div0` | verifier (structural) | AMBIGUOUS from unrecorded EPS variant, bad operand count, or divide-by-zero |

The auto-bucket is a heuristic over observable signals — **not** ground truth. The per-run `*_review.csv` has a blank `human_label(TP/TN/FP/FN)` column for real adjudication.

## On the cached extractions in this repo

The model backend was **not reachable from the build sandbox** (datacenter IP blocked by the provider's CDN), so live extraction could not be originated here. The `cache/extractions/*.json` files are **seeded fixtures** — hand-authored from each filing's *real fetched statement text* and clearly marked `"_seed_note"` — covering AMD (current-only liabilities + untagged continuing-ops EPS), PLTR (restricted-cash CF label), NVDA (untagged EPS, math fine), and KO (no standalone Total Liabilities row in the slice). They exist so the replay → parse → verify → log path is demonstrable on real numbers. **Run `--live` on a machine with a working backend to replace them with genuine model output**; the harness caches the live JSON in the same place.
