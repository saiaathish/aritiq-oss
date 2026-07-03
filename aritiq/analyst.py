"""
AI Analyst Mode — analyst mode. The ONE place a model touches user-facing
output, built so it cannot quietly undermine "the verifier contains no model".

THE HARD BOUNDARY (each layer deterministic, each tested):

1. THE LEDGER. From verification output, ONLY claims whose status is VERIFIED
   become facts the model may see. Everything else (WRONG_MATH,
   INSUFFICIENT_EVIDENCE, UNSUPPORTED_NUMBER, UNCHECKED, AMBIGUOUS, CONFLICT,
   PROPAGATED_ERROR, NEEDS_REVIEW) goes to a BLOCKED list whose numeric values
   are STRIPPED before anything downstream — the model cannot leak a number it
   never receives.

2. THE PRE-MODEL REFUSAL GATE. Relevance of facts/blocked items to the
   question is decided by deterministic topic matching. If no VERIFIED fact is
   relevant, the analyst refuses BEFORE any model call — `model_called=False`
   — naming the blocking status. The adversarial case ("the only relevant
   number is bad") is therefore decided by code, not by prompt discipline.

3. THE POST-MODEL NUMBER WHITELIST. When the model does answer, every numeric
   token in its answer must match a value from the verified facts it was given
   (rounding-tolerant), and every citation must name a real fact id. An answer
   containing any number outside the whitelist is REJECTED and replaced with a
   refusal — a fluent hallucination cannot reach the caller.

WHAT THE MODEL CONTRIBUTES: wording only. Which numbers may be spoken, and
whether to speak at all, is decided by deterministic code on both sides of the
call.

FIREWALL: this module lives OUTSIDE `aritiq/core/` and imports no model SDK
directly — the completion function is injected (defaulting to the extractor's
existing provider plumbing, lazily). `aritiq/core/` remains model-free.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Sequence

from .core.schema import VerificationResult, VerificationStatus

# (system_prompt, user_prompt) -> raw model text.  Same shape as extractor's.
CompletionFn = Callable[[str, str], str]

_DIGIT_RE = re.compile(r"\d")
_NUM_RE = re.compile(r"-?\$?\(?\d[\d,]*\.?\d*\)?%?")

# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@dataclass
class VerifiedFact:
    fact_id: str
    topic: str                    # rule_name or operation
    text: str                     # claim text / synthesized description
    values: List[float]           # every number the model may repeat
    explanation: str


@dataclass
class BlockedItem:
    topic: str
    status: str                   # the non-VERIFIED verdict
    reason: str                   # explanation with ALL digits stripped


@dataclass
class FactLedger:
    facts: List[VerifiedFact] = field(default_factory=list)
    blocked: List[BlockedItem] = field(default_factory=list)


def _strip_numbers(text: str) -> str:
    """Remove every numeric token so a blocked value can never leak through a
    reason string."""
    return _NUM_RE.sub("[number withheld]", text or "")


def ledger_from_results(results: Sequence[VerificationResult]) -> FactLedger:
    """Build the ledger from live pipeline output (VerificationResult objects)."""
    ledger = FactLedger()
    for i, r in enumerate(results):
        topic = r.claim.rule_name or r.claim.operation.value
        if r.status == VerificationStatus.VERIFIED:
            values = [v for v in (
                [r.claim.stated_value, r.recomputed_value]
                + [o.value for o in r.claim.operands]
            ) if v is not None]
            ledger.facts.append(VerifiedFact(
                fact_id=f"F{len(ledger.facts) + 1}",
                topic=topic,
                text=r.claim.claim_text,
                values=values,
                explanation=r.explanation,
            ))
        else:
            ledger.blocked.append(BlockedItem(
                topic=topic,
                status=r.status.value,
                reason=_strip_numbers(r.explanation),
            ))
    return ledger


def ledger_from_records(records: Sequence[dict]) -> FactLedger:
    """Build the ledger from harness claim-record dicts (the benchmark replay
    shape used by the dashboard and the backend cache)."""
    ledger = FactLedger()
    for r in records:
        topic = r.get("rule_name") or r.get("operation", "claim")
        if r.get("verdict") == VerificationStatus.VERIFIED.value:
            values = [v for v in (r.get("operand_values") or []) if v is not None]
            ledger.facts.append(VerifiedFact(
                fact_id=f"F{len(ledger.facts) + 1}",
                topic=topic,
                text=f"{topic} check passed on operands "
                     f"{[v for v in values]}",
                values=values,
                explanation=r.get("explanation", ""),
            ))
        else:
            ledger.blocked.append(BlockedItem(
                topic=topic,
                status=r.get("verdict", "UNCHECKED"),
                reason=_strip_numbers(r.get("explanation", "")),
            ))
    return ledger


# ---------------------------------------------------------------------------
# Deterministic relevance
# ---------------------------------------------------------------------------

# question keywords -> topic (rule_name / operation) they concern
_TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "balance_sheet_identity": ["balance", "asset", "assets", "liabilities",
                               "liability", "equity", "sheet"],
    "eps_reconciliation": ["eps", "earnings", "per-share", "share", "shares",
                           "diluted", "basic"],
    "cash_flow_tie_out": ["cash"],
    "margin_percent": ["margin", "margins"],
    "percent_change": ["growth", "increase", "decrease", "change", "grew",
                       "fell", "rose", "decline", "declined"],
}

_STOPWORDS = frozenset(
    "the a an is are was were did do does why how what which of to in on for "
    "and or with by from at it its this that company s".split()
)


def _question_topics(question: str) -> List[str]:
    words = {w.strip("?.,!()'\"").lower() for w in question.split()}
    words -= _STOPWORDS
    hits = []
    for topic, kws in _TOPIC_KEYWORDS.items():
        if words.intersection(kws):
            hits.append(topic)
    return hits


def _text_overlap(question: str, text: str) -> bool:
    qw = {w.strip("?.,!()'\"").lower() for w in question.split()} - _STOPWORDS
    tw = {w.strip("?.,!()'\"$%").lower() for w in (text or "").split()} - _STOPWORDS
    qw = {w for w in qw if len(w) > 3 and not _DIGIT_RE.search(w)}
    tw = {w for w in tw if len(w) > 3 and not _DIGIT_RE.search(w)}
    return len(qw & tw) >= 1


def relevant_items(question: str, ledger: FactLedger):
    """Deterministic relevance: topic-keyword match OR claim-text word overlap."""
    topics = set(_question_topics(question))
    facts = [f for f in ledger.facts
             if f.topic in topics or _text_overlap(question, f.text)]
    blocked = [b for b in ledger.blocked
               if b.topic in topics or _text_overlap(question, b.reason)]
    return facts, blocked


# ---------------------------------------------------------------------------
# The answer object
# ---------------------------------------------------------------------------


@dataclass
class AnalystAnswer:
    mode: str            # "answered" | "refused_blocked" | "refused_no_data"
                         # | "rejected_unverified_output"
    answer: Optional[str]
    citations: List[str] = field(default_factory=list)
    facts_available: int = 0
    facts_used: List[dict] = field(default_factory=list)
    blocking: List[dict] = field(default_factory=list)   # topic+status, no numbers
    model_called: bool = False
    guard: str = ""      # the deterministic boundary decision, stated

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Post-model validation (the number whitelist)
# ---------------------------------------------------------------------------

def _extract_numbers(text: str) -> List[float]:
    out = []
    # strip [F1]-style citations first so fact ids aren't parsed as numbers
    cleaned = re.sub(r"\[F\d+\]", "", text)
    for tok in _NUM_RE.findall(cleaned):
        t = tok.replace(",", "").replace("$", "").replace("%", "")
        neg = t.startswith("(") and t.endswith(")")
        t = t.strip("()")
        if not t or not _DIGIT_RE.search(t):
            continue
        try:
            v = float(t)
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def _matches_whitelist(num: float, whitelist: Sequence[float]) -> bool:
    a = abs(num)
    # prose counters ("the three statements", "2 of 4 checks") are allowed
    if a <= 12 and float(a).is_integer():
        return True
    for w in whitelist:
        for cand in {w, abs(w)}:
            if abs(num - cand) <= max(0.005 * abs(cand), 0.01):
                return True
            for d in (0, 1, 2, 3):
                if abs(num - round(cand, d)) <= 10 ** (-d) / 2 + 1e-9:
                    return True
    return False


def validate_answer(answer_text: str, citations: Sequence[str],
                    facts: Sequence[VerifiedFact]) -> Optional[str]:
    """Return None if the answer passes; otherwise the reason it fails."""
    fact_ids = {f.fact_id for f in facts}
    for c in citations:
        if c not in fact_ids:
            return f"citation {c!r} does not name a provided verified fact"
    if not citations:
        return "no citations — every analyst answer must cite verified facts"
    whitelist = [v for f in facts for v in f.values]
    for num in _extract_numbers(answer_text):
        if not _matches_whitelist(num, whitelist):
            return (f"number {num} does not appear in any verified fact "
                    "(hallucination guard)")
    return None


# ---------------------------------------------------------------------------
# The analyst
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are Aritiq's analyst. You answer questions about a company's financials USING ONLY the numbered VERIFIED FACTS provided. Hard rules:
1. Use ONLY numbers that literally appear in the facts. Never compute, estimate, or recall any other number.
2. Cite the fact id in square brackets (e.g. [F1]) after every numeric statement.
3. If the facts provided are not sufficient to answer, say so plainly instead of guessing.
4. Respond with a JSON array containing exactly one object: [{"answer": "<your answer>", "citations": ["F1", ...]}] and nothing else."""


