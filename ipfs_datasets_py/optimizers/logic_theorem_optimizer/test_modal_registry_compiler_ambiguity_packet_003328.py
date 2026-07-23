"""Regression coverage for packet-003328 compiler ambiguity policy pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_003328_FAMILY_PAIRS = (
    ("deontic", "deontic"),
    ("deontic", "temporal"),
    ("frame", "deontic"),
    ("frame", "frame"),
    ("frame", "temporal"),
    ("temporal", "deontic"),
    ("temporal", "frame"),
    ("temporal", "temporal"),
)


def test_packet_003328_pairs_are_pinned_in_packet_table() -> None:
    assert tuple(COMPILER_AMBIGUITY_PACKET_003328_FAMILY_PAIRS) == (
        _PACKET_003328_FAMILY_PAIRS
    )


def test_packet_003328_pairs_are_supported_across_adaptive_ambiguity_policies() -> None:
    for predicted_family, target_family in _PACKET_003328_FAMILY_PAIRS:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
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
