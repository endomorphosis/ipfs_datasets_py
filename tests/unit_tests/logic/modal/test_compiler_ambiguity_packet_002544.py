"""Regression coverage for packet-002544 refined modal family cue policy."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_002544_FAMILY_PAIRS,
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_002544_refined_family_cue_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
    )

    assert COMPILER_REFINED_PACKET_002544_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
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
            >= 0.0015
        )

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        )
        >= 0.155
    )


def test_packet_002544_profile_cues_cover_study_request_and_duty_language() -> None:
    deontic_cues = {
        cue
        for operator in DEFAULT_MODAL_REGISTRY.get_profile(
            ModalLogicFamily.DEONTIC
        ).operators
        for cue in operator.cue_terms
    }
    temporal_cues = {
        cue
        for operator in DEFAULT_MODAL_REGISTRY.get_profile(
            ModalLogicFamily.TEMPORAL
        ).operators
        for cue in operator.cue_terms
    }
    conditional_cues = {
        cue
        for operator in DEFAULT_MODAL_REGISTRY.get_profile(
            ModalLogicFamily.CONDITIONAL_NORMATIVE
        ).operators
        for cue in operator.cue_terms
    }

    assert {
        "shall study",
        "administer and enforce",
        "collection of customs duties",
    } <= deontic_cues
    assert {
        "grant period",
        "fellowship period",
        "during each fiscal year",
    } <= temporal_cues
    assert {"upon the request of", "upon request"} <= conditional_cues
