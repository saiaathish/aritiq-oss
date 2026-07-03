"""Prompt contract checks for cross-statement extraction."""

from aritiq.extract.cross_statement import CROSS_STATEMENT_SYSTEM_PROMPT


def test_cash_tie_out_prompt_requires_restricted_cash_disclosure_context():
    prompt = CROSS_STATEMENT_SYSTEM_PROMPT.lower()

    assert "restricted cash" in prompt
    assert "source_text" in prompt
    assert "notes" in prompt
    assert "false wrong_math" in prompt
