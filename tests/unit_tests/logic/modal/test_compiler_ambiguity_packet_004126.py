"""Regression coverage for packet-004126 refined modal family cue policy."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_004126_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_required_adaptive_ambiguity_targets,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_004126_family_cue_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    )

    assert COMPILER_REFINED_PACKET_004126_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_004126_refined_thresholds_cover_evidence_margins() -> None:
    base_threshold = 0.15
    evidence_cases = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.050619093457,
            0.21,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.976531932586,
            0.0,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.388733759963,
            0.0,
        ),
    )

    for predicted_family, target_family, family_margin, weak_buffer in evidence_cases:
        effective_threshold = (
            base_threshold
            + compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            + weak_buffer
        )
        assert family_margin <= effective_threshold

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        )
        >= 0.21
    )
