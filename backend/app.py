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

GOLD_PATH = os.path.join(ROOT, "benchmark", "gold_set.json")
RUNS_DIR = os.path.join(ROOT, "benchmark", "runs")

app = FastAPI(title="Aritiq API", version="0.1.0")

MAX_SOURCE_CHARS = int(os.environ.get("ARITIQ_MAX_SOURCE_CHARS", "250000"))
MAX_SUMMARY_CHARS = int(os.environ.get("ARITIQ_MAX_SUMMARY_CHARS", "20000"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("ARITIQ_RATE_LIMIT_PER_MINUTE", "30"))
_RATE_BUCKETS: dict[str, list[float]] = {}
_RATE_LOCK = threading.Lock()
_BYOK_ENV_LOCK = threading.Lock()

# Dev CORS: allow any localhost port (Next defaults to 3000).
app.add_middleware(
    CORSMiddleware,
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


def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> None:
    keys = _configured_api_keys()
    if keys:
        bearer = ""
        if authorization and authorization.lower().startswith("bearer "):
            bearer = authorization.split(" ", 1)[1].strip()
        supplied = x_api_key or bearer
        if supplied not in keys:
            raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    now = time.time()
    window_start = now - 60
    cid = _client_id(request)
    with _RATE_LOCK:
        bucket = [t for t in _RATE_BUCKETS.get(cid, []) if t >= window_start]
        if len(bucket) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
        bucket.append(now)
        _RATE_BUCKETS[cid] = bucket


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
def health():
    return {"status": "ok", "live_key": _has_live_key(), "examples": len(EXAMPLES)}


@app.get("/examples")
def examples():
    return EXAMPLES


@app.post("/audit")
def audit_endpoint(req: AuditRequest, _auth: None = Depends(require_api_key)):
    if not req.source.strip() or not req.summary.strip():
        raise HTTPException(status_code=400, detail="Both source and summary are required.")

    # 1) Bundled example -> deterministic replay (no API key needed).
    doc_id = REPLAY_INDEX.get((_norm(req.source), _norm(req.summary)))
    if doc_id is not None:
        res = run_audit(req.source, req.summary, complete_fn=_replay_fn_for(doc_id))
        return _serialize_audit(res)

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
    return _serialize_audit(res)


@app.post("/audit-multi")
def audit_multi_endpoint(req: MultiAuditRequest, _auth: None = Depends(require_api_key)):
    """Audit a summary against MULTIPLE labeled source documents (Phase 3).

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
def audit_ticker_endpoint(req: TickerAuditRequest, _auth: None = Depends(require_api_key)):
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
    return payload
