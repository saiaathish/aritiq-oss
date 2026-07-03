# AI Analyst Mode — measurement report

Generated 2026-07-02 05:20 UTC from replay run `run_1782915651.json` (78 filers, 234 question/filer pairs).

## Deterministic boundary sweep (no model needed)

- Outcomes: {'answered': 136, 'refused_blocked': 75, 'refused_no_data': 23}
- Blocked-only topics correctly refused pre-model: **72/72** (the at-scale adversarial test; every one is a real filer whose only relevant verdicts did not pass verification)
- Refusals named these blocking statuses: {'INSUFFICIENT_EVIDENCE': 71, 'UNSUPPORTED_NUMBER': 10}
- Hard-gate failures: **0**

## Live narration (real model through the same guards)

- AAPL — 'Does the balance sheet balance?' → **answered** (model_called=True, citations=['F1']): “Yes, the balance sheet balances as the check passed on the operands 359241.0, 285508.0, and 73733.0.”
- AAPL — 'Does the reported EPS reconcile with net income and share count?' → **refused_blocked** (model_called=False): Refused before any model call: the question concerns eps_reconciliation, whose claims did not pass verification (INSUFFICIENT_EVIDENCE). A v
- JPM — 'Does the balance sheet balance?' → **answered** (model_called=True, citations=['F1']): “Yes, the balance sheet balances as the check passed [F1].”
- PLTR — 'Does the reported EPS reconcile with net income and share count?' → **answered** (model_called=True, citations=['F2', 'F3']): “Yes, the reported EPS reconciles with net income and share count as indicated by the eps_reconciliation checks passed for 0.69 based on 1625”
- TSLA — 'Does the cash flow statement tie out to balance sheet cash?' → **refused_blocked** (model_called=False): Refused before any model call: the question concerns cash_flow_tie_out, whose claims did not pass verification (INSUFFICIENT_EVIDENCE). A ve

## Per-filer outcomes

| Ticker | balance sheet Q | EPS Q | cash Q |
|---|---|---|---|
| AMD | answered | answered | refused_blocked |
| PLTR | answered | answered | refused_no_data |
| AAPL | answered | refused_blocked | refused_blocked |
| MSFT | answered | answered | answered |
| NVDA | answered | answered | answered |
| TSLA | answered | answered | refused_blocked |
| GOOGL | answered | answered | answered |
| AMZN | refused_blocked | answered | refused_blocked |
| META | answered | answered | refused_blocked |
| INTC | answered | answered | refused_blocked |
| JPM | answered | refused_blocked | refused_no_data |
| BAC | answered | answered | refused_no_data |
| WFC | answered | answered | refused_no_data |
| GS | answered | refused_no_data | answered |
| KO | answered | answered | refused_blocked |
| PG | answered | refused_no_data | refused_blocked |
| JNJ | answered | answered | answered |
| PFE | answered | answered | refused_no_data |
| MRK | refused_blocked | refused_blocked | refused_blocked |
| XOM | answered | answered | refused_blocked |
| CVX | answered | refused_blocked | refused_blocked |
| BA | answered | refused_blocked | answered |
| GE | answered | refused_blocked | refused_no_data |
| DIS | answered | answered | refused_blocked |
| NFLX | answered | answered | refused_blocked |
| CRM | answered | answered | answered |
| ORCL | answered | answered | answered |
| CSCO | answered | answered | refused_blocked |
| T | refused_blocked | answered | refused_blocked |
| VZ | answered | answered | refused_blocked |
| PGR | answered | refused_no_data | refused_no_data |
| MET | answered | refused_blocked | answered |
| AIG | answered | refused_blocked | refused_no_data |
| PLD | answered | answered | answered |
| AMT | refused_no_data | refused_no_data | refused_no_data |
| SPG | refused_blocked | answered | refused_blocked |
| O | answered | answered | refused_blocked |
| NEE | answered | refused_blocked | refused_blocked |
| DUK | answered | refused_blocked | refused_no_data |
| SO | refused_no_data | answered | refused_blocked |
| HON | answered | refused_blocked | answered |
| RTX | answered | answered | refused_blocked |
| F | answered | refused_no_data | refused_blocked |
| ETSY | answered | answered | refused_blocked |
| RIVN | answered | answered | refused_blocked |
| ROKU | answered | answered | refused_blocked |
| DDOG | answered | answered | answered |
| U | refused_blocked | answered | refused_blocked |
| EQIX | answered | refused_blocked | refused_blocked |
| DLR | answered | answered | refused_blocked |
| VICI | answered | refused_blocked | refused_blocked |
| WELL | refused_blocked | answered | refused_blocked |
| AVB | answered | refused_blocked | refused_blocked |
| BXP | answered | answered | refused_blocked |
| CCI | answered | answered | refused_blocked |
| TRV | answered | refused_blocked | refused_blocked |
| ALL | answered | answered | answered |
| PRU | refused_blocked | refused_blocked | refused_blocked |
| AFL | answered | refused_no_data | answered |
| CB | answered | refused_no_data | refused_no_data |
| SCHW | answered | answered | refused_blocked |
| HEI | answered | answered | answered |
| LEN | answered | refused_no_data | refused_blocked |
| UHAL | answered | refused_no_data | answered |
| SOLV | answered | answered | answered |
| KVUE | answered | answered | answered |
| CARR | answered | refused_blocked | refused_blocked |
| FOXA | answered | refused_no_data | answered |
| PSKY | answered | answered | answered |
| BBWI | answered | answered | answered |
| W | answered | answered | refused_blocked |
| CVNA | answered | refused_blocked | refused_blocked |
| AFRM | answered | refused_blocked | refused_blocked |
| RKT | answered | refused_blocked | refused_blocked |
| UNH | answered | answered | answered |
| UNP | answered | answered | refused_blocked |
| DAL | answered | refused_blocked | refused_blocked |
| UPS | refused_blocked | refused_blocked | refused_blocked |

## Honest boundary

- The sweep proves the BOUNDARY (refuse on blocked, cite on answer, whitelist on numbers) over real verdicts. The stub's prose is trivial by design; prose quality is a model property, not a guarantee this system makes.
- `answered` here means the topic had verified facts and the cited answer passed the whitelist — not that the answer is insightful.
- Relevance matching is deterministic keyword/overlap (v1); a question phrased entirely without topic words would refuse as no-data rather than risk a wrong route. That failure mode is closed-world by construction.
