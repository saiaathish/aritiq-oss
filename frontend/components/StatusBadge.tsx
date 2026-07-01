"use client";

import { STATUS_CONFIG, cn } from "@/lib/utils";
import type { Status } from "@/lib/types";

export function StatusBadge({
  status,
  className,
}: {
  status: Status;
  className?: string;
}) {
  const cfg = STATUS_CONFIG[status];
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium",
        cfg.chip,
        cfg.italic && "italic",
        cfg.bold && "font-bold",
        className
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      {cfg.label}
    </span>
  );
}
