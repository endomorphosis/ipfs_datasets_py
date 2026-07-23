"""Regression coverage for packet-000151 refined modal family cue pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_PACKET_000151_FAMILY_PAIRS,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_000151_FAMILY_PAIRS = (
    ("frame", "deontic"),
    ("frame", "frame"),
    ("frame", "temporal"),
)


def test_packet_000151_pairs_match_registry_constant() -> None:
    assert tuple(COMPILER_REFINED_PACKET_000151_FAMILY_PAIRS) == (
        _PACKET_000151_FAMILY_PAIRS
    )


def test_packet_000151_pairs_are_supported_across_compiler_policies() -> None:
    for predicted_family, target_family in _PACKET_000151_FAMILY_PAIRS:
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
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_000151_refined_margin_buffer_covers_frame_family_evidence() -> None:
    observed_margins = {
        ("frame", "deontic"): (-0.47508163427, -0.330438732962, -0.230401998129),
        ("frame", "frame"): (0.095426451185,),
        ("frame", "temporal"): (-0.996752403131, -0.60682397327),
    }

    for pair, margins in observed_margins.items():
        margin_buffer = compiler_refined_modal_family_cue_margin_buffer(*pair)
        effective_threshold = 0.15 + margin_buffer
        assert margin_buffer > 0.0
        assert any(margin <= effective_threshold for margin in margins)
