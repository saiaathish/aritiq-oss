# Aritiq — Day 2: LLM-assisted claim extraction

Day 2 builds the **only** stage of Aritiq that uses an LLM: turning a source
document plus an AI-generated summary into structured, schema-valid `Claim`
objects that the Day 1 verifier can check. The whole design treats this stage
with suspicion, because its errors are the ones that can propagate.

> One line: **the LLM parses prose into claims; deterministic code still does
> all the checking.** This stage is firewalled from the verifier so a parse
> error can't become a confident wrong verdict.

---

## What was built

| Piece | File | Purpose |
|---|---|---|
| Strict JSON contract | `aritiq/extract/schema.py` | Pydantic models (`RawClaim`, `RawOperand`); hard validation; number cleaning; conversion to the Day 1 `Claim` dataclass |
| Extraction prompt | `aritiq/extract/prompt.py` | Operation catalog, operand-order rules, decrease-sign rule, grounding rules, "never guess an operand", JSON-only output |
| Extractor engine | `aritiq/extract/extractor.py` | Provider-agnostic (Anthropic default, OpenAI optional); injectable `complete_fn`; robust parse → validate |
| Pipeline | `aritiq/pipeline.py` | `audit(source, summary)` → extract → verify → score in one call, firewall intact |
| Gold benchmark | `benchmark/gold_set.json` | 4 documents, **21 hand-labeled claims** with traps |
| Eval harness | `benchmark/eval_extraction.py` | Measures recall / operation / order / grounding; `--selftest` proves it detects errors |
| Tests | `tests/test_extract.py` | 21 tests, no API key needed |
| Offline demo | `demo_extract.py` | Full pipeline on a real document, no key |

The verifier and scorer were **not touched** — `aritiq/core/` is exactly as
Day 1 left it.

---

## How to run

```bash
pip install -r requirements.txt          # pydantic + pytest

python -m pytest -q                       # 61 tests, no API key
python benchmark/eval_extraction.py       # offline replay benchmark
python benchmark/eval_extraction.py --selftest   # prove the harness detects errors
python demo_extract.py                    # full pipeline on one document, offline

# With a real model:
export ANTHROPIC_API_KEY=sk-...
python benchmark/eval_extraction.py --live
python demo_extract.py --live
```

The extractor is provider-agnostic. Default backend is Anthropic
(`claude-sonnet-4-6`); set `ARITIQ_PROVIDER=openai` or pass `provider=`/`model=`
to change it. Anything that can implement `(system_prompt, user_prompt) -> str`
can be injected as `complete_fn`, which is how the tests and the offline
benchmark run with no network.

---

## The firewall, in practice

`aritiq/extract/` imports the Day 1 **schema** (to build `Claim` objects) but
never imports `verify` or `score`. `verify.py` imports neither extraction nor
any LLM SDK. Two tests assert this structurally by parsing the import graph
(`tests/test_extract.py::TestFirewall`), so the separation can't rot silently.

Belt and suspenders against bad model output:

1. **JSON-array discipline** — the prompt demands a bare JSON array; the
   Anthropic backend additionally prefills `[` to force it.
2. **Hard validation** — every array element is validated independently by
   Pydantic. A malformed claim (bad operation, bad source label, missing field,
   unparseable number) is recorded as an `ExtractionIssue` and **discarded** —
   it never reaches the verifier. One bad claim doesn't sink the rest.

A deliberate choice in number cleaning: `"$1,200"` → `1200.0` and `"25%"` →
`25.0`, but a magnitude suffix like `"100M"` is **not** auto-expanded. Silently
turning `"100M"` into `1e8` next to a sibling operand written as a bare `125`
would create a hidden scale mismatch — the exact kind of quiet corruption Aritiq
exists to catch. Unparseable values surface as visible issues instead.

---

## Replay self-check (same-model, clean inputs) — NOT a real-document accuracy number

**Read this framing before the table.** The numbers below are a *replay
self-check*, not a measured real-world accuracy. No API key was available in the
build session, so the "model outputs" in `benchmark/runs/` were produced by
Claude (Opus-class) following the production prompt, then scored against
hand-built gold labels on four clean, trap-exercising documents. That is the
strongest extractor on the easiest inputs, grading a controlled set — an
upper bound that confirms the *plumbing and the traps work*, not a typical-case
figure. The honest, still-unmeasured number is end-to-end accuracy on messy real
filings; we expect it to be lower and we do not fabricate it.

Run: `python benchmark/eval_extraction.py` (offline replay).

| Metric | Replay self-check (clean inputs, strong model) |
|---|---|
| Claim recall | 21/21 found |
| Operation accuracy | 21/21 |
| Stated-value accuracy | 21/21 |
| Operand-order accuracy | 12/12 order-sensitive |
| Grounding accuracy | 21/21 |
| Fully-correct claims | 21/21 |
| Spurious extractions | 0 |
| Schema-rejected items | 0 |
| Verdict agreement | 21/21 — same verifier verdict from extracted vs. gold operands |

### Why this is a self-check, not a measurement

