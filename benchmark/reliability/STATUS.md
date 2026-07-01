# Aritiq Hardening Pass — Status (honest accounting)

This file states, item by item, what is closed with evidence and what is **not yet
complete**. Nothing here claims real-world accuracy, readiness, or "done" beyond
what the numbers below support.

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
