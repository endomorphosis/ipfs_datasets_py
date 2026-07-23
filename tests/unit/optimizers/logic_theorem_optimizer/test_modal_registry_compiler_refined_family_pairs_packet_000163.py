"""Regression coverage for packet-000163 modal family cue pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_000163_CLAIMED_FAMILY_PAIRS = (
    ("deontic", "conditional_normative"),
    ("deontic", "deontic"),
    ("frame", "conditional_normative"),
    ("frame", "deontic"),
    ("frame", "epistemic"),
)


def test_packet_000163_claimed_pairs_are_pinned_in_packet_pair_table() -> None:
    packet_pairs = set(COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS)

    for pair in _PACKET_000163_CLAIMED_FAMILY_PAIRS:
        assert pair in packet_pairs


def test_packet_000163_claimed_pairs_are_supported_across_policies() -> None:
    for predicted_family, target_family in _PACKET_000163_CLAIMED_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(
            predicted_family,
            target_family,
        )
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


def test_packet_000163_claimed_pairs_have_refined_margin_buffers() -> None:
    expected_minimum_buffers = {
        ("deontic", "conditional_normative"): 0.0015,
        ("deontic", "deontic"): 0.086,
        ("frame", "conditional_normative"): 0.02,
        ("frame", "deontic"): 0.006,
        ("frame", "epistemic"): 0.02,
    }

    for predicted_family, target_family in _PACKET_000163_CLAIMED_FAMILY_PAIRS:
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            >= expected_minimum_buffers[(predicted_family, target_family)]
        )
