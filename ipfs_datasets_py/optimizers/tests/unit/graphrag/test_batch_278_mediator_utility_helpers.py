"""Tests for OntologyMediator utility helper methods."""

from __future__ import annotations

from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


def _mediator() -> OntologyMediator:
    return OntologyMediator(generator=Mock(), critic=Mock(), max_rounds=2)


def test_pending_recommendation_returns_top_phrase() -> None:
    mediator = _mediator()
    mediator._recommendation_counts = {  # type: ignore[attr-defined]
        "normalize names": 2,
        "add relationships": 5,
    }

    assert mediator.pending_recommendation() == "add relationships"


def test_action_types_returns_sorted_unique_actions() -> None:
    mediator = _mediator()
    mediator.apply_action_bulk(["merge_duplicates", "add_missing_properties", "merge_duplicates"])

    assert mediator.action_types() == ["add_missing_properties", "merge_duplicates"]


def test_log_snapshot_pushes_snapshot_and_action_entry() -> None:
    mediator = _mediator()
    ontology = {"entities": [{"id": "e1"}], "relationships": []}

    mediator.log_snapshot("before_refine", ontology)
    ontology["entities"][0]["id"] = "changed-after-log"

    snap = mediator.peek_undo()
    assert snap is not None
    assert snap["entities"][0]["id"] == "e1"
    assert mediator.action_log()[-1]["action"] == "snapshot:before_refine"


def test_clear_stash_returns_removed_count_and_clears() -> None:
    mediator = _mediator()
    mediator.stash({"entities": [], "relationships": []})
    mediator.stash({"entities": [{"id": "e1"}], "relationships": []})

    assert mediator.clear_stash() == 2
    assert mediator.get_undo_depth() == 0
