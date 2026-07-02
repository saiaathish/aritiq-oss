import type {
  AuditResult,
  CompanyTimeline,
  DocumentInput,
  Example,
  RiskDashboard,
} from "./types";

import { createClient } from "./supabase/client";

const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    const hn = window.location.hostname;
    if (hn !== "localhost" && hn !== "127.0.0.1") {
      return window.location.origin;
    }
  }
  return "http://localhost:8000";
};

const API_URL = getApiUrl();

/** Thrown for any failure so the UI can render a single, friendly banner. */
export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// Module-level singleton + 60s token cache. The Supabase browser client keeps
// an internal auth state machine; if two callers race (e.g. UserMenu.tsx's
// getUser() on mount, then authHeader()'s getSession() inside the first Audit
// click), the in-flight validation can wipe the cached session and getSession()
// returns null even though cookies hold a valid token. Doing getUser() first
// until we have a verified session, then caching the resolved access_token so
// subsequent audits reuse it, eliminates the race without a network call on
// every keystroke.
let _supabase: ReturnType<typeof createClient> | null = null;
let _subbed = false;
function getClient() {
  if (!_supabase) _supabase = createClient();
  if (!_subbed) {
    _subbed = true;
    _supabase.auth.onAuthStateChange((_event, session) => {
      _cachedAuth = session?.access_token
        ? { token: session.access_token, exp: session.expires_at ?? 0 }
        : null;
    });
  }
  return _supabase;
}

type CachedAuth = { token: string; exp: number };
let _cachedAuth: CachedAuth | null = null;

/** Supabase session JWT for the audit endpoints (they 401 without one). */
async function authHeader(): Promise<Record<string, string>> {
  const nowS = Math.floor(Date.now() / 1000);
  // Fast path: cached token with at least 30s of life left.
  if (_cachedAuth && _cachedAuth.exp - nowS > 30) {
    return { Authorization: `Bearer ${_cachedAuth.token}` };
  }
  const supabase = getClient();
  try {
    // getUser() hits the server, validates the JWT, and forces a token
    // refresh if the stored one is near-expired (THAT is what fixes the
    // post-OAuth "first audit clicks me back to /login" bug — getSession()
    // alone reads cookies without validating and can briefly resolve null).
    const { data } = await supabase.auth.getUser();
    if (!data.user) return {};
    const { data: sessionData } = await supabase.auth.getSession();
    const session = sessionData.session;
    if (!session?.access_token) return {};
    _cachedAuth = {
      token: session.access_token,
      // Supabase documents the JWT TTL at 1 hour; pin the cache to that so
      // we never silently hand out a token past its server-known expiry.
      exp: session.expires_at ?? nowS + 3600,
    };
    return { Authorization: `Bearer ${session.access_token}` };
  } catch {
    // Transient network error: don't bounce the user to /login if we still
    // hold a non-expired cached token. Same 30s margin as the fast path so a
    // token Supabase is about to consider stale isn't handed to the backend.
    if (_cachedAuth && _cachedAuth.exp - nowS > 30) {
      return { Authorization: `Bearer ${_cachedAuth.token}` };
    }
    return {};
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeader()) },
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
    // Session missing/expired -> bounce through login and come back here.
    if (res.status === 401 && typeof window !== "undefined") {
      const here = window.location.pathname + window.location.search;
      window.location.href = `/login?next=${encodeURIComponent(here)}`;
      throw new ApiError("Please sign in to run audits — redirecting…");
    }
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

/**
 * Fetch a company's SEC filing timeline (Phase 3 item 1). Every event carries
 * a `verification_coverage` label and the response ships the legend, so the UI
 * states plainly which filing types Aritiq actually verifies (10-K/10-Q),
 * which are partial (8-K with Item 2.02), and which are listed-only.
 */
export async function getTimeline(
  ticker: string,
  opts?: { forms?: string[]; limit?: number }
): Promise<CompanyTimeline> {
  const params = new URLSearchParams();
  if (opts?.forms?.length) params.set("forms", opts.forms.join(","));
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  let res: Response;
  try {
    res = await fetch(
      `${API_URL}/timeline/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ""}`,
      { headers: await authHeader() }
    );
  } catch {
    throw new ApiError(
      `Couldn't reach the Aritiq API at ${API_URL}. Is the backend running?`
    );
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status} ${res.statusText}).`;
    try {
      const data = await res.json();
      if (data?.detail)
        detail =
          typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep default */
    }
    throw new ApiError(detail);
  }
  return res.json() as Promise<CompanyTimeline>;
}

/**
 * Fetch the institutional risk dashboard (Phase 3 item 2) — deterministic
 * panels over cached benchmark verdicts + company memory. 404s for tickers
 * outside the benchmark cache rather than fabricating panels.
 */
export async function getDashboard(ticker: string): Promise<RiskDashboard> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/dashboard/${encodeURIComponent(ticker)}`, {
      headers: await authHeader(),
    });
  } catch {
    throw new ApiError(
      `Couldn't reach the Aritiq API at ${API_URL}. Is the backend running?`
    );
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status} ${res.statusText}).`;
    try {
      const data = await res.json();
      if (data?.detail)
        detail =
          typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep default */
    }
    throw new ApiError(detail);
  }
  return res.json() as Promise<RiskDashboard>;
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
