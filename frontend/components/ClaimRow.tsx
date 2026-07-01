"use client";

import * as React from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { ChevronDown, HelpCircle, Info } from "lucide-react";
import type { Result, Operand } from "@/lib/types";
import {
  STATUS_CONFIG,
  OPERAND_SOURCE_STYLE,
  INTERNAL_CONSISTENCY_RULES,
  claimGroup,
  cn,
  fmt,
  prettyOp,
} from "@/lib/utils";
import { StatusBadge } from "./StatusBadge";

// What the recomputation looks like, written out per internal-consistency rule.
function getComputation(
  rule_name: string | null | undefined,
  operands: Operand[],
  recomputed: number | null
): string {
  if (rule_name === "balance_sheet_identity" && operands.length >= 3) {
    return `${fmt(operands[1]?.value)} + ${fmt(operands[2]?.value)} = ${fmt(recomputed)}`;
  }
  if (rule_name === "eps_reconciliation" && operands.length >= 3) {
    return `${fmt(operands[1]?.value)} ÷ ${fmt(operands[2]?.value)} = ${fmt(recomputed)}`;
  }
  if (rule_name === "cash_flow_tie_out" && operands.length >= 2) {
    return `${fmt(operands[1]?.value)} (should equal ${fmt(operands[0]?.value)})`;
  }
  return "—";
}

