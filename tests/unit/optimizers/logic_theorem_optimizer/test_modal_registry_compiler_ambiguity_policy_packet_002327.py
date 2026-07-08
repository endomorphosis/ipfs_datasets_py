"""Regression coverage for packet-002327 compiler ambiguity pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_002327_FAMILY_PAIRS = (
    ("deontic", "deontic"),
    ("frame", "deontic"),
)


def test_packet_002327_pairs_are_pinned_in_packet_pair_table() -> None:
    assert (
        tuple(COMPILER_AMBIGUITY_PACKET_002327_FAMILY_PAIRS)
        == _PACKET_002327_FAMILY_PAIRS
    )


def test_packet_002327_pairs_are_exposed_by_policy_helpers() -> None:
    for predicted_family, target_family in _PACKET_002327_FAMILY_PAIRS:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(predicted_family)
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


def test_packet_002327_pairs_keep_small_margin_buffers_for_explicit_ambiguity() -> None:
    assert compiler_refined_modal_family_cue_margin_buffer("deontic", "deontic") >= 0.086
    assert compiler_refined_modal_family_cue_margin_buffer("frame", "deontic") >= 0.08
