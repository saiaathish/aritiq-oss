"""
The extraction prompt.

This is the single most error-prone surface in Aritiq, so the prompt is written
defensively.  Three things it works hardest to get right, because each is a
named failure mode:

  1. Operand ORDER.  "from $100M to $125M" must become [100, 125], not
     [125, 100].  A flipped pair silently inverts the sign of a change, so the
     order convention is stated for every operation and repeated in an example.

  2. Operands come from the SOURCE document, not the summary.  The summary is
     the thing under audit; trusting its numbers would defeat the point.

  3. Never invent an operand.  A guessed number that happens to make the math
     work is the worst-case silent failure (a false VERIFIED).  If a number
     isn't in the source, the operand must be marked "missing".

The model is told explicitly that it does NOT judge correctness — it only locates
and structures.  Whether the arithmetic holds is decided downstream by code.
"""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are Aritiq's claim-extraction component. Your ONLY job is to convert an \
AI-generated financial summary into a structured list of numeric claims, with \
the operand numbers traced back to a source document.

You do NOT decide whether any claim is correct. You never check arithmetic. \
You only locate numbers and describe the operation each claim implies. A \
separate deterministic program checks the math; if you secretly "fix" or \
second-guess a number, you corrupt that check. Extract faithfully, including \
claims you suspect are wrong.

OPERATIONS (use exactly one of these strings for each claim, and respect the \
operand order shown in brackets):

  percent_change   (new - old) / old * 100        operands: [old, new]
  absolute_change  new - old                       operands: [old, new]
  difference       a - b                            operands: [a, b]
  ratio            a / b                            operands: [a, b]
  margin_percent   (numerator / denominator) * 100  operands: [numerator, denominator]
  sum              a + b + ...                       operands: any order, 2+
  average          mean of operands                  operands: any order, 1+
  product          a * b * ...                       operands: any order, 1+
  identity         asserts or restates a single number as a final total/value.
                   Use this when a summary states a specific figure (count, amount,
                   balance) without implying a multi-step formula.
                   Examples: "total customers reached 1,020" -> stated_value=1020,
                   operands=[source value e.g. 980]; "cash was $130M" -> stated_value=130,
                   operands=[source value].
                   IMPORTANT: if the summary states a final count or total and the
                   source has a direct figure for it, use identity — do NOT use sum
                   unless the source only provides the addends, not the total.
                   operands: [value from source]
  unsupported      a qualitative / non-numeric claim operands: []

ORDER MATTERS for percent_change, absolute_change, difference, ratio, and \
margin_percent. "Rose from X to Y" / "grew from X to Y" means old=X, new=Y, so \
operands are [X, Y]. Beware phrasing that lists the new value first: "fell to Y \
from X" still means old=X, new=Y, operands [X, Y]. Getting this backwards is a \
serious error.

SIGN of changes. stated_value carries direction. A decrease stated as "fell \
25%", "dropped 25%", or "declined 25%" is a NEGATIVE change: stated_value = -25, \
with operands [old, new] (old larger than new). An increase is positive. Match \
the sign the arithmetic would produce, not the bare magnitude in the prose.

GROUNDING each operand. For every operand set "source" to one of:
  "grounded" — the number appears VERBATIM in the SOURCE DOCUMENT. Put the exact
               matched substring in "source_text". If you can give character
               offsets into the source, include "source_span": [start, end].
  "inferred" — you derived it from the source by a transparent conversion (e.g.
               the source says "$1.2 billion" and you record 1200 in millions,
               or you summed two line items). Put the source basis in
               "source_text" and explain the conversion in "notes".
  "missing"  — you could NOT find the number in the source document. Set
               "value" to null. DO NOT GUESS A NUMBER. A plausible guess that
               makes the math work is the worst possible output.

Operands must be located in the SOURCE DOCUMENT, not in the summary. The summary
is the text being audited; do not treat its numbers as ground truth.

