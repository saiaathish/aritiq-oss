"""
Audit-trail / compliance export (Feature 3).

Renders an audit's per-claim record — the data that ALREADY EXISTS on every
VerificationResult / Claim — into two archival formats compliance and audit teams
retain:

  * CSV  — one row per claim: claim text, operation/rule, operands with values and
           source citations, verdict, recomputed value, delta, explanation, and a
           run timestamp. Pure stdlib `csv`; always available.
  * PDF  — the same record formatted for human review, generated deterministically
           with reportlab (no LLM). Optional dependency: if reportlab isn't
           installed, export_pdf raises a clear ImportError and CSV still works.

This is a PRESENTATION layer. It performs NO arithmetic and makes NO verdict — it
reports exactly what the verifier already decided. It lives OUTSIDE aritiq/core/ (it
is I/O, not verification) and imports only the schema types, so it cannot affect a
verdict. No model SDK is imported.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

# Type-only imports (no verification logic, no arithmetic).
from ..core.schema import VerificationResult, Claim, Operand

try:  # PDF is an optional capability
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    PDF_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only where reportlab is absent
    PDF_AVAILABLE = False


CSV_COLUMNS = [
    "row", "claim_text", "operation", "rule_name", "eps_variant",
    "operands", "operand_sources", "stated_value", "verdict",
    "recomputed_value", "delta", "caused_by", "explanation",
    "source_text", "run_timestamp",
]


def _fmt_num(x: Optional[float]) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return f"{x:.6g}"


def _operand_str(o: Operand) -> str:
    return _fmt_num(o.value)


def _operand_source_str(o: Operand) -> str:
    """A human-readable provenance string for one operand — its source citation."""
    bits = []
    if o.category:
        bits.append(o.category)
    if o.source_text:
        bits.append(o.source_text)
    if o.doc_id:
        bits.append(f"doc={o.doc_id}")
    src = getattr(o.source, "value", str(o.source))
    tail = f" [{src}]" if src else ""
    return ("; ".join(bits) + tail).strip() if bits else src


@dataclass
class AuditRow:
    """One flattened, export-ready record for a single verified claim."""
    row: int
    claim_text: str
    operation: str
    rule_name: str
    eps_variant: str
    operands: str            # e.g. "100 | 112"
    operand_sources: str     # e.g. "total_assets [grounded]; ..."
    stated_value: str
    verdict: str
    recomputed_value: str
    delta: str
    caused_by: str
    explanation: str
    source_text: str
    run_timestamp: str

    def as_dict(self) -> dict:
        return {c: getattr(self, c) for c in CSV_COLUMNS}


def rows_from_results(
    results: Sequence[VerificationResult],
    *,
    run_timestamp: Optional[str] = None,
) -> List[AuditRow]:
    """Flatten VerificationResults into export rows. Reads only what the verifier
    already produced — no recomputation."""
    ts = run_timestamp or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    rows: List[AuditRow] = []
    for i, r in enumerate(results, start=1):
        c: Claim = r.claim
        ops = c.operands or []
        rows.append(AuditRow(
            row=i,
            claim_text=c.claim_text or "",
            operation=getattr(c.operation, "value", str(c.operation)),
            rule_name=c.rule_name or "",
            eps_variant=getattr(c.eps_variant, "value", "") if c.eps_variant else "",
            operands=" | ".join(_operand_str(o) for o in ops),
            operand_sources="; ".join(_operand_source_str(o) for o in ops),
            stated_value=_fmt_num(c.stated_value),
            verdict=getattr(r.status, "value", str(r.status)),
            recomputed_value=_fmt_num(r.recomputed_value),
            delta=_fmt_num(r.delta),
            caused_by=r.caused_by or "",
            explanation=(r.explanation or "").strip(),
            source_text=(c.source_text or "").strip(),
            run_timestamp=ts,
        ))
    return rows


def export_csv(
    results: Sequence[VerificationResult],
    path: str,
    *,
    run_timestamp: Optional[str] = None,
    meta: Optional[dict] = None,
) -> str:
    """Write the audit record as CSV (one row per claim). Returns the path.

    `meta` (optional) is written as leading `# key: value` comment lines — e.g. the
    ticker, the Aritiq score, the run timestamp — so the file is self-describing for
    an archive without needing a separate manifest.
    """
    rows = rows_from_results(results, run_timestamp=run_timestamp)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        if meta:
            for k, v in meta.items():
                fh.write(f"# {k}: {v}\n")
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r.as_dict())
    return path


def export_pdf(
    results: Sequence[VerificationResult],
    path: str,
    *,
    title: str = "Aritiq Audit Report",
    run_timestamp: Optional[str] = None,
    meta: Optional[dict] = None,
) -> str:
    """Render the audit record as a human-review PDF (deterministic, no LLM).

    Raises ImportError if reportlab is not installed — CSV export is always
    available and requires no third-party package.
    """
    if not PDF_AVAILABLE:
        raise ImportError(
            "PDF export requires reportlab (`pip install reportlab`). "
            "CSV export (export_csv) has no third-party dependency.")

    ts = run_timestamp or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    rows = rows_from_results(results, run_timestamp=ts)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7, leading=8.5)
    small_mono = ParagraphStyle("mono", parent=small, fontName="Courier", fontSize=6.5)
    head = ParagraphStyle("th", parent=small, textColor=colors.white, fontSize=7,
                          fontName="Helvetica-Bold")

    doc = SimpleDocTemplate(path, pagesize=landscape(letter),
                            leftMargin=0.4 * inch, rightMargin=0.4 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title=title)
    story: List[Any] = [Paragraph(title, styles["Title"])]
    story.append(Paragraph(f"Generated: {ts} (UTC) — deterministic export; "
                           f"no reasoning or arithmetic performed at export time.",
                           styles["Italic"]))
    if meta:
        meta_txt = " &nbsp;•&nbsp; ".join(f"<b>{k}:</b> {v}" for k, v in meta.items())
        story.append(Paragraph(meta_txt, small))
    story.append(Spacer(1, 8))

    # verdict tally so a reviewer sees the shape at a glance
    tally: dict = {}
    for r in rows:
        tally[r.verdict] = tally.get(r.verdict, 0) + 1
    story.append(Paragraph("Verdict tally: " +
                           ", ".join(f"{k}={v}" for k, v in sorted(tally.items())), small))
    story.append(Spacer(1, 8))

    # Verdict color coding for quick scanning (presentation only).
    verdict_color = {
        "VERIFIED": colors.HexColor("#1b7f37"),
        "WRONG_MATH": colors.HexColor("#b00020"),
        "INSUFFICIENT_EVIDENCE": colors.HexColor("#8a6d00"),
        "PROPAGATED_ERROR": colors.HexColor("#8a6d00"),
        "CONFLICT": colors.HexColor("#b00020"),
    }

    header = ["#", "Claim", "Op / Rule", "Operands", "Sources", "Stated",
              "Verdict", "Recomputed", "Δ", "Explanation"]
    data: List[List[Any]] = [[Paragraph(h, head) for h in header]]
    for r in rows:
        vstyle = ParagraphStyle("v", parent=small,
                                textColor=verdict_color.get(r.verdict, colors.black),
                                fontName="Helvetica-Bold")
        data.append([
            Paragraph(str(r.row), small),
            Paragraph(r.claim_text, small),
            Paragraph(f"{r.operation}<br/>{r.rule_name}", small),
            Paragraph(r.operands, small_mono),
            Paragraph(r.operand_sources, small),
            Paragraph(r.stated_value, small_mono),
            Paragraph(r.verdict, vstyle),
            Paragraph(r.recomputed_value, small_mono),
            Paragraph(r.delta, small_mono),
            Paragraph(r.explanation, small),
        ])

    col_widths = [0.3, 2.15, 1.0, 1.1, 1.7, 0.55, 1.15, 0.9, 0.5, 2.25]
    table = Table(data, colWidths=[w * inch for w in col_widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222b45")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f6fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Every row is a claim the deterministic verifier already ruled on. This "
        "document is a faithful transcript of those rulings for audit retention — it "
        "does not re-decide anything.", styles["Italic"]))
    doc.build(story)
    return path
