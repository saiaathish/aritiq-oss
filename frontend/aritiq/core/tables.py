"""
Structured table extraction + unit/period normalization (§2.1, §2.2).

THIS FILE CONTAINS NO LLM CALLS.  It is deterministic parsing and arithmetic —
the "Stage 1 grows up" work the roadmap calls for, done in the deterministic
zone where Aritiq wants to grow.

Two jobs:

  1. parse_markdown_table(text) -> List[TableCell]
     Don't flatten tables to prose.  Parse a pipe/markdown table into
     (row_label, column_label, value, unit_footnote) cells.  The LITERAL header
     and row-label strings are preserved on each cell so a header
     mis-attribution (off-by-one row in a dense table — named failure §7) is
     auditable, exactly as operand grounding already is.

  2. normalize_value(...) / normalize_cells(...)
     "$1.2B" vs "$1,200M" vs a cell that's implicitly "in thousands" are the
     same number in different costumes.  Convert everything to a canonical scale
     BEFORE the verifier ever sees it.  This is more code in the deterministic
     zone, which is the right direction to grow.

A reviewer can read this top to bottom and confirm: no model, just text→numbers.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .schema import TableCell


# ---------------------------------------------------------------------------
# 1. Table parsing
# ---------------------------------------------------------------------------

# A scale footnote like "(in thousands)" or "in millions, except per-share data".
_SCALE_FOOTNOTE_RE = re.compile(
    r"in\s+(thousands|millions|billions)", re.IGNORECASE
)


def _detect_scale_footnote(text: str) -> Optional[str]:
    """Return a normalized scale-footnote string if the text declares one."""
    m = _SCALE_FOOTNOTE_RE.search(text or "")
    if m:
        return f"in {m.group(1).lower()}"
    return None


def _parse_number(cell_text: str) -> Optional[float]:
    """Parse a single table cell into a float, or None if it isn't numeric.

    Handles $, commas, %, and parenthesized negatives — the accounting
    convention where (1,234) means -1234.  Does NOT expand magnitude suffixes
    here; that's normalize_value's explicit job, so scale conversions stay
    visible and in one place.
    """
    s = (cell_text or "").strip()
    if not s:
        return None
    neg = False
    # Parenthesized negative: (1,234) -> -1234
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(",", "").replace("$", "").replace("%", "").strip()
    if not re.fullmatch(r"-?\d*\.?\d+", s):
        return None
    val = float(s)
    return -val if neg else val


def parse_markdown_table(
    text: str,
    table_caption: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> List[TableCell]:
    """Parse a pipe-delimited / markdown table into TableCells.

    Conventions (matching how 10-K excerpts are typically pasted):
      - The first non-separator row is the HEADER (its cells are column labels).
      - The first column of each body row is the ROW LABEL.
      - A markdown separator row (---|---) is ignored.
      - A scale footnote ("in thousands") found in the caption OR in any line of
        the text is attached to every cell as unit_footnote.

    Each numeric body cell becomes a TableCell(row_label, column_label, value).
    Non-numeric cells are skipped (e.g. a blank or a textual note).
    """
    scale = _detect_scale_footnote(text)
    if scale is None and table_caption:
        scale = _detect_scale_footnote(table_caption)

    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    # Keep only lines that look like table rows (contain a pipe).
    rows = [ln for ln in lines if "|" in ln]
    if len(rows) < 2:
        return []

    def split_row(ln: str) -> List[str]:
        # Strip leading/trailing pipes then split.
        parts = ln.strip().strip("|").split("|")
        return [p.strip() for p in parts]

    # Find the header: first row that is not a markdown separator.
    header_idx = 0
    for i, ln in enumerate(rows):
        cells = split_row(ln)
        if all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c):
            continue  # separator
        header_idx = i
        break

    header = split_row(rows[header_idx])
    if not header:
        return []
    column_labels = header[1:]  # first header cell is the corner / row-label header

    cells_out: List[TableCell] = []
    for ln in rows[header_idx + 1:]:
        cells = split_row(ln)
        if all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c):
            continue  # separator row inside body
        if not cells:
            continue
        row_label = cells[0]
        for ci, raw in enumerate(cells[1:]):
            value = _parse_number(raw)
            if value is None:
                continue
            col_label = column_labels[ci] if ci < len(column_labels) else f"col{ci}"
            cells_out.append(
                TableCell(
                    row_label=row_label,
                    column_label=col_label,
                    value=value,
                    unit_footnote=scale,
                    doc_id=doc_id,
                )
            )
    return cells_out


def find_cell(
    cells: List[TableCell],
    row_label: str,
    column_label: Optional[str] = None,
) -> Optional[TableCell]:
    """Locate a cell by (case-insensitive, trimmed) labels. None if not found.

    Matching is deterministic, not fuzzy model matching, and prefers precision:
      1. an EXACT row-label match wins over a substring match — so a lookup for
         "Cash and cash equivalents" returns the balance-sheet row, not the
         cash-flow row "Cash and cash equivalents, end" that merely contains it;
      2. only if no exact match exists do we fall back to a substring match
         (so "Total assets" still finds "Total assets, net").
    Column match, when given, is exact (trimmed, lowercased).
    """
    rl = row_label.strip().lower()
    cl = column_label.strip().lower() if column_label is not None else None

    def col_ok(c: TableCell) -> bool:
        return cl is None or cl == c.column_label.strip().lower()

    # Pass 1: exact row-label match.
    for c in cells:
        if c.row_label.strip().lower() == rl and col_ok(c):
            return c
    # Pass 2: substring fallback.
    for c in cells:
        if rl in c.row_label.strip().lower() and col_ok(c):
            return c
    return None


# ---------------------------------------------------------------------------
# 2. Unit / period normalization
# ---------------------------------------------------------------------------

# Canonical money scale used across Aritiq operands: millions ($M).
# (Phase 1 prompt already normalizes prose money to "$M"; we match that so a
# table-grounded operand and a prose-grounded operand are directly comparable.)
_SUFFIX_TO_MILLIONS = {
    "k": 1e-3, "thousand": 1e-3, "thousands": 1e-3,
    "m": 1.0, "mm": 1.0, "million": 1.0, "millions": 1.0,
    "b": 1e3, "bn": 1e3, "billion": 1e3, "billions": 1e3,
    "t": 1e6, "trillion": 1e6, "trillions": 1e6,
}

_MONEY_RE = re.compile(
    r"^\s*\$?\s*(-?\d[\d,]*\.?\d*)\s*(k|mm|m|bn|b|t|thousand|thousands|million|"
    r"millions|billion|billions|trillion|trillions)?\s*$",
    re.IGNORECASE,
)


def normalize_money_to_millions(raw: str) -> Optional[float]:
    """Convert a money string to a float in MILLIONS, or None if unparseable.

    "$1.2B" -> 1200.0 ; "$1,200M" -> 1200.0 ; "$500,000K" -> 500.0 ;
    a bare "125" with no suffix is assumed already in millions (the Aritiq
    operand convention) and returned as 125.0.
    """
    m = _MONEY_RE.match(raw or "")
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    factor = _SUFFIX_TO_MILLIONS.get(suffix, 1.0) if suffix else 1.0
    return num * factor


def apply_scale_footnote_to_millions(value: float, unit_footnote: Optional[str]) -> float:
    """Rescale a raw table value into MILLIONS using its scale footnote.

    A cell value of 1,234 under "in thousands" is 1.234 in millions; under
    "in billions" it's 1234 in millions.  No footnote -> assume the value is
    already in the canonical scale and return unchanged.
    """
    if not unit_footnote:
        return value
    foot = unit_footnote.lower()
    if "thousand" in foot:
        return value * 1e-3
    if "billion" in foot:
        return value * 1e3
    if "million" in foot:
        return value  # already millions
    return value


# Row labels that denote a PER-SHARE figure, which the standard footnote
# "in thousands, except per-share data" deliberately exempts from rescaling.
# A blind rescale of EPS would corrupt the eps_reconciliation check (EPS is
# already in dollars/share; multiplying it by 1e-3 makes 2.00 into 0.002).
_PER_SHARE_HINTS = ("per share", "per-share", "eps", "earnings per")


def _is_per_share(row_label: str) -> bool:
    low = (row_label or "").lower()
    return any(h in low for h in _PER_SHARE_HINTS)


def normalize_cells_to_millions(cells: List[TableCell]) -> List[TableCell]:
    """Return new TableCells with values rescaled to millions per their footnote.

    The original labels and footnote are preserved (so the audit trail still
    shows what the source literally said); only the value is canonicalized.

    IMPORTANT: per-share rows (EPS, "... per share") are NOT rescaled. The
    canonical footnote is "in thousands, EXCEPT per-share data" — honoring that
    exception is exactly the kind of unit subtlety that, if ignored, would make
    eps_reconciliation produce false WRONG_MATH. Respecting it is correct, and
    it is done in the deterministic zone where such rules belong.
    """
    out: List[TableCell] = []
    for c in cells:
        rescaled = c.value if _is_per_share(c.row_label) else \
            apply_scale_footnote_to_millions(c.value, c.unit_footnote)
        out.append(
            TableCell(
                row_label=c.row_label,
                column_label=c.column_label,
                value=rescaled,
                unit_footnote=c.unit_footnote,
                doc_id=c.doc_id,
            )
        )
    return out
