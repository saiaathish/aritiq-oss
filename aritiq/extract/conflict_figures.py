"""
Cross-document conflict-figure extraction (Phase 3 wiring).

Problem this closes
-------------------
`registry.find_conflicts` detects when two filings report the same labelled
figure with different values — but it compares structured `TableCell`s
(row_label, column_label, value).  Real input pasted into the UI is PROSE, which
produces no cells, so on prose the conflict scan had nothing to compare and the
cross-document CONFLICT never fired.  This module is the missing extraction step:
it grounds a small, fixed set of comparable labelled figures from each prose
document into `TableCell`s, so `find_conflicts` can do its job on real text.

Firewall
--------
This is an LLM step, so it lives in `extract/`, NOT `core/`.  Like every other
extractor it imports the schema (to *produce* TableCell objects) and never
imports `verify`/`score`/`registry` logic that decides a verdict.  The model's
ONLY job here is to LOCATE figures and label them with a normalized metric name
and a period; it never decides whether two values "conflict" — that stays in
deterministic code (`find_conflicts`).

Discipline (mirrors cross_statement.py)
---------------------------------------
* Normalize the metric name to a small controlled vocabulary so "Total revenue"
  and "Revenue, net" become the same key and are actually comparable.  A figure
  whose metric doesn't map to the vocabulary is dropped, not guessed — a wrong
  label would manufacture a false conflict (or hide a real one).
* Normalize the period to a canonical token (e.g. "fiscal year 2024" -> "FY2024")
  so the SAME period across two filings shares a column_label.
* Ground the VALUE verbatim; never compute or reconcile.  Restated vs original
  is exactly the disagreement we want surfaced, so we must not "fix" it.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from ..core.schema import TableCell
from .extractor import CompletionFn, _default_complete_fn, DEFAULT_MAX_TOKENS
from .schema import _coerce_number, _extract_json_array


# A small controlled vocabulary of metric keys.  The model is asked to map each
# grounded figure to one of these; anything else is dropped (see _canonical_metric).
CONFLICT_METRICS = {
    "total_revenue": "Total revenue",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "total_liabilities": "Total liabilities",
    "total_equity": "Total stockholders' equity",
    "gross_profit": "Gross profit",
    "operating_income": "Operating income",
    "cash_and_equivalents": "Cash and cash equivalents",
    "diluted_eps": "Diluted EPS",
    "basic_eps": "Basic EPS",
}


CONFLICT_FIGURE_SYSTEM_PROMPT = """\
You are Aritiq's CROSS-DOCUMENT FIGURE component. Your ONLY job is to locate a \
small, fixed set of headline financial figures inside ONE document and report \
each with a NORMALIZED metric key and a NORMALIZED period. You do NOT compare \
anything across documents. You never compute, reconcile, or "fix" a number. A \
separate deterministic program compares figures across documents.

Report a figure ONLY for these metric keys (use the key string exactly):
  total_revenue, net_income, total_assets, total_liabilities, total_equity,
  gross_profit, operating_income, cash_and_equivalents, diluted_eps, basic_eps

For EACH figure you can locate in THIS document:
  - "metric": one of the keys above. If a figure doesn't match any key, OMIT it.
  - "period": the fiscal period the figure is FOR, normalized as "FY<year>"
    (e.g. "fiscal year 2024" -> "FY2024", "the year ended December 31, 2025" ->
    "FY2025", "Q3 2025" -> "Q3-2025"). A later filing often reports a PRIOR
    year's figure too (e.g. a FY2025 10-K stating FY2024 revenue "as restated") —
    report THAT figure with the PRIOR period (FY2024) and the value as stated in
    THIS document. Reporting restated prior-year figures is important: that is
    exactly how a cross-document disagreement is detected.
  - "value": the number, normalized to millions of dollars for money figures
    (e.g. "$740.0 million" -> 740.0, "$1.2 billion" -> 1200.0), or the raw
    per-share number for EPS (e.g. "$1.36" -> 1.36). Ground it VERBATIM from the
    document; do NOT compute or adjust it.
  - "source_text": the exact substring you read the figure from.

If the same metric+period appears more than once in this document with the same
value, report it once. If a metric is absent, omit it.

OUTPUT FORMAT: return ONLY a JSON array, no prose, no markdown, no code fences.
Each element:
  {"metric": "<key>", "period": "FY2024", "value": number, "source_text": string}

If the document contains none of these figures, return []."""


CONFLICT_FIGURE_USER_TEMPLATE = """\
DOCUMENT {doc_label} (locate and ground the headline figures here):
\"\"\"
{document}
\"\"\"

Return the JSON array of figures now (normalized metric key + period + value)."""


def build_conflict_figure_user_prompt(document: str, doc_label: str = "") -> str:
    return CONFLICT_FIGURE_USER_TEMPLATE.format(
        document=document.strip(), doc_label=doc_label or "(unnamed)"
    )


def _canonical_metric(raw: object) -> Optional[str]:
    """Map a model-reported metric to its display label, or None to drop it."""
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return CONFLICT_METRICS.get(key)


_PERIOD_RE = re.compile(r"(?:FY)?\s*(\d{4})", re.IGNORECASE)
_QUARTER_RE = re.compile(r"Q([1-4])[\s\-]*(\d{4})", re.IGNORECASE)


def _canonical_period(raw: object) -> Optional[str]:
    """Normalize a period string to FY<year> or Q<n>-<year>, or None to drop it.

    Deterministic: a period we can't confidently canonicalize is dropped rather
    than guessed, because a wrong period would create a false cross-document key
    match (or miss a real one).
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    q = _QUARTER_RE.search(s)
    if q:
        return f"Q{q.group(1)}-{q.group(2)}"
    m = _PERIOD_RE.search(s)
    if m:
        return f"FY{m.group(1)}"
    return None


def parse_conflict_figures(text: str, doc_id: str) -> List[TableCell]:
    """Parse a model response into TableCells (metric=row, period=column).

    Pure, no LLM.  Each element is validated independently; a row that can't be
    canonicalized (bad metric, bad period, non-numeric value) is silently
    dropped — surfacing a half-understood figure as a cell could fabricate a
    conflict, which is worse than missing one.
    """
    try:
        array_str = _extract_json_array(text)
        data = json.loads(array_str)
    except (ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []

    cells: List[TableCell] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        metric = _canonical_metric(item.get("metric"))
        period = _canonical_period(item.get("period"))
        value = _coerce_number(item.get("value"))
        if metric is None or period is None or not isinstance(value, (int, float)):
            continue
        cells.append(TableCell(
            row_label=metric,
            column_label=period,
            value=float(value),
            doc_id=doc_id,
        ))
    return cells


def extract_conflict_figures(
    document: str,
    doc_id: str,
    *,
    complete_fn: Optional[CompletionFn] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> List[TableCell]:
    """Ground comparable labelled figures from one prose document into TableCells.

    Pass `complete_fn` to run offline (tests/replay); omit for the default
    backend.  Returns the cells (possibly empty); never raises on a bad model
    response — unparseable output yields an empty list, so a figure-extraction
    failure degrades to "no conflict detected", never a crash or a fabricated one.
    """
    system_prompt = CONFLICT_FIGURE_SYSTEM_PROMPT
    user_prompt = build_conflict_figure_user_prompt(document, doc_label=doc_id)

    if complete_fn is None:
        complete_fn, _prov, _mod = _default_complete_fn(provider, model, max_tokens)

    raw = complete_fn(system_prompt, user_prompt)
    return parse_conflict_figures(raw, doc_id)
