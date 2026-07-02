"""MD&A directional-claim extraction.

This module is an extraction edge only: a caller supplies a model completion
function and receives structured prose-direction tags. No verification happens
here. `aritiq/core/` performs the deterministic XBRL comparison.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, List, Optional

from aritiq.core.schema import TrendDir


CompletionFn = Callable[[str, str], str]


@dataclass
class MdaDirectionalClaim:
    metric: str
    direction: TrendDir
    excerpt: str
    period: Optional[str] = None
    confidence: Optional[str] = None


MDA_SYSTEM_PROMPT = """You extract directional business claims from SEC MD&A text.

Return only JSON. Extract only claims where management characterizes a metric
direction as up, down, or flat. Do not invent percentages or numbers. Do not
decide whether the statement is true; just tag the prose direction.
"""


def build_mda_user_prompt(mda_text: str) -> str:
    return f"""Extract directional MD&A claims from this text.

Allowed directions: "up", "down", "flat".
Allowed output schema:
[
  {{
    "metric": "revenue|net_income|operating_income|gross_margin|net_margin|other",
    "direction": "up|down|flat",
    "excerpt": "verbatim sentence fragment",
    "period": "optional period wording",
    "confidence": "high|medium|low"
  }}
]

Rules:
- Use "up" for grew, increased, improved, expanded, higher.
- Use "down" for declined, decreased, contracted, lower, deteriorated.
- Use "flat" only for stable, flat, unchanged, comparable, in line.
- If wording is vague without a direction, omit it.
- Never invent a percentage.

MD&A text:
{mda_text}
"""


def _parse_direction(value: str) -> TrendDir:
    v = (value or "").strip().lower()
    if v == "up":
        return TrendDir.UP
    if v == "down":
        return TrendDir.DOWN
    if v == "flat":
        return TrendDir.FLAT
    raise ValueError(f"unknown MD&A direction {value!r}")


def parse_mda_directional_claims(raw_json: str) -> List[MdaDirectionalClaim]:
    data = json.loads(raw_json)
    if not isinstance(data, list):
        raise ValueError("MD&A directional extraction must return a JSON array")
    out: List[MdaDirectionalClaim] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip()
        excerpt = str(item.get("excerpt") or "").strip()
        direction = _parse_direction(str(item.get("direction") or ""))
        if not metric or not excerpt:
            continue
        out.append(MdaDirectionalClaim(
            metric=metric,
            direction=direction,
            excerpt=excerpt,
            period=item.get("period"),
            confidence=item.get("confidence"),
        ))
    return out


def extract_mda_directional_claims(
    mda_text: str,
    *,
    complete_fn: CompletionFn,
) -> List[MdaDirectionalClaim]:
    raw = complete_fn(MDA_SYSTEM_PROMPT, build_mda_user_prompt(mda_text))
    return parse_mda_directional_claims(raw)
