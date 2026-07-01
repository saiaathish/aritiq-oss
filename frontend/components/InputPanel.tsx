"use client";

import * as React from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { Loader2, ShieldCheck, ChevronDown, FileText, Sparkles, Building2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Example } from "@/lib/types";

export type InputMode = "ticker" | "paste";

interface InputPanelProps {
  mode: InputMode;
  onModeChange: (m: InputMode) => void;
  ticker: string;
  onTickerChange: (v: string) => void;
  onAuditTicker: () => void;
  source: string;
  summary: string;
  onSourceChange: (v: string) => void;
  onSummaryChange: (v: string) => void;
  onAudit: () => void;
  loading: boolean;
  examples: Example[];
  onLoadExample: (e: Example) => void;
}

export function InputPanel({
  mode,
  onModeChange,
  ticker,
  onTickerChange,
  onAuditTicker,
  source,
  summary,
  onSourceChange,
  onSummaryChange,
  onAudit,
  loading,
  examples,
  onLoadExample,
}: InputPanelProps) {
  const canSubmit = (source || "").trim().length > 0 && (summary || "").trim().length > 0 && !loading;
  const canSubmitTicker = (ticker || "").trim().length > 0 && !loading;

  function handleKeyDown(e: React.KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canSubmit) onAudit();
  }

  if (mode === "ticker") {
    return (
      <Card className="p-5 sm:p-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Building2 className="h-4 w-4 text-primary" />
            Audit a company&apos;s latest 10-K
          </div>
          <ModeToggle mode={mode} onChange={onModeChange} disabled={loading} />
        </div>

        <label className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted">
          <Search className="h-3.5 w-3.5" />
          Ticker symbol
        </label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={ticker}
            onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === "Enter" && canSubmitTicker) onAuditTicker();
            }}
            placeholder="AAPL"
            spellCheck={false}
            disabled={loading}
            maxLength={8}
            className="w-full rounded-xl border border-border/70 bg-white/[0.03] px-4 py-3 font-mono text-lg uppercase tracking-widest text-foreground placeholder:text-muted/40 outline-none transition-colors focus:border-primary/60 sm:max-w-[220px]"
          />
          <Button onClick={onAuditTicker} disabled={!canSubmitTicker} size="lg" className="sm:min-w-[160px]">
            <AnimatePresence mode="wait" initial={false}>
              {loading ? (
                <motion.span key="loading" className="inline-flex items-center gap-2"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Fetching &amp; auditing…
                </motion.span>
              ) : (
                <motion.span key="idle" className="inline-flex items-center gap-2"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                  <ShieldCheck className="h-4 w-4" />
                  Audit
                </motion.span>
              )}
            </AnimatePresence>
          </Button>
        </div>
        <p className="mt-3 text-xs text-muted">
          Aritiq fetches the latest 10-K from SEC EDGAR (free, public), strips it to the financial
          statements, and checks whether the filing&apos;s own numbers are internally consistent —
          balance sheet, EPS, and cash tie-out — with no model in the verifier. US-listed companies
          that file a 10-K.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {["AAPL", "MSFT", "NVDA", "TSLA"].map((t) => (
            <button
              key={t}
              onClick={() => onTickerChange(t)}
              disabled={loading}
              className="rounded-full bg-white/[0.04] px-3 py-1 text-[11px] font-medium text-muted transition-colors hover:bg-white/[0.08] hover:text-foreground disabled:opacity-50"
            >
              {t}
            </button>
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-5 sm:p-6" onKeyDown={handleKeyDown}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <FileText className="h-4 w-4 text-primary" />
          Audit a summary
        </div>
        <div className="flex items-center gap-2">
          {examples.length > 0 && (
            <ExampleMenu examples={examples} onSelect={onLoadExample} disabled={loading} />
          )}
          <ModeToggle mode={mode} onChange={onModeChange} disabled={loading} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Field
          label="Source Document(s)"
          hint="ground truth"
          icon={<FileText className="h-3.5 w-3.5" />}
        >
          <Textarea
            value={source}
            onChange={(e) => onSourceChange(e.target.value)}
            placeholder="Paste the source document — the figures Aritiq will trace claims back to (e.g. an earnings release or invoice)."
            className="min-h-[200px] font-mono text-[13px]"
            spellCheck={false}
            disabled={loading}
          />
          <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground/70 px-1 select-none">
            <span>Single document or multiple (future)</span>
            <span className="cursor-not-allowed opacity-50 flex items-center gap-0.5">
              + Add another document (future)
            </span>
          </div>
        </Field>

        <Field
          label="AI-Generated Summary"
          hint="audited"
          icon={<Sparkles className="h-3.5 w-3.5" />}
        >
          <Textarea
            value={summary}
            onChange={(e) => onSummaryChange(e.target.value)}
            placeholder="Paste the AI-generated summary to audit. Aritiq extracts each numeric claim and re-checks the arithmetic."
            className="min-h-[200px] text-[13px]"
            spellCheck={false}
            disabled={loading}
          />
        </Field>
      </div>

      <div className="mt-5 flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted">
          The LLM only parses prose into claims. The verdicts come from code re-computing the math.
        </p>
        <Button onClick={onAudit} disabled={!canSubmit} size="lg" className="sm:min-w-[160px]">
          <AnimatePresence mode="wait" initial={false}>
            {loading ? (
              <motion.span
                key="loading"
                className="inline-flex items-center gap-2"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                <Loader2 className="h-4 w-4 animate-spin" />
                Auditing…
              </motion.span>
            ) : (
              <motion.span
                key="idle"
                className="inline-flex items-center gap-2"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                <ShieldCheck className="h-4 w-4" />
                Audit
              </motion.span>
            )}
          </AnimatePresence>
        </Button>
      </div>
    </Card>
  );
}

function ModeToggle({
  mode,
  onChange,
  disabled,
}: {
  mode: InputMode;
  onChange: (m: InputMode) => void;
  disabled: boolean;
}) {
  return (
    <div className="inline-flex items-center rounded-lg bg-white/[0.04] p-0.5 text-[11px] font-medium">
      {(["ticker", "paste"] as InputMode[]).map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          disabled={disabled}
          className={cn(
            "rounded-md px-3 py-1.5 transition-colors disabled:opacity-50",
            mode === m ? "bg-primary/20 text-primary" : "text-muted hover:text-foreground"
          )}
        >
          {m === "ticker" ? "By ticker" : "Paste text"}
        </button>
      ))}
    </div>
  );
}

function Field({
  label,
  hint,
  icon,
  children,
}: {
  label: string;
  hint: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted">
          {icon}
          {label}
        </label>
        <span className="rounded-full bg-white/[0.04] px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted">
          {hint}
        </span>
      </div>
      {children}
    </div>
  );
}

function ExampleMenu({
  examples,
  onSelect,
  disabled,
}: {
  examples: Example[];
  onSelect: (e: Example) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  React.useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, []);

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Load example
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} />
      </Button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-xl glass p-1.5"
          >
            {examples.map((ex) => (
              <button
                key={ex.id}
                role="menuitem"
                onClick={() => {
                  onSelect(ex);
                  setOpen(false);
                }}
                className="flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left text-[13px] text-foreground transition-colors hover:bg-white/[0.06]"
              >
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-primary/15 text-[10px] font-bold text-primary">
                  {ex.id}
                </span>
                <span className="text-muted">{ex.name}</span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
