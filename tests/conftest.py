"""
Shared pytest fixtures / collection hooks for the Aritiq test suite.

Cache-dependent skip
--------------------
A few offline tests read the LARGE raw SEC companyfacts cache
(`benchmark/reliability/cache/xbrl/_raw_<TICKER>.json`) by real ticker. That cache
(~321 MB) is deterministically re-fetchable and is therefore gitignored (see
benchmark/reliability/cache/README.md), so it may be absent on a fresh clone before
the harness regenerates it. Rather than fail the suite in that situation, we SKIP
those specific tests when their required raw files are missing. On a machine where
the cache is present (the normal dev/benchmark box) they run exactly as before.

This is done via a collection hook so the individual test files don't need editing.
"""
import os

import pytest

_XBRL_CACHE = os.path.join(os.path.dirname(__file__), "..",
                           "benchmark", "reliability", "cache", "xbrl")

# test name -> raw-cache tickers it needs present to run
_CACHE_DEPENDENT = {
    "test_noncomparable_sic_class_is_declined_wholesale": ["PLD", "SPG", "AVB"],
    "test_comparable_group_verifies_winner_and_catches_wrong_claim":
        ["PLTR", "CRM", "ORCL", "DDOG", "U"],
}


def _missing(tickers):
    return [t for t in tickers
            if not os.path.exists(os.path.join(_XBRL_CACHE, f"_raw_{t}.json"))]


def pytest_collection_modifyitems(config, items):
    for item in items:
        need = _CACHE_DEPENDENT.get(item.name)
        if not need:
            continue
        gone = _missing(need)
        if gone:
            item.add_marker(pytest.mark.skip(
                reason=f"raw XBRL cache absent for {gone} "
                       f"(re-fetchable; see benchmark/reliability/cache/README.md)"))
