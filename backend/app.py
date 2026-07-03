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
For the bundled examples we replay saved extraction outputs, so the demo works
with NO API key. For any other (source, summary), we call the real extractor,
which needs your own model key (BYOK) — configure it in a .env file; see
.env.example. If no key is set and the input isn't a bundled example, /audit
returns a clear 503 the UI renders in its error banner.

Run:
    pip install -r backend/requirements.txt
    uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import threading
import re
import sys
from contextlib import contextmanager
from dataclasses import asdict
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
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
from aritiq import config  # noqa: E402
import aritiq.enterprise as enterprise  # noqa: E402

# Load BYOK settings (.env) into the environment. See aritiq/config.py.
config.load()

GOLD_PATH = os.path.join(ROOT, "benchmark", "gold_set.json")
RUNS_DIR = os.path.join(ROOT, "benchmark", "runs")

app = FastAPI(title="Aritiq API", version="0.1.0")

MAX_SOURCE_CHARS = int(os.environ.get("ARITIQ_MAX_SOURCE_CHARS", "250000"))
MAX_SUMMARY_CHARS = int(os.environ.get("ARITIQ_MAX_SUMMARY_CHARS", "20000"))
_BYOK_ENV_LOCK = threading.Lock()

# CORS: this runs locally, so allow any localhost port (the Next.js dev server
# defaults to :3000). Add extra origins via ARITIQ_ALLOWED_ORIGINS if you host
# the UI elsewhere.
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
    """True when a model key is configured for the selected provider."""
    return config.has_key()


# Everything runs locally, so there is no sign-in and no multi-tenant identity.
# All requests share a single local workspace (used only for optional on-disk
# audit history in a local SQLite file under your XDG state dir).
def local_ctx() -> enterprise.AuthContext:
    with enterprise.connect() as conn:
        return enterprise.ensure_default_workspace(conn)


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
    key_name = _provider_key_name(provider or config.provider())
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
        # ---- multi-document fields (None for ordinary per-claim verdicts) ----
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


@app.get("/health")
@app.head("/health")
def health():
    return {"status": "ok", "live_key": _has_live_key(), "examples": len(EXAMPLES)}


@app.get("/examples")
def examples():
    return EXAMPLES


@app.post("/audit")
def audit_endpoint(
    req: AuditRequest,
    request: Request,
    ctx: enterprise.AuthContext = Depends(local_ctx),
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


    # 2) Novel input -> live extraction (requires a key).
    if not _has_live_key() and not req.api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "No model API key configured, so custom documents can't be audited "
                "yet. Set your provider and key in a .env file (see .env.example) and "
                "restart the backend — or click “Load example” to try Aritiq with a "
                "bundled document, which needs no key."
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
    _auth: enterprise.AuthContext = Depends(local_ctx),
):
    """Audit a summary against MULTIPLE labeled source documents (multi-document).

    Unlike /audit, this builds a document registry so claims ground to the
    document they describe (not first-match across a concatenated blob), runs
    cross-statement checks per document, and surfaces cross-document CONFLICTs
    with restatement-disclosure classification.

    Requires a live model key (no replay path for arbitrary multi-doc input).
    """

    if not req.documents or not req.summary.strip():
        raise HTTPException(status_code=400, detail="At least one document and a summary are required.")
    if not _has_live_key() and not req.api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "No model API key configured, so multi-document audits can't run "
                "yet. Set your provider and key in a .env file (see .env.example) and "
                "restart the backend."
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
    ctx: enterprise.AuthContext = Depends(local_ctx),
):
    """Audit a company's latest 10-K by ticker — the "type AAPL, hit Audit" flow.

    Pure-Python EDGAR ingestion (no cost) fetches the filing and strips it to its
    financial-statements section; the audit then runs. With no `summary`, Aritiq
    checks the filing's OWN internal consistency (balance sheet, EPS, cash
    tie-out) — the strongest no-summary demo. With a `summary`, it audits that
    summary against the real filing.
    """

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
def dashboard_endpoint(ticker: str, _auth: None = Depends(local_ctx)):
    """Institutional risk dashboard (the risk dashboard) — deterministic panels
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
def analyst_endpoint(req: AnalystRequest, _auth: None = Depends(local_ctx)):
    """AI Analyst Mode (analyst mode) — answers ONLY from claims that passed
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
    _auth: None = Depends(local_ctx),
):
    """Sequence a company's SEC filings by type and date (filing-timeline).

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
