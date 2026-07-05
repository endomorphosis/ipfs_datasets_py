"""Tests for the deterministic modal logic registry."""

from __future__ import annotations

import json

import ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry as modal_registry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000394_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000495_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_005849_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_004796_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS,
    COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS,
    COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000258_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000116_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000194_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000226_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_000440_FAMILY_PAIRS,
    COMPILER_REFINED_PACKET_003441_FAMILY_PAIRS,
    COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
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


def test_adaptive_policy_helpers_normalize_directional_family_pair_tokens() -> None:
    assert is_compiler_ambiguity_policy_pair("frame", "frame->deontic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "deontic->temporal") is True
    assert supports_signal_free_adaptive_ambiguity_pair(
        "temporal",
        "temporal->frame",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "frame->deontic",
        "deontic",
    )
    assert "deontic" in compiler_ambiguity_policy_targets("frame->deontic")


def test_refined_modal_family_cue_margin_buffer_is_pair_specific_and_normalized() -> None:
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            "conditional_normative",
            "conditional_normative",
        )
        >= 0.0015
    )
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            "deontic",
            "deontic",
        )
        >= 0.076
    )
    assert abs(
        compiler_refined_modal_family_cue_margin_buffer(
            "temporal",
            "temporal->deontic",
        )
        - 0.0015
    ) <= 1e-12
    assert abs(
        compiler_refined_modal_family_cue_margin_buffer(
            "temporal",
            "temporal",
        )
        - 0.0015
    ) <= 1e-12
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            "frame",
            "deontic",
        )
        >= 0.0015
    )


def test_refined_modal_family_cue_policy_pairs_cover_compiler_registry_todo_bundle() -> None:
    refined_pairs = set(modal_registry.COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    assert ("conditional_normative", "conditional_normative") in refined_pairs
    assert ("deontic", "deontic") in refined_pairs
    assert ("temporal", "deontic") in refined_pairs


def test_packet_000226_refined_frame_family_pairs_cover_weak_typed_targets() -> None:
    packet_pairs = (
        ("frame", "conditional_normative"),
        ("frame", "epistemic"),
    )
    assert COMPILER_REFINED_PACKET_000226_FAMILY_PAIRS == packet_pairs

    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in packet_pairs:
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
            >= 0.36
        )


def test_packet_003441_refined_cue_pairs_cover_weak_family_evidence() -> None:
    packet_pairs = (
        ("deontic", "deontic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    )
    assert COMPILER_REFINED_PACKET_003441_FAMILY_PAIRS == packet_pairs
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in packet_pairs:
        assert (predicted_family, target_family) in refined_pairs
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )

    observed_weak_self_margin = 0.225541191768
    effective_threshold = 0.15 + compiler_refined_modal_family_cue_margin_buffer(
        "deontic",
        "deontic",
    )
    assert effective_threshold > observed_weak_self_margin


def test_packet_000116_refined_cue_pairs_cover_compiler_registry_evidence() -> None:
    packet_pairs = (
        ("conditional_normative", "deontic"),
        ("deontic", "deontic"),
        ("deontic", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "epistemic"),
        ("frame", "temporal"),
        ("temporal", "deontic"),
    )
    assert COMPILER_REFINED_PACKET_000116_FAMILY_PAIRS == packet_pairs
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in packet_pairs:
        assert (predicted_family, target_family) in refined_pairs
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )

    observed_frame_temporal_margin = -0.995435587685
    effective_frame_temporal_threshold = (
        0.15
        + compiler_refined_modal_family_cue_margin_buffer("frame", "temporal")
    )
    assert observed_frame_temporal_margin <= effective_frame_temporal_threshold


def test_packet_000440_family_pairs_are_refined_required_priority_policy() -> None:
    expected_pairs = (
        ("frame", "conditional_normative"),
        ("frame", "temporal"),
        ("temporal", "conditional_normative"),
        ("temporal", "deontic"),
    )
    assert tuple(COMPILER_REFINED_PACKET_000440_FAMILY_PAIRS) == expected_pairs

    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in expected_pairs:
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


