"""Regression coverage for packet-004476 modal family cue policy pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS,
    COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_packet_004476_pairs_are_exact_generalized_family_bundle() -> None:
    assert tuple(COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS) == (
        ("deontic", "deontic"),
        ("frame", "alethic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "frame"),
        ("frame", "temporal"),
        ("temporal", "deontic"),
        ("temporal", "temporal"),
    )


def test_packet_004476_pairs_are_supported_across_compiler_policies() -> None:
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_004476_FAMILY_PAIRS:
        assert (predicted_family, target_family) in refined_pairs
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
            >= 0.0015
        )


def test_packet_004476_self_pairs_keep_weak_typed_family_buffers() -> None:
    for family in ("deontic", "frame", "temporal"):
        assert (
            compiler_weak_typed_self_family_cue_margin_buffer(family, family)
            >= 0.135
        )
