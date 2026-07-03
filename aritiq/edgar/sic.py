"""
SEC SIC (Standard Industrial Classification) lookup — the peer-grouping key.

WHY THIS EXISTS
---------------
Peer/sector comparison ("X has the best margin in its peer group") needs a
DEFENSIBLE peer set. Building an industry-classification system from scratch is a
research problem out of scope for this round. The SEC already assigns every filer a
SIC code, exposed in the submissions feed
(`data.sec.gov/submissions/CIK{cik}.json` → `sic` / `sicDescription`). Grouping the
filers we already have by SIC code reuses data the SEC publishes — no new judgment
model, no hand-maintained peer lists.

NAMED LIMITATION (documented, not hidden): SIC codes are COARSE. Two companies with
the same SIC code are in the same broad industry but are not always true competitors
(e.g. a mega-cap and a micro-cap in "6798 Real Estate Investment Trusts"). We surface
the SIC code and description on every comparison so a reviewer sees exactly what
"peer" meant — the classytr judgment is explicit, exactly like `definitional_flag`
surfaces a vague word instead of silently resolving it.

FIREWALL: plain HTTP / cached JSON against the SEC's free no-auth submissions API,
the same pattern as sec.py / xbrl.py. NO model SDK here; nothing in aritiq/core/
imports this.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .sec import lookup_cik, _default_fetch, FetchFn, EdgarError, SUBMISSIONS_URL

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)),
    "benchmark", "reliability", "cache", "sic",
)


@dataclass
class SicInfo:
    ticker: str
    cik: Optional[int] = None
    name: str = ""
    sic: Optional[str] = None
    sic_description: str = ""
    fetch_error: Optional[str] = None


def _cache_path(ticker: str, cache_dir: str) -> str:
    return os.path.join(cache_dir, f"{ticker.upper()}.json")


def get_sic(
    ticker: str,
    *,
    fetch: Optional[FetchFn] = None,
    cache_dir: str = _DEFAULT_CACHE,
    use_cache: bool = True,
) -> SicInfo:
    """Return the SIC code + description for a ticker (cached).

    Never raises: a fetch/parse failure records `fetch_error` and returns a valid
    SicInfo with sic=None, so a peer-grouping loop never crashes.
    """
    fetch = fetch or _default_fetch
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(ticker, cache_dir)
    if use_cache and os.path.exists(path):
        d = json.load(open(path))
        return SicInfo(**d)

    out = SicInfo(ticker=ticker.upper())
    try:
        cik, company = lookup_cik(ticker, fetch=fetch)
        out.cik = cik
        out.name = company
        url = SUBMISSIONS_URL.format(cik10=f"{cik:010d}")
        d = json.loads(fetch(url))
        sic = d.get("sic")
        out.sic = str(sic) if sic not in (None, "") else None
        out.sic_description = d.get("sicDescription", "") or ""
        if d.get("name"):
            out.name = d["name"]
        time.sleep(0.12)  # under SEC 10 req/sec
    except EdgarError as e:
        out.fetch_error = f"{type(e).__name__}: {e}"
    except Exception as e:
        out.fetch_error = f"{type(e).__name__}: {str(e)[:180]}"

    # cache successful lookups only (don't pin a transient failure)
    if out.fetch_error is None and out.sic is not None:
        json.dump(out.__dict__, open(path, "w"), indent=2)
    return out


def group_by_sic(
    tickers: List[str],
    *,
    fetch: Optional[FetchFn] = None,
    cache_dir: str = _DEFAULT_CACHE,
    use_cache: bool = True,
) -> Dict[str, List[SicInfo]]:
    """Group tickers by SIC code. Tickers whose SIC couldn't be resolved are placed
    under the key "UNKNOWN" so they are visible, never silently dropped."""
    groups: Dict[str, List[SicInfo]] = {}
    for tk in tickers:
        info = get_sic(tk, fetch=fetch, cache_dir=cache_dir, use_cache=use_cache)
        key = info.sic if info.sic else "UNKNOWN"
        groups.setdefault(key, []).append(info)
    return groups
