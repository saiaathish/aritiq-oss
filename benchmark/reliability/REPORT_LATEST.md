# Aritiq Reliability Report

- **Mode:** `replay`
- **Filings:** 83 (83 with extraction)
- **In-scope claims:** 238
- **Run:** 2026-07-01T14:20:50Z → 2026-07-01T14:20:51Z

> Counts are observations from this run. No real-filing accuracy is claimed; FP/FN adjudication requires the human review CSV.

## Verdict distribution

| Verdict | Count |
|---|---|
| VERIFIED | 159 |
| INSUFFICIENT_EVIDENCE | 70 |
| UNSUPPORTED_NUMBER | 9 |

## Evidence-flag emission by rule

Low emission means correct math is wrongly gated to INSUFFICIENT_EVIDENCE.

| Rule | Emitted / Total | Rate |
|---|---|---|
| balance_sheet_identity | 81/81 | 100% |
| cash_flow_tie_out | 72/72 | 100% |
| eps_reconciliation | 85/85 | 100% |

## Breakdown by statement type

Share of in-scope claims by verdict, aggregated across all sectors. Aggregation only — no verdict is recomputed. `%X-miss` = UNSUPPORTED_NUMBER (missing operand); `WRONG_MATH` convictions are shown as a raw count and never folded into a percentage.

| Statement type | N | % verified | % insufficient-evidence | % extraction-miss | WRONG_MATH |
|---|---|---|---|---|---|
| eps_reconciliation | 85 | 69.4% | 21.2% | 9.4% | 0 |
| balance_sheet_identity | 81 | 90.1% | 8.6% | 1.2% | 0 |
| cash_flow_tie_out | 72 | 37.5% | 62.5% | 0.0% | 0 |

## Breakdown by sector

Share of in-scope claims by verdict, grouped by the filer's sector. Aggregation only.

| Sector | N | % verified | % insufficient-evidence | % extraction-miss | WRONG_MATH |
|---|---|---|---|---|---|
| Software | 20 | 95.0% | 5.0% | 0.0% | 0 |
| Insurance | 17 | 76.5% | 17.6% | 5.9% | 0 |
| Utility | 12 | 33.3% | 66.7% | 0.0% | 0 |
| Media | 11 | 90.9% | 9.1% | 0.0% | 0 |
| REIT | 10 | 80.0% | 20.0% | 0.0% | 0 |
| Semiconductors | 10 | 80.0% | 20.0% | 0.0% | 0 |
| Banking | 9 | 77.8% | 22.2% | 0.0% | 0 |
| Software (growth) | 7 | 57.1% | 42.9% | 0.0% | 0 |
| Automotive | 6 | 66.7% | 33.3% | 0.0% | 0 |
| Energy | 6 | 50.0% | 33.3% | 16.7% | 0 |
| REIT (data center) | 6 | 50.0% | 50.0% | 0.0% | 0 |
| Telecom | 6 | 50.0% | 50.0% | 0.0% | 0 |
| Consumer Staples | 5 | 60.0% | 40.0% | 0.0% | 0 |
| Industrials | 5 | 60.0% | 20.0% | 20.0% | 0 |
| Pharma | 5 | 40.0% | 20.0% | 40.0% | 0 |
| Retail (smaller) | 5 | 100.0% | 0.0% | 0.0% | 0 |
| Aerospace (mid-cap) | 4 | 100.0% | 0.0% | 0.0% | 0 |
| Aerospace/Defense | 4 | 75.0% | 25.0% | 0.0% | 0 |
| E-commerce (mid-cap) | 4 | 75.0% | 25.0% | 0.0% | 0 |
| Fintech (smaller) | 4 | 25.0% | 75.0% | 0.0% | 0 |
| Healthcare (managed care) | 4 | 100.0% | 0.0% | 0.0% | 0 |
| Healthcare (spinoff) | 4 | 100.0% | 0.0% | 0.0% | 0 |
| Logistics | 4 | 100.0% | 0.0% | 0.0% | 0 |
| Aerospace | 3 | 66.7% | 0.0% | 33.3% | 0 |
| Automotive (growth) | 3 | 66.7% | 33.3% | 0.0% | 0 |
| Automotive (smaller) | 3 | 33.3% | 66.7% | 0.0% | 0 |
| Consumer (spinoff) | 3 | 100.0% | 0.0% | 0.0% | 0 |
| Consumer Electronics | 3 | 33.3% | 66.7% | 0.0% | 0 |
| E-commerce (smaller) | 3 | 66.7% | 33.3% | 0.0% | 0 |
| E-commerce/Cloud | 3 | 66.7% | 33.3% | 0.0% | 0 |
| Financial (brokerage) | 3 | 66.7% | 33.3% | 0.0% | 0 |
| Fintech (mortgage) | 3 | 33.3% | 66.7% | 0.0% | 0 |
| Healthcare | 3 | 100.0% | 0.0% | 0.0% | 0 |
| Industrials (spinoff) | 3 | 33.3% | 66.7% | 0.0% | 0 |
| Media/Streaming | 3 | 66.7% | 33.3% | 0.0% | 0 |
| Networking | 3 | 66.7% | 33.3% | 0.0% | 0 |
| REIT (gaming) | 3 | 33.3% | 66.7% | 0.0% | 0 |
| REIT (healthcare) | 3 | 33.3% | 66.7% | 0.0% | 0 |
| REIT (office) | 3 | 66.7% | 33.3% | 0.0% | 0 |
| REIT (residential) | 3 | 33.3% | 66.7% | 0.0% | 0 |
| REIT (towers) | 3 | 66.7% | 33.3% | 0.0% | 0 |
| Streaming (mid-cap) | 3 | 66.7% | 33.3% | 0.0% | 0 |
| Transportation (airline) | 3 | 33.3% | 33.3% | 33.3% | 0 |
| Transportation (parcel) | 3 | 0.0% | 66.7% | 33.3% | 0 |
| Transportation (rail) | 3 | 66.7% | 33.3% | 0.0% | 0 |
| Homebuilding | 2 | 50.0% | 50.0% | 0.0% | 0 |
| Insurance (life) | 2 | 0.0% | 50.0% | 50.0% | 0 |

