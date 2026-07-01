"""
Aritiq as a TRUST LAYER — what it looks like for a downstream AI agent to treat
Aritiq as a correctness gate before it states a financial fact.

THE PATTERN (System 4 from the reviewer feedback)
--------------------------------------------------
Most "AI + finance" products let a language model read a filing and then *say a
number*. The number is often plausible and sometimes wrong, and nothing in the
pipeline knows the difference. Aritiq inverts that: a claim is only usable once the
DETERMINISTIC verifier has ruled on it. This script simulates the consumer side of
that contract — a tiny "agent" that answers a question about a company but is
ALLOWED to assert only what Aritiq marked VERIFIED, and must refuse or hedge when
the relevant claim is INSUFFICIENT_EVIDENCE (Aritiq declined to convict) or
WRONG_MATH (Aritiq found a real disagreement).

The "agent" here is deliberately dumb — string templating over the audit result,
no second LLM call. The point is the TRUST GATE, not a chatbot: the gate is what
turns "the model said $7.49" into "$7.49, and Aritiq verified the filing's own EPS
reconciliation."

HOW IT GETS AN AUDIT
--------------------
Primary path (production): POST the ticker to Aritiq's `/audit-ticker` endpoint and
consume the JSON. Run with `--http http://localhost:8000` (and `--api-key` if the
server sets ARITIQ_API_KEYS).

Offline path (default here): the same audit result is reconstructed from cached SEC
XBRL facts through the SAME unmodified verifier, serialized into the SAME shape the
endpoint returns — so this demo is fully reproducible with no network and no model
key, and the agent logic is byte-for-byte identical to the live path.

Run:
    python benchmark/demo/trust_layer_demo.py                       # offline, cached
    python benchmark/demo/trust_layer_demo.py --http http://localhost:8000
    python benchmark/demo/trust_layer_demo.py AAPL PLTR BAC         # pick tickers
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "benchmark", "reliability"))

# Verdict semantics — the whole contract lives in these three words.
VERIFIED = "VERIFIED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
WRONG_MATH = "WRONG_MATH"


# ===========================================================================
# 1. Getting an audit result (HTTP endpoint, or offline cached — same shape)
# ===========================================================================

def fetch_audit_via_http(ticker: str, base_url: str,
                         api_key: Optional[str] = None, timeout: float = 120.0) -> dict:
    """Call Aritiq's real /audit-ticker endpoint and return the JSON payload.

    This is the production path: Aritiq is infrastructure the agent calls over the
    wire. Requires the backend running and (for live extraction) a model key on the
    server. Kept import-local so the offline demo has no httpx dependency.
    """
    import httpx  # local import: only needed on the HTTP path
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key
    r = httpx.post(f"{base_url.rstrip('/')}/audit-ticker",
                   json={"ticker": ticker}, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def build_cached_audit(ticker: str) -> dict:
    """Reconstruct an /audit-ticker-shaped result offline from cached XBRL facts.

    Uses the SAME build_claims_from_facts + verify_claim path the reliability
    benchmark uses, then serializes to the SAME dict shape backend/app.py's
    /audit-ticker returns — so the agent code below cannot tell the two apart.
    """
    from xbrl_verify import build_claims_from_facts     # benchmark/reliability
    from aritiq.edgar.xbrl import extract_xbrl_facts
    from aritiq.core.verify import verify_claim

    f = extract_xbrl_facts(ticker, use_cache=True)
    results = []
    if not f.fetch_error:
        for c in build_claims_from_facts(f):
            r = verify_claim(c)
            results.append({
                "status": r.status.value,
                "explanation": r.explanation,
                "claim": {
                    "claim_text": c.claim_text,
                    "operation": c.operation.value,
                    "stated_value": c.stated_value,
                    "unit": c.unit,
                    "operands": [
                        {"value": o.value, "category": o.category,
                         "source_text": o.source_text}
                        for o in c.operands
                    ],
                },
            })
    return {
        "filing": {"ticker": ticker.upper(), "company": f.company,
                   "period": f.period_end, "source": "cached XBRL (offline)"},
        "results": results,
    }


# ===========================================================================
# 2. The trust gate — the actual pattern being demonstrated
# ===========================================================================

def select_relevant(audit: dict, keywords: List[str]) -> List[dict]:
    """Return the audit results whose claim text matches any keyword (the claims
    an agent would consult to answer a question about `keywords`)."""
    kws = [k.lower() for k in keywords]
    out = []
    for r in audit.get("results", []):
        text = (r.get("claim", {}).get("claim_text") or "").lower()
        if any(k in text for k in kws):
            out.append(r)
    return out


def _eps_value(result: dict) -> Optional[str]:
    """Pull the per-share EPS figure from an eps_reconciliation claim's operands.

    The reconciliation's first operand is the stated EPS (category 'basic'/
    'diluted'); we surface it so the agent can quote a real number, not a guess.
    """
    ops = result.get("claim", {}).get("operands", [])
    if not ops:
        return None
    first = ops[0]
    cat = first.get("category") or ""
    val = first.get("value")
    if val is None:
        return None
    return f"${val:.2f} ({cat})" if cat else f"${val:.2f}"


def answer_eps_question(audit: dict) -> Dict[str, str]:
    """The agent's answer to: 'What was this company's EPS and is it trustworthy?'

    Trust gate:
      * a relevant WRONG_MATH  -> REFUSE (the filing's own EPS does not reconcile)
      * else any VERIFIED       -> ANSWER, quoting the verified figure(s)
      * else only INSUFFICIENT   -> LOW CONFIDENCE / DECLINE (Aritiq couldn't confirm)
      * else nothing relevant    -> NO BASIS

    Returns {decision, answer} where decision is one of
    ANSWER / DECLINE_DISPUTED / DECLINE_UNVERIFIED / NO_BASIS.
    """
    company = audit.get("filing", {}).get("company") or audit.get("filing", {}).get("ticker", "")
    relevant = select_relevant(audit, ["eps", "earnings per share"])

    if not relevant:
        return {"decision": "NO_BASIS",
                "answer": f"I don't have a verified EPS claim for {company}, so I won't state one."}

    disputed = [r for r in relevant if r["status"] == WRONG_MATH]
    verified = [r for r in relevant if r["status"] == VERIFIED]
    gated = [r for r in relevant if r["status"] == INSUFFICIENT]

    if disputed:
        # A conviction on the EPS reconciliation: refuse to assert the number.
        why = disputed[0].get("explanation", "").strip()
        return {"decision": "DECLINE_DISPUTED",
                "answer": (f"I will NOT state {company}'s EPS as fact: Aritiq flagged the "
                           f"filing's EPS reconciliation as WRONG_MATH — the stated EPS does "
                           f"not reconcile to net income / shares within tolerance. A human "
                           f"should review before this number is used. ({why[:120]})")}

    if verified:
        figs = [v for v in (_eps_value(r) for r in verified) if v]
        fig_str = " and ".join(dict.fromkeys(figs)) if figs else "the reported figure"
        caveat = ""
        if gated:
            caveat = (" (Note: a related cash-flow/other check for this filing was gated "
                      "INSUFFICIENT_EVIDENCE, so I'm limiting my answer to EPS only.)")
        return {"decision": "ANSWER",
                "answer": (f"{company}'s EPS was {fig_str}. I can state this with confidence "
                           f"because Aritiq VERIFIED that the filing's own EPS reconciles to "
                           f"net income divided by weighted shares.{caveat}")}

    if gated:
        why = gated[0].get("explanation", "").strip()
        return {"decision": "DECLINE_UNVERIFIED",
                "answer": (f"I can't confirm {company}'s EPS with confidence. Aritiq returned "
                           f"INSUFFICIENT_EVIDENCE — it declined to certify the figure rather "
                           f"than guess (e.g. continuing-operations vs total basis unresolved). "
                           f"I'd flag this as unverified. ({why[:120]})")}

    return {"decision": "NO_BASIS",
            "answer": f"No usable verified EPS claim for {company}."}


def answer_cash_question(audit: dict) -> Dict[str, str]:
    """The agent's answer to: 'Does this company's cash position tie out cleanly?'

    Same trust gate, exercised on the cash_flow_tie_out claim — which for filers
    with restricted cash is deliberately gated INSUFFICIENT_EVIDENCE, so this is
    where an honest agent must SAY it can't confirm rather than assert a clean
    tie-out.
    """
    company = audit.get("filing", {}).get("company") or audit.get("filing", {}).get("ticker", "")
    relevant = select_relevant(audit, ["cash tie", "cash flow", "cash tie-out"])
    if not relevant:
        return {"decision": "NO_BASIS",
                "answer": f"I have no cash-tie-out claim for {company} to rely on."}

    disputed = [r for r in relevant if r["status"] == WRONG_MATH]
    verified = [r for r in relevant if r["status"] == VERIFIED]
    gated = [r for r in relevant if r["status"] == INSUFFICIENT]

    if disputed:
        return {"decision": "DECLINE_DISPUTED",
                "answer": (f"I will NOT claim {company}'s cash ties out: Aritiq marked the "
                           f"cash tie-out WRONG_MATH. Needs human review.")}
    if verified and not gated:
        return {"decision": "ANSWER",
                "answer": (f"Yes — {company}'s ending cash on the cash-flow statement ties to "
                           f"the balance-sheet cash line; Aritiq VERIFIED it.")}
    if gated:
        why = gated[0].get("explanation", "").strip()
        return {"decision": "DECLINE_UNVERIFIED",
                "answer": (f"I can't confirm {company}'s cash ties out cleanly. Aritiq returned "
                           f"INSUFFICIENT_EVIDENCE — typically the cash-flow line includes "
                           f"restricted cash while the balance-sheet line doesn't, so the two "
                           f"aren't expected to be equal and Aritiq declines to certify a "
                           f"tie-out rather than assert a false one. I'd flag this as "
                           f"needs-review, not a discrepancy. ({why[:100]})")}
    return {"decision": "NO_BASIS", "answer": f"No usable cash claim for {company}."}


# ===========================================================================
# 3. Transcript
# ===========================================================================

QUESTIONS = [
    ("What was this company's EPS and is it trustworthy?", answer_eps_question),
    ("Does this company's cash position tie out cleanly?", answer_cash_question),
]


def run_ticker(ticker: str, *, http: Optional[str] = None,
               api_key: Optional[str] = None) -> Dict:
    audit = (fetch_audit_via_http(ticker, http, api_key) if http
             else build_cached_audit(ticker))
    verdicts: Dict[str, int] = {}
    for r in audit.get("results", []):
        verdicts[r["status"]] = verdicts.get(r["status"], 0) + 1
    answers = [{"question": q, **fn(audit)} for q, fn in QUESTIONS]
    return {
        "ticker": ticker.upper(),
        "verdict_summary": " ".join(f"{k}={v}" for k, v in sorted(verdicts.items())) or "(no claims)",
        "answers": answers,
    }


def main():
    ap = argparse.ArgumentParser(description="Aritiq trust-layer agent demo")
    ap.add_argument("tickers", nargs="*", default=["AAPL", "PLTR", "BAC"],
                    help="tickers to query (default: AAPL PLTR BAC)")
    ap.add_argument("--http", default=None,
                    help="Aritiq backend base URL (e.g. http://localhost:8000); "
                         "omit to run offline from cached XBRL")
    ap.add_argument("--api-key", default=None, help="API key if the backend requires one")
    args = ap.parse_args()
    tickers = args.tickers or ["AAPL", "PLTR", "BAC"]

    def wrap(text: str, lead: str = "      agent> ", cont: str = "             ") -> None:
        line = lead
        for w in text.split():
            if len(line) + len(w) + 1 > 92:
                print(line); line = cont + w
            else:
                line += (" " if line.strip() else "") + w
        print(line)

    print("=" * 74)
    print("  ARITIQ TRUST-LAYER DEMO — an agent that may only assert what's VERIFIED")
    print(f"  source: {'HTTP ' + args.http if args.http else 'offline cached XBRL'}")
    print("=" * 74)
    for tk in tickers:
        res = run_ticker(tk, http=args.http, api_key=args.api_key)
        print(f"\n  ▶ {res['ticker']}   [Aritiq verdicts: {res['verdict_summary']}]")
        for a in res["answers"]:
            print(f"    Q: {a['question']}")
            print(f"       decision: {a['decision']}")
            wrap(a["answer"])
    print("\n" + "=" * 74)
    print("  The agent stated a number ONLY when Aritiq VERIFIED it; it declined on")
    print("  WRONG_MATH (disputed) and INSUFFICIENT_EVIDENCE (unverified). That refusal")
    print("  is the product: Aritiq is the correctness gate in front of the agent.")
    print("=" * 74)


if __name__ == "__main__":
    main()
