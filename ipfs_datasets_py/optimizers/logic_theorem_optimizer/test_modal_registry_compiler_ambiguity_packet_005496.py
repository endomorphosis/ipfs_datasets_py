"""Regression checks for packet-005496 modal family cue policy coverage."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS,
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_005496_FAMILY_PAIRS = (
    ("deontic", "conditional_normative"),
    ("deontic", "epistemic"),
    ("frame", "conditional_normative"),
    ("frame", "deontic"),
    ("frame", "temporal"),
    ("temporal", "temporal"),
)


def _profile_cues(family: ModalLogicFamily) -> set[str]:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(family)
    return {
        cue
        for operator in profile.operators
        for cue in operator.cue_terms
    }


def test_packet_005496_pairs_are_registered_across_compiler_policies() -> None:
    assert COMPILER_AMBIGUITY_PACKET_005496_FAMILY_PAIRS == _PACKET_005496_FAMILY_PAIRS
    for predicted_family, target_family in _PACKET_005496_FAMILY_PAIRS:
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


def test_packet_005496_pairs_are_exposed_by_target_lookup_tables() -> None:
    for predicted_family, target_family in _PACKET_005496_FAMILY_PAIRS:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )


def test_packet_005496_statutory_cues_route_to_target_families() -> None:
    assert {
        "may appoint a board of inquiry",
        "shall administer the park",
        "shall furnish hospitalization",
    } <= _profile_cues(ModalLogicFamily.DEONTIC)
    assert {
        "for a period not to exceed",
        "not to exceed",
        "period not to exceed",
    } <= _profile_cues(ModalLogicFamily.TEMPORAL)
    assert {
        "board of inquiry",
        "in the opinion of",
        "inquire into",
        "inquiry into",
    } <= _profile_cues(ModalLogicFamily.EPISTEMIC)
