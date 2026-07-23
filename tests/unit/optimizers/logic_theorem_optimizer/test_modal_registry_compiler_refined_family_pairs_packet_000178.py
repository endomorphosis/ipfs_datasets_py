"""Regression coverage for packet-000178 refined modal family cue pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    COMPILER_REFINED_PACKET_000178_FAMILY_PAIRS,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_000178_FAMILY_PAIRS = (
    ("conditional_normative", "conditional_normative"),
    ("conditional_normative", "deontic"),
    ("deontic", "frame"),
    ("frame", "temporal"),
)

_PACKET_000178_MIN_MARGIN_BUFFERS = {
    ("conditional_normative", "deontic"): 0.31,
    ("deontic", "frame"): 0.34,
    ("frame", "temporal"): 1.08,
}


def test_packet_000178_pairs_are_pinned_in_refined_pair_table() -> None:
    assert (
        tuple(COMPILER_REFINED_PACKET_000178_FAMILY_PAIRS)
        == _PACKET_000178_FAMILY_PAIRS
    )


def test_packet_000178_pairs_are_supported_across_compiler_policies() -> None:
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in _PACKET_000178_FAMILY_PAIRS:
        assert (predicted_family, target_family) in refined_pairs
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


def test_packet_000178_refined_margin_buffers_cover_residual_family_gaps() -> None:
    for pair, expected_floor in _PACKET_000178_MIN_MARGIN_BUFFERS.items():
        assert compiler_refined_modal_family_cue_margin_buffer(*pair) >= expected_floor

    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            "conditional_normative",
            "conditional_normative",
        )
        >= 0.14
    )
