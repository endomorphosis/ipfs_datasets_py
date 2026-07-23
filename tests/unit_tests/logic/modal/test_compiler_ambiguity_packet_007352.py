"""Regression coverage for packet-007352 refined modal family cue policy."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REFINED_PACKET_007352_FAMILY_PAIRS,
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


def _cue_terms_for_family(family: ModalLogicFamily) -> set[str]:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(family)
    return {
        cue
        for operator in profile.operators
        for cue in operator.cue_terms
    }


def test_packet_007352_family_cue_pairs_are_registered() -> None:
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
            ModalLogicFamily.DEONTIC.value,
        ),
    )

    assert set(expected_pairs) <= set(COMPILER_REFINED_PACKET_007352_FAMILY_PAIRS)
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
        >= 0.135
    )


def test_packet_007352_literal_cues_cover_appropriation_and_construction() -> None:
    deontic_cues = _cue_terms_for_family(ModalLogicFamily.DEONTIC)
    temporal_cues = _cue_terms_for_family(ModalLogicFamily.TEMPORAL)

    assert "shall not be construed to limit" in deontic_cues
    assert "shall not be construed to restrict" in deontic_cues
    assert "shall not be construed to circumvent" in deontic_cues
    assert "for the expenses of carrying out" in temporal_cues
    assert "study authorized by section" in temporal_cues
