"use client";

/**
 * RiskDashboard — Phase 3 item 2.
 *
 * Five deterministic panels over numbers that already exist upstream
 * (core/score.py, core/restatement.py, company_memory gates, evidence flags).
 * The honesty rule this component enforces: a panel with nothing to measure
 * renders its UNASSESSED / NO DATA state — it never paints a clean-looking
 * number over an absence of evidence. Restatement risk on a single filing is
 * always UNASSESSED, and the boundary line ships with the data.
 */

import type { RiskDashboard as RiskDashboardData, DashboardPanel } from "@/lib/types";
import { cn } from "@/lib/utils";

function valueTone(p: DashboardPanel): string {
  if (p.state !== "ok" || p.value === null) return "text-zinc-500";
  if (p.value >= 90) return "text-emerald-400";
  if (p.value >= 60) return "text-amber-400";
  return "text-red-400";
}

function PanelCard({ panel }: { panel: DashboardPanel }) {
  const showNumber = panel.state === "ok" && panel.value !== null;
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold text-zinc-300">{panel.title}</h4>
        <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[9px] uppercase tracking-wide text-zinc-500">
          {panel.basis}
        </span>
      </div>

      {showNumber ? (
        <div className={cn("text-3xl font-bold tabular-nums", valueTone(panel))}>
          {panel.value}
          <span className="text-sm font-normal text-zinc-500"> /100</span>
        </div>
      ) : (
        <div className="text-lg font-semibold uppercase tracking-wide text-zinc-500">
          {panel.state === "unassessed" ? "Unassessed" : panel.state === "no_data" ? "No data" : "—"}
        </div>
      )}

      {/* Restatement panel: counts, never a fabricated score */}
      {panel.key === "restatement_risk" && panel.state === "ok" && (
        <div className="text-xs text-zinc-400">
          {String(panel.components["conflicts"] ?? 0)} conflict(s)
          {Number(panel.components["UNEXPLAINED"] ?? 0) > 0 && (
            <span className="ml-2 text-red-400 font-medium">
              {String(panel.components["UNEXPLAINED"])} unexplained
            </span>
          )}
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-zinc-500">{panel.detail}</p>
    </div>
  );
}

export function RiskDashboard({ dashboard }: { dashboard: RiskDashboardData }) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-zinc-200">
        Institutional risk dashboard — {dashboard.ticker}
      </h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {dashboard.panels.map((p) => (
          <PanelCard key={p.key} panel={p} />
        ))}
      </div>
      <p className="text-[11px] text-zinc-500 border-t border-zinc-800 pt-3">
        {dashboard.boundary}
      </p>
    </div>
  );
}
