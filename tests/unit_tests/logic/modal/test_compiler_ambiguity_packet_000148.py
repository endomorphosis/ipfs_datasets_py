"""Regression coverage for packet-000148 compiler registry cue policy."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_PACKET_000148_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_000148_family_cue_pairs_are_registered() -> None:
    expected_pair_buffers = (
        (
            (
                ModalLogicFamily.DEONTIC.value,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ),
            0.45,
        ),
        ((ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value), 0.24),
        ((ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value), 0.58),
    )
    expected_pairs = tuple(pair for pair, _ in expected_pair_buffers)

    assert COMPILER_AMBIGUITY_PACKET_000148_FAMILY_PAIRS == expected_pairs
    for (predicted_family, target_family), expected_min_buffer in expected_pair_buffers:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
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
                target_family,
            )
            >= expected_min_buffer
        )
