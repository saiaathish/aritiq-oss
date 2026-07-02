# Aritiq — Phase 3, 4, 5 Handoff

*Written 2026-07-01, for a fresh agent picking up work with no memory of prior
sessions. Read this whole document before touching code.*

## Read first, in this order

1. `ROADMAP.md` — phased plan, with Phases 1 and 2 marked complete and their
   measured results inline.
2. `benchmark/reliability/STATUS.md` — full history, one entry per feature, in
   the format this project requires: **what was built → the reproducible
   command and number that prove it works → the honest boundary of what's
   NOT proven.** Every item below must be documented this way when finished.
3. `PHASE3_PROGRESS.md` — note this is a *different* "Phase 3" than the one
   below (it's the original internal phase numbering, built the provenance
   graph / weighted score / restatement classification). Don't confuse the
   two. Its closing sections state the exact boundary this whole project is
   built around: no model grades the math, ever, inside `aritiq/core/`.

## Non-negotiable ground rules (apply to Phases 3, 4, and 5 alike)

- `aritiq/core/` never imports a model SDK. Check before and after every
  change (`grep` for imports, or run the existing firewall test).
- No claim ships without a reproducible script and a real measured number
  behind it. This is the project's entire differentiator — it is what
  separates Aritiq from "another LLM finance chatbot."
- Full test suite passes with zero regressions before anything is called
  done. Current baseline: 456 tests collected, 447+ passing.
- Every finished item gets a STATUS.md entry in the established format.
- There is a git repo with a stale `.git/index.lock` that sandboxed agents
  cannot remove due to filesystem permissions. If you hit this, don't fight
  it — leave changes in the working tree and tell the user to run
  `rm -f .git/index.lock` from their own terminal, then commit. This has now
  happened across three phases of uncommitted work; say so explicitly if it
  happens again.

## Current state (as of Phase 2 close)

Phase 1: all known WRONG_MATH cases closed, cash-flow evidence-gating rate
validated as correct caution. Phase 2: `depends_on` extraction tagging
(`aritiq/extract/linker.py`) feeds real edges into the provenance graph; a
Knowledge Graph UI (`frontend/components/DependencyGraph.tsx`,
`frontend/lib/graph.ts`) surfaces it with upstream/downstream/`caused_by`
detail; multi-filing company memory (`aritiq/edgar/company_memory.py`)
computes cross-year metric trajectories and deterministic comparability
signals over all 83 cached filers.

Filing-type support today (README.md's table): 10-K and 10-Q fully
supported and measured. 8-K experimental/partial by nature (only filings
with an Item 2.02 exhibit carry XBRL). DEF 14A and S-1 explicitly not
supported. `aritiq/edgar/form4.py` already parses Form 4 ownership XML but
nothing sequences it against other filings yet.

No user/team/org model exists yet. Backend auth (`backend/app.py`) is a
single static API-key check (`require_api_key`) plus a BYOK env-var
mechanism — there is no per-user or per-org concept anywhere in the code.
**Correction (2026-07-01):** `backend/app.py` does have per-client-IP rate
limiting (`ARITIQ_RATE_LIMIT_PER_MINUTE`, default 30/min, line 66/154) — an
earlier version of this doc said no rate limiting existed; that was wrong,
confirmed by direct grep. It's still just an in-memory per-IP bucket, not a
per-key or per-org quota system, so Phase 4's "API-key dashboard" (usage,
limits, rotation, history) still starts from close to zero.

---

## Phase 3 — Institutional-grade additions

Three items, strict dependency order — build and measure item 1 before
starting item 2, item 2 before item 3. Do not parallelize.

