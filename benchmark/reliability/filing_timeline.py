"""
Phase 3 item 1 — SEC filing timeline: measurement over the real 83-filer set.

What this measures (and what it does NOT):
- For every filer in filing_set.json, build the timeline from the SEC
  submissions feed (aritiq.edgar.timeline, cached under cache/timeline/).
- INTEGRITY GATES per filer (hard failures, counted):
    * every filing_date parses as an ISO date,
    * events are sorted newest-first,
    * every accession matches the EDGAR format NNNNNNNNNN-NN-NNNNNN,
    * every event carries a coverage label from the closed enum,
    * every 8-K labeled PARTIAL actually lists Item 2.02.
- INDEPENDENT SPOT-CHECK: for a handful of filers, the latest 10-K accession +
  filing date from the submissions feed are cross-checked against SEC's OTHER
  endpoint (www.sec.gov browse-edgar Atom feed). Two SEC surfaces agreeing on
  the same accession is the reproducible version of "hand-check against EDGAR".
- NOT measured here: any financial verification of the filings themselves —
  that is exactly what the coverage labels state per form. This script proves
  the SEQUENCING is right, nothing more.

Run:
    python benchmark/reliability/filing_timeline.py                    # all 83
    python benchmark/reliability/filing_timeline.py AAPL JPM WELL      # subset
    python benchmark/reliability/filing_timeline.py --md benchmark/reliability/TIMELINE_REPORT.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from aritiq.edgar.timeline import (  # noqa: E402
    ALL_COVERAGE_LEVELS,
    COVERAGE_FULL,
    COVERAGE_PARTIAL,
    get_timeline,
)
from aritiq.edgar.sec import SEC_USER_AGENT  # noqa: E402

FILING_SET = os.path.join(HERE, "filing_set.json")
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_ATOM_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    "&type=10-K&dateb=&owner=include&count=10&output=atom"
)
SPOT_CHECK_TICKERS = ["AAPL", "JPM", "WELL"]


def _load_tickers() -> List[str]:
    d = json.load(open(FILING_SET))
    return [f["ticker"] for f in d["filings"]]


def _iso_ok(s: str) -> bool:
    try:
        dt.date.fromisoformat(s)
        return True
    except Exception:
        return False


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def spot_check_latest_10k(ticker: str, cik: int, timeline_events) -> dict:
    """Cross-check the latest 10-K against the browse-edgar Atom feed
    (a different SEC endpoint than the submissions JSON)."""
    ours = next((e for e in timeline_events if e.form == "10-K"), None)
    out = {"ticker": ticker, "ok": False, "detail": ""}
    if ours is None:
        out["detail"] = "no 10-K in timeline recent window"
        return out
    try:
        atom = _fetch(_ATOM_URL.format(cik=f"{cik:010d}"))
    except Exception as e:
        out["detail"] = f"atom fetch failed: {e}"
        return out
    # Atom entries carry accession-number and filing-date tags.
    accessions = re.findall(r"accession-n\w*>([\d-]+)<", atom)
    dates = re.findall(r"filing-date>([\d-]+)<", atom)
    if not accessions:
        out["detail"] = "no 10-K entries in atom feed"
        return out
    if ours.accession == accessions[0] and (not dates or ours.filing_date == dates[0]):
        out["ok"] = True
        out["detail"] = (f"latest 10-K agrees on both SEC endpoints: "
                         f"{ours.accession} filed {ours.filing_date}")
    else:
        out["detail"] = (f"MISMATCH: submissions={ours.accession}/{ours.filing_date} "
                         f"atom={accessions[0]}/{dates[0] if dates else '?'}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", help="subset (default: full filing set)")
    ap.add_argument("--md", help="write a markdown report to this path")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    tickers = [t.upper() for t in args.tickers] or _load_tickers()

    ok, failed = [], []
    gate_failures: List[str] = []
    form_totals: Counter = Counter()
    coverage_totals: Counter = Counter()
    per_filer_rows: List[str] = []
    date_min, date_max = "9999-12-31", "0000-01-01"

    for tk in tickers:
        tl = get_timeline(tk, use_cache=not args.no_cache)
        if tl.fetch_error or not tl.events:
            failed.append((tk, tl.fetch_error or "no events"))
            continue
        ok.append(tk)

        # --- integrity gates ---
        dates = [e.filing_date for e in tl.events]
        if not all(_iso_ok(d) for d in dates):
            gate_failures.append(f"{tk}: non-ISO filing date")
        if dates != sorted(dates, reverse=True):
            gate_failures.append(f"{tk}: events not sorted newest-first")
        for e in tl.events:
            if e.accession and not _ACCESSION_RE.match(e.accession):
                gate_failures.append(f"{tk}: bad accession {e.accession!r}")
                break
        if any(e.verification_coverage not in ALL_COVERAGE_LEVELS for e in tl.events):
            gate_failures.append(f"{tk}: unknown coverage label")
        for e in tl.events:
            if e.form == "8-K" and e.verification_coverage == COVERAGE_PARTIAL:
                if "2.02" not in [i.strip() for i in e.items.split(",")]:
                    gate_failures.append(f"{tk}: PARTIAL 8-K without Item 2.02")
                    break

        fc = tl.form_counts()
        cc = tl.coverage_counts()
        form_totals.update(fc)
        coverage_totals.update(cc)
        date_min = min(date_min, min(dates))
        date_max = max(date_max, max(dates))
        per_filer_rows.append(
            f"| {tk} | {len(tl.events)} | {fc.get('10-K', 0)} | {fc.get('10-Q', 0)} "
            f"| {fc.get('8-K', 0)} | {cc[COVERAGE_PARTIAL]} | {fc.get('4', 0)} "
            f"| {fc.get('DEF 14A', 0)} | {'yes' if tl.has_older_filings else 'no'} |"
        )

    # --- independent spot-check (submissions feed vs browse-edgar atom feed) ---
    spots = []
    for tk in SPOT_CHECK_TICKERS:
        if tk not in ok:
            continue
        tl = get_timeline(tk)
        spots.append(spot_check_latest_10k(tk, tl.cik, tl.events))

    lines = []
    lines.append("# SEC Filing Timeline — measurement report\n")
    lines.append(f"Generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
                 f"over the reliability filing set.\n")
    lines.append(f"- Filers attempted: **{len(tickers)}**")
    lines.append(f"- Timelines built: **{len(ok)}/{len(tickers)}**")
    lines.append(f"- Total events sequenced: **{sum(form_totals.values())}** "
                 f"(recent window per filer; spans {date_min} → {date_max})")
    lines.append(f"- Integrity-gate failures: **{len(gate_failures)}**"
                 + (f" — {gate_failures}" if gate_failures else ""))
    if failed:
        lines.append(f"- Fetch failures: {failed}")
    lines.append("")
    lines.append("## Events by form (top 12)\n")
    lines.append("| Form | Count |\n|---|---|")
    for form, n in form_totals.most_common(12):
        lines.append(f"| {form} | {n} |")
    lines.append("")
    lines.append("## Events by verification coverage\n")
    lines.append("The load-bearing table: what Aritiq actually verifies per filing type.\n")
    lines.append("| Coverage | Events | Meaning |\n|---|---|---|")
    meanings = {
        COVERAGE_FULL: "10-K/10-Q — measured financial verification",
        COVERAGE_PARTIAL: "8-K with Item 2.02 earnings exhibit — experimental/partial",
        "ownership_data_only": "Form 4 — parsed insider transactions, not financially verified",
        "listed_only": "dated entry + EDGAR link only, NO verification",
    }
    for cov in ALL_COVERAGE_LEVELS:
        lines.append(f"| {cov} | {coverage_totals.get(cov, 0)} | {meanings[cov]} |")
    lines.append("")
    lines.append("## Independent spot-check (submissions JSON vs browse-edgar Atom)\n")
    for s in spots:
        lines.append(f"- {'PASS' if s['ok'] else 'FAIL'} {s['ticker']}: {s['detail']}")
    lines.append("")
    lines.append("## Per-filer detail\n")
    lines.append("| Ticker | Events | 10-K | 10-Q | 8-K | 8-K w/2.02 | Form 4 | DEF 14A | older archives |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    lines.extend(per_filer_rows)
    lines.append("")
    lines.append("## Honest boundary\n")
    lines.append("- This proves SEQUENCING (types, dates, accessions, links), not verification. "
                 "Financial verification coverage is exactly the per-form label — nothing more.")
    lines.append("- The `recent` window is the SEC's most-recent ~1,000 filings per filer; "
                 "older filings exist in paginated archives (flagged, not fetched in v1).")
    lines.append("- The spot-check proves two SEC endpoints agree on the latest 10-K; it is "
                 "not a per-event audit of every timeline entry.")

    report = "\n".join(lines)
    print(report)
    if args.md:
        with open(args.md, "w") as f:
            f.write(report + "\n")
        print(f"\n[written to {args.md}]", file=sys.stderr)

    spot_fail = any(not s["ok"] for s in spots)
    return 1 if (gate_failures or failed or spot_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
