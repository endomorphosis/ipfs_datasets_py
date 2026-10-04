"""Packet-003070 registry coverage for compiler ambiguity policy pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_003070_policy_pairs_are_registered() -> None:
    family_pairs = (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
    )

    for predicted_family, target_family in family_pairs:
        assert is_compiler_ambiguity_policy_pair(
            predicted_family,
            target_family,
        ), (predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        ), (predicted_family, target_family)
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        ), (predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        ), (predicted_family, target_family)


def test_packet_003070_deontic_policy_targets_include_temporal_and_self() -> None:
    predicted_family = ModalLogicFamily.DEONTIC.value
    expected_targets = (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    )

    policy_targets = compiler_ambiguity_policy_targets(predicted_family)
    required_targets = compiler_required_adaptive_ambiguity_targets(predicted_family)
    for target_family in expected_targets:
        assert target_family in policy_targets
        assert target_family in required_targets
