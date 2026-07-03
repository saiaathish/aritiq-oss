"""
Tests for the extraction extraction stage.

None of these tests call an LLM or need an API key — every model response is
injected as a string through a fake complete_fn.  They exercise the three things
that keep the firewall honest:

  1. hard schema validation (malformed claims are rejected, not passed through),
  2. robust JSON parsing (fences/prose/garbage handled without crashing),
  3. correct conversion into the verifier's Claim dataclass,

plus a structural test that proves no verification code is importable from the
extraction package, and an end-to-end check that the benchmark harness actually
detects injected extraction errors.
"""
import ast
import importlib.util
import os

import pytest

from aritiq.core.schema import Operation, OperandSource, VerificationStatus
from aritiq.core.verify import verify_claim
from aritiq.extract import extract_claims, parse_claims
from aritiq.extract.schema import RawClaim, _coerce_number

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Number coercion
# ---------------------------------------------------------------------------

class TestCoerceNumber:
    def test_plain_number_untouched(self):
        assert _coerce_number(125) == 125
        assert _coerce_number(2.5) == 2.5

    def test_currency_and_commas(self):
        assert _coerce_number("$1,200") == 1200.0
        assert _coerce_number("$125.00") == 125.0

    def test_percent_sign(self):
        assert _coerce_number("25%") == 25.0

    def test_null_like_to_none(self):
        assert _coerce_number("n/a") is None
        assert _coerce_number("") is None

    def test_magnitude_suffix_NOT_expanded(self):
        # Critical: we must NOT silently scale "100M" to 1e8 — that could create
        # a hidden scale mismatch. It is returned unchanged so Pydantic rejects it.
        assert _coerce_number("100M") == "100M"
        assert _coerce_number("1.2bn") == "1.2bn"


# ---------------------------------------------------------------------------
# Hard schema validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_valid_claim_parses(self):
        claims, issues = parse_claims(
            '[{"claim_text":"x","operation":"percent_change","stated_value":30,'
            '"operands":[{"value":100,"source":"grounded"},{"value":125,"source":"grounded"}]}]'
        )
        assert len(claims) == 1 and not issues
        assert claims[0].operation == Operation.PERCENT_CHANGE

    def test_bad_operation_enum_rejected_others_survive(self):
        claims, issues = parse_claims(
            '[{"claim_text":"ok","operation":"sum","stated_value":3,'
            '"operands":[{"value":1,"source":"grounded"},{"value":2,"source":"grounded"}]},'
            '{"claim_text":"bad","operation":"growth","stated_value":1,"operands":[]}]'
        )
        assert len(claims) == 1          # the good one survives
        assert len(issues) == 1          # the bad one is flagged, not passed through
        assert issues[0].index == 1

    def test_bad_source_enum_rejected(self):
        claims, issues = parse_claims(
            '[{"claim_text":"x","operation":"identity","stated_value":1,'
            '"operands":[{"value":1,"source":"made_up"}]}]'
        )
        assert not claims and len(issues) == 1

    def test_missing_required_field_rejected(self):
        # no claim_text
        claims, issues = parse_claims('[{"operation":"identity","stated_value":1,"operands":[]}]')
        assert not claims and len(issues) == 1

    def test_dirty_number_in_value_coerced(self):
        claims, _ = parse_claims(
            '[{"claim_text":"x","operation":"identity","stated_value":"$1,200",'
            '"operands":[{"value":"$1,200","source":"grounded"}]}]'
        )
        assert claims[0].stated_value == 1200.0
        assert claims[0].operands[0].value == 1200.0

    def test_unparseable_value_rejected(self):
        claims, issues = parse_claims(
            '[{"claim_text":"x","operation":"identity","stated_value":1,'
            '"operands":[{"value":"100M","source":"grounded"}]}]'
        )
        assert not claims and len(issues) == 1


# ---------------------------------------------------------------------------
# Robust JSON extraction
# ---------------------------------------------------------------------------

class TestJsonExtraction:
    GOOD = ('[{"claim_text":"x","operation":"identity","stated_value":1,'
            '"operands":[{"value":1,"source":"grounded"}]}]')

    def test_plain_array(self):
        claims, issues = parse_claims(self.GOOD)
        assert len(claims) == 1 and not issues

    def test_code_fence(self):
        claims, _ = parse_claims("```json\n" + self.GOOD + "\n```")
        assert len(claims) == 1

    def test_leading_prose(self):
        claims, _ = parse_claims("Here are the claims:\n" + self.GOOD)
        assert len(claims) == 1

    def test_trailing_prose(self):
        claims, _ = parse_claims(self.GOOD + "\n\nHope that helps!")
        assert len(claims) == 1

    def test_no_array_is_issue_not_crash(self):
        claims, issues = parse_claims("I could not find any numeric claims.")
        assert not claims and len(issues) == 1

    def test_malformed_json_is_issue_not_crash(self):
        claims, issues = parse_claims('[{"claim_text": "x", oops}]')
        assert not claims and len(issues) == 1

    def test_empty_array(self):
        claims, issues = parse_claims("[]")
        assert claims == [] and issues == []

    def test_nested_brackets_in_strings(self):
        # a ']' inside a string value must not end the array early
        raw = ('[{"claim_text":"array [x] notation","operation":"identity",'
               '"stated_value":1,"operands":[{"value":1,"source":"grounded"}]}]')
        claims, issues = parse_claims(raw)
        assert len(claims) == 1 and not issues


