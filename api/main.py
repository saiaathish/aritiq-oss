"""FastAPI wrapper for the Aritiq audit pipeline.

Two extraction passes run behind one firewall (see aritiq.pipeline.audit):
  1. summary audit  (Phase 1) — trace the summary's numbers to the source.
  2. cross-statement (Phase 2) — check the source's own numbers agree.

Offline demo: a POST /audit whose text matches a known example is served from
saved replay fixtures (no API key), INCLUDING the Phase 2 cross-statement output
so internal-consistency claims actually appear. Unmatched requests fall through
to the live backend (ANTHROPIC_API_KEY / ARITIQ_PROVIDER), where both passes run
against the real model.
"""

import datetime as _dt
import io
import os
import tempfile

from fastapi import FastAPI, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from aritiq.pipeline import audit
from aritiq.export import export_csv, export_pdf, PDF_AVAILABLE

from .replays import find_replay, menu


class AuditRequest(BaseModel):
    source: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)


app = FastAPI(title="Aritiq API")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _normalize(result) -> dict:
    raw = jsonable_encoder(result)
    # Normalize issues: ExtractionIssue uses "reason"; frontend expects "message"
    raw["issues"] = [
        {"message": i.get("reason") or i.get("message", "unknown extraction error")}
        for i in raw.get("issues", [])
    ]
    return raw


@app.post("/audit")
def audit_summary(payload: AuditRequest) -> dict:
    replay = find_replay(payload.source, payload.summary)

    if replay is not None:
        # Offline replay — serve the saved model outputs. The two passes use
        # different prompts, so each gets its own fixture; cross-statement is
        # only run when a fixture exists for it.
        summary_fn, cs_fn = replay
        result = audit(
            payload.source,
            payload.summary,
            complete_fn=summary_fn,
            cs_complete_fn=cs_fn,
            check_internal_consistency=cs_fn is not None,
        )
    else:
        # Live path — real backend runs both passes (needs an API key).
        result = audit(payload.source, payload.summary)

    return _normalize(result)


def _run_audit(payload: "AuditRequest"):
    """Run an audit (replay if the input matches a known example, else live)."""
    replay = find_replay(payload.source, payload.summary)
    if replay is not None:
        summary_fn, cs_fn = replay
        return audit(payload.source, payload.summary, complete_fn=summary_fn,
                     cs_complete_fn=cs_fn, check_internal_consistency=cs_fn is not None)
    return audit(payload.source, payload.summary)


@app.post("/audit/export")
def audit_export(payload: AuditRequest, format: str = Query("csv", pattern="^(csv|pdf)$")):
    """Feature 3 — compliance export. Runs the audit and returns the per-claim
    audit trail as a downloadable CSV or PDF (deterministic; no LLM at export time).

    The API is stateless (audits are not persisted by id), so the export is produced
    from a fresh run of the same input rather than looked up — the exported record is
    exactly the verdicts the pipeline just produced.
    """
    result = _run_audit(payload)
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    meta = {"generated": ts, "provider": getattr(result, "provider", "") or "replay",
            "score": getattr(result.score, "score", None)}
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if format == "pdf":
        if not PDF_AVAILABLE:
            return Response(
                content="PDF export requires reportlab on the server; CSV is available.",
                status_code=503, media_type="text/plain")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            path = tf.name
        try:
            export_pdf(result.results, path, title="Aritiq Audit Report",
                       run_timestamp=ts, meta=meta)
            data = open(path, "rb").read()
        finally:
            os.unlink(path)
        return Response(content=data, media_type="application/pdf",
                        headers={"Content-Disposition":
                                 f'attachment; filename="aritiq_audit_{stamp}.pdf"'})

    # CSV (default) — build in a temp file then stream back.
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
        path = tf.name
    try:
        export_csv(result.results, path, run_timestamp=ts, meta=meta)
        data = open(path, "rb").read()
    finally:
        os.unlink(path)
    return Response(content=data, media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="aritiq_audit_{stamp}.csv"'})


@app.get("/examples")
def get_examples() -> list:
    return menu()
