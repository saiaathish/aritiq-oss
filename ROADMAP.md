# Aritiq Roadmap — Post-Phase-3 to Deployment

*Written 2026-07-01. Supersedes the informal plan pasted into chat — this version is
checked against the actual repo state (`REPORT_LATEST.md`, `PHASE3_PROGRESS.md`,
`benchmark/reliability/STATUS.md`) rather than assumed.*

## Where Aritiq actually stands today

Before adding anything, here's what's already shipped and measured, so the plan
below builds on top of it instead of re-proposing it:

- **238 in-scope claims across 83 filers** (`benchmark/reliability/REPORT_LATEST.md`,
  run 2026-07-01): 158 VERIFIED, 64 INSUFFICIENT_EVIDENCE, 9 UNSUPPORTED_NUMBER,
  **7 WRONG_MATH remaining** — concentrated in Utility (2), and one each in Industrials,
  Industrials (spinoff), E-commerce (smaller), eps_reconciliation (6 of 7), balance_sheet
  (1 of 7).
- **XBRL-first grounding already exists** (`aritiq/edgar/xbrl.py`), not just proposed:
  100% completion on the 78-filer set vs. 94% for LLM grounding, no model involved.
- **Derived/temporal engine already exists**: `xbrl_history.py` (multi-year trend
  verification, 78/78 filers, 468/468 positive controls, 314/314 negative controls) and
  `sic.py` + `xbrl_peers.py` (peer/margin comparison, honestly scoped to 2 of 8 SIC groups
  where margins are defensible; REITs/banks/insurers correctly declined as non-comparable).
- **Provenance graph + weighted score + restatement classification** shipped in Phase 3
  (`core/graph.py`, `core/score.py`, `core/restatement.py`), 232 tests passing, firewall
  intact (`aritiq/core/` imports no model SDK).
- **347+ tests passing**, deterministic reliability harness with fault-injection
  self-tests (`--selftest`).

So Phase 1 items 2–4 from the original plan (XBRL-first, derived financials, cross-year
consistency) are **substantially done**, not greenfield. The real gap is narrower than
the original plan implied: closing out the last 7 WRONG_MATH cases, the 62.5%
INSUFFICIENT_EVIDENCE rate on cash_flow_tie_out, and production hardening. That
re-ranks the priorities below.

---

## Phase 1 — Close the loop on what's measured — ✅ COMPLETE (2026-07-01)

> **Status: DONE.** All three items closed. Prose benchmark now adjudicates to
> **WRONG_MATH 0** (was 7), VERIFIED 159 / INSUFFICIENT_EVIDENCE 70 /
> UNSUPPORTED_NUMBER 9 over 238 claims, no VERIFIED regression. `pytest -q` →
> **440 passed, 1 skipped**; firewall clean. Full write-up (per-filer, per-mechanism)
> in `benchmark/reliability/STATUS.md` → "Phase 1 (post-Phase-3) — closing the 7
> WRONG_MATH cases". Summary:
> - **Item 1 (7 WRONG_MATH):** W resolved by a deterministic per-share published-
>   rounding tolerance; WELL (balance sheet) by a mezzanine/temporary-equity
>   completeness gate; NEE/HON/CARR/SO/TRV by an independent XBRL adjudication
>   backstop that downgrades a prose conviction to INSUFFICIENT_EVIDENCE when SEC
>   XBRL facts (weighted-avg shares, income-to-common, attributable-to-parent)
>   reconcile the figure. All five VERIFY outright in the independent XBRL lane. No
>   ticker special-cased; each fix ships a non-weakening guard proving a genuine
>   error still convicts. Side effect: the XBRL lane fell 29 → 8 WRONG_MATH.
> - **Item 2 (cash_flow 62.5%):** investigated — **correct caution, not a shortfall.**
>   35/45 declines are XBRL-confirmed real restricted-cash scope differences (TSLA
>   +$1.1B, META +$3.2B). Also surfaced (and documented) a same-line-twice extraction
>   artifact for Phase 2.
> - **Item 3 (gold gates):** trend verification expanded to 83/83 filers (499/499
>   positive, 335/335 negative controls); peer comparison to 8 SIC groups.

