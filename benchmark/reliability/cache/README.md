# Benchmark caches

The reliability harness caches SEC data on disk so runs are reproducible offline and
a network hiccup never destroys progress. These subdirectories differ in size and in
whether they are committed to git.

## Tracked in git (small, valuable fixtures)

- **`extractions/`** — cached LLM extraction outputs used by the `--replay` path and
  by offline tests. Compact; committed so the suite is reproducible without a model key.
- **`sic/`** — cached SIC-code lookups (one small JSON per ticker) used by the
  peer-comparison layer.

## NOT tracked in git (large, deterministically re-fetchable)

Gitignored (see the repo `.gitignore`) because they are big and can be rebuilt from
the SEC's free APIs at any time:

- **`xbrl/`** — raw `companyfacts` JSON, `_raw_<TICKER>.json` (~321 MB across the
  benchmark set; some large filers are 7–10 MB each).
- **`filings/`** — stripped 10-K filing text per ticker.
- **`runs/`** — per-run result JSON and review CSVs (may embed fetched filing text).

### Regenerate the XBRL / filings caches

```bash
# Re-fetch every filer in filing_set.json from SEC EDGAR (no model key needed;
# this only fetches + caches, it does not call an LLM):
python benchmark/reliability/harness.py --fetch-only

# The XBRL-grounded tools populate cache/xbrl/ on first use; to warm it explicitly:
python benchmark/reliability/xbrl_verify.py            # full filing set
python benchmark/reliability/xbrl_verify.py AAPL BAC   # a subset
```

Tests that read the raw `xbrl/` cache by real ticker **skip automatically** when the
cache is absent (see `tests/conftest.py`), so a fresh clone's `pytest` is green; run
the commands above to enable those tests locally.
