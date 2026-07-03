"""
Phase 1 moment-of-truth: what XBRL facts exist for the filers that broke text
extraction? Fetches XBRL facts for a set of tickers and prints what was found.

Run:
    python benchmark/reliability/xbrl_probe.py
    python benchmark/reliability/xbrl_probe.py AMD TSLA SPG JPM WFC CAT
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.edgar.xbrl import extract_xbrl_facts  # noqa: E402

# Includes the mechanism-bug filers AND the 5 that failed LLM extraction entirely.
DEFAULT = ["AMD", "TSLA", "SPG", "JPM", "BAC", "DUK", "WFC", "CAT", "BRK-A", "BRK-B", "GEV"]


def fmt(v):
    if v is None:
        return "     —      "
    if abs(v) >= 1000:
        return f"{v/1e6:>10.1f}M"   # display in $M
    return f"{v:>11.3f}"


def main():
    tickers = sys.argv[1:] or DEFAULT
    print("=" * 100)
    print("  ARITIQ — XBRL fact probe (Phase 1 moment of truth). Values shown in $M except EPS/shares.")
    print("=" * 100)
    for tk in tickers:
        f = extract_xbrl_facts(tk)
        if f.fetch_error:
            print(f"\n  {tk:6} FETCH ERROR: {f.fetch_error}")
            continue
        print(f"\n  {tk:6} {f.company[:34]:34} period={f.period_end} fy={f.fy}")
        print(f"    Assets={fmt(f.assets)}  Liabilities={fmt(f.liabilities)}  "
              f"Equity={fmt(f.equity)} (incl_NCI={f.equity_includes_nci})")
        print(f"    NI_total={fmt(f.net_income_total)}  NI_to_common={fmt(f.net_income_to_common)}")
        print(f"    EPS_basic={f.eps_basic}  EPS_diluted={f.eps_diluted}  "
              f"shares_basic={fmt(f.shares_basic)}  shares_diluted={fmt(f.shares_diluted)}")
        print(f"    BS_cash={fmt(f.bs_cash)}  CF_cash={fmt(f.cf_cash)} "
              f"(incl_restricted={f.cf_cash_includes_restricted})")
        # quick reconciliation preview
        if f.assets and f.liabilities is not None and f.equity is not None:
            gap = f.assets - (f.liabilities + f.equity)
            print(f"    -> BS identity: Assets - (Liab+Eq) = {gap/1e6:+.1f}M "
                  f"({'ties' if abs(gap) < 0.001*f.assets else 'GAP'})")
        elif f.liabilities is None:
            print(f"    -> BS identity: Liabilities tag ABSENT (filer tags components only)")
    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
