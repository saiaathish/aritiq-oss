"""Offline tests for AI Analyst Mode (aritiq/analyst.py) — fake models only.

Pins the three-layer boundary:
1. only VERIFIED claims become facts; blocked values are digit-stripped,
2. the refusal gate fires BEFORE any model call (proven with a model stub
   that raises if invoked) — including THE adversarial case: the only
   relevant number is bad,
3. the post-model whitelist rejects any number the facts don't contain, so a
   fluent hallucination cannot reach the caller.
"""
import pytest

from aritiq.analyst import (
    AnalystAnswer,
    FactLedger,
    ask_analyst,
    ledger_from_records,
    ledger_from_results,
    relevant_items,
    validate_answer,
)
from aritiq.core.schema import (
    Claim,
    Operand,
    Operation,
    VerificationResult,
    VerificationStatus,
)


def _result(status, *, rule="balance_sheet_identity", text=None,
            stated=100.0, operands=(60.0, 40.0), explanation="explained: 60 + 40"):
    claim = Claim(
        claim_text=text or f"{rule} claim",
        operation=Operation.INTERNAL_CONSISTENCY,
        stated_value=stated,
        operands=[Operand(value=v) for v in operands],
        unit="$M",
        rule_name=rule,
    )
    return VerificationResult(claim=claim, status=status,
                              recomputed_value=stated, explanation=explanation)


def _never_call(system_prompt, user_prompt):  # a model stub that must NOT run
    raise AssertionError("model was called — the refusal gate failed")


# ---------------------------------------------------------------------------
# Layer 1 — the ledger
# ---------------------------------------------------------------------------

def test_ledger_only_verified_become_facts():
    results = [
        _result(VerificationStatus.VERIFIED),
        _result(VerificationStatus.WRONG_MATH, rule="eps_reconciliation"),
        _result(VerificationStatus.INSUFFICIENT_EVIDENCE, rule="cash_flow_tie_out"),
    ]
    ledger = ledger_from_results(results)
    assert len(ledger.facts) == 1
    assert ledger.facts[0].topic == "balance_sheet_identity"
    assert {b.status for b in ledger.blocked} == {"WRONG_MATH", "INSUFFICIENT_EVIDENCE"}


def test_blocked_reasons_are_digit_stripped():
    r = _result(VerificationStatus.WRONG_MATH,
                explanation="stated 4.99 but recomputed 3.9143 from 4341/1109")
    ledger = ledger_from_results([r])
    assert not any(ch.isdigit() for ch in ledger.blocked[0].reason)
    assert "[number withheld]" in ledger.blocked[0].reason


def test_ledger_from_records_shape():
    records = [
        {"rule_name": "balance_sheet_identity", "verdict": "VERIFIED",
         "operand_values": [100.0, 60.0, 40.0], "explanation": "ok"},
        {"rule_name": "cash_flow_tie_out", "verdict": "INSUFFICIENT_EVIDENCE",
         "operand_values": [10.0, 11.0], "explanation": "restricted cash 1.1B"},
    ]
    ledger = ledger_from_records(records)
    assert len(ledger.facts) == 1 and len(ledger.blocked) == 1
    assert ledger.facts[0].values == [100.0, 60.0, 40.0]
    assert not any(ch.isdigit() for ch in ledger.blocked[0].reason)


# ---------------------------------------------------------------------------
# Layer 2 — the pre-model refusal gate
# ---------------------------------------------------------------------------

