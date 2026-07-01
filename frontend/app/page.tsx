"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldCheck, Lock, Loader2, ScanSearch, AlertTriangle, Building2, ExternalLink } from "lucide-react";
import { InputPanel, type InputMode } from "@/components/InputPanel";
import { ScoreRing } from "@/components/ScoreRing";
import { ClaimsTable } from "@/components/ClaimsTable";
import { DependencyGraph } from "@/components/DependencyGraph";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Card } from "@/components/ui/card";
import { audit, auditDocuments, auditTicker, getExamples, ApiError } from "@/lib/api";
import { splitDocuments } from "@/lib/splitDocuments";
import type { AuditResult, Example } from "@/lib/types";

export default function Page() {
  const [mode, setMode] = React.useState<InputMode>("ticker");
  const [ticker, setTicker] = React.useState("");
  const [source, setSource] = React.useState("");
  const [summary, setSummary] = React.useState("");
  const [result, setResult] = React.useState<AuditResult | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [examples, setExamples] = React.useState<Example[]>([]);

  React.useEffect(() => {
    getExamples().then(setExamples);
  }, []);

  const runAudit = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // If the source contains two or more clearly-headed documents, route to
      // the multi-document path so claims ground to the right filing and a
      // cross-document CONFLICT (e.g. a restated prior-year figure) is surfaced.
      const split = splitDocuments(source);
      const data = split.multi
        ? await auditDocuments(split.documents, summary)
        : await audit(source, summary);
      setResult(data);
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e.message : "Something went wrong while auditing.");
    } finally {
      setLoading(false);
    }
  }, [source, summary]);

  const runTickerAudit = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await auditTicker(ticker);
      setResult(data);
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e.message : "Something went wrong fetching that filing.");
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  function loadExample(ex: Example) {
    setMode("paste");
    setSource(ex.source);
    setSummary(ex.summary);
    setResult(null);
    setError(null);
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
      <Header />

      <div className="mt-8">
        <InputPanel
          mode={mode}
          onModeChange={(m) => {
            setMode(m);
            setError(null);
          }}
          ticker={ticker}
          onTickerChange={setTicker}
          onAuditTicker={runTickerAudit}
          source={source}
          summary={summary}
          onSourceChange={setSource}
          onSummaryChange={setSummary}
          onAudit={runAudit}
          loading={loading}
          examples={examples}
          onLoadExample={loadExample}
        />
      </div>

      <div className="mt-6">
        <AnimatePresence mode="wait">
          {error && !loading && (
            <motion.div key="error" exit={{ opacity: 0 }}>
              <ErrorBanner message={error} onRetry={runAudit} />
            </motion.div>
          )}

          {loading && (
            <motion.div
              key="loading"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
            >
              <LoadingState />
            </motion.div>
          )}

          {!loading && result && (
            <motion.div
              key="result"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              className="space-y-6"
            >
              {result.filing && <FilingBanner filing={result.filing} />}

              <Card className="p-6 sm:p-8">
                <ScoreRing score={result.score} results={result.results} />
              </Card>

              {result.issues.length > 0 && <IssuesNote count={result.issues.length} messages={result.issues.map((i) => i.message)} />}

              {result.conflicts && result.conflicts.length > 0 && (
                <ConflictsPanel conflicts={result.conflicts} />
              )}

              <DependencyGraph results={result.results} />

              <ClaimsTable results={result.results} />
            </motion.div>
          )}

          {!loading && !result && !error && (
            <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <EmptyState />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <Footer />
    </main>
  );
}

function Header() {
  return (
    <header>
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-primary/15 ring-1 ring-inset ring-primary/30">
          <ShieldCheck className="h-6 w-6 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Aritiq</h1>
          <p className="text-xs text-muted">AI Financial Summary Auditor</p>
        </div>
        <div className="ml-auto hidden items-center gap-1.5 rounded-full glass-subtle px-3 py-1.5 text-[11px] font-medium text-muted sm:flex">
          <Lock className="h-3.5 w-3.5 text-primary" />
          LLM parses · code verifies
        </div>
      </div>
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-muted">
        Aritiq traces every numeric claim back to its source and re-checks it with deterministic
        code — catching the derived-number errors (growth, margins, ratios) that grounding checkers
        miss. It also checks whether a document's own numbers agree with each other, with no model
        in the verifier.
      </p>
    </header>
  );
}

function LoadingState() {
  return (
    <Card className="p-8">
      <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
        <div className="relative">
          <div className="h-16 w-16 rounded-full border-2 border-white/10" />
          <Loader2 className="absolute inset-0 m-auto h-8 w-8 animate-spin text-primary" />
        </div>
        <div>
          <p className="text-sm font-medium text-foreground">Auditing the summary…</p>
          <p className="mt-1 text-xs text-muted">Extracting claims, tracing operands, recomputing the math.</p>
        </div>
        <div className="mt-2 w-full max-w-md space-y-2">
          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              className="h-10 rounded-lg bg-white/[0.04]"
              animate={{ opacity: [0.4, 0.7, 0.4] }}
              transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.18, ease: "easeInOut" }}
            />
          ))}
        </div>
      </div>
    </Card>
  );
}

