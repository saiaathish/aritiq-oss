"""
Per-company, multi-filing memory built on cached SEC companyfacts.

This module packages existing xbrl_history series into a deterministic
cross-year view. It does not read footnotes or classify accounting language.
Signals here mean "machine-detectable comparability/definition risk surfaced"
from XBRL metadata and existing gates.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Iterable, List, Optional

from .xbrl import _DEFAULT_CACHE
from .xbrl_history import ConceptSeries, CONCEPT_TAGS, get_concept_series


DEFAULT_MEMORY_CONCEPTS = (
    "revenue",
    "net_income",
    "assets",
    "liabilities",
    "equity",
    "gross_profit",
    "operating_income",
    "eps_basic",
    "eps_diluted",
    "shares_basic",
)


@dataclass
class MetricPoint:
    period_end: str
    value: float
    yoy_change_pct: Optional[float] = None


@dataclass
class ComparabilitySignal:
    concept: str
    signal: str
    detail: str
    deterministic: bool = True


@dataclass
class MetricMemory:
    concept: str
    tag_used: Optional[str]
    points: List[MetricPoint] = field(default_factory=list)
    n_points: int = 0
    latest_yoy_change_pct: Optional[float] = None
    dropped_noncomparable_spans: int = 0
    split_sensitive: bool = False
    signals: List[ComparabilitySignal] = field(default_factory=list)
    fetch_error: Optional[str] = None


@dataclass
class CompanyMemory:
    ticker: str
    metrics: List[MetricMemory] = field(default_factory=list)
    signals: List[ComparabilitySignal] = field(default_factory=list)
    boundary: str = (
        "Deterministic XBRL/companyfacts memory only. Accounting-change signals "
        "mean tag/comparability gates fired; footnote-language interpretation is "
        "not performed here."
    )


def _metric_points(series: ConceptSeries) -> List[MetricPoint]:
    points: List[MetricPoint] = []
    prev: Optional[float] = None
    for period_end, value in series.series:
        yoy = None
        if prev not in (None, 0):
            yoy = round((value - prev) / prev * 100.0, 4)
        points.append(MetricPoint(period_end=period_end, value=value, yoy_change_pct=yoy))
        prev = value
    return points


def _signals_for_series(series: ConceptSeries) -> List[ComparabilitySignal]:
    signals: List[ComparabilitySignal] = []
    if series.dropped_noncomparable_spans > 0:
        signals.append(
            ComparabilitySignal(
                concept=series.concept,
                signal="noncomparable_spans_dropped",
                detail=(
                    f"{series.dropped_noncomparable_spans} non-annual/non-comparable "
                    "span(s) were excluded before trend comparison."
                ),
            )
        )
    if series.split_sensitive:
        signals.append(
            ComparabilitySignal(
                concept=series.concept,
                signal="split_sensitive_series",
                detail=(
                    "Per-share/share-count series may be non-comparable across stock "
                    "splits unless restated; raw multi-year comparison is flagged."
                ),
            )
        )
    if series.tag_used and series.concept in CONCEPT_TAGS and series.tag_used != CONCEPT_TAGS[series.concept][0]:
        signals.append(
            ComparabilitySignal(
                concept=series.concept,
                signal="fallback_xbrl_tag_used",
                detail=(
                    f"Used fallback tag {series.tag_used} instead of preferred "
                    f"{CONCEPT_TAGS[series.concept][0]} for logical concept {series.concept}."
                ),
            )
        )
    return signals


def build_company_memory(
    ticker: str,
    *,
    concepts: Iterable[str] = DEFAULT_MEMORY_CONCEPTS,
    form: str = "10-K",
    cache_dir: str = _DEFAULT_CACHE,
    use_cache: bool = True,
) -> CompanyMemory:
    """Build deterministic cross-year memory for one company."""

    out = CompanyMemory(ticker=ticker.upper())
    for concept in concepts:
        series = get_concept_series(
            ticker,
            concept,
            form=form,
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        points = _metric_points(series)
        signals = _signals_for_series(series)
        latest_yoy = None
        for point in reversed(points):
            if point.yoy_change_pct is not None:
                latest_yoy = point.yoy_change_pct
                break
        metric = MetricMemory(
            concept=concept,
            tag_used=series.tag_used,
            points=points,
            n_points=len(points),
            latest_yoy_change_pct=latest_yoy,
            dropped_noncomparable_spans=series.dropped_noncomparable_spans,
            split_sensitive=series.split_sensitive,
            signals=signals,
            fetch_error=series.fetch_error,
        )
        out.metrics.append(metric)
        out.signals.extend(signals)
    return out


def company_memory_to_dict(memory: CompanyMemory) -> dict:
    return asdict(memory)
