"""
Fetch + slice QUALITY check — the part of the benchmark that needs NO LLM.

For every cached filing, measure whether the statements slice produced by
aritiq.edgar.sec.extract_financial_statements actually contains the balance-sheet
identity rows (Total assets AND a Total liabilities / Total equity line with real
figures). This is the upstream gate on everything else: if the statements region
wasn't sliced correctly, extraction has nothing to ground against.

This is fully reproducible offline once filings are cached
(`harness.py --fetch-only`). It does NOT call a model.

Run:
    python benchmark/reliability/slice_quality.py
"""
from __future__ import annotations

import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FILINGS_DIR = os.path.join(HERE, "cache", "filings")

_TA = re.compile(r"total\s+assets[^0-9]{0,40}\$?\s*[0-9][0-9,]{4,}", re.IGNORECASE)
_TLE = re.compile(
    r"(total\s+liabilities|total\s+(?:stockholders|shareholders|shareowners).{0,4}equity|"
    r"total\s+equity|liabilities\s+and\s+(?:stockholders|shareholders|shareowners|equity))"
    r"[^0-9]{0,40}\$?\s*[0-9][0-9,]{4,}",
    re.IGNORECASE,
)


def classify(text: str) -> str:
    a, l = bool(_TA.search(text)), bool(_TLE.search(text))
    if a and l:
        return "full_identity"
    if a or l:
        return "partial"
    return "no_identity"


def main():
    # Only score filings that are in the CURRENT filing set, so stale cache files
    # from removed/renamed tickers don't pollute the count.
    fs_path = os.path.join(HERE, "filing_set.json")
    current = {f["ticker"].upper() for f in json.load(open(fs_path))["filings"]}
    files = sorted(fp for fp in glob.glob(os.path.join(FILINGS_DIR, "*.json"))
                   if os.path.splitext(os.path.basename(fp))[0].upper() in current)
    if not files:
        print("No cached filings. Run: python benchmark/reliability/harness.py --fetch-only")
        return
    rows, counts = [], {"full_identity": 0, "partial": 0, "no_identity": 0, "fetch_fail": 0}
    for fp in files:
        d = json.load(open(fp))
        tk, t = d["ticker"], d.get("statements_text", "")
        if d.get("fetch_error"):
            counts["fetch_fail"] += 1
            rows.append((tk, "fetch_fail", len(t)))
            continue
        c = classify(t)
        counts[c] += 1
        rows.append((tk, c, len(t)))

    n = len(files)
    print("=" * 70)
    print("  ARITIQ — fetch + slice quality (no LLM)")
    print("=" * 70)
    print(f"  filings: {n}")
    print(f"  full balance-sheet identity in slice: {counts['full_identity']} "
          f"({100*counts['full_identity']/n:.0f}%)")
    print(f"  partial: {counts['partial']}   no identity: {counts['no_identity']}   "
          f"fetch fail: {counts['fetch_fail']}")
    print("-" * 70)
    for tk, c, ln in rows:
        flag = "" if c == "full_identity" else "   <-- review"
        print(f"    {tk:6} {c:14} chars={ln:>6}{flag}")
    print("=" * 70)


if __name__ == "__main__":
    main()
