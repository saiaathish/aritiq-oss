# Aritiq — Technical & Initiative Overview
*Prepared for external evaluation (YC Startup School application review)*

## 1. What Aritiq Is

Aritiq is an AI-assisted SEC filing verification platform. It reads a public company's
10-K/10-Q filings, extracts the financial claims a filing makes (numbers, ratios,
year-over-year comparisons, EPS math, cash flow reconciliations), and then checks
whether those claims are internally consistent, arithmetically correct, and properly
grounded in the filing's own numbers — before a human analyst, journalist, or investor
has to.

The pitch in one line: **LLMs are good at reading messy documents, bad at arithmetic
and judgment. Aritiq uses the LLM only to read, and a fully deterministic engine to
verify.**

## 2. The Problem

Financial filings are long, dense, and self-referential — a single 10-K can contain
hundreds of numbers that are supposed to tie out to each other (income statement to
cash flow, EPS to net income and share count, current-year to prior-year restatements,
segment totals to consolidated totals). Analysts catch inconsistencies manually, slowly,
and inconsistently. Generic LLM tools that try to "just ask GPT if this filing looks
right" fail in a specific, dangerous way: LLMs hallucinate arithmetic confidently. A
tool that uses an LLM to both extract *and* judge financial correctness inherits the
LLM's numerical unreliability into a domain where being wrong is expensive
(reputational, financial, legal).

## 3. Core Architecture Decision (the thing that makes this defensible)

```
SEC Filing → Section Parser → LLM Structured Extraction → Deterministic Verification
           → Dependency Graph → Weighted Scoring → API → Frontend
```

**Golden rule enforced throughout the codebase:** the LLM extracts facts; it never
performs arithmetic, comparison, or business-logic judgment. All scoring, tolerance
checks, cross-statement consistency, and verdict assignment happen in plain,
auditable Python — no model call sits anywhere near the decision path. This is
mechanically enforced with a "firewall" check (a grep-based CI gate) that fails the
build if any model SDK import appears inside the core verification module.

This separation is the core IP claim: not "we prompt an LLM to audit a filing" (which
every competitor could trivially copy and which inherits LLM unreliability), but
"we built a deterministic financial-verification engine that happens to use an LLM
as a structured-data front end."

## 4. What the Verification Engine Actually Checks

- **Arithmetic verification** — addition/subtraction tie-outs, percent change, CAGR,
  margin calculations, ratio validation.
- **Cross-statement consistency** — does a number on the income statement agree with
  where it's referenced on the cash flow or balance sheet; temporal validation across
  reporting periods; aggregate filtering to avoid false matches; definitional checks
  (e.g., "operating margin" computed consistently).
- **Dependency graph / provenance DAG** — every verified claim is a node; if an
  upstream number is wrong, everything computed from it is marked
  `PROPAGATED_ERROR` rather than independently re-flagged, and the final score is
  dependency-weighted so a single bad input doesn't get double-counted.
- **Restatement detection** — classifies a changed number as an
  `EXPLICIT_RESTATEMENT`, a `POSSIBLE_RECLASSIFICATION`, `UNEXPLAINED`, or
  `UNCLASSIFIED`, instead of flatly calling it an error.
- **Evidence gating (`INSUFFICIENT_EVIDENCE`)** — the most important safety feature.
  If the filing doesn't provide enough information to check a claim (e.g., liabilities
  aren't fully broken out, or "restricted cash" language is ambiguous), the system
  returns `INSUFFICIENT_EVIDENCE` rather than accusing the filer of an error.
  `WRONG_MATH` is reserved strictly for cases with correct operands, sufficient
  evidence, and genuine arithmetic disagreement. This asymmetry — biasing toward
  "we don't know" over "you're wrong" — is a deliberate design choice to avoid false
  accusations against real companies.

## 5. Current Engineering Maturity (honest, not marketing)

- **~390 automated tests passing**, 1 skipped, run on every change.
- **Verification engine: ~95% complete** — this is the most mature, closest-to-
  production part of the system.
