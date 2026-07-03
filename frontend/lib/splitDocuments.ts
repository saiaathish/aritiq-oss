import type { DocumentInput } from "./types";

/**
 * Split a single pasted "source" blob into labeled documents when the user has
 * pasted more than one filing into one box.
 *
 * Why this exists: the UI has historically had one source textarea, and people
 * paste two filings into it (e.g. "Source Document A — FY2024 10-K ... Source
 * Document B — FY2025 10-K ..."). The single-string /audit path then grounds
 * same-named figures against whichever document came first, producing false
 * positives and never surfacing a cross-document conflict. Detecting the split
 * lets the page route a genuine two-document paste to /audit-multi.
 *
 * The split is intentionally conservative: it only fires on clear document
 * headers, and if it can't find at least two, it returns a single document so
 * the caller falls back to the ordinary single-source path. It never silently
 * mangles a single document that merely mentions the word "document".
 */

// Header patterns that strongly indicate a new document boundary.
const HEADER_PATTERNS: RegExp[] = [
  // "Source Document A — ...", "Document B:", "DOCUMENT 1 ..."
  /^\s*(?:source\s+)?document\s+([A-Z0-9][\w-]*)\s*[—\-:.]/i,
  // "=== DOCUMENT X (period: FY2025) ===" (our own labeled format)
  /^\s*={2,}\s*document\s+([\w-]+).*?={2,}\s*$/i,
  // "Exhibit A", "Filing 1 —"
  /^\s*(?:exhibit|filing)\s+([A-Z0-9][\w-]*)\s*[—\-:.]/i,
];

// Try to pull a fiscal period out of a header/first line, e.g. "FY2024" or
// "fiscal year 2025" or "FY2025 10-K".
function detectPeriod(text: string): string | undefined {
  const fy = text.match(/\bFY\s?(\d{4})\b/i) || text.match(/fiscal\s+(?:year\s+)?(\d{4})/i);
  if (fy) return `FY${fy[1]}`;
  return undefined;
}

function detectDocType(text: string): string | undefined {
  const m = text.match(/\b(10-K|10-Q|8-K|press\s+release|annual\s+report|earnings\s+release)\b/i);
  return m ? m[1].replace(/\s+/g, " ") : undefined;
}

interface SplitResult {
  multi: boolean;
  documents: DocumentInput[];
}

export function splitDocuments(source: string): SplitResult {
  const lines = source.split(/\r?\n/);

  // Find indices of lines that look like a document header.
  const boundaries: { line: number; label: string }[] = [];
  for (let i = 0; i < lines.length; i++) {
    for (const re of HEADER_PATTERNS) {
      const m = lines[i].match(re);
      if (m) {
        boundaries.push({ line: i, label: m[1] });
        break;
      }
    }
  }

  if (boundaries.length < 2) {
    // Not a clear multi-document paste — treat as one document.
    return {
      multi: false,
      documents: [{ doc_id: "DOC_1", text: source }],
    };
  }

  // Slice the text between consecutive boundaries.
  const documents: DocumentInput[] = [];
  for (let b = 0; b < boundaries.length; b++) {
    const start = boundaries[b].line;
    const end = b + 1 < boundaries.length ? boundaries[b + 1].line : lines.length;
    const chunk = lines.slice(start, end).join("\n").trim();
    if (!chunk) continue;
    const headerLine = lines[start];
    const period = detectPeriod(headerLine) ?? detectPeriod(chunk);
    const docType = detectDocType(headerLine) ?? detectDocType(chunk);
    // Build a readable doc_id like "A_FY2024" when possible.
    const rawLabel = boundaries[b].label.toUpperCase();
    const doc_id = period ? `${rawLabel}_${period}` : `DOC_${rawLabel}`;
    documents.push({ doc_id, text: chunk, period, doc_type: docType });
  }

  return { multi: documents.length >= 2, documents };
}
