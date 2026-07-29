"""Regression coverage for packet-000295 compiler ambiguity family pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_000295_REQUIRED_FAMILY_PAIRS = (
    ("deontic", "deontic"),
    ("deontic", "frame"),
    ("frame", "deontic"),
)


def test_packet_000295_required_pairs_are_in_registry_constant() -> None:
    packet_pairs = set(COMPILER_AMBIGUITY_PACKET_000295_FAMILY_PAIRS)
    for family_pair in _PACKET_000295_REQUIRED_FAMILY_PAIRS:
        assert family_pair in packet_pairs


def test_packet_000295_required_pairs_are_policy_targets() -> None:
    for predicted_family, target_family in _PACKET_000295_REQUIRED_FAMILY_PAIRS:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(predicted_family)
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )


def test_packet_000295_required_pairs_support_explicit_adaptive_ambiguity() -> None:
    for predicted_family, target_family in _PACKET_000295_REQUIRED_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_signal_free_adaptive_ambiguity_pair(predicted_family, target_family)
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
