# Aritiq — Phase 2 Progress

*Backend expansion: from a working demo to a research-grade system, with the moat made wider — and provably still a moat.*

## The one-paragraph version

Phase 1 proved a single thesis: an LLM parses messy financial prose into structured claims, and deterministic code — with no model anywhere in it — verifies the arithmetic. That firewall is what earned Aritiq its credibility, because "wrong math is wrong" needs no judgment call and produces near-zero false positives on what it flags. Phase 2 does not touch that principle. It widens the space of inputs the deterministic verifier can ground and check: from one clean document with nine arithmetic operations, to a registry of cross-referenced documents, parsed tables, and time series, checked with six new but still fully deterministic operations, applicable to both a hedge fund's earnings analysis and a consumer's budgeting app. The verifier got wider. It did not get smarter. For a tool whose entire pitch is "the verifier contains no model," that is the only correct direction to grow.

## What shipped

All six sequencing steps from the research roadmap are built, tested, and benchmarked. The verification path grew by ~765 lines of pure, model-free code across three new core modules, and the test suite grew from 61 tests to **151, all passing**.

**Step 1 — Source registry (§2.2).** Phase 1 assumed "the source document": one string both operands of a claim live in. That breaks the moment a claim spans filings ("revenue grew 12% year-over-year"). The registry replaces the single string with a small keyed collection so an operand can name *which* document it came from. It is deliberately tiny — its value is representational: it makes multi-document claims *expressible*. It also surfaces the one new failure mode it introduces (two filings disagreeing on the same figure) as a `CONFLICT`, and never silently picks a winner.

**Step 2 — Cross-statement consistency (§3.3).** The highest value-to-risk feature: does a document's own balance sheet balance? Does its stated EPS match net income over shares from the same filing? Does the cash-flow statement's ending cash tie to the balance sheet's cash line? These are internal-consistency checks the company's own numbers should satisfy — pure arithmetic, applied claim-to-claim instead of claim-to-source. One new operation, `internal_consistency`, dispatches to three named rules, so the verifier doesn't grow one bespoke function per check. This is the strongest demo moment in the phase: "the company's own numbers don't add up" is a catch a grounding checker structurally cannot make.

**Step 3 — Table + footnote extraction (§2.1–2.2).** The "Stage 1 grows up" work, done in the deterministic zone. Tables are parsed into `(row_label, column_label, value, unit_footnote)` structure rather than flattened to prose, with the literal header strings preserved so a header mis-attribution is auditable. A separate normalization pass converts "$1.2B", "$1,200M", and a cell that's implicitly "in thousands" into one canonical scale before the verifier ever sees them — and correctly honors the "except per-share data" exception so EPS is not rescaled into nonsense. A table-grounded operand verifies through the *unchanged* verifier exactly as a prose-grounded one does. That invariance is the evidence the firewall design was right the first time.

**Step 4 — Temporal consistency (§3.2).** Three operations over an ordered `(period, value)` series: `trend_direction` ("grew for the third consecutive quarter"), `superlative` ("highest margin in five years"), and `consecutive_count`. Each is a comparison over an ordered sequence — still pure computation, no model judgment.

**Step 5 — B2C aggregate-filter (Axis C).** The same firewall applied to consumer documents. `aggregate_filter` sums or counts a filtered transaction subset, then composes into the existing `percent_change` — two compositional steps, not a new kind of math. Categorization is the new, explicitly-labeled extraction risk: an operand whose category was inferred by the LLM carries `category_inferred` provenance plus a scheme-version stamp, so a "verified-but-recategorized" claim is visibly different from a clean match, and categorization drift between months is detectable rather than invisible.

