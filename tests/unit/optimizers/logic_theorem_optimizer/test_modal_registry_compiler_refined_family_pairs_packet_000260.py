"""Regression coverage for packet-000260 refined modal family cue pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    COMPILER_REFINED_PACKET_000260_FAMILY_PAIRS,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_000260_FAMILY_PAIRS = (
    ("deontic", "deontic"),
    ("deontic", "frame"),
    ("frame", "frame"),
)


def test_packet_000260_pairs_match_registry_constant() -> None:
    assert tuple(COMPILER_REFINED_PACKET_000260_FAMILY_PAIRS) == _PACKET_000260_FAMILY_PAIRS


def test_packet_000260_pairs_are_in_refined_modal_family_cue_policy_table() -> None:
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in _PACKET_000260_FAMILY_PAIRS:
        assert (predicted_family, target_family) in refined_pairs


def test_packet_000260_pairs_are_supported_across_compiler_ambiguity_policies() -> None:
    for predicted_family, target_family in _PACKET_000260_FAMILY_PAIRS:
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


def test_packet_000260_pairs_have_family_cue_margin_buffers() -> None:
    assert (
        compiler_refined_modal_family_cue_margin_buffer("deontic", "frame")
        >= 0.0015
    )
    assert (
        compiler_refined_modal_family_cue_margin_buffer("frame", "frame")
        >= 0.135
    )
    assert (
        compiler_weak_typed_self_family_cue_margin_buffer("deontic", "deontic")
        >= 0.135
    )
