"""Tests for the deterministic modal logic registry."""

from __future__ import annotations

import json

import ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry as modal_registry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS,
    COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    DEFAULT_MODAL_REGISTRY,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    ModalLogicFamily,
    ModalRegistry,
    ModalSystem,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_normative_modal_family,
    is_signal_free_adaptive_ambiguity_pair,
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
    assert {"has a duty to", "under an obligation to", "shall issue"}.issubset(
        cue_terms
    )
    assert {"is entitled to", "shall be entitled to"}.issubset(cue_terms)


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
    assert "as otherwise provided in" in cue_terms
    assert "does not affect" in cue_terms


def test_temporal_profile_includes_deadline_and_calendar_scope_cues() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.TEMPORAL)
    cue_terms = {cue for operator in profile.operators for cue in operator.cue_terms}

    assert "not later than" in cue_terms
    assert "effective date" in cue_terms
    assert "fiscal year" in cue_terms
    assert "fiscal years" in cue_terms
    assert "for each fiscal year" in cue_terms
    assert "from time to time" in cue_terms
    assert "on or after" in cue_terms
    assert "after notice and opportunity for hearing" in cue_terms


def test_doxastic_profile_includes_belief_and_intent_inflections() -> None:
    profile = DEFAULT_MODAL_REGISTRY.get_profile(ModalLogicFamily.DOXASTIC)
    cue_terms = {cue for operator in profile.operators for cue in operator.cue_terms}

    assert "believe" in cue_terms
    assert "believed" in cue_terms
    assert "belief" in cue_terms
    assert "intend" in cue_terms
    assert "intended" in cue_terms
    assert "suspect" in cue_terms
    assert "suspected" in cue_terms
    assert "intent to" in cue_terms
    assert "with intent to" in cue_terms


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


def test_adaptive_policy_helpers_normalize_prefixed_and_separator_family_tokens() -> None:
    assert is_compiler_ambiguity_policy_pair("modal_family:deontic", "epistemic")
    assert is_compiler_ambiguity_policy_pair(
        "flogic:modal_family:frame",
        "temporal",
    )
    assert is_compiler_ambiguity_policy_pair("frame", "conditional-normative")
    assert supports_signal_free_adaptive_ambiguity_pair(
        "flogic:modal_family:deontic",
        "modal_family:temporal",
    )


def test_signal_free_pair_helper_normalizes_prefixed_and_enum_style_family_tokens() -> None:
    assert is_signal_free_adaptive_ambiguity_pair(
        "flogic:modal_family:frame",
        "ModalLogicFamily.TEMPORAL",
    )
    assert is_signal_free_adaptive_ambiguity_pair(
        "modal_family:alethic",
        "ModalLogicFamily.DYNAMIC",
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        "modal_family:alethic",
        "ModalLogicFamily.DYNAMIC",
    )


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
    assert supports_signal_free_adaptive_ambiguity_pair("dynamic", "temporal")
    assert supports_signal_free_adaptive_ambiguity_pair("epistemic", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair(
        "epistemic",
        "conditional_normative",
    )
    assert supports_signal_free_adaptive_ambiguity_pair("epistemic", "epistemic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "deontic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "alethic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "epistemic")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "frame")
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "temporal")
    assert supports_signal_free_adaptive_ambiguity_pair("dynamic", "temporal")
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
    assert supports_signal_free_adaptive_ambiguity_pair("frame", "doxastic")
    assert supports_signal_free_adaptive_ambiguity_pair(
        "epistemic",
        "temporal",
    )


def test_compiler_required_adaptive_ambiguity_pairs_are_covered_by_both_policies() -> None:
    required_non_priority_pairs = {
        ("conditional_normative", "conditional_normative"),
        ("dynamic", "dynamic"),
        ("epistemic", "epistemic"),
        ("epistemic", "temporal"),
        ("frame", "alethic"),
        ("frame", "frame"),
    }
    for predicted_family, target_family in (
        COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
    ):
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        is_priority_pair = is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        is_compiler_pair = is_compiler_ambiguity_policy_pair(
            predicted_family,
            target_family,
        )
        if predicted_family == target_family and not (
            is_priority_pair or is_compiler_pair
        ):
            continue
        if (
            predicted_family,
            target_family,
        ) == ("epistemic", "temporal"):
            continue
        assert is_priority_pair or is_compiler_pair
        if (predicted_family, target_family) in required_non_priority_pairs:
            assert not is_priority_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )
        else:
            assert is_priority_signal_free_adaptive_ambiguity_pair(
                predicted_family,
                target_family,
            )