def test_ADVERSARIAL_only_relevant_number_is_bad_refuses_without_model():
    """THE adversarial case from the roadmap: the only claim relevant to the
    question is WRONG_MATH. The analyst must decline — and must do so without
    ever invoking the model (the stub raises if called)."""
    results = [
        _result(VerificationStatus.WRONG_MATH, rule="eps_reconciliation",
                explanation="stated 7.49 but recomputed 0.0075"),
        # an unrelated verified fact exists, so the ledger is not empty:
        _result(VerificationStatus.VERIFIED, rule="balance_sheet_identity"),
    ]
    ledger = ledger_from_results(results)
    out = ask_analyst("Why did diluted EPS look so strong?", ledger,
                      complete_fn=_never_call)
    assert out.mode == "refused_blocked"
    assert out.model_called is False
    assert out.answer is None
    assert "WRONG_MATH" in out.guard
    # and the refusal metadata carries status + topic, never a number
    assert out.blocking == [{"topic": "eps_reconciliation", "status": "WRONG_MATH"}]


def test_refuses_on_insufficient_evidence_naming_the_status():
    results = [_result(VerificationStatus.INSUFFICIENT_EVIDENCE,
                       rule="cash_flow_tie_out",
                       explanation="restricted cash scope difference 1.1B")]
    ledger = ledger_from_results(results)
    out = ask_analyst("Does the cash flow tie out?", ledger,
                      complete_fn=_never_call)
    assert out.mode == "refused_blocked"
    assert "INSUFFICIENT_EVIDENCE" in out.guard
    assert out.model_called is False


def test_topic_precision_adjacent_verified_fact_is_not_license():
    """REGRESSION for the hole the at-scale measurement caught: a verified
    balance-sheet fact must NOT let the analyst answer a CASH question whose
    actual subject (cash_flow_tie_out) is blocked — even though the question's
    wording ('...to balance sheet cash') also matches the verified topic."""
    results = [
        _result(VerificationStatus.VERIFIED, rule="balance_sheet_identity"),
        _result(VerificationStatus.INSUFFICIENT_EVIDENCE, rule="cash_flow_tie_out",
                explanation="restricted cash scope difference"),
    ]
    ledger = ledger_from_results(results)
    out = ask_analyst("Does the cash flow statement tie out to balance sheet cash?",
                      ledger, complete_fn=_never_call)
    assert out.mode == "refused_blocked"
    assert out.model_called is False
    assert out.blocking == [{"topic": "cash_flow_tie_out",
                             "status": "INSUFFICIENT_EVIDENCE"}]
    assert "adjacent topic" in out.guard


def test_topic_coverage_uncovered_subject_refuses_despite_adjacent_facts():
    """Companion regression (also surfaced by the at-scale measurement): when
    the question's subject has NO claims at all, a verified fact on an
    adjacent topic must not produce a fluent non-answer."""
    ledger = ledger_from_results([
        _result(VerificationStatus.VERIFIED, rule="balance_sheet_identity"),
        # note: no cash_flow_tie_out claim of any status exists
    ])
    out = ask_analyst("Does the cash flow statement tie out to balance sheet cash?",
                      ledger, complete_fn=_never_call)
    assert out.mode == "refused_no_data"
    assert out.model_called is False
    assert "cash_flow_tie_out" in out.guard


def test_refuses_no_data_when_nothing_relevant():
    ledger = ledger_from_results([_result(VerificationStatus.VERIFIED)])
    out = ask_analyst("What was the dividend payout ratio?", ledger,
                      complete_fn=_never_call)
    assert out.mode == "refused_no_data"
    assert out.model_called is False


def test_blocked_numbers_never_reach_the_prompt():
    """Mixed case: a verified balance-sheet fact AND a blocked balance-sheet
    claim are both relevant. The model runs — but the blocked claim's number
    must not appear anywhere in the prompt it receives."""
    results = [
        _result(VerificationStatus.VERIFIED, stated=500.0, operands=(300.0, 200.0),
                explanation="within tolerance"),
        _result(VerificationStatus.WRONG_MATH, stated=77777.0,
                operands=(66666.0, 11111.0),
                explanation="stated 77777 but recomputed 77778 from 66666+11111"),
    ]
    ledger = ledger_from_results(results)
    seen = {}

    def capture(system_prompt, user_prompt):
        seen["prompt"] = system_prompt + "\n" + user_prompt
        return '[{"answer": "Assets of 500 [F1] equal 300 plus 200 [F1].", "citations": ["F1"]}]'

    out = ask_analyst("Does the balance sheet balance?", ledger, complete_fn=capture)
    assert out.mode == "answered"
    for leaked in ("77777", "66666", "11111"):
        assert leaked not in seen["prompt"]
    assert "WRONG_MATH" in seen["prompt"]  # status is disclosed, value is not


