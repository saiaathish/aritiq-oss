# Aritiq Hardening Pass — Status (honest accounting)

This file states, item by item, what is closed with evidence and what is **not yet
complete**. Nothing here claims real-world accuracy, readiness, or "done" beyond
what the numbers below support.

---

# Phase 4 — enterprise features

Written 2026-07-02. Closes roadmap Phase 4 within deliberately narrow scope: small-team workspace identity, audit history, watchlists, API-key dashboard, and webhook delivery plumbing. No OAuth providers, billing/subscriptions, mobile app, or full RBAC.

## What was built

`aritiq/enterprise.py` adds a SQLite-backed enterprise layer outside `aritiq/core/`: orgs, users, per-org API keys, per-key usage events, persisted audit history, watchlists, webhooks, and webhook deliveries. It imports no model SDK and performs no verification.

Backend API additions in `backend/app.py`:

- `POST /enterprise/bootstrap` creates a minimal org/user plus initial API key.
- `GET /enterprise/team` returns current org/users/auth context.
- `GET/POST /enterprise/api-keys`, `POST /enterprise/api-keys/{id}/rotate`, `POST /enterprise/api-keys/{id}/deactivate` provide the API-key dashboard surface: usage, limits, rotation, status/history.
- `GET /enterprise/audits`, `GET /enterprise/audits/{id}` list/reopen persisted completed audits. `/audit` and `/audit-ticker` now store successful audit payloads per org.
- `GET/POST /enterprise/watchlists`, `POST /enterprise/watchlists/check` store watched tickers and reuse Phase 3 `get_timeline()` as the only filing detector. No separate filing-detection system was invented.
- `GET/POST /enterprise/webhooks`, `POST /enterprise/webhooks/dispatch` store generic webhook targets and dispatch queued filing events with retry/backoff.

Auth/rate limiting changed explicitly: existing `ARITIQ_API_KEYS` still works as legacy shared-key mode, but enterprise keys are now first-class. If an enterprise key authenticates, rate limiting uses `key:{api_key_id}` and that key's `limit_per_minute`; IP fallback remains only for local/dev unauthenticated mode. Invalid supplied keys no longer fall back to default workspace.

## Measured result (reproducible)

`python benchmark/reliability/enterprise_phase4.py --md benchmark/reliability/ENTERPRISE_PHASE4_REPORT.md`

Deterministic local SQLite run, no model calls and no SEC network:

- `workspace_created`: true
- `users`: 1
- `api_keys_total`: 3 (initial disabled by rotation, secondary, rotated replacement)
- `rotated_old_key_rejected`: true
- `new_rotated_key_accepted`: true
- `usage_calls_recorded`: 1
- `audit_history_count`: 1
- `audit_detail_reopens`: true
- `watchlist_count`: 1
- `webhook_count`: 1
- `webhooks_queued`: 1
- first webhook dispatch: `{"delivered": 0, "failed_or_retrying": 1}`
- second dispatch after retry due: `{"delivered": 1, "failed_or_retrying": 0}`

Tests: `tests/test_enterprise_phase4.py` adds 5 deterministic cases covering team/API-key dashboard/per-key limit, rotation rejecting old key, replay audit persistence/list/detail reopen, watchlist timeline reuse + webhook queueing, and webhook retry→success. Targeted backend regression set passed: **17 passed, 1 warning** (`tests/test_backend_timeline.py`, `tests/test_backend_dashboard.py`, `tests/test_backend_analyst.py`, `tests/test_backend_graph_serialization.py`, `tests/test_backend_phase_demos.py`, `tests/test_enterprise_phase4.py`). Full suite passed: **515 passed, 2 skipped, 1 warning**.

## Honest boundary

- This is a minimal identity/org model, not full RBAC. Every user in an org effectively shares the workspace.
- Bootstrap is a local/team bootstrap primitive, not a production sign-up/auth provider flow. Google/Microsoft OAuth remain explicitly out of scope.
- Audit history persists completed payloads exactly as produced; it does not add new verification or re-run old audits.
- Watchlists detect "new filing" by comparing the latest accession returned by Phase 3 timeline. They do not poll SEC continuously by themselves; a caller/scheduler must invoke `/enterprise/watchlists/check`.
- Webhooks are generic HTTP POST targets. Slack/email-specific providers are not built; retry/backoff is local durable delivery state, not a managed queue.

## Reproduce

```bash
python benchmark/reliability/enterprise_phase4.py --md benchmark/reliability/ENTERPRISE_PHASE4_REPORT.md
pytest -q tests/test_enterprise_phase4.py
pytest -q tests/test_backend_timeline.py tests/test_backend_dashboard.py tests/test_backend_analyst.py tests/test_backend_graph_serialization.py tests/test_backend_phase_demos.py tests/test_enterprise_phase4.py
```

---

# Phase 5 — expanded evaluation suite (XBRL-grounded lane)

Written 2026-07-02. Closes Phase 5 only for deterministic SEC-companyfacts/XBRL evaluation. No live prose-extraction expansion is claimed because this environment had no `ARITIQ_PROVIDER`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or `GEMINI_API_KEY`; creating new LLM extraction caches for 32 brand-new filers was therefore impossible without fabricating results.

## What was built

`benchmark/reliability/filing_set.json` expanded from **83** to **115** US 10-K filers. Added names were selected from the actual `REPORT_LATEST.md` gaps, not ticker familiarity:

- banks/brokers/custody/specialty credit: C, MS, USB, PNC, TFC, COF, NTRS, STT;
- insurers/brokers/life/P&C: BRO, AON, AJG, HIG, CINF, LNC;
- regulated utilities: AEP, EXC, SRE, XEL, PEG, ED;
- REIT subtypes: EQR, PSA, WY, IRM, ESS, MAA;
- capital-intensive industrial/defense/airline/retail stress: DE, ETN, EMR, NOC, LUV, TGT.

ADRs / 20-F / 40-F issuers deliberately left out: current `aritiq/edgar/xbrl.py` companyfacts extraction is US-GAAP 10-K/10-Q centered. Forcing foreign private issuers would mix benchmark expansion with issuer-form support.

Added `benchmark/reliability/xbrl_calibration.py`: reproducible calibration report over `xbrl_verify.py` run JSON. Confidence definition uses existing verifier state only:

- **high** = decisive math verdict (`VERIFIED` or `WRONG_MATH`);
- **medium** = conservative verifier decline (`INSUFFICIENT_EVIDENCE`);
- **low** = no XBRL claim / fetch failure.

No invented model confidence score. Precision/FPR/recall are automatic operating metrics over this XBRL lane:

- precision = `VERIFIED / (VERIFIED + WRONG_MATH)`;
- false-positive rate = `WRONG_MATH / (VERIFIED + WRONG_MATH)`;
- verification recall/coverage = `VERIFIED / all emitted XBRL claims`.

## Measured result (reproducible)

Commands:

```bash
python3 benchmark/reliability/xbrl_verify.py --md benchmark/reliability/XBRL_REPORT.md
python3 benchmark/reliability/xbrl_calibration.py benchmark/reliability/cache/runs/xbrl_run_1782971461.json --md benchmark/reliability/PHASE5_XBRL_CALIBRATION.md
```

Expanded deterministic XBRL run:

- **115 filers**.
- **354 XBRL-grounded claims**.
- Verdicts: **281 VERIFIED**, **63 INSUFFICIENT_EVIDENCE**, **10 WRONG_MATH**.
- Statement types: **180 eps_reconciliation**, **88 balance_sheet_identity**, **86 cash_flow_tie_out**.
- Precision (`VERIFIED / VERIFIED+WRONG_MATH`): **96.6%**.
- False-positive rate (`WRONG_MATH / VERIFIED+WRONG_MATH`): **3.4%**.
- Verification recall / coverage (`VERIFIED / all emitted claims`): **79.4%**.
- Decline rate (`INSUFFICIENT_EVIDENCE / all emitted claims`): **17.8%**.
- Confidence calibration: high tier **281 VERIFIED / 10 WRONG_MATH**; medium tier **63 INSUFFICIENT_EVIDENCE**.

WRONG_MATH root-cause queue (all EPS-only XBRL-lane convictions; not human-adjudicated issuer-error claims):

| Ticker | Sector | Operands `[eps, numerator, shares]` | Computed EPS | Root cause |
|---|---|---:|---:|---|
| BAC | Banking | `[3.81, 29055000000, 7680900000]` | 3.7828 | XBRL EPS operands do not reconcile within existing per-share rounding tolerance; accounting-scope review required before calling filer error. |
| GS | Banking | `[51.95, 16300000000, 312700000]` | 52.1266 | same. |
| T | Telecom | `[3.04, 21889000000, 7169000000]` | 3.0533 | same. |
| DUK | Utility | `[6.31, 4912000000, 777000000]` | 6.3218 | same; appears in both EPS variants. |
| DUK | Utility | `[6.31, 4912000000, 777000000]` | 6.3218 | duplicate basic/diluted reported same values. |
| ETSY | E-commerce (mid-cap) | `[1.39, 162982000, 124114000]` | 1.3132 | same. |
| DDOG | Software (growth) | `[0.31, 107741000, 363472000]` | 0.2964 | same. |
| GEV | Industrials (spinoff) | `[17.92, 4884000000, 272000000]` | 17.9559 | same. |
| NTRS | Banking | `[8.78, 1695100000, 191358026]` | 8.8583 | same. |
| NTRS | Banking | `[8.74, 1695100000, 192246525]` | 8.8173 | same. |

Tests added: `tests/test_xbrl_calibration.py` pins the 115-filer/354-claim run totals, calibration percentages, and report boundary text.

## Honest boundary

- This does **not** claim the original prose-extraction reliability harness has been live-expanded to 115 filers. It could not be, because no model provider key was available for new extraction caches.
- `REPORT_LATEST.md` remains the current 83-filer prose-extraction benchmark; `PHASE5_XBRL_CALIBRATION.md` is the expanded deterministic SEC-companyfacts lane.
- WRONG_MATH rows above are calibration/root-cause queue entries, not adjudicated true filer mistakes. Treating any as real issuer arithmetic error requires filing-level accounting review.
- `aritiq/core/` remains model-SDK-free; Phase 5 added no model call path.

---

# Phase 3 — item 3: AI Analyst Mode