The perfect score is **real but circular, and it is not the headline.** Three
things bound it, stated plainly so no one has to discover them:

1. **Same-model upper bound.** No API key was available in the build session, so
   the replayed model outputs in `benchmark/runs/` were produced by Claude
   (Opus-class) following the production prompt, blind to the gold labels. That
   is the *strongest* extractor grading the *easiest* inputs — an upper bound,
   not a typical-case number. Run `--live` with your own key (and ideally a
   smaller production model) for an independent figure; a weaker model will
   score lower, especially on the traps below.
2. **Clean inputs by design.** These four documents are well-formed earnings
   releases and an invoice. Real 10-K tables and footnotes are far messier;
   table parsing is named future work, not a solved problem (see Day 4).
3. **Small set.** 21 claims is enough to exercise every operation and every
   trap once, not enough to put tight error bars on a percentage.

The intellectually honest split — and the thing to say out loud — is:

> *The verifier is deterministic and essentially perfect. Extraction on clean
> inputs with a strong model is also near-perfect. The open, interesting,
> still-unmeasured number is end-to-end accuracy on messy real documents, and we
> expect it to be lower. Day 4 measures that.*

### Why "verdict agreement" is the metric that matters

An extraction slip only hurts the product if it changes the verdict. A flipped
operand pair on a claim that's wrong either way still ends up `WRONG_MATH`; who
cares. So alongside the four extraction metrics, the harness reports **verdict
agreement**: does the final verifier verdict come out the same when fed the
extracted operands vs. the gold operands? That is the number that maps to "would
a user have been misled."

---

## The harness has teeth (it is not a blind grader)

A 100% is only meaningful if the grader can actually fail things. Run:

```bash
python benchmark/eval_extraction.py --selftest
```

It injects the build guide's named failure modes into the faithful outputs and
asserts each is caught:

| Injected fault | Caught by |
|---|---|
| Dropped a claim | recall 100% → 95.2% |
| Wrong operation (margin→ratio) | operation 100% → 95.0% |
| Operand-order flip | order 100% → 91.7% |
| Misread stated value | stated 100% → 95.0% |
| **Guessed operands → false `VERIFIED`** | grounding ↓ and **verdict agreement → 76.2%** |
| Malformed claim (bad enum) | schema-rejected = 1 |

All seven checks pass (`tests/test_extract.py::TestHarnessHasTeeth` runs this in
CI). The guessed-operand case is the important one: a fabricated number that
makes the math work is the worst silent failure, and the harness flags it as a
verdict disagreement.

---

## Named fragile cases (where this *will* break first)

These are baked into the gold set as traps and currently pass, but they are the
points most likely to fail on a weaker model or messier input. Volunteering them
is the point:

- **Operand order on "from X to Y" / "fell to Y from X"** (A1, A3, D1). Lists
  the new value first; a model that takes appearance order inverts the change.
- **Sign of decreases** (D1). "Dropped 25%" must become `stated_value = -25`.
  Get the sign wrong and an honest summary reads as `WRONG_MATH`.
- **Grounded vs. inferred on unit conversions** (C1–C3, C5). Source says "$1.2
  billion"; summary says "$1,200 million". The converted figure is *inferred*,
  not grounded — easy to mislabel.
- **Inferred vs. missing** (B4). The $4,500 taxable base isn't printed in the
  invoice; it's subtotal − discount. Marking it *missing* would turn a real
  `VERIFIED` into `UNSUPPORTED_NUMBER`.
- **Missing, not guessed** (C4). International revenue is absent from the source.
  The extractor must mark the operands *missing* and never invent a number.

---

## Day 2 "done when" — checklist

- [x] Hand the pipeline a summary + source, get back schema-valid `Claim`s — `audit()` / `demo_extract.py`.
- [x] Strict schema validation; malformed claims discarded/flagged, never passed through.
- [x] Operand grounding modeled (grounded / inferred / missing) with verbatim source text + optional spans.
- [x] Extractor prompted hard against guessing operands.
- [x] Extraction accuracy **measured** on a hand-labeled set, with failure cases named and a self-test proving detection.

## Honesty-checklist items touched today

- [x] No LLM in the verification path — asserted structurally by tests.
- [x] Extraction accuracy measured and reported, with failure cases named.
- [x] Tolerance settings stated (Day 1 defaults: ±0.5pp / ±0.5%).
- [x] No "production-ready" or "100% accurate" language — the 100% is explicitly framed as a same-model, clean-input upper bound.
- [ ] Benchmark reports verifier number **and** end-to-end number on **real** documents — deferred to Day 4 (this is the honest, lower number).

---

## Known limitations / what's next

- The reported accuracy is a strong-model, clean-input upper bound; the
  meaningful end-to-end number on messy real filings is Day 4.
- No table/footnote parsing yet — scoped intentionally to clean prose inputs.
- Scoring still uses Day 1's placeholder weights; purposeful calibration is Day 3.
- Live runs require a key and an installed SDK; everything else (verifier,
  tests, replay benchmark, demo) runs offline.
