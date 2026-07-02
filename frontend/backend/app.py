"""
Aritiq backend — a thin FastAPI wrapper around aritiq.pipeline.audit.

Endpoints
---------
  GET  /examples   -> the bundled gold documents (for the UI's "Load example")
  POST /audit      -> { source, summary }  ->  AuditResult (the exact JSON the
                      frontend expects)
  GET  /health     -> liveness + whether a live API key is configured

Running the audit
-----------------
For the bundled examples we replay the saved Day 2 extraction outputs, so the
demo works with NO API key. For any other (source, summary), we call the real
extractor, which needs ANTHROPIC_API_KEY (or OPENAI_API_KEY + ARITIQ_PROVIDER).
If no key is set and the input isn't a bundled example, /audit returns a clear
503 the UI renders in its error banner.

Run:
    pip install -r backend/requirements.txt
    uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import threading
import time
import re
import sys
from contextlib import contextmanager
from dataclasses import asdict
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# Make the aritiq package importable (repo root is the parent of this file).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aritiq.pipeline import audit as run_audit  # noqa: E402
from aritiq.pipeline import audit_documents as run_audit_documents, SourceDoc  # noqa: E402
from aritiq.core.schema import VerificationResult  # noqa: E402
from aritiq.edgar import (  # noqa: E402
    fetch_10k_text, EdgarError, UnknownTickerError, NoFilingError,
)
from aritiq.edgar.timeline import (  # noqa: E402
    COVERAGE_LEGEND, get_timeline,
)
from aritiq.dashboard import build_dashboard  # noqa: E402
from aritiq.edgar.company_memory import build_company_memory  # noqa: E402
from aritiq.analyst import ask_analyst, ledger_from_records  # noqa: E402
import aritiq.enterprise as enterprise  # noqa: E402
from backend import rate_limit, supabase_auth  # noqa: E402

GOLD_PATH = os.path.join(ROOT, "benchmark", "gold_set.json")
RUNS_DIR = os.path.join(ROOT, "benchmark", "runs")

app = FastAPI(title="Aritiq API", version="0.1.0")

MAX_SOURCE_CHARS = int(os.environ.get("ARITIQ_MAX_SOURCE_CHARS", "250000"))
MAX_SUMMARY_CHARS = int(os.environ.get("ARITIQ_MAX_SUMMARY_CHARS", "20000"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("ARITIQ_RATE_LIMIT_PER_MINUTE", "30"))
_RATE_BUCKETS: dict[str, list[float]] = {}
_RATE_LOCK = threading.Lock()
_BYOK_ENV_LOCK = threading.Lock()

# CORS: localhost (any port) for dev, plus an env-driven allowlist for the
# deployed frontend origin(s), e.g. ARITIQ_ALLOWED_ORIGINS="https://aritiq.app".
_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ARITIQ_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Emails exempt from the per-user burst/daily audit limits (comma-separated).
# Kept out of source so the open-source repo ships no personal data.
UNLIMITED_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ARITIQ_UNLIMITED_EMAILS", "").split(",")
    if e.strip()
}

# Explicit opt-in for the old local-dev behavior where requests with no
# credentials at all fall back to a shared default workspace. NEVER set this
# in production: it exposes the shared audit history to anonymous callers.
ALLOW_ANON_DEV = os.environ.get("ARITIQ_ALLOW_ANON_DEV", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Bundled examples + replay index
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _load_examples():
    try:
        data = json.load(open(GOLD_PATH))
    except FileNotFoundError:
        return [], {}
    examples = []
    replay = {}  # normalized (source|||summary) -> doc_id
    for d in data["documents"]:
        examples.append(
            {"id": d["id"], "name": d["name"], "source": d["source"], "summary": d["summary"]}
        )
        replay[(_norm(d["source"]), _norm(d["summary"]))] = d["id"]
    return examples, replay


EXAMPLES, REPLAY_INDEX = _load_examples()


def _replay_fn_for(doc_id: str):
    raw = json.load(open(os.path.join(RUNS_DIR, f"{doc_id}.json")))["raw"]
    return lambda system_prompt, user_prompt: raw


def _has_live_key() -> bool:
    provider = (os.environ.get("ARITIQ_PROVIDER") or "anthropic").lower()
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY"))
    if provider == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    return bool(
        os.environ.get("ANTHROPIC_API_KEY") if provider == "anthropic"
        else os.environ.get("OPENAI_API_KEY")
    )


def _configured_api_keys() -> set[str]:
    raw = os.environ.get("ARITIQ_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def _client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_credentials(
    x_api_key: Optional[str], authorization: Optional[str]
) -> tuple[str, str]:
    """Return (bearer, supplied) from the two credential headers."""
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    return bearer, (x_api_key or bearer)


def _api_key_ctx(request: Request, supplied: str) -> Optional[enterprise.AuthContext]:
    """AuthContext for an enterprise or legacy (ARITIQ_API_KEYS) key, or None."""
    ent_ctx = enterprise.authenticate(supplied)
    if ent_ctx is not None:
        _apply_rate_limit(f"key:{ent_ctx.api_key_id}", ent_ctx.limit_per_minute)
        enterprise.record_usage(ent_ctx, request.method, request.url.path)
        return ent_ctx
    if supplied and supplied in _configured_api_keys():
        with enterprise.connect() as conn:
            ctx = enterprise.ensure_default_workspace(conn)
        _apply_rate_limit(f"legacy:{supplied[:12]}", RATE_LIMIT_PER_MINUTE)
        return ctx
    return None


def _supabase_ctx(request: Request, bearer: str) -> Optional[enterprise.AuthContext]:
    """AuthContext for a verified Supabase session token, or None.

    Each Supabase account gets its OWN org+user (keyed by the token's `sub`),
    so audit history is isolated per user — never the shared default workspace.
    """
    payload = supabase_auth.verify_supabase_token(bearer) if bearer else None
    if payload is None:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    request.state.user_id = sub
    request.state.email = payload.get("email")
    with enterprise.connect() as conn:
        ctx = enterprise.ensure_supabase_workspace(
            conn, sub, email=payload.get("email")
        )
    _apply_rate_limit(f"user:{sub}", RATE_LIMIT_PER_MINUTE)
    return ctx


def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> enterprise.AuthContext:
    """Auth for data/history endpoints (/enterprise/*, /dashboard, /analyst,
    /timeline). Accepts an enterprise key, a legacy ARITIQ_API_KEYS key, or a
    signed-in Supabase user (scoped to their own workspace). Anonymous access
    is rejected unless ARITIQ_ALLOW_ANON_DEV is explicitly set for local dev.
    """
    bearer, supplied = _extract_credentials(x_api_key, authorization)

    ctx = _api_key_ctx(request, supplied)
    if ctx is not None:
        return ctx

    ctx = _supabase_ctx(request, bearer)
    if ctx is not None:
        return ctx

    if not supplied and ALLOW_ANON_DEV:
        with enterprise.connect() as conn:
            ctx = enterprise.ensure_default_workspace(conn)
        _apply_rate_limit(f"ip:{_client_id(request)}", RATE_LIMIT_PER_MINUTE)
        return ctx

    raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def require_user(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> enterprise.AuthContext:
    """Auth for endpoints that spend model tokens (/audit, /audit-multi,
    /audit-ticker). Enterprise/legacy API keys keep working for scripted
    access; everyone else must be a signed-in Supabase user, rate-limited per
    user id (burst + daily) rather than per IP. No anonymous fallback."""
    bearer, supplied = _extract_credentials(x_api_key, authorization)

    ctx = _api_key_ctx(request, supplied)
    if ctx is not None:
        return ctx

    ctx = _supabase_ctx(request, bearer)
    if ctx is not None:
        return ctx

    raise HTTPException(
        status_code=401,
        detail="Sign in with Google to run audits.",
    )


def _enforce_user_rate_limit(request: Request) -> None:
    """Burst + daily limits for Supabase users; exempt ARITIQ_UNLIMITED_EMAILS."""
    user_id = getattr(request.state, "user_id", None)
    email = (getattr(request.state, "email", None) or "").lower()
    if user_id and email not in UNLIMITED_EMAILS:
        try:
            rate_limit.check_rate_limit(user_id)
        except rate_limit.RateLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc))


def _apply_rate_limit(bucket_id: str, limit_per_minute: int) -> None:
    now = time.time()
    window_start = now - 60
    with _RATE_LOCK:
        bucket = [t for t in _RATE_BUCKETS.get(bucket_id, []) if t >= window_start]
        if len(bucket) >= int(limit_per_minute):
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
        bucket.append(now)
        _RATE_BUCKETS[bucket_id] = bucket


def _provider_key_name(provider: str) -> str:
    return {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get((provider or "").lower(), "")


def _model_kwargs(req) -> dict:
    out = {}
    if getattr(req, "provider", None):
        out["provider"] = req.provider
    if getattr(req, "model", None):
        out["model"] = req.model
    return out


@contextmanager
def _temporary_byok(provider: Optional[str], api_key: Optional[str]):
    """Use per-request model key without persisting it server-side."""
    if not api_key:
        yield
        return
    key_name = _provider_key_name(provider or os.environ.get("ARITIQ_PROVIDER") or "gemini")
    if not key_name:
        raise HTTPException(status_code=400, detail="Unsupported provider for BYOK.")
    with _BYOK_ENV_LOCK:
        previous = os.environ.get(key_name)
        os.environ[key_name] = api_key
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(key_name, None)
            else:
                os.environ[key_name] = previous


# ---------------------------------------------------------------------------
# Serialization: dataclasses -> the frontend's AuditResult shape
# ---------------------------------------------------------------------------

def _serialize_result(r: VerificationResult) -> dict:
    c = r.claim
    return {
        "status": r.status.value,
        "recomputed_value": r.recomputed_value,
        "delta": r.delta,
        "explanation": r.explanation,
        # ---- Phase 3 fields (None for ordinary per-claim verdicts) ----
        "caused_by": r.caused_by,
        "restatement_type": r.restatement_type.value if r.restatement_type else None,
        "claim": {
            "claim_text": c.claim_text,
            "operation": c.operation.value,
            "stated_value": c.stated_value,
            "unit": c.unit,
            "source_text": c.source_text,
            "node_id": c.node_id,
            "depends_on": list(c.depends_on),
            "operands": [
                {
                    "value": None if o.source.value == "missing" else o.value,
                    "source": o.source.value,
                    "source_text": o.source_text,
                    "source_span": list(o.source_span) if o.source_span else None,
                    "doc_id": o.doc_id,
                }
                for o in c.operands
            ],
        },
    }


def _serialize_audit(res) -> dict:
    return {
        "score": asdict(res.score),
        "results": [_serialize_result(r) for r in res.results],
        "issues": [{"message": getattr(i, "reason", str(i))} for i in res.issues],
        # Cross-document conflicts, surfaced separately for the UI (also in results).
        "conflicts": [_serialize_result(r) for r in getattr(res, "conflicts", [])],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class AuditRequest(BaseModel):
    source: str
    summary: str
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None

    @field_validator("source")
    @classmethod
    def _source_size(cls, v):
        if len(v or "") > MAX_SOURCE_CHARS:
            raise ValueError(f"source exceeds {MAX_SOURCE_CHARS} characters")
        return v

    @field_validator("summary")
    @classmethod
    def _summary_size(cls, v):
        if len(v or "") > MAX_SUMMARY_CHARS:
            raise ValueError(f"summary exceeds {MAX_SUMMARY_CHARS} characters")
        return v


class DocumentInput(BaseModel):
    doc_id: str
    text: str
    period: Optional[str] = None
    doc_type: Optional[str] = None

    @field_validator("text")
    @classmethod
    def _text_size(cls, v):
        if len(v or "") > MAX_SOURCE_CHARS:
            raise ValueError(f"document text exceeds {MAX_SOURCE_CHARS} characters")
        return v


class MultiAuditRequest(BaseModel):
    documents: list[DocumentInput]
    summary: str
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None

    @field_validator("summary")
    @classmethod
    def _summary_size(cls, v):
        if len(v or "") > MAX_SUMMARY_CHARS:
            raise ValueError(f"summary exceeds {MAX_SUMMARY_CHARS} characters")
        return v


class TickerAuditRequest(BaseModel):
    ticker: str
    # Optional: audit an AI summary against the fetched 10-K. If omitted, Aritiq
    # audits the filing's own INTERNAL CONSISTENCY (does the balance sheet
    # balance? does EPS reconcile? does cash tie out?) — which needs no summary.
    summary: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None

    @field_validator("summary")
    @classmethod
    def _ticker_summary_size(cls, v):
        if v is not None and len(v) > MAX_SUMMARY_CHARS:
            raise ValueError(f"summary exceeds {MAX_SUMMARY_CHARS} characters")
        return v


class BootstrapRequest(BaseModel):
    org_name: str = "Aritiq workspace"
    user_email: str
    user_name: Optional[str] = None
    key_label: str = "Initial key"
    limit_per_minute: int = RATE_LIMIT_PER_MINUTE


class ApiKeyCreateRequest(BaseModel):
    label: str = "API key"
    limit_per_minute: int = RATE_LIMIT_PER_MINUTE


class WatchlistCreateRequest(BaseModel):
    ticker: str


class WebhookCreateRequest(BaseModel):
    url: str
    secret: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "live_key": _has_live_key(), "examples": len(EXAMPLES)}


@app.get("/examples")
def examples():
    return EXAMPLES


@app.post("/enterprise/bootstrap")
def bootstrap_enterprise(req: BootstrapRequest):
    """Create first minimal team workspace plus initial API key.

    This is deliberately not OAuth or billing. It is a local/team bootstrap
    primitive for small SEC-research teams.
    """
    if not req.user_email.strip():
        raise HTTPException(status_code=400, detail="user_email required.")
    if req.limit_per_minute < 1:
        raise HTTPException(status_code=400, detail="limit_per_minute must be positive.")
    return enterprise.create_workspace(
        req.org_name,
        req.user_email,
        user_name=req.user_name,
        key_label=req.key_label,
        limit_per_minute=req.limit_per_minute,
    )


@app.get("/enterprise/team")
def enterprise_team(ctx: enterprise.AuthContext = Depends(require_api_key)):
    with enterprise.connect() as conn:
        org = conn.execute("SELECT id, name, created_at FROM orgs WHERE id = ?", (ctx.org_id,)).fetchone()
        users = conn.execute(
            "SELECT id, org_id, email, name, created_at FROM users WHERE org_id = ? ORDER BY id",
            (ctx.org_id,),
        ).fetchall()
    return {"org": dict(org), "users": [dict(u) for u in users], "auth": ctx.to_dict()}


@app.get("/enterprise/api-keys")
def enterprise_api_keys(ctx: enterprise.AuthContext = Depends(require_api_key)):
    return enterprise.api_key_dashboard(ctx.org_id)


@app.post("/enterprise/api-keys")
def enterprise_create_api_key(
    req: ApiKeyCreateRequest,
    ctx: enterprise.AuthContext = Depends(require_api_key),
):
    if req.limit_per_minute < 1:
        raise HTTPException(status_code=400, detail="limit_per_minute must be positive.")
    return enterprise.create_api_key(
        ctx.org_id,
        user_id=ctx.user_id,
        label=req.label,
        limit_per_minute=req.limit_per_minute,
    )


@app.post("/enterprise/api-keys/{key_id}/rotate")
def enterprise_rotate_api_key(key_id: int, ctx: enterprise.AuthContext = Depends(require_api_key)):
    try:
        return enterprise.rotate_api_key(key_id, ctx.org_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/enterprise/api-keys/{key_id}/deactivate")
def enterprise_deactivate_api_key(key_id: int, ctx: enterprise.AuthContext = Depends(require_api_key)):
    try:
        enterprise.deactivate_api_key(key_id, ctx.org_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "disabled", "id": key_id}


@app.get("/enterprise/audits")
def enterprise_audit_history(
    limit: int = 50,
    ctx: enterprise.AuthContext = Depends(require_api_key),
):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500.")
    return {"audits": enterprise.list_audits(ctx.org_id, limit=limit)}


@app.get("/enterprise/audits/{audit_id}")
def enterprise_audit_detail(audit_id: int, ctx: enterprise.AuthContext = Depends(require_api_key)):
    audit_record = enterprise.get_audit(ctx.org_id, audit_id)
    if not audit_record:
        raise HTTPException(status_code=404, detail="audit not found")
    return audit_record


@app.get("/enterprise/watchlists")
def enterprise_watchlists(ctx: enterprise.AuthContext = Depends(require_api_key)):
    return {"watchlists": enterprise.list_watchlists(ctx.org_id)}


@app.post("/enterprise/watchlists")
def enterprise_add_watchlist(
    req: WatchlistCreateRequest,
    ctx: enterprise.AuthContext = Depends(require_api_key),
):
    ticker = (req.ticker or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required.")
    return enterprise.add_watchlist(ctx.org_id, ticker)


@app.post("/enterprise/watchlists/check")
def enterprise_check_watchlists(ctx: enterprise.AuthContext = Depends(require_api_key)):
    detected = []
    for item in enterprise.list_watchlists(ctx.org_id):
        tl = get_timeline(item["ticker"], limit=1)
        if tl.fetch_error or not tl.events:
            enterprise.update_watchlist_seen(ctx.org_id, item["id"], item.get("last_seen_accession"))
            continue
        latest = tl.events[0]
        filing = {
            "form": latest.form,
            "filing_date": latest.filing_date,
            "report_date": latest.report_date,
            "accession": latest.accession,
            "items": latest.items,
            "verification_coverage": latest.verification_coverage,
            "document_url": latest.document_url(tl.cik) if tl.cik else None,
            "description": latest.primary_doc_description,
        }
        if item.get("last_seen_accession") and item.get("last_seen_accession") != latest.accession:
            queued = enterprise.enqueue_webhook_deliveries(
                ctx.org_id,
                watchlist_id=item["id"],
                ticker=item["ticker"],
                accession=latest.accession,
                filing=filing,
            )
            detected.append({"ticker": item["ticker"], "filing": filing, "webhooks_queued": queued})
        enterprise.update_watchlist_seen(ctx.org_id, item["id"], latest.accession)
    return {"detected": detected}


@app.get("/enterprise/webhooks")
def enterprise_webhooks(ctx: enterprise.AuthContext = Depends(require_api_key)):
    return {"webhooks": enterprise.list_webhooks(ctx.org_id)}


@app.post("/enterprise/webhooks")
def enterprise_add_webhook(
    req: WebhookCreateRequest,
    ctx: enterprise.AuthContext = Depends(require_api_key),
):
    if not req.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="webhook url must be http(s).")
    return enterprise.add_webhook(ctx.org_id, req.url, secret=req.secret)


@app.post("/enterprise/webhooks/dispatch")
def enterprise_dispatch_webhooks(ctx: enterprise.AuthContext = Depends(require_api_key)):
    return enterprise.dispatch_due_webhooks(ctx.org_id)


@app.post("/audit")
def audit_endpoint(
    req: AuditRequest,
    request: Request,
    ctx: enterprise.AuthContext = Depends(require_user),
):
    if not req.source.strip() or not req.summary.strip():
        raise HTTPException(status_code=400, detail="Both source and summary are required.")

    # 1) Bundled example -> deterministic replay (no API key needed).
    doc_id = REPLAY_INDEX.get((_norm(req.source), _norm(req.summary)))
    if doc_id is not None:
        res = run_audit(req.source, req.summary, complete_fn=_replay_fn_for(doc_id))
        payload = _serialize_audit(res)
        payload["audit_history_id"] = enterprise.store_audit(
            ctx, payload, source_label=f"example:{doc_id}"
        )
        return payload

    # Enforce rate limits for custom audits
    _enforce_user_rate_limit(request)

    # 2) Novel input -> live extraction (requires a key).
    if not _has_live_key() and not req.api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "No model API key configured on the server, so custom documents can't be "
                "audited yet. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY with "
                "ARITIQ_PROVIDER=openai) and restart the backend — or click “Load example” "
                "to try Aritiq with a bundled document, which needs no key."
            ),
        )

    try:
        with _temporary_byok(req.provider, req.api_key):
            res = run_audit(req.source, req.summary, **_model_kwargs(req))
    except Exception as exc:  # surface extractor/SDK errors as a clean 502
        raise HTTPException(status_code=502, detail=f"Extraction failed: {exc}")
    payload = _serialize_audit(res)
    payload["audit_history_id"] = enterprise.store_audit(ctx, payload, source_label="custom")
    return payload


@app.post("/audit-multi")
def audit_multi_endpoint(
    req: MultiAuditRequest,
    request: Request,
    _auth: enterprise.AuthContext = Depends(require_user),
):
    """Audit a summary against MULTIPLE labeled source documents (Phase 3).

    Unlike /audit, this builds a document registry so claims ground to the
    document they describe (not first-match across a concatenated blob), runs
    cross-statement checks per document, and surfaces cross-document CONFLICTs
    with restatement-disclosure classification.

    Requires a live model key (no replay path for arbitrary multi-doc input).
    """
    _enforce_user_rate_limit(request)

    if not req.documents or not req.summary.strip():
        raise HTTPException(status_code=400, detail="At least one document and a summary are required.")
    if not _has_live_key() and not req.api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "No model API key configured on the server, so multi-document audits "
                "can't run yet. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY with "
                "ARITIQ_PROVIDER=openai) and restart the backend."
            ),
        )
    docs = [
        SourceDoc(doc_id=d.doc_id, text=d.text, period=d.period, doc_type=d.doc_type)
        for d in req.documents
    ]
    try:
        with _temporary_byok(req.provider, req.api_key):
            res = run_audit_documents(docs, req.summary, **_model_kwargs(req))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Extraction failed: {exc}")
    return _serialize_audit(res)


@app.post("/audit-ticker")
def audit_ticker_endpoint(
    req: TickerAuditRequest,
    request: Request,
    ctx: enterprise.AuthContext = Depends(require_user),
):
    """Audit a company's latest 10-K by ticker — the "type AAPL, hit Audit" flow.

    Pure-Python EDGAR ingestion (no cost) fetches the filing and strips it to its
    financial-statements section; the audit then runs. With no `summary`, Aritiq
    checks the filing's OWN internal consistency (balance sheet, EPS, cash
    tie-out) — the strongest no-summary demo. With a `summary`, it audits that
    summary against the real filing.
    """
    _enforce_user_rate_limit(request)

    ticker = (req.ticker or "").strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="A ticker symbol is required.")

    # 1) Fetch + strip the 10-K (free; no API key needed for this step).
    try:
        filing, source_text = fetch_10k_text(ticker)
    except UnknownTickerError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NoFilingError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except EdgarError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch from SEC EDGAR: {exc}")

    # 2) The audit itself needs a model key (the extractor parses the filing).
    if not _has_live_key() and not req.api_key:
        provider = (os.environ.get("ARITIQ_PROVIDER") or "anthropic").lower()
        key_name = {
            "gemini": "GEMINI_API_KEY",
            "groq": "GROQ_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }.get(provider, "API key")
        raise HTTPException(
            status_code=503,
            detail=(
                f"Fetched {filing.company}'s {filing.filing_date} 10-K from SEC EDGAR, but "
                f"no model API key is configured on the server to parse it. Set "
                f"{key_name} and restart the backend."
            ),
        )

    # 3) Run the audit. No summary -> internal-consistency audit of the filing.
    summary = (req.summary or "").strip()
    try:
        with _temporary_byok(req.provider, req.api_key):
            if summary:
                res = run_audit(source_text, summary, **_model_kwargs(req))
            else:
                # Internal-consistency-only: the summary audit pass has nothing to
                # check, so we pass an empty summary; the cross-statement pass runs on
                # the filing's own numbers.
                res = run_audit(source_text, "", check_internal_consistency=True,
                                **_model_kwargs(req))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Audit failed: {exc}")

    payload = _serialize_audit(res)
    payload["filing"] = {
        "ticker": filing.ticker,
        "company": filing.company,
        "cik": filing.cik,
        "accession": filing.accession,
        "filing_date": filing.filing_date,
        "period": filing.period,
        "document_url": filing.document_url,
        "source_chars": len(source_text),
    }
    payload["audit_history_id"] = enterprise.store_audit(
        ctx,
        payload,
        ticker=filing.ticker,
        source_label=f"{filing.ticker} {filing.filing_date} 10-K",
    )
    return payload


_RELIABILITY_RUNS_DIR = os.path.join(
    ROOT, "benchmark", "reliability", "cache", "runs")


def _latest_replay_claim_records(ticker: str) -> Optional[list]:
    """Per-ticker claim records from the newest committed replay run, or None.

    Deterministic presentation data (verdicts + evidence flags the benchmark
    already produced) — no model call, no live extraction, no key needed.
    """
    import glob as _glob
    candidates = sorted(_glob.glob(os.path.join(_RELIABILITY_RUNS_DIR, "run_*.json")),
                        key=os.path.getmtime, reverse=True)
    for p in candidates:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        if d.get("schema") != "aritiq.reliability.run/v1" or d.get("mode") != "replay":
            continue
        for f in d.get("filings", []):
            if f.get("ticker", "").upper() == ticker.upper():
                return f.get("claims") or None
        return None  # newest replay run exists but has no such ticker
    return None


@app.get("/dashboard/{ticker}")
def dashboard_endpoint(ticker: str, _auth: None = Depends(require_api_key)):
    """Institutional risk dashboard (Phase 3 item 2) — deterministic panels
    over the newest benchmark replay's verdicts + cached company memory.

    Presentation only: verification score is core/score.py's AritiqScore,
    consistency comes from company_memory's comparability gates, and a panel
    with nothing to measure says UNASSESSED (restatement risk on a
    single-filing input is always unassessed — never rendered as 'low').
    Available for filers in the reliability benchmark cache; 404 otherwise.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="A ticker symbol is required.")
    records = _latest_replay_claim_records(ticker)
    if not records:
        raise HTTPException(
            status_code=404,
            detail=(f"No cached benchmark verdicts for {ticker}. The dashboard is "
                    "built from the reliability benchmark's replay data (83 cached "
                    "filers); run an audit first for other tickers."),
        )
    try:
        memory = build_company_memory(ticker)
    except Exception:
        memory = None  # panel reports 'unassessed' rather than the endpoint failing
    return build_dashboard(ticker, records, memory=memory).to_dict()


class AnalystRequest(BaseModel):
    ticker: str
    question: str
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None

    @field_validator("question")
    @classmethod
    def _question_size(cls, v):
        if len(v or "") > 2000:
            raise ValueError("question too long (max 2000 chars)")
        return v


@app.post("/analyst")
def analyst_endpoint(req: AnalystRequest, _auth: None = Depends(require_api_key)):
    """AI Analyst Mode (Phase 3 item 3) — answers ONLY from claims that passed
    verification, cites them, and refuses when the relevant number is blocked.

    The refusal gates are deterministic and run BEFORE any model call, so a
    question about an unverified number costs zero tokens and cannot be
    narrated over. Answers are validated against a verified-number whitelist;
    a fluent hallucination is rejected, not returned.
    """
    ticker = (req.ticker or "").strip().upper()
    question = (req.question or "").strip()
    if not ticker or not question:
        raise HTTPException(status_code=400,
                            detail="Both ticker and question are required.")
    records = _latest_replay_claim_records(ticker)
    if not records:
        raise HTTPException(
            status_code=404,
            detail=(f"No cached benchmark verdicts for {ticker}. Analyst mode "
                    "answers only over verified claims, and none are cached for "
                    "this ticker."),
        )
    ledger = ledger_from_records(records)

    # The deterministic refusal gates need no model. Try them first so blocked
    # questions work keyless (and cost nothing).
    def _sentinel(_s, _u):
        raise _NeedsModel()

    try:
        gate_check = ask_analyst(question, ledger, complete_fn=_sentinel)
        return gate_check.to_dict()   # a pre-model refusal was decided
    except _NeedsModel:
        pass                           # answerable — fall through to narration

    # An answerable question needs a model for narration.
    if not _has_live_key() and not req.api_key:
        raise HTTPException(
            status_code=503,
            detail=("This question is answerable from verified claims, but no "
                    "model API key is configured for narration. Set the "
                    "provider key or pass api_key."),
        )
    try:
        with _temporary_byok(req.provider, req.api_key):
            out = ask_analyst(question, ledger)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analyst failed: {exc}")
    return out.to_dict()


class _NeedsModel(Exception):
    """Internal sentinel: the analyst reached the model-call stage."""


@app.get("/timeline/{ticker}")
def timeline_endpoint(
    ticker: str,
    forms: Optional[str] = None,
    limit: int = 200,
    _auth: None = Depends(require_api_key),
):
    """Sequence a company's SEC filings by type and date (Phase 3 item 1).

    Every event carries a `verification_coverage` label, and the response ships
    the legend explaining exactly what Aritiq verifies per filing type — 10-K/
    10-Q measured, 8-K partial (Item 2.02 only), Form 4 ownership-data-only,
    everything else listed-only. The label travels WITH the data so no client
    can imply coverage that doesn't exist.
    """
    ticker = (ticker or "").strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="A ticker symbol is required.")
    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 5000.")
    form_list = [f for f in (forms or "").split(",") if f.strip()] or None

    tl = get_timeline(ticker, forms=form_list, limit=limit)
    if tl.fetch_error:
        status = 404 if "UnknownTicker" in tl.fetch_error else 502
        raise HTTPException(status_code=status, detail=tl.fetch_error)

    return {
        "ticker": tl.ticker,
        "cik": tl.cik,
        "name": tl.name,
        "has_older_filings": tl.has_older_filings,
        "coverage_legend": COVERAGE_LEGEND,
        "events": [
            {
                "form": e.form,
                "filing_date": e.filing_date,
                "report_date": e.report_date,
                "accession": e.accession,
                "items": e.items,
                "verification_coverage": e.verification_coverage,
                "document_url": e.document_url(tl.cik) if tl.cik else None,
                "description": e.primary_doc_description,
            }
            for e in tl.events
        ],
    }