**Step 6 — Logical/definitional flagging (§3.4).** The disciplined non-feature. "Costs were flat, but the table shows a 4% increase" *sounds* checkable, but "flat" has no universal numeric threshold — it is a judgment call dressed as a fact. So this does not build a verifier. It detects that a qualitative word sits next to a number (cheap, deterministic) and routes the claim to `NEEDS_REVIEW` for a human — it never invents a cutoff and pretends the resulting verdict is objective. Resisting the pull to make everything resolvable is exactly the discipline that keeps the moat defensible.

## How we know it works (and where the numbers stop)

The benchmarks are reported the way the roadmap demands: **broken out by rule and by claim type, never blended into one headline.**

The cross-statement benchmark runs seven constructed financial statements with known-correct and known-broken relationships through the actual rule functions. Per-rule precision is 3/3 for `balance_sheet_identity`, 3/3 for `eps_reconciliation`, and 2/2 for `cash_flow_tie_out` — exact, because it is pure arithmetic on pure inputs. A fault-injection self-test corrupts each passing case and confirms the verdict flips, so a perfect score reflects a real check, not a blind grader.

The end-to-end table benchmark takes a 10-K-shaped fixture (pipe tables, an "in thousands, except per-share" footnote, parenthesized negatives, multiple period columns) and runs the whole pipeline — parse, normalize, ground from cells, verify — with all three cross-statement rules passing. This proves the §2.3 invariance: `verify.py` did not change to handle tables.

**What is deliberately absent: a real-10-K accuracy number.** Phase 2's benchmarks prove verifier-logic precision on constructed inputs. They are explicitly not a measurement of extraction accuracy on messy real filings — that requires live extraction over hand-labelled filings, and we do not fabricate it. The Phase 1 replay "100%" is reframed in the notes as a same-model self-check on clean inputs, not a measured real-world figure. The honest, still-open number is end-to-end accuracy on real documents, and we expect it to be lower.

## Honesty checklist (roadmap §8)

- Every new operation passes the §3.1 test — one objectively correct, model-free verdict given grounded inputs — and the reason fits in one sentence. (Verified independently by an adversarial review pass.)
- Provenance types are *extended*, not collapsed: `grounded_table_cell`, `grounded_prose`, `category_inferred`, plus per-operand `doc_id` for cross-document claims.
- Benchmark numbers are reported broken out by source/claim type, never blended.
- The B2C data-handling approach (synthetic/consented data only) is stated plainly in the README before anyone asks.
- No claim type was added because it sounded impressive — `definitional_flag` is the proof, since it deliberately refuses to resolve anything.
- The README's "known limitations" section grew with this phase: cross-document comparability, the extractor-tag dependency, categorization ambiguity, and non-GAAP/basic-vs-diluted reconciliation are all named.

## The honest boundary of the thesis

Worth stating out loud, because saying it first is far stronger than being caught on it: the verifier is genuinely model-free, but its verdicts are only as sound as the extractor's tags. "Code verifies the arithmetic" is unconditionally true. "Code verifies the claim is about what the extractor *said* it's about" is not — the verifier trusts that the EPS variant was tagged correctly, that the series was ordered chronologically, that the right subset was filtered. A wrong tag can fail silently. The firewall guarantees no model grades the math; it does not guarantee the labels are right. We measure that error separately and report it by type. That boundary is not a weakness to hide — it is the precise line that makes everything inside it defensible.

## Definition of done — met

The source registry exists and multiple multi-document claim types verify end-to-end with no model in the verification path. Table-grounded extraction works on a 10-K-shaped fixture, reported separately from prose. Multiple new operations ship with their own synthetic test suites. The B2C variant runs end-to-end on synthetic data with `aggregate_filter`, and its categorization limitation is written down. The honesty checklist passes. And for every new feature shipped, there is a one-sentence reason it is still "code verifies" and not "a smarter model grading another model" — stated without flinching, exactly as the original guide demanded.

The bar carried forward from Phase 1 was never "impressive." It was: a wider moat, provably still a moat, with the new limits stated as plainly as the old ones. That is what shipped.

---

*Aritiq — built for YC Startup School 2026. The verifier contains no model.*
