"use client";

import * as React from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Building2,
  ChevronDown,
  FileText,
  Loader2,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
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

const TEXT_FILE_ACCEPT = ".pdf,.txt,.md,.csv,.json,.html,.htm,.xml,.log,text/*,application/pdf";

async function extractPdfText(file: File) {
  const pdfjs = await import("pdfjs-dist/build/pdf.mjs");

  const data = await file.arrayBuffer();
  const pdf = await pdfjs.getDocument({ data, disableWorker: true }).promise;
  const pages: string[] = [];

  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    const pageText = content.items
      .map((item) => ("str" in item ? item.str : ""))
      .join(" ")
      .replace(/[ \t]+/g, " ")
      .trim();

    if (pageText) pages.push(pageText);
  }

  await pdf.destroy();
  return pages.join("\n\n");
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
  const canSubmit = source.trim().length > 0 && summary.trim().length > 0 && !loading;
  const canSubmitTicker = ticker.trim().length > 0 && !loading;

  const sourceFileRef = React.useRef<HTMLInputElement>(null);
  const summaryFileRef = React.useRef<HTMLInputElement>(null);
  const [sourceFileName, setSourceFileName] = React.useState<string | null>(null);
  const [summaryFileName, setSummaryFileName] = React.useState<string | null>(null);
  const [fileError, setFileError] = React.useState<string | null>(null);

  function handleKeyDown(e: React.KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && canSubmit) {
      onAudit();
    }
  }

  async function handleFileRead(
    file: File,
    setter: (value: string) => void,
    nameSetter: (name: string | null) => void
  ) {
    setFileError(null);

    const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
    const looksLikeText =
      file.type.startsWith("text/") ||
      /\.(txt|md|csv|json|html?|xml|log)$/i.test(file.name);

    if (!isPdf && !looksLikeText) {
      setFileError("Upload a PDF or text-like file: TXT, MD, CSV, JSON, HTML, XML, or LOG.");
      return;
    }

    if (isPdf) {
      try {
        const text = await extractPdfText(file);
        if (!text.trim()) {
          setFileError("No selectable text found in this PDF. Scanned PDFs need OCR before upload.");
          return;
        }
        setter(text);
        nameSetter(file.name);
      } catch {
        setFileError("Could not read this PDF. Try exporting it as text or uploading a non-scanned PDF.");
      }
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result;
      if (typeof text === "string") {
        setter(text);
        nameSetter(file.name);
        return;
      }
      setFileError("Could not read file as text.");
    };
    reader.onerror = () => {
      setFileError("Could not read file.");
    };
    reader.readAsText(file);
  }

  function handleDrop(
    e: React.DragEvent,
    setter: (value: string) => void,
    nameSetter: (name: string | null) => void
  ) {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFileRead(file, setter, nameSetter);
  }

  function handleFileInput(
    e: React.ChangeEvent<HTMLInputElement>,
    setter: (value: string) => void,
    nameSetter: (name: string | null) => void
  ) {
    const file = e.target.files?.[0];
    if (file) void handleFileRead(file, setter, nameSetter);
    e.target.value = "";
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
                <motion.span
                  key="loading"
                  className="inline-flex items-center gap-2"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                >
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Fetching &amp; auditing…
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
        <p className="mt-3 text-xs text-muted">
          Aritiq fetches the latest 10-K from SEC EDGAR, strips it to financial statements, and
          checks whether the filing&apos;s own numbers are internally consistent.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {["AAPL", "MSFT", "NVDA", "TSLA"].map((t) => (
            <button
              key={t}
              type="button"
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
          Custom audit
        </div>
        <div className="flex items-center gap-2">
          {examples.length > 0 && (
            <ExampleMenu
              examples={examples}
              onSelect={(example) => {
                setSourceFileName(null);
                setSummaryFileName(null);
                setFileError(null);
                onLoadExample(example);
              }}
              disabled={loading}
            />
          )}
          <ModeToggle mode={mode} onChange={onModeChange} disabled={loading} />
        </div>
      </div>

      {fileError && (
        <div className="mb-3 rounded-lg border border-wrong/30 bg-wrong/[0.08] px-3 py-2 text-xs text-wrong">
          {fileError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Field label="Source Document(s)" hint="ground truth" icon={<FileText className="h-3.5 w-3.5" />}>
          <UploadableTextarea
            value={source}
            onChange={(value) => {
              onSourceChange(value);
              if (sourceFileName) setSourceFileName(null);
            }}
            placeholder="Paste a source document, upload a text file, or drag one here."
            className="font-mono"
            disabled={loading}
            inputRef={sourceFileRef}
            fileName={sourceFileName}
            onFileInput={(e) => handleFileInput(e, onSourceChange, setSourceFileName)}
            onDrop={(e) => handleDrop(e, onSourceChange, setSourceFileName)}
            onChooseFile={() => sourceFileRef.current?.click()}
            onClearFile={() => {
              setSourceFileName(null);
              onSourceChange("");
            }}
          />
        </Field>

        <Field label="AI-Generated Summary" hint="audited" icon={<Sparkles className="h-3.5 w-3.5" />}>
          <UploadableTextarea
            value={summary}
            onChange={(value) => {
              onSummaryChange(value);
              if (summaryFileName) setSummaryFileName(null);
            }}
            placeholder="Paste the AI-generated summary, upload a text file, or drag one here."
            disabled={loading}
            inputRef={summaryFileRef}
            fileName={summaryFileName}
            onFileInput={(e) => handleFileInput(e, onSummaryChange, setSummaryFileName)}
            onDrop={(e) => handleDrop(e, onSummaryChange, setSummaryFileName)}
            onChooseFile={() => summaryFileRef.current?.click()}
            onClearFile={() => {
              setSummaryFileName(null);
              onSummaryChange("");
            }}
          />
        </Field>
      </div>

      <div className="mt-5 flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted">
          Calculations are derived from primary source documents.
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

function UploadableTextarea({
  value,
  onChange,
  placeholder,
  className,
  disabled,
  inputRef,
  fileName,
  onFileInput,
  onDrop,
  onChooseFile,
  onClearFile,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
  disabled: boolean;
  inputRef: React.RefObject<HTMLInputElement>;
  fileName: string | null;
  onFileInput: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onDrop: (e: React.DragEvent) => void;
  onChooseFile: () => void;
  onClearFile: () => void;
}) {
  return (
    <div>
      <div onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
        <Textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cn("min-h-[200px] text-[13px]", className)}
          spellCheck={false}
          disabled={disabled}
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept={TEXT_FILE_ACCEPT}
          className="hidden"
          onChange={onFileInput}
        />
        {fileName ? (
          <div className="flex max-w-full items-center gap-1.5 rounded-lg bg-primary/10 px-2.5 py-1.5 text-[11px] font-medium text-primary ring-1 ring-inset ring-primary/25">
            <FileText className="h-3 w-3 shrink-0" />
            <span className="truncate">{fileName}</span>
            <button
              type="button"
              onClick={onClearFile}
              disabled={disabled}
              aria-label={`Remove ${fileName}`}
              className="ml-0.5 rounded-full p-0.5 transition-colors hover:bg-primary/20 disabled:opacity-50"
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={onChooseFile}
            disabled={disabled}
            className="flex items-center gap-1.5 rounded-lg border border-dashed border-white/15 bg-white/[0.02] px-3 py-1.5 text-[11px] font-medium text-muted transition-colors hover:border-primary/40 hover:bg-primary/[0.04] hover:text-primary disabled:opacity-50"
          >
            <Upload className="h-3 w-3" />
            Upload file
          </button>
        )}
        <span className="select-none text-[10px] text-muted/60">or drag &amp; drop</span>
      </div>
    </div>
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
          type="button"
          onClick={() => onChange(m)}
          disabled={disabled}
          className={cn(
            "rounded-md px-3 py-1.5 transition-colors disabled:opacity-50",
            mode === m ? "bg-primary/20 text-primary" : "text-muted hover:text-foreground"
          )}
        >
          {m === "ticker" ? "By ticker" : "Custom"}
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
    function onPointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.04] px-3 py-1.5 text-[11px] font-medium text-muted transition-colors hover:bg-white/[0.08] hover:text-foreground disabled:opacity-50"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Load example
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-xl bg-[#0B0F19] border border-white/10 shadow-2xl p-1.5"
          >
            {examples.map((ex) => (
              <button
                key={ex.id}
                type="button"
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