- **Extraction layer: hardened, not yet fully proven** — recent work added
  enum-alias normalization (so small LLM output variance doesn't break parsing),
  NaN/Infinity rejection before verification, and output caps to protect latency.
  Known failure modes have been found and diagnosed on real filings (e.g., a bank's
  EPS reconciliation using total net income instead of income-to-common, a filer
  whose financial statements are incorporated by reference into a separate exhibit
  rather than the base 10-K) — these are documented, root-caused, and queued for
  fixes rather than papered over.
- **API/backend: hardened for real use** — optional API-key auth, per-client rate
  limiting, request size caps, and a bring-your-own-key (BYOK) flow where a caller's
  model API key is used per-request and never persisted server-side.
- **Live benchmark run completed at scale**: 83 real filers pulled live from SEC
  EDGAR, spanning software, banking, insurance, REITs (including UPREIT and
  data-center subtypes), utilities, industrials, aerospace, healthcare
  payer/provider, transportation, fintech, and recent corporate spinoffs. 238
  in-scope claims: 158 verified (66.4%), 64 correctly gated to
  insufficient-evidence (26.9%), 9 extraction misses (3.8%, diagnosed and
  attributed to the extraction layer, not the verifier), and 7 flagged
  arithmetic disagreements (2.9%) currently under manual review rather than
  claimed as confirmed catches. Five filers (Berkshire Hathaway's two share
  classes, Caterpillar, GE Vernova, HCA Healthcare) legitimately returned zero
  extracted claims and are logged as such, not silently dropped. Results are
  broken down per sector and per statement type (balance sheet identity, EPS
  reconciliation, cash flow tie-out) so weak spots are visible rather than
  averaged away — for example, cash flow tie-out currently verifies only 37.5%
  of claims because the restricted-cash evidence gate fires on the majority of
  filers, by design, rather than guessing.
- **Frontend**: working end-to-end prototype — ticker search, live SEC filing
  retrieval, filing preview, audit report, weighted score, consistency report. Not
  yet polished; lacks dependency-graph visualization and dedicated UI for
  propagated-error / insufficient-evidence verdicts.
- **Not yet done**: deployment (frontend/backend not yet live), broader BYOK UX,
  and a large-scale (50+ filing) benchmark needed before making any public accuracy
  claim.

**Overall estimated completion: ~40–45%** of a shippable product — but the ~40% that
exists is the architecturally hard part (deterministic financial reasoning at scale),
not the easy part (CRUD, UI chrome). The remaining ~60% is largely execution
(deployment, broader benchmarking, UI polish) rather than open research risk.

## 6. Why This Is a Real Technical Moat, Not a Wrapper

1. The deterministic core doesn't degrade if the underlying LLM changes, gets
   worse, or gets more expensive — swapping GPT-4 for Claude for Gemini for a local
   model only affects extraction quality, never the verification logic. This makes
   the product resilient to the exact commoditization risk most "AI wrapper"
   startups face.
2. The evidence-gating system (`INSUFFICIENT_EVIDENCE`) required inventing genuinely
   new logic per financial statement type (balance sheet completeness, EPS basis
   matching, restricted-cash detection) — it is not a general-purpose feature, it's
   domain-specific engineering that reflects real time spent reading actual filings
   and actual failure modes (AMD, Palantir, JPMorgan, Wells Fargo all surfaced real,
   distinct bugs that were root-caused rather than ignored).
3. The project is being built with a benchmark-first, honesty-first discipline:
   every round of work is graded against a real test suite and real live SEC data,
   failures are documented rather than hidden, and features that don't have
   sufficient underlying data (e.g., segment reconciliation — the SEC's own
   companyfacts cache was scanned and found to lack usable dimensional data) were
   explicitly *not* shipped rather than faked. This engineering discipline is itself
   a signal of founder quality that's harder to fake than a slick demo.

## 6a. Two Hard Subproblems We Actually Solved

These were not anticipated in advance — both were found by running the benchmark
against real filings and reading the failures, which is the point of building the
benchmark in the first place.

The first came from JPMorgan's 10-K. The verifier flagged an EPS reconciliation as
arithmetically wrong: diluted EPS of $20.02 didn't match net income of $57.048B
divided by 2,781.5M diluted shares, which comes out to $20.51. The gap looks small,
but at that scale it's not rounding error — it's a basis mismatch. Diluted EPS at
any bank with preferred stock is computed on net income *available to common
shareholders*, meaning preferred dividends are subtracted from net income before
dividing by share count. The extractor had pulled total net income instead. A naive
fix would be to just re-run the arithmetic with a "corrected" number, but that
reintroduces exactly the failure mode Aritiq exists to prevent: an LLM silently
deciding what the "real" income figure should be. Instead, the fix is deterministic
context detection in extraction post-processing — the system looks for explicit
preferred/common-income language in the filing itself (including bank-specific
phrasing like "net income applicable to common equity") and, when that context is
present but the EPS math still doesn't tie out cleanly, downgrades the verdict to
`INSUFFICIENT_EVIDENCE` rather than asserting `WRONG_MATH`. When the basis is
unambiguous, the reconciliation verifies normally. Nothing about this required the
model to make a judgment call; it required reading the filing's own words more
carefully before doing arithmetic on them.

The second came from Wells Fargo, which returned zero extracted claims entirely.
Reading the actual text sent to the model showed why: it was 24,000 characters of
cover page and "Item 1: Business" narrative, with no financial statement tables
anywhere in it. Wells Fargo's 10-K explicitly incorporates its financial statements
by reference to a separate Annual Report to Shareholders exhibit rather than
including them in the base document — a filing pattern several large banks use.
The section-detection logic that finds financial statements inside a 10-K was
working correctly; the statements simply weren't in the document it was given. The
fix follows the filing's own accession index (`index.json`) for sibling documents —
including SEC's structured interactive report pages — and falls back to those when
the primary document's statement slice scores as boilerplate rather than tabular
financial data. This generalizes beyond Wells Fargo to any filer using the same
incorporate-by-reference structure, which is exactly the kind of fix that a
benchmark run surfaces and a hand-picked demo set never would.

## 7. Market Angle

Buyers who need this: equity research desks, short-sellers and activist investors,
compliance/audit teams, financial journalists, and increasingly, AI systems
themselves that consume SEC data and need a trust layer before treating a number as
fact. As more financial analysis gets automated by other AI tools, a deterministic
verification layer sitting between "raw filing" and "downstream AI consumer" becomes
more valuable, not less — it's positioned as infrastructure other AI products would
want to sit behind, not just a standalone analyst tool.

## 8. Founder Working Style (relevant to YC evaluation)

The build process itself has been notably rigorous for a pre-seed/solo project:
strict test-driven iteration (test count tracked every round), a self-imposed
architectural "firewall" preventing scope creep of LLM responsibility into
deterministic logic, real (not synthetic) SEC data used for every benchmark, and a
consistent refusal to claim more maturity than the evidence supports (e.g.,
explicitly declining to ship a guidance-tracking feature after real data showed it
would be unreliable, and explicitly flagging a "caught error" as likely a false
positive rather than claiming a win). This is the kind of engineering and
intellectual honesty that's a strong (if qualitative) signal for a technical
solo-founder application.