**Item 1 — SEC filing timeline (build first, lowest risk).**
Sequence a company's filings by type and date: 10-K, 10-Q, 8-K where
available, Form 4 (reuse `form4.py`, don't rebuild ownership parsing). Pull
from SEC's `submissions` feed (`data.sec.gov/submissions/CIK{cik}.json`) —
`aritiq/edgar/sic.py` already fetches and caches from this endpoint for SIC
lookup; follow that pattern rather than inventing a new HTTP client. State
plainly, in the UI and in docs, which filing types in the timeline get real
financial verification (10-K/10-Q, partially 8-K) and which are just dated
entries with a link (DEF 14A, 13D, 13F, Form 4 itself beyond ownership
data) — implying verification coverage that doesn't exist is exactly the
kind of overclaim this project's discipline is built to prevent. Measure:
run against real cached filers with multi-year history, hand-spot-check a
few against actual EDGAR filing dates/types.

**Item 2 — Institutional risk dashboard (build second).**
This is presentation logic over numbers that already exist — don't
recompute anything that's already computed elsewhere:
- Verification Score / Extraction Confidence → `core/score.py`'s existing
  `AritiqScore` (weighted + unweighted).
- Restatement Risk → `core/restatement.py`'s existing
  `classify_restatement` output.
- Consistency Score → can reasonably derive from `company_memory.py`'s
  comparability signals (dropped spans, split-sensitivity, fallback tags).
- Disclosure Quality and Evidence Coverage are the two genuinely new
  metrics. Decide explicitly whether each is deterministic (e.g., Evidence
  Coverage = % of claims with non-empty `source_text`) or requires model
  judgment. If the latter, it must live outside `aritiq/core/` and be
  labeled model-assisted, never presented as verified.
Measure against several real cached companies and confirm the dashboard's
numbers agree with what STATUS.md and existing reports already established
about those specific filers — a filer with known INSUFFICIENT_EVIDENCE
history on cash flow should not silently show as "clean" on the dashboard.

**Item 3 — AI Analyst Mode (build last, highest risk).**
The one place a model touches output directly — the feature most likely to
quietly undermine "the verifier contains no model" if built carelessly.
Interaction model: user asks e.g. "why did operating margin decrease," the
system answers only using claims that already passed through
`core/verify.py`, cites which verified claims it used, and refuses or flags
when the needed number is UNCHECKED / INSUFFICIENT_EVIDENCE / WRONG_MATH.
Build a hard, testable boundary between "verified claims available to
answer from" and "the model's own generation" — construct at least one
adversarial test where the only relevant number is bad, and confirm the
system declines rather than hallucinating a fluent-sounding explanation
over it. Lives in `aritiq/extract/` or a new sibling module, never in
`aritiq/core/`.

---

## Phase 4 — Enterprise features (explicitly deferred until Phase 3 is solid)

Team workspaces, audit history, watchlists, API-key dashboard, webhooks.
Real, useful, but not YC-story-critical — do not start this before Phase 3
is measured and documented. Notes for whoever eventually picks this up:

- **No auth/user model exists.** This phase starts from zero on
  organizations, users, and permissions — it is not a matter of "wiring up"
  something partial. Scope that honestly before estimating effort.
- **API-key dashboard** has a real starting point: `backend/app.py`'s
  `require_api_key`/BYOK mechanism is a single static key today; a real
  dashboard (usage, limits, rotation, history) needs actual per-key
  identity, which doesn't exist yet either.
- **Webhooks** ("filing detected → run audit → notify") depend on Phase 3's
  filing timeline existing first, since that's what would detect a new
  filing to trigger on.
- Per the original plan and this roadmap: explicitly do NOT build auth
  providers (Google/Microsoft OAuth), billing, or subscriptions as part of
  this — those were named out of scope for the YC-facing story.

## Phase 5 — Evaluation suite expansion

Current benchmark: 83 filers, 238 claims, broken down by sector and
statement type in `benchmark/reliability/REPORT_LATEST.md`. Growing this to
250–500 filings is real, valuable work, but should follow — not precede —
Phase 3, for the same reason it followed Phase 1 originally: a bigger
benchmark just restates whatever unresolved failures exist at higher N. Once
started: expand `benchmark/reliability/filing_set.json` with new tickers
across underrepresented sectors (the current set already covers banks,
insurers, REITs, utilities — check `REPORT_LATEST.md`'s sector table for
which have thin N before adding), and report precision/recall/false-positive
rate/confidence calibration per the same STATUS.md discipline — a number
without a reproducible script behind it doesn't count.

---

## Sequencing summary

Phase 3 (timeline → dashboard → AI Analyst Mode, in that order) should be
fully measured and documented before Phase 4 or 5 starts. Phase 4 and 5 can
likely run in parallel with each other once Phase 3 is done, since neither
depends on the other. Before starting any phase, re-verify this document's
"current state" section against the live repo — don't trust it blindly if
significant time has passed since 2026-07-01.
