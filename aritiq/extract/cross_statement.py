"""
Cross-statement consistency extraction (cross-statement, spec §3).

This is the ONLY new place an LLM runs for the cross-statement feature, and the
job is *narrower* than summary-audit claim extraction, not broader: locate and ground
a fixed, small set of figures, and never compute anything.  Whether the numbers
agree is decided entirely downstream by aritiq.core.rules — pure code.

Firewall: like extractor.py, this module imports the schema and prompt builders
but NOT aritiq.core.verify or score.  Verification never imports it.

Key discipline (spec §3, "Decision point"):
  Absence of a statement is a DIFFERENT fact than a statement that fails to
  balance.  If a document has no balance sheet (e.g. it's an earnings press
  release), the extractor emits ZERO balance_sheet_identity claims — it does NOT
  emit a claim with three `missing` operands and let it become UNSUPPORTED_NUMBER.
  "Doesn't apply" must not be conflated with "unsupported".
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..core.schema import Claim, Operation, OperandSource
from .extractor import CompletionFn, ExtractionOutput, _default_complete_fn, DEFAULT_MAX_TOKENS
from .schema import ExtractionIssue, parse_claims


# The three rules, with the statement each requires and the operand order the
# verifier expects.  Stated here (not just in the prompt) so the contract is
# greppable from code.
RULE_REQUIREMENTS = {
    "balance_sheet_identity": {
        "needs": "a balance sheet (assets, liabilities, equity)",
        "operand_order": "[total_assets, total_liabilities, total_equity]",
    },
    "eps_reconciliation": {
        "needs": "an income statement with EPS, net income, and weighted-average shares",
        "operand_order": "[stated_eps, net_income, shares_outstanding]",
    },
    "cash_flow_tie_out": {
        "needs": "both a cash-flow statement ending cash and a balance-sheet cash line",
        "operand_order": "[statement_ending_cash, balance_sheet_cash]",
    },
}

_PREFERRED_EPS_CONTEXT_RE = re.compile(
    r"(net\s+income\s+(?:applicable|available|attributable)\s+(?:to\s+)?common"
    r"|net\s+income\s+applicable\s+common"
    r"|(?:income|earnings)\s+available\s+to\s+common"
    r"|preferred\s+(?:stock\s+)?dividend"
    r"|preferred\s+(?:stock\s+)?(?:distributions|redemption))",
    re.IGNORECASE,
)


def _document_has_preferred_eps_context(document: str) -> bool:
    return bool(_PREFERRED_EPS_CONTEXT_RE.search(document or ""))


CROSS_STATEMENT_SYSTEM_PROMPT = """\
You are Aritiq's CROSS-STATEMENT extraction component. Your ONLY job is to locate \
a small, fixed set of figures inside ONE financial document and ground each one \
verbatim. You do NOT check whether the numbers agree — a separate deterministic \
program does that. Never compute anything. Never "fix" a number.

