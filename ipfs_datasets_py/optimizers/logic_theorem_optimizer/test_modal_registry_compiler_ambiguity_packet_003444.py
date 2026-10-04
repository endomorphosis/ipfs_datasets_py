"""Regression checks for packet-003444 compiler ambiguity policy coverage."""

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
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_003444_policy_pairs_are_registered() -> None:
    family_pairs = (
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DOXASTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
    )

    for predicted_family, target_family in family_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family), (
            predicted_family,
            target_family,
        )


def test_temporal_to_doxastic_inherits_compiler_adaptive_support() -> None:
    predicted_family = ModalLogicFamily.TEMPORAL.value
    target_family = ModalLogicFamily.DOXASTIC.value

    assert target_family in compiler_ambiguity_policy_targets(predicted_family)
    assert target_family in compiler_required_adaptive_ambiguity_targets(predicted_family)
    assert supports_signal_free_adaptive_ambiguity_pair(
        predicted_family,
        target_family,
    )
