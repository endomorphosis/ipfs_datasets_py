"""Tests for the deterministic modal logic registry."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    ModalRegistry,
    ModalSystem,
    is_normative_modal_family,
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