You produce internal_consistency claims for these rules, ONLY when the document \
actually contains the required statement:

  balance_sheet_identity
    needs: a balance sheet with total assets, total liabilities, total equity.
    operands (IN THIS ORDER): [total_assets, total_liabilities, total_equity]
    CRITICAL — liabilities must be TOTAL liabilities (current AND long-term), not a
    subtotal.
      - ALWAYS ground the explicit "Total liabilities" subtotal row. That exact row
        is the only acceptable liabilities operand.
      - NEVER use "Total current liabilities" as total liabilities. It is a SUBTOTAL;
        long-term debt, deferred taxes, lease/pension obligations, and other
        non-current rows sit BELOW it and are excluded from it.
      - If the explicit "Total liabilities" row IS present, ground it and set
        params.liabilities_complete = true.
      - If only a current-liabilities subtotal is visible (no explicit total
        liabilities row), set params.liabilities_complete = false. Do NOT pass the
        current-only subtotal as if it were total liabilities.
    Set params.liabilities_complete = true ONLY when you grounded the explicit
    "Total liabilities" line (or the explicit sum of ALL liability rows).
      - NEVER set the liabilities operand to 0 (or null/missing) while assets and
        equity are populated. A real company with assets ALWAYS has liabilities; a 0
        there means you failed to find the Total liabilities line. If you cannot
        locate an explicit Total liabilities figure, do NOT emit 0 with
        liabilities_complete=true — instead mark the operand "missing" and set
        liabilities_complete=false. Many balance sheets show "Total liabilities and
        stockholders' equity" (which equals total ASSETS) — that is NOT total
        liabilities; do not ground it as the liabilities operand.
      - Sanity check before you emit: liabilities + equity should approximately
        equal assets. If your three grounded figures don't come close, you have
        grounded the wrong liabilities or equity line — re-ground rather than
        emitting figures that obviously don't tie, and if still unsure set
        liabilities_complete=false.
    CRITICAL — EQUITY IS TOTAL EQUITY INCLUDING NONCONTROLLING INTEREST. The
    identity that holds on the face of the balance sheet is
    Total Liabilities + Total Equity (INCLUDING noncontrolling interest) = Total
    Assets. When the filer shows a separate "Noncontrolling interest(s)" (or
    "redeemable noncontrolling interest") line BELOW "Total stockholders' equity
    attributable to [parent]", you MUST ground the equity operand against the
    filer's "Total equity" / "Total stockholders' equity and noncontrolling
    interests" line — i.e. the figure the filer itself adds to total liabilities to
    reach total assets — NOT the parent-only stockholders' equity above it.
      - If there is no noncontrolling-interest line, stockholders' equity and total
        equity are identical — nothing changes.
    UPREIT / PARTNERSHIP STRUCTURES (REITs especially). Some filers — notably REITs
    structured as an umbrella partnership (UPREITs) — place a MEZZANINE line BETWEEN
    total liabilities and equity, labeled things like "Limited partners' preferred
    interest in the Operating Partnership", "noncontrolling redeemable interests",
    or "redeemable noncontrolling interest". The true identity is then
    Total Liabilities + that mezzanine interest + Total Equity = Total Assets. When
    such a line exists: ground the equity operand against the figure that, added to
    liabilities, reaches total assets (often "Total liabilities and equity" minus
    liabilities), AND quote that mezzanine/redeemable/limited-partners line verbatim
    in the claim's source_text or notes so its presence is recorded. Do not silently
    drop it — if assets don't tie to liabilities + your equity operand, look for a
    redeemable / limited-partners / noncontrolling line accounting for the gap and
    name it in source_text.
    Quick check: for TSLA, parent-only equity 82,137 + liabilities 54,941 = 137,078
    ≠ assets 137,806, but TOTAL equity incl. NCI ≈ 82,865 ties exactly — the
    total-equity line is the right operand. For an UPREIT like Simon Property Group,
    assets exceed liabilities + total equity by exactly the "limited partners' /
    noncontrolling redeemable interests" mezzanine line — quote that line.

  eps_reconciliation
    needs: an income statement with a stated EPS, net income, and weighted-average
           shares outstanding.
    operands (IN THIS ORDER): [stated_eps, net_income, shares_outstanding]
    ALWAYS set "eps_variant" to "basic" or "diluted" matching the EPS you grounded
    — this tag is REQUIRED on every EPS claim, never leave it null. Ground the SHARES
    of the SAME variant (basic shares for basic EPS) and ALWAYS tag the shares
    operand's "category" with that same variant word ("basic" or "diluted"). If you
    cannot find the matching-variant shares, mark that operand "missing" — do NOT
    substitute the other variant, and do NOT leave the variant untagged.
    CRITICAL — SAME UNIT SCALE for net_income and shares. The income statement has a
    single unit header, e.g. "(in millions, except per share data)" or "(in
    thousands ...)". net_income and shares are BOTH printed in that same scale, so
    ground BOTH at that scale: if net income reads "$ 112,010" under an "in millions"
    header, that is 112010 (millions) and the weighted-average shares on the same
    statement (e.g. "15,344" ) are ALSO in millions — do NOT convert shares to raw
    units (15,343,783 thousand) or grab a share count from a different table/scale.
    A correct pairing satisfies stated_eps ≈ net_income / shares to within a cent; if
    your grounded net_income / shares is off from the stated EPS by 100x or 1000x,
    you have grounded the two operands at different scales — re-ground them from the
    SAME line region under the SAME unit header. Never normalize one operand without
    the other.
    CRITICAL — NUMERATOR IS NET INCOME APPLICABLE TO COMMON (preferred stock).
    Banks, utilities, REITs and others with PREFERRED STOCK do NOT compute EPS on
    total net income — they subtract preferred dividends first. Before grounding the
    numerator, look between the "Net income" line and the EPS line for any of:
    "Net income applicable to common stockholders/shareholders", "Net income
    available to common", or an explicit "Preferred stock dividends" deduction.
      - If such a line exists, ground the EPS numerator against that ADJUSTED
        (applicable-to-common) figure, NOT the total net income line above it. Put
        that exact label in the numerator operand's source_text.
      - If no such line exists (most filers have no preferred stock), total net
        income IS the correct numerator — do not change anything.
    Quick check: stated_eps × shares should ≈ your numerator. For a bank like JPM,
    total net income 57,048 / 2,776.5 = 20.55 ≠ stated 20.05, but net income
    applicable to common 55,668 / 2,776.5 = 20.05 — the applicable-to-common line is
    the right numerator.
    CRITICAL — MATCH THE EPS LINE LABEL EXACTLY, then pick the income line that
    shares its basis. EPS is reported on different income bases: TOTAL net income,
    and income from CONTINUING OPERATIONS only (excluding discontinued operations).
      - "Earnings (loss) from continuing operations per share — basic/diluted"
        reconciles against "Income from continuing operations, net of tax" —
        NEVER against "Net income".
      - "Basic/diluted earnings per share" (the TOTAL EPS line, with no
        "continuing operations" qualifier) reconciles against "Net income" (total).
      - Do not mix the two. Pairing a continuing-operations EPS with total net
        income (or vice versa) is the exact AMD-class slip that yields a false
        WRONG_MATH.
    ALWAYS emit BOTH params.eps_income_basis and params.income_operand_basis, each
    set to "continuing" or "total" — eps_income_basis matching the EPS line label you
    grounded, income_operand_basis matching the net-income line you grounded. They
    must describe the SAME basis for the check to run. If you genuinely cannot
    determine the income basis, emit params.eps_income_basis = null (and do not
    attempt to force a reconciliation) — the verifier will hold the check rather
    than risk a false mismatch.

  cash_flow_tie_out
    needs: "cash and cash equivalents at end of period" from the cash-flow
           statement AND "cash and cash equivalents" from the balance sheet.
    operands (IN THIS ORDER): [statement_ending_cash, balance_sheet_cash]
    CRITICAL — RESTRICTED CASH IN THE LABEL ITSELF. If the cash-flow statement line
    is labeled "Cash, cash equivalents, and restricted cash" (or any phrasing that
    includes "restricted cash", e.g. "cash equivalents and restricted cash"), then
    that figure is a DIFFERENT SCOPE than a balance-sheet "Cash and cash equivalents"
    line by definition. In that case:
      - ground that exact label string in the CF operand's source_text, AND
      - set params.restricted_cash_disclosed = true.
    Do NOT attempt to reconcile a "...and restricted cash" cash-flow line against a
    balance-sheet "Cash and cash equivalents" line without this flag — they measure
    different things.
    Separately, if nearby text discloses why the two cash figures differ (cash held
    in escrow, "difference attributable", a reconciliation note, or similar), also
    set params.restricted_cash_disclosed = true AND include that disclosure sentence
    in the claim's "source_text" or "notes". Do not decide whether it resolves the
    mismatch; downstream deterministic code uses the flag and the label/disclosure
    text to avoid a false WRONG_MATH.

