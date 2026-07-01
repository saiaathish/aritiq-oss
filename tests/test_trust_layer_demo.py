"""
Tests for the trust-layer agent demo (benchmark/demo/trust_layer_demo.py).

The POINT of the demo is the trust GATE: an agent may assert only what Aritiq
marked VERIFIED, and must refuse on WRONG_MATH and hedge on INSUFFICIENT_EVIDENCE.
These tests drive the gate with hand-built fixture audit responses (the exact shape
/audit-ticker returns) so the refusal behavior is confirmed by code — NO live
network, NO SEC fetch, NO model call.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "benchmark", "demo"))

import trust_layer_demo as demo  # noqa: E402

_XBRL_CACHE = os.path.join(_REPO, "benchmark", "reliability", "cache", "xbrl")


def _require_raw_cache(*tickers):
    """Skip (don't fail) when the large, gitignored raw companyfacts cache for a
    ticker isn't present — e.g. on a fresh clone before the harness regenerates it.
    See benchmark/reliability/cache/README.md for regeneration."""
    missing = [t for t in tickers
               if not os.path.exists(os.path.join(_XBRL_CACHE, f"_raw_{t}.json"))]
    if missing:
        pytest.skip(f"raw XBRL cache absent for {missing} (re-fetchable; see cache/README.md)")


def _audit(company, results):
    return {"filing": {"ticker": company[:4].upper(), "company": company},
            "results": results}


def _eps_claim(status, eps=7.49, variant="basic", explanation=""):
    return {
        "status": status,
        "explanation": explanation,
        "claim": {
            "claim_text": f"[XBRL] {variant} EPS reconciliation",
            "operation": "internal_consistency",
            "stated_value": None, "unit": None,
            "operands": [
                {"value": eps, "category": variant, "source_text": "XBRL EPS"},
                {"value": 1.0e11, "category": "total", "source_text": "XBRL NetIncomeLoss"},
                {"value": 1.5e10, "category": variant, "source_text": "XBRL shares"},
            ],
        },
    }


def _cash_claim(status, explanation=""):
    return {
        "status": status, "explanation": explanation,
        "claim": {"claim_text": "[XBRL] cash tie-out",
                  "operation": "internal_consistency", "stated_value": None,
                  "unit": "$", "operands": [
                      {"value": 100.0, "category": "statement_ending_cash", "source_text": "CF cash"},
                      {"value": 100.0, "category": "balance_sheet_cash", "source_text": "BS cash"}]},
    }


# ---- EPS gate: the core refuse/answer contract ----------------------------

def test_verified_eps_is_answered_with_the_figure():
    audit = _audit("Verified Co", [_eps_claim("VERIFIED", eps=7.49)])
    out = demo.answer_eps_question(audit)
    assert out["decision"] == "ANSWER"
    assert "7.49" in out["answer"]
    assert "VERIFIED" in out["answer"]


def test_wrong_math_eps_is_refused_not_stated():
    """The critical safety property: a WRONG_MATH EPS must NEVER be asserted."""
    audit = _audit("Disputed Co",
                   [_eps_claim("WRONG_MATH", eps=9.99, explanation="exceeds tolerance")])
    out = demo.answer_eps_question(audit)
    assert out["decision"] == "DECLINE_DISPUTED"
    # the disputed number must not be presented as the answer
    assert "9.99" not in out["answer"]
    assert "WRONG_MATH" in out["answer"]
    assert "NOT" in out["answer"] or "will not" in out["answer"].lower()


def test_insufficient_evidence_eps_is_hedged_not_asserted():
    audit = _audit("Unresolved Co",
                   [_eps_claim("INSUFFICIENT_EVIDENCE", eps=3.33,
                               explanation="continuing-ops vs total basis unresolved")])
    out = demo.answer_eps_question(audit)
    assert out["decision"] == "DECLINE_UNVERIFIED"
    assert "3.33" not in out["answer"]
    assert "INSUFFICIENT_EVIDENCE" in out["answer"]


def test_wrong_math_wins_over_a_coexisting_verified_claim():
    """If ANY relevant EPS claim is WRONG_MATH, the agent must refuse — a verified
    sibling claim does not license asserting past a live conviction."""
    audit = _audit("Mixed Co", [
        _eps_claim("VERIFIED", eps=7.49, variant="basic"),
        _eps_claim("WRONG_MATH", eps=8.88, variant="diluted", explanation="exceeds tolerance"),
    ])
    out = demo.answer_eps_question(audit)
    assert out["decision"] == "DECLINE_DISPUTED"


def test_no_eps_claim_yields_no_basis():
    audit = _audit("Silent Co", [_cash_claim("VERIFIED")])
    out = demo.answer_eps_question(audit)
    assert out["decision"] == "NO_BASIS"


# ---- cash gate: INSUFFICIENT_EVIDENCE refusal on the real gated rule -------

def test_cash_insufficient_evidence_is_declined():
    audit = _audit("Restricted Co",
                   [_cash_claim("INSUFFICIENT_EVIDENCE",
                                explanation="restricted-cash disclosure detected")])
    out = demo.answer_cash_question(audit)
    assert out["decision"] == "DECLINE_UNVERIFIED"
    assert "INSUFFICIENT_EVIDENCE" in out["answer"]


def test_cash_verified_is_answered():
    audit = _audit("Clean Co", [_cash_claim("VERIFIED")])
    out = demo.answer_cash_question(audit)
    assert out["decision"] == "ANSWER"


# ---- select_relevant keyword routing --------------------------------------

def test_select_relevant_matches_on_claim_text():
    audit = _audit("Co", [_eps_claim("VERIFIED"), _cash_claim("VERIFIED")])
    eps = demo.select_relevant(audit, ["eps"])
    cash = demo.select_relevant(audit, ["cash tie"])
    assert len(eps) == 1 and "EPS" in eps[0]["claim"]["claim_text"]
    assert len(cash) == 1 and "cash" in cash[0]["claim"]["claim_text"].lower()


# ---- offline end-to-end (cached, no network) ------------------------------

def test_run_ticker_offline_cached_smoke():
    """The offline path must produce a decision for each question without network."""
    _require_raw_cache("AAPL")
    res = demo.run_ticker("AAPL", http=None)
    assert res["ticker"] == "AAPL"
    assert len(res["answers"]) == 2
    for a in res["answers"]:
        assert a["decision"] in {"ANSWER", "DECLINE_DISPUTED", "DECLINE_UNVERIFIED", "NO_BASIS"}


def test_run_ticker_bac_refuses_disputed_eps_offline():
    """BAC's cached EPS reconciliation is WRONG_MATH — the agent must refuse."""
    _require_raw_cache("BAC")
    res = demo.run_ticker("BAC", http=None)
    eps_answer = next(a for a in res["answers"] if "EPS" in a["question"])
    assert eps_answer["decision"] == "DECLINE_DISPUTED"
