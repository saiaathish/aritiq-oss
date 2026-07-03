"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { ListChecks, AlertCircle, ChevronRight } from "lucide-react";
import type { Result } from "@/lib/types";
import {
  claimGroup,
  GROUP_META,
  INTERNAL_CONSISTENCY_RULES,
  ALL_RULE_NAMES,
  type ClaimGroup,
} from "@/lib/utils";
import { ClaimRow } from "./ClaimRow";

export function ClaimsTable({ results }: { results: Result[] }) {
  const reduce = useReducedMotion();
  const [showNA, setShowNA] = React.useState(false);

  // Group results by claim type, preserving order within each group.
  const grouped = React.useMemo(() => {
    const acc = new Map<ClaimGroup, Result[]>();
    results.forEach((r) => {
      const g = claimGroup(r.claim.operation);
      if (!acc.has(g)) acc.set(g, []);
      acc.get(g)!.push(r);
    });
    return Array.from(acc.entries()).sort(
      (a, b) => GROUP_META[a[0]].order - GROUP_META[b[0]].order
    );
  }, [results]);

  // "Not applicable" internal-consistency rules: only meaningful when AT LEAST
  // ONE internal-consistency check ran (i.e. the document had statements to
  // check). If no internal checks ran at all, the document type simply doesn't
  // support them — we don't clutter the view with three N/A rows.
  const internalResults = grouped.find(([g]) => g === "internal_consistency")?.[1] ?? [];
  const presentRules = new Set(internalResults.map((r) => r.claim.rule_name));
  const missingRules =
    internalResults.length > 0
      ? ALL_RULE_NAMES.filter((rule) => !presentRules.has(rule))
      : [];

  // Running index so row-entry animations stagger across the whole list.
  let runningIndex = 0;

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
          <ListChecks className="h-4 w-4 text-primary" />
          Per-claim trace
          <span className="text-xs font-normal text-muted">
            ({results.length} claim{results.length === 1 ? "" : "s"} — click any row to inspect)
          </span>
        </div>

        {/* Column header (desktop only) */}
        <div className="mb-1.5 hidden grid-cols-[136px_minmax(0,1fr)_96px_96px_84px_20px] items-center gap-3 px-4 text-[10px] font-semibold uppercase tracking-wider text-muted sm:grid">
          <span>Status</span>
          <span>Operation / claim</span>
          <span className="text-right">Stated</span>
          <span className="text-right">Recomputed</span>
          <span className="text-right">Δ</span>
          <span />
        </div>
      </div>

      {grouped.map(([group, groupResults]) => {
        const meta = GROUP_META[group];
        const isP2 = group !== "arithmetic";
        return (
          <div key={group} className="space-y-2">
            <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] pb-1.5">
              <span
                className={`text-xs font-bold uppercase tracking-wider ${
                  isP2 ? "text-primary" : "text-muted"
                }`}
                title={meta.blurb}
              >
                {meta.title}
              </span>
              <span className="shrink-0 text-[10px] text-muted">
                {group === "internal_consistency"
                  ? `${groupResults.length} rule${groupResults.length === 1 ? "" : "s"} checked`
                  : `${groupResults.length} claim${groupResults.length === 1 ? "" : "s"}`}
              </span>
            </div>

            <div className="space-y-2">
              {groupResults.map((r) => {
                const idx = runningIndex++;
                return (
                  <motion.div
                    key={`${group}-${idx}`}
                    initial={reduce ? { opacity: 0 } : { opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      delay: reduce ? 0 : idx * 0.04,
                      duration: 0.3,
                      ease: [0.16, 1, 0.3, 1],
                    }}
                  >
                    <ClaimRow result={r} />
                  </motion.div>
                );
              })}
            </div>

            {/* N/A internal-consistency rules — only when some checks ran. */}
            {group === "internal_consistency" && missingRules.length > 0 && (
              <div className="mt-1">
                <button
                  onClick={() => setShowNA((o) => !o)}
                  className="flex cursor-pointer items-center gap-1.5 text-[10px] font-medium text-muted transition-colors hover:text-foreground"
                >
                  <ChevronRight className={`h-3 w-3 transition-transform ${showNA ? "rotate-90" : ""}`} />
                  Not applicable to this document ({missingRules.length})
                </button>
                {showNA && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    className="mt-1.5 space-y-1 pl-4"
                  >
                    {missingRules.map((rule) => (
                      <div key={rule} className="flex items-center gap-2 text-[10px] text-muted-foreground">
                        <AlertCircle className="h-3 w-3 text-muted-foreground/60" />
                        <span>{INTERNAL_CONSISTENCY_RULES[rule]?.name ?? rule}</span>
                        <span className="rounded bg-white/[0.04] px-1 text-[8px] uppercase">N/A</span>
                      </div>
                    ))}
                  </motion.div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
