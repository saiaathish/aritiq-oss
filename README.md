# Aritiq
https://aritiq.vercel.app

**Aritiq verifies AI-generated financial summaries by tracing numeric claims to source numbers and checking the arithmetic deterministically.**

Or more plainly: Aritiq makes sure AI doesn't lie with numbers.

---

## The problem

Grounding-based hallucination checkers ask: *does this claim sound supported by the source?* They catch invented facts, but they miss something subtler and arguably more dangerous in finance — wrong derived numbers.

Consider: *"Revenue rose from $100M to $125M, a 30% increase."* Every number appears in the source document. A grounding checker waves it through. A calculator doesn't: (125 − 100) / 100 = **25%**, not 30%. The AI was grounded and still wrong.

Aritiq catches this class of error every time, with no judgment call and no second model.

---

## How it works

```
  Source document           AI-generated summary
  (10-K, earnings, etc.)   (the text being audited)
         │                          │
         └──────────┬───────────────┘
                    ▼
        ┌───────────────────────┐
        │  Stage 1: Ingestion    │  parse & normalise source figures
        └───────────┬───────────┘
                    ▼
        ┌───────────────────────┐
        │  Stage 2: Extraction   │  ◄── the ONLY place an LLM runs
        │  (LLM-assisted)        │  summary → structured Claim objects
        └───────────┬───────────┘
                    │
       ══════════ FIREWALL ══════════  structured data only; no prose
                    │
        ┌───────────▼───────────┐
        │  Stage 3: Verification │  ◄── pure deterministic code, NO LLM
        │  (the moat)            │  recompute each claim, classify verdict
        └───────────┬───────────┘
                    ▼
        ┌───────────────────────┐
        │  Stage 4: Scoring      │  aggregate → Aritiq Score + per-claim trace
        └───────────────────────┘
```

The firewall between Stage 2 and Stage 3 is the whole point. The LLM turns messy prose into structured `Claim` objects. Deterministic code verifies those claims. The two halves never mix — open `aritiq/core/verify.py` and confirm there is no model import anywhere in it.

### Two grounding sources, one verifier (hybrid architecture)

Aritiq grounds operands two ways, both feeding the **same** deterministic verifier core (`aritiq/core/`):