# ---------------------------------------------------------------------------
# Conversion to the verifier's Claim dataclass
# ---------------------------------------------------------------------------

class TestConversion:
    def test_grounded_inferred_missing_mapped(self):
        claims, _ = parse_claims(
            '[{"claim_text":"x","operation":"percent_change","stated_value":20,'
            '"operands":[{"value":null,"source":"missing"},'
            '{"value":1200,"source":"inferred","source_text":"$1.2 billion"}]}]'
        )
        ops = claims[0].operands
        assert ops[0].source == OperandSource.MISSING
        assert ops[0].value == 0.0                      # placeholder for missing
        assert ops[1].source == OperandSource.INFERRED
        assert ops[1].value == 1200.0
        assert ops[1].source_text == "$1.2 billion"

    def test_source_span_becomes_tuple(self):
        claims, _ = parse_claims(
            '[{"claim_text":"x","operation":"identity","stated_value":1,'
            '"operands":[{"value":1,"source":"grounded","source_span":[3,8]}]}]'
        )
        assert claims[0].operands[0].source_span == (3, 8)

    def test_bad_span_rejected(self):
        claims, issues = parse_claims(
            '[{"claim_text":"x","operation":"identity","stated_value":1,'
            '"operands":[{"value":1,"source":"grounded","source_span":[3]}]}]'
        )
        assert not claims and len(issues) == 1


# ---------------------------------------------------------------------------
# End-to-end extractor (with a fake model) feeding the verifier
# ---------------------------------------------------------------------------

class TestExtractorEndToEnd:
    def test_extract_then_verify_motivating_example(self):
        source = "Revenue was $125M, up from $100M."
        summary = "Revenue rose from $100M to $125M, a 30% increase."
        fake = (
            '[{"claim_text":"Revenue rose from $100M to $125M, a 30% increase",'
            '"operation":"percent_change","stated_value":30,'
            '"operands":[{"value":100,"source":"grounded"},{"value":125,"source":"grounded"}],'
            '"unit":"%"}]'
        )
        out = extract_claims(source, summary, complete_fn=lambda s, u: fake)
        assert out.n_claims == 1
        # The extractor reports the (wrong) claim faithfully; the verifier catches it.
        r = verify_claim(out.claims[0])
        assert r.status == VerificationStatus.WRONG_MATH
        assert abs(r.recomputed_value - 25.0) < 1e-9

    def test_prompt_passed_to_completion(self):
        seen = {}

        def spy(system_prompt, user_prompt):
            seen["sys"] = system_prompt
            seen["user"] = user_prompt
            return "[]"

        extract_claims("SRC", "SUM", complete_fn=spy)
        assert "SRC" in seen["user"] and "SUM" in seen["user"]
        assert "operand" in seen["sys"].lower()      # the prompt describes operands
        assert "missing" in seen["sys"].lower()      # ... and the no-guess rule

    def test_bad_response_does_not_raise(self):
        out = extract_claims("s", "s", complete_fn=lambda s, u: "no json here")
        assert out.n_claims == 0 and out.n_issues == 1


# ---------------------------------------------------------------------------
# Firewall: no verification code is reachable from the extraction package
# ---------------------------------------------------------------------------

class TestFirewall:
    def _imports_in(self, path):
        tree = ast.parse(open(path).read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add(("." * (node.level or 0)) + (node.module or ""))
        return mods

    def test_extract_package_never_imports_verifier_or_scorer(self):
        extract_dir = os.path.join(REPO, "aritiq", "extract")
        offenders = {}
        for fn in os.listdir(extract_dir):
            if not fn.endswith(".py"):
                continue
            mods = self._imports_in(os.path.join(extract_dir, fn))
            bad = [m for m in mods if "verify" in m or m.endswith(".score") or m == "score"]
            if bad:
                offenders[fn] = bad
        assert not offenders, f"extraction must not import verification code: {offenders}"

    def test_verifier_never_imports_extraction_or_llm(self):
        # Check IMPORTS, not text: verify.py's docstring proudly says "NO LLM
        # CALLS", so a substring scan would false-positive on the reassurance.
        mods = self._imports_in(os.path.join(REPO, "aritiq", "core", "verify.py"))
        bad = [m for m in mods if any(t in m for t in ("extract", "anthropic", "openai", "prompt"))]
        assert not bad, f"verify.py must not import extraction/LLM code: {bad}"


# ---------------------------------------------------------------------------
# The benchmark harness genuinely detects injected extraction errors
# ---------------------------------------------------------------------------

def _load_harness():
    import sys
    path = os.path.join(REPO, "benchmark", "eval_extraction.py")
    spec = importlib.util.spec_from_file_location("eval_extraction", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # let @dataclass resolve annotations via the module
    spec.loader.exec_module(mod)
    return mod


class TestHarnessHasTeeth:
    def test_faithful_replay_scores_high(self):
        h = _load_harness()
        docs = h.load_gold()
        runs = os.path.join(REPO, "benchmark", "runs")
        replay = h.replay_complete_fn(runs)
        results = []
        for d in docs:
            replay.setter(d.id)
            results.append(h.evaluate_doc(d, replay))
        s = h.summarize(results)
        # On clean inputs with faithful extraction, recall is complete.
        assert s["recall"][0] == s["recall"][1]
        assert s["verdict_agreement"][0] == s["verdict_agreement"][1]

    def test_selftest_detects_all_injected_faults(self):
        h = _load_harness()
        runs = os.path.join(REPO, "benchmark", "runs")
        assert h.run_selftest(runs) is True
