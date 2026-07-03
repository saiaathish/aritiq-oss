# Multi-metric peer coverage + anomaly scan

Adds return-on-assets and leverage to net-margin peer comparison so the SIC classes where net margin is non-comparable (REITs, banks, insurers) still get a defensible peer view. Outliers are z-score **review cues (≥2σ), never verdicts**.

## net_margin — comparable in 2/8 groups

_NetIncome / Revenues; excluded for REIT/bank/insurer SICs (partial revenue tag)._

| SIC | Description | Peers | Outliers (value, z) |
|---|---|---|---|
| 6798 | Real Estate Investment Trusts | — | declined: net_margin not comparable for SIC 6798: NetIncome / Revenues; excluded for REIT/bank/insurer SICs (partial revenue tag). |
| 6331 | Fire, Marine & Casualty Insurance | — | declined: net_margin not comparable for SIC 6331: NetIncome / Revenues; excluded for REIT/bank/insurer SICs (partial revenue tag). |
| 7372 | Services-Prepackaged Software | 5 | none |
| 3674 | Semiconductors & Related Devices | — | declined: only 2 comparable peer(s) (need >= 3) |
| 3711 | Motor Vehicles & Passenger Car Bodies | — | declined: only 2 comparable peer(s) (need >= 3) |
| 6021 | National Commercial Banks | — | declined: net_margin not comparable for SIC 6021: NetIncome / Revenues; excluded for REIT/bank/insurer SICs (partial revenue tag). |
| 2834 | Pharmaceutical Preparations | — | declined: only 2 comparable peer(s) (need >= 3) |
| 3724 | Aircraft Engines & Engine Parts | 3 | none |

## return_on_assets — comparable in 7/8 groups

_NetIncome / Assets; comparable across sectors including financials and REITs._

| SIC | Description | Peers | Outliers (value, z) |
|---|---|---|---|
| 6798 | Real Estate Investment Trusts | 8 | SPG (13.21, z=2.44) |
| 6331 | Fire, Marine & Casualty Insurance | 7 | none |
| 7372 | Services-Prepackaged Software | 5 | none |
| 3674 | Semiconductors & Related Devices | 3 | none |
| 3711 | Motor Vehicles & Passenger Car Bodies | — | declined: only 2 comparable peer(s) (need >= 3) |
| 6021 | National Commercial Banks | 3 | none |
| 2834 | Pharmaceutical Preparations | 3 | none |
| 3724 | Aircraft Engines & Engine Parts | 3 | none |

## debt_ratio — comparable in 5/8 groups

_Liabilities / Assets (leverage); >100% implies negative equity (flagged)._

| SIC | Description | Peers | Outliers (value, z) |
|---|---|---|---|
| 6798 | Real Estate Investment Trusts | 11 | CCI (105.19, z=2.07) |
| 6331 | Fire, Marine & Casualty Insurance | 7 | none |
| 7372 | Services-Prepackaged Software | 4 | none |
| 3674 | Semiconductors & Related Devices | — | declined: only 1 comparable peer(s) (need >= 3) |
| 3711 | Motor Vehicles & Passenger Car Bodies | 3 | none |
| 6021 | National Commercial Banks | 3 | none |
| 2834 | Pharmaceutical Preparations | — | declined: only 2 comparable peer(s) (need >= 3) |
| 3724 | Aircraft Engines & Engine Parts | — | declined: only 2 comparable peer(s) (need >= 3) |

**Coverage:** union of the three metrics gives a defensible peer comparison in 8 SIC groups.
