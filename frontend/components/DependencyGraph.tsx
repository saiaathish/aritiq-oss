"use client";

import * as React from "react";
import {
  ArrowRight,
  GitBranch,
  Link2,
  type LucideIcon,
} from "lucide-react";
import type { Result, Status } from "@/lib/types";
import { cn, fmt, STATUS_CONFIG } from "@/lib/utils";
import { StatusBadge } from "./StatusBadge";
import { Card } from "./ui/card";

const NODE_H = 92;
const NODE_GAP = 16;
const NODE_Y = NODE_H + NODE_GAP;

type Node = {
  id: string;
  result: Result;
  index: number;
  deps: string[];
};

const NODE_STYLE: Record<Status, string> = {
  VERIFIED: "border-verified/35 bg-verified/[0.06]",
  WRONG_MATH: "border-wrong/45 bg-wrong/[0.07]",
  INSUFFICIENT_EVIDENCE: "border-unsupported/45 bg-unsupported/[0.08]",
  UNSUPPORTED_NUMBER: "border-unchecked/45 bg-white/[0.03]",
  AMBIGUOUS: "border-ambiguous/40 bg-ambiguous/[0.06]",
  UNCHECKED: "border-unchecked/35 bg-white/[0.025]",
  NEEDS_REVIEW: "border-ambiguous/40 bg-ambiguous/[0.06]",
  CONFLICT: "border-wrong/45 bg-wrong/[0.07]",
  PROPAGATED_ERROR: "border-orange-400/55 bg-orange-400/[0.09]",
};

const EDGE_STYLE: Record<Status, string> = {
  VERIFIED: "#34D399",
  WRONG_MATH: "#F87171",
  INSUFFICIENT_EVIDENCE: "#FBBF24",
  UNSUPPORTED_NUMBER: "#8A98B2",
  AMBIGUOUS: "#60A5FA",
  UNCHECKED: "#8A98B2",
  NEEDS_REVIEW: "#60A5FA",
  CONFLICT: "#EF4444",
  PROPAGATED_ERROR: "#FB923C",
};

function nodeId(result: Result, index: number) {
  return result.claim.node_id || `claim-${index + 1}`;
}

function shortText(result: Result) {
  return result.claim.claim_text || result.claim.rule_name || result.claim.operation;
}

function operationLabel(result: Result) {
  if (result.claim.rule_name) return result.claim.rule_name.replaceAll("_", " ");
  return result.claim.operation.replaceAll("_", " ");
}

