"""Regression coverage for packet-001115 temporal modal family cue rules."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_PACKET_001115_FAMILY_PAIRS,
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_001115_FAMILY_PAIRS = (
    ("deontic", "temporal"),
    ("frame", "temporal"),
)


def test_packet_001115_pairs_match_registry_constant() -> None:
    assert tuple(COMPILER_REFINED_PACKET_001115_FAMILY_PAIRS) == (
        _PACKET_001115_FAMILY_PAIRS
    )


def test_packet_001115_pairs_are_supported_across_compiler_policies() -> None:
    for predicted_family, target_family in _PACKET_001115_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
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
            >= 0.08
        )


def test_packet_001115_temporal_profile_covers_uscode_status_history_cues() -> None:
    temporal_profile = DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.TEMPORAL)
    temporal_cues = {
        cue
        for operator in temporal_profile.operators
        for cue in operator.cue_terms
    }

    assert {
        "effective date of repeal",
        "renumbered",
        "renumbered section",
        "section renumbered",
        "section repealed",
        "sections repealed",
    } <= temporal_cues