def test_signal_free_support_falls_back_to_compiler_required_policy_pairs(
    monkeypatch,
) -> None:
    trimmed_signal_free_pairs = tuple(
        pair
        for pair in modal_registry.SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if pair != ("frame", "alethic")
    )
    monkeypatch.setattr(
        modal_registry,
        "SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
        trimmed_signal_free_pairs,
    )

    assert supports_signal_free_adaptive_ambiguity_pair(
        "frame",
        "alethic",
    ) is True


def test_signal_free_support_falls_back_to_compiler_ambiguity_bundle_pairs(
    monkeypatch,
) -> None:
    trimmed_signal_free_pairs = tuple(
        pair
        for pair in modal_registry.SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if pair != ("frame", "dynamic")
    )
    trimmed_required_pairs = tuple(
        pair
        for pair in modal_registry.COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if pair != ("frame", "dynamic")
    )
    monkeypatch.setattr(
        modal_registry,
        "SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
        trimmed_signal_free_pairs,
    )
    monkeypatch.setattr(
        modal_registry,
        "COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
        trimmed_required_pairs,
    )

    assert supports_signal_free_adaptive_ambiguity_pair(
        "frame",
        "dynamic",
    ) is True


def test_compiler_required_adaptive_ambiguity_bundle_covers_deontic_conflict_pairs() -> None:
    required_pairs = set(COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS)

    assert ("alethic", "deontic") in required_pairs
    assert ("alethic", "conditional_normative") in required_pairs
    assert ("alethic", "epistemic") in required_pairs
    assert ("alethic", "temporal") in required_pairs
    assert ("conditional_normative", "deontic") in required_pairs
    assert ("deontic", "conditional_normative") in required_pairs
    assert ("deontic", "dynamic") in required_pairs
    assert ("deontic", "epistemic") in required_pairs
    assert ("epistemic", "conditional_normative") in required_pairs
    assert ("deontic", "deontic") in required_pairs
    assert ("deontic", "temporal") in required_pairs
    assert ("dynamic", "temporal") in required_pairs
    assert ("epistemic", "conditional_normative") in required_pairs
    assert ("epistemic", "temporal") in required_pairs
    assert ("frame", "conditional_normative") in required_pairs
    assert ("frame", "deontic") in required_pairs
    assert ("frame", "alethic") in required_pairs
    assert ("frame", "epistemic") in required_pairs
    assert ("frame", "temporal") in required_pairs
    assert ("frame", "doxastic") in required_pairs
    assert ("temporal", "conditional_normative") in required_pairs
    assert ("temporal", "deontic") in required_pairs
    assert ("temporal", "epistemic") in required_pairs
    assert ("temporal", "temporal") in required_pairs
    assert compiler_required_adaptive_ambiguity_targets("alethic") == (
        "deontic",
        "conditional_normative",
        "epistemic",
        "temporal",
        "frame",
    )
    assert compiler_required_adaptive_ambiguity_targets("conditional_normative") == (
        "deontic",
        "temporal",
        "conditional_normative",
    )
    assert compiler_required_adaptive_ambiguity_targets("deontic") == (
        "conditional_normative",
        "dynamic",
        "epistemic",
        "deontic",
        "temporal",
        "frame",
    )
    assert compiler_required_adaptive_ambiguity_targets("dynamic") == (
        "dynamic",
        "temporal",
    )
    assert compiler_required_adaptive_ambiguity_targets("epistemic") == (
        "deontic",
        "conditional_normative",
        "epistemic",
        "temporal",
    )
    assert compiler_required_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "alethic",
        "epistemic",
        "temporal",
        "frame",
        "doxastic",
    )
    assert compiler_required_adaptive_ambiguity_targets("temporal") == (
        "deontic",
        "epistemic",
        "conditional_normative",
        "frame",
        "temporal",
    )


