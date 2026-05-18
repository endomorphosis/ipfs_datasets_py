"""Tests for the deterministic modal logic registry."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    ModalRegistry,
    ModalSystem,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_normative_modal_family,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


def test_default_registry_covers_all_modal_families() -> None:
    families = {profile.family for profile in DEFAULT_MODAL_REGISTRY.all_profiles()}

    assert families == set(ModalLogicFamily)


def test_deontic_profile_has_expected_operators_and_serial_semantics() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.DEONTIC)
    symbols = {operator.symbol for operator in profile.operators}
    cue_terms = {cue for operator in profile.operators for cue in operator.cue_terms}

    assert profile.system == ModalSystem.D
    assert profile.semantics.serial is True
    assert {"O", "P", "F"}.issubset(symbols)
    assert {"shall", "must", "may", "prohibited"}.issubset(cue_terms)


def test_frame_profile_is_bm25_ontology_grounded() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile("frame", "FRAME_BM25")

    assert profile.family == ModalLogicFamily.FRAME
    assert profile.system == ModalSystem.FRAME_BM25
    assert profile.semantics.ontology_frame_grounded is True


def test_conditional_profile_includes_terms_and_conditions_cues() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.CONDITIONAL_NORMATIVE)
    cue_terms = {cue for operator in profile.operators for cue in operator.cue_terms}

    assert "under such terms and conditions" in cue_terms
    assert "subject to the terms and conditions" in cue_terms


def test_registry_serialization_is_stable_json_ready() -> None:
    registry = ModalRegistry()
    payload = registry.to_dict()
    rendered = json.dumps(payload, sort_keys=True)

    assert "deontic:D" in payload
    assert "frame:FRAME_BM25" in payload
    assert rendered == json.dumps(payload, sort_keys=True)


def test_normative_modal_family_helper_handles_strings_and_enums() -> None:
    assert is_normative_modal_family(ModalLogicFamily.DEONTIC) is True
    assert is_normative_modal_family("conditional_normative") is True
    assert is_normative_modal_family("temporal") is False
    assert is_normative_modal_family("unknown-family") is False


def test_signal_free_adaptive_ambiguity_pair_policy_covers_required_bundle_pairs() -> None:
    assert supports_signal_free_adaptive_ambiguity_pair(
        "deontic",
        "conditional_normative",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "deontic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "temporal",
    )
    assert supports_signal_free_adaptive_ambiguity_pair("epistemic", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "frame")
    assert supports_signal_free_adaptive_ambiguity_pair(
        "frame",
        "conditional_normative",
    )
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "epistemic")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "temporal")
    assert (
        supports_signal_free_adaptive_ambiguity_pair(
            "epistemic",
            "temporal",
        )
        is False
    )


def test_signal_free_adaptive_ambiguity_targets_are_ordered_and_directional() -> None:
    assert signal_free_adaptive_ambiguity_targets("temporal") == (
        "conditional_normative",
        "deontic",
        "frame",
    )
    assert signal_free_adaptive_ambiguity_targets("deontic") == (
        "conditional_normative",
        "frame",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("conditional_normative") == (
        "deontic",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("epistemic") == ("deontic",)
    assert signal_free_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "epistemic",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("hybrid") == ("frame",)


def test_priority_signal_free_adaptive_ambiguity_pair_policy_is_directional() -> None:
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "deontic",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "deontic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "frame")
    assert is_priority_signal_free_adaptive_ambiguity_pair("hybrid", "frame")
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "deontic")
    assert (
        is_priority_signal_free_adaptive_ambiguity_pair("deontic", "frame")
        is False
    )
    assert (
        is_priority_signal_free_adaptive_ambiguity_pair("frame", "temporal")
        is False
    )
