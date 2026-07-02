"""
Robust SEC fetch — retry/backoff + rate-limit spacing + latency metrics.

WHY THIS EXISTS
---------------
`aritiq/edgar/sec.py`'s default fetcher is a single `urllib.urlopen`. In production
a deployed instance must not silently die on a transient EDGAR hiccup — a timeout, a
dropped connection, an SEC 429 (rate limit) or a 5xx. This module wraps ANY base
fetch function (default: the edgar default fetcher) with:

  * RETRY with exponential backoff + jitter on transient failures only;
  * rate-limit SPACING (a minimum interval between calls, under SEC's 10 req/s);
  * honoring a `Retry-After` header when the server sends one;
  * per-call LATENCY + outcome METRICS (p50/p95/max, retry count, error breakdown)
    for throughput/observability, emitted through the standard `logging` module.

It is dependency-injected: the edgar functions (`fetch_10k_text`, `lookup_cik`,
`extract_xbrl_facts`, …) all accept a `fetch=` callable, so adopting this is simply
`fetch_10k_text(ticker, fetch=make_robust_fetch())`. No edgar/core code changes; no
model SDK is imported.

WHAT IS AND ISN'T RETRIED
-------------------------
Only TRANSIENT transport failures are retried (see `is_retryable`). Semantic errors
that will never succeed on retry — an unknown ticker, a missing filing, an HTTP 404
or 403 — are raised immediately. Those are also raised by sec.py's own logic AFTER a
fetch returns, so they never even reach this wrapper; the wrapper only guards the raw
network call.
"""
from __future__ import annotations

import logging
import random
import socket
import time
import urllib.error
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

FetchFn = Callable[[str], str]

# HTTP status codes worth retrying: rate limit + transient server errors.
RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})

_LOG = logging.getLogger("aritiq.ingest")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class FetchMetrics:
    """Accumulates throughput/latency/outcome stats across fetch calls.

    One instance can be shared across a whole benchmark run or a request's fetches
    to give an observable picture (how many calls, how slow, how many retries, what
    failed). `summary()` returns a JSON-friendly dict.
    """
    calls: int = 0
    successes: int = 0
    failures: int = 0
    retries: int = 0
    total_latency_s: float = 0.0
    latencies_s: List[float] = field(default_factory=list)
    # outcome tag -> count, e.g. "ok", "http_429", "timeout", "url_error", "http_404"
    outcomes: Dict[str, int] = field(default_factory=dict)

    def _record_latency(self, dt: float) -> None:
        self.total_latency_s += dt
        self.latencies_s.append(dt)

    def _bump(self, tag: str) -> None:
        self.outcomes[tag] = self.outcomes.get(tag, 0) + 1

    @staticmethod
    def _pct(sorted_vals: List[float], p: float) -> float:
        if not sorted_vals:
            return 0.0
        k = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
        return sorted_vals[k]

    def summary(self) -> dict:
        s = sorted(self.latencies_s)
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "retries": self.retries,
            "success_rate": round(self.successes / self.calls, 4) if self.calls else None,
            "latency_s": {
                "mean": round(self.total_latency_s / len(s), 4) if s else 0.0,
                "p50": round(self._pct(s, 50), 4),
                "p95": round(self._pct(s, 95), 4),
                "max": round(s[-1], 4) if s else 0.0,
                "total": round(self.total_latency_s, 4),
            },
            "outcomes": dict(sorted(self.outcomes.items())),
        }


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------

def _outcome_tag(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"http_{exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return "url_error"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    return f"error_{type(exc).__name__}"


def is_retryable(exc: BaseException) -> bool:
    """True iff `exc` is a transient transport failure worth retrying.

    Retryable: HTTP 429/5xx, generic URLError (connection reset/refused/DNS blip),
    socket/timeout errors. NOT retryable: HTTP 404/403/4xx (other than 429) and any
    non-network exception — those will not succeed on retry.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP_STATUS
    if isinstance(exc, urllib.error.URLError):
        # URLError wraps DNS/connection failures; its .reason is often a socket error.
        return True
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError)):
        return True
    return False


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Parse a Retry-After header (seconds form) from an HTTPError, if present."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            ra = exc.headers.get("Retry-After") if exc.headers else None
            if ra is not None:
                return max(0.0, float(int(ra)))
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# The wrapper
# ---------------------------------------------------------------------------

def make_robust_fetch(
    base_fetch: Optional[FetchFn] = None,
    *,
    max_retries: int = 4,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    min_interval: float = 0.0,
    jitter: float = 0.25,
    metrics: Optional[FetchMetrics] = None,
    logger: Optional[logging.Logger] = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    rng: Optional[random.Random] = None,
) -> FetchFn:
    """Return a FetchFn that wraps `base_fetch` with retry/backoff + metrics.

    Parameters (all optional):
      base_fetch   the underlying fetcher (default: edgar's _default_fetch).
      max_retries  additional attempts after the first (4 => up to 5 tries).
      base_delay   first backoff delay in seconds; doubles each retry.
      max_delay    cap on any single backoff delay.
      min_interval minimum seconds between the START of consecutive calls
                   (rate-limit spacing; 0 disables).
      jitter       fractional random jitter added to each backoff (0..1).
      metrics      a FetchMetrics to accumulate into (created if None; always
                   reachable afterwards via the returned fn's `.metrics`).
      logger       logging.Logger (default: "aritiq.ingest").
      sleep/monotonic/rng  injectable for deterministic, fast tests.

    The returned callable has a `.metrics` attribute for inspection.
    """
    # Imported lazily so importing this module never forces a network stack import
    # and so tests can wrap a pure stub without pulling edgar.
    if base_fetch is None:
        from aritiq.edgar.sec import _default_fetch as base_fetch  # type: ignore
    log = logger or _LOG
    m = metrics if metrics is not None else FetchMetrics()
    r = rng or random.Random()
    _last_call_start = {"t": None}  # mutable closure cell

    def _space_rate_limit() -> None:
        if min_interval <= 0:
            return
        last = _last_call_start["t"]
        if last is not None:
            wait = min_interval - (monotonic() - last)
            if wait > 0:
                sleep(wait)
        _last_call_start["t"] = monotonic()

    def _fetch(url: str) -> str:
        attempt = 0
        while True:
            _space_rate_limit()
            m.calls += 1
            t0 = monotonic()
            try:
                out = base_fetch(url)
            except Exception as exc:  # noqa: BLE001 — classify below
                dt = monotonic() - t0
                m._record_latency(dt)
                tag = _outcome_tag(exc)
                m._bump(tag)
                if is_retryable(exc) and attempt < max_retries:
                    attempt += 1
                    m.retries += 1
                    ra = _retry_after_seconds(exc)
                    if ra is not None:
                        delay = min(max_delay, ra)
                    else:
                        delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                        delay += delay * jitter * r.random()
                    log.warning(
                        "SEC fetch transient failure (%s) on %s; retry %d/%d in %.2fs",
                        tag, url, attempt, max_retries, delay)
                    sleep(delay)
                    continue
                # exhausted or non-retryable
                m.failures += 1
                log.error("SEC fetch FAILED (%s) on %s after %d attempt(s)",
                          tag, url, attempt + 1)
                raise
            else:
                dt = monotonic() - t0
                m._record_latency(dt)
                m.successes += 1
                m._bump("ok")
                log.debug("SEC fetch ok on %s in %.3fs (attempt %d)", url, dt, attempt + 1)
                return out

    _fetch.metrics = m  # type: ignore[attr-defined]
    return _fetch