def test_compiler_ambiguity_policy_pair_helper_matches_declared_bundle() -> None:
    assert set(COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS) == {
        ("alethic", "conditional_normative"),
        ("alethic", "deontic"),
        ("alethic", "epistemic"),
        ("alethic", "frame"),
        ("conditional_normative", "conditional_normative"),
        ("conditional_normative", "deontic"),
        ("conditional_normative", "epistemic"),
        ("conditional_normative", "temporal"),
        ("conditional_normative", "frame"),
        ("deontic", "conditional_normative"),
        ("deontic", "deontic"),
        ("deontic", "dynamic"),
        ("deontic", "epistemic"),
        ("deontic", "temporal"),
        ("deontic", "frame"),
        ("dynamic", "temporal"),
        ("epistemic", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "frame"),
        ("frame", "alethic"),
        ("frame", "epistemic"),
        ("frame", "dynamic"),
        ("frame", "temporal"),
        ("frame", "doxastic"),
        ("frame", "frame"),
        ("hybrid", "frame"),
        ("temporal", "deontic"),
        ("temporal", "alethic"),
        ("temporal", "epistemic"),
        ("temporal", "conditional_normative"),
        ("temporal", "frame"),
        ("temporal", "temporal"),
    }
    assert is_compiler_ambiguity_policy_pair(
        "alethic",
        "conditional_normative",
    ) is True
    assert is_compiler_ambiguity_policy_pair("alethic", "deontic") is True
    assert is_compiler_ambiguity_policy_pair("alethic", "epistemic") is True
    assert is_compiler_ambiguity_policy_pair("alethic", "frame") is True
    assert (
        is_compiler_ambiguity_policy_pair(
            "conditional_normative",
            "conditional_normative",
        )
        is True
    )
    assert is_compiler_ambiguity_policy_pair("conditional_normative", "deontic") is True
    assert is_compiler_ambiguity_policy_pair(
        "conditional_normative",
        "epistemic",
    ) is True
    assert is_compiler_ambiguity_policy_pair("conditional_normative", "temporal") is True
    assert is_compiler_ambiguity_policy_pair("conditional_normative", "frame") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "conditional_normative") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "deontic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "dynamic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "epistemic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "temporal") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "frame") is True
    assert is_compiler_ambiguity_policy_pair("dynamic", "temporal") is True
    assert is_compiler_ambiguity_policy_pair(
        "epistemic",
        "conditional_normative",
    ) is True
    assert is_compiler_ambiguity_policy_pair("frame", "conditional_normative") is True
    assert is_compiler_ambiguity_policy_pair("frame", "deontic") is True
    assert is_compiler_ambiguity_policy_pair("frame", "frame") is True
    assert is_compiler_ambiguity_policy_pair("frame", "alethic") is True
    assert is_compiler_ambiguity_policy_pair("frame", "epistemic") is True
    assert is_compiler_ambiguity_policy_pair("frame", "dynamic") is True
    assert is_compiler_ambiguity_policy_pair("frame", "temporal") is True
    assert is_compiler_ambiguity_policy_pair("frame", "doxastic") is True
    assert is_compiler_ambiguity_policy_pair("frame", "frame") is True
    assert is_compiler_ambiguity_policy_pair("hybrid", "frame") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "deontic") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "alethic") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "epistemic") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "conditional_normative") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "frame") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "temporal") is True
    assert is_compiler_ambiguity_policy_pair("frame", "hybrid") is False
    assert is_compiler_required_adaptive_ambiguity_pair(
        "frame",
        "conditional_normative",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "deontic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "alethic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "epistemic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "temporal") is True
    assert is_compiler_required_adaptive_ambiguity_pair("frame", "doxastic") is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "conditional_normative",
        "deontic",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "conditional_normative",
        "conditional_normative",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair("deontic", "dynamic") is True
    assert is_compiler_required_adaptive_ambiguity_pair("alethic", "deontic") is True
    assert (
        is_compiler_required_adaptive_ambiguity_pair(
            "alethic",
            "conditional_normative",
        )
        is True
    )
    assert is_compiler_required_adaptive_ambiguity_pair(
        "alethic",
        "epistemic",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair("alethic", "temporal") is True
    assert is_compiler_required_adaptive_ambiguity_pair("alethic", "epistemic") is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "temporal",
        "conditional_normative",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "deontic",
        "epistemic",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "epistemic",
        "conditional_normative",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair(
        "epistemic",
        "temporal",
    ) is True
    assert is_compiler_required_adaptive_ambiguity_pair("dynamic", "temporal") is True
    assert is_compiler_required_adaptive_ambiguity_pair("deontic", "temporal") is True
    assert is_compiler_required_adaptive_ambiguity_pair("temporal", "temporal") is True


def test_compiler_ambiguity_policy_targets_are_ordered_and_directional() -> None:
    assert compiler_ambiguity_policy_targets("alethic") == (
        "deontic",
        "conditional_normative",
        "epistemic",
        "frame",
    )
    assert compiler_ambiguity_policy_targets("deontic") == (
        "conditional_normative",
        "dynamic",
        "epistemic",
        "deontic",
        "temporal",
        "frame",
    )
    assert compiler_ambiguity_policy_targets("dynamic") == ("temporal",)
    assert compiler_ambiguity_policy_targets("frame") == (
        "conditional_normative",
        "deontic",
        "frame",
        "alethic",
        "epistemic",
        "dynamic",
        "temporal",
        "doxastic",
    )
    assert compiler_ambiguity_policy_targets("dynamic") == (
        "temporal",
    )
    assert compiler_ambiguity_policy_targets("temporal") == (
        "deontic",
        "alethic",
        "epistemic",
        "conditional_normative",
        "frame",
        "temporal",
    )
    assert compiler_ambiguity_policy_targets("temporal") == (
        "deontic",
        "alethic",
        "epistemic",
        "conditional_normative",
        "frame",
        "temporal",
    )
    assert compiler_ambiguity_policy_targets("conditional_normative") == (
        "deontic",
        "temporal",
        "conditional_normative",
        "epistemic",
        "frame",
    )
    assert compiler_ambiguity_policy_targets("temporal") == (
        "deontic",
        "alethic",
        "epistemic",
        "conditional_normative",
        "frame",
        "temporal",
    )


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
    assert signal_free_adaptive_ambiguity_targets("dynamic") == (
        "temporal",
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
        "conditional_normative",
        "epistemic",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "frame",
        "alethic",
        "epistemic",
        "dynamic",
        "temporal",
        "doxastic",
    )
    assert signal_free_adaptive_ambiguity_targets("hybrid") == ("frame",)


def test_signal_free_adaptive_ambiguity_targets_do_not_repeat_pairs() -> None:
    for family in (
        "alethic",
        "conditional_normative",
        "deontic",
        "dynamic",
        "epistemic",
        "frame",
        "hybrid",
        "temporal",
    ):
        targets = signal_free_adaptive_ambiguity_targets(family)
        assert len(targets) == len(set(targets))


def test_priority_signal_free_adaptive_ambiguity_pair_policy_is_directional() -> None:
    expected_pairs = {
        ("alethic", "deontic"),
        ("alethic", "conditional_normative"),
        ("alethic", "epistemic"),
        ("alethic", "temporal"),
        ("alethic", "frame"),
        ("deontic", "conditional_normative"),
        ("deontic", "epistemic"),
        ("deontic", "frame"),
        ("deontic", "temporal"),
        ("deontic", "dynamic"),
        ("deontic", "deontic"),
        ("conditional_normative", "deontic"),
        ("conditional_normative", "temporal"),
        ("conditional_normative", "frame"),
        ("temporal", "conditional_normative"),
        ("temporal", "deontic"),
        ("temporal", "alethic"),
        ("temporal", "epistemic"),
        ("temporal", "frame"),
        ("temporal", "temporal"),
        ("hybrid", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
        ("frame", "temporal"),
        ("frame", "doxastic"),
        ("epistemic", "deontic"),
        ("epistemic", "conditional_normative"),
    }
    for predicted_family, target_family in expected_pairs:
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
    assert not is_priority_signal_free_adaptive_ambiguity_pair("frame", "alethic")
    assert not is_priority_signal_free_adaptive_ambiguity_pair("epistemic", "temporal")
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
        "epistemic",
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
        "dynamic",
        "temporal",
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
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "epistemic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "frame")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "temporal")
    assert is_priority_signal_free_adaptive_ambiguity_pair("hybrid", "frame")
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "frame",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "deontic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "alethic") is False
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "epistemic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "temporal")
    assert is_priority_signal_free_adaptive_ambiguity_pair("epistemic", "deontic")
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "epistemic",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "epistemic",
        "temporal",
    ) is False


def test_priority_signal_free_adaptive_targets_are_ordered_directional_subsets() -> None:
    assert priority_signal_free_adaptive_ambiguity_targets("alethic") == (
        "deontic",
        "conditional_normative",
        "epistemic",
        "temporal",
        "frame",
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
        "epistemic",
        "frame",
        "temporal",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "epistemic",
        "temporal",
        "doxastic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("deontic") == (
        "conditional_normative",
        "epistemic",
        "frame",
        "temporal",
        "dynamic",
        "deontic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("dynamic") == (
        "temporal",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("epistemic") == (
        "deontic",
        "conditional_normative",
    )


def test_priority_signal_free_policy_covers_recurrent_compiler_ambiguity_pairs() -> None:
    recurrent_pairs = (
        ("alethic", "deontic"),
        ("alethic", "conditional_normative"),
        ("alethic", "epistemic"),
        ("alethic", "temporal"),
        ("conditional_normative", "deontic"),
        ("deontic", "conditional_normative"),
        ("deontic", "deontic"),
        ("deontic", "frame"),
        ("deontic", "temporal"),
        ("dynamic", "temporal"),
        ("conditional_normative", "temporal"),
        ("temporal", "epistemic"),
        ("temporal", "frame"),
        ("temporal", "temporal"),
        ("epistemic", "deontic"),
        ("epistemic", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
        ("frame", "temporal"),
        ("frame", "doxastic"),
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