## Failure taxonomy (auto-bucketed)

| Count | Bucket | Owner |
|---|---|---|
| 159 | `auto:true_positive_candidate` | —(verified) |
| 70 | `verifier_gate_fired:by_design` | verifier(by_design) |
| 9 | `extraction_failure:missing_operand` | extraction |

## Per-filing

| Ticker | Company | Source | Claims | Verdicts |
|---|---|---|---|---|
| AMD | ADVANCED MICRO DEVICES INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| PLTR | Palantir Technologies Inc. | replay-cache | 3 | VERIFIED=3 |
| AAPL | Apple Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| MSFT | MICROSOFT CORP | replay-cache | 3 | VERIFIED=3 |
| NVDA | NVIDIA CORP | replay-cache | 3 | VERIFIED=3 |
| TSLA | Tesla, Inc. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| GOOGL | Alphabet Inc. | replay-cache | 3 | VERIFIED=3 |
| AMZN | AMAZON COM INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| META | Meta Platforms, Inc. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| INTC | INTEL CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| JPM | JPMORGAN CHASE & CO | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| BAC | BANK OF AMERICA CORP /DE/ | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| WFC | WELLS FARGO & COMPANY/MN | replay-cache | 2 | VERIFIED=2 |
| GS | GOLDMAN SACHS GROUP INC | replay-cache | 2 | VERIFIED=2 |
| KO | COCA COLA CO | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| PG | PROCTER & GAMBLE Co | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| JNJ | JOHNSON & JOHNSON | replay-cache | 3 | VERIFIED=3 |
| PFE | PFIZER INC | replay-cache | 2 | VERIFIED=2 |
| MRK | Merck & Co., Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 UNSUPPORTED_NUMBER=2 |
| XOM | EXXON MOBIL CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| CVX | CHEVRON CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 UNSUPPORTED_NUMBER=1 VERIFIED=1 |
| BA | BOEING CO | replay-cache | 3 | UNSUPPORTED_NUMBER=1 VERIFIED=2 |
| GE | GENERAL ELECTRIC CO | replay-cache | 2 | UNSUPPORTED_NUMBER=1 VERIFIED=1 |
| DIS | Walt Disney Co | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| NFLX | NETFLIX INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| CRM | Salesforce, Inc. | replay-cache | 3 | VERIFIED=3 |
| ORCL | ORACLE CORP | replay-cache | 4 | VERIFIED=4 |
| CSCO | CISCO SYSTEMS, INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| T | AT&T INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| VZ | VERIZON COMMUNICATIONS INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| BRK-B | BERKSHIRE HATHAWAY INC | replay-cache | 0 |  |
| PGR | PROGRESSIVE CORP/OH/ | replay-cache | 1 | VERIFIED=1 |
| MET | METLIFE INC | replay-cache | 3 | UNSUPPORTED_NUMBER=1 VERIFIED=2 |
| AIG | AMERICAN INTERNATIONAL GROUP, INC. | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| PLD | Prologis, Inc. | replay-cache | 3 | VERIFIED=3 |
| AMT | AMERICAN TOWER CORP /MA/ | replay-cache | 1 | VERIFIED=1 |
| SPG | SIMON PROPERTY GROUP INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| O | REALTY INCOME CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| NEE | NEXTERA ENERGY INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=2 VERIFIED=2 |
| DUK | Duke Energy CORP | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| SO | SOUTHERN CO | replay-cache | 6 | INSUFFICIENT_EVIDENCE=5 VERIFIED=1 |
| CAT | CATERPILLAR INC | replay-cache | 0 |  |
| HON | HONEYWELL INTERNATIONAL INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| RTX | RTX Corp | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| F | FORD MOTOR CO | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| ETSY | ETSY INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| RIVN | Rivian Automotive, Inc. / DE | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| ROKU | ROKU, INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| DDOG | Datadog, Inc. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| U | Unity Software Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| EQIX | EQUINIX INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| DLR | DIGITAL REALTY TRUST, INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| VICI | VICI PROPERTIES INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| WELL | WELLTOWER INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| AVB | AVALONBAY COMMUNITIES INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| BXP | BXP, Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| CCI | CROWN CASTLE INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| TRV | TRAVELERS COMPANIES, INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| ALL | ALLSTATE CORP | replay-cache | 4 | VERIFIED=4 |
| PRU | PRUDENTIAL FINANCIAL INC | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 UNSUPPORTED_NUMBER=1 |
| AFL | AFLAC INC | replay-cache | 2 | VERIFIED=2 |
| CB | Chubb Ltd | replay-cache | 2 | VERIFIED=2 |
| SCHW | SCHWAB CHARLES CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| BRK-A | BERKSHIRE HATHAWAY INC | replay-cache | 0 |  |
| HEI | HEICO CORP | replay-cache | 4 | VERIFIED=4 |
| LEN | LENNAR CORP /NEW/ | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| UHAL | U-Haul Holding Co /NV/ | replay-cache | 4 | VERIFIED=4 |
| GEV | GE Vernova Inc. | replay-cache | 0 |  |
| SOLV | Solventum Corp | replay-cache | 4 | VERIFIED=4 |
| KVUE | Kenvue Inc. | replay-cache | 3 | VERIFIED=3 |
| CARR | CARRIER GLOBAL Corp | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| FOXA | Fox Corp | replay-cache | 4 | VERIFIED=4 |
| PSKY | Paramount Skydance Corp | replay-cache | 3 | VERIFIED=3 |
| BBWI | Bath & Body Works, Inc. | replay-cache | 5 | VERIFIED=5 |
| W | Wayfair Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| CVNA | CARVANA CO. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| AFRM | Affirm Holdings, Inc. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=3 VERIFIED=1 |
| RKT | Rocket Companies, Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| UNH | UNITEDHEALTH GROUP INC | replay-cache | 4 | VERIFIED=4 |
| HCA | HCA Healthcare, Inc. | replay-cache | 0 |  |
| UNP | UNION PACIFIC CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| DAL | DELTA AIR LINES, INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 UNSUPPORTED_NUMBER=1 VERIFIED=1 |
| UPS | UNITED PARCEL SERVICE INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 UNSUPPORTED_NUMBER=1 |

## Prioritized fix list (pre-deployment)

- [P3 extraction] No claims carried graph dependencies (depends_on). Cross-statement claims are leaf-level by nature, so this is expected here; revisit only when the summary-audit pass (derived figures) is added to this harness.