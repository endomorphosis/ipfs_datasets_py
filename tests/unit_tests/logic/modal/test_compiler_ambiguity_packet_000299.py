"""Regression coverage for packet-000299 refined modal family cue policy."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_000299_FAMILY_PAIRS,
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


def test_packet_000299_family_cue_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
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

    assert COMPILER_REFINED_PACKET_000299_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
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


def test_packet_000299_refined_buffers_cover_observed_family_gaps() -> None:
    base_adaptive_threshold = 0.15
    observed_family_gaps = {
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ): 0.347824902286,
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
        ): 0.377400290236,
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ): 0.317010207838,
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ): 0.197858984759,
    }

    for (predicted_family, target_family), observed_gap in observed_family_gaps.items():
        refined_threshold = (
            base_adaptive_threshold
            + compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
        )
        assert refined_threshold > observed_gap
