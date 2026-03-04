"""Tests for WS12-04: Proof Conflict Taxonomy + Reason Codes.

Covers CONFLICT_CLASSES, CONFLICT_REASON_CODES, classify_conflict_class,
and detect_proof_conflicts.
"""
from __future__ import annotations

import pytest

from reasoner.hybrid_v2_blueprint import (
    CONFLICT_CLASSES,
    CONFLICT_REASON_CODES,
    CONFLICT_TAXONOMY_VERSION,
    AtomV2,
    CanonicalIdV2,
    ConditionNodeV2,
    DeonticOpV2,
    FrameKindV2,
    FrameV2,
    LegalIRV2,
    NormV2,
    TemporalConstraintV2,
    TemporalExprV2,
    TemporalRelationV2,
    classify_conflict_class,
    detect_proof_conflicts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_norm(
    norm_key: str,
    op: DeonticOpV2,
    frame_ref: str,
    temporal_ref: str | None = None,
    exceptions: list | None = None,
) -> NormV2:
    return NormV2(
        id=CanonicalIdV2(namespace="norm", value=norm_key),
        op=op,
        target_frame_ref=frame_ref,
        activation=ConditionNodeV2(op="true"),
        exceptions=exceptions or [],
        temporal_ref=temporal_ref,
    )


def _make_frame(frame_key: str) -> FrameV2:
    return FrameV2(
        id=CanonicalIdV2(namespace="frame", value=frame_key),
        kind=FrameKindV2.ACTION,
        predicate=frame_key,
    )


def _make_temporal(temp_key: str, duration: str = "30d") -> TemporalConstraintV2:
    return TemporalConstraintV2(
        id=CanonicalIdV2(namespace="temporal", value=temp_key),
        relation=TemporalRelationV2.WITHIN,
        expr=TemporalExprV2(kind="duration", duration=duration),
    )


def _ir_with_norms(*norms: NormV2) -> LegalIRV2:
    frames: dict = {}
    for n in norms:
        frame_key = n.target_frame_ref.split(":")[1]
        frames[f"frame:{frame_key}"] = _make_frame(frame_key)
    ir = LegalIRV2(frames=frames, norms={n.id.ref(): n for n in norms})
    return ir


# ---------------------------------------------------------------------------
# TestConflictTaxonomy
# ---------------------------------------------------------------------------

class TestConflictTaxonomy:
    def test_all_three_classes_have_reason_codes(self):
        for cls in ("modal_conflict", "temporal_conflict", "exception_precedence_conflict"):
            assert cls in CONFLICT_CLASSES
            assert cls in CONFLICT_REASON_CODES

    def test_classify_modal_conflict(self):
        assert classify_conflict_class("modal_conflict") == "PC_CONFLICT_MODAL"

    def test_classify_temporal_conflict(self):
        assert classify_conflict_class("temporal_conflict") == "PC_CONFLICT_TEMPORAL"

    def test_classify_exception_precedence_conflict(self):
        assert classify_conflict_class("exception_precedence_conflict") == "PC_CONFLICT_EXCEPTION_PRECEDENCE"

    def test_unknown_class_returns_unknown_code_no_exception(self):
        # Contract-safe: must not raise
        result = classify_conflict_class("completely_unknown_class")
        assert result == "PC_CONFLICT_UNKNOWN_CLASS"

    def test_empty_string_returns_unknown_no_exception(self):
        assert classify_conflict_class("") == "PC_CONFLICT_UNKNOWN_CLASS"


# ---------------------------------------------------------------------------
# TestDetectProofConflicts
# ---------------------------------------------------------------------------

class TestDetectProofConflicts:
    def test_envelope_keys_always_present(self):
        ir = LegalIRV2()
        result = detect_proof_conflicts(ir)
        for key in ("taxonomy_version", "conflicts", "conflict_count"):
            assert key in result, f"Missing key: {key}"

    def test_taxonomy_version_matches_constant(self):
        ir = LegalIRV2()
        result = detect_proof_conflicts(ir)
        assert result["taxonomy_version"] == CONFLICT_TAXONOMY_VERSION

    def test_no_conflicts_empty_ir(self):
        ir = LegalIRV2()
        result = detect_proof_conflicts(ir)
        assert result["conflicts"] == []
        assert result["conflict_count"] == 0

    def test_no_conflicts_single_norm(self):
        norm = _make_norm("n1", DeonticOpV2.O, "frame:submit")
        ir = _ir_with_norms(norm)
        result = detect_proof_conflicts(ir)
        assert result["conflict_count"] == 0

    def test_modal_conflict_detected(self):
        """O and F on the same frame_ref → modal_conflict."""
        norm_o = _make_norm("n_oblig", DeonticOpV2.O, "frame:submit")
        norm_f = _make_norm("n_forbid", DeonticOpV2.F, "frame:submit")
        ir = _ir_with_norms(norm_o, norm_f)
        result = detect_proof_conflicts(ir)
        assert result["conflict_count"] >= 1
        classes = [c["class"] for c in result["conflicts"]]
        assert "modal_conflict" in classes

    def test_modal_conflict_has_required_keys(self):
        norm_o = _make_norm("n_oblig", DeonticOpV2.O, "frame:submit")
        norm_f = _make_norm("n_forbid", DeonticOpV2.F, "frame:submit")
        ir = _ir_with_norms(norm_o, norm_f)
        result = detect_proof_conflicts(ir)
        conflict = next(c for c in result["conflicts"] if c["class"] == "modal_conflict")
        for key in ("class", "reason_code", "norm_ids", "frame_ref", "description"):
            assert key in conflict, f"Conflict dict missing key: {key}"
        assert conflict["reason_code"] == "PC_CONFLICT_MODAL"
        assert len(conflict["norm_ids"]) == 2

    def test_no_conflict_o_plus_p_different_ops_not_modal(self):
        """O and P on same frame should NOT be a modal_conflict (only O vs F is)."""
        norm_o = _make_norm("n_oblig", DeonticOpV2.O, "frame:submit")
        norm_p = _make_norm("n_perm", DeonticOpV2.P, "frame:submit")
        ir = _ir_with_norms(norm_o, norm_p)
        result = detect_proof_conflicts(ir)
        modal_conflicts = [c for c in result["conflicts"] if c["class"] == "modal_conflict"]
        assert len(modal_conflicts) == 0

    def test_temporal_conflict_detected(self):
        """Same frame, same op (O), different temporal_refs → temporal_conflict."""
        norm_a = _make_norm("n_a", DeonticOpV2.O, "frame:file", temporal_ref="temporal:t1")
        norm_b = _make_norm("n_b", DeonticOpV2.O, "frame:file", temporal_ref="temporal:t2")
        ir = _ir_with_norms(norm_a, norm_b)
        result = detect_proof_conflicts(ir)
        classes = [c["class"] for c in result["conflicts"]]
        assert "temporal_conflict" in classes

    def test_temporal_conflict_has_required_keys(self):
        norm_a = _make_norm("n_a", DeonticOpV2.O, "frame:file", temporal_ref="temporal:t1")
        norm_b = _make_norm("n_b", DeonticOpV2.O, "frame:file", temporal_ref="temporal:t2")
        ir = _ir_with_norms(norm_a, norm_b)
        result = detect_proof_conflicts(ir)
        conflict = next(c for c in result["conflicts"] if c["class"] == "temporal_conflict")
        for key in ("class", "reason_code", "norm_ids", "frame_ref", "description"):
            assert key in conflict, f"Conflict dict missing key: {key}"
        assert conflict["reason_code"] == "PC_CONFLICT_TEMPORAL"

    def test_no_temporal_conflict_same_temporal_ref(self):
        """Same frame, same op, same temporal_ref → no temporal conflict."""
        norm_a = _make_norm("n_a", DeonticOpV2.O, "frame:file", temporal_ref="temporal:t1")
        norm_b = _make_norm("n_b", DeonticOpV2.O, "frame:file", temporal_ref="temporal:t1")
        ir = _ir_with_norms(norm_a, norm_b)
        result = detect_proof_conflicts(ir)
        temporal_conflicts = [c for c in result["conflicts"] if c["class"] == "temporal_conflict"]
        assert len(temporal_conflicts) == 0

    def test_conflict_count_matches_conflicts_list_length(self):
        norm_o = _make_norm("n_oblig", DeonticOpV2.O, "frame:submit")
        norm_f = _make_norm("n_forbid", DeonticOpV2.F, "frame:submit")
        ir = _ir_with_norms(norm_o, norm_f)
        result = detect_proof_conflicts(ir)
        assert result["conflict_count"] == len(result["conflicts"])
