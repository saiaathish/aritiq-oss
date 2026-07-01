"""
Tests for the ingestion robustness layer (aritiq/ingest/robust_fetch.py).

All deterministic and offline: the base fetch is a stub, and sleep/monotonic/rng are
injected so there is no real waiting and no real network. These confirm the actual
production properties — retry on transient errors, NO retry on fatal ones, bounded
exponential backoff, Retry-After honoring, rate-limit spacing, and metrics — rather
than just that the code runs.
"""
import socket
import urllib.error

import pytest

from aritiq.ingest import make_robust_fetch, FetchMetrics, is_retryable, RETRYABLE_HTTP_STATUS


class _Clock:
    """Deterministic monotonic clock + sleep recorder."""
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class _Rng:
    """Zero-jitter RNG so backoff delays are exact."""
    def random(self):
        return 0.0


def _http_error(code):
    return urllib.error.HTTPError(url="http://x", code=code, msg="e", hdrs=None, fp=None)


# ---- classification --------------------------------------------------------

def test_is_retryable_transport_errors():
    assert is_retryable(_http_error(429))
    assert is_retryable(_http_error(503))
    assert is_retryable(urllib.error.URLError("conn reset"))
    assert is_retryable(socket.timeout("timed out"))
    assert is_retryable(TimeoutError())


def test_is_not_retryable_fatal():
    assert not is_retryable(_http_error(404))
    assert not is_retryable(_http_error(403))
    assert not is_retryable(ValueError("bad ticker"))
    assert 429 in RETRYABLE_HTTP_STATUS and 404 not in RETRYABLE_HTTP_STATUS


# ---- retry / backoff behavior ---------------------------------------------

def test_retries_transient_then_succeeds():
    clock = _Clock()
    calls = {"n": 0}

    def base(url):
        calls["n"] += 1
        if calls["n"] < 3:          # fail twice, then succeed
            raise urllib.error.URLError("temporary")
        return "OK"

    f = make_robust_fetch(base, max_retries=4, base_delay=0.5, jitter=0.0,
                          sleep=clock.sleep, monotonic=clock.monotonic, rng=_Rng())
    assert f("http://x") == "OK"
    assert calls["n"] == 3
    assert f.metrics.successes == 1
    assert f.metrics.retries == 2
    # exponential backoff: 0.5, then 1.0
    assert clock.slept == [0.5, 1.0]


def test_fatal_error_is_not_retried():
    calls = {"n": 0}

    def base(url):
        calls["n"] += 1
        raise _http_error(404)

    clock = _Clock()
    f = make_robust_fetch(base, max_retries=4, sleep=clock.sleep,
                          monotonic=clock.monotonic, rng=_Rng())
    with pytest.raises(urllib.error.HTTPError):
        f("http://x")
    assert calls["n"] == 1           # no retries on a 404
    assert clock.slept == []
    assert f.metrics.failures == 1
    assert f.metrics.outcomes.get("http_404") == 1


def test_gives_up_after_max_retries_and_raises():
    calls = {"n": 0}

    def base(url):
        calls["n"] += 1
        raise _http_error(503)

    clock = _Clock()
    f = make_robust_fetch(base, max_retries=3, base_delay=1.0, jitter=0.0,
                          max_delay=8.0, sleep=clock.sleep,
                          monotonic=clock.monotonic, rng=_Rng())
    with pytest.raises(urllib.error.HTTPError):
        f("http://x")
    assert calls["n"] == 4           # 1 initial + 3 retries
    assert f.metrics.retries == 3
    assert f.metrics.failures == 1
    # backoff doubles then caps: 1, 2, 4
    assert clock.slept == [1.0, 2.0, 4.0]


def test_backoff_is_capped_by_max_delay():
    def base(url):
        raise _http_error(500)

    clock = _Clock()
    f = make_robust_fetch(base, max_retries=5, base_delay=1.0, max_delay=3.0,
                          jitter=0.0, sleep=clock.sleep, monotonic=clock.monotonic,
                          rng=_Rng())
    with pytest.raises(urllib.error.HTTPError):
        f("http://x")
    # 1, 2, then capped at 3, 3, 3
    assert clock.slept == [1.0, 2.0, 3.0, 3.0, 3.0]


def test_retry_after_header_is_honored():
    hdrs = {"Retry-After": "7"}
    err = urllib.error.HTTPError(url="http://x", code=429, msg="slow down",
                                 hdrs=hdrs, fp=None)
    calls = {"n": 0}

    def base(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise err
        return "OK"

    clock = _Clock()
    f = make_robust_fetch(base, max_retries=2, base_delay=0.5, max_delay=30.0,
                          jitter=0.0, sleep=clock.sleep, monotonic=clock.monotonic,
                          rng=_Rng())
    assert f("http://x") == "OK"
    assert clock.slept == [7.0]       # used Retry-After, not the 0.5 base backoff


# ---- rate-limit spacing ----------------------------------------------------

def test_min_interval_spaces_consecutive_calls():
    def base(url):
        return "OK"

    clock = _Clock()
    f = make_robust_fetch(base, min_interval=0.5, jitter=0.0, sleep=clock.sleep,
                          monotonic=clock.monotonic, rng=_Rng())
    f("http://a")   # first call: no wait
    f("http://b")   # immediately after: must space by 0.5
    assert clock.slept == [0.5]


# ---- metrics ---------------------------------------------------------------

def test_metrics_summary_shape_and_counts():
    calls = {"n": 0}

    def base(url):
        calls["n"] += 1
        if calls["n"] == 2:
            raise urllib.error.URLError("blip")   # one transient, retried
        return "OK"

    clock = _Clock()
    m = FetchMetrics()
    f = make_robust_fetch(base, metrics=m, jitter=0.0, sleep=clock.sleep,
                          monotonic=clock.monotonic, rng=_Rng())
    f("http://a")   # ok first try
    f("http://b")   # fails once (URLError), then ok
    s = m.summary()
    assert s["successes"] == 2
    assert s["retries"] == 1
    assert s["calls"] == 3           # 2 logical fetches, 3 base calls
    assert s["outcomes"]["ok"] == 2
    assert s["outcomes"]["url_error"] == 1
    assert "p95" in s["latency_s"] and "p50" in s["latency_s"]
    assert m is f.metrics


def test_shared_metrics_across_two_fetchers():
    m = FetchMetrics()
    clock = _Clock()
    a = make_robust_fetch(lambda u: "A", metrics=m, sleep=clock.sleep,
                          monotonic=clock.monotonic, rng=_Rng())
    b = make_robust_fetch(lambda u: "B", metrics=m, sleep=clock.sleep,
                          monotonic=clock.monotonic, rng=_Rng())
    a("http://a"); b("http://b")
    assert m.successes == 2 and m.calls == 2