- **XBRL grounding (`aritiq/edgar/xbrl.py`) — primary for internal-consistency checks.** Every SEC filer is legally required to also submit their financial statements as XBRL: every number tagged against the standardized US-GAAP taxonomy (`Assets`, `Liabilities`, `NetIncomeLossAvailableToCommonStockholdersBasic`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`, ...) regardless of how the company laid out its prose. Because the SEC's own tagging already resolved the label ambiguity, XBRL grounding sidesteps the prose/table label-matching that caused the extraction bugs found in benchmarking. It is plain HTTP against SEC's free, no-auth `data.sec.gov/api/xbrl/companyfacts` endpoint — **no model is involved**, so the firewall is unaffected. This answers *"what is actually true in the filing?"*

- **LLM extraction (`aritiq/extract/`) — for summary-vs-source auditing, and as a fallback.** XBRL tells you what the filing says; it does **not** tell you whether some *other* document (an AI-generated summary, an earnings-call paraphrase) faithfully represents it. That summary-vs-source audit is a genuinely different task, and the LLM extraction path handles it. LLM extraction also serves as a fallback for any fact XBRL doesn't tag.

Both paths produce the same `Claim`/operand objects and run through the same unmodified `check_balance_sheet_identity` / `check_eps_reconciliation` / `check_cash_flow_tie_out`. See `benchmark/reliability/STATUS.md` for the measured before/after: on a 78-filer set, XBRL grounding reached 100% completion (every filer produced ≥1 checkable claim, including five filers whose prose statements the LLM could not parse at all) vs 94% for LLM grounding, with the preferred-dividend (JPM/DUK) and noncontrolling-interest (TSLA) mechanism bugs resolved directly by the standardized tags. No accuracy or "solved" claim is made beyond those measured numbers.

#### Filing types

Because `companyfacts` returns facts from every form a company has filed (keyed by a `form` field), XBRL grounding works across filing types — pick the form with `extract_xbrl_facts(ticker, form=...)` or `python benchmark/reliability/xbrl_verify.py --form 10-Q`:

| Form | Status | Notes |
|---|---|---|
| **10-K** (annual) | Supported | The original path; 78-filer benchmark, 100% completion. |
| **10-Q** (quarterly) | Supported | Selects standalone-quarter income facts so numerator/shares/EPS describe the same quarter. Measured on 18 known-clean filers: 100% completion, 55 VERIFIED / 5 INSUFFICIENT_EVIDENCE / 2 rounding-boundary WRONG_MATH. |
| **8-K** (current reports) | Experimental | Only 8-Ks with an Item 2.02 earnings exhibit carry XBRL financials, so coverage is partial *by nature* (~32/78 filers have any 8-K facts) and recency varies by filer. Verifies correctly where the data exists. |
| **S-1 / DEF 14A** | Not supported | S-1s often predate XBRL history; proxies carry governance/compensation data, not the statements these checks operate on. |

#### SEC filing timeline

`aritiq/edgar/timeline.py` sequences a company's filings by type and date from the SEC submissions feed (`GET /timeline/{ticker}` in the backend, `FilingTimeline` in the UI). Every event carries an explicit `verification_coverage` label so the timeline never implies coverage that doesn't exist: **10-K/10-Q** events are the verified forms per the table above; an **8-K** is partial only when it carries an Item 2.02 earnings exhibit; **Form 4** entries are parsed insider transactions (`form4.py`), not financially verified; everything else — DEF 14A, 13D/13F, S-1, and *all amendments* (10-K/A included) — is a dated entry with an EDGAR link and nothing more. Measured over the 83-filer set: 83/83 timelines built, 126,492 events sequenced, 0 integrity-gate failures, latest-10-K spot-check agreeing across two independent SEC endpoints (`benchmark/reliability/TIMELINE_REPORT.md`). The feed's recent window (1,000 filings or the last full year, whichever is more) is a named limitation — older filings are flagged, not fetched.

#### Institutional risk dashboard

`aritiq/dashboard.py` (`GET /dashboard/{ticker}`, `RiskDashboard` in the UI) presents five deterministic panels over numbers that already exist: Verification Score (core/score.py's weighted + unweighted pair), Evidence Coverage (share of claims whose required evidence flags reached extraction), Disclosure Quality (share of declines explained by the filer's own disclosures or SEC XBRL), Cross-Year Consistency (company_memory's comparability gates), and Restatement Risk (disclosure-language classification counts on cross-document conflicts). A panel with nothing to measure says UNASSESSED — a single filing's restatement risk is never rendered as "low". Measured over the 83-filer replay: dashboard-recovered totals exactly match `REPORT_LATEST.md` (VERIFIED 159 / INSUFFICIENT_EVIDENCE 70 / UNSUPPORTED 9 / WRONG_MATH 0), and known-decline filers (TSLA/META/KO) cannot present as clean (`benchmark/reliability/DASHBOARD_REPORT.md`).

#### AI Analyst Mode

`aritiq/analyst.py` (`POST /analyst`) answers questions **only from claims that passed verification**, cites the facts it used, and refuses when the relevant number is UNCHECKED / INSUFFICIENT_EVIDENCE / WRONG_MATH. The boundary is deterministic on both sides of the model: blocked values are digit-stripped before prompting (the model can't leak a number it never receives), refusals fire *before* any model call, and answers are validated against a verified-number whitelist — a fluent hallucination is rejected, not returned. Measured over 234 real question/filer pairs: 72/72 blocked-topic questions refused pre-model, 0 gate failures; live narration verified end-to-end (`benchmark/reliability/ANALYST_REPORT.md`). What the model contributes is wording; which numbers may be spoken is decided by code.

### Audit a real 10-K by ticker

The fastest way to see Aritiq work: pick the **By ticker** tab, type a symbol (e.g. `AAPL`), and hit Audit. Aritiq fetches that company's latest 10-K from SEC EDGAR (free, public, no key), strips the HTML down to the financial-statements section, and checks whether the filing's own numbers are internally consistent — does the balance sheet balance, does EPS reconcile, does cash tie out — with no model in the verifier.

The ingestion is pure Python (`aritiq/edgar/`): `ticker → CIK → latest 10-K → strip HTML → extract statements`, all over SEC's free endpoints with a descriptive User-Agent. It locates the real statements by numeric density (the statement *names* appear many times in a filing — table of contents, MD&A, notes — but only the actual statements are followed by dense number tables). US-listed companies that file a 10-K are supported; foreign filers (20-F/40-F) and the specialized statement layouts of some banks/insurers are named limitations.

### Supported operations

**Core arithmetic operations (single document):**

| Operation | Formula | Notes |
|---|---|---|
| `percent_change` | (new − old) / old × 100 | catches the 30%/25% class of error |
| `absolute_change` | new − old | |
| `sum` | a + b + … | |
| `difference` | a − b | |
| `ratio` | a / b | |
| `margin_percent` | (num / denom) × 100 | gross/net/operating margin |
| `average` | mean | |
| `product` | a × b × … | |
| `identity` | restates one number | catches flat misstatements |

**Cross-statement & temporal checks (still no model in the verifier):**

| Operation | Checks | Notes |
|---|---|---|
| `internal_consistency` | a document's own numbers agree with each other | named rules: `balance_sheet_identity`, `eps_reconciliation`, `cash_flow_tie_out` — "the company's own numbers don't add up" |
| `trend_direction` | an ordered series moves up / down / flat | over a `(period, value)` series |
| `superlative` | a value is the max/min over a window | "highest margin in five years" |
| `consecutive_count` | N periods in a row satisfy a direction | "third consecutive quarter of growth" |
| `aggregate_filter` | sum/count over a filtered subset, composes into `percent_change` | B2C: "you spent 18% more on dining" |
| `definitional_flag` | **detects** a vague word next to a number; **does not resolve it** | routes to `NEEDS_REVIEW` — never invents a numeric threshold for "flat" |

Every cross-statement operation passes the same test the core nine pass: *given
grounded inputs, there is one objectively correct verdict, computable by a pure
function, with no model-judgment step.* The one candidate that fails that test —
"is a 4% change 'flat'?" — is deliberately **not** resolved; it is flagged for a
human. That discipline is the point: the moat got wider, not smarter.

### Verdict taxonomy

| Status | Meaning |
|---|---|
| `VERIFIED` | Recomputed value matches stated value within tolerance |
| `WRONG_MATH` | Operands grounded in source, recomputation disagrees — the headline catch |
| `UNSUPPORTED_NUMBER` | At least one operand missing from source; claim unverifiable |
| `AMBIGUOUS` | Divide-by-zero, wrong operand count, or multi-reading |
| `UNCHECKED` | Qualitative claim; no arithmetic applies; excluded from score |
| `NEEDS_REVIEW` | *(cross-statement)* A vague word ("flat") sits next to a number; no universal threshold exists, so it's routed to a human. Excluded from score. |
| `CONFLICT` | *(cross-statement)* Two source documents disagree on the same figure (restatement/typo). Surfaced, never silently resolved. |
| `PROPAGATED_ERROR` | *(multi-document)* This claim is not independently broken — its operands trace, through the dependency graph, back to a claim that is. Carries `caused_by` pointing at the root, so a reviewer sees one root cause plus its consequences instead of N flat flags. Excluded from the score (counted once, at the root). |

### Aritiq Score

The score (0–100) is a **trust signal**: how much should a reader trust the numeric claims in this summary? Weights are purpose-derived:

- `VERIFIED` → 1.0 (full credit)
- `WRONG_MATH` → 0.0 (zero — a confidently-wrong derived number is the scariest failure)
- `UNSUPPORTED_NUMBER` → 0.4 (unverifiable, not disproven)
- `AMBIGUOUS` → 0.4 (structural issue, not a confirmed error)
- `UNCHECKED` → excluded from the denominator
- `NEEDS_REVIEW` → excluded from the denominator *(cross-statement)*
- `CONFLICT` → 0.0 *(cross-statement)*
- `PROPAGATED_ERROR` → excluded from the denominator *(multi-document — counted once at the root)*

Raw counts are always shown alongside the composite score. Counts are unarguable; the score embeds a judgment call.

**Dependency weighting (multi-document).** The score now reports two numbers side by side — for example *Weighted 62 · Unweighted 81*. The **unweighted** number is the flat mean above. The **weighted** number weights each root claim's contribution by `1 + log(1 + downstream_count)`, so a `WRONG_MATH` on a figure many claims depend on costs more than one on an isolated leaf — logarithmically, so a single failure is meaningfully (not catastrophically) penalized. `PROPAGATED_ERROR` consequences are excluded so a root error is counted once. With no dependency structure, the weighted score equals the unweighted score exactly. Both are shown so the weighting stays auditable and never becomes a black box.

---

## Benchmark results

### Verifier precision (synthetic set, 32 unit tests)

| Metric | Result |
|---|---|
| Tests passing | **32 / 32** |
| Operations covered | All 9 (both directions each) |
| Edge cases covered | Divide-by-zero, bad operand count, missing operand, qualitative |
| False positives | 0 |
| False negatives | 0 |

The verifier is deterministic code on deterministic inputs. Correctness is provable, not measured.

### End-to-end accuracy (gold benchmark, 21 hand-labeled claims)

| Metric | Result |
|---|---|
| Claim recall | 100% (21/21) |
| Operation accuracy | 100% (21/21) |
| Operand-order accuracy | 100% (12/12 order-sensitive) |
| Verdict agreement | 100% (21/21) |
| Spurious extractions | 0 |
| Schema-rejected items | 0 |

**Important caveat:** the benchmark was run in replay mode against four hand-constructed documents. This is an optimistic upper bound — a single model on clean, controlled input. Real-world accuracy on messy SEC filings with nested tables, footnotes, and non-standard formatting will be lower. That gap is named, measured, and the honest next step.

To run the benchmark live against the API:

```bash
# Uses your BYOK settings from .env (ARITIQ_PROVIDER + the matching key).
python benchmark/eval_extraction.py --live
```

---

## Known limitations

These are stated here before anyone asks, because volunteering weaknesses is what makes the strengths credible.

**Extraction depends on an LLM.** Claim parsing uses whichever model you configure (Anthropic, OpenAI, Gemini, or Groq). Extraction errors propagate — a mis-ordered operand pair or a guessed operand can produce a false `WRONG_MATH` or a false `VERIFIED`. The benchmark measures this rate; it is not zero on real documents.

**Table and footnote parsing is hard.** Real 10-Ks use nested HTML tables, continuation footnotes, and non-standard number formatting. The current ingestion stage handles clean prose well and struggles with complex tables. This is named future work, not a solved problem.

**Qualitative claims are not checked.** "The company improved its competitive position" produces `UNCHECKED` — there is no arithmetic to verify. Aritiq covers numeric claims only.

**Narrow scope is a feature, not a bug.** The deterministic verifier catches arithmetic errors and flat misstatements with near-zero false positives on the claims it does flag. It does not attempt to judge plausibility, context, or forward-looking statements. That narrowness is what makes the catch defensible.

### Cross-statement limitations

**The verifier is model-free; its verdicts still rest on upstream extraction tags.** This is the honest boundary of the thesis. "Code verifies the arithmetic" is unconditionally true. But "code verifies the claim is about what the extractor *said* it's about" is not — the verifier trusts that the extractor tagged the EPS variant correctly, ordered the time series chronologically, and selected the right filtered subset. A wrong tag can fail silently (e.g. a mis-tagged shares variant flips the EPS guard from `AMBIGUOUS` to a confident verdict). The firewall guarantees no model grades the math; it does not guarantee the extractor's labels are right. We measure extraction error separately and report it broken out by type, never blended.

**Cross-document comparability is a genuine unsolved problem.** When a prior-period filing uses a different accounting presentation (a restatement, a segment reclassification), the "same" number may not be comparable even when both are correctly grounded. The source registry surfaces a `CONFLICT` when two documents disagree on a figure — it never silently picks a winner — but it cannot reconcile a presentation change. The restatement scan annotates such a conflict with whether the filer's own text *discloses* a restatement or reclassification near the disputed number (see below); it does not reconcile the presentation, and it does not determine what kind of change occurred.

**GAAP/non-GAAP and basic/diluted EPS are designed-around, not eliminated.** `eps_reconciliation` records which EPS variant it grounded and refuses to compare a basic EPS against diluted shares (it returns `AMBIGUOUS`, not a false `WRONG_MATH`). If the variant is unrecorded on either side, the check is held at `AMBIGUOUS` and **not run** — a `WRONG_MATH` from untagged operands can't be distinguished from a variant mismatch, so it is never emitted (the explanation names the fix: tag `eps_variant` on the claim and `category` on the shares operand). A `WRONG_MATH` on an `eps_reconciliation` claim is therefore trustworthy only when the extractor tagged the variant on both sides. Cross-statement checks can still produce a `WRONG_MATH` on a correctly-reported but unusually-presented number (a GAAP/non-GAAP reconciliation); the fix is more extraction metadata, not a smarter check.

**B2C categorization is a conditional guarantee.** "Is a Target purchase 'groceries' or 'household'?" is an ambiguity in the source data itself, not just in extraction. An `aggregate_filter` verdict is conditional on the categorization scheme, and an operand whose category was inferred carries `category_inferred` provenance plus a scheme-version stamp so a "verified-but-recategorized" claim is visibly different from a clean match — and so categorization *drift* between months is detectable, not invisible. The B2C path is scoped to synthetic or the user's own consented data; no feature stores or transmits other people's financial documents.

**Real-document accuracy is still unmeasured.** The cross-statement benchmarks prove *verifier-logic precision* on constructed inputs (synthetic statements with exact ground truth, and a 10-K-shaped table fixture run end-to-end). They are explicitly **not** a real-filing accuracy number — measuring that honestly requires live extraction over hand-labelled filings, which is named future work. No fabricated real-10-K figure appears anywhere in this repo.

### Multi-document limitations

**The dependency graph only works if extraction tags the edges.** The dependency-graph propagation, and the weighting that builds on it, do nothing unless the extractor tags when one claim's operand is another claim's stated output (`depends_on`). An unlinked shared number simply doesn't propagate; a wrongly-linked one propagates where it shouldn't. The graph logic is provably correct given correct edges — but the edges are an extraction property, measured separately, not a guarantee of the verifier.

**The restatement scan detects disclosure language, not restatement type.** The restatement scan reads a bounded window of text near a `CONFLICT` figure for the filer's own restatement or reclassification language. `EXPLICIT_RESTATEMENT` means that language was found; `POSSIBLE_RECLASSIFICATION` and `UNEXPLAINED` are claims about the *text* ("reclassification language is / no disclosure language is present near the number"), **not** determinations about the accounting. It does not diff XBRL taxonomy tags and does not assert what kind of change occurred. The scan is only as good as the context the extractor located the figure in; a mis-located figure yields an annotation about the wrong text.

**The weighted score embeds a deliberate judgment call.** The choice of `1 + log(1 + downstream_count)` is a defensible weighting, not a derived constant — logarithmic so a single failure is meaningful but not catastrophic. The unweighted score is always shown beside it so the judgment stays visible and comparable, and the two are equal whenever there is no dependency structure to weight by.

---

## Running the project

Everything runs locally. There is no sign-in and no hosted service — you bring your own model API key (BYOK).

### Prerequisites

- Python ≥ 3.9
- Node.js ≥ 18 (only if you want the web UI)
- Your own model API key for live extraction — one of Anthropic, OpenAI, Gemini, or Groq. Not needed for the tests, the offline demo, or the bundled examples.

### 1. Configure your key (BYOK)

```bash
cp .env.example .env
# then edit .env — set ARITIQ_PROVIDER and paste the matching key, e.g.
#   ARITIQ_PROVIDER=anthropic
#   ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is git-ignored, so your key never gets committed. See `.env.example` for all supported providers.

### 2. Backend

```bash
# Install core deps (+ the SDK for the provider you chose)
pip install -r requirements.txt
pip install anthropic        # or: openai / google-genai, to match ARITIQ_PROVIDER

# Run the tests (no key needed)
pytest tests/ -q

# Run the offline demo (no key needed)
python demo.py

# Start the local API server
uvicorn backend.app:app --reload --port 8000
# → http://localhost:8000
```

The server audits the bundled examples with **no key**. To audit your own documents, it reads the key from your `.env`.

### 3. Frontend (optional web UI)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

Then open `http://localhost:3000`, paste a source document and an AI-generated summary, and hit Audit. (The UI talks to the backend on `http://localhost:8000` by default — override with `NEXT_PUBLIC_API_URL`.)

### Project structure

```
aritiq/
  core/                       # ── the verification path: NO LLM anywhere here ──
    schema.py        # Claim, Operand, registry, all enums
    verify.py        # Deterministic verifier — dispatches cross-statement ops to rules.py
    rules.py         # cross-statement pure rule functions (cross-statement, temporal, …)
    registry.py      # Source registry + cross-document CONFLICT detection (§2.2, §7)
    tables.py        # Structured table extraction + unit normalization (§2.1, §2.2)
    graph.py         # dependency DAG + propagated-error walk
    restatement.py   # restatement disclosure-language scan
    conflicts.py     # cross-document CONFLICT verdicts (registry + restatement bridge)
    score.py         # Aritiq Score: purpose-derived weights + dependency weighting
  edgar/                      # ── SEC EDGAR ingestion: NO LLM, no cost ──
    sec.py           # ticker → CIK → latest 10-K → strip HTML → extract statements
  extract/                    # ── the ONLY place an LLM runs ──
    schema.py        # Pydantic contract for LLM output
    prompt.py        # summary-audit extraction prompt (+ multi-doc routing)
    cross_statement.py # cross-statement extraction prompt + applicability guard
    extractor.py     # Provider-agnostic engine (Anthropic / OpenAI / Gemini / Groq)
  pipeline.py        # audit() / audit_documents() → AuditResult
backend/
  app.py             # local FastAPI server: /audit, /audit-multi, /audit-ticker, /examples, /health, /dashboard, /analyst, /timeline
frontend/
  app/page.tsx       # Single-page UI
  components/        # ScoreRing, ClaimsTable, ClaimRow, InputPanel, …
benchmark/
  gold_set.json              # 21 hand-labeled claims across 4 documents
  eval_extraction.py         # extraction harness: replay + live, fault-injection self-test
  runs/                      # Saved model outputs (replay artifacts)
  cross_statement_gold.json  # synthetic statements, exact ground truth
  eval_cross_statement.py    # per-rule benchmark + fault-injection self-test
  eval_table_extraction.py   # end-to-end table→normalize→verify on a 10-K-shaped fixture
  table_fixtures/            # Constructed 10-K-style excerpts (fabricated numbers)
tests/
  test_verifier.py           # 32 unit tests, all operations both directions
  test_extract.py            # 29 extraction tests, mocked (no API key)
  test_cross_statement.py    # cross-statement rules + the EPS-variant confound
  test_temporal.py           # trend / superlative / consecutive-count
  test_b2c_aggregate.py      # aggregate_filter + category-inferred provenance
  test_definitional_flag.py  # flag-and-route discipline (no invented threshold)
  test_tables.py             # table parsing + unit normalization
  test_registry.py           # registry + cross-document conflict detection
  test_cross_statement_extract.py  # extraction applicability discipline + firewall
  test_extraction_firewall.py # AST proof that no verifier code imports a model
  test_graph.py              # DAG construction + propagation
  test_score_weighted.py     # dependency-weighted score + degrade-to-flat invariant
  test_restatement.py        # disclosure-language scan + over-fire boundary
  test_vesper_endtoend.py    # every component on the Vesper pair (deterministic, no LLM)
  test_pipeline_multidoc.py  # audit_documents wiring + cross-doc CONFLICT surfacing
demo.py              # Offline verifier demo
demo_extract.py      # Offline pipeline demo (replay extractor)
```

### Running the consistency benchmarks

```bash
# Cross-statement consistency, reported PER RULE (never blended):
python benchmark/eval_cross_statement.py
python benchmark/eval_cross_statement.py --selftest   # fault injection: proves it has teeth

# End-to-end table-grounded verification (parse → normalize → verify):
python benchmark/eval_table_extraction.py
```

---

## The pitch (one paragraph)

Aritiq is infrastructure, not a chatbot. It's a guardrail you install before shipping LLM-generated financial output — earnings summaries, analyst reports, invoice audits, model-generated 10-K commentary. It catches the category of error that grounding checkers structurally miss: derived numbers (growth rates, margins, ratios) that are computed wrong even when every source number is present. Its catch on arithmetic is unambiguous — wrong math is wrong, no judgment call — which gives it a near-zero false-positive rate on the contradictions it does flag. That's what makes a guardrail stay installed instead of getting ripped out.

---

Aritiq is open source. Contributions welcome — see the code, run the tests, and open a PR.