def _default_complete_fn() -> CompletionFn:
    # Lazy import so this module never hard-depends on a model SDK.
    from .extract.extractor import _default_complete_fn as build
    import os
    provider = (os.environ.get("ARITIQ_PROVIDER") or "anthropic").lower()
    fn, _p, _m = build(provider, None, 1024)
    return fn


def ask_analyst(
    question: str,
    ledger: FactLedger,
    *,
    complete_fn: Optional[CompletionFn] = None,
) -> AnalystAnswer:
    """Answer a question from verified claims only. See module docstring for
    the three-layer boundary this function enforces."""
    facts, blocked = relevant_items(question, ledger)
    blocking = [{"topic": b.topic, "status": b.status} for b in blocked]

    # ---- Layer 2a: TOPIC-PRECISION gate (deterministic) ---------------------
    # If ANY topic the question touches has blocked claims and NO verified
    # claim for that same topic, refuse — even when an ADJACENT topic has
    # verified facts. Without this, "does cash tie out to balance sheet cash?"
    # would be answered from a verified balance-sheet fact while the actual
    # subject (the cash tie-out) is INSUFFICIENT_EVIDENCE — a fluent answer
    # over a bad number, the exact failure this mode must not have. (Found by
    # the at-scale measurement in benchmark/reliability/analyst_eval.py, not
    # by construction — kept as a regression test.)
    q_topics = set(_question_topics(question))
    verified_topics = {f.topic for f in ledger.facts}
    blocked_only_topics = sorted(
        t for t in q_topics
        if t not in verified_topics and any(b.topic == t for b in ledger.blocked)
    )
    if blocked_only_topics:
        statuses = sorted({b.status for b in ledger.blocked
                           if b.topic in blocked_only_topics})
        return AnalystAnswer(
            mode="refused_blocked", answer=None,
            facts_available=len(ledger.facts),
            blocking=[{"topic": b.topic, "status": b.status}
                      for b in ledger.blocked if b.topic in blocked_only_topics],
            model_called=False,
            guard=(f"Refused before any model call: the question concerns "
                   f"{', '.join(blocked_only_topics)}, whose claims did not pass "
                   f"verification ({', '.join(statuses)}). A verified fact on an "
                   "adjacent topic is not license to narrate an unverified one."),
        )

    # ---- Layer 2b: TOPIC-COVERAGE gate (deterministic) ----------------------
    # A question is answerable only when EVERY topic it names has at least one
    # verified fact. A topic with no claims at all (neither verified nor
    # blocked) is an uncovered subject: answering from an adjacent verified
    # topic would produce a fluent non-answer ("does cash tie out?" → "the
    # balance sheet balances!"). Conservative by design — the v1 posture is
    # refuse rather than risk a wrong route.
    absent_topics = sorted(
        t for t in q_topics
        if t not in verified_topics and not any(b.topic == t for b in ledger.blocked)
    )
    if absent_topics:
        return AnalystAnswer(
            mode="refused_no_data", answer=None,
            facts_available=len(ledger.facts), model_called=False,
            guard=(f"Refused before any model call: no claim (verified or "
                   f"otherwise) covers {', '.join(absent_topics)}, which the "
                   "question asks about. Verified facts on adjacent topics are "
                   "not an answer to an uncovered subject."),
        )

    # ---- Layer 2c: pre-model refusal gate (deterministic) -------------------
    if not facts:
        if blocked:
            statuses = sorted({b.status for b in blocked})
            return AnalystAnswer(
                mode="refused_blocked", answer=None,
                facts_available=len(ledger.facts), blocking=blocking,
                model_called=False,
                guard=(f"Refused before any model call: the claims relevant to "
                       f"this question did not pass verification "
                       f"({', '.join(statuses)}). Aritiq does not narrate "
                       "numbers it could not verify."),
            )
        return AnalystAnswer(
            mode="refused_no_data", answer=None,
            facts_available=len(ledger.facts), model_called=False,
            guard=("Refused before any model call: no verified claim is "
                   "relevant to this question."),
        )

    # ---- Model narration over verified facts only --------------------------
    fact_lines = "\n".join(
        f"{f.fact_id} [{f.topic}]: {f.text} (values: "
        f"{', '.join(str(v) for v in f.values)}) — {f.explanation}"
        for f in facts
    )
    note = ""
    if blocked:
        note = ("\nNOTE: some related checks did NOT pass verification "
                f"({', '.join(sorted({b.status for b in blocked}))}); their "
                "numbers are withheld from you. If they matter to the answer, "
                "say the verification status instead of a number.")
    user_prompt = f"VERIFIED FACTS:\n{fact_lines}\n{note}\nQUESTION: {question}"

    fn = complete_fn or _default_complete_fn()
    raw = fn(_SYSTEM_PROMPT, user_prompt)

    answer_text, citations = _parse_model_response(raw)
    if answer_text is None:
        return AnalystAnswer(
            mode="rejected_unverified_output", answer=None,
            facts_available=len(ledger.facts), blocking=blocking,
            model_called=True,
            guard="Model response was not parseable as the required cited format.",
        )

    # ---- Layer 3: post-model number whitelist (deterministic) ---------------
    failure = validate_answer(answer_text, citations, facts)
    if failure:
        return AnalystAnswer(
            mode="rejected_unverified_output", answer=None,
            citations=citations, facts_available=len(ledger.facts),
            blocking=blocking, model_called=True,
            guard=(f"Model output REJECTED by the deterministic guard: {failure}. "
                   "The fluent answer was withheld rather than shown."),
        )

    return AnalystAnswer(
        mode="answered", answer=answer_text, citations=citations,
        facts_available=len(ledger.facts),
        facts_used=[{"fact_id": f.fact_id, "topic": f.topic, "text": f.text}
                    for f in facts if f.fact_id in set(citations)],
        blocking=blocking, model_called=True,
        guard=("Answered from verified facts only; every number in the answer "
               "matched the verified-fact whitelist and every citation names a "
               "provided fact."),
    )


def _parse_model_response(raw: str):
    """Parse [{"answer": ..., "citations": [...]}] (tolerating code fences)."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return None, []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None, []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        obj = data[0]
    elif isinstance(data, dict):
        obj = data
    else:
        return None, []
    answer = obj.get("answer")
    citations = obj.get("citations") or []
    if not isinstance(answer, str) or not isinstance(citations, list):
        return None, []
    return answer, [str(c) for c in citations]
