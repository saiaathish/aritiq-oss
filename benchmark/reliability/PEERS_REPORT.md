# Peer / sector comparison (SIC-based, XBRL-grounded)

Peer sets are the SEC's own SIC industry codes — reused, not invented. **Named limitation:** SIC codes are coarse; the same code is not always a true competitor. Every comparison carries its SIC code so the judgment is explicit.

- Viable SIC groups (>= 3 members): 8
- Compared: 2 | Declined for non-comparability: 6
- Comparability gates: period alignment (<= 200d apart), margin sanity (|margin| <= 100%)

## SIC 6798 — Real Estate Investment Trusts

Members: PLD, AMT, SPG, O, EQIX, DLR, VICI, WELL, AVB, BXP, CCI

**DECLINED:** net-margin comparison declined for this SIC class: REIT — `Revenues` tag captures partial rental income, not total revenue. NI/Revenues is not a defensible cross-peer metric here (observed in-group margin spread was driven by tag meaning, not performance).

Excluded (gated, not compared):

- `PLD`: SIC-class non-comparable revenue denominator
- `AMT`: SIC-class non-comparable revenue denominator
- `SPG`: SIC-class non-comparable revenue denominator
- `O`: SIC-class non-comparable revenue denominator
- `EQIX`: SIC-class non-comparable revenue denominator
- `DLR`: SIC-class non-comparable revenue denominator
- `VICI`: SIC-class non-comparable revenue denominator
- `WELL`: SIC-class non-comparable revenue denominator
- `AVB`: SIC-class non-comparable revenue denominator
- `BXP`: SIC-class non-comparable revenue denominator
- `CCI`: SIC-class non-comparable revenue denominator

## SIC 6331 — Fire, Marine & Casualty Insurance

Members: BRK-B, PGR, AIG, TRV, ALL, CB, BRK-A

**DECLINED:** net-margin comparison declined for this SIC class: P&C insurer — `Revenues` tag captures premiums, not a comparable top line. NI/Revenues is not a defensible cross-peer metric here (observed in-group margin spread was driven by tag meaning, not performance).

Excluded (gated, not compared):

- `BRK-B`: SIC-class non-comparable revenue denominator
- `PGR`: SIC-class non-comparable revenue denominator
- `AIG`: SIC-class non-comparable revenue denominator
- `TRV`: SIC-class non-comparable revenue denominator
- `ALL`: SIC-class non-comparable revenue denominator
- `CB`: SIC-class non-comparable revenue denominator
- `BRK-A`: SIC-class non-comparable revenue denominator

## SIC 7372 — Services-Prepackaged Software

Members: PLTR, MSFT, CRM, ORCL, DDOG, U

**Winner:** PLTR (36.31% net margin) — verifier verdict `VERIFIED`

| Peer | Period | Net margin % |
|---|---|---|
| PLTR | 2025-12-31 | 36.31 |
| ORCL | 2026-05-31 | 25.37 |
| CRM | 2026-01-31 | 17.96 |
| DDOG | 2025-12-31 | 3.14 |
| U | 2025-12-31 | -21.78 |

Excluded (gated, not compared):

- `MSFT`: period 2025-06-30 is 335d behind peer group latest — stale, excluded

> neg-control (U as max): WRONG_MATH

## SIC 3674 — Semiconductors & Related Devices

Members: AMD, NVDA, INTC

**DECLINED:** only 2 peer(s) survived comparability gating (need >= 3); declining rather than crown 'best-in-class' over a non-comparable group

| Peer | Period | Net margin % |
|---|---|---|
| AMD | 2025-12-27 | 12.51 |
| INTC | 2025-12-27 | -0.51 |

Excluded (gated, not compared):

- `NVDA`: period 2022-01-30 is 1427d behind peer group latest — stale, excluded

## SIC 3711 — Motor Vehicles & Passenger Car Bodies

Members: TSLA, F, RIVN

**DECLINED:** only 2 peer(s) survived comparability gating (need >= 3); declining rather than crown 'best-in-class' over a non-comparable group

| Peer | Period | Net margin % |
|---|---|---|
| TSLA | 2025-12-31 | 4.0 |
| RIVN | 2025-12-31 | -67.68 |

Excluded (gated, not compared):

- `F`: period 2024-12-31 is 365d behind peer group latest — stale, excluded

## SIC 6021 — National Commercial Banks

Members: JPM, BAC, WFC

**DECLINED:** net-margin comparison declined for this SIC class: commercial bank — net interest income tagged idiosyncratically across filers. NI/Revenues is not a defensible cross-peer metric here (observed in-group margin spread was driven by tag meaning, not performance).

Excluded (gated, not compared):

- `JPM`: SIC-class non-comparable revenue denominator
- `BAC`: SIC-class non-comparable revenue denominator
- `WFC`: SIC-class non-comparable revenue denominator

## SIC 2834 — Pharmaceutical Preparations

Members: JNJ, PFE, MRK

**DECLINED:** only 2 peer(s) survived comparability gating (need >= 3); declining rather than crown 'best-in-class' over a non-comparable group

| Peer | Period | Net margin % |
|---|---|---|
| JNJ | 2025-12-28 | 28.46 |
| MRK | 2025-12-31 | 28.08 |

Excluded (gated, not compared):

- `PFE`: period 2023-12-31 is 731d behind peer group latest — stale, excluded

## SIC 3724 — Aircraft Engines & Engine Parts

Members: HON, RTX, HEI

**Winner:** HEI (15.39% net margin) — verifier verdict `VERIFIED`

| Peer | Period | Net margin % |
|---|---|---|
| HEI | 2025-10-31 | 15.39 |
| HON | 2025-12-31 | 12.63 |
| RTX | 2025-12-31 | 7.6 |

> neg-control (RTX as max): WRONG_MATH

