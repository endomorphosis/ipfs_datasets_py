"""Coverage for remaining unchecked P2 GraphRAG helper methods."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)


def test_generator_rebuild_result_wraps_entities_and_relationships() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    entities = [Entity(id="e1", type="Person", text="Alice", confidence=0.9)]
    rels = [Relationship(id="r1", source_id="e1", target_id="e1", type="self", confidence=0.4)]

    result = gen.rebuild_result(entities, relationships=rels, confidence=0.77, metadata={"x": 1})

    assert result.entities[0].id == "e1"
    assert result.relationships[0].id == "r1"
    assert result.confidence == 0.77
    assert result.metadata == {"x": 1}


def test_critic_evaluate_list_returns_scores_in_input_order() -> None:
    critic = OntologyCritic(use_llm=False)
    ontologies = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

    def _fake_eval(ontology, _context):
        key = ontology["id"]
        val = {"a": 0.2, "b": 0.4, "c": 0.8}[key]
        return CriticScore(val, val, val, val, val, val)

    critic.evaluate_ontology = _fake_eval  # type: ignore[method-assign]
    scores = critic.evaluate_list(ontologies, context=SimpleNamespace(domain="test"))

    assert [round(s.overall, 6) for s in scores] == [0.2, 0.4, 0.8]


def test_learning_adapter_score_variance_reports_population_variance() -> None:
    adapter = OntologyLearningAdapter()
    adapter.apply_feedback(0.2, actions=[])
    adapter.apply_feedback(0.8, actions=[])

    # mean=0.5, variance=((0.3^2)+(0.3^2))/2=0.09
    assert adapter.score_variance() == pytest.approx(0.09)


def test_group_entities_by_confidence_band_buckets_entities() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = gen.rebuild_result(
        entities=[
            Entity(id="e1", type="Person", text="A", confidence=0.2),
            Entity(id="e2", type="Person", text="B", confidence=0.5),
            Entity(id="e3", type="Person", text="C", confidence=0.9),
        ]
    )

    buckets = gen.group_entities_by_confidence_band(result, bands=[0.3, 0.7])

    assert [e.id for e in buckets["<0.3"]] == ["e1"]
    assert [e.id for e in buckets["[0.3,0.7)"]] == ["e2"]
    assert [e.id for e in buckets[">=0.7"]] == ["e3"]
