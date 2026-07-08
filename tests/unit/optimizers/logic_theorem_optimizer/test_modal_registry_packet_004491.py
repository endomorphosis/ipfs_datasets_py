"""Regression coverage for packet-004491 modal family cue refinements."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_004491_FAMILY_PAIRS = (
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
    (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value),
)


def _profile_cues(family: ModalLogicFamily) -> set[str]:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(family)
    return {
        cue
        for operator in profile.operators
        for cue in operator.cue_terms
    }


def test_packet_004491_frame_target_pairs_are_supported() -> None:
    for predicted_family, target_family in _PACKET_004491_FAMILY_PAIRS:
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_ambiguity_policy_pair(
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
            > 0.0
        )


def test_packet_004491_deontic_registry_covers_operative_statutory_phrases() -> None:
    deontic_cues = _profile_cues(ModalLogicFamily.DEONTIC)

    assert "shall be received" in deontic_cues
    assert "shall be received in all courts" in deontic_cues
    assert "may make and file" in deontic_cues


def test_packet_004491_epistemic_registry_covers_report_status_phrase() -> None:
    epistemic_cues = _profile_cues(ModalLogicFamily.EPISTEMIC)

    assert "annual report to congress" in epistemic_cues
