"""Tests for OntologyMediator.batch_apply_strategies error handling."""

from __future__ import annotations

from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


def test_batch_apply_strategies_collects_refine_errors_without_crashing() -> None:
    mediator = OntologyMediator(generator=Mock(), critic=Mock(), max_rounds=2)
    context = Mock()

    ontologies = [
        {"entities": [{"id": "e1"}], "relationships": []},
        {"entities": [{"id": "e2"}], "relationships": []},
    ]
    feedbacks = [Mock(), Mock()]

    def _fake_refine(ontology, _feedback, _context):
        if ontology["entities"][0]["id"] == "e2":
            raise ValueError("synthetic failure")
        return {
            "entities": list(ontology["entities"]),
            "relationships": list(ontology["relationships"]),
            "metadata": {},
        }

    mediator.refine_ontology = _fake_refine  # type: ignore[method-assign]
    out = mediator.batch_apply_strategies(ontologies, feedbacks, context, max_workers=1)

    assert out["success_count"] == 1
    assert out["error_count"] == 1
    assert len(out["errors"]) == 1
    assert out["errors"][0]["error_type"] == "ValueError"


def test_batch_apply_strategies_validates_input_lengths() -> None:
    mediator = OntologyMediator(generator=Mock(), critic=Mock(), max_rounds=2)

    try:
        mediator.batch_apply_strategies(
            ontologies=[{"entities": [], "relationships": []}],
            feedbacks=[],
            context=Mock(),
            max_workers=1,
        )
        assert False, "Expected ValueError for length mismatch"
    except ValueError as exc:
        assert "Length mismatch" in str(exc)