def test_packet_001444_family_pairs_are_explicit_signal_free_registry_policy() -> None:
    expected_pairs = (
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "temporal"),
    )
    assert tuple(COMPILER_AMBIGUITY_PACKET_001444_FAMILY_PAIRS) == expected_pairs

    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in expected_pairs:
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


def test_compiler_ambiguity_core_pairs_cover_frame_margin_bundle_targets() -> None:
    core_pairs = set(COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS)
    expected_core_pairs = {
        ("frame", "conditional_normative"),
        ("frame", "epistemic"),
        ("frame", "frame"),
        ("deontic", "conditional_normative"),
        ("deontic", "deontic"),
        ("temporal", "deontic"),
    }
    assert expected_core_pairs.issubset(core_pairs)
    for predicted_family, target_family in expected_core_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_refined_modal_family_cue_policy_pairs_cover_packet_004796_pairs() -> None:
    expected_pairs = (
        ("deontic", "deontic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("temporal", "deontic"),
    )

    assert COMPILER_AMBIGUITY_PACKET_004796_FAMILY_PAIRS == expected_pairs
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in expected_pairs:
        assert (predicted_family, target_family) in refined_pairs
        assert is_compiler_ambiguity_policy_pair(
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
            > 0.0
        )


def test_refined_modal_family_cue_policy_pairs_cover_packet_000043_pairs() -> None:
    expected_pairs = (
        ("frame", "deontic"),
        ("frame", "frame"),
        ("frame", "temporal"),
        ("temporal", "conditional_normative"),
    )

    assert COMPILER_REFINED_PACKET_000043_FAMILY_PAIRS == expected_pairs
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    for predicted_family, target_family in expected_pairs:
        assert (predicted_family, target_family) in refined_pairs
        assert is_compiler_ambiguity_policy_pair(
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
            > 0.0
        )


def test_refined_modal_family_cue_policy_pairs_cover_packet_004705_pairs() -> None:
    expected_pairs = {
        ("conditional_normative", "conditional_normative"),
        ("conditional_normative", "temporal"),
        ("deontic", "conditional_normative"),
        ("deontic", "deontic"),
        ("temporal", "conditional_normative"),
        ("temporal", "deontic"),
    }
    refined_pairs = set(COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS)
    assert expected_pairs.issubset(refined_pairs)
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
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
        "alethic",
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
    assert supports_signal_free_adaptive_ambiguity_pair("temporal", "dynamic")
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
        ("deontic", "alethic"),
        ("epistemic", "epistemic"),
        ("frame", "dynamic"),
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
    assert ("temporal", "dynamic") in required_pairs
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
        "alethic",
        "temporal",
        "conditional_normative",
        "dynamic",
        "frame",
        "epistemic",
    )
    assert compiler_required_adaptive_ambiguity_targets("deontic") == (
        "conditional_normative",
        "dynamic",
        "epistemic",
        "deontic",
        "temporal",
        "frame",
        "doxastic",
        "alethic",
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
        "frame",
    )
    assert compiler_required_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "alethic",
        "epistemic",
        "temporal",
        "frame",
        "doxastic",
        "dynamic",
    )
    assert compiler_required_adaptive_ambiguity_targets("temporal") == (
        "deontic",
        "alethic",
        "epistemic",
        "doxastic",
        "conditional_normative",
        "frame",
        "dynamic",
        "temporal",
    )


def test_compiler_ambiguity_packet_000521_pairs_surface_adaptive_ambiguity() -> None:
    expected_pairs = (
        ("deontic", "deontic"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "frame"),
    )

    assert COMPILER_AMBIGUITY_PACKET_000521_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_signal_free_adaptive_ambiguity_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
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
            > 0.0
        )


def test_compiler_ambiguity_packet_000258_pairs_surface_adaptive_ambiguity() -> None:
    expected_pairs = (
        ("deontic", "deontic"),
        ("deontic", "frame"),
    )

    assert COMPILER_REFINED_PACKET_000258_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_signal_free_adaptive_ambiguity_pair(predicted_family, target_family)
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
            > 0.0
        )