# ---------------------------------------------------------------------------
# Layer 3 — the post-model whitelist
# ---------------------------------------------------------------------------

def _bs_ledger():
    return ledger_from_results([
        _result(VerificationStatus.VERIFIED, stated=500.0, operands=(300.0, 200.0)),
    ])


def test_answers_with_valid_citations_and_numbers():
    def model(sp, up):
        return '[{"answer": "Total assets of $500 [F1] equal liabilities of 300 plus equity of 200 [F1].", "citations": ["F1"]}]'
    out = ask_analyst("Does the balance sheet balance?", _bs_ledger(),
                      complete_fn=model)
    assert out.mode == "answered"
    assert out.citations == ["F1"]
    assert out.model_called is True
    assert out.facts_used[0]["fact_id"] == "F1"


def test_hallucinated_number_is_rejected():
    def lying_model(sp, up):
        return '[{"answer": "Assets were $999 [F1], a record.", "citations": ["F1"]}]'
    out = ask_analyst("Does the balance sheet balance?", _bs_ledger(),
                      complete_fn=lying_model)
    assert out.mode == "rejected_unverified_output"
    assert out.answer is None                       # the fluent lie is withheld
    assert "999" in out.guard and "hallucination guard" in out.guard


def test_invented_citation_is_rejected():
    def model(sp, up):
        return '[{"answer": "Assets were 500 [F9].", "citations": ["F9"]}]'
    out = ask_analyst("Does the balance sheet balance?", _bs_ledger(),
                      complete_fn=model)
    assert out.mode == "rejected_unverified_output"


def test_uncited_answer_is_rejected():
    def model(sp, up):
        return '[{"answer": "Everything is fine.", "citations": []}]'
    out = ask_analyst("Does the balance sheet balance?", _bs_ledger(),
                      complete_fn=model)
    assert out.mode == "rejected_unverified_output"


def test_unparseable_model_output_is_rejected_not_passed_through():
    def model(sp, up):
        return "Sure! The balance sheet looks great, assets were about 510."
    out = ask_analyst("Does the balance sheet balance?", _bs_ledger(),
                      complete_fn=model)
    assert out.mode == "rejected_unverified_output"
    assert out.answer is None


def test_code_fenced_json_is_tolerated():
    def model(sp, up):
        return '```json\n[{"answer": "Assets 500 [F1].", "citations": ["F1"]}]\n```'
    out = ask_analyst("Does the balance sheet balance?", _bs_ledger(),
                      complete_fn=model)
    assert out.mode == "answered"


def test_whitelist_allows_rounding_and_prose_counters():
    facts = ledger_from_results([
        _result(VerificationStatus.VERIFIED, rule="eps_reconciliation",
                stated=7.493, operands=(112010.0, 14948.5)),
    ]).facts
    # rounded restatement of a fact value passes; prose counter passes
    assert validate_answer("EPS was 7.49 [F1], one of 2 checks.", ["F1"], facts) is None
    # a number nowhere near any fact fails
    assert validate_answer("EPS was 9.12 [F1].", ["F1"], facts) is not None


def test_relevance_matching_is_topic_based():
    ledger = ledger_from_results([
        _result(VerificationStatus.VERIFIED, rule="eps_reconciliation"),
        _result(VerificationStatus.VERIFIED, rule="cash_flow_tie_out"),
    ])
    facts, _ = relevant_items("What was basic EPS?", ledger)
    assert [f.topic for f in facts] == ["eps_reconciliation"]
