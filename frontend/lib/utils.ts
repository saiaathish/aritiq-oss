import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  HelpCircle,
  MinusCircle,
  type LucideIcon,
} from "lucide-react";
import type { Status } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export interface StatusStyle {
  label: string;
  icon: LucideIcon;
  /** foreground text/icon color */
  text: string;
  /** translucent chip background */
  chip: string;
  /** small status dot */
  dot: string;
  /** left accent border for expanded rows */
  accent: string;
  italic?: boolean;
  bold?: boolean;
}

export const STATUS_CONFIG: Record<Status, StatusStyle> = {
  VERIFIED: {
    label: "Verified",
    icon: CheckCircle2,
    text: "text-verified",
    chip: "bg-verified/10 text-verified ring-1 ring-inset ring-verified/25",
    dot: "bg-verified",
    accent: "border-l-verified",
  },
  WRONG_MATH: {
    label: "Wrong math",
    icon: XCircle,
    text: "text-wrong",
    chip: "bg-wrong/10 text-wrong ring-1 ring-inset ring-wrong/30",
    dot: "bg-wrong-strong",
    accent: "border-l-wrong-strong",
    bold: true,
  },
  UNSUPPORTED_NUMBER: {
    label: "Unsupported",
    icon: AlertTriangle,
    text: "text-unsupported",
    chip: "bg-unsupported/10 text-unsupported ring-1 ring-inset ring-unsupported/25",
    dot: "bg-unsupported",
    accent: "border-l-unsupported",
  },
  AMBIGUOUS: {
    label: "Ambiguous",
    icon: HelpCircle,
    text: "text-ambiguous",
    chip: "bg-ambiguous/10 text-ambiguous ring-1 ring-inset ring-ambiguous/25",
    dot: "bg-ambiguous",
    accent: "border-l-ambiguous",
  },
  UNCHECKED: {
    label: "Unchecked",
    icon: MinusCircle,
    text: "text-unchecked",
    chip: "bg-unchecked/10 text-unchecked ring-1 ring-inset ring-unchecked/20",
    dot: "bg-unchecked",
    accent: "border-l-unchecked",
    italic: true,
  },
  // ---- Phase 2 statuses ----
  // A vague word next to a number, routed to a human. Styled like UNCHECKED
  // (excluded from the score) but with the help icon to read as "look at this".
  NEEDS_REVIEW: {
    label: "Needs review",
    icon: HelpCircle,
    text: "text-ambiguous",
    chip: "bg-ambiguous/10 text-ambiguous ring-1 ring-inset ring-ambiguous/25",
    dot: "bg-ambiguous",
    accent: "border-l-ambiguous",
    italic: true,
  },
  // Two source documents disagree on the same figure — a red flag, styled
  // like WRONG_MATH because the reader should treat it as one.
  CONFLICT: {
    label: "Conflict",
    icon: XCircle,
    text: "text-wrong",
    chip: "bg-wrong/10 text-wrong ring-1 ring-inset ring-wrong/30",
    dot: "bg-wrong-strong",
    accent: "border-l-wrong-strong",
    bold: true,
  },
  // ---- Phase 3 status ----
  // Not independently broken — a consequence of an upstream failed claim.
  // Styled like UNSUPPORTED (a softer amber): it's a flag, but the reader should
  // chase the ROOT (caused_by), not this row. Excluded from the score.
  PROPAGATED_ERROR: {
    label: "Propagated",
    icon: AlertTriangle,
    text: "text-orange-300",
    chip: "bg-orange-400/10 text-orange-300 ring-1 ring-inset ring-orange-400/30",
    dot: "bg-orange-400",
    accent: "border-l-orange-400",
    italic: true,
  },
  INSUFFICIENT_EVIDENCE: {
    label: "Insufficient evidence",
    icon: HelpCircle,
    text: "text-amber-300",
    chip: "bg-amber-300/10 text-amber-300 ring-1 ring-inset ring-amber-300/30",
    dot: "bg-unsupported",
    accent: "border-l-unsupported",
    italic: true,
  },
};

export const OPERAND_SOURCE_STYLE: Record<
  string,
  { label: string; cls: string }
> = {
  grounded: {
    label: "grounded",
    cls: "bg-verified/10 text-verified ring-1 ring-inset ring-verified/25",
  },
  grounded_prose: {
    label: "grounded (prose)",
    cls: "bg-verified/10 text-verified ring-1 ring-inset ring-verified/25",
  },
  grounded_table_cell: {
    label: "grounded (table)",
    cls: "bg-verified/10 text-verified ring-1 ring-inset ring-verified/25",
  },
  grounded_cross_document: {
    label: "cross-document",
    cls: "bg-indigo-500/10 text-indigo-400 ring-1 ring-inset ring-indigo-500/25",
  },
  inferred: {
    label: "inferred",
    cls: "bg-ambiguous/10 text-ambiguous ring-1 ring-inset ring-ambiguous/25",
  },
  category_inferred: {
    label: "category inferred",
    cls: "bg-ambiguous/10 text-ambiguous ring-1 ring-inset ring-ambiguous/25",
  },
  missing: {
    label: "missing",
    cls: "bg-wrong/10 text-wrong ring-1 ring-inset ring-wrong/30",
  },
};

/** Format a numeric value for display with tabular figures; null -> em dash. */
export function fmt(n: number | null | undefined, opts?: { sign?: boolean }): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  // Trim to at most 4 decimals, drop trailing zeros, keep integers clean.
  let s =
    Number.isInteger(n)
      ? n.toString()
      : abs >= 1000
        ? n.toLocaleString("en-US", { maximumFractionDigits: 2 })
        : parseFloat(n.toFixed(4)).toString();
  if (opts?.sign && n > 0) s = `+${s}`;
  return s;
}

