"""
Phase 2 firewall test — the moat got WIDER, not SMARTER.

The entire Aritiq thesis is that no model sits in the verification path. Phase 2
added a lot of new verification code (rules.py, registry.py, tables.py) and two
new statuses. This test pins, at the AST level, that none of that new code
reaches for an LLM — so a reviewer (or a YC partner) can trust the claim without
reading every line.

If any future change imports anthropic/openai/etc. into the verification path,
this test fails loudly.
"""
import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every module the verification path can reach. If you add a new pure-verifier
# module, add it here.
VERIFICATION_PATH = [
    os.path.join("aritiq", "core", "schema.py"),
    os.path.join("aritiq", "core", "verify.py"),
    os.path.join("aritiq", "core", "rules.py"),
    os.path.join("aritiq", "core", "score.py"),
    os.path.join("aritiq", "core", "registry.py"),
    os.path.join("aritiq", "core", "tables.py"),
    # ---- Phase 3 additions: still pure, still in the firewall ----
    os.path.join("aritiq", "core", "graph.py"),
    os.path.join("aritiq", "core", "restatement.py"),
    os.path.join("aritiq", "core", "conflicts.py"),
]

FORBIDDEN_SUBSTRINGS = ("anthropic", "openai", "google.genai", "groq",
                        "extract", "prompt", "llm")


def _imports_in(path):
    tree = ast.parse(open(path).read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(("." * (node.level or 0)) + (node.module or ""))
    return mods


def test_no_verification_module_imports_an_llm():
    offenders = {}
    for rel in VERIFICATION_PATH:
        path = os.path.join(REPO, rel)
        mods = _imports_in(path)
        bad = [m for m in mods if any(t in m.lower() for t in FORBIDDEN_SUBSTRINGS)]
        if bad:
            offenders[rel] = bad
    assert not offenders, f"verification path must contain NO model imports: {offenders}"


def test_rules_module_is_pure_functions_only():
    """rules.py must not import the extraction package or any SDK — it is the
    heart of the 'code verifies' claim."""
    mods = _imports_in(os.path.join(REPO, "aritiq", "core", "rules.py"))
    bad = [m for m in mods if "extract" in m or any(
        sdk in m.lower() for sdk in ("anthropic", "openai", "genai", "groq"))]
    assert not bad, f"rules.py must be model-free: {bad}"


def test_every_new_operation_has_a_verifier_branch():
    """Each Phase 2 Operation must be handled by the verifier (no silent
    fall-through to a wrong default). This guards the §3.1 discipline: every
    operation we added is something code actually verifies."""
    from aritiq.core.schema import (
        Operation, Claim, Operand, OperandSource, TrendDir, Superlative, EPSVariant,
    )
    from aritiq.core.verify import verify_claim, _PHASE2_OPERATIONS

    # Every Phase 2 operation must be in the dispatch set.
    expected = {
        Operation.INTERNAL_CONSISTENCY, Operation.TREND_DIRECTION,
        Operation.SUPERLATIVE, Operation.CONSECUTIVE_COUNT,
        Operation.AGGREGATE_FILTER, Operation.DEFINITIONAL_FLAG,
    }
    assert expected <= _PHASE2_OPERATIONS

    # And each one, given a minimal claim, returns a real status (never raises).
    smoke = [
        Claim("bs", Operation.INTERNAL_CONSISTENCY, None,
              [Operand(3.0), Operand(1.0), Operand(2.0)], rule_name="balance_sheet_identity"),
        Claim("trend", Operation.TREND_DIRECTION, None,
              [Operand(1.0), Operand(2.0)], trend_dir=TrendDir.UP,
              params={"series": [("a", 1.0), ("b", 2.0)]}),
        Claim("sup", Operation.SUPERLATIVE, None,
              [Operand(1.0), Operand(2.0)], superlative=Superlative.MAX,
              params={"series": [("a", 1.0), ("b", 2.0)]}),
        Claim("cons", Operation.CONSECUTIVE_COUNT, 1.0,
              [Operand(1.0), Operand(2.0)], trend_dir=TrendDir.UP,
              params={"series": [("a", 1.0), ("b", 2.0)]}),
        Claim("agg", Operation.AGGREGATE_FILTER, 3.0,
              [Operand(1.0), Operand(2.0)], params={"mode": "sum"}),
        Claim("def", Operation.DEFINITIONAL_FLAG, None, [],
              params={"nearby_number": 4.0}),
    ]
    for c in smoke:
        r = verify_claim(c)
        assert r.status is not None
