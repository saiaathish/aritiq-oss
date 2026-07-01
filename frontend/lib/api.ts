import type { AuditResult, DocumentInput, Example } from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

/** Thrown for any failure so the UI can render a single, friendly banner. */
export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // Network-level failure (backend down, CORS, DNS, offline, …)
    throw new ApiError(
      `Couldn't reach the Aritiq API at ${API_URL}. Is the backend running? ` +
        `Start it with: uvicorn backend.app:app --reload`
    );
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status} ${res.statusText}).`;
    try {
      const data = await res.json();
      if (data?.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep the default detail */
    }
    throw new ApiError(detail);
  }

  return res.json() as Promise<T>;
}

export async function audit(source: string, summary: string): Promise<AuditResult> {
  return postJson<AuditResult>("/audit", { source, summary });
}

/**
 * Multi-document audit (Phase 3): send 2+ labeled filings so claims ground to
 * the document they describe and cross-document CONFLICTs (e.g. a restated
 * prior-year figure) are surfaced. Hits /audit-multi.
 */
export async function auditDocuments(
  documents: DocumentInput[],
  summary: string
): Promise<AuditResult> {
  return postJson<AuditResult>("/audit-multi", { documents, summary });
}

/**
 * Audit a company's latest 10-K by ticker. Aritiq fetches the filing from SEC
 * EDGAR (free, server-side), strips it to the financial statements, and audits
 * it. With no summary, it checks the filing's own internal consistency. The
 * response includes a `filing` block describing what was fetched.
 */
export async function auditTicker(
  ticker: string,
  summary?: string
): Promise<AuditResult> {
  return postJson<AuditResult>("/audit-ticker", { ticker, summary: summary ?? null });
}

export async function getExamples(): Promise<Example[]> {
  try {
    const res = await fetch(`${API_URL}/examples`);
    if (!res.ok) return [];
    return (await res.json()) as Example[];
  } catch {
    return []; // examples are a convenience; never block the UI on them
  }
}
