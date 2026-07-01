"""
Strict JSON contract for LLM-extracted claims, plus the conversion bridge to
the Day 1 verifier schema.

Design rules (these are deliberate):

  * The LLM is asked for a JSON array of claims.  We validate that array HARD
    with Pydantic.  If a claim is structurally malformed (missing a required
    field, wrong type, an operation/source value outside the enum), it is
    *rejected* and recorded as an ExtractionIssue — it never reaches the
    verifier.  This is the "validate hard" half of belt-and-suspenders.

  * We do NOT enforce *semantic* rules here (e.g. "percent_change needs exactly
    two operands").  Operand-count problems, divide-by-zero, etc. are the
    verifier's job — it classifies them as AMBIGUOUS.  Rejecting them here would
    blur the firewall: structural validity is an extraction concern, arithmetic
    validity is a verification concern, and they must stay separate.

  * Numbers from real summaries are dirty ("$1,200", "25%", "1.2bn").  A
    `before` validator normalizes common money/percent formatting into floats
    so a benign formatting choice doesn't get mislabeled as a structural error.
    Genuinely non-numeric junk still fails validation.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, field_validator

from ..core.schema import (
    Claim,
    EPSVariant,
    Operand,
    Operation,
    OperandSource,
    Superlative,
    TrendDir,
)


MAX_EXTRACTED_CLAIMS = 200

_OPERATION_ALIASES = {
    "percentchange": Operation.PERCENT_CHANGE.value,
    "percentage_change": Operation.PERCENT_CHANGE.value,
    "growth_rate": Operation.PERCENT_CHANGE.value,
    "change_percent": Operation.PERCENT_CHANGE.value,
    "margin": Operation.MARGIN_PERCENT.value,
    "gross_margin": Operation.MARGIN_PERCENT.value,
    "net_margin": Operation.MARGIN_PERCENT.value,
    "operating_margin": Operation.MARGIN_PERCENT.value,
    "divide": Operation.RATIO.value,
    "quotient": Operation.RATIO.value,
    "addition": Operation.SUM.value,
    "subtract": Operation.DIFFERENCE.value,
}

_SOURCE_ALIASES = {
    "grounded_table": OperandSource.GROUNDED_TABLE_CELL.value,
    "table_cell": OperandSource.GROUNDED_TABLE_CELL.value,
    "prose": OperandSource.GROUNDED_PROSE.value,
    "grounded_text": OperandSource.GROUNDED.value,
}

# ---------------------------------------------------------------------------
# Number normalization
# ---------------------------------------------------------------------------

def _coerce_number(v):
    """
    Turn a possibly-dirty numeric value into a float, WITHOUT guessing scale.

    Accepts plain numbers untouched.  For strings, strips currency symbols,
    thousands separators, and a trailing percent sign, then parses the plain
    number ("$1,200" -> 1200.0, "25%" -> 25.0).

    It deliberately does NOT expand magnitude suffixes (M/bn/...).  Auto-scaling
    "$100M" to 1e8 while a sibling operand is written as a bare 125 (meaning
    $125M) would silently create a scale mismatch — the exact kind of quiet
    corruption Aritiq exists to prevent.  Scale normalization is the extractor's
    explicit job (the prompt requires consistent units in `value`).  So a value
    we can't parse as a plain number is returned unchanged, which makes Pydantic
    reject it and surfaces it as a visible ExtractionIssue rather than a guess.
    """
    if v is None or isinstance(v, (int, float)):
        return v
    if not isinstance(v, str):
        return v

    s = v.strip().lower().replace(",", "").replace("$", "").replace("%", "").strip()
    if s in ("", "n/a", "na", "none", "null"):
        return None

    if re.fullmatch(r"-?\d*\.?\d+", s):
        return float(s)
    return v  # leftover suffix/junk -> let Pydantic reject it (visible, not silent)


def _reject_nonfinite(v):
    if isinstance(v, (int, float)) and not math.isfinite(float(v)):
        raise ValueError("non-finite numeric value (NaN/Infinity) rejected")
    return v


# ---------------------------------------------------------------------------
# Pydantic models — the wire format the LLM must produce
# ---------------------------------------------------------------------------

class RawOperand(BaseModel):
    """One input number to a claim's arithmetic, as reported by the extractor."""
    model_config = ConfigDict(extra="ignore")

    value: Optional[float] = None       # null is allowed iff source == "missing"
    source: OperandSource = OperandSource.GROUNDED
    source_text: Optional[str] = None   # verbatim string located in the SOURCE doc
    source_span: Optional[List[int]] = None  # [start, end] char offsets, if known

    # ---- Phase 2 optional provenance (default off; Phase 1 ignores these) --
    doc_id: Optional[str] = None        # §2.2 which registry doc this came from
    category: Optional[str] = None      # Axis C: inferred category / EPS variant tag
    category_scheme_version: Optional[str] = None  # §7 categorization version stamp

    @field_validator("source", mode="before")
    @classmethod
    def _clean_source(cls, v):
        if isinstance(v, str):
            key = re.sub(r"[^a-z0-9]+", "_", v.strip().lower()).strip("_")
            return _SOURCE_ALIASES.get(key, key)
        return v

    @field_validator("value", mode="before")
    @classmethod
    def _clean_value(cls, v):
        return _reject_nonfinite(_coerce_number(v))

    @field_validator("source_span")
    @classmethod
    def _check_span(cls, v):
        if v is not None and len(v) != 2:
            raise ValueError("source_span must be [start, end]")
        return v