CRITICAL — applicability vs. missing:
  If the document does NOT contain the statement a rule needs, DO NOT emit that
  rule's claim at all. Returning a claim with all-"missing" operands is WRONG.
  "The statement isn't here" (omit the claim) is different from "a number is
  missing" (emit with that operand marked missing). Only emit a rule's claim when
  the required statement is present and you can locate at least most of its operands.

GROUNDING each operand — set "source" to:
  "grounded"  — the number appears verbatim in the document. Put the exact matched
                substring in "source_text".
  "inferred"  — you converted units transparently (e.g. read a "(in thousands)"
                table and expressed the value consistently). Explain in "notes".
  "missing"   — you could not find it. Set "value" to null. DO NOT GUESS.

For internal_consistency claims:
  - "stated_value" MUST be null (there is no asserted result; the check IS the
    comparison).
  - "operation" MUST be "internal_consistency".
  - "rule_name" MUST be one of the three rule names above.
  - "unit" should be the money scale you normalized to (e.g. "$M") or null for EPS.
  - "params" carries the COMPLETENESS / SCOPE EVIDENCE the verifier gates on:
      balance_sheet_identity: {"liabilities_complete": true|false}
      eps_reconciliation:     {"eps_income_basis": "continuing"|"total",
                               "income_operand_basis": "continuing"|"total"}
      cash_flow_tie_out:      {"restricted_cash_disclosed": true|false}
    Supplying honest evidence is REQUIRED: if you omit or cannot establish it, the
    verifier returns INSUFFICIENT_EVIDENCE instead of a verdict — which is correct.
    NEVER fabricate a flag to force a check to run.

