"""Extraction support for multi-document provenance graph fields."""

from aritiq.extract import parse_claims
from aritiq.extract.prompt import SYSTEM_PROMPT


def test_parse_claims_preserves_node_id_and_depends_on():
    raw = """[
      {"claim_text":"Revenue was $100M","operation":"identity","stated_value":100,
       "operands":[{"value":100,"source":"grounded"}],
       "node_id":"revenue"},
      {"claim_text":"Gross margin was 40%","operation":"margin_percent","stated_value":40,
       "operands":[{"value":40,"source":"grounded"},{"value":100,"source":"grounded"}],
       "node_id":"gross_margin","depends_on":["revenue"]}
    ]"""

    claims, issues = parse_claims(raw)

    assert not issues
    assert claims[0].node_id == "revenue"
    assert claims[0].depends_on == []
    assert claims[1].node_id == "gross_margin"
    assert claims[1].depends_on == ["revenue"]


def test_prompt_mentions_graph_fields():
    prompt = SYSTEM_PROMPT.lower()

    assert "node_id" in prompt
    assert "depends_on" in prompt
    assert "provenance graph" in prompt
