"""Tests for the deterministic modal logic registry."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
    compiler_required_adaptive_ambiguity_targets,
    DEFAULT_MODAL_REGISTRY,
    is_compiler_required_adaptive_ambiguity_pair,
    ModalLogicFamily,
    ModalRegistry,
    ModalSystem,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_normative_modal_family,
    priority_signal_free_adaptive_ambiguity_targets,
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
    assert {"has a duty to", "under an obligation to"}.issubset(cue_terms)


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
    assert "notwithstanding" in cue_terms
    assert "except as provided by" in cue_terms
    assert "as provided by" in cue_terms


def test_temporal_profile_includes_deadline_and_calendar_scope_cues() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.TEMPORAL)
    cue_terms = {cue for operator in profile.operators for cue in operator.cue_terms}

    assert "not later than" in cue_terms
    assert "effective date" in cue_terms
    assert "fiscal year" in cue_terms
    assert "from time to time" in cue_terms
    assert "on or after" in cue_terms


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
        "alethic",
        "epistemic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "dynamic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "deontic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "conditional_normative",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "frame",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "temporal",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "deontic",
        "conditional_normative",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "deontic",
        "deontic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "deontic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "conditional_normative",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "temporal",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "epistemic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "frame",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "dynamic",
    )
    assert supports_signal_free_adaptive_ambiguity_pair("deontic", "epistemic")
    assert supports_signal_free_adaptive_ambiguity_pair("deontic", "dynamic")
    assert supports_signal_free_adaptive_ambiguity_pair("epistemic", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair("epistemic", "epistemic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "alethic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "epistemic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "frame")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "temporal")
    assert supports_signal_free_adaptive_ambiguity_pair(
        "frame",
        "conditional_normative",
    )
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "frame")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "alethic")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "epistemic")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "alethic")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "dynamic")
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "temporal")
    assert (
        supports_signal_free_adaptive_ambiguity_pair(
            "epistemic",
            "temporal",
        )
        is False
    )


def test_compiler_required_adaptive_ambiguity_pairs_are_covered_by_both_policies() -> None:
    for predicted_family, target_family in (
        COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
    ):
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_required_adaptive_ambiguity_bundle_covers_deontic_conflict_pairs() -> None:
    required_pairs = set(COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS)

    assert ("alethic", "deontic") in required_pairs
    assert ("alethic", "temporal") in required_pairs
    assert ("conditional_normative", "deontic") in required_pairs
    assert ("deontic", "conditional_normative") in required_pairs
    assert ("deontic", "dynamic") in required_pairs
    assert ("deontic", "deontic") in required_pairs
    assert ("deontic", "temporal") in required_pairs
    assert ("frame", "conditional_normative") in required_pairs
    assert ("frame", "deontic") in required_pairs
    assert ("frame", "alethic") in required_pairs
    assert ("frame", "epistemic") in required_pairs
    assert ("frame", "temporal") in required_pairs
    assert ("temporal", "conditional_normative") in required_pairs
    assert ("temporal", "deontic") in required_pairs
    assert compiler_required_adaptive_ambiguity_targets("alethic") == (
        "deontic",
        "temporal",
    )
    assert compiler_required_adaptive_ambiguity_targets("conditional_normative") == (
        "deontic",
        "temporal",
    )
    assert compiler_required_adaptive_ambiguity_targets("deontic") == (
        "conditional_normative",
        "dynamic",
        "deontic",
        "temporal",
        "frame",
    )
    assert compiler_required_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "alethic",
        "epistemic",
        "temporal",
    )
    assert compiler_required_adaptive_ambiguity_targets("temporal") == (
        "deontic",
        "conditional_normative",
    )
    assert is_compiler_required_adaptive_ambiguity_pair(
        "frame",
        "conditional_normative",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "deontic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "alethic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "epistemic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "temporal") is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "conditional_normative",
        "deontic",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair("deontic", "dynamic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("alethic", "deontic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("alethic", "temporal") is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "temporal",
        "conditional_normative",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair("deontic", "temporal") is True


def test_signal_free_adaptive_ambiguity_targets_are_ordered_and_directional() -> None:
    assert signal_free_adaptive_ambiguity_targets("alethic") == (
        "epistemic",
        "dynamic",
        "deontic",
        "conditional_normative",
        "frame",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("temporal") == (
        "conditional_normative",
        "deontic",
        "alethic",
        "epistemic",
        "frame",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("deontic") == (
        "deontic",
        "conditional_normative",
        "frame",
        "temporal",
        "epistemic",
        "dynamic",
    )
    assert signal_free_adaptive_ambiguity_targets("conditional_normative") == (
        "deontic",
        "conditional_normative",
        "temporal",
        "epistemic",
        "dynamic",
        "frame",
    )
    assert signal_free_adaptive_ambiguity_targets("epistemic") == (
        "deontic",
        "epistemic",
    )
    assert signal_free_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "frame",
        "alethic",
        "epistemic",
        "dynamic",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("hybrid") == ("frame",)


def test_signal_free_adaptive_ambiguity_targets_do_not_repeat_pairs() -> None:
    for family in (
        "alethic",
        "conditional_normative",
        "deontic",
        "epistemic",
        "frame",
        "hybrid",
        "temporal",
    ):
        targets = signal_free_adaptive_ambiguity_targets(family)
        assert len(targets) == len(set(targets))


def test_priority_signal_free_adaptive_ambiguity_pair_policy_is_directional() -> None:
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "deontic",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "alethic",
        "temporal",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "deontic",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "deontic",
        "deontic",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "deontic",
        "dynamic",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "deontic",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair("deontic", "epistemic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("deontic", "temporal")
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "temporal",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "conditional_normative",
        "frame",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "temporal",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "deontic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "alethic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "frame")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "temporal")
    assert is_priority_signal_free_adaptive_ambiguity_pair("hybrid", "frame")
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "frame",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "deontic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "alethic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "epistemic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "temporal")
    assert is_priority_signal_free_adaptive_ambiguity_pair("epistemic", "deontic")


def test_priority_signal_free_adaptive_targets_are_ordered_directional_subsets() -> None:
    assert priority_signal_free_adaptive_ambiguity_targets("alethic") == (
        "deontic",
        "conditional_normative",
        "temporal",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("conditional_normative") == (
        "deontic",
        "temporal",
        "frame",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("temporal") == (
        "conditional_normative",
        "deontic",
        "alethic",
        "frame",
        "temporal",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "epistemic",
        "temporal",
        "alethic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("deontic") == (
        "conditional_normative",
        "epistemic",
        "frame",
        "temporal",
        "dynamic",
        "deontic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("epistemic") == (
        "deontic",
        "epistemic",
    )


def test_priority_signal_free_policy_covers_recurrent_compiler_ambiguity_pairs() -> None:
    recurrent_pairs = (
        ("alethic", "deontic"),
        ("alethic", "conditional_normative"),
        ("alethic", "temporal"),
        ("conditional_normative", "deontic"),
        ("deontic", "conditional_normative"),
        ("deontic", "deontic"),
        ("deontic", "frame"),
        ("deontic", "temporal"),
        ("conditional_normative", "temporal"),
        ("temporal", "frame"),
        ("temporal", "temporal"),
        ("epistemic", "deontic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "alethic"),
        ("frame", "epistemic"),
        ("frame", "temporal"),
    )
    for predicted_family, target_family in recurrent_pairs:
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