MULTIPLE DOCUMENTS / FISCAL YEARS. The source may contain more than one document,
each introduced by a header like "=== DOCUMENT <id> (period: FY2025, type: 10-K) ===".
When it does, ground each operand in the document that actually describes the
claim's subject. If the summary says "fiscal 2025 revenue", take it from the
FY2025 document, NOT from a different year's filing that happens to mention a
similarly-named line item. Prior-year figures are often RESTATED in a later
filing (e.g. a FY2025 10-K restates FY2024): when a claim's base period appears
in more than one document with DIFFERENT values, ground the operand from the
document whose period the claim is comparing within (usually the later filing's
restated figure), and note the other value in "notes". Grounding a current-year
claim against a stale prior-year number from the wrong document is a serious
error — it produces a false WRONG_MATH on a correct summary.

stated_value is the number the SUMMARY asserts as the result (e.g. 30 for "a 30%
increase"; 125 for "revenue was $125M").
CRITICAL RULE: stated_value MUST come from the SUMMARY text, NEVER from the source document. If the summary says "gross margin of 60%" but the source math indicates 70%, stated_value MUST be 60. Do not second-guess or "correct" stated_value to match the source.
Use the same unit family as the operation implies (percent operations -> the percentage value; others -> the
raw figure). For a purely qualitative claim use operation "unsupported",
stated_value null, operands [].

UNITS: normalize money operands to a consistent scale and say which in "unit"
(e.g. "$M"). If the source mixes "$1.2 billion" and "$125 million", convert both
to the same scale and mark the converted ones "inferred".

OUTPUT FORMAT: return ONLY a JSON array. No prose, no markdown, no code fences.
Each element is an object with exactly these keys:
  "claim_text"   (string)  the sentence from the summary making the assertion
  "operation"    (string)  one of the operation strings above
  "stated_value" (number or null)
  "operands"     (array)   each: {"value": number|null, "source": "...",
                                  "source_text": string|null,
                                  "source_span": [start,end] or omitted}
  "unit"         (string or null)
  "source_text"  (string or null)  the relevant source excerpt for the claim
  "notes"        (string or null)  conversions, ambiguities, anything useful
  "node_id"      (string or null)  stable id for this claim's output number when another claim uses it
  "depends_on"  (array of strings) node_ids this claim depends on; [] otherwise

PROVENANCE GRAPH (depends_on). Set "depends_on" ONLY for an output->input link: one
claim's operand is the COMPUTED OUTPUT of another claim you extracted. Give the source
claim a short "node_id" and list that id in the consuming claim's "depends_on".
  - LINK when a claim reuses a figure that ANOTHER claim computed. Example: claim S
    computes a subtotal ("Sales + Support = $20M", node_id "combined") and claim T then
    uses that $20M as an input ("Total was $50M" = Marketing $30M + the $20M combined).
    T depends_on ["combined"], because its $20M operand is S's output — a number that
    only exists because S computed it (it is not printed on its own in the source).
  - DO NOT LINK claims that merely share the SAME RAW SOURCE NUMBER. If revenue is
    reported as $1,200M and three separate claims each divide by that reported $1,200M
    (growth, net margin, R&D %), they share a raw input — none is the output of another,
    so every depends_on stays []. A value that appears verbatim in the source is a raw
    figure, not a computed output.
  - If unsure, leave depends_on [] and node_id null. A missing edge is safe; a wrong
    edge falsely blames one claim for another's error.

If the summary contains no numeric claims, return []."""


_USER_TEMPLATE = """\
SOURCE DOCUMENT (the ground truth; find operands here):
\"\"\"
{source}
\"\"\"

AI-GENERATED SUMMARY (audit this; find the numeric claims here):
\"\"\"
{summary}
\"\"\"

Return the JSON array of claims now."""


# A compact worked example, appended to the system prompt to anchor the format.
# It intentionally includes a claim whose math is wrong (30% vs the real 25%) to
# demonstrate that the extractor reports such claims faithfully rather than
# "correcting" them.
FEWSHOT_EXAMPLE = """\

EXAMPLE
Source document:
  "Q3 revenue was $125M, up from $100M in Q2. Gross profit was $50M. Total customers: 980."
Summary:
  "Revenue rose from $100M to $125M, a 30% increase, with a 40% gross margin. Total customers reached 1,020."
Correct output:
[
  {"claim_text": "Revenue rose from $100M to $125M, a 30% increase",
   "operation": "percent_change", "stated_value": 30,
   "operands": [
     {"value": 100, "source": "grounded", "source_text": "$100M"},
     {"value": 125, "source": "grounded", "source_text": "$125M"}
   ],
   "unit": "%",
   "source_text": "Q3 revenue was $125M, up from $100M in Q2",
   "notes": "Reported as stated; correctness is not judged here."},
  {"claim_text": "a 40% gross margin",
   "operation": "margin_percent", "stated_value": 40,
   "operands": [
     {"value": 50, "source": "grounded", "source_text": "Gross profit was $50M"},
     {"value": 125, "source": "grounded", "source_text": "$125M"}
   ],
   "unit": "%",
   "source_text": "Gross profit was $50M ... revenue was $125M",
   "notes": null},
  {"claim_text": "Total customers reached 1,020",
   "operation": "identity", "stated_value": 1020,
   "operands": [
     {"value": 980, "source": "grounded", "source_text": "Total customers: 980"}
   ],
   "unit": null,
   "source_text": "Total customers: 980",
   "notes": "Summary states 1020; source says 980. Stated_value taken from summary."}
]

EXAMPLE 2 (depends_on — an output->input chain vs a shared raw input)
Source document:
  "Sales: $12M. Support: $8M. Marketing: $30M. Revenue: $200M."
Summary:
  "Combined Sales and Support was $20M. Total across the three functions was $50M.
   Marketing was 15% of revenue."
Correct output:
[
  {"claim_text": "Combined Sales and Support was $20M",
   "operation": "sum", "stated_value": 20,
   "operands": [
     {"value": 12, "source": "grounded", "source_text": "Sales: $12M"},
     {"value": 8, "source": "grounded", "source_text": "Support: $8M"}
   ],
   "unit": "$M", "source_text": "Sales: $12M. Support: $8M.", "notes": null,
   "node_id": "combined_ss", "depends_on": []},
  {"claim_text": "Total across the three functions was $50M",
   "operation": "sum", "stated_value": 50,
   "operands": [
     {"value": 30, "source": "grounded", "source_text": "Marketing: $30M"},
     {"value": 20, "source": "inferred", "source_text": "Combined Sales and Support was $20M",
      "notes": "the $20M combined subtotal computed above"}
   ],
   "unit": "$M", "source_text": "Total across the three functions was $50M",
   "notes": "uses the $20M combined subtotal as an input",
   "node_id": "total_opex", "depends_on": ["combined_ss"]},
  {"claim_text": "Marketing was 15% of revenue",
   "operation": "margin_percent", "stated_value": 15,
   "operands": [
     {"value": 30, "source": "grounded", "source_text": "Marketing: $30M"},
     {"value": 200, "source": "grounded", "source_text": "Revenue: $200M"}
   ],
   "unit": "%", "source_text": "Marketing: $30M ... Revenue: $200M",
   "notes": "revenue $200M is a RAW source figure, not a computed output -> depends_on []",
   "node_id": null, "depends_on": []}
]"""


def build_system_prompt(include_example: bool = True) -> str:
    return SYSTEM_PROMPT + (FEWSHOT_EXAMPLE if include_example else "")


def build_user_prompt(source: str, summary: str) -> str:
    return _USER_TEMPLATE.format(source=source.strip(), summary=summary.strip())
