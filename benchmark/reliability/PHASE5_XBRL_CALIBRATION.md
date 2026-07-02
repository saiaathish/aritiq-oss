# Phase 5 expanded XBRL benchmark report

- Source run: `reliability/cache/runs/xbrl_run_1782971461.json`
- Filers: 115
- XBRL-grounded claims: 354
- Verdict totals: `{'VERIFIED': 281, 'INSUFFICIENT_EVIDENCE': 63, 'WRONG_MATH': 10}`
- Precision (VERIFIED / VERIFIED+WRONG_MATH): 96.6%
- False-positive rate (WRONG_MATH / VERIFIED+WRONG_MATH): 3.4%
- Verification recall/coverage (VERIFIED / all emitted claims): 79.4%
- Decline rate (INSUFFICIENT_EVIDENCE / all emitted claims): 17.8%

## Confidence calibration definition

No new confidence score is invented. Confidence tier is derived from existing verifier state: high = decisive math verdict (VERIFIED or WRONG_MATH), medium = conservative verifier decline (INSUFFICIENT_EVIDENCE), low = no XBRL claim/fetch failure.

| Tier | Verdict mix |
|---|---|
| high | `{'VERIFIED': 281, 'WRONG_MATH': 10}` |
| medium | `{'INSUFFICIENT_EVIDENCE': 63}` |

## Breakdown by statement type

| Statement type | Claims | Verdict mix |
|---|---:|---|
| eps_reconciliation | 180 | `VERIFIED=170 WRONG_MATH=10` |
| balance_sheet_identity | 88 | `VERIFIED=77 INSUFFICIENT_EVIDENCE=11` |
| cash_flow_tie_out | 86 | `VERIFIED=34 INSUFFICIENT_EVIDENCE=52` |

## Breakdown by sector

| Sector | Claims | Verdict mix |
|---|---:|---|
| Insurance | 34 | `VERIFIED=31 INSUFFICIENT_EVIDENCE=3` |
| Banking | 32 | `VERIFIED=28 WRONG_MATH=4` |
| Utility | 26 | `VERIFIED=16 INSUFFICIENT_EVIDENCE=8 WRONG_MATH=2` |
| Software | 22 | `VERIFIED=20 INSUFFICIENT_EVIDENCE=2` |
| Industrials | 17 | `VERIFIED=15 INSUFFICIENT_EVIDENCE=2` |
| REIT | 13 | `VERIFIED=10 INSUFFICIENT_EVIDENCE=3` |
| REIT (residential) | 12 | `VERIFIED=5 INSUFFICIENT_EVIDENCE=7` |
| Semiconductors | 10 | `VERIFIED=8 INSUFFICIENT_EVIDENCE=2` |
| Aerospace/Defense | 8 | `VERIFIED=7 INSUFFICIENT_EVIDENCE=1` |
| Software (growth) | 8 | `VERIFIED=5 INSUFFICIENT_EVIDENCE=2 WRONG_MATH=1` |
| Automotive | 7 | `VERIFIED=5 INSUFFICIENT_EVIDENCE=2` |
| Industrials (spinoff) | 7 | `VERIFIED=5 INSUFFICIENT_EVIDENCE=1 WRONG_MATH=1` |
| REIT (data center) | 7 | `VERIFIED=4 INSUFFICIENT_EVIDENCE=3` |
| Energy | 6 | `VERIFIED=6` |
| Insurance (life) | 6 | `VERIFIED=4 INSUFFICIENT_EVIDENCE=2` |
| Transportation (airline) | 6 | `VERIFIED=5 INSUFFICIENT_EVIDENCE=1` |
| Consumer Staples | 5 | `VERIFIED=4 INSUFFICIENT_EVIDENCE=1` |
| Pharma | 5 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=2` |
| Telecom | 5 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=2 WRONG_MATH=1` |
| Automotive (growth) | 4 | `VERIFIED=4` |
| Consumer (spinoff) | 4 | `VERIFIED=4` |
| Consumer Electronics | 4 | `VERIFIED=4` |
| E-commerce (mid-cap) | 4 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=1 WRONG_MATH=1` |
| E-commerce (smaller) | 4 | `VERIFIED=4` |
| Financial (brokerage) | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Fintech (mortgage) | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Fintech (smaller) | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Healthcare | 4 | `VERIFIED=4` |
| Healthcare (managed care) | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Healthcare (spinoff) | 4 | `VERIFIED=4` |
| Media | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Media/Streaming | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Networking | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| REIT (gaming) | 4 | `VERIFIED=4` |
| REIT (timber) | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| REIT (towers) | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Streaming (mid-cap) | 4 | `VERIFIED=4` |
| Transportation (rail) | 4 | `VERIFIED=3 INSUFFICIENT_EVIDENCE=1` |
| Aerospace | 3 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=1` |
| Aerospace (mid-cap) | 3 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=1` |
| Automotive (smaller) | 3 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=1` |
| E-commerce/Cloud | 3 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=1` |
| Healthcare (hospitals) | 3 | `VERIFIED=3` |
| Homebuilding | 3 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=1` |
| REIT (healthcare) | 3 | `VERIFIED=1 INSUFFICIENT_EVIDENCE=2` |
| REIT (office) | 3 | `VERIFIED=2 INSUFFICIENT_EVIDENCE=1` |
| REIT (self-storage) | 3 | `VERIFIED=3` |
| Retail | 3 | `VERIFIED=3` |
| Retail (smaller) | 3 | `VERIFIED=3` |
| Transportation (parcel) | 3 | `VERIFIED=3` |
| Logistics | 2 | `VERIFIED=2` |
| REIT (specialty) | 2 | `VERIFIED=2` |
| Conglomerate | 1 | `VERIFIED=1` |
| Insurance/Conglomerate | 1 | `VERIFIED=1` |

