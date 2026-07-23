"""Regression coverage for packet-005985 compiler ambiguity pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_005985_FAMILY_PAIRS = (
    ("frame", "deontic"),
    ("frame", "doxastic"),
    ("frame", "temporal"),
)


def test_packet_005985_pairs_are_pinned_in_packet_pair_table() -> None:
    assert (
        tuple(COMPILER_AMBIGUITY_PACKET_005985_FAMILY_PAIRS)
        == _PACKET_005985_FAMILY_PAIRS
    )


def test_packet_005985_frame_targets_are_exposed_by_policy_helpers() -> None:
    assert set(_PACKET_005985_FAMILY_PAIRS).issubset(
        {("frame", target) for target in compiler_ambiguity_policy_targets("frame")}
    )
    assert set(_PACKET_005985_FAMILY_PAIRS).issubset(
        {
            ("frame", target)
            for target in compiler_required_adaptive_ambiguity_targets("frame")
        }
    )
    assert set(_PACKET_005985_FAMILY_PAIRS).issubset(
        {
            ("frame", target)
            for target in priority_signal_free_adaptive_ambiguity_targets("frame")
        }
    )
    assert set(_PACKET_005985_FAMILY_PAIRS).issubset(
        {("frame", target) for target in signal_free_adaptive_ambiguity_targets("frame")}
    )


def test_packet_005985_pairs_are_supported_across_compiler_ambiguity_policies() -> None:
    for predicted_family, target_family in _PACKET_005985_FAMILY_PAIRS:
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
