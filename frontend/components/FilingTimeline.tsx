"use client";

/**
 * FilingTimeline — Phase 3 item 1.
 *
 * Renders a company's SEC filings in date order, with an EXPLICIT
 * verification-coverage badge on every event and the legend up top. The
 * honesty rule this component exists to enforce: 10-K/10-Q are the forms with
 * measured financial verification; an 8-K is "partial" only when it carries an
 * Item 2.02 earnings exhibit; Form 4 is parsed ownership data; everything else
 * (DEF 14A, 13D/13F, S-1, amendments…) is a dated entry with a link — nothing
 * more is claimed, matching README.md's filing-type support table.
 */

import { useMemo, useState } from "react";
import type {
  CompanyTimeline,
  TimelineEvent,
  VerificationCoverage,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const COVERAGE_STYLE: Record<
  VerificationCoverage,
  { label: string; chip: string }
> = {
  full_financial_verification: {
    label: "Verified forms",
    chip: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  },
  partial_financial_verification: {
    label: "Partial (Item 2.02)",
    chip: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  },
  ownership_data_only: {
    label: "Ownership data",
    chip: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  },
  listed_only: {
    label: "Listed only",
    chip: "bg-zinc-500/15 text-zinc-400 border border-zinc-500/30",
  },
};

const FILTERS: { key: string; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "10-K", label: "10-K" },
  { key: "10-Q", label: "10-Q" },
  { key: "8-K", label: "8-K" },
  { key: "4", label: "Form 4" },
  { key: "DEF 14A", label: "DEF 14A" },
];

export function FilingTimeline({ timeline }: { timeline: CompanyTimeline }) {
  const [filter, setFilter] = useState<string>("ALL");

  const events = useMemo(() => {
    if (filter === "ALL") return timeline.events;
    return timeline.events.filter((e) => e.form === filter);
  }, [timeline.events, filter]);

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-zinc-200">
          SEC filing timeline — {timeline.name || timeline.ticker}
        </h3>
        {/* The load-bearing honesty statement, always visible */}
        <p className="mt-1 text-xs text-zinc-400">
          Aritiq runs measured financial verification on{" "}
          <span className="text-emerald-400 font-medium">10-K and 10-Q</span>{" "}
          filings only. <span className="text-amber-400">8-K</span> is
          partial/experimental (only Item 2.02 earnings exhibits carry XBRL).{" "}
          <span className="text-sky-400">Form 4</span> transactions are parsed
          but not financially verified. All other forms are{" "}
          <span className="text-zinc-300">dated entries with a link</span> — no
          verification is performed or implied.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "rounded-full px-2.5 py-1 text-[11px] font-medium border transition-colors",
              filter === f.key
                ? "bg-zinc-200 text-zinc-900 border-zinc-200"
                : "bg-transparent text-zinc-400 border-zinc-700 hover:border-zinc-500"
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <ol className="relative border-l border-zinc-800 pl-4 space-y-2 max-h-[28rem] overflow-y-auto">
        {events.map((e) => (
          <TimelineRow key={`${e.accession}-${e.form}`} event={e} />
        ))}
        {events.length === 0 && (
          <li className="text-xs text-zinc-500 py-2">
            No {filter === "ALL" ? "" : `${filter} `}filings in the recent
            window.
          </li>
        )}
      </ol>

      {timeline.has_older_filings && (
        <p className="text-[11px] text-zinc-500">
          Older filings exist in SEC&apos;s paginated archives beyond this
          recent window and are not shown.
        </p>
      )}
    </div>
  );
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  const cov = COVERAGE_STYLE[event.verification_coverage];
  return (
    <li className="relative">
      <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-zinc-600" />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-zinc-300 w-20 shrink-0">
          {event.filing_date}
        </span>
        <span className="font-semibold text-zinc-200 w-16 shrink-0">
          {event.form}
        </span>
        <span
          className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
            cov.chip
          )}
          title={event.verification_coverage}
        >
          {cov.label}
        </span>
        {event.items && (
          <span className="text-[10px] text-zinc-500">Items {event.items}</span>
        )}
        {event.document_url && (
          <a
            href={event.document_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] text-zinc-400 underline decoration-zinc-700 hover:text-zinc-200"
          >
            EDGAR
          </a>
        )}
      </div>
    </li>
  );
}
