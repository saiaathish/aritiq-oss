"""Check whether SEC companyfacts cache exposes dimensional segment facts.

SEC companyfacts is excellent for consolidated tag time series, but dimensional
segment facts are not consistently present in the cached companyfacts shape.
This scanner makes that coverage finding reproducible before any reconciliation
logic tries to sum segment members.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List


DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "benchmark",
    "reliability",
    "cache",
    "xbrl",
)

SEGMENT_KEYS = {"segments", "segment", "dimensions", "dimension"}


def scan_companyfacts_segments(cache_dir: str = DEFAULT_CACHE_DIR) -> Dict[str, object]:
    files = []
    for dirpath, _, names in os.walk(cache_dir):
        for name in names:
            if name.startswith("_raw_") and name.endswith(".json"):
                files.append(os.path.join(dirpath, name))

    filers_with_segments: List[dict] = []
    total_fact_rows = 0
    segment_fact_rows = 0

    for path in sorted(files):
        ticker = os.path.basename(path).replace("_raw_", "").replace(".json", "")
        data = json.load(open(path))
        examples = []
        count = 0
        for namespace, concepts in data.get("facts", {}).items():
            for tag, obj in concepts.items():
                for unit, facts in obj.get("units", {}).items():
                    for fact in facts:
                        total_fact_rows += 1
                        keys = set(fact.keys())
                        if keys & SEGMENT_KEYS:
                            count += 1
                            segment_fact_rows += 1
                            if len(examples) < 3:
                                examples.append({
                                    "namespace": namespace,
                                    "tag": tag,
                                    "unit": unit,
                                    "end": fact.get("end"),
                                    "val": fact.get("val"),
                                    "segment_keys": sorted(keys & SEGMENT_KEYS),
                                })
        if count:
            filers_with_segments.append({
                "ticker": ticker,
                "segment_fact_rows": count,
                "examples": examples,
            })

    return {
        "schema": "aritiq.segment_companyfacts_premise/v1",
        "files_scanned": len(files),
        "total_fact_rows_scanned": total_fact_rows,
        "segment_fact_rows": segment_fact_rows,
        "filers_with_segment_facts": len(filers_with_segments),
        "filers": filers_with_segments,
        "conclusion": (
            "companyfacts cache does not expose dimensional segment facts; "
            "segment reconciliation needs inline-XBRL/facts API dimensional "
            "data, not the current consolidated companyfacts cache"
            if segment_fact_rows == 0 else
            "segment-shaped facts present; reconciliation parser can be scoped"
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan companyfacts cache for segment facts")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    args = ap.parse_args()
    print(json.dumps(scan_companyfacts_segments(args.cache_dir), indent=2))


if __name__ == "__main__":
    main()
