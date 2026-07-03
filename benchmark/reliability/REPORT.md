# Aritiq Reliability Report

- **Mode:** `replay`
- **Filings:** 78 (78 with extraction)
- **In-scope claims:** 231
- **Run:** 2026-07-01T00:15:51Z → 2026-07-01T00:15:51Z

> Counts are observations from this run. No real-filing accuracy is claimed; FP/FN adjudication requires the human review CSV.

## Verdict distribution

| Verdict | Count |
|---|---|
| VERIFIED | 157 |
| INSUFFICIENT_EVIDENCE | 60 |
| WRONG_MATH | 10 |
| UNSUPPORTED_NUMBER | 4 |

## Evidence-flag emission by rule

Low emission means correct math is wrongly gated to INSUFFICIENT_EVIDENCE.

| Rule | Emitted / Total | Rate |
|---|---|---|
| balance_sheet_identity | 78/78 | 100% |
| cash_flow_tie_out | 70/70 | 100% |
| eps_reconciliation | 83/83 | 100% |

## Failure taxonomy (auto-bucketed)

| Count | Bucket | Owner |
|---|---|---|
| 157 | `auto:true_positive_candidate` | —(verified) |
| 60 | `verifier_gate_fired:by_design` | verifier(by_design) |
| 10 | `auto:NEEDS_REVIEW_HIGH(conviction)` | —(needs_human) |
| 4 | `extraction_failure:missing_operand` | extraction |

## Per-filing

| Ticker | Company | Source | Claims | Verdicts |
|---|---|---|---|---|
| AMD | ADVANCED MICRO DEVICES INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| PLTR | Palantir Technologies Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| AAPL | Apple Inc. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=3 VERIFIED=1 |
| MSFT | MICROSOFT CORP | replay-cache | 3 | VERIFIED=3 |
| NVDA | NVIDIA CORP | replay-cache | 4 | VERIFIED=4 |
| TSLA | Tesla, Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| GOOGL | Alphabet Inc. | replay-cache | 4 | VERIFIED=4 |
| AMZN | AMAZON COM INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=2 VERIFIED=2 |
| META | Meta Platforms, Inc. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| INTC | INTEL CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| JPM | JPMORGAN CHASE & CO | replay-cache | 2 | VERIFIED=1 WRONG_MATH=1 |
| BAC | BANK OF AMERICA CORP /DE/ | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| WFC | WELLS FARGO & COMPANY/MN | replay-cache | 0 |  |
| GS | GOLDMAN SACHS GROUP INC | replay-cache | 2 | VERIFIED=2 |
| KO | COCA COLA CO | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| PG | PROCTER & GAMBLE Co | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| JNJ | JOHNSON & JOHNSON | replay-cache | 3 | VERIFIED=3 |
| PFE | PFIZER INC | replay-cache | 3 | VERIFIED=3 |
| MRK | Merck & Co., Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 UNSUPPORTED_NUMBER=1 VERIFIED=1 |
| XOM | EXXON MOBIL CORP | replay-cache | 3 | VERIFIED=3 |
| CVX | CHEVRON CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| BA | BOEING CO | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 UNSUPPORTED_NUMBER=1 VERIFIED=1 |
| GE | GENERAL ELECTRIC CO | replay-cache | 2 | VERIFIED=2 |
| DIS | Walt Disney Co | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| NFLX | NETFLIX INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| CRM | Salesforce, Inc. | replay-cache | 4 | VERIFIED=4 |
| ORCL | ORACLE CORP | replay-cache | 4 | VERIFIED=4 |
| CSCO | CISCO SYSTEMS, INC. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| T | AT&T INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| VZ | VERIZON COMMUNICATIONS INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| BRK-B | BERKSHIRE HATHAWAY INC | replay-cache | 0 |  |
| PGR | PROGRESSIVE CORP/OH/ | replay-cache | 1 | VERIFIED=1 |
| MET | METLIFE INC | replay-cache | 3 | UNSUPPORTED_NUMBER=1 VERIFIED=2 |
| AIG | AMERICAN INTERNATIONAL GROUP, INC. | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| PLD | Prologis, Inc. | replay-cache | 3 | VERIFIED=3 |
| AMT | AMERICAN TOWER CORP /MA/ | replay-cache | 1 | VERIFIED=1 |
| SPG | SIMON PROPERTY GROUP INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| O | REALTY INCOME CORP | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| NEE | NEXTERA ENERGY INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 WRONG_MATH=1 |
| DUK | Duke Energy CORP | replay-cache | 2 | VERIFIED=1 WRONG_MATH=1 |
| SO | SOUTHERN CO | replay-cache | 6 | INSUFFICIENT_EVIDENCE=4 VERIFIED=1 WRONG_MATH=1 |
| CAT | CATERPILLAR INC | replay-cache | 0 |  |
| HON | HONEYWELL INTERNATIONAL INC | replay-cache | 3 | VERIFIED=2 WRONG_MATH=1 |
| RTX | RTX Corp | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| F | FORD MOTOR CO | replay-cache | 2 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 |
| ETSY | ETSY INC | replay-cache | 4 | INSUFFICIENT_EVIDENCE=1 VERIFIED=3 |
| RIVN | Rivian Automotive, Inc. / DE | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| ROKU | ROKU, INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| DDOG | Datadog, Inc. | replay-cache | 4 | VERIFIED=3 WRONG_MATH=1 |
| U | Unity Software Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| EQIX | EQUINIX INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| DLR | DIGITAL REALTY TRUST, INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| VICI | VICI PROPERTIES INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| WELL | WELLTOWER INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 WRONG_MATH=1 |
| AVB | AVALONBAY COMMUNITIES INC | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| BXP | BXP, Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| CCI | CROWN CASTLE INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=2 |
| TRV | TRAVELERS COMPANIES, INC. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 WRONG_MATH=1 |
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
| CARR | CARRIER GLOBAL Corp | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 WRONG_MATH=1 |
| FOXA | Fox Corp | replay-cache | 4 | VERIFIED=4 |
| PSKY | Paramount Skydance Corp | replay-cache | 3 | VERIFIED=3 |
| BBWI | Bath & Body Works, Inc. | replay-cache | 5 | VERIFIED=5 |
| W | Wayfair Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=1 VERIFIED=1 WRONG_MATH=1 |
| CVNA | CARVANA CO. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |
| AFRM | Affirm Holdings, Inc. | replay-cache | 4 | INSUFFICIENT_EVIDENCE=3 VERIFIED=1 |
| RKT | Rocket Companies, Inc. | replay-cache | 3 | INSUFFICIENT_EVIDENCE=2 VERIFIED=1 |

## Prioritized fix list (pre-deployment)

- [P1 review] 10 WRONG_MATH conviction(s). Manually confirm each is a real arithmetic disagreement with complete, correctly-scoped operands before shipping — a single false conviction is the worst-case failure.
- [P3 extraction] No claims carried graph dependencies (depends_on). Cross-statement claims are leaf-level by nature, so this is expected here; revisit only when the summary-audit pass (derived figures) is added to this harness.