**1. Root-cause and fix the remaining 7 WRONG_MATH cases.**
Per-filer, not per-bucket: pull the 7 failing claims from `REPORT_LATEST.md` (Utility ×2,
Industrials, Industrials spinoff, E-commerce smaller, plus 2 more in eps_reconciliation),
diff extracted vs. XBRL ground truth, and classify each as an extraction bug, a rule gap,
or a genuine filing irregularity. Document every one in `STATUS.md` the way JPM/WFC/AMD/
Palantir were — this is the pattern that already works and the strongest section of the
repo for a reviewer.

**2. Attack the cash_flow_tie_out INSUFFICIENT_EVIDENCE rate (62.5%, worst of the three
rules).** This isn't a false-positive problem, it's an evidence-gating problem — the rule
is declining to answer more than half the time. Investigate whether that's correct
caution (genuine restricted-cash/escrow ambiguity, which Phase 3 already handles) or an
extraction shortfall (source text not making it into `source_text`/`notes`). Given Phase
2 already built the restricted-cash carrying logic, this is likely measurable within days,
not weeks.

**3. Expand the gold gates already built, don't add new machinery.** The peer-comparison
and trend-verification code already exists — the fastest win is running them against more
of the 83-filer set and folding failures into the same STATUS.md discipline, rather than
starting a new "Derived Financial Engine" from scratch as the original plan suggested.

---

## Phase 2 — Fill genuine gaps (3–5 weeks)

**4. Financial Knowledge Graph UI.** ✅ COMPLETE (2026-07-01). Existing
`DependencyGraph` now has clickable node detail showing verdict, source
statement/evidence, explanation, operands, upstream dependencies, downstream
dependents, and `PROPAGATED_ERROR.caused_by` root cause. Data-level replay over
`benchmark/runs_graph/` proves **2 real edges**, **2 downstream nodes**,
**2 caused_by hits**, **0 missing refs**, **0 false edges** on negative controls
(`benchmark/eval_graph_ui_data.py`, report `benchmark/GRAPH_UI_REPORT.md`).

**5. Multi-filing company memory.** ✅ COMPLETE (2026-07-01). Added deterministic
per-company memory over cached XBRL companyfacts (`aritiq/edgar/company_memory.py`):
cross-year metric trajectories, latest YoY drift, and comparability/accounting-risk
signals from existing gates (`dropped_noncomparable_spans`, `split_sensitive`,
fallback tag use). No LLM footnote read; boundary documented. Measured across
83 cached filers: **83/83** usable multi-year series, **734** metric series,
**10,678** cross-year points, deterministic signals on **83** companies
(`benchmark/reliability/company_memory.py`, report `benchmark/COMPANY_MEMORY_REPORT.md`).

**6. Extraction-side `depends_on` tagging.** — ✅ COMPLETE (2026-07-01). Named directly
in `PHASE3_PROGRESS.md` as the load-bearing gap: the graph and weighted score are "inert"
without the extractor tagging which claims share an operand.

> **Status: DONE.** Closed with a deterministic output→input linker
> (`aritiq/extract/linker.py`, firewall-safe, run inside `extract_claims`) plus a
> hardened prompt + worked chained few-shot. Measured on real model output
> (`benchmark/eval_depends_on.py`, replay over gold A–D): **2 depends_on edges inferred
> on real extraction (was 0), 2/2 fault-injected root failures propagate to
> PROPAGATED_ERROR, 0 false edges** on the shared-raw-input negative controls. The
> previously-inert graph/score/restatement machinery is now driven by real edges. Full
> write-up (build → measured result → boundary) in `benchmark/reliability/STATUS.md`
> → "Phase 2 — item 1". Suite 452 passed, firewall clean. Items 4 and 5 now
> also complete; latest suite **454 passed, 2 skipped**.

---

## Phase 3 — Institutional-grade additions — ✅ COMPLETE (2026-07-02)