export function DependencyGraph({ results }: { results: Result[] }) {
  const nodes = React.useMemo<Node[]>(
    () =>
      results.map((result, index) => ({
        id: nodeId(result, index),
        result,
        index,
        deps: result.claim.depends_on ?? [],
      })),
    [results]
  );

  const byId = React.useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const edges = React.useMemo(
    () =>
      nodes.flatMap((target) =>
        target.deps
          .map((dep) => {
            const source = byId.get(dep);
            return source ? { source, target } : null;
          })
          .filter(Boolean) as { source: Node; target: Node }[]
      ),
    [byId, nodes]
  );

  const [selectedId, setSelectedId] = React.useState(nodes[0]?.id ?? "");
  React.useEffect(() => {
    if (nodes.length && !byId.has(selectedId)) setSelectedId(nodes[0].id);
  }, [byId, nodes, selectedId]);

  const selected = byId.get(selectedId) ?? nodes[0];
  const height = Math.max(180, nodes.length * NODE_Y - NODE_GAP);
  const hasEdges = edges.length > 0;

  return (
    <Card className="overflow-hidden p-5 sm:p-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/12 ring-1 ring-inset ring-primary/25">
              <GitBranch className="h-4 w-4 text-primary" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">Dependency graph</h2>
              <p className="mt-0.5 text-xs text-muted">
                Claims are nodes. Arrows show derived claims depending on upstream claims.
              </p>
            </div>
          </div>
        </div>
        <div className="rounded-full border border-white/[0.06] bg-white/[0.03] px-3 py-1 text-[11px] text-muted">
          {nodes.length} nodes · {edges.length} edges
        </div>
      </div>

      {!hasEdges && (
        <div className="mb-4 rounded-lg border border-white/[0.05] bg-white/[0.025] px-3 py-2 text-xs text-muted">
          No dependencies were emitted for this audit. Nodes still show verdict distribution.
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="relative overflow-x-auto rounded-xl border border-white/[0.05] bg-background/35 p-3">
          <div className="relative min-w-[520px]" style={{ height }}>
            <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
              <defs>
                <marker id="dependency-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                  <path d="M0,0 L8,4 L0,8 Z" fill="#8A98B2" />
                </marker>
              </defs>
              {edges.map(({ source, target }) => {
                const y1 = source.index * NODE_Y + NODE_H / 2;
                const y2 = target.index * NODE_Y + NODE_H / 2;
                const active = selected?.id === source.id || selected?.id === target.id;
                const color = EDGE_STYLE[target.result.status];
                return (
                  <path
                    key={`${source.id}->${target.id}`}
                    d={`M 52 ${y1} C 18 ${y1}, 18 ${y2}, 52 ${y2}`}
                    fill="none"
                    stroke={color}
                    strokeOpacity={active ? 0.95 : 0.45}
                    strokeWidth={active ? 2.5 : 1.5}
                    markerEnd="url(#dependency-arrow)"
                  />
                );
              })}
            </svg>

            <div className="absolute inset-y-0 left-[51px] w-px bg-white/[0.04]" />

            {nodes.map((node) => {
              const cfg = STATUS_CONFIG[node.result.status];
              const Icon = cfg.icon as LucideIcon;
              const isSelected = selected?.id === node.id;
              return (
                <button
                  key={node.id}
                  type="button"
                  onClick={() => setSelectedId(node.id)}
                  className={cn(
                    "absolute left-16 right-2 flex h-[92px] min-w-0 items-start gap-3 rounded-xl border p-3 text-left transition",
                    NODE_STYLE[node.result.status],
                    isSelected ? "ring-2 ring-primary/45" : "hover:border-white/25"
                  )}
                  style={{ top: node.index * NODE_Y }}
                >
                  <span className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", cfg.chip)}>
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">{operationLabel(node.result)}</span>
                      {node.deps.length > 0 && (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-white/[0.05] px-2 py-0.5 text-[10px] text-muted">
                          <Link2 className="h-3 w-3" />
                          {node.deps.length}
                        </span>
                      )}
                    </span>
                    <span className="mt-1 block line-clamp-2 text-xs leading-relaxed text-muted">
                      {shortText(node.result)}
                    </span>
                  </span>
                  {node.result.status === "PROPAGATED_ERROR" && (
                    <span className="shrink-0 rounded-full bg-orange-400/15 px-2 py-1 text-[10px] font-semibold text-orange-300">
                      upstream
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {selected && (
          <GraphDetail
            node={selected}
            byId={byId}
            onSelect={setSelectedId}
          />
        )}
      </div>
    </Card>
  );
}

function GraphDetail({
  node,
  byId,
  onSelect,
}: {
  node: Node;
  byId: Map<string, Node>;
  onSelect: (id: string) => void;
}) {
  const { result } = node;
  const upstream = node.deps.map((id) => byId.get(id)).filter(Boolean) as Node[];
  const causedBy = result.caused_by ? byId.get(result.caused_by) : null;

  return (
    <aside className="rounded-xl border border-white/[0.06] bg-white/[0.025] p-4">
      <div className="flex items-center justify-between gap-3">
        <StatusBadge status={result.status} />
        <span className="font-mono text-[10px] text-muted">{node.id}</span>
      </div>

      <h3 className="mt-4 text-sm font-semibold text-foreground">{operationLabel(result)}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted">{shortText(result)}</p>

      {result.status === "PROPAGATED_ERROR" && (
        <div className="mt-4 rounded-lg border border-orange-400/25 bg-orange-400/[0.08] p-3 text-xs text-orange-100">
          This claim is not independently wrong. It depends on an upstream failed claim.
          {causedBy && (
            <button
              type="button"
              onClick={() => onSelect(causedBy.id)}
              className="mt-2 flex items-center gap-1 font-semibold text-orange-200 hover:text-orange-100"
            >
              Jump to cause: {operationLabel(causedBy.result)}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}

      {upstream.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted">Depends on</div>
          <div className="space-y-2">
            {upstream.map((dep) => (
              <button
                key={dep.id}
                type="button"
                onClick={() => onSelect(dep.id)}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-white/[0.05] bg-white/[0.025] px-3 py-2 text-left text-xs text-muted hover:border-white/15 hover:text-foreground"
              >
                <span className="truncate">{operationLabel(dep.result)}</span>
                <StatusBadge status={dep.result.status} className="shrink-0 px-2 py-0.5 text-[10px]" />
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <Metric label="Stated" value={fmt(result.claim.stated_value)} />
        <Metric label="Recomputed" value={fmt(result.recomputed_value)} />
      </div>

      <div className="mt-4">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted">Operands</div>
        <div className="space-y-2">
          {result.claim.operands.length === 0 ? (
            <div className="rounded-lg bg-white/[0.025] px-3 py-2 text-xs text-muted">No operands emitted.</div>
          ) : (
            result.claim.operands.map((op, i) => (
              <div key={i} className="rounded-lg border border-white/[0.05] bg-white/[0.025] px-3 py-2">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-muted">Operand {i + 1}</span>
                  <span className="font-mono text-foreground">{fmt(op.value)}</span>
                </div>
                {op.source_text && (
                  <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
                    {op.source_text}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </aside>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white/[0.025] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 font-mono text-sm text-foreground">{value}</div>
    </div>
  );
}