export function ClaimRow({ result }: { result: Result }) {
  const [open, setOpen] = React.useState(false);
  const reduce = useReducedMotion();
  const cfg = STATUS_CONFIG[result.status];
  const { claim } = result;
  const unit = claim.unit ?? "";
  const group = claimGroup(claim.operation);
  const isInternal = group === "internal_consistency";

  const ruleCfg =
    isInternal && claim.rule_name ? INTERNAL_CONSISTENCY_RULES[claim.rule_name] : undefined;

  const deltaCls =
    result.status === "WRONG_MATH" || result.status === "CONFLICT"
      ? "text-wrong font-semibold"
      : "text-muted";

  // Primary line shown in the collapsed row: rule name for internal checks,
  // friendly operation name otherwise.
  const titleText = isInternal ? ruleCfg?.name ?? "Internal Consistency" : prettyOp(claim.operation);
  // Secondary line: the formula for internal checks, the claim sentence otherwise.
  const subText = isInternal ? ruleCfg?.formula ?? "Document self-check" : claim.claim_text;

  // For internal checks with no stated_value, show the asserted (first operand)
  // figure in the Stated column so the row isn't blank.
  const statedDisplay =
    claim.stated_value !== null
      ? claim.stated_value
      : isInternal && claim.operands[0]
        ? claim.operands[0].value
        : null;

  return (
    <motion.div
      layout={!reduce}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "overflow-hidden rounded-xl border border-border/60 bg-white/[0.015] transition-colors",
        open ? "bg-white/[0.035]" : "hover:bg-white/[0.03]"
      )}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full cursor-pointer px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/50"
      >
        {/* Desktop: aligned columns */}
        <div className="hidden grid-cols-[136px_minmax(0,1fr)_96px_96px_84px_20px] items-center gap-3 sm:grid">
          <StatusBadge status={result.status} />
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <span className="truncate">{titleText}</span>
              <TypeTag group={group} />
            </div>
            <div className="truncate text-xs text-muted">{subText}</div>
          </div>
          <div className="tnum text-right text-sm text-foreground">{fmt(statedDisplay)}</div>
          <div className="tnum text-right text-sm text-foreground">{fmt(result.recomputed_value)}</div>
          <div className={cn("tnum text-right text-sm", deltaCls)}>
            {fmt(result.delta, { sign: true })}
          </div>
          <ChevronDown
            className={cn(
              "h-5 w-5 justify-self-end text-muted transition-transform duration-200",
              open && "rotate-180"
            )}
          />
        </div>

        {/* Mobile: compact */}
        <div className="flex items-center gap-3 sm:hidden">
          <StatusBadge status={result.status} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <span className="truncate">{titleText}</span>
              <TypeTag group={group} />
            </div>
            <div className="truncate text-xs text-muted">{subText}</div>
          </div>
          <ChevronDown
            className={cn("h-5 w-5 shrink-0 text-muted transition-transform duration-200", open && "rotate-180")}
          />
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={reduce ? { opacity: 1 } : { height: "auto", opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{ duration: reduce ? 0.12 : 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className={cn("mx-4 mb-4 border-l-2 pl-4", cfg.accent)}>
              {isInternal && ruleCfg ? (
                <InternalConsistencyDetail result={result} ruleCfg={ruleCfg} />
              ) : (
                <ArithmeticDetail result={result} unit={unit} />
              )}

              {/* The verdict explanation — always shown. */}
              <div className="flex items-start gap-2 rounded-lg bg-white/[0.025] px-3 py-2">
                <cfg.icon className={cn("mt-0.5 h-4 w-4 shrink-0", cfg.text)} />
                <p className="text-xs leading-relaxed text-muted">{result.explanation}</p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/** Small pill labelling the claim type for any non-arithmetic group. */
function TypeTag({ group }: { group: ReturnType<typeof claimGroup> }) {
  if (group === "arithmetic") return null;
  const label =
    group === "internal_consistency"
      ? "Self-check"
      : group === "temporal"
        ? "Temporal"
        : group === "aggregate"
          ? "Aggregate"
          : "Review";
  return (
    <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-primary">
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Internal-consistency detail
// ---------------------------------------------------------------------------

function InternalConsistencyDetail({
  result,
  ruleCfg,
}: {
  result: Result;
  ruleCfg: (typeof INTERNAL_CONSISTENCY_RULES)[string];
}) {
  const { claim } = result;
  const isFail = result.status === "WRONG_MATH";
  const isAmbiguous = result.status === "AMBIGUOUS";

  return (
    <>
      <div className="mb-3 flex items-start gap-1.5">
        <HelpCircle className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
        <p className="text-xs text-muted-foreground">{ruleCfg.checks}</p>
      </div>

      {/* EPS variant, when relevant — the §4 confound, made visible. */}
      {claim.eps_variant && (
        <div className="mb-3 inline-flex items-center gap-1.5 rounded-md bg-white/[0.03] px-2 py-1 text-[10px] text-muted">
          <Info className="h-3 w-3 text-primary" />
          Reconciled against <span className="font-semibold text-foreground">{claim.eps_variant}</span> EPS and the matching share count
        </div>
      )}

      {/* Operands & document location */}
      <div className="mb-4">
        <SectionLabel>Rule operands &amp; location</SectionLabel>
        <div className="space-y-2">
          {claim.operands.map((op, i) => (
            <OperandCard
              key={i}
              op={op}
              label={ruleCfg.operandLabels[i] || `Operand ${i + 1}`}
              structural
            />
          ))}
        </div>
      </div>

      {/* Verification */}
      <div className="mb-4">
        <SectionLabel>Verification</SectionLabel>
        <div className="max-w-xl space-y-2 rounded-lg border border-white/[0.03] bg-white/[0.02] p-3 text-xs">
          <KV k="Check" v={<span className="font-semibold text-foreground">{ruleCfg.formula}</span>} />
          <KV k="Tolerance" v={<span className="text-muted">{ruleCfg.tolerance}</span>} />
          <KV
            k="Computation"
            v={<span className="font-mono text-foreground">{getComputation(claim.rule_name, claim.operands, result.recomputed_value)}</span>}
          />
          <div className="mt-2 space-y-1 border-t border-white/[0.04] pt-2">
            <KV k={ruleCfg.actualLabel} v={<span className="font-mono text-foreground">{fmt(getActual(result))}</span>} />
            <KV k={ruleCfg.expectedLabel} v={<span className="font-mono text-foreground">{fmt(result.recomputed_value)}</span>} />
            {isFail && (
              <div className="mt-1 flex justify-between border-t border-dashed border-white/[0.04] pt-1 font-semibold text-wrong">
                <span>Discrepancy</span>
                <span>{fmt(result.delta, { sign: true })}</span>
              </div>
            )}
            {isAmbiguous && (
              <div className="mt-1 flex items-start gap-1.5 border-t border-dashed border-white/[0.04] pt-1.5 text-ambiguous">
                <span className="text-[10px] leading-relaxed">
                  Flagged ambiguous rather than wrong — e.g. a basic/diluted EPS or
                  GAAP/non-GAAP mismatch the comparison can't fairly resolve.
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

/** The value the rule compares against the computed side (the "actual"). */
function getActual(result: Result): number | null {
  // For all three rules the "actual" is the first operand (stated assets /
  // stated EPS / cash-flow ending cash).
  return result.claim.operands[0]?.value ?? result.claim.stated_value ?? null;
}

// ---------------------------------------------------------------------------
// Arithmetic / temporal / aggregate / definitional detail
// ---------------------------------------------------------------------------

function ArithmeticDetail({ result, unit }: { result: Result; unit: string }) {
  const { claim } = result;
  const hasCategoryInferred = claim.operands.some((o) => o.source === "category_inferred");

  return (
    <>
      <p className="mb-3 text-sm leading-relaxed text-foreground">&ldquo;{claim.claim_text}&rdquo;</p>

      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <Metric label="Stated" value={`${fmt(claim.stated_value)}${unit ? ` ${unit}` : ""}`} />
        <Metric
          label="Recomputed"
          value={
            result.recomputed_value === null
              ? "—"
              : `${fmt(result.recomputed_value)}${unit ? ` ${unit}` : ""}`
          }
          highlight={result.status === "WRONG_MATH"}
        />
        <Metric label="Δ" value={fmt(result.delta, { sign: true })} highlight={result.status === "WRONG_MATH"} />
      </div>

      {hasCategoryInferred && (
        <div className="mb-3 flex items-start gap-1.5 rounded-md bg-ambiguous/[0.06] px-2 py-1.5 text-[10px] text-ambiguous">
          <Info className="mt-px h-3 w-3 shrink-0" />
          One or more operands were grouped by an inferred category — this verdict is
          conditional on the categorization being correct.
        </div>
      )}

      {claim.operands.length > 0 && (
        <div className="mb-4">
          <SectionLabel>Operands &amp; provenance</SectionLabel>
          <div className="space-y-1.5">
            {claim.operands.map((op, i) => (
              <OperandCard key={i} op={op} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Shared operand card — handles every provenance type and optional doc_id.
// ---------------------------------------------------------------------------

function OperandCard({
  op,
  label,
  structural,
}: {
  op: Operand;
  label?: string;
  structural?: boolean;
}) {
  const src = OPERAND_SOURCE_STYLE[op.source] ?? OPERAND_SOURCE_STYLE.missing;
  const isMissing = op.source === "missing";

  // The "where it came from" line adapts to provenance:
  //  - missing          -> not located
  //  - category_inferred -> show the inferred category
  //  - everything else   -> the grounded source text / location
  const locationText = isMissing
    ? structural
      ? "not located in document"
      : "not located in source document"
    : op.source === "category_inferred" && op.category
      ? `category: ${op.category}`
      : op.source_text
        ? structural
          ? `Location: ${op.source_text}`
          : `“${op.source_text}”`
        : "—";

  if (structural) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/[0.03] bg-white/[0.015] px-3 py-2">
        <div className="min-w-[120px]">
          <div className="text-xs font-semibold text-foreground">{label}</div>
          <div className="mt-0.5 max-w-sm truncate font-mono text-[10px] text-muted-foreground">
            {locationText}
            {op.doc_id ? ` · ${op.doc_id}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="tnum text-sm font-semibold text-foreground">
            {isMissing ? "—" : fmt(op.value)}
          </span>
          <span className={cn("rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide", src.cls)}>
            {src.label}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg bg-white/[0.025] px-3 py-2">
      <span className="tnum text-sm font-medium text-foreground">{isMissing ? "—" : fmt(op.value)}</span>
      <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", src.cls)}>{src.label}</span>
      <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">
        {locationText}
        {op.doc_id ? ` · ${op.doc_id}` : ""}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2 border-b border-white/[0.04] pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">
      {children}
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted">{k}</span>
      {v}
    </div>
  );
}

function Metric({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-[11px] uppercase tracking-wider text-muted">{label}</span>
      <span className={cn("tnum font-mono text-sm", highlight ? "font-semibold text-wrong" : "text-foreground")}>
        {value}
      </span>
    </div>
  );
}
