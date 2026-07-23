"""Regression coverage for packet-003089 compiler modal family cue pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_003089_FAMILY_PAIRS = (
    ("deontic", "conditional_normative"),
    ("deontic", "temporal"),
    ("temporal", "deontic"),
    ("temporal", "dynamic"),
    ("temporal", "frame"),
    ("temporal", "temporal"),
    ("frame", "conditional_normative"),
    ("frame", "deontic"),
    ("frame", "frame"),
    ("frame", "temporal"),
)


def test_packet_003089_pairs_are_priority_signal_free_targets() -> None:
    for predicted_family, target_family in _PACKET_003089_FAMILY_PAIRS:
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )


def test_packet_003089_pairs_are_supported_across_compiler_ambiguity_policies() -> None:
    for predicted_family, target_family in _PACKET_003089_FAMILY_PAIRS:
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
