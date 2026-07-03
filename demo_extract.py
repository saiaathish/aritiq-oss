"""
Aritiq full-pipeline demo — the whole flow on one document.

By default this runs OFFLINE: it replays a saved model extraction (no API key
needed) so anyone can see source -> extract -> verify -> score end to end, with
every claim's operands and recomputation laid out for inspection.

    python demo_extract.py            # offline replay (default)
    python demo_extract.py --live     # call your configured model (needs a key)

With --live, Aritiq uses your BYOK settings from .env (ARITIQ_PROVIDER plus the
matching *_API_KEY). See .env.example.

The point to notice: the extractor faithfully reports a claim whose math is
wrong ("a 30% increase" when the real change is 25%), and the deterministic
verifier — not a model — is what catches it.
"""
import argparse
import json
import os

from aritiq import config
from aritiq.pipeline import audit

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = json.load(open(os.path.join(HERE, "benchmark", "gold_set.json")))
DOC = next(d for d in GOLD["documents"] if d["id"] == "A")

STATUS_ICONS = {
    "VERIFIED": "✅", "WRONG_MATH": "❌", "UNSUPPORTED_NUMBER": "⚠️ ",
    "AMBIGUOUS": "🔷", "UNCHECKED": "—",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use a real model (needs API key)")
    args = ap.parse_args()

    if args.live:
        config.load()
        complete_fn = None
        mode = "LIVE"
    else:
        raw = json.load(open(os.path.join(HERE, "benchmark", "runs", "A.json")))["raw"]
        complete_fn = lambda s, u: raw
        mode = "OFFLINE replay"

    print("=" * 72)
    print(f"  ARITIQ — full pipeline demo  ({mode})")
    print(f"  Document: {DOC['name']}")
    print("=" * 72)
    print("\n  SOURCE DOCUMENT:")
    print("    " + DOC["source"].replace("\n", "\n    "))
    print("\n  AI SUMMARY (audited):")
    print("    " + DOC["summary"].replace("\n", "\n    "))

    result = audit(DOC["source"], DOC["summary"], complete_fn=complete_fn)

    print("\n  PER-CLAIM TRACE (every verdict is inspectable):")
    for i, r in enumerate(result.results, 1):
        icon = STATUS_ICONS.get(r.status.value, "?")
        c = r.claim
        operands = ", ".join(
            f"{o.value:g}[{o.source.value[:4]}]" for o in c.operands
        ) or "—"
        print(f"\n    [{i:02d}] {icon} {r.status.value}")
        print(f"         claim     : {c.claim_text}")
        print(f"         operation : {c.operation.value}({operands})")
        if r.recomputed_value is not None:
            print(f"         stated {c.stated_value} vs recomputed {r.recomputed_value:.4f}  (Δ={r.delta:+.4f})")
        print(f"         verdict   : {r.explanation}")

    s = result.score
    print("\n" + "=" * 72)
    print(f"  ARITIQ SCORE: {s.score}/100   "
          f"(✅{s.verified}  ❌{s.wrong_math}  ⚠️{s.unsupported}  🔷{s.ambiguous}  —{s.unchecked})")
    if result.issues:
        print(f"  Extraction issues (schema-rejected): {len(result.issues)}")
    print(f"  Extraction by: {result.provider}/{result.model}")
    print("  Reminder: the score comes from code recomputing the math, not a model's opinion.")
    print("=" * 72)


if __name__ == "__main__":
    main()
