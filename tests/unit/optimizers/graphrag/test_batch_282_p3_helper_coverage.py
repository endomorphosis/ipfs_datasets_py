"""Coverage for remaining unchecked P3 helper methods."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def _sample_result() -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9),
            Entity(id="e2", type="Person", text="Bob", confidence=0.8),
            Entity(id="e3", type="Organization", text="Acme", confidence=0.7),
        ],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.6),
            Relationship(id="r2", source_id="e1", target_id="e3", type="worksFor", confidence=0.6),
        ],
        confidence=0.82,
    )


def test_logic_validator_validate_all_preserves_order() -> None:
    validator = LogicValidator(use_cache=False)
    validator.check_consistency = lambda ontology: SimpleNamespace(  # type: ignore[method-assign]
        is_consistent=ontology.get("id")
    )
    ontologies = [{"id": "a"}, {"id": "b"}]

    results = validator.validate_all(ontologies)

    assert [r.is_consistent for r in results] == ["a", "b"]


def test_critic_score_to_list_dimension_order() -> None:
    score = CriticScore(
        completeness=0.1,
        consistency=0.2,
        clarity=0.3,
        granularity=0.4,
        relationship_coherence=0.5,
        domain_alignment=0.6,
    )
    assert score.to_list() == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def test_generator_describe_result_and_config_summary() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = _sample_result()
    desc = gen.describe_result(result)

    assert "3 entities" in desc
    assert "2 relationships" in desc
    assert "confidence 0.82" in desc

    cfg = ExtractionConfig(confidence_threshold=0.65, max_entities=123, max_relationships=10)
    summary = cfg.summary()
    assert "threshold=0.65" in summary
    assert "max_entities=123" in summary


def test_entity_result_filter_by_type_and_relationships_for() -> None:
    result = _sample_result()

    persons_only = result.filter_by_type("Person")
    assert [e.id for e in persons_only.entities] == ["e1", "e2"]
    # r2 references organization e3, so only r1 remains
    assert [r.id for r in persons_only.relationships] == ["r1"]

    rels_for_e1 = result.relationships_for("e1")
    assert {r.id for r in rels_for_e1} == {"r1", "r2"}


def test_pipeline_total_runs_and_mediator_stash() -> None:
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline._run_history = [SimpleNamespace(score=SimpleNamespace(overall=0.1))]  # type: ignore[attr-defined]
    assert pipeline.total_runs() == 1

    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    ontology = {"entities": [{"id": "e1"}], "relationships": []}
    assert mediator.stash(ontology) == 1
    ontology["entities"][0]["id"] = "changed"
    assert mediator.peek_undo()["entities"][0]["id"] == "e1"  # type: ignore[index]
