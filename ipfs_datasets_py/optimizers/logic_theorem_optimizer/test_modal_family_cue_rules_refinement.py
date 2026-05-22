"""Deterministic regressions for modal-family cue refinement rules."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    _apply_competing_scope_backfill,
)


def test_modal_registry_covers_doxastic_self_pair_for_adaptive_policy_tables() -> None:
    predicted = ModalLogicFamily.DOXASTIC.value
    target = ModalLogicFamily.DOXASTIC.value
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
