# Aritiq as a trust layer — the correctness gate in front of an AI agent

This is what it looks like for an external AI agent to treat **Aritiq as a
correctness gate before it makes a factual claim** — the "System 4" pattern from the
reviewer feedback. It is the difference between an AI product that *says a number*
and one that *says a number Aritiq verified*.

## The pattern

Most "AI + finance" tools let a language model read a filing and then state a
figure. The figure is usually plausible and occasionally wrong, and nothing in the
pipeline can tell the two apart. Aritiq inverts the flow: a claim is usable only
after the **deterministic verifier** has ruled on it. `trust_layer_demo.py`
simulates the consumer side of that contract — a deliberately dumb "agent" (string
templating, no second LLM call) that answers a question about a company but is
allowed to assert only what Aritiq marked `VERIFIED`, and must decline or hedge when
the relevant claim is:

- `WRONG_MATH` — Aritiq found a real disagreement → **refuse** and route to a human.
- `INSUFFICIENT_EVIDENCE` — Aritiq declined to certify (e.g. restricted cash makes a
  cash tie-out un-checkable, or continuing-ops vs total EPS basis is unresolved) →
  **flag as unverified**, don't assert.

The point is the trust gate, not the chatbot. The agent logic is intentionally
trivial so that all the trustworthiness comes from Aritiq's verdict, not from the
agent being clever.

## How it gets an audit

- **Production path:** POST a ticker to Aritiq's real `/audit-ticker` endpoint and
  consume the JSON. Run with `--http http://localhost:8000` (add `--api-key ...` if
  the server sets `ARITIQ_API_KEYS`). This is the "Aritiq is infrastructure another
  agent calls over the wire" story.
- **Offline path (default):** the same audit result is reconstructed from cached SEC
  XBRL facts through the **same unmodified verifier**, serialized into the **same
  shape** the endpoint returns. So the demo is fully reproducible with no network and
  no model key, and the agent code is byte-for-byte identical on both paths.

## Run it

```bash
python benchmark/demo/trust_layer_demo.py                 # AAPL PLTR BAC, offline
python benchmark/demo/trust_layer_demo.py AAPL MSFT       # pick tickers
python benchmark/demo/trust_layer_demo.py --http http://localhost:8000
```

## What the transcript shows (see `TRANSCRIPT.txt`)

Three real filers, chosen to exercise every branch of the gate:

- **AAPL** — all `VERIFIED`. The agent states EPS ($7.49 basic / $7.46 diluted) and
  confirms the cash tie-out, each because Aritiq verified the filing's own
  reconciliation.
- **PLTR** — EPS `VERIFIED` (agent answers), but cash tie-out
  `INSUFFICIENT_EVIDENCE` (restricted cash) → the agent **refuses to claim the cash
  ties out**, and explains *why it's a needs-review, not a discrepancy*.
- **BAC** — EPS reconciliation `WRONG_MATH` in the cached data → the agent **will not
  state BAC's EPS as fact** and routes it to human review.

The one-line summary: the agent asserted a number **only** when Aritiq verified it,
and the refusals are the product.

## Test

`tests/test_trust_layer_demo.py` runs the gate against fixture audit responses (no
network) and asserts the refuse-on-`WRONG_MATH` and hedge-on-`INSUFFICIENT_EVIDENCE`
behavior actually fires — so the gate is verified by code, not just by a nice-looking
manual run.