OUTPUT FORMAT: return ONLY a JSON array. No prose, no markdown, no code fences.
Each element:
  {"claim_text": string,
   "operation": "internal_consistency",
   "rule_name": "balance_sheet_identity" | "eps_reconciliation" | "cash_flow_tie_out",
   "stated_value": null,
   "eps_variant": "basic" | "diluted" | null,
   "operands": [{"value": number|null, "source": "...", "source_text": string|null,
                 "category": string|null}],
   "params": object|null,
   "unit": string|null,
   "source_text": string|null,
   "notes": string|null}

If the document supports NONE of the three rules, return []."""


CROSS_STATEMENT_USER_TEMPLATE = """\
FINANCIAL DOCUMENT (locate and ground the figures here):
\"\"\"
{document}
\"\"\"

Return the JSON array of internal_consistency claims now \
(omit any rule whose required statement is absent)."""


def build_cross_statement_user_prompt(document: str) -> str:
    return CROSS_STATEMENT_USER_TEMPLATE.format(document=document.strip())


def extract_internal_consistency(
    document: str,
    *,
    complete_fn: Optional[CompletionFn] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ExtractionOutput:
    """Extract internal_consistency claims from a single financial document.

    Like extract_claims, this never raises on a bad model response: malformed
    claims become ExtractionIssues; only well-formed claims appear in `.claims`.
    Pass `complete_fn` to run offline (tests/replay); omit for the default backend.
    """
    system_prompt = CROSS_STATEMENT_SYSTEM_PROMPT
    user_prompt = build_cross_statement_user_prompt(document)

    used_provider, used_model = "injected", "injected"
    if complete_fn is None:
        complete_fn, used_provider, used_model = _default_complete_fn(provider, model, max_tokens)

    raw = complete_fn(system_prompt, user_prompt)
    claims, issues = parse_claims(raw)

    # Defensive post-filter enforcing the applicability discipline in code, not
    # just in the prompt: drop any internal_consistency claim whose operands are
    # ALL missing — that's the "doesn't apply" case the model was told to omit,
    # and we refuse to let it leak through as UNSUPPORTED_NUMBER.
    preferred_eps_context = _document_has_preferred_eps_context(document)
    filtered: List[Claim] = []
    for c in claims:
        if c.operation == Operation.INTERNAL_CONSISTENCY and c.operands:
            if all(o.source == OperandSource.MISSING for o in c.operands):
                issues.append(ExtractionIssue(
                    index=None,
                    reason=(f"dropped {c.rule_name}: all operands missing → rule not "
                            f"applicable to this document (omitted, not UNSUPPORTED)"),
                    raw=c.claim_text[:120],
                ))
                continue
            if c.rule_name == "eps_reconciliation" and preferred_eps_context:
                c.params = dict(c.params or {})
                c.params.setdefault("preferred_dividends_present", True)
        filtered.append(c)

    return ExtractionOutput(
        claims=filtered,
        issues=issues,
        raw_response=raw,
        provider=used_provider,
        model=used_model,
    )
