# SEC Filing Timeline — measurement report

Generated 2026-07-02 05:03 UTC over the reliability filing set.

- Filers attempted: **83**
- Timelines built: **83/83**
- Total events sequenced: **126492** (recent window per filer; spans 1994-02-11 → 2026-07-01)
- Integrity-gate failures: **0**

## Events by form (top 12)

| Form | Count |
|---|---|
| 424B2 | 47502 |
| 4 | 42752 |
| 8-K | 7837 |
| 144 | 5583 |
| FWP | 3595 |
| SC 13G/A | 1792 |
| 10-Q | 1779 |
| 424B3 | 1458 |
| 3 | 1438 |
| DEFA14A | 1305 |
| 424B5 | 899 |
| 11-K | 748 |

## Events by verification coverage

The load-bearing table: what Aritiq actually verifies per filing type.

| Coverage | Events | Meaning |
|---|---|---|
| full_financial_verification | 2375 | 10-K/10-Q — measured financial verification |
| partial_financial_verification | 2407 | 8-K with Item 2.02 earnings exhibit — experimental/partial |
| ownership_data_only | 42752 | Form 4 — parsed insider transactions, not financially verified |
| listed_only | 78958 | dated entry + EDGAR link only, NO verification |

## Independent spot-check (submissions JSON vs browse-edgar Atom)

- PASS AAPL: latest 10-K agrees on both SEC endpoints: 0000320193-25-000079 filed 2025-10-31
- PASS JPM: latest 10-K agrees on both SEC endpoints: 0001628280-26-008131 filed 2026-02-13
- PASS WELL: latest 10-K agrees on both SEC endpoints: 0000766704-26-000010 filed 2026-02-12

## Per-filer detail

