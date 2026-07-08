"""Regression coverage for packet-003428 refined frame cue policy."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_003428_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_003428_frame_family_cue_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.EPISTEMIC.value,
            0.7,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            1.05,
        ),
    )

    assert {
        (source_family, target_family)
        for source_family, target_family, _ in expected_pairs
    } <= set(COMPILER_REFINED_PACKET_003428_FAMILY_PAIRS)
    for predicted_family, target_family, minimum_buffer in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                f"{predicted_family}->{target_family}",
            )
            >= minimum_buffer
        )
