"""
Audit-trail / compliance export regression suite (Feature 3).

Covers:
  (a) rows_from_results flattens a VerificationResult faithfully — verdict, operands,
      source citations, recomputed value, delta, and timestamp — with NO recomputation
      and NO change to the verdict;
  (b) export_csv writes a well-formed CSV with the meta header and one row per claim;
  (c) INSUFFICIENT_EVIDENCE / non-VERIFIED verdicts export exactly as ruled (the
      export never launders a decline into a pass);
  (d) export_pdf produces a real PDF when reportlab is present, and raises a clear
      ImportError (never a silent failure) when it is not.

Offline / synthetic — no network, no LLM.
"""
import csv
import os
import tempfile

import pytest

from aritiq.core.schema import (
    Claim, Operation, Operand, OperandSource, VerificationResult, VerificationStatus,
)
from aritiq.export import (
    rows_from_results, export_csv, export_pdf, PDF_AVAILABLE, CSV_COLUMNS,
)


def _result(verdict, stated=None, recomputed=None, delta=None, explanation="",
            operands=None, claim_text="test claim", rule="balance_sheet_identity"):
    claim = Claim(
        claim_text=claim_text, operation=Operation.INTERNAL_CONSISTENCY,
        stated_value=stated, rule_name=rule,
        operands=operands or [
            Operand(value=100.0, source=OperandSource.GROUNDED,
                    category="total_assets", source_text="XBRL Assets"),
            Operand(value=60.0, source=OperandSource.GROUNDED,
                    category="total_liabilities", source_text="XBRL Liabilities"),
        ],
        source_text="XBRL tags",
    )
    return VerificationResult(claim=claim, status=verdict, recomputed_value=recomputed,
                              delta=delta, explanation=explanation)


def test_rows_are_faithful_to_the_verdict():
    results = [
        _result(VerificationStatus.VERIFIED, stated=100.0, recomputed=100.0, delta=0.0,
                explanation="within tolerance"),
        _result(VerificationStatus.WRONG_MATH, stated=999.0, recomputed=160.0,
                delta=839.0, explanation="recomputation disagrees", claim_text="bad claim"),
    ]
    rows = rows_from_results(results)
    assert len(rows) == 2
    assert rows[0].verdict == "VERIFIED"
    assert rows[1].verdict == "WRONG_MATH"
    # operands + their source citations are carried, not dropped
    assert "100" in rows[0].operands and "60" in rows[0].operands
    assert "total_assets" in rows[0].operand_sources
    assert "XBRL Assets" in rows[0].operand_sources
    assert rows[1].recomputed_value == "160"
    assert rows[1].delta == "839"
    assert rows[0].run_timestamp  # a timestamp is always stamped


def test_export_csv_is_wellformed_with_meta():
    results = [_result(VerificationStatus.VERIFIED, recomputed=100.0)]
    d = tempfile.mkdtemp()
    path = os.path.join(d, "audit.csv")
    export_csv(results, path, meta={"ticker": "TEST", "period_end": "2024-12-31"})
    text = open(path).read()
    assert text.startswith("# ticker: TEST")
    assert "# period_end: 2024-12-31" in text
    # parse the data rows (skip comment lines) and check columns + row count
    data_lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    reader = csv.DictReader(data_lines)
    assert reader.fieldnames == CSV_COLUMNS
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "VERIFIED"


def test_insufficient_evidence_exports_as_is_never_laundered():
    """The export must transcribe a decline exactly — it must never turn an
    INSUFFICIENT_EVIDENCE (or any non-pass) into a VERIFIED."""
    results = [_result(VerificationStatus.INSUFFICIENT_EVIDENCE,
                       explanation="declined: restricted cash disclosed")]
    d = tempfile.mkdtemp()
    path = os.path.join(d, "audit.csv")
    export_csv(results, path)
    data = [ln for ln in open(path).read().splitlines() if not ln.startswith("#")]
    row = list(csv.DictReader(data))[0]
    assert row["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert row["recomputed_value"] == ""   # nothing recomputed on a decline
    assert "declined" in row["explanation"]


def test_propagated_error_carries_caused_by():
    r = _result(VerificationStatus.PROPAGATED_ERROR, explanation="upstream broke")
    r.caused_by = "node-7"
    rows = rows_from_results([r])
    assert rows[0].verdict == "PROPAGATED_ERROR"
    assert rows[0].caused_by == "node-7"


@pytest.mark.skipif(not PDF_AVAILABLE, reason="reportlab not installed")
def test_export_pdf_writes_a_real_pdf():
    results = [
        _result(VerificationStatus.VERIFIED, recomputed=100.0, explanation="ok"),
        _result(VerificationStatus.WRONG_MATH, recomputed=160.0, delta=839.0,
                explanation="disagrees"),
    ]
    d = tempfile.mkdtemp()
    path = os.path.join(d, "audit.pdf")
    export_pdf(results, path, title="Test Audit", meta={"ticker": "TEST"})
    assert os.path.exists(path)
    with open(path, "rb") as fh:
        assert fh.read(5) == b"%PDF-"   # real PDF magic bytes
    assert os.path.getsize(path) > 500


def test_export_pdf_raises_clear_error_when_unavailable(monkeypatch):
    """If reportlab is absent, export_pdf must raise a clear ImportError — never fail
    silently or produce a broken file."""
    import aritiq.export.audit_export as ae
    monkeypatch.setattr(ae, "PDF_AVAILABLE", False)
    with pytest.raises(ImportError) as exc:
        ae.export_pdf([_result(VerificationStatus.VERIFIED)], "/tmp/never.pdf")
    assert "reportlab" in str(exc.value)
