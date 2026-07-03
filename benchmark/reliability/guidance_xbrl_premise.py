"""Check whether SEC companyfacts contains issuer forward-guidance figures.

Round-9 Feature C premise check. Guidance is commonly in press releases,
earnings calls, or furnished 8-K text, not standardized companyfacts concepts.
This script makes that finding reproducible instead of forcing a weak tracker.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Dict, List


DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "benchmark",
    "reliability",
    "cache",
    "xbrl",
)

GUIDANCE_TERMS = re.compile(
    r"guidance|outlook|projection|forecast|expectedrevenue|expectedearnings",
    re.I,
)

FALSE_POSITIVE_TERMS = re.compile(
    r"hedge|hedging|derivative|forecastedtransaction|reinsurance|"
    r"expectedcost|expectednumber|amortization|tax|qualifying",
    re.I,
)


def scan_companyfacts_cache(cache_dir: str = DEFAULT_CACHE_DIR) -> Dict[str, object]:
    files = []
    for dirpath, _, names in os.walk(cache_dir):
        for name in names:
            if name.startswith("_raw_") and name.endswith(".json"):
                files.append(os.path.join(dirpath, name))

    raw_hits: List[dict] = []
    candidate_hits: List[dict] = []
    for path in sorted(files):
        ticker = os.path.basename(path).replace("_raw_", "").replace(".json", "")
        try:
            data = json.load(open(path))
        except Exception as exc:
            raw_hits.append({
                "ticker": ticker,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        for namespace, concepts in data.get("facts", {}).items():
            for tag, obj in concepts.items():
                label = str(obj.get("label", ""))
                desc = str(obj.get("description", ""))
                haystack = " ".join([tag, label, desc])
                if not GUIDANCE_TERMS.search(haystack):
                    continue
                hit = {
                    "ticker": ticker,
                    "namespace": namespace,
                    "tag": tag,
                    "label": label,
                    "reason": "matches forward-looking term",
                }
                raw_hits.append(hit)
                if not FALSE_POSITIVE_TERMS.search(haystack):
                    candidate_hits.append(hit)

    return {
        "schema": "aritiq.guidance_xbrl_premise/v1",
        "files_scanned": len(files),
        "raw_forward_term_hits": len(raw_hits),
        "issuer_guidance_candidates": len(candidate_hits),
        "conclusion": (
            "companyfacts does not reliably expose issuer guidance ranges"
            if not candidate_hits else
            "candidate guidance-like companyfacts concepts found; manual validation required"
        ),
        "raw_hit_sample": raw_hits[:25],
        "candidate_hits": candidate_hits,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan XBRL cache for guidance concepts")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    args = ap.parse_args()
    print(json.dumps(scan_companyfacts_cache(args.cache_dir), indent=2))


if __name__ == "__main__":
    main()
