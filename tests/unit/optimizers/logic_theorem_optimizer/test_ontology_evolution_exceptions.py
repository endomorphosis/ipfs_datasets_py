"""Tests for typed exception handling in ontology evolution updates."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import ontology_evolution as oe


def test_apply_single_update_handles_typed_runtime_error() -> None:
    evolution = oe.OntologyEvolution(base_ontology={"terms": []})
    candidate = oe.UpdateCandidate(
        event_type=oe.EvolutionEvent.TERM_ADDED,
        item="new_term",
        confidence=0.9,
    )

    class BadTerms(list):
        def append(self, item):  # type: ignore[override]
            raise RuntimeError("append failed")

    evolution.current_ontology["terms"] = BadTerms()

    assert evolution._apply_single_update(candidate) is False


def test_apply_single_update_does_not_swallow_keyboard_interrupt() -> None:
    evolution = oe.OntologyEvolution(base_ontology={})
    candidate = oe.UpdateCandidate(
        event_type=oe.EvolutionEvent.RELATION_ADDED,
        item={"name": "rel"},
        confidence=0.9,
    )

    class BombDict(dict):
        def __contains__(self, key):
            raise KeyboardInterrupt()

    evolution.current_ontology = BombDict()

    with pytest.raises(KeyboardInterrupt):
        evolution._apply_single_update(candidate)