def test_compiler_ambiguity_policy_pair_helper_matches_declared_bundle() -> None:
    assert set(COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS) == {
        ("alethic", "conditional_normative"),
        ("alethic", "deontic"),
        ("alethic", "epistemic"),
        ("alethic", "frame"),
        ("conditional_normative", "conditional_normative"),
        ("conditional_normative", "deontic"),
        ("conditional_normative", "dynamic"),
        ("conditional_normative", "epistemic"),
        ("conditional_normative", "temporal"),
        ("conditional_normative", "frame"),
        ("conditional_normative", "alethic"),
        ("deontic", "conditional_normative"),
        ("deontic", "deontic"),
        ("deontic", "doxastic"),
        ("deontic", "dynamic"),
        ("deontic", "epistemic"),
        ("deontic", "alethic"),
        ("deontic", "temporal"),
        ("deontic", "frame"),
        ("doxastic", "conditional_normative"),
        ("doxastic", "doxastic"),
        ("doxastic", "epistemic"),
        ("dynamic", "dynamic"),
        ("dynamic", "temporal"),
        ("epistemic", "conditional_normative"),
        ("epistemic", "deontic"),
        ("epistemic", "frame"),
        ("epistemic", "temporal"),
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
        ("temporal", "doxastic"),
        ("temporal", "conditional_normative"),
        ("temporal", "frame"),
        ("temporal", "dynamic"),
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
    assert is_compiler_ambiguity_policy_pair("conditional_normative", "alethic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "conditional_normative") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "deontic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "dynamic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "epistemic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "alethic") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "temporal") is True
    assert is_compiler_ambiguity_policy_pair("deontic", "frame") is True
    assert is_compiler_ambiguity_policy_pair("doxastic", "doxastic") is True
    assert is_compiler_ambiguity_policy_pair("dynamic", "temporal") is True
    assert is_compiler_ambiguity_policy_pair(
        "epistemic",
        "conditional_normative",
    ) is True
    assert is_compiler_ambiguity_policy_pair(
        "epistemic",
        "deontic",
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
    assert is_compiler_ambiguity_policy_pair("temporal", "doxastic") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "conditional_normative") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "frame") is True
    assert is_compiler_ambiguity_policy_pair("temporal", "dynamic") is True
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
        "alethic",
        "deontic",
        "temporal",
        "frame",
        "doxastic",
    )
    assert compiler_ambiguity_policy_targets("epistemic") == (
        "conditional_normative",
        "deontic",
        "temporal",
        "frame",
    )
    assert compiler_ambiguity_policy_targets("dynamic") == ("temporal", "dynamic")
    assert compiler_ambiguity_policy_targets("doxastic") == (
        "epistemic",
        "doxastic",
        "conditional_normative",
    )
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
        "dynamic",
    )
    assert compiler_ambiguity_policy_targets("temporal") == (
        "deontic",
        "alethic",
        "epistemic",
        "conditional_normative",
        "frame",
        "dynamic",
        "temporal",
        "doxastic",
    )
    assert compiler_ambiguity_policy_targets("temporal") == (
        "deontic",
        "alethic",
        "epistemic",
        "conditional_normative",
        "frame",
        "dynamic",
        "temporal",
        "doxastic",
    )
    assert compiler_ambiguity_policy_targets("conditional_normative") == (
        "deontic",
        "temporal",
        "conditional_normative",
        "epistemic",
        "frame",
        "alethic",
        "dynamic",
    )
    assert compiler_ambiguity_policy_targets("temporal") == (
        "deontic",
        "alethic",
        "epistemic",
        "conditional_normative",
        "frame",
        "dynamic",
        "temporal",
        "doxastic",
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
        "doxastic",
        "frame",
        "dynamic",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("deontic") == (
        "alethic",
        "deontic",
        "conditional_normative",
        "frame",
        "temporal",
        "epistemic",
        "dynamic",
        "doxastic",
    )
    assert signal_free_adaptive_ambiguity_targets("dynamic") == (
        "temporal",
        "dynamic",
    )
    assert signal_free_adaptive_ambiguity_targets("conditional_normative") == (
        "deontic",
        "conditional_normative",
        "alethic",
        "temporal",
        "epistemic",
        "dynamic",
        "frame",
    )
    assert signal_free_adaptive_ambiguity_targets("epistemic") == (
        "deontic",
        "conditional_normative",
        "epistemic",
        "frame",
        "temporal",
    )
    assert signal_free_adaptive_ambiguity_targets("doxastic") == (
        "epistemic",
        "doxastic",
        "conditional_normative",
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
        ("deontic", "doxastic"),
        ("conditional_normative", "deontic"),
        ("conditional_normative", "alethic"),
        ("conditional_normative", "epistemic"),
        ("conditional_normative", "conditional_normative"),
        ("conditional_normative", "temporal"),
        ("conditional_normative", "dynamic"),
        ("conditional_normative", "frame"),
        ("dynamic", "dynamic"),
        ("doxastic", "conditional_normative"),
        ("doxastic", "doxastic"),
        ("doxastic", "epistemic"),
        ("epistemic", "frame"),
        ("epistemic", "temporal"),
        ("temporal", "conditional_normative"),
        ("temporal", "deontic"),
        ("temporal", "alethic"),
        ("temporal", "epistemic"),
        ("temporal", "doxastic"),
        ("temporal", "frame"),
        ("temporal", "dynamic"),
        ("temporal", "temporal"),
        ("hybrid", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "frame"),
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
    assert is_priority_signal_free_adaptive_ambiguity_pair("frame", "alethic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("epistemic", "temporal")
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
        "epistemic",
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
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "doxastic")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "frame")
    assert is_priority_signal_free_adaptive_ambiguity_pair("temporal", "dynamic")
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
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "epistemic",
        "conditional_normative",
    )
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        "epistemic",
        "temporal",
    )


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
        "conditional_normative",
        "alethic",
        "dynamic",
        "epistemic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("temporal") == (
        "conditional_normative",
        "deontic",
        "alethic",
        "epistemic",
        "frame",
        "dynamic",
        "temporal",
        "doxastic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("frame") == (
        "conditional_normative",
        "deontic",
        "epistemic",
        "temporal",
        "doxastic",
        "frame",
        "alethic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("deontic") == (
        "conditional_normative",
        "epistemic",
        "frame",
        "temporal",
        "dynamic",
        "doxastic",
        "deontic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("doxastic") == (
        "epistemic",
        "doxastic",
        "conditional_normative",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("dynamic") == (
        "temporal",
        "dynamic",
    )
    assert priority_signal_free_adaptive_ambiguity_targets("epistemic") == (
        "deontic",
        "conditional_normative",
        "frame",
        "temporal",
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
        ("temporal", "dynamic"),
        ("temporal", "temporal"),
        ("epistemic", "deontic"),
        ("epistemic", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "frame"),
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


def test_packet_001270_recurrent_compiler_registry_family_pairs_are_supported() -> None:
    """Keep packet-001270 recurrent directional family transitions policy-covered."""
    recurrent_pairs = (
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("conditional_normative", "frame"),
        ("temporal", "alethic"),
        ("temporal", "deontic"),
        ("temporal", "frame"),
        ("deontic", "deontic"),
        ("frame", "frame"),
        ("temporal", "temporal"),
        ("conditional_normative", "temporal"),
        ("deontic", "alethic"),
    )
    for predicted_family, target_family in recurrent_pairs:
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_ambiguity_policy_pair(
            predicted_family,
            target_family,
        )


def test_packet_000495_adaptive_family_pairs_are_explicit_ambiguity_policy() -> None:
    """Keep packet-000495 low-margin family transitions reviewable."""
    expected_pairs = (
        ("deontic", "deontic"),
        ("deontic", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "frame"),
    )

    assert COMPILER_AMBIGUITY_PACKET_000495_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_000228_family_pairs_are_explicit_ambiguity_policy() -> None:
    """Expose packet-000228 low-margin family transitions as reviewable ambiguity."""
    expected_pairs = (
        ("deontic", "deontic"),
        ("deontic", "dynamic"),
        ("deontic", "frame"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "doxastic"),
        ("frame", "temporal"),
    )

    assert COMPILER_AMBIGUITY_PACKET_000228_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_000394_frame_family_pairs_are_explicit_ambiguity_policy() -> None:
    """Keep packet-000394 frame predictions reviewable against legal families."""
    expected_pairs = (
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
    )

    assert COMPILER_AMBIGUITY_PACKET_000394_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_005849_family_pairs_are_explicit_ambiguity_policy() -> None:
    """Expose packet-005849 small margins as compiler ambiguity policy."""
    expected_pairs = (
        ("conditional_normative", "conditional_normative"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
    )

    assert COMPILER_AMBIGUITY_PACKET_005849_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_000194_refined_family_cue_pairs_are_policy_covered() -> None:
    """Keep packet-000194 deontic/frame refined cue transitions explicit."""
    expected_pairs = (
        ("deontic", "deontic"),
        ("deontic", "frame"),
        ("frame", "frame"),
    )

    assert COMPILER_REFINED_PACKET_000194_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert (predicted_family, target_family) in (
            COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_signal_free_adaptive_ambiguity_pair(
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
            > 0.0
        )


def test_packet_001807_adaptive_family_pairs_are_explicit_ambiguity_policy() -> None:
    """Keep packet-001807 low-margin family transitions visible to the compiler."""
    expected_pairs = (
        ("deontic", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "deontic"),
    )

    assert COMPILER_AMBIGUITY_PACKET_001807_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_000102_adaptive_family_pairs_are_explicit_ambiguity_policy() -> None:
    """Keep packet-000102 low-margin family transitions visible to the compiler."""
    expected_pairs = (
        ("deontic", "temporal"),
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("frame", "temporal"),
        ("temporal", "deontic"),
    )

    assert COMPILER_AMBIGUITY_PACKET_000102_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_failed_validation_rescue_packet_family_pairs_are_registered() -> None:
    """Keep hand-rescued failed-validation packet pairs syntax-safe and reachable."""
    refined_packets = {
        "003313": (
            ("frame", "deontic"),
            ("frame", "temporal"),
            ("temporal", "deontic"),
        ),
        "003650": (
            ("deontic", "epistemic"),
            ("frame", "deontic"),
            ("frame", "doxastic"),
            ("temporal", "deontic"),
        ),
        "003960": (
            ("conditional_normative", "deontic"),
            ("frame", "conditional_normative"),
            ("frame", "deontic"),
        ),
        "004579": (
            ("deontic", "deontic"),
            ("deontic", "frame"),
            ("frame", "deontic"),
            ("frame", "doxastic"),
            ("frame", "frame"),
            ("temporal", "deontic"),
        ),
        "004746": (
            ("frame", "conditional_normative"),
            ("frame", "deontic"),
            ("temporal", "epistemic"),
        ),
        "004762": (
            ("deontic", "doxastic"),
            ("deontic", "temporal"),
            ("frame", "deontic"),
            ("frame", "temporal"),
        ),
    }

    for packet_id, expected_pairs in refined_packets.items():
        packet_pairs = getattr(
            modal_registry,
            f"COMPILER_REFINED_PACKET_{packet_id}_FAMILY_PAIRS",
        )
        assert packet_pairs == expected_pairs
        for predicted_family, target_family in expected_pairs:
            assert (predicted_family, target_family) in (
                COMPILER_REFINED_MODAL_FAMILY_CUE_POLICY_PAIRS
            )

    ambiguity_pairs = modal_registry.COMPILER_AMBIGUITY_PACKET_001879_FAMILY_PAIRS
    assert ("frame", "dynamic") in ambiguity_pairs
    for predicted_family, target_family in ambiguity_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