class RawClaim(BaseModel):
    """A single numeric assertion found in the summary, with its provenance."""
    model_config = ConfigDict(extra="ignore")

    claim_text: str
    operation: Operation
    stated_value: Optional[float] = None
    operands: List[RawOperand] = []
    unit: Optional[str] = None
    source_text: Optional[str] = None
    notes: Optional[str] = None

    # ---- Phase 2 optional fields (default None; Phase 1 claims never set) --
    rule_name: Optional[str] = None              # §3.3 internal-consistency rule
    eps_variant: Optional[EPSVariant] = None     # §4 basic / diluted
    trend_dir: Optional[TrendDir] = None         # §3.2 up / down / flat
    superlative: Optional[Superlative] = None    # §3.2 max / min
    params: dict = {}                            # operation-specific extras (series, mode, ...)

    # ---- Phase 3 provenance graph fields -------------------------------
    node_id: Optional[str] = None
    depends_on: List[str] = []

    @field_validator("operation", mode="before")
    @classmethod
    def _clean_operation(cls, v):
        if isinstance(v, str):
            key = re.sub(r"[^a-z0-9]+", "_", v.strip().lower()).strip("_")
            return _OPERATION_ALIASES.get(key, key)
        return v

    @field_validator("stated_value", mode="before")
    @classmethod
    def _clean_stated(cls, v):
        return _reject_nonfinite(_coerce_number(v))

    @field_validator("params", mode="before")
    @classmethod
    def _params_none_is_empty(cls, v):
        """Accept `params: null` as an empty params bag.

        WHY THIS IS SAFE (and is NOT the forbidden None->{} value-coercion).
        `params` is an OPTIONAL metadata bag — `null`, `{}`, and an omitted key
        are all semantically identical ("this claim carries no extra params").
        A model that writes `"params": null` instead of `"params": {}` has made a
        benign formatting choice, not hidden a real number, so rejecting the whole
        claim over it (the Verizon failure: 3 claims silently dropped with
        `dict_type` errors, leaving a vacuous 100/100 score) is wrong.

        Critically, this does NOT coerce an operand VALUE of None into a number —
        that remains strict in `_coerce_number`, because a missing operand value
        DOES hide a real extraction failure and must stay visible. The repair here
        is logged by `parse_claims` as a visible ExtractionIssue, never silent.
        """
        if v is None:
            return {}
        return v


# ---------------------------------------------------------------------------
# Issues — what we record when a claim is rejected or repaired
# ---------------------------------------------------------------------------

@dataclass
class ExtractionIssue:
    """A structural problem with one element of the LLM output."""
    index: Optional[int]      # position in the JSON array, if known
    reason: str               # human-readable cause
    raw: Optional[str] = None # the offending fragment, truncated for logs


# ---------------------------------------------------------------------------
# Conversion: validated RawClaim -> Day 1 Claim dataclass
# ---------------------------------------------------------------------------

def _raw_to_operand(ro: RawOperand) -> Operand:
    # A missing operand has no usable value; the verifier ignores the value and
    # short-circuits to UNSUPPORTED_NUMBER, so a placeholder is safe here.
    value = ro.value if ro.value is not None else 0.0
    span = tuple(ro.source_span) if ro.source_span else None
    return Operand(
        value=value,
        source=ro.source,
        source_text=ro.source_text,
        source_span=span,
        doc_id=ro.doc_id,
        category=ro.category,
        category_scheme_version=ro.category_scheme_version,
    )


def _repair_operation_and_operands(rc: RawClaim) -> tuple[Operation, List[RawOperand]]:
    """Narrow cleanup for common live extraction shape mistakes."""
    op = rc.operation
    operands = list(rc.operands)
    text = " ".join(
        p for p in (rc.claim_text, rc.source_text, rc.notes, rc.unit) if p
    ).lower()

    if (
        op == Operation.IDENTITY
        and len(operands) == 2
        and "margin" in text
        and rc.stated_value is not None
    ):
        return Operation.MARGIN_PERCENT, operands

    if op == Operation.IDENTITY and len(operands) > 1 and (
        "eps" in text or "earnings per share" in text
    ):
        return op, operands[:1]

    return op, operands