/** Friendly display name for an operation enum.
 *  Phase 2 operations get hand-written labels; everything else is title-cased. */
const OP_LABELS: Record<string, string> = {
  percent_change: "Percent change",
  absolute_change: "Absolute change",
  margin_percent: "Margin %",
  internal_consistency: "Internal consistency",
  trend_direction: "Trend direction",
  superlative: "Superlative",
  consecutive_count: "Consecutive count",
  aggregate_filter: "Aggregate filter",
  definitional_flag: "Definitional flag",
};

export function prettyOp(op: string): string {
  if (!op) return "—";
  if (OP_LABELS[op]) return OP_LABELS[op];
  const s = op.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// Claim-type taxonomy — single source of truth for how claims are grouped and
// labelled across every component. Adding a new operation here is the ONLY
// place a section header or grouping needs to change.
// ---------------------------------------------------------------------------

export type ClaimGroup =
  | "internal_consistency"
  | "temporal"
  | "aggregate"
  | "definitional"
  | "arithmetic";

/** Map an operation string to its display group. */
export function claimGroup(op: string): ClaimGroup {
  switch (op) {
    case "internal_consistency":
      return "internal_consistency";
    case "trend_direction":
    case "superlative":
    case "consecutive_count":
      return "temporal";
    case "aggregate_filter":
      return "aggregate";
    case "definitional_flag":
      return "definitional";
    default:
      return "arithmetic";
  }
}

export interface GroupMeta {
  /** Section header shown in the claims list and score breakdown. */
  title: string;
  /** Short phase / nature tag. */
  tag: string;
  /** One-line description for tooltips. */
  blurb: string;
  /** Display order — internal-consistency first ("good news" structural checks). */
  order: number;
}

export const GROUP_META: Record<ClaimGroup, GroupMeta> = {
  internal_consistency: {
    title: "Internal Consistency Checks",
    tag: "Phase 2 · structural",
    blurb:
      "Checks whether a document's own numbers agree with each other (e.g. the balance sheet balances). Structural checks with tight tolerance — they don't depend on LLM extraction accuracy.",
    order: 0,
  },
  temporal: {
    title: "Temporal Consistency",
    tag: "Phase 2 · time series",
    blurb:
      "Checks an asserted trend, superlative, or streak over an ordered series of periods — pure comparison over the sequence.",
    order: 1,
  },
  aggregate: {
    title: "Aggregate Checks",
    tag: "Phase 2 · B2C",
    blurb:
      "Sums or counts a filtered subset (e.g. dining transactions), then composes into a percent-change. Categorization is flagged where the category was inferred.",
    order: 2,
  },
  definitional: {
    title: "Flagged for Review",
    tag: "Phase 2 · human review",
    blurb:
      "A vague word (“flat”, “stable”) sits next to a number. There's no universal numeric threshold, so Aritiq routes it to a human instead of inventing a cutoff.",
    order: 3,
  },
  arithmetic: {
    title: "Arithmetic Claims",
    tag: "Phase 1",
    blurb:
      "Derived-number claims (growth, margins, ratios) traced to source numbers and re-computed deterministically.",
    order: 4,
  },
};

/** Rule metadata for internal_consistency claims — formulas, labels, tolerance. */
export interface RuleMeta {
  name: string;
  formula: string;
  /** Label for the value the rule compares AGAINST the computed side. */
  actualLabel: string;
  /** Label for the computed/expected side. */
  expectedLabel: string;
  tolerance: string;
  operandLabels: string[];
  /** Human sentence of what it checks, for tooltips. */
  checks: string;
}

export const INTERNAL_CONSISTENCY_RULES: Record<string, RuleMeta> = {
  balance_sheet_identity: {
    name: "Balance Sheet Identity",
    formula: "Assets = Liabilities + Equity",
    actualLabel: "Stated total assets",
    expectedLabel: "Liabilities + Equity",
    tolerance: "0.1% relative",
    operandLabels: ["Total Assets", "Total Liabilities", "Total Equity"],
    checks: "Total Assets should equal Total Liabilities + Total Equity — a fundamental accounting identity.",
  },
  eps_reconciliation: {
    name: "EPS Reconciliation",
    formula: "EPS = Net Income / Shares",
    actualLabel: "Stated EPS",
    expectedLabel: "Net Income / Shares",
    tolerance: "0.5¢ absolute",
    operandLabels: ["Stated EPS", "Net Income", "Shares Outstanding"],
    checks: "Stated EPS should equal Net Income divided by the matching share count (basic or diluted).",
  },
  cash_flow_tie_out: {
    name: "Cash Flow Tie-Out",
    formula: "Cash-flow ending cash = Balance-sheet cash",
    actualLabel: "Cash-flow ending cash",
    expectedLabel: "Balance-sheet cash",
    tolerance: "0.01% relative",
    operandLabels: ["Statement Ending Cash", "Balance Sheet Cash"],
    checks: "The cash-flow statement's ending cash should be the literal same figure as the balance sheet's cash line.",
  },
};

export const ALL_RULE_NAMES = [
  "balance_sheet_identity",
  "eps_reconciliation",
  "cash_flow_tie_out",
] as const;

export function scoreColor(score: number): {
  ring: string;
  text: string;
  glow: string;
  label: string;
} {
  if (score >= 80)
    return { ring: "#34D399", text: "text-verified", glow: "rgba(52,211,153,0.35)", label: "Trustworthy" };
  if (score >= 50)
    return { ring: "#FBBF24", text: "text-unsupported", glow: "rgba(251,191,36,0.35)", label: "Mixed" };
  return { ring: "#F87171", text: "text-wrong", glow: "rgba(248,113,113,0.4)", label: "Unreliable" };
}
