"""Deterministic regressions for modal-family cue refinement rules."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import pytest

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    _apply_competing_scope_backfill,
    _apply_directional_modal_family_pair_backfill,
    SpaCyLegalEncoder,
    modal_ambiguity_signals,
)


def test_modal_registry_covers_doxastic_self_pair_for_adaptive_policy_tables() -> None:
    predicted = ModalLogicFamily.DOXASTIC.value
    target = ModalLogicFamily.DOXASTIC.value
    assert is_compiler_required_adaptive_ambiguity_pair(predicted, target)
    assert is_compiler_ambiguity_policy_pair(predicted, target)
    assert is_signal_free_adaptive_ambiguity_pair(predicted, target)
    assert is_priority_signal_free_adaptive_ambiguity_pair(predicted, target)


@pytest.mark.parametrize(
    ("predicted", "target"),
    (
        (
            ModalLogicFamily.EPISTEMIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    ),
)
def test_modal_registry_packet_002134_directional_pairs_are_supported_across_policy_tables(
    predicted: str,
    target: str,
) -> None:
    assert is_compiler_required_adaptive_ambiguity_pair(predicted, target)
    assert is_compiler_ambiguity_policy_pair(predicted, target)
    assert is_signal_free_adaptive_ambiguity_pair(predicted, target)
    assert is_priority_signal_free_adaptive_ambiguity_pair(predicted, target)


def test_competing_scope_backfill_reinforces_frame_to_deontic_when_scope_is_explicit() -> None:
    counts = {
        ModalLogicFamily.FRAME.value: 4.0,
        ModalLogicFamily.DEONTIC.value: 0.0,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
    }
    _apply_competing_scope_backfill(counts, signals)
    assert counts[ModalLogicFamily.DEONTIC.value] == pytest.approx(0.8)


def test_competing_scope_backfill_reinforces_temporal_to_deontic_when_scope_is_explicit() -> None:
    counts = {
        ModalLogicFamily.TEMPORAL.value: 4.0,
        ModalLogicFamily.DEONTIC.value: 0.0,
    }
    signals = {
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_statutory_scope_reference": True,
    }
    _apply_competing_scope_backfill(counts, signals)
    assert counts[ModalLogicFamily.DEONTIC.value] == pytest.approx(1.0)


def test_competing_scope_backfill_reinforces_temporal_to_frame_when_frame_scope_is_structural() -> None:
    counts = {
        ModalLogicFamily.TEMPORAL.value: 4.0,
        ModalLogicFamily.FRAME.value: 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_frame_context": True,
        "has_statutory_scope_reference": True,
    }
    _apply_competing_scope_backfill(counts, signals)
    assert counts[ModalLogicFamily.FRAME.value] == pytest.approx(1.0)


def test_directional_backfill_reinforces_temporal_to_deontic_with_strong_scope_signals() -> None:
    counts = {
        ModalLogicFamily.TEMPORAL.value: 4.0,
        ModalLogicFamily.DEONTIC.value: 0.4,
    }
    signals = {
        "has_deontic_cue": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_frame_context": True,
        "has_statutory_scope_reference": True,
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
    }
    _apply_directional_modal_family_pair_backfill(counts, signals)
    assert counts[ModalLogicFamily.DEONTIC.value] == pytest.approx(1.35)


def test_directional_backfill_reinforces_epistemic_to_deontic_with_statutory_scope() -> None:
    counts = {
        ModalLogicFamily.EPISTEMIC.value: 4.0,
        ModalLogicFamily.DEONTIC.value: 0.0,
    }
    signals = {
        "has_deontic_cue": True,
        "has_deontic_scope": True,
        "has_deontic_scope_phrase": True,
        "has_epistemic_scope": True,
        "has_frame_context": True,
        "has_statutory_scope_reference": True,
    }
    _apply_directional_modal_family_pair_backfill(counts, signals)
    assert counts[ModalLogicFamily.DEONTIC.value] == pytest.approx(1.35)
def test_spacy_signals_treat_reasonably_believes_as_epistemic_scope_phrase() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The officer reasonably believes the report is false.",
        document_id="cue-rules-reasonably-believes",
    )

    signals = modal_ambiguity_signals(encoding)
    assert signals["has_doxastic_cue"] is True
    assert signals["has_epistemic_scope"] is True
    assert signals["has_epistemic_scope_phrase"] is True


def test_competing_scope_backfill_reinforces_doxastic_to_epistemic_scope_overlap() -> None:
    counts = {
        ModalLogicFamily.DOXASTIC.value: 1.0,
        ModalLogicFamily.EPISTEMIC.value: 0.0,
    }
    signals = {
        "has_epistemic_scope": True,
        "has_epistemic_scope_phrase": True,
    }

    _apply_competing_scope_backfill(counts, signals)
    assert counts[ModalLogicFamily.EPISTEMIC.value] >= 0.35


def test_directional_backfill_reinforces_temporal_to_structural_conditional_scope() -> None:
    counts = {
        ModalLogicFamily.TEMPORAL.value: 0.9,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value: 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_token": True,
        "has_condition_or_exception_scope": True,
        "has_statutory_scope_reference": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)
    assert counts[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] >= 0.35


def test_directional_backfill_reinforces_temporal_to_structural_frame_scope() -> None:
    counts = {
        ModalLogicFamily.TEMPORAL.value: 0.9,
        ModalLogicFamily.FRAME.value: 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_token": True,
        "has_statutory_scope_reference": True,
        "has_frame_context": True,
    }

    _apply_directional_modal_family_pair_backfill(counts, signals)
    assert counts[ModalLogicFamily.FRAME.value] >= 0.35


def test_compiler_tracks_epistemic_target_signals_for_doxastic_predictions() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="regex")
    )

    target_signals = compiler._adaptive_target_signal_by_family(
        ModalLogicFamily.DOXASTIC.value,
        signals={
            "has_epistemic_scope": True,
            "has_epistemic_scope_phrase": True,
        },
        has_frame_scope=False,
    )

    assert target_signals == {
        ModalLogicFamily.EPISTEMIC.value: True,
    }
def test_packet_003115_refined_pairs_include_temporal_to_alethic_as_required_target() -> None:
    predicted = ModalLogicFamily.TEMPORAL.value
    target = ModalLogicFamily.ALETHIC.value
    assert target in compiler_required_adaptive_ambiguity_targets(predicted)
    assert is_compiler_required_adaptive_ambiguity_pair(predicted, target)
    assert is_compiler_ambiguity_policy_pair(predicted, target)
    assert is_signal_free_adaptive_ambiguity_pair(predicted, target)
    assert is_priority_signal_free_adaptive_ambiguity_pair(predicted, target)


def test_competing_scope_backfill_reinforces_temporal_to_alethic_with_explicit_scope() -> None:
    counts = {
        ModalLogicFamily.TEMPORAL.value: 4.0,
        ModalLogicFamily.ALETHIC.value: 0.0,
    }
    signals = {
        "has_temporal_scope": True,
        "has_temporal_scope_phrase": True,
        "has_temporal_scope_token": True,
        "has_alethic_scope": True,
        "has_alethic_scope_phrase": True,
    }
    _apply_competing_scope_backfill(counts, signals)
    assert counts[ModalLogicFamily.ALETHIC.value] == pytest.approx(0.35)