| Ticker | Events | 10-K | 10-Q | 8-K | 8-K w/2.02 | Form 4 | DEF 14A | older archives |
|---|---|---|---|---|---|---|---|---|
| AMD | 1000 | 9 | 27 | 109 | 38 | 626 | 9 | yes |
| PLTR | 971 | 6 | 17 | 43 | 23 | 503 | 7 | no |
| AAPL | 1000 | 11 | 33 | 104 | 45 | 589 | 11 | yes |
| MSFT | 1003 | 6 | 19 | 65 | 25 | 730 | 6 | yes |
| NVDA | 1001 | 6 | 18 | 60 | 25 | 565 | 7 | yes |
| TSLA | 1001 | 8 | 25 | 125 | 67 | 454 | 8 | yes |
| GOOGL | 1004 | 3 | 9 | 40 | 12 | 525 | 3 | yes |
| AMZN | 1004 | 6 | 18 | 64 | 24 | 526 | 6 | yes |
| META | 1002 | 2 | 6 | 22 | 8 | 544 | 2 | yes |
| INTC | 1001 | 7 | 22 | 121 | 30 | 626 | 8 | yes |
| JPM | 25252 | 1 | 3 | 25 | 4 | 136 | 1 | yes |
| BAC | 11464 | 1 | 3 | 13 | 4 | 142 | 1 | yes |
| WFC | 1000 | 2 | 5 | 34 | 6 | 188 | 2 | yes |
| GS | 14794 | 1 | 3 | 17 | 5 | 70 | 1 | yes |
| KO | 1003 | 8 | 25 | 111 | 33 | 565 | 8 | yes |
| PG | 1000 | 4 | 15 | 88 | 19 | 601 | 4 | yes |
| JNJ | 1001 | 8 | 25 | 99 | 36 | 484 | 9 | yes |
| PFE | 1004 | 6 | 16 | 60 | 25 | 715 | 6 | yes |
| MRK | 1000 | 8 | 25 | 67 | 34 | 650 | 9 | yes |
| XOM | 1001 | 7 | 19 | 107 | 26 | 306 | 6 | yes |
| CVX | 1000 | 7 | 22 | 99 | 32 | 506 | 8 | yes |
| BA | 1001 | 7 | 22 | 107 | 31 | 639 | 8 | yes |
| GE | 1000 | 8 | 22 | 123 | 33 | 573 | 8 | yes |
| DIS | 1003 | 6 | 20 | 88 | 26 | 501 | 5 | yes |
| NFLX | 1004 | 3 | 10 | 29 | 13 | 695 | 4 | yes |
| CRM | 1003 | 3 | 9 | 29 | 12 | 786 | 3 | yes |
| ORCL | 1002 | 11 | 31 | 94 | 43 | 582 | 10 | yes |
| CSCO | 1006 | 6 | 20 | 78 | 26 | 554 | 6 | yes |
| T | 1005 | 4 | 13 | 67 | 17 | 759 | 4 | yes |
| VZ | 1004 | 3 | 8 | 54 | 11 | 755 | 3 | yes |
| BRK-B | 1001 | 10 | 29 | 73 | 34 | 271 | 10 | yes |
| PGR | 1000 | 5 | 13 | 66 | 17 | 741 | 5 | yes |
| MET | 1000 | 6 | 16 | 112 | 31 | 617 | 6 | yes |
| AIG | 1002 | 6 | 16 | 108 | 22 | 686 | 6 | yes |
| PLD | 1001 | 8 | 22 | 121 | 30 | 699 | 8 | yes |
| AMT | 1000 | 9 | 28 | 232 | 37 | 475 | 10 | yes |
| SPG | 1004 | 12 | 36 | 112 | 47 | 636 | 12 | yes |
| O | 1000 | 11 | 34 | 221 | 47 | 438 | 11 | yes |
| NEE | 1000 | 8 | 22 | 153 | 30 | 491 | 8 | yes |
| DUK | 1003 | 8 | 22 | 142 | 29 | 599 | 8 | yes |
| SO | 1012 | 6 | 16 | 95 | 23 | 661 | 6 | yes |
| CAT | 1002 | 7 | 22 | 99 | 30 | 650 | 8 | yes |
| HON | 1010 | 6 | 19 | 109 | 32 | 660 | 7 | yes |
| RTX | 1001 | 9 | 27 | 114 | 35 | 499 | 9 | yes |
| F | 1002 | 7 | 21 | 171 | 29 | 627 | 7 | yes |
| ETSY | 1000 | 8 | 25 | 78 | 35 | 668 | 8 | yes |
| RIVN | 507 | 5 | 14 | 77 | 20 | 256 | 5 | no |
| ROKU | 1000 | 8 | 22 | 74 | 31 | 588 | 8 | yes |
| DDOG | 1001 | 4 | 11 | 24 | 15 | 498 | 5 | yes |
| U | 922 | 6 | 17 | 69 | 25 | 469 | 6 | no |
| EQIX | 1000 | 7 | 19 | 117 | 26 | 523 | 7 | yes |
| DLR | 1002 | 9 | 26 | 193 | 37 | 553 | 9 | yes |
| VICI | 776 | 9 | 26 | 148 | 35 | 370 | 9 | no |
| WELL | 1001 | 12 | 34 | 169 | 60 | 522 | 12 | yes |
| AVB | 1008 | 11 | 34 | 119 | 45 | 595 | 12 | yes |
| BXP | 1006 | 10 | 30 | 81 | 39 | 732 | 10 | yes |
| CCI | 1001 | 10 | 31 | 219 | 44 | 450 | 10 | yes |
| TRV | 1006 | 8 | 25 | 63 | 35 | 624 | 9 | yes |
| ALL | 1004 | 9 | 25 | 185 | 41 | 542 | 9 | yes |
| PRU | 1003 | 5 | 15 | 94 | 26 | 517 | 5 | yes |
| AFL | 1003 | 10 | 29 | 107 | 39 | 570 | 10 | yes |
| CB | 1001 | 8 | 25 | 84 | 38 | 627 | 10 | yes |
| SCHW | 1001 | 5 | 16 | 66 | 21 | 630 | 6 | yes |
| BRK-A | 1001 | 10 | 29 | 73 | 34 | 271 | 10 | yes |
| HEI | 1000 | 17 | 53 | 126 | 71 | 500 | 18 | yes |
| LEN | 1007 | 11 | 34 | 139 | 47 | 541 | 11 | yes |
| UHAL | 975 | 33 | 97 | 196 | 20 | 240 | 32 | no |
| GEV | 205 | 2 | 7 | 17 | 8 | 97 | 2 | no |
| SOLV | 254 | 2 | 7 | 29 | 9 | 123 | 2 | no |
| KVUE | 485 | 3 | 10 | 30 | 13 | 245 | 3 | no |
| CARR | 555 | 6 | 19 | 85 | 25 | 249 | 6 | no |
| FOXA | 629 | 7 | 23 | 71 | 30 | 337 | 7 | no |
| PSKY | 188 | 1 | 4 | 21 | 3 | 48 | 0 | no |
| BBWI | 1002 | 13 | 38 | 185 | 84 | 530 | 13 | yes |
| W | 1000 | 6 | 19 | 77 | 25 | 488 | 7 | yes |
| CVNA | 1001 | 3 | 10 | 34 | 13 | 680 | 4 | yes |
| AFRM | 682 | 5 | 17 | 60 | 22 | 435 | 6 | no |
| RKT | 663 | 6 | 18 | 98 | 26 | 342 | 6 | no |
| UNH | 1000 | 6 | 16 | 91 | 22 | 765 | 6 | yes |
| HCA | 1017 | 9 | 25 | 103 | 34 | 670 | 9 | yes |
| UNP | 1000 | 6 | 17 | 87 | 24 | 674 | 6 | yes |
| DAL | 1000 | 10 | 28 | 176 | 38 | 525 | 10 | yes |
| UPS | 1014 | 10 | 31 | 102 | 41 | 613 | 11 | yes |

## Honest boundary

- This proves SEQUENCING (types, dates, accessions, links), not verification. Financial verification coverage is exactly the per-form label — nothing more.
- The `recent` window is the SEC's most-recent ~1,000 filings per filer; older filings exist in paginated archives (flagged, not fetched in v1).
- The spot-check proves two SEC endpoints agree on the latest 10-K; it is not a per-event audit of every timeline entry.
