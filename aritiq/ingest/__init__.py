"""
Aritiq ingestion robustness (System 2).

A thin, dependency-injected robustness layer over SEC fetches: retry with
exponential backoff + jitter on TRANSIENT failures (timeouts, connection resets,
429/5xx), rate-limit spacing, and per-call latency/outcome metrics for throughput
and observability. It wraps any base fetch function and is passed to the existing
edgar functions via their `fetch=` parameter — no edgar/core code is modified, and
no model SDK is imported.
"""
from .robust_fetch import (  # noqa: F401
    FetchMetrics, make_robust_fetch, is_retryable, RETRYABLE_HTTP_STATUS,
)