function EmptyState() {
  return (
    <Card className="p-10">
      <div className="flex flex-col items-center justify-center gap-3 py-6 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl glass-subtle">
          <ScanSearch className="h-6 w-6 text-muted" />
        </div>
        <p className="text-sm font-medium text-foreground">No audit yet</p>
        <p className="max-w-sm text-xs text-muted">
          Paste a source document and an AI summary above, or use “Load example,” then run an audit
          to see the score and a fully inspectable per-claim trace.
        </p>
      </div>
    </Card>
  );
}

function IssuesNote({ count, messages }: { count: number; messages: string[] }) {
  return (
    <div className="rounded-xl border border-unsupported/25 bg-unsupported/[0.06] p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-unsupported">
        <AlertTriangle className="h-4 w-4" />
        {count} extracted claim{count === 1 ? "" : "s"} failed schema validation and {count === 1 ? "was" : "were"} skipped
      </div>
      <ul className="mt-2 space-y-1 pl-6 text-xs text-muted">
        {messages.slice(0, 4).map((m, i) => (
          <li key={i} className="list-disc">{m}</li>
        ))}
      </ul>
    </div>
  );
}

function FilingBanner({ filing }: { filing: NonNullable<AuditResult["filing"]> }) {
  return (
    <div className="rounded-xl glass-subtle p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 ring-1 ring-inset ring-primary/30">
            <Building2 className="h-4.5 w-4.5 text-primary" />
          </div>
          <div>
            <div className="text-sm font-semibold text-foreground">
              {filing.company}{" "}
              <span className="font-mono text-xs font-normal text-muted">({filing.ticker})</span>
            </div>
            <div className="text-xs text-muted">
              Latest 10-K · filed {filing.filing_date}
              {filing.period ? ` · period ${filing.period}` : ""} · fetched from SEC EDGAR
            </div>
          </div>
        </div>
        <a
          href={filing.document_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-white/[0.08] hover:text-foreground"
        >
          View filing on SEC.gov
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  );
}

function ConflictsPanel({ conflicts }: { conflicts: AuditResult["conflicts"] }) {
  if (!conflicts || conflicts.length === 0) return null;
  const RESTATEMENT_LABEL: Record<string, string> = {
    EXPLICIT_RESTATEMENT: "Explicit restatement language found nearby",
    POSSIBLE_RECLASSIFICATION: "Reclassification language found nearby",
    UNEXPLAINED: "No disclosure language found near the figure",
    UNCLASSIFIED: "Not classified",
  };
  return (
    <div className="rounded-xl border border-wrong/30 bg-wrong/[0.06] p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-wrong">
        <AlertTriangle className="h-4 w-4" />
        {conflicts.length} cross-document conflict{conflicts.length === 1 ? "" : "s"} — two filings
        disagree on the same figure
      </div>
      <p className="mt-1 text-xs text-muted">
        Aritiq surfaces the disagreement and never silently picks a winner — the authoritative figure
        is a human decision. Where the filer&apos;s own text discloses a restatement near the number,
        that is noted (disclosure language found, not a determination of restatement type).
      </p>
      <ul className="mt-3 space-y-2">
        {conflicts.map((c, i) => (
          <li key={i} className="rounded-lg bg-white/[0.03] p-3 text-[13px]">
            <div className="font-medium text-foreground">{c.claim.claim_text}</div>
            <div className="mt-1 text-xs text-muted">{c.explanation}</div>
            {c.restatement_type && (
              <span className="mt-2 inline-flex items-center rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary ring-1 ring-inset ring-primary/30">
                {RESTATEMENT_LABEL[c.restatement_type] ?? c.restatement_type}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Footer() {
  return (
    <footer className="mt-14 border-t border-border/60 pt-6">
      <p className="text-center text-xs text-muted">
        The verifier contains no LLM. Every verdict above is produced by code re-computing the math —
        inspect any claim to trace the operands and the arithmetic.
      </p>
    </footer>
  );
}