Written 2026-07-02. Closes handoff Phase 3 item 3 (build last, highest risk —
"the one place a model touches output directly"). `aritiq/analyst.py` lives
OUTSIDE `aritiq/core/`; the verifier remains model-free and the module itself
imports no model SDK (the completion function is injected, defaulting lazily
to the extractor's existing provider plumbing).

## What was built — a three-layer deterministic boundary

1. **The ledger.** Only VERIFIED claims become facts the model may see.
   Every other status (WRONG_MATH, INSUFFICIENT_EVIDENCE, UNSUPPORTED_NUMBER,
   UNCHECKED, AMBIGUOUS, CONFLICT, PROPAGATED_ERROR, NEEDS_REVIEW) goes to a
   blocked list whose numeric values are **digit-stripped** before anything
   downstream — the model cannot leak a number it never receives (tested:
   blocked values are absent from the prompt even when a related verified
   fact makes the model run; the blocked STATUS is disclosed, the value is not).
2. **Pre-model refusal gates** (all deterministic, all `model_called=False`):
   - *topic-precision*: if any topic the question touches has blocked claims
     and no verified claim for that topic, refuse — a verified fact on an
     ADJACENT topic is not license to narrate an unverified one;
   - *topic-coverage*: if any topic the question names has no claims at all,
     refuse rather than produce a fluent non-answer from adjacent facts;
   - *no-data*: nothing relevant at all → refuse.
   Both topic gates were added because THE AT-SCALE MEASUREMENT CAUGHT THE
   HOLES (v0 answered "does cash tie out to balance-sheet cash?" from a
   verified balance-sheet fact while the cash tie-out was blocked — 82 gate
   failures on real data). Each hole is now a named regression test. This is
   recorded deliberately: the measurement catching the design's first attempt
   is the discipline working, not an embarrassment to hide.
3. **Post-model number whitelist.** Every numeric token in the model's answer
   must match a value from the verified facts it was given
   (rounding-tolerant; prose counters ≤12 allowed); every citation must name
   a provided fact; uncited or unparseable output is rejected. A fluent
   hallucination is withheld and replaced with the guard's reason.

Surfacing: `POST /analyst {ticker, question}` — refusals work KEYLESS and
cost zero tokens (the gates run before narration); an answerable question
with no configured key is a clear 503, never a keyless guess.

## Measured result (reproducible)

`python benchmark/reliability/analyst_eval.py --live --md benchmark/reliability/ANALYST_REPORT.md`
(exit code enforces the gates):

**Deterministic sweep** — 78 filers × 3 questions = 234 pairs against the
real replay verdicts, answer path exercised end-to-end via a deterministic
citing stub (so `answered` also proves the whitelist passes on real values):
- Outcomes: **answered 136 / refused_blocked 75 / refused_no_data 23**.
- **The adversarial test, at scale: 72/72** (filer, question) pairs whose
  topic has only non-VERIFIED verdicts refused BEFORE any model call —
  every one a real filer whose relevant number is genuinely bad
  (TSLA/META/KO restricted-cash among them). Blocking statuses named:
  INSUFFICIENT_EVIDENCE 71, UNSUPPORTED_NUMBER 10.
- Zero answers over topics with no verified facts; zero uncited answers.
  **0 hard-gate failures.**

**Live narration** (gemini, the configured provider, from this sandbox):
- AAPL balance sheet → **answered**, cited [F1], numbers 359,241 / 285,508 /
  73,733 all from the verified fact — passed the whitelist.
- JPM balance sheet → **answered**, cited. PLTR EPS → **answered**, cited
  [F2, F3].
- AAPL EPS → **refused_blocked pre-model** (its EPS is INSUFFICIENT_EVIDENCE
  in the adjudicated replay).
- **Live adversarial: TSLA cash → refused_blocked, model_called=False** —
  zero tokens spent narrating an unverifiable number.

Tests: `tests/test_analyst.py` (17 offline cases with fake models: ledger
composition, digit-stripping, THE adversarial case proven with a stub that
raises if invoked, both topic-gate regressions, hallucinated-number/invented-
citation/uncited/unparseable rejection, rounding+counter tolerance) +
`tests/test_backend_analyst.py` (4 cases). Full suite **509 passed, 1
skipped** (was 455 at session start — +54 across the three Phase 3 items,
zero regressions). Firewall: `aritiq/core/` and `aritiq/analyst.py` import no
model SDK (grep clean).

## Honest boundary (what is NOT proven)

- **Wording, not truth-of-wording.** The guards pin WHICH numbers can be
  spoken and WHEN to refuse. They do not pin phrasing: a model could
  mis-CHARACTERIZE a verified number in words ("declined" for a rise) without
  using a non-whitelisted numeral. Narrative-faithfulness checking is future
  work; the live samples looked faithful but 4 samples prove reachability,
  not prose quality.
- Relevance matching is deterministic keyword/overlap (v1). A question
  phrased entirely without topic words refuses as no-data rather than risking
  a wrong route — conservative, closed-world by construction. Multi-topic
  questions require every named topic verified-covered, which can over-refuse
  (e.g. "why did margin decrease" needs percent_change coverage too).
- The whitelist allows integer prose counters ≤12 and rounding to ≤3
  decimals; a hallucination inside those tolerances (e.g. asserting "3" of
  something) would pass numerically. It cannot smuggle a financial figure.
- The backend endpoint answers only over the 83 cached benchmark filers'
  verdicts; live-audit-then-ask wiring is future work.

## Changed files

- `aritiq/analyst.py` (new) — ledger, gates, whitelist, provider-agnostic.
- `benchmark/reliability/analyst_eval.py` (new) — 234-pair sweep + live
  narration; `ANALYST_REPORT.md` (new).
- `backend/app.py` — `POST /analyst` (keyless refusals; 503 over guessing).
- `tests/test_analyst.py`, `tests/test_backend_analyst.py` (new, 21 tests).

## Reproduce

```bash
pytest -q                                                      # 509 passed, 1 skipped
python benchmark/reliability/analyst_eval.py                   # 72/72 refusals, exit 0
python benchmark/reliability/analyst_eval.py --live            # + live narration (needs key)
```

---

# Phase 3 — item 2: institutional risk dashboard

Written 2026-07-02. Closes handoff Phase 3 item 2 (build second). Presentation
logic over numbers that already exist — nothing recomputed, nothing new
verified, `aritiq/core/` untouched.

## What was built

`aritiq/dashboard.py` (new, outside `aritiq/core/` — presentation, not
verification) assembles five panels per company:

1. **Verification Score** — calls the REAL `core/score.py::compute_score` on
   the recorded verdicts (minimal Claim/VerificationResult objects rebuilt
   from harness claim records so weights/exclusions stay in exactly one
   place). Weighted + unweighted shown as a pair; the vacuous-score guard
   passes through as UNASSESSED, never a clean 100.
2. **Evidence Coverage** — NEW metric, decided **deterministic** (per the
   roadmap's explicit fork): share of claims whose rule-required evidence
   flags were all present in the extracted claim (`evidence_emitted`). Stated
   as a property of extraction grounding, not of the numbers.
3. **Disclosure Quality** — NEW metric, decided **deterministic**: of the
   INSUFFICIENT_EVIDENCE declines, the share that is *explained* — required
   disclosure context present in the grounded claim OR SEC XBRL adjudicated
   the figure. Panel copy states it is a JOINT property of filer disclosure
   and extraction grounding, not a pure filer attribute. (A model-assisted
   version would live outside core and be labeled; v1 deliberately isn't.)
4. **Cross-Year Consistency** — derived from `company_memory.py`'s existing
   signals: % of usable multi-year series with no detected friction (dropped
   non-comparable spans, fallback-tag definition risk). `split_sensitive` is
   surfaced but NOT penalized — it flags every per-share concept as a class,
   so penalizing it would deduct identical points from every EPS-reporting
   filer (decision documented in code + tested).
5. **Restatement Risk** — counts of `core/restatement.py`'s RestatementType
   language classifications on CONFLICT results. **No cross-document input ⇒
   UNASSESSED**, never "low risk"; ran-and-found-none is a distinct state
   with copy saying "no conflicts DETECTED", not "no restatement occurred".
   Never a fabricated 0-100.

Surfacing: `GET /dashboard/{ticker}` (backend, deterministic, keyless — built
from the newest committed replay run + cached company memory; 404 for tickers
outside the cache rather than fabricating panels) and
`frontend/components/RiskDashboard.tsx` (renders UNASSESSED/NO DATA states as
states; boundary line ships with the data).

## Measured result (reproducible)

`python benchmark/reliability/risk_dashboard.py --md benchmark/reliability/DASHBOARD_REPORT.md`
(exit code enforces the agreement gates):

- **78 filers dashboarded** (the filers with prose claims in the newest replay
  run; the 5 extraction-empty filers are visible as absent, not painted over).
- **Agreement gate 1 — totals:** dashboard-recovered verdict totals equal the
  run's own: **VERIFIED 159 / INSUFFICIENT_EVIDENCE 70 / UNSUPPORTED 9 /
  WRONG_MATH 0** — exactly REPORT_LATEST.md's established numbers. AGREE.
- **Agreement gate 2 — known-decline filers not clean:** TSLA, META, KO (the
  XBRL-confirmed restricted-cash scope differences from Phase 1 item 2) each
  show ≥1 INSUFFICIENT_EVIDENCE in the verification panel AND their
  disclosure-quality panel classifies those declines as EXPLAINED (the
  restricted-cash disclosure reached the claim). A filer with known declines
  cannot silently present as clean. PASS.
- **Agreement gate 3 — no fabricated restatement risk:** all 78 restatement
  panels are UNASSESSED on this single-filing run. PASS.
- **Agreement gate 4 — shape:** all 78 dashboards have exactly the five
  panels, all `deterministic`. PASS. **0 gate failures overall.**
- Real differentiation, not a flat metric: consistency ranges from 11.1 (AMD —
  heavy dropped-span history) through 40.0 (AAPL) to 100.0 (PLTR).
- Tests: `tests/test_dashboard.py` (13 offline cases pinning every panel
  definition, the vacuous-guard passthrough, split-not-penalized, and
  unassessed-never-low-risk) + `tests/test_backend_dashboard.py` (2 cases).
  Full suite **488 passed, 1 skipped** (+15, zero regressions). Firewall clean
  (`aritiq/dashboard.py` imports core types/functions and edgar memory — no
  model SDK anywhere in the chain).

## Honest boundary (what is NOT proven)

- Presentation only. The dashboard adds no verification; this measurement
  proves the presentation does not DISTORT upstream numbers, not that the
  upstream numbers are more right than STATUS.md already claims.
- Disclosure Quality conflates filer disclosure with extraction grounding by
  construction (stated on the panel). Separating them would need labeled
  extraction-quality data that does not exist yet.
- Consistency's "clean" definition is one defensible aggregation of the
  existing gates, not a standard. The raw signal counts ship in `components`
  so a reviewer can re-weight them.
- Restatement Risk has no real cross-document conflict data in this
  measurement (single-filing benchmark); its populated path is pinned by
  offline tests only. Measuring it on real multi-filing conflicts is future
  work (needs the multi-doc pipeline run over real restatement pairs).
- The backend endpoint serves only the 83 cached benchmark filers; it 404s
  otherwise instead of running a live audit.

## Changed files

- `aritiq/dashboard.py` (new) — five deterministic panels.
- `benchmark/reliability/risk_dashboard.py` (new) — agreement-gate
  measurement; `DASHBOARD_REPORT.md` (new).
- `backend/app.py` — `GET /dashboard/{ticker}` + replay-record loader.
- `frontend/components/RiskDashboard.tsx` (new), `frontend/lib/types.ts`,
  `frontend/lib/api.ts` — UI rendering states as states (typecheck clean).
- `tests/test_dashboard.py`, `tests/test_backend_dashboard.py` (new, 15 tests).

## Reproduce

```bash
pytest -q                                                      # 488 passed, 1 skipped
python benchmark/reliability/risk_dashboard.py                 # 4 gates, exit 0
cd frontend && npm run typecheck
```

---

# Phase 3 — item 1: SEC filing timeline

Written 2026-07-02. Closes handoff Phase 3 item 1 (build first, lowest risk).
Sequencing work only — no new verification logic, `aritiq/core/` untouched.

## What was built

`aritiq/edgar/timeline.py` sequences a company's filings by type and date from
the SEC submissions feed (`data.sec.gov/submissions/CIK{cik}.json` →
`filings.recent`), following the exact `sic.py` pattern: plain HTTP, cached
JSON (`cache/timeline/`), 0.12s throttle, never raises out of a batch loop
(`fetch_error` recorded instead), failures never cached. Form 4 ownership
detail REUSES `form4.py` (`form4_events_with_ownership` wraps
`fetch_recent_form4_transactions`); no ownership parsing was rebuilt.

**The honest-coverage rule is the feature, not a footnote.** Every event
carries a `verification_coverage` label from a closed, tested enum:

- `full_financial_verification` — 10-K, 10-Q only (the measured forms).
- `partial_financial_verification` — 8-K **with Item 2.02 in the feed's
  `items` field** (the only 8-K variant carrying XBRL financials, per Round 7).
  An 8-K *without* 2.02 is `listed_only` — finer-grained than a blanket
  "8-K = partial" claim would be.
- `ownership_data_only` — Form 4: transactions parsed from the filer's XML,
  explicitly NOT financially verified.
- `listed_only` — everything else (DEF 14A, S-1, 13D/13G, 13F, Forms 3/5, 144,
  unknown/future forms) **and all amendments**: 10-K/A does NOT inherit 10-K's
  coverage, because the benchmark measured "10-K", not "10-K/A".

Surfacing: `GET /timeline/{ticker}` (backend/app.py, behind `require_api_key`)
ships `COVERAGE_LEGEND` in every response so no client invents its own claim;
`frontend/components/FilingTimeline.tsx` renders the coverage statement as
always-visible copy plus a per-event badge. README gained a filing-timeline
section stating the same boundary.

## Measured result (reproducible)

`python benchmark/reliability/filing_timeline.py --md benchmark/reliability/TIMELINE_REPORT.md`
(exit code enforces the gates — a gate failure fails the run):

- **83/83 filers** in the reliability set built a timeline; 0 fetch failures.
- **126,492 events sequenced** (spans 1994-02-11 → 2026-07-01). Coverage
  breakdown: 2,375 full (10-K/10-Q), 2,407 partial (8-K w/ Item 2.02, out of
  7,837 8-Ks total — the 2.02 refinement is doing real work), 42,752 ownership
  (Form 4), 78,958 listed-only.
- **0 integrity-gate failures** across all 83: every filing date ISO-parses,
  every timeline sorted newest-first, every accession matches the EDGAR
  format, every event's coverage label is in the closed enum, and every 8-K
  labeled partial actually lists Item 2.02.
- **Independent spot-check 3/3 PASS** (AAPL, JPM, WELL): the latest 10-K's
  accession + filing date agree between the submissions JSON and SEC's
  *separate* browse-edgar Atom endpoint — the reproducible version of
  "hand-check against EDGAR" (AAPL 0000320193-25-000079 / 2025-10-31,
  JPM 0001628280-26-008131 / 2026-02-13, WELL 0000766704-26-000010 /
  2026-02-12).
- Tests: `tests/test_timeline.py` (14 offline cases: coverage mapping incl.
  amendments/unknowns/8-K-item exactness, sort + tiebreak, filter/limit,
  cache-poisoning prevention, cache-hit no-refetch, document URLs, fetch
  failure, ragged-feed columns) + `tests/test_backend_timeline.py` (4 cases:
  response shape, legend ships with data, filters, 404). Full suite
  **473 passed, 1 skipped** (was 455 — +18, zero regressions). Firewall clean.

## Honest boundary (what is NOT proven)

- This proves **sequencing** — types, dates, accessions, links — not
  verification. Financial verification coverage is exactly the per-form label;
  the timeline adds no new verified numbers anywhere.
- The submissions `recent` window is the most recent 1,000 filings OR the last
  full year, whichever is more (measured: AAPL/WELL ≈1,000 back to 2015; JPM
  25,252 covering one year of structured-notes prospectuses). Older filings
  live in paginated archives that v1 does NOT fetch; `has_older_filings`
  surfaces the truncation.
- The spot-check covers the latest 10-K for 3 filers across two SEC endpoints;
  it is not a per-event audit of all 126,492 entries.
- `form4_events_with_ownership` is network-heavy (one index.json + one XML per
  filing, straight from `form4.py`) and was smoke-level exercised, not
  benchmark-measured; the Form 4 events *in the timeline itself* come from the
  submissions feed and are fully covered by the gates above.

## Changed files

- `aritiq/edgar/timeline.py` (new) — timeline + coverage labels + Form 4 reuse.
- `benchmark/reliability/filing_timeline.py` (new) — 83-filer measurement with
  integrity gates + cross-endpoint spot-check; `TIMELINE_REPORT.md` (new).
- `backend/app.py` — `GET /timeline/{ticker}` (legend ships with data).
- `frontend/components/FilingTimeline.tsx` (new), `frontend/lib/types.ts`,
  `frontend/lib/api.ts` — UI with always-visible coverage copy (typecheck
  clean; same render-validation boundary as the Phase 2 graph UI).
- `tests/test_timeline.py`, `tests/test_backend_timeline.py` (new, 18 tests).
- `README.md` — filing-timeline section under the filing-types table.

## Reproduce

```bash
pytest -q                                                    # 473 passed, 1 skipped
python benchmark/reliability/filing_timeline.py              # gates + spot-check, exit 0
cd frontend && npm run typecheck
```

## ROUND 8 — institutional feature push (multi-period trends, peer comparison, audit export)

Three features aimed at institutional credibility, each additive, each leaving all
prior work intact. Every number below is reproducible by re-running the named script.

### Feature 1 — multi-period trend verification — MECHANISM PROVEN

**What was built.** `aritiq/edgar/xbrl_history.py` reads the FULL reporting history
for a concept straight out of the already-cached `companyfacts` response (zero new
fetching — the series was always in the JSON, just unused across periods). It hands
the chronological `(period_end, value)` series to the EXISTING, unmodified temporal
checks (`check_trend_direction`, `check_superlative`, `check_consecutive_count`) and
the EXISTING `percent_change` arithmetic. No new verifier logic; `aritiq/core/` is
untouched and still imports no model SDK (firewall test green).

**Measured — `python benchmark/reliability/xbrl_trends.py` over all 78 cached filers:**
- **78/78 filers had usable multi-year series** (revenue + net income). Zero fetch
  failures — all from cache.
- Claims are GENERATED FROM THE REAL DATA (compute the real YoY %, real trend
  direction, real consecutive-increase run from the actual XBRL values, then assert
  it) with a NEGATIVE control planted beside each (assert the opposite / an overstated
  count / a wrong %).
- **Positive controls (real claim → must VERIFY): 468/468 (100%).**
- **Negative controls (wrong claim → must be caught as WRONG_MATH): 314/314 (100%).**
- Verdict totals across all generated claims: `VERIFIED 403, WRONG_MATH 379` (the
  WRONG_MATH are the intentional negative controls plus superlative-not-max cases).

**Two real comparability bugs found and GATED (not hidden):**
1. **Fiscal-year-change / stub periods.** A concept's series carries quarters, YTD
   cumulatives, and (for filers who changed fiscal year end) short stub periods. Comparing
   a stub "year" against full years is a silent apples-to-oranges error. `xbrl_history`
   keeps only spans inside a tight annual window (340–380 days) and RECORDS how many
   points it dropped (`dropped_noncomparable_spans`). Across the first 20 filers, 144
   non-annual revenue spans were dropped. Regression-tested (`test_fiscal_year_change_stub_is_dropped`).
2. **Share-count comparability across stock splits.** Per-share concepts (EPS, shares)
   are NOT comparable across a split unless restated; XBRL facts are as-filed. Real case
   found live: **NVDA `shares_basic` jumps 2.5B → 24.9B at its 2024 10-for-1 split.** A
   naive percent_change would report a spurious ~900% change. The series is flagged
   `split_sensitive=True` and the trend builder DECLINES to build a percent_change on it
   (no silent wrong comparison). Regression-tested
   (`test_split_sensitive_series_builds_no_percent_change`).

**Tests:** `tests/test_xbrl_history.py`, 10 new offline/synthetic cases. Full suite
**347 passed, 1 skipped** (was 337 — +10, no regressions). Report:
`benchmark/reliability/TRENDS_REPORT.md`.

**Honest scope.** This proves the VERIFICATION mechanism on real multi-period data. It
does NOT yet extract such trend claims from filing prose (that is extraction work,
explicitly out of scope for this round per the handoff — prove the mechanism first).

### Feature 2 — peer/sector comparison (SIC-based) — PARTIAL, HONESTLY SCOPED

**What was built.** `aritiq/edgar/sic.py` looks up each filer's SEC-assigned SIC code
from the submissions feed (`data.sec.gov/submissions/CIK{cik}.json`, cached to
`cache/sic/`) and groups the filing set by it — the SEC's own industry classification,
reused, not invented. `benchmark/reliability/xbrl_peers.py` computes net margin
(`NetIncomeLoss / Revenues`) for each peer using the SAME xbrl_history grounding, then
runs a `superlative`-across-companies claim ("X has the highest margin in its peer
group") through the EXISTING `check_superlative` verifier — the same function used for
temporal superlatives, applied across companies instead of across time.

**Measured — `python benchmark/reliability/xbrl_peers.py` over 8 SIC groups (>=3 members):**
- **2 groups compared with defensible margins, both VERIFIED** by the existing verifier:
  - Software (SIC 7372): **PLTR highest at 36.3%** over 5 peers (CRM 18.0, ORCL 25.4,
    DDOG 3.1, U -21.8). MSFT excluded — its June fiscal-year-end sits 335d behind the
    calendar-year peers, a period-alignment gate. Negative control (claim U is the max)
    correctly caught as WRONG_MATH.
  - Aircraft parts (SIC 3724): **HEI highest at 15.4%** over 3 peers (HON, RTX).
- **6 groups correctly DECLINED**, split into two honest reasons:
  - **4 SIC-class non-comparable** (REITs 6798, insurers 6331, banks 6021): the
    `Revenues` tag captures a partial/idiosyncratic top line, so NI/Revenues is not a
    defensible margin. Observed directly: REIT "margins" ranged **7.9% (BXP) to 15280%
    (AVB)** within one SIC code — that spread is what "Revenues" means per filer, not
    performance. These SIC classes are named in `_NONCOMPARABLE_MARGIN_SICS` and declined
    wholesale, with the raw metrics still recorded so a reviewer can SEE the incomparability.
  - **2 dropped below the 3-peer minimum** (semiconductors, pharma) because the CACHED
    companyfacts snapshot has stale revenue for one member (NVDA revenue → 2022, PFE →
    2023); the period-alignment gate excluded them rather than compare a stale figure. A
    live re-fetch would refresh these.

**Gates (never a silent wrong comparison):** (1) period alignment — every peer's period
must be within 200 days of the group's latest; (2) margin sanity — |margin| ≤ 100%;
(3) SIC-class non-comparability — named classes declined wholesale; (4) if < 3 peers
survive, decline rather than crown a "best-in-class" over a non-comparable group.

**NAMED LIMITATION (surfaced on every result):** SIC codes are coarse — the same code is
not always a true competitor. The SIC code + description travel with each comparison so
the judgment is explicit, exactly like `definitional_flag` surfaces a vague word.

**Tests:** `tests/test_xbrl_peers.py`, 6 new offline cases. Report:
`benchmark/reliability/PEERS_REPORT.md`. This is shipped as a **documented partial /
narrower-scope** feature (2 of 8 groups defensibly comparable on the one metric), NOT
claimed as a general peer-comparison engine — same honest treatment as 8-K got.

### Feature 3 — audit-trail / compliance export (CSV + PDF) — COMPLETE

**What was built.** `aritiq/export/audit_export.py` renders an audit's per-claim record
— data that ALREADY EXISTS on every `VerificationResult` / `Claim` — into two archival
formats: a stdlib-only CSV (always available) and a deterministic reportlab PDF
(optional; a clear ImportError if reportlab is absent, never a silent failure). One row
per claim carries: claim text, operation/rule, every operand WITH its value and source
citation, stated value, verdict, recomputed value, delta, `caused_by` (for propagated
errors), explanation, source text, and a UTC run timestamp. It is a pure
data-to-document transform — NO arithmetic, NO verdict, NO LLM. It lives OUTSIDE
`aritiq/core/` (it is I/O, not verification) and imports only `core.schema` types, so it
cannot affect a verdict; no model SDK is imported.

**Reachable two ways:**
- CLI: `python benchmark/reliability/xbrl_verify.py AAPL JPM --export-dir <dir>` writes
  `<TICKER>_<FORM>_audit.csv` and `.pdf` per filer.
- API: `POST /audit/export?format=csv|pdf` runs the audit and streams back the file with
  a download `Content-Disposition`. (The API is stateless — audits aren't persisted by
  id — so the export is produced from a fresh run of the same input; the exported record
  is exactly the verdicts the pipeline just produced. `?format=pdf` returns 503 with a
  plain-text note if reportlab isn't on the server, so CSV always works.)

**Verified end-to-end on real data (reproducible):**
- `xbrl_verify.py AAPL JPM PLTR --export-dir benchmark/reliability/exports` produced
  CSV+PDF for each. AAPL's four rows were HAND-CHECKED against the known figures:
  Assets $359.241B = Liabilities $285.508B + Equity $73.733B (VERIFIED, Δ0); basic EPS
  $7.49 = $112.010B / 14.9485B sh = $7.493 (VERIFIED); cash tie-out $35.934B = $35.934B
  (VERIFIED). **PLTR's cash tie-out exported as `INSUFFICIENT_EVIDENCE` with its full
  explanation** — proof the export transcribes honest declines faithfully and never
  launders a decline into a pass (regression-tested,
  `test_insufficient_evidence_exports_as_is_never_laundered`).
- API path exercised through the LLM-pipeline replay (`POST /audit/export`): CSV 200 with
  meta header + Aritiq score, PDF 200 with valid `%PDF-` magic bytes.

**Tests:** `tests/test_audit_export.py`, 6 new offline cases (faithfulness, CSV shape,
decline-not-laundered, propagated-error caused_by, real-PDF magic bytes, clear
ImportError when reportlab absent). Sample outputs: `benchmark/reliability/exports/`.

---

## ROUND 8 — full-suite result

Baseline entering the round: **337 passed, 1 skipped.** After all three features:
**359 passed, 1 skipped** (+22 tests, zero regressions). Firewall test green
(`aritiq/core/` imports no model SDK; the two new edgar modules and the export module
are not imported by any core module). Every number above is reproducible by re-running
the named script or `pytest`.

## ROUND 7 — beyond 10-K: 10-Q and 8-K via XBRL (additive, all prior work intact)

The `companyfacts` API already returns facts from EVERY form a company filed; the
`form` field distinguishes them. So extending past 10-K was mostly period-selection
work in `aritiq/edgar/xbrl.py`, not new grounding. The 10-K path, the 78-filer
benchmark, the LLM pipeline, and all `aritiq/core/` gates are UNCHANGED (10-K is the
default form; the new behaviour is opt-in via `form=`).

### 10-Q (quarterly) — SUPPORTED
`extract_xbrl_facts(..., form="10-Q")` and `xbrl_verify.py --form 10-Q`. The one real
mechanism handled: 10-Q income facts carry BOTH a standalone-quarter (~90 day) span
AND a year-to-date cumulative (~180/270 day) span; the reported quarterly EPS pairs
with the standalone quarter, so `_select_fact` picks the SHORTEST ~90-day span for
10-Q (vs the longest ~annual span for 10-K). Numerator, shares, and stated EPS then
all describe the same quarter.

**Measured (18 known-clean tickers, their latest 10-Q):**
- **18/18 completion (100%)**; verdicts: **VERIFIED 55, INSUFFICIENT_EVIDENCE 5,
  WRONG_MATH 2.**
- Both WRONG_MATH (BAC, PG) are the SAME rounding-boundary / preferred-dividend class
  already seen on 10-Ks (ratio ≤1.02×), not a new 10-Q bug — BAC/PG correctly used
  the net-income-to-common tag; the gaps are published-precision rounding. No gate
  weakened. Ready to describe as **supported** in the README.

### 8-K (current reports) — EXPERIMENTAL / partial by nature
`form="8-K"`. Only 8-Ks with an Item 2.02 earnings exhibit carry XBRL financials, so
coverage is inherently partial — **32/78 cached filers have any 8-K core-tag facts**;
that is a fact about the form, not a system limitation. Where the data exists, it
verifies correctly through the unchanged verifier: on 10 earnings-heavy filers,
AAPL/MSFT/JPM/GE/WFC/CVX returned all-VERIFIED, CAT produced no claims (its 8-K facts
lack the needed tag combination), and BAC/AIG hit the same rounding / insurer-
structure classes as their 10-Ks. **Recency also varies**: some filers' most recent
8-K balance-sheet facts are years old (e.g. AAPL's resolve to 2014 — it stopped
tagging balance sheets in 8-Ks), which the period-pin surfaces honestly rather than
hiding. Documented as a **known-limitation / experimental** capability, NOT "supported"
on par with 10-Q.

### S-1 / proxy (DEF 14A) — NOT ATTEMPTED
Deliberately skipped per the round's guidance and time budget. S-1s often predate a
company's XBRL history; proxies (DEF 14A) carry compensation/governance data, not the
balance-sheet/EPS/cash statements Aritiq's internal-consistency checks operate on, so
they are not a natural fit. Better to leave 10-Q solid and 8-K documented than to
manufacture a weak fourth use case. This is stated as not-done, not implied-supported.

Tests: **337 passed, 1 skipped** (+3 this round: quarterly-selection fixtures in
`tests/test_xbrl_grounding.py`). Firewall: clean. 10-K path and LLM pipeline verified
unchanged.

---

## ROUND 6 — XBRL grounding pivot (additive, LLM pipeline intact)

**Root insight:** every bug across five rounds traced to the LLM grounding numbers
from free-form prose/table layout. SEC filers ALSO submit XBRL — the same numbers
tagged against the standardized US-GAAP taxonomy. Grounding from XBRL sidesteps
label-matching entirely. Built as a NEW parallel data source feeding the SAME
verifier; the LLM pipeline and all `aritiq/core/` gates are untouched and still pass.

### Phase 1 — `aritiq/edgar/xbrl.py` (fetch + fact extraction), `xbrl_probe.py`
Plain HTTP against `data.sec.gov/api/xbrl/companyfacts` (no auth, no model; firewall
intact). Parses the exact tags the three checks need, pins the fiscal period, and
returns None for any untagged fact (never derives/guesses — e.g. AMD/DUK don't tag
total `Liabilities`, correctly reported absent). Moment-of-truth probe confirmed the
5 filers that failed LLM extraction entirely (WFC, CAT, BRK-A, BRK-B, GEV) all have
clean XBRL data, and that `NetIncomeLossAvailableToCommonStockholdersBasic` (JPM/DUK
mechanism-1) and `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`
(TSLA mechanism-2) resolve those bug classes directly by tag.

### Phase 2 — `xbrl_verify.py`: XBRL facts through the EXISTING verifier
Builds `Claim`s from XBRL facts and runs the SAME unmodified `check_*` functions.
Evidence flags set definitively from tags (`liabilities_complete=true` only when the
literal `Liabilities` tag supplied the value). Minimal, additive verifier change:
`_normalize_basis` now recognizes "common" as a valid income basis (distinct from
"total"; a common-vs-total pairing still mismatches — no gate weakened).

**Measured before/after, same 78-filer set:**
| Metric | LLM-grounded | XBRL-grounded |
|---|---|---|
| Completion (≥1 checkable claim) | 73/78 (94%) | **78/78 (100%)** |
| Fetch/extraction failures | 5 (WFC,CAT,BRK-A,BRK-B,GEV) | **0** |
| VERIFIED claims | 157 | **204** |
| WRONG_MATH | 10 | 29 |

The higher XBRL WRONG_MATH count reflects MORE checkable claims (271 vs ~180; XBRL
never fails to extract, so more claims reach arithmetic). Honest breakdown of the 29:
**22 are EPS rounding-boundary** (ratio ≤1.06× — XBRL gives full-precision NI/shares
but stated EPS is rounded to $0.01, so e.g. 6.322 vs 6.31 disagrees at the 2nd
decimal); **6 are genuine REIT/multi-class balance-sheet structure gaps** (SPG/DLR/
WELL UPREIT mezzanine, U/HEI multi-class, PRU insurer — equity components outside
"total equity incl NCI"); **1 is CVNA** (1.35×, a real wrong-operand). Per the hard
rules the EPS tolerance was NOT loosened to make rounding-boundary cases pass — they
genuinely disagree at the published precision.

### Phase 3 — hybrid documentation (not a pipeline rewire)
With a working repo and limited time, Phase 3 was scoped to DOCUMENTING the hybrid
architecture (README + this file) rather than rewiring the LLM pipeline's primary
source (higher risk near submission). The architecture: **XBRL grounds internal
consistency checks; LLM extraction grounds summary-vs-source auditing** (a genuinely
different task XBRL can't do) and serves as a fallback. Wiring XBRL as the automatic
primary inside `aritiq/pipeline.py` is the natural next step, deferred to stay safe.

Tests: **334 passed, 1 skipped** (+8 this round: `tests/test_xbrl_grounding.py`).
Firewall: clean (`aritiq/core/` and `aritiq/edgar/xbrl.py` import no model SDK).

---

## ROUND 5 — pre-YC hardening: security, SPG/SO root cause, 78-filer benchmark

### Security sweep (done)
- **No secret was ever committed to git history** — the repo is not a git repo yet,
  so there is no history to scrub. The prior leaks were in chat transcripts / a live
  `.env`, never in version control. The first commit must simply exclude `.env`
  (already gitignored).
- `.gitignore` strengthened: `.env`, `.env.*`, `*.env`, `.env.local`, `**/.env.local`,
  `*.key`, plus Python and Node/Next ignores.
- Full-repo secret scan (`gsk_` / `sk-ant-` / `AQ.` / `AIza` across .py/.json/.md/.ts/.tsx):
  **zero matches.** The Gemini key lives only in `.env` (gitignored). Run logs and
  extraction caches contain no echoed keys or Authorization headers.
- **Confirmed + fixed a redaction gap the brief predicted:** the `redact()` guard did
  NOT catch the Gemini `AQ.Ab...` key shape (different from Groq `gsk_`). Regex
  extended to cover `AQ.`, `sk-ant-`, `AIza`, `gsk_`, `sk-`, and Bearer tokens; all
  verified masked.
- Frontend: only `frontend/.env.local.example` exists (placeholder URL, no secret);
  no real `.env.local`. `LICENSE` present (MIT). README scanned — no real keys, no
  TODO/FIXME/profanity in user-facing text.

### SPG / SO root cause (done)
- **SPG = UPREIT mezzanine, exactly as hypothesized.** Simon Property Group's balance
  sheet has a "Limited partners' preferred interest in the Operating Partnership and
  noncontrolling redeemable interests" line (233,306) BETWEEN liabilities and equity —
  Assets exceed Liabilities + Total Equity by exactly that line. Two fixes: (1) the
  Mechanism-2 NCI regex was generalized to cover UPREIT/partnership structures
  (`noncontrolling redeemable`, `limited partners' interest in the Operating
  Partnership`, generic redeemable-interest) — it previously only matched
  `redeemable noncontrolling` (wrong word order); (2) the prompt now instructs
  grounding the mezzanine line into context. After a fresh live extraction, **SPG
  balance sheet → INSUFFICIENT_EVIDENCE** (was WRONG_MATH).
- **SO = rounding boundary, documented as an honest non-fix.** SO diluted EPS
  4,341/1,109 = 3.9143 vs stated 3.92: the filer publishes net income and shares
  rounded to whole millions and EPS to 2 decimals; the rounding band [3.9121, 3.9166]
  puts 3.92 ~0.003 outside what the published operands support. The operands are
  correct; forcing it to pass would require loosening the half-cent EPS tolerance,
  which is forbidden. Left as WRONG_MATH and documented. (A later run grounded a
  different SO income line — a genuine wrong-operand, also correctly WRONG_MATH.)
- Fixtures added: `tests/test_wrong_line_item_gates.py` — SPG UPREIT cases + SO
  rounding-boundary + must-NOT-fire on balanced sheets.

### Expanded benchmark — 78 filers, real live run
Filing set expanded 50 → **78** (added REITs/UPREITs, insurers, multi-class,
spinoffs, convertible-preferred, Up-C, smaller-caps). Two symbols were dead in SEC's
current ticker map (MMC, PARA→now PSKY); replaced with valid SCHW and PSKY — no dead
entries, no cherry-picking. Slice quality: **71/78 (91%)** produce a full
balance-sheet-identity slice.

**Full live run (provider: gemini / gemini-3.1-flash-lite-preview — the configured
one, confirmed reachable from the sandbox and used; NOT a substitute):**
- **78/78 attempted, 73 completed with ≥1 checkable claim (93.6%)**, 5 extraction_empty
  (WFC, BRK-A, BRK-B, CAT, GEV — non-standard statement labels / incomplete primary
  doc; a known ingest gap, not a false result).
- Verdicts: **VERIFIED 157, INSUFFICIENT_EVIDENCE 60, WRONG_MATH 10, UNSUPPORTED 4.**
- **WRONG_MATH = 10.** Honest breakdown: 4 (JPM, DUK, DDOG, WELL) are cases where the
  fix mechanism EXISTS and the phrase is present in the filing, but the model did not
  surface the preferred-dividend / NCI disclosure line into the claim's grounded
  context, so the evidence-required safety net correctly did not fire (a
  prompt-adherence gap, improvable — NOT a false conviction through a broken gate).
  The other 6 (TRV, NEE, HON, SO, CARR, W) have no preferred/NCI language in the
  filing at all and are genuine small-margin disagreements (<1.07×, mostly
  rounding-boundary). Per the hard rules the gate was NOT widened to scan full filing
  text (that would break the "evidence in grounded context" precedent).

Tests: **326 passed, 1 skipped** (+6 this round). Firewall: clean.

---

## ROUND 4 — wrong_line_item gates (confirmed across 3 models)
Three live runs (Groq llama-4-scout, Gemini 2.5 Flash, Gemini 3.1 Flash Lite)
converged on one root cause for 14/14 WRONG_MATH: the extractor grounded the wrong
LINE ITEM. Two mechanisms, each fixed with prompt hardening + a NEW verifier safety
net (evidence-required, fires only on a FAILING check when the phrase is present —
never blanket, never touches VERIFIED):

- **Mechanism 1 — EPS numerator.** Filers with preferred stock compute EPS on net
  income APPLICABLE TO COMMON (net of preferred dividends), not total net income.
  Prompt now requires grounding the applicable-to-common line when present. Net:
  if EPS fails tolerance AND the grounded context names "net income applicable/
  available to common" or "preferred dividend", route to INSUFFICIENT_EVIDENCE.
- **Mechanism 2 — BS equity.** The identity holds against TOTAL equity INCLUDING
  noncontrolling interest, not parent-only stockholders' equity. Prompt now requires
  the "Total equity (incl. NCI)" line. Net: if BS fails tolerance AND the context
  names a noncontrolling-interest line, route to INSUFFICIENT_EVIDENCE.

**Live re-run (provider: gemini / gemini-3.1-flash-lite-preview, the configured one
— confirmed reachable from the sandbox and used; NOT a substitute). All 50/50
attempted, 96% completion (48/50; BRK-B & CAT extraction_empty — non-standard
statement labels, a separate ingest issue):**
WRONG_MATH **14 → 3**, VERIFIED 101.

Previously-flagged resolution: TSLA (BS + 2 EPS) → all VERIFIED (extractor now
grounds total equity incl. NCI = 82,807 and applicable-to-common numerator);
GOOGL/JPM/BAC/GE/NEE/DUK/HON balance sheets → VERIFIED; JPM/BAC/DUK EPS →
INSUFFICIENT_EVIDENCE (safety net caught the still-wrong total-NI numerator with the
preferred phrase present); SO basic EPS → VERIFIED. **DUK = 2 distinct claims** (1
BS + 1 EPS), one per mechanism.

The 3 remaining WRONG_MATH are GENUINE small-margin, correctly NOT swallowed: SPG BS
×2 (0.57% gap, REIT — the extraction did NOT surface an NCI line into the grounded
context, so the net correctly did not fire; an honest residual grounding miss, not a
false conviction to hide) and SO diluted EPS (0.15% off). Per the brief these stay
WRONG_MATH rather than be papered over.

Tests: **320 passed, 1 skipped** (+12 this round). Firewall: clean. New fixtures:
`tests/test_wrong_line_item_gates.py` (JPM EPS, TSLA BS, + must-NOT-fire and
prior-gates-intact cases).

---

## ROUND 3 — false-conviction gates from the real 50-filer live run
A real live benchmark (45/50 attempted, Groq/llama-4-scout) produced **18
WRONG_MATH**. Hand-tracing the operands showed they were extraction artifacts, not
verifier errors. Two NEW verifier gates were added (neither weakens an existing
gate) plus extraction-prompt hardening:

- **EPS unit-scale gate** (`check_eps_reconciliation`): when net_income/shares is
  off from stated EPS by ≥20× (an order-of-magnitude units artifact, e.g. shares in
  raw units vs income in $M), return INSUFFICIENT_EVIDENCE not WRONG_MATH. Threshold
  is deliberately conservative — calibrated so AAPL/CRM/SPG (~1000×) are caught while
  BAC/PLTR/TSLA/JPM/SO (~1.01–1.04×, plausibly genuine) still convict.
- **Zero-liabilities gate** (`check_balance_sheet_identity`): liabilities == 0 with
  non-zero assets and equity is an impossible value (always a grounding failure), so
  `liabilities_complete` is overridden and the claim gates to INSUFFICIENT_EVIDENCE.
- **Prompt** (`cross_statement.py`): ground net_income and shares at the SAME unit
  header; never emit liabilities=0 / "Total liabilities and equity" as the
  liabilities operand (mark missing + complete=false instead); always emit the
  basic/diluted variant tag on every EPS claim and shares operand.

**Result (verifier gates replayed over the SAME real extractions):**
WRONG_MATH **18 → 12**. The 6 removed are exactly the artifacts: AAPL×2, CRM×2, SPG×1
(scale) and AMD×1 (zero-liab) → now INSUFFICIENT_EVIDENCE. Every previously-flagged
ticker now resolves correctly: AAPL/CRM/SPG EPS → INSUFFICIENT_EVIDENCE; AMD BS →
INSUFFICIENT_EVIDENCE (and AMD EPS → VERIFIED); AAPL/BAC/CRM/SPG balance sheets →
VERIFIED. The remaining 12 WRONG_MATH were verified GENUINE (not artifacts): all EPS
cases <1.05× off; BS gaps 0.5–16% (TSLA 728/0.5%, DIS 2.8%, ORCL 16%, VZ 15% — the
dropped-NCI/redeemable-equity pattern). Per the brief, these are left as WRONG_MATH,
not papered over.

Tests: **308 passed, 1 skipped** (+14 this round). Firewall: clean. New regression
fixtures: `tests/test_scale_and_zero_liab_gates.py` (AAPL scale, AMD zero-liab, +
the must-NOT-swallow cases).

**Caveat:** the verifier gates apply now (deterministic). The PROMPT fixes only take
effect on a fresh `--live` run, which must be done on a machine with a reachable
backend (the sandbox can't originate live calls). After re-running live, the dropped
NCI/redeemable-equity BS mismatches (TSLA/DIS/ORCL/VZ) should be re-inspected to
confirm whether better grounding resolves them or they need a 4th equity-component
operand.

---


## 0. Security — CLOSED on my side; ONE action remains for you
- The leaked Groq key was scrubbed from `.env` (replaced with a placeholder). It
  was the only place the literal key existed; it was never committed to git (the
  repo is not a git repo) and is not present in any run log or extraction cache.
- Added `.gitignore` covering `.env`, `*.key`, etc.
- Added a `redact()` guard in the harness so any provider error message that
  echoes a key/token is masked (`gsk_***REDACTED***`) before it can reach a log.
- **YOU MUST STILL ROTATE/REVOKE the exposed key in the Groq console.** I cannot
  do that — it requires console access. Treat the old key as compromised until
  you rotate it.

## 1. Open threads from the last round — CLOSED (diagnosed)
- **AMD `claims=0` root cause:** the model (llama-4-scout) emitted an arithmetic
  EXPRESSION as an operand value (`"value": 9455 + 2348 + 625 + 313 + 1186`),
  which is invalid JSON. `json.loads` rejects the whole array, so all 4 claims are
  dropped. The harness used to log this as "OK claims=0" — the same vacuous shape
  as the VZ bug. It is now classified `silent_degradation` (see item 2).
- **AAPL / MSFT / TSLA / GOOGL live results** (from cached live groq runs):
  | Ticker | claims | checkable | verdicts |
  |---|---|---|---|
  | AAPL | 4 | 4 | VERIFIED 2, WRONG_MATH 1, UNSUPPORTED 1 |
  | MSFT | 3 | 3 | VERIFIED 2, UNSUPPORTED 1 |
  | TSLA | 4 | 3 | VERIFIED 1, WRONG_MATH 1, UNSUPPORTED 1, INSUFFICIENT_EVIDENCE 1 |
  | GOOGL | 5 | 5 | VERIFIED 4, UNSUPPORTED 1 |
  - The **AAPL WRONG_MATH is a false conviction from an extraction unit-scale
    error**: net income grounded in $M (112,010) vs shares grounded in thousands
    (14,948,500), so 112010/14948500 = 0.0075 ≠ 7.49. This is an open EXTRACTION
    bug (unit consistency), flagged for the prioritized list — NOT a verifier bug.
    A unit-scale gate (decline rather than convict when stated EPS and computed
    differ by >=100x) is the recommended fix and is noted below; not yet built so
    as not to rush a `core/` change without its own tests.

## 2. Verizon vacuous-score bug — CLOSED with a hard guard
- `compute_score` no longer returns 100.0 when there are zero checkable claims. It
  returns `score_available=False`, `score_state="no_checkable_claims"`, and the
  score field is 0.0 — callers must render the state, never a number. (Tests:
  `tests/test_vacuous_score_guard.py`.)
- `params: null` (the VZ Pydantic `dict_type` drop) is now treated as an empty
  params bag AND recorded as a visible `repaired:` ExtractionIssue — the claim is
  kept, the repair is not silent. Operand VALUE coercion was deliberately NOT
  loosened (a null operand value still stays visible, per the brief).
- The pipeline annotates the score with `dropped_claims` + `dropped_reasons` so a
  hollow result can never hide WHY it is hollow.
- The harness now classifies every filing at the pipeline level
  (`ok` / `silent_degradation` / `vacuous_no_checkable` / `extraction_unavailable`
  / `fetch_failed` / `extraction_empty`) instead of a misleading "OK".

## 3. Bank-filer slicing bug — CLOSED and verified on real byte counts
- `aritiq/edgar/sec.py` no longer picks the statements region by raw numeric
  density (which let bank footnote tables out-score the real statements). It now
  prefers the earliest dense anchor whose window actually contains the
  balance-sheet IDENTITY rows, and never cuts the slice before those rows (wide
  cap for filers whose statements are spread far apart).
- Verified on real fetches: JPM 2,366 → 60,000 chars with `Total assets 4,424,900`
  AND `Total stockholders' equity`; GS 4,709 → 60,000 with `Total assets
  1,809,320` + `Total liabilities 1,684,348`; BAC recovered with `Total assets
  3,411,738` + `Total liabilities 3,108,495`.
- Corpus-wide (50 fetched filings): **45/50 (90%) now produce a slice containing
  the full balance-sheet identity.** Regression fixtures: `tests/test_bank_slicing.py`.
- **Still failing the slice (open, documented):** AMT, BRK-B, CAT (`no_identity` —
  REIT/insurer/finance-arm statement ordering the 24KB window misses) and WFC
  (SEC served an incomplete primary doc `wfc-20251231_d2.htm`; a
  document-selection bug, not a slicing bug). MRK is partial. These are the
  next-layer findings, not regressions of the fix.

## 4. Full-breadth live benchmark — PARTIAL, explicitly NOT complete
- The filing set was expanded to **50 structurally-varied filers** (banks,
  insurers, REITs, utilities, multi-segment industrials, finance-arm autos, and
  several mid-cap / pre-profit filers). All 50 fetch from SEC.
- **I could NOT run live extraction for the full set from this environment**: the
  Groq endpoint returns Cloudflare `error code: 1010` (the sandbox's datacenter IP
  is blocked). Live extraction works from YOUR machine (that is how the 7 cached
  live runs were produced); it does not work from here.
- What actually ran (live/cached extraction present): **8 filers attempted, 7
  completed with ≥1 checkable claim (87.5% of attempted), 1 silent_degradation
  (AMD).** The other 42 are `extraction_unavailable` — never run, reported
  separately, NOT counted as failures.
- **To complete item 4, run on a machine with a working backend:**
  ```bash
  # rotate the key first, put the new one in .env, then:
  python benchmark/reliability/harness.py --live          # all 50 filers
  python benchmark/reliability/report.py --md benchmark/reliability/REPORT.md
  ```
  The report will then show the real completion rate over all 50, and every
  filing that crashes / silently drops / returns 0 checkable becomes a fixture.

## Prioritized fixes before deployment (from real data)
1. **Extraction unit-scale consistency** (P1, extraction + a new verifier gate):
   the AAPL false WRONG_MATH. Add a deterministic order-of-magnitude gate to EPS
   reconciliation (decline → INSUFFICIENT_EVIDENCE when stated vs computed differ
   by ≥100×), and tighten the prompt to normalize shares/income to one scale.
2. **JSON-expression operands** (P1, extraction/parse): the AMD drop. Either
   instruct the model to emit literal numbers only, or add a guarded numeric-
   expression evaluator in the parser (digits/operators only) that records a
   visible repair. Until then the guard correctly marks it `silent_degradation`.
3. **Non-standard balance-sheet slicing** (P2, ingest): AMT/BRK-B/CAT label
   wording; WFC primary-document selection.
4. **Run the full 50-filer live sweep** (P1, measurement): the actual completion
   number over the whole structurally-varied set still has to be produced.

## Test + firewall status after this pass
- `python -m pytest tests/ -q` → **294 passed, 1 skipped** (was 284; +10).
- `grep -r "import anthropic|openai|groq|gemini" aritiq/core/` → **empty** (clean).

---

# Phase 1 (post-Phase-3) — closing the 7 WRONG_MATH cases

Written 2026-07-01. This closes roadmap Phase 1 items 1–3. The 83-filer replay run
carried **7 WRONG_MATH convictions**; every one is now resolved. Final adjudicated
verdict distribution over 238 in-scope claims: **VERIFIED 159, INSUFFICIENT_EVIDENCE
70, UNSUPPORTED_NUMBER 9, WRONG_MATH 0** (was WRONG_MATH 7). No VERIFIED result
regressed. `pytest -q` → **440 passed, 1 skipped**; `aritiq/core/` imports no model
SDK (firewall clean).

The discipline is the same JPM/WFC/AMD one: each conviction is traced to a
mechanism, fixed with a deterministic, non-ticker-specific rule, and proven not to
weaken (a genuine error in the same shape still convicts). Three of the fixes are
pure `aritiq/core` rule improvements; the fourth is an independent XBRL cross-check
in the harness. **No arithmetic moved into the LLM; no ticker is special-cased.**

## The four mechanisms and their fixes

**(A) Per-share published-rounding tolerance — resolves W directly; underpins SO/TRV.**
`aritiq/core/rules.py::eps_rounding_tolerance`. EPS is `net_income / shares`, and
each operand is printed already-rounded (net income to $1M, shares to 0.1M or 1M,
EPS to the cent). The smallest discrepancy a *genuine* error could produce is bounded
below by that input rounding propagated through the division:
`tol = half_ulp(eps) + half_ulp(N)/|S| + |N|/S² · half_ulp(S)`. A gap inside this band
is indistinguishable from input rounding, so convicting it is a false WRONG_MATH.
Wayfair is the clean case: −313/128 = −2.4453 vs published −2.44, entirely explained
by shares rounded to the nearest million. **Non-weakening:** the tolerance is
`max(flat_floor, propagated)`, never tighter than the old half-cent floor, so nothing
that verified before can flip; and a genuine multi-cent error (tested: 3.99 vs
4341/1109 = 3.9143) still convicts. `half_ulp` reads each operand's own decimal/
trailing-zero granularity, capped at 0.1% of the value so ambiguous zeros can't
inflate the band. A whole-number EPS float (2.00 → 2.0) is pinned to half-cent
precision.

**(B) Mezzanine / temporary-equity completeness gate — resolves WELL (balance sheet).**
`aritiq/core/rules.py::check_balance_sheet_identity`, new `redeemable_equity_present`
evidence. UPREITs and any issuer with **redeemable** noncontrolling interests park a
"temporary" (mezzanine) equity block *between* total liabilities and permanent equity
— captured by neither the `Liabilities` tag nor either `StockholdersEquity` tag. So
Assets = Liabilities + Mezzanine + Equity, and a two-term tie-out falls short by
exactly the mezzanine block (Welltower: 67,303,047 vs 24,100,108 + 42,939,716, a
263,223 / 0.39% gap = the redeemable-OP-unit line). When the tie-out fails **and** a
redeemable/temporary-equity line is disclosed (from the filer's own XBRL
`RedeemableNoncontrollingInterestEquityCarryingAmount` tag, or redeemable/mezzanine
language in grounded context), the equity picture is provably incomplete → decline,
don't convict. **Non-weakening:** failure-only, evidence-required; the same failing
sheet with no mezzanine signal still convicts (tested), and the flag never touches a
balanced sheet.

**(C) Independent XBRL adjudication backstop — resolves NEE, HON, CARR, SO, TRV.**
`benchmark/reliability/harness.py::xbrl_adjudicate`. These five are prose extraction
scope errors: the extractor grounded a wrong-scope operand that a better prompt would
avoid, but which the replay cache still carries. Rather than special-case them, before
recording any prose WRONG_MATH we cross-check it against the SEC's own standardized
XBRL facts — an independent, deterministic grounding (plain SEC JSON, no LLM). If an
XBRL-grounded version of the same rule reconciles the figure, the prose conviction was
a scope artifact → **downgrade to INSUFFICIENT_EVIDENCE** (prose scope unconfirmed;
XBRL reconciles). If XBRL independently *also* convicts, the WRONG_MATH stands. This
never manufactures a VERIFIED and never hides a real error. Per filer:

| Ticker | Prose operands (wrong scope) | XBRL-grounded operands (correct scope) | Mechanism |
|---|---|---|---|
| NEE  | eps 3.31, ni 6,835, **sh 2,083 (period-end)** | sh **2,064.5 (weighted-avg)** → VERIFIED | period-end vs weighted-average shares |
| HON  | eps 7.40, **ni 4,772 (consolidated)**, sh 635.3 | ni **4,729 / sh 639 (attributable)** → VERIFIED | numerator included noncontrolling interest |
| CARR | eps 1.74, **ni 1,587 (consolidated)**, sh 852.4 | ni **1,484 (attributable)** → VERIFIED | numerator included NCI/disc-ops |
| SO   | eps 3.92 (diluted), **ni 4,171 (pre-NCI)**, sh 1,109 | ni **4,341 (attributable to common)** → VERIFIED | consolidated vs attributable-to-common |
| TRV  | eps 27.83 (basic), **ni 6,288 (total)**, sh 224.2 | ni **6,242 (available to common)** → VERIFIED | two-class / income-available-to-common |

All five downgrade WRONG_MATH → INSUFFICIENT_EVIDENCE in the prose lane; all five
VERIFY outright in the independent XBRL lane (`xbrl_verify.py`), the two-lanes-agree
result. WELL's balance sheet downgrades via the same backstop because its XBRL
grounding declines under fix (B).

## Side effect: the independent XBRL lane got much cleaner too
Fixes (A) and (B) live in the shared verifier, so the standalone XBRL-grounded lane
improved from **29 → 8 WRONG_MATH** over the 83 filers with no lane-specific code. A
diluted-numerator scope guard was added to `build_claims_from_facts` (an UPREIT's
diluted EPS uses an OP-unit-adjusted numerator that isn't separately tagged; pairing
the basic income-to-common tag with diluted shares is a scope mismatch, so we decline
to emit that claim rather than convict — the Welltower diluted case). The **8
remaining XBRL-lane convictions (BAC, GS, T, DUK×2, ETSY, DDOG, GEV, …) are pre-
existing and out of Phase-1 scope** — none is one of the 7 prose convictions; their
gaps exceed the input-rounding band and trace to diluted-numerator / two-class
subtleties. Documented here as the next layer, not regressions.

## Item 2 — cash_flow_tie_out INSUFFICIENT_EVIDENCE rate (62.5%): correct caution, not a shortfall
Investigated all 45 cash-flow declines. **Every one is triggered by a restricted-cash /
escrow / reconciliation disclosure present in the grounded context** — so the source
text *is* reaching the claim; this is NOT the "text not making it into source_text/
notes" shortfall the roadmap flagged. Cross-checked against XBRL: **35/45 have a
confirmed real scope difference** (CF ending cash incl. restricted ≠ BS unrestricted
cash — TSLA +$1.1B/6.7%, META +$3.2B/9.0%, KO +$740M/7.2%, INTC +$447M), where a naive
tie-out would be a false WRONG_MATH. The gate is behaving exactly as designed.

The investigation also surfaced a **genuine extraction artifact** worth recording: for
8 filers (KO, AVB, SO, RTX, BXP, AFRM, …) the prose extractor grounded the *same*
figure for both cash operands while XBRL shows cf ≠ bs — i.e. it missed the restricted
difference and grounded one line twice. A tempting "verify the equal case" refinement
was implemented and then **reverted**: prose alone cannot distinguish a genuine zero-
restricted tie from a same-line-twice artifact, so verifying the equal case would
certify an extraction miss as VERIFIED. The conservative decline is the honest verdict;
the independent XBRL lane recovers the genuine ties by tag. (The next-layer extraction
fix — force the CF operand to the "…and restricted cash" line — is logged for Phase 2.)

## Item 3 — gold gates expanded over the full 83-filer set
- **Multi-period XBRL trend verification** (`xbrl_trends.py`): now **83/83 filers**
  with usable series (was 78/78). **Positive controls 499/499 (100%)**, **negative
  controls 335/335 (100%)** — real trend claims verify, fabricated ones are caught.
- **SIC peer comparison** (`peer_metrics.py`): defensible peer comparison in **8 SIC
  groups** across net_margin, return_on_assets, and debt_ratio (net_margin alone
  reached only 2). Correctly **declines** groups with < 3 comparable peers and flags
  outliers with z-scores (SPG net_margin z=2.44; CCI debt_ratio z=2.07). No false
  comparisons across non-comparable structures (REIT/bank/insurer margins).

## Changed files (Phase 1)
- `aritiq/core/rules.py` — `eps_rounding_tolerance` + `_decimal_half_ulp` (A);
  `redeemable_equity_present` gate in `check_balance_sheet_identity` (B); cash-flow
  decline comment hardened.
- `aritiq/core/verify.py` — `_context_names_redeemable_equity` + wiring of the
  mezzanine evidence flag.
- `aritiq/edgar/xbrl.py` — `temp_equity` fact (`RedeemableNoncontrollingInterest…` /
  `TemporaryEquity…` tags).
- `benchmark/reliability/xbrl_verify.py` — mezzanine flag in `build_claims_from_facts`;
  UPREIT diluted-numerator scope guard.
- `benchmark/reliability/harness.py` — `xbrl_adjudicate` backstop; `prose_verdict` +
  `adjudication` recorded per claim.
- Tests: `tests/test_phase1_rounding_and_mezzanine.py` (new, 13 cases incl. non-
  weakening guards); `tests/test_wrong_line_item_gates.py` (SO reclassified + genuine-
  error guard).

## Reproduce
```bash
pytest -q                                                   # 440 passed, 1 skipped
python benchmark/reliability/harness.py --replay            # prose run, WRONG_MATH=0 adjudicated
python benchmark/reliability/report.py --md benchmark/reliability/REPORT_LATEST.md
python benchmark/reliability/xbrl_verify.py                 # independent lane, 29→8
python benchmark/reliability/xbrl_trends.py                 # 499/499 pos, 335/335 neg
python benchmark/reliability/peer_metrics.py                # 8 SIC groups
```

---

# Phase 2 — item 4: Financial Knowledge Graph UI

Written 2026-07-01. Closes ROADMAP Phase 2 item 4. This is **surfacing**
existing graph/verdict data, not new verification logic.

## What was built

`frontend/components/DependencyGraph.tsx` already existed and rendered a graph
from `result.claim.depends_on`, but the inspector was upstream-only. It did not
show downstream dependents, full claim/source evidence, verdict explanation,
operand provenance metadata, or `PROPAGATED_ERROR.caused_by` root cause.

Changes:

1. Added `frontend/lib/graph.ts` as the single frontend graph-neighborhood
helper. It builds nodes, edges, missing dependency references, upstream,
downstream, and caused-by lookup from one `AuditResult.results` payload.
Downstream computation lives there, not duplicated in backend.
2. Extended `DependencyGraph` selected-node panel to show verdict, claim text,
source/evidence statement, verdict explanation, operand source metadata,
upstream dependencies, downstream dependents, and propagated-error root cause.
3. Added backend serialization of `claim.source_text` in `backend/app.py` so UI
can show claim-level evidence, not only operand snippets.

## Measured result (reproducible)

`python benchmark/eval_graph_ui_data.py --md benchmark/GRAPH_UI_REPORT.md`

Replay over real `benchmark/runs_graph/` extraction output, not synthetic
all-leaf fixtures:

| Doc | Claims | Edges | Upstream nodes | Downstream nodes | Evidence nodes | caused_by hits | Missing refs | Note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A Northwind Logistics | 8 | 0 | 0 | 0 | 8 | 0 | 0 | negative control |
| B Acme Invoice | 5 | 1 | 1 | 1 | 5 | 1 | 0 | real edge structure |
| C Globex Annual Highlights | 5 | 0 | 0 | 0 | 4 | 0 | 0 | negative control |
| D Meridian Cost Report | 3 | 1 | 1 | 1 | 3 | 1 | 0 | real edge structure |

- **2 real `depends_on` edges** available to UI.
- **2 nodes with downstream dependents** — UI has real downstream content.
- **2 `PROPAGATED_ERROR.caused_by` hits** under fault injection.
- **0 missing dependency refs.**
- **0 false edges** on negative controls A/C.

## Honest boundary

- This does not create new graph inference. It renders graph structure already
present in audit results. If extraction emits no edges, UI says so.
- Browser plugin was unavailable in this session. Render validation used
frontend typecheck/build. `npm run lint` is not configured; Next.js opened the
interactive ESLint setup prompt, so no lint config was created during this pass.
- No backend neighborhood endpoint added; current frontend computes graph
neighborhood from the serialized audit result once, in `frontend/lib/graph.ts`.

## Changed files

- `frontend/lib/graph.ts` — graph model/neighborhood helper.
- `frontend/components/DependencyGraph.tsx` — richer inspector.
- `frontend/lib/types.ts` — claim-level `source_text`.
- `backend/app.py` — serialize `claim.source_text`.
- `benchmark/eval_graph_ui_data.py` — reproducible graph UI data measurement.
- `benchmark/GRAPH_UI_REPORT.md` — measurement report.
- `tests/test_backend_graph_serialization.py` — serializer regression.

## Reproduce

```bash
python benchmark/eval_graph_ui_data.py --md benchmark/GRAPH_UI_REPORT.md
cd frontend && npm run typecheck && npm run build
pytest -q # 454 passed, 2 skipped
```

---

# Phase 2 — item 5: Multi-filing company memory

Written 2026-07-01. Closes ROADMAP Phase 2 item 5. This packages existing
cached companyfacts history into a per-company memory view; it does not add new
SEC fetching and does not put model logic into `aritiq/core/`.

## What was built

`aritiq/edgar/xbrl_history.py` already returned per-concept multi-year series
with the right comparability gates: `tag_used`, `dropped_noncomparable_spans`,
and `split_sensitive`.

New `aritiq/edgar/company_memory.py` packages those into per-company metric
trajectories, per-period YoY drift, latest YoY drift per metric, and
deterministic comparability/accounting-risk signals:
`noncomparable_spans_dropped`, `split_sensitive_series`, and
`fallback_xbrl_tag_used`.

## Accounting-change decision

Built deterministic signal surfacing only. In this pass, "accounting change /
definition risk detected" means an XBRL/comparability gate fired: fallback tag
use, dropped non-comparable spans, or split-sensitive series.

Footnote-language interpretation is **not** performed. If added later, it must
live in an extraction layer (same firewall discipline as `aritiq/extract/`), not
inside `aritiq/core/`.

## Measured result (reproducible)

`python benchmark/reliability/company_memory.py --md benchmark/COMPANY_MEMORY_REPORT.md`

Cached SEC companyfacts only; no model calls:

- **83** filers measured.
- **83/83** companies had usable multi-year series.
- **734** usable metric series.
- **10,678** cross-year points.
- **83** companies had deterministic comparability signals.
- Signal counts:
  - `noncomparable_spans_dropped`: **260**
  - `fallback_xbrl_tag_used`: **54**
  - `split_sensitive_series`: **243**

## Honest boundary

- This is deterministic XBRL memory, not accounting footnote interpretation.
- Fallback tag use is a definition-risk signal, not proof of an accounting
policy change.
- `split_sensitive_series` says raw per-share/share-count comparisons need care
across splits unless restated; it does not decide whether restatement occurred.
- `dropped_noncomparable_spans` proves the gate fired and excluded stubs/YTD/
non-comparable spans; it does not explain why the filer had those spans.

## Changed files

- `aritiq/edgar/company_memory.py` — per-company memory aggregation.
- `benchmark/reliability/company_memory.py` — real cached-filer measurement.
- `benchmark/COMPANY_MEMORY_REPORT.md` — measurement report.
- `tests/test_company_memory.py` — deterministic trajectory/signal tests.

## Reproduce

```bash
python benchmark/reliability/company_memory.py --md benchmark/COMPANY_MEMORY_REPORT.md
pytest -q # 454 passed, 2 skipped
```

---

# Phase 2 — item 1: depends_on extraction tagging (the highest-leverage item)

Written 2026-07-01. Closes ROADMAP Phase 2 item 1. The provenance graph
(`core/graph.py`), weighted score (`core/score.py`), and restatement classification
(`core/restatement.py`) were all built and tested in Phase 3 but **inert**: they only
do something when claims carry `depends_on` edges, and nothing populated them on real
extraction (PHASE3_PROGRESS.md's named boundary). This item makes the edges real.

## What was built

**The gap, precisely.** `node_id`/`depends_on` were already wired end-to-end (schema,
`parse_claims`, `raw_to_claim`, `build_dag`, `propagate_errors`) and the prompt even
mentioned them — but the few-shot example demonstrated **neither**, and its one derived
claim grounded revenue as a raw source figure (the `depends_on = []` case), so the model
had no positive pattern and emitted nothing. Also, the reliability harness measures only
leaf-level `internal_consistency` claims, so it could never surface edges — the main
`extract_claims` (source + summary) path is where derived-figure chains live.

**Two changes, belt-and-suspenders, both extraction-side (firewall untouched — the
verifier still only ever *consumes* edges):**

1. **A deterministic linker** — `aritiq/extract/linker.py`, run inside `extract_claims`
   after `parse_claims`. It infers an output→input edge B→A only when one of B's
   operands equals the **computed output** of exactly one dollar-computation claim A
   (`sum`/`difference`/`product`/`average`), that value is **derived-only** (does not
   appear as a raw figure in the source), unit-kind matches, the source is unique, and
   the edge introduces no cycle. Every filter only ever *withholds* an edge — a missing
   edge fails silently and safely; a wrong edge does not. Edges the LLM already tagged
   are preserved (union, never clobbered).

2. **A hardened prompt + a worked chained few-shot** — `aritiq/extract/prompt.py`. A new
   EXAMPLE 2 shows `node_id` on a computed subtotal and `depends_on` on the total that
   consumes it, contrasted with a margin that divides by *reported* revenue and
   therefore stays `depends_on: []`. Live-verified: under the shipped prompt the model
   now grounds the total as `[Marketing 30, Combined 20]` and emits the edge itself.

**The load-bearing distinction (output→input, NOT shared raw input).** Three claims that
each divide by the same reported revenue share a *raw* input — none is another's output,
so all stay leaf. Gold doc A reports `$125M` revenue AND has a `sum` that computes 125
from two segments; the margin's denominator 125 is the raw reported figure, so linking
margin→sum would be a false edge. The derived-only filter excludes exactly this.

## Measured result (reproducible)

`python benchmark/eval_depends_on.py` — replay over gold_set A–D against a committed
corpus of real model output under the shipped prompt (`benchmark/runs_graph/`, kept
separate from the frozen gold-aligned `benchmark/runs/` so the extraction-accuracy
regression baseline is untouched):

| Doc | Claims | Edges | Graph nodes | Roots | Propagated on fault | Note |
|---|---|---|---|---|---|---|
| A | 8 | 0 | 0 | 0 | 0 | negative control (shared raw input) |
| B | 5 | 1 | 4 | 1 | 1 | tax base $4,500 = net-before-tax output |
| C | 5 | 0 | 0 | 0 | 0 | negative control (shared raw input) |
| D | 3 | 1 | 2 | 1 | 1 | total $50M uses the $20M combined subtotal |

- **2 depends_on edges inferred on real extraction** (was 0) — non-zero graph structure
  on real filings, not just hand-built fixtures.
- **Propagation is live:** fault-injecting a `WRONG_MATH` at each source node relabels
  its downstream consumer `PROPAGATED_ERROR` with the correct `caused_by` — **2/2**.
  The previously-inert graph machinery is now driven by real extraction edges.
- **0 false edges** on the shared-raw-input negative controls (A, C) — from BOTH the
  linker and the LLM.
- Unit tests: `tests/test_depends_on_linker.py` (12 cases) pin every safety property —
  positive multi-level chains, shared-raw-input stays leaf, value-in-source excluded,
  identity/percent never a $-source, ambiguous source not guessed, cycle prevention,
  LLM edges preserved, idempotency. Full suite **452 passed, 1 skipped**; `aritiq/core/`
  imports no model SDK (firewall clean).

## Honest boundary

- **The graph is only as complete as extraction expresses.** The linker recovers the
  output→input edges the extraction actually grounds; if the model grounds raw
  components instead of an intermediate (the pre-hardening doc-D behavior: total
  grounded `[12,8,25]`, no edge), the chain isn't in the operands and no edge is
  inferred. This is the correct, safe failure (silent under-linking), and it is exactly
  why the prompt was hardened — to lead the model to express intermediates. A missing
  edge never propagates; that is the design.
- **Scope of the deterministic linker.** v1 infers **dollar** derivation chains
  (`sum`/`difference`/`product`/`average` outputs feeding a later operand). Percentage→
  percentage chains and ratio-multiple chains are left to the prompt/LLM path and not
  inferred by code — a named limitation, not a silent one. The corpus is 4 documents;
  broadening it is Phase 2 follow-up work, not a claim made here.
- **No accuracy score against labeled edges** is claimed — the gold set has no
  `depends_on` labels, so this is a structure + self-consistency + no-false-edge
  measurement, reported as exactly that.

## Changed files
- `aritiq/extract/linker.py` (new) — deterministic output→input linker.
- `aritiq/extract/extractor.py` — calls `link_claims(claims, source_text=source)`.
- `aritiq/extract/prompt.py` — sharpened depends_on instruction + worked chained few-shot.
- `benchmark/eval_depends_on.py` (new) — reproducible replay measurement (+`--regen`).
- `benchmark/runs_graph/{A..D}.json` (new) — committed hardened-prompt corpus.
- `benchmark/DEPENDS_ON_REPORT.md` (new) — the measurement table.
- `tests/test_depends_on_linker.py` (new, 12 tests).

## Reproduce
```bash
pytest -q                                   # 452 passed, 1 skipped
python benchmark/eval_depends_on.py         # 2 edges, 2/2 propagation, 0 false edges
python benchmark/eval_extraction.py         # frozen extraction baseline still 100% faithful-replay
```
