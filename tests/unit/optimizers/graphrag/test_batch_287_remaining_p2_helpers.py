"""Coverage for remaining unchecked GraphRAG P2 helper methods."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


def _result() -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.95),
            Entity(id="e2", type="Person", text="Bob", confidence=0.80),
            Entity(id="e3", type="Org", text="Acme", confidence=0.60),
            Entity(id="e4", type="Place", text="NY", confidence=0.55),
            Entity(id="e5", type="Place", text="SF", confidence=0.50),
        ],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.8),
            Relationship(id="r2", source_id="e2", target_id="e4", type="visited", confidence=0.7),
            Relationship(id="r3", source_id="e4", target_id="e5", type="near", confidence=0.6),
        ],
        confidence=0.7,
        metadata={"source": "unit-test"},
        errors=["warn"],
    )


def test_generator_split_result_balanced_and_metadata() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = _result()

    chunks = gen.split_result(result, 2)
    assert [len(c.entities) for c in chunks] == [3, 2]
    assert [r.id for r in chunks[0].relationships] == ["r1"]
    assert [r.id for r in chunks[1].relationships] == ["r3"]
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[1].metadata["chunk_count"] == 2
    assert chunks[0].errors == ["warn"]

    with pytest.raises(ValueError, match="n must be >= 1"):
        gen.split_result(result, 0)


def test_critic_dimension_rankings_and_weakest_scores() -> None:
    critic = OntologyCritic(use_llm=False)
    score = CriticScore(
        completeness=0.4,
        consistency=0.7,
        clarity=0.6,
        granularity=0.2,
        relationship_coherence=0.5,
        domain_alignment=0.9,
    )
    assert critic.dimension_rankings(score) == [
        "domain_alignment",
        "consistency",
        "clarity",
        "relationship_coherence",
        "completeness",
        "granularity",
    ]

    s1 = CriticScore(0.2, 0.2, 0.2, 0.2, 0.2, 0.2)
    s2 = CriticScore(0.7, 0.7, 0.7, 0.7, 0.7, 0.7)
    s3 = CriticScore(0.1, 0.1, 0.1, 0.1, 0.1, 0.1)
    assert [s.overall for s in critic.weakest_scores([s1, s2, s3], n=2)] == [0.1, 0.2]


def test_mediator_bulk_action_count_and_actions_never_applied() -> None:
    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    recorded = mediator.apply_action_bulk(
        [
            "add_entity",
            ("add_entity", {"id": "e1"}),
            {"action": "merge_entities"},
        ]
    )
    assert recorded == 3
    assert mediator.action_count_for("add_entity") == 2
    assert mediator.action_count_for("merge_entities") == 1

    never = mediator.actions_never_applied()
    assert "add_entity" not in never
    assert "add_missing_properties" in never


def test_unreachable_entities_describe_and_entity_ids_helpers() -> None:
    validator = LogicValidator(use_cache=False)
    ontology = {
        "entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}, {"id": "e4"}],
        "relationships": [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e3"},
        ],
    }
    assert validator.unreachable_entities(ontology, source="e1") == ["e4"]

    cfg = ExtractionConfig(confidence_threshold=0.7, max_entities=12)
    described = cfg.describe()
    assert "threshold=0.7" in described
    assert "max_entities=12" in described

    assert _result().entity_ids == ["e1", "e2", "e3", "e4", "e5"]