## WRONG_MATH root-cause queue

These are deterministic XBRL-lane EPS convictions, not human-adjudicated filer errors. They require accounting-scope review before being counted as true issuer mistakes.

| Ticker | Sector | Rule | Stated | Numerator | Shares | Computed | Root cause |
|---|---|---|---:|---:|---:|---:|---|
| BAC | Banking | eps_reconciliation | 3.81 | 29055000000.0 | 7680900000.0 | 3.7828 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| GS | Banking | eps_reconciliation | 51.95 | 16300000000.0 | 312700000.0 | 52.1266 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| T | Telecom | eps_reconciliation | 3.04 | 21889000000.0 | 7169000000.0 | 3.0533 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| DUK | Utility | eps_reconciliation | 6.31 | 4912000000.0 | 777000000.0 | 6.3218 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| DUK | Utility | eps_reconciliation | 6.31 | 4912000000.0 | 777000000.0 | 6.3218 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| ETSY | E-commerce (mid-cap) | eps_reconciliation | 1.39 | 162982000.0 | 124114000.0 | 1.3132 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| DDOG | Software (growth) | eps_reconciliation | 0.31 | 107741000.0 | 363472000.0 | 0.2964 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| GEV | Industrials (spinoff) | eps_reconciliation | 17.92 | 4884000000.0 | 272000000.0 | 17.9559 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| NTRS | Banking | eps_reconciliation | 8.78 | 1695100000.0 | 191358026.0 | 8.8583 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |
| NTRS | Banking | eps_reconciliation | 8.74 | 1695100000.0 | 192246525.0 | 8.8173 | EPS XBRL operands do not reconcile within existing per-share rounding tolerance; requires accounting-scope review before treating as filer error. |

## Honest boundary

- This is an expanded deterministic XBRL benchmark because no live LLM provider key was available to create new prose-extraction caches.
- The existing 83-filer prose-extraction benchmark remains separately represented by `REPORT_LATEST.md`; this report expands the SEC-companyfacts lane to 115 US 10-K filers / 354 claims.
- ADR/20-F/40-F issuers remain out of scope; current companyfacts extraction is US-GAAP 10-K/10-Q centered.
- No-claim filers: FOXA.