> **Status: DONE.** All three items built in the handoff's dependency order
> (timeline → dashboard → analyst), each measured against real data with a
> reproducible script and documented in `benchmark/reliability/STATUS.md`
> ("Phase 3 — item 1/2/3"). Suite 455 → **509 passed, 1 skipped**, zero
> regressions; firewall clean throughout. Summary:
> - **Item 1 — SEC filing timeline** (`aritiq/edgar/timeline.py`,
>   `GET /timeline/{ticker}`, `FilingTimeline.tsx`): 83/83 filers, 126,492
>   events sequenced, 0 integrity-gate failures, latest-10-K spot-check
>   agreeing across two independent SEC endpoints. Every event carries an
>   explicit verification-coverage label (10-K/10-Q verified; 8-K partial
>   only with Item 2.02; Form 4 ownership-only; everything else + ALL
>   amendments listed-only). `TIMELINE_REPORT.md`.
> - **Item 2 — risk dashboard** (`aritiq/dashboard.py`,
>   `GET /dashboard/{ticker}`, `RiskDashboard.tsx`): five deterministic
>   panels reusing core/score, core/restatement, company_memory; Evidence
>   Coverage + Disclosure Quality decided deterministic (documented).
>   Dashboard-recovered totals exactly match REPORT_LATEST (159/70/9/0);
>   TSLA/META/KO cannot present as clean; restatement on single filings is
>   UNASSESSED, never "low". `DASHBOARD_REPORT.md`.
> - **Item 3 — AI Analyst Mode** (`aritiq/analyst.py`, `POST /analyst`):
>   three-layer deterministic boundary (VERIFIED-only ledger with
>   digit-stripped blocked items; pre-model topic-precision/coverage refusal
>   gates; post-model number whitelist). 234 real question/filer pairs:
>   **72/72 blocked-topic refusals pre-model**, 0 gate failures; live gemini
>   narration verified, live adversarial (TSLA cash) refused at zero token
>   cost. Notably, the at-scale measurement CAUGHT two real boundary holes in
>   v0 (adjacent-topic answering), now fixed + regression-tested — the
>   measure-first discipline doing its job. `ANALYST_REPORT.md`.

These were genuinely novel and good YC talking points, and every one is built on
top of Phase 1–2 primitives (graph, XBRL grounding, restatement classification) —
sequenced after those were hardened so the "wow" demo is backed by a system with
no known open WRONG_MATH cases underneath it.

---

## Phase 4 — Enterprise features (explicitly deferred, not now)

Team workspaces, audit history, watchlists, API key dashboards, webhooks. Real, but not
YC-story-critical yet. Matches the original plan's Phase 3 — no disagreement here.

---

## Phase 5 — Evaluation suite expansion

Current: 83 filers, 238 claims, sector-broken-down (utilities, REITs, banks, insurers,
software, pharma, industrials, etc. already represented in `REPORT_LATEST.md`). Growing
this to 250–500 filings is real work but should follow, not precede, closing the 7 known
WRONG_MATH cases — a bigger benchmark with the same unresolved failures just restates the
problem at higher N.

---

## Phase 6 — Production readiness

Structured logging, monitoring, error tracking, CI/CD, staging, security review, API docs,
rollback plan. Unchanged from the original plan — genuinely not started yet based on repo
structure (no `.github/workflows`, no logging config found). This can run in parallel with
Phase 1–2 since it's orthogonal engineering, not verification logic.

---

## Explicitly not now

Auth providers, billing/subscriptions, mobile apps, social features, chart-heavy
dashboards for their own sake, AI chat without a verified-data constraint. Agreed with the
original plan — none of these strengthen the correctness story.

---

## The one-sentence reprioritization

The original plan assumed Aritiq was earlier-stage than it is — XBRL grounding, derived
metrics, and cross-year trends are already built and measured. The actual next move is
narrower and cheaper: close out the 7 named WRONG_MATH cases and the cash-flow evidence
gap using the same STATUS.md discipline that already resolved JPM/WFC/AMD/Palantir, then
wire the existing graph/score/restatement machinery to the extractor via `depends_on`
tagging before building any new "wow" feature on top of it.
