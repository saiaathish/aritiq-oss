"""
Phase 3 / Move 2 test suite — restatement DISCLOSURE-LANGUAGE classification.

Constructed ground truth, no LLM. The classifier is a deterministic context-
string lookup, so these tests pin exact behavior, including the boundary case the
spec flags as most likely to over-fire.

The spec's three required cases:
  * Unit: "(restated)" in the grounding context of the later figure
    -> EXPLICIT_RESTATEMENT.
  * Unit: no nearby disclosure text at all -> UNEXPLAINED (NOT a guess).
  * Negative: a CONFLICT whose nearby text mentions "reclassification" only in an
    UNRELATED, far-away sentence must NOT be mis-tagged.

Framing the suite also encodes: this detects disclosure LANGUAGE near a conflict,
never "what kind of restatement occurred".
"""
import pytest

from aritiq.core.registry import FigureConflict
from aritiq.core.restatement import (
    classify_restatement,
    classify_conflict_context,
    DEFAULT_CONTEXT_WINDOW,
)
from aritiq.core.schema import RestatementType, SourceDocument


def conflict(va=200.0, vb=210.0):
    return FigureConflict(
        row_label="Net income", column_label="Q3",
        doc_a="10Q", value_a=va, doc_b="PR", value_b=vb,
    )


# ===========================================================================
# Explicit restatement language -> EXPLICIT_RESTATEMENT
# ===========================================================================

class TestExplicitRestatement:
    def test_as_restated_in_context_string(self):
        out = classify_restatement(
            conflict(),
            context="Net income for the quarter, as restated, was 210.",
        )
        assert out.restatement_type == RestatementType.EXPLICIT_RESTATEMENT
        assert out.matched_disclosure_text == "as restated"

    def test_restated_in_later_doc_prose(self):
        doc = SourceDocument(
            doc_id="PR",
            text="Net income (restated) for Q3 was 210, up from the prior figure.",
        )
        out = classify_restatement(conflict(), later_doc=doc)
        assert out.restatement_type == RestatementType.EXPLICIT_RESTATEMENT
        assert out.matched_disclosure_text == "restated"

    def test_previously_reported_counts_as_explicit(self):
        out = classify_restatement(
            conflict(),
            context="This differs from the 200 previously reported in the 10-Q.",
        )
        assert out.restatement_type == RestatementType.EXPLICIT_RESTATEMENT

    def test_explicit_outranks_reclassification(self):
        # Both words present near the figure -> the stronger signal wins.
        out = classify_restatement(
            conflict(),
            context="Amounts were reclassified and the total was restated to 210.",
        )
        assert out.restatement_type == RestatementType.EXPLICIT_RESTATEMENT


# ===========================================================================
# Reclassification language -> POSSIBLE_RECLASSIFICATION (a narrow claim)
# ===========================================================================

class TestPossibleReclassification:
    def test_reclassified_to_conform(self):
        out = classify_restatement(
            conflict(),
            context="Prior amounts were reclassified to conform to current presentation; the figure is 210.",
        )
        assert out.restatement_type == RestatementType.POSSIBLE_RECLASSIFICATION
        assert out.matched_disclosure_text is not None

    def test_segment_realignment_language(self):
        out = classify_restatement(
            conflict(),
            context="Following the segment realignment, the comparable figure is 210.",
        )
        assert out.restatement_type == RestatementType.POSSIBLE_RECLASSIFICATION


# ===========================================================================
# No disclosure language -> UNEXPLAINED (never a guess)
# ===========================================================================

class TestUnexplained:
    def test_no_nearby_disclosure_is_unexplained(self):
        out = classify_restatement(
            conflict(),
            context="Net income was 210 for the third quarter of the fiscal year.",
        )
        assert out.restatement_type == RestatementType.UNEXPLAINED
        assert out.matched_disclosure_text is None

    def test_no_context_at_all_is_unclassified_not_unexplained(self):
        # Absence of input must NOT be reported as "we looked and found nothing".
        out = classify_restatement(conflict())
        assert out.restatement_type == RestatementType.UNCLASSIFIED


# ===========================================================================
# Negative / boundary — the over-fire risk the spec calls out explicitly
# ===========================================================================

class TestOverFireBoundary:
    def test_far_away_reclassification_word_does_not_fire(self):
        """'reclassified' appears, but ~600 chars from the figure in an unrelated
        sentence. With the bounded context window it must NOT be matched."""
        filler = "x" * 600
        text = (
            f"Net income was 210 for the quarter. {filler} "
            f"Separately, certain assets were reclassified between segments last year."
        )
        out = classify_restatement(
            conflict(), later_doc=SourceDocument(doc_id="PR", text=text),
            window=DEFAULT_CONTEXT_WINDOW,
        )
        assert out.restatement_type == RestatementType.UNEXPLAINED

    def test_near_reclassification_word_does_fire(self):
        # Control for the test above: the SAME word, but adjacent to the figure.
        text = "Net income was 210, reclassified to conform to current presentation."
        out = classify_restatement(conflict(), later_doc=SourceDocument(doc_id="PR", text=text))
        assert out.restatement_type == RestatementType.POSSIBLE_RECLASSIFICATION

    def test_word_boundary_no_substring_false_match(self):
        # A token that merely CONTAINS our keywords as a substring must not match.
        out = classify_restatement(
            conflict(),
            context="The restatedness metric was 210.",  # 'restated' is inside 'restatedness'
        )
        # \brestated\b should NOT match inside "restatedness".
        assert out.restatement_type == RestatementType.UNEXPLAINED


# ===========================================================================
# describe() surfaces the annotation, immutability of inputs
# ===========================================================================

class TestAnnotationPlumbing:
    def test_describe_includes_classification(self):
        out = classify_restatement(conflict(), context="as restated, 210")
        d = out.describe()
        assert "EXPLICIT_RESTATEMENT" in d
        # still says it's not auto-resolved
        assert "human" in d.lower()

    def test_input_conflict_not_mutated(self):
        c = conflict()
        _ = classify_restatement(c, context="as restated, 210")
        assert c.restatement_type == RestatementType.UNCLASSIFIED  # original untouched
