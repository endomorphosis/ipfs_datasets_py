"""Regression coverage for packet-000169 refined modal family cue pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    COMPILER_REFINED_PACKET_000169_FAMILY_PAIRS,
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_000169_FAMILY_PAIRS = (
    ("deontic", "deontic"),
    ("deontic", "dynamic"),
    ("deontic", "frame"),
    ("frame", "conditional_normative"),
    ("frame", "deontic"),
    ("frame", "doxastic"),
    ("frame", "temporal"),
)


def test_packet_000169_pairs_match_registry_constant() -> None:
    assert tuple(COMPILER_REFINED_PACKET_000169_FAMILY_PAIRS) == _PACKET_000169_FAMILY_PAIRS


def test_packet_000169_pairs_are_in_refined_modal_family_cue_policy_table() -> None:
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in _PACKET_000169_FAMILY_PAIRS:
        assert (predicted_family, target_family) in refined_pairs


def test_packet_000169_pairs_are_supported_across_compiler_ambiguity_policies() -> None:
    for predicted_family, target_family in _PACKET_000169_FAMILY_PAIRS:
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


def test_packet_000169_pairs_have_refined_margin_buffers() -> None:
    expected_buffers = {
        (ModalLogicFamily.DEONTIC, ModalLogicFamily.DEONTIC): 0.086,
        (ModalLogicFamily.DEONTIC, ModalLogicFamily.DYNAMIC): 0.325,
        (ModalLogicFamily.DEONTIC, ModalLogicFamily.FRAME): 0.28,
        (ModalLogicFamily.FRAME, ModalLogicFamily.CONDITIONAL_NORMATIVE): 0.36,
        (ModalLogicFamily.FRAME, ModalLogicFamily.DEONTIC): 0.34,
        (ModalLogicFamily.FRAME, ModalLogicFamily.DOXASTIC): 0.18,
        (ModalLogicFamily.FRAME, ModalLogicFamily.TEMPORAL): 0.13,
    }
    for (predicted_family, target_family), expected_buffer in expected_buffers.items():
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - expected_buffer
            )
            <= 1e-12
        )
    assert (
        abs(
            compiler_weak_typed_self_family_cue_margin_buffer(
                ModalLogicFamily.DEONTIC,
                ModalLogicFamily.DEONTIC,
            )
            - 0.155
        )
        <= 1e-12
    )


def test_packet_000169_deontic_profile_includes_official_duty_cues() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(family=ModalLogicFamily.DEONTIC)
    obligation_cues = {
        cue
        for operator in profile.operators
        if operator.symbol == "O"
        for cue in operator.cue_terms
    }

    assert "shall administer" in obligation_cues
    assert "shall appoint" in obligation_cues
