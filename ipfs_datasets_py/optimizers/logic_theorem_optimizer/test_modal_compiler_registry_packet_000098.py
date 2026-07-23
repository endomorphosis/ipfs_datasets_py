"""Packet-000098 registry coverage for refined modal family cue rules."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_PACKET_000098_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_required_adaptive_ambiguity_targets,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_modal_registry_packet_000098_family_pairs_are_supported() -> None:
    expected_pairs = (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value),
    )

    assert COMPILER_REFINED_PACKET_000098_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_modal_registry_packet_000098_refined_margin_buffers() -> None:
    expected_buffers = {
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value): 0.36,
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ): 0.84,
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value): 0.94,
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value): 0.18,
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value): 0.58,
    }

    for pair, expected_buffer in expected_buffers.items():
        assert (
            compiler_refined_modal_family_cue_margin_buffer(*pair)
            == expected_buffer
        )

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.FRAME.value,
        )
        == 0.19
    )