def raw_to_claim(rc: RawClaim) -> Claim:
    """Convert a validated RawClaim into the verifier's Claim dataclass."""
    operation, operands = _repair_operation_and_operands(rc)
    return Claim(
        claim_text=rc.claim_text,
        operation=operation,
        stated_value=rc.stated_value,
        operands=[_raw_to_operand(o) for o in operands],
        unit=rc.unit,
        source_text=rc.source_text,
        notes=rc.notes,
        rule_name=rc.rule_name,
        eps_variant=rc.eps_variant,
        trend_dir=rc.trend_dir,
        superlative=rc.superlative,
        params=dict(rc.params) if rc.params else {},
        node_id=rc.node_id,
        depends_on=list(rc.depends_on),
    )


# ---------------------------------------------------------------------------
# JSON extraction + hard validation (NO LLM here — pure, testable)
# ---------------------------------------------------------------------------

def _extract_json_array(text: str) -> str:
    """
    Pull the JSON array out of a model response.

    Handles:
    - Bare arrays:                  [ {...}, {...} ]
    - Wrapped in an object:         { "claims": [ {...} ] }  (Gemini JSON mode)
    - Wrapped in markdown fences:   ```json\n[...]\n```
    - Leading/trailing prose
    """
    if text is None:
        raise ValueError("empty model response")

    # Strip code fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)

    text = text.strip()

    # If the response is a JSON object (Gemini json-mode wraps in {}),
    # try to parse it and extract the first array value.
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            for v in obj.values():
                if isinstance(v, list):
                    return json.dumps(v)
        except json.JSONDecodeError:
            pass  # fall through to bracket-walk below

    start = text.find("[")
    if start == -1:
        raise ValueError("no JSON array found in model response")

    # Walk to the matching bracket, respecting strings/escapes.
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("unterminated JSON array in model response")


def _normalize_model_item(item: dict) -> dict:
    """Normalize common LLM spelling/enum aliases before strict validation."""
    fixed = dict(item)
    op = fixed.get("operation")
    if isinstance(op, str):
        key = re.sub(r"[^a-z0-9]+", "_", op.strip().lower()).strip("_")
        fixed["operation"] = _OPERATION_ALIASES.get(key, key)
    operands = []
    for operand in fixed.get("operands") or []:
        if not isinstance(operand, dict):
            operands.append(operand)
            continue
        o = dict(operand)
        src = o.get("source")
        if isinstance(src, str):
            src_key = re.sub(r"[^a-z0-9]+", "_", src.strip().lower()).strip("_")
            o["source"] = _SOURCE_ALIASES.get(src_key, src_key)
        operands.append(o)
    fixed["operands"] = operands
    return fixed


def parse_claims(text: str) -> Tuple[List[Claim], List[ExtractionIssue]]:
    """
    Parse raw model text into (valid Claims, issues).

    This function contains no LLM call and is the seam the test suite exercises.
    Each array element is validated independently: one malformed claim does not
    discard the rest, it is recorded as an ExtractionIssue.  Only structurally
    valid claims cross into the verifier.
    """
    issues: List[ExtractionIssue] = []

    try:
        array_str = _extract_json_array(text)
    except ValueError as exc:
        return [], [ExtractionIssue(index=None, reason=str(exc), raw=(text or "")[:200])]

    try:
        data = json.loads(array_str)
    except json.JSONDecodeError as exc:
        return [], [ExtractionIssue(index=None, reason=f"JSON decode error: {exc}", raw=array_str[:200])]

    if not isinstance(data, list):
        return [], [ExtractionIssue(index=None, reason="top-level JSON is not an array", raw=array_str[:200])]

    if len(data) > MAX_EXTRACTED_CLAIMS:
        issues.append(ExtractionIssue(
            index=None,
            reason=(
                f"model returned {len(data)} claims; capped at "
                f"{MAX_EXTRACTED_CLAIMS} to protect API latency"
            ),
            raw=array_str[:200],
        ))
        data = data[:MAX_EXTRACTED_CLAIMS]

    claims: List[Claim] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            issues.append(ExtractionIssue(index=i, reason="array element is not an object", raw=str(item)[:200]))
            continue
        # Visibility (not silence): record benign shape repairs so a downstream
        # report can see the model emitted null where {} was expected, without
        # discarding an otherwise-valid claim (the Verizon vacuous-score fix).
        if "params" in item and item.get("params") is None:
            issues.append(ExtractionIssue(
                index=i,
                reason="repaired: params was null, treated as empty {} (claim kept)",
                raw=json.dumps(item)[:200],
            ))
        try:
            rc = RawClaim.model_validate(item)
        except Exception as exc:  # pydantic ValidationError or otherwise
            issues.append(ExtractionIssue(index=i, reason=f"schema validation failed: {exc}", raw=json.dumps(item)[:200]))
            continue
        claims.append(raw_to_claim(rc))

    return claims, issues
