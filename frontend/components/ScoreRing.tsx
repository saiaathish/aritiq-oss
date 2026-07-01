"use client";

import * as React from "react";
import { motion, animate, useReducedMotion } from "framer-motion";
import type { Score, Result } from "@/lib/types";
import { scoreColor, claimGroup, GROUP_META, cn, type ClaimGroup } from "@/lib/utils";

const SIZE = 184;
const STROKE = 12;
const R = (SIZE - STROKE) / 2;
const C = 2 * Math.PI * R;

// The status rows shown inside each group card, in display order.
const STATUS_ROWS: { key: string; label: string; color: string; symbol: string }[] = [
  { key: "VERIFIED", label: "Verified", color: "text-verified", symbol: "✓" },
  { key: "WRONG_MATH", label: "Wrong math", color: "text-wrong", symbol: "✗" },
  { key: "CONFLICT", label: "Conflict", color: "text-wrong", symbol: "✗" },
  { key: "AMBIGUOUS", label: "Ambiguous", color: "text-ambiguous", symbol: "?" },
  { key: "UNSUPPORTED_NUMBER", label: "Unsupported", color: "text-muted", symbol: "—" },
  { key: "NEEDS_REVIEW", label: "Needs review", color: "text-ambiguous", symbol: "⌕" },
  { key: "UNCHECKED", label: "Unchecked", color: "text-muted", symbol: "—" },
];

export function ScoreRing({ score, results }: { score: Score; results?: Result[] }) {
  const reduce = useReducedMotion();
  const value = Math.max(0, Math.min(100, score.score));
  const { ring, text, glow, label } = scoreColor(value);

  const [display, setDisplay] = React.useState(reduce ? value : 0);
  const decimals = Number.isInteger(value) ? 0 : 1;

  React.useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    const controls = animate(0, value, {
      duration: 1.1,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [value, reduce]);

  const resultsList = results || [];

  // Build per-group, per-status counts straight from the results that exist.
  // Only groups that actually have claims are rendered — no guessed N/A noise.
  const groups = React.useMemo(() => {
    const acc = new Map<ClaimGroup, Map<string, number>>();
    for (const r of resultsList) {
      const g = claimGroup(r.claim.operation);
      if (!acc.has(g)) acc.set(g, new Map());
      const m = acc.get(g)!;
      m.set(r.status, (m.get(r.status) ?? 0) + 1);
    }
    return Array.from(acc.entries()).sort(
      (a, b) => GROUP_META[a[0]].order - GROUP_META[b[0]].order
    );
  }, [resultsList]);

  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-start sm:gap-8">
      <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
        <div
          aria-hidden
          className="absolute inset-0 rounded-full"
          style={{ boxShadow: `0 0 60px ${glow}`, opacity: 0.6 }}
        />
        <svg
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="-rotate-90"
          role="img"
          aria-label={`Aritiq score ${value} out of 100`}
        >
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={R}
            fill="none"
            stroke="rgba(255,255,255,0.08)"
            strokeWidth={STROKE}
          />
          <motion.circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={R}
            fill="none"
            stroke={ring}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={C}
            initial={{ strokeDashoffset: C }}
            animate={{ strokeDashoffset: C - (C * value) / 100 }}
            transition={{ duration: reduce ? 0 : 1.2, ease: [0.16, 1, 0.3, 1] }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("tnum text-5xl font-bold tracking-tight", text)}>
            {display.toFixed(decimals)}
          </span>
          <span className="mt-0.5 text-xs font-medium uppercase tracking-[0.18em] text-muted">
            / 100
          </span>
        </div>
      </div>

      <div className="flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className={cn("text-lg font-semibold", text)}>{label}</span>
          <span className="text-sm text-muted">Aritiq Score</span>
          {typeof score.unweighted_score === "number" &&
            score.unweighted_score !== score.score && (
              <span className="rounded-full bg-white/[0.04] px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted">
                Weighted {score.score} · Unweighted {score.unweighted_score}
              </span>
            )}
        </div>
        <p className="mb-4 max-w-md text-sm text-muted">
          {score.total_checkable} checkable claim{score.total_checkable === 1 ? "" : "s"}.
          Score = share of checkable claims that hold up, weighted so a confidently-wrong
          number costs the most. Items routed to human review are excluded.
        </p>

        {/* Per-type breakdown — only groups that are present are shown. */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 max-w-xl">
          {groups.map(([group, counts]) => {
            const meta = GROUP_META[group];
            const rows = STATUS_ROWS.filter((s) => (counts.get(s.key) ?? 0) > 0);
            const total = Array.from(counts.values()).reduce((a, b) => a + b, 0);
            const isP2 = group !== "arithmetic";
            return (
              <div
                key={group}
                className="rounded-xl bg-white/[0.02] p-3 border border-white/[0.04]"
              >
                <div
                  className={cn(
                    "mb-2 flex items-center justify-between gap-2 border-b border-white/[0.04] pb-1 text-[10px] font-bold uppercase tracking-wider",
                    isP2 ? "text-primary" : "text-muted"
                  )}
                >
                  <span className="truncate" title={meta.blurb}>{meta.title}</span>
                  <span
                    className={cn(
                      "shrink-0 font-normal normal-case text-[9px]",
                      isP2 ? "text-primary/60" : "text-muted-foreground"
                    )}
                  >
                    {total}
                  </span>
                </div>
                <div className="space-y-1.5">
                  {rows.map((s) => (
                    <RowStat
                      key={s.key}
                      label={s.label}
                      count={counts.get(s.key) ?? 0}
                      color={s.color}
                      symbol={s.symbol}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {groups.some(([g]) => g === "internal_consistency") && (
          <div className="mt-3 flex max-w-xl items-start gap-1.5 text-[10px] leading-relaxed text-muted-foreground">
            <span className="font-bold text-primary">ℹ</span>
            <span>
              Internal-consistency verdicts use a tighter tolerance and check the
              document's own coherence — they don't depend on LLM extraction being
              correct, which makes them a stronger signal than arithmetic claims.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function RowStat({
  label,
  count,
  color,
  symbol,
}: {
  label: string;
  count: number;
  color: string;
  symbol: string;
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <div className="flex items-center gap-1.5 text-muted-foreground">
        <span className={cn("flex w-3 justify-center font-mono text-[10px] font-semibold", color)}>
          {symbol}
        </span>
        <span>{label}</span>
      </div>
      <span className={cn("tnum font-bold", count > 0 ? "text-foreground" : "text-muted-foreground/45")}>
        {count}
      </span>
    </div>
  );
}
