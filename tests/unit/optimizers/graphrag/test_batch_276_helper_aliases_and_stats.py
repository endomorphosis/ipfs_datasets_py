"""Coverage for helper aliases already present in GraphRAG components."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def _sample_result() -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9),
            Entity(id="e2", type="Person", text="Bob", confidence=0.4),
        ],
        relationships=[
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="knows",
                confidence=0.8,
            )
        ],
        confidence=0.7,
    )


def test_extraction_config_with_threshold_returns_copy() -> None:
    cfg = ExtractionConfig(confidence_threshold=0.55, max_entities=11)
    updated = cfg.with_threshold(0.8)

    assert updated.confidence_threshold == 0.8
    assert updated.max_entities == 11
    assert cfg.confidence_threshold == 0.55


def test_generator_entity_ids_and_filter_result_by_confidence() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = _sample_result()

    assert gen.entity_ids(result) == ["e1", "e2"]
    filtered = gen.filter_result_by_confidence(result, min_conf=0.5)
    assert [e.id for e in filtered.entities] == ["e1"]
    assert filtered.relationships == []


def test_learning_adapter_feedback_summary_and_ids() -> None:
    adapter = OntologyLearningAdapter()
    adapter.apply_feedback(0.8, actions=[{"action": "normalize"}, {"action": "dedup"}])
    adapter.apply_feedback(0.3, actions=[])

    summary = adapter.feedback_summary_dict()
    assert summary["count"] == 2
    assert summary["mean"] == 0.55
    assert summary["variance"] > 0.0
    assert adapter.feedback_ids() == ["normalize+dedup", "record_1"]


def test_logic_validator_is_empty_helper() -> None:
    validator = LogicValidator(use_cache=False)
    assert validator.is_empty({"entities": [], "relationships": []}) is True
    assert validator.is_empty({"entities": [{"id": "e1"}], "relationships": []}) is False


def test_pipeline_history_helpers_and_critic_pass_helpers() -> None:
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline._run_history = [  # type: ignore[attr-defined]
        SimpleNamespace(score=SimpleNamespace(overall=0.2)),
        SimpleNamespace(score=SimpleNamespace(overall=0.8)),
    ]

    assert pipeline.has_run() is True
    assert pipeline.average_run_score() == 0.5
    assert pipeline.score_at(1) == 0.8

    critic = OntologyCritic(use_llm=False)
    low = CriticScore(0.2, 0.2, 0.2, 0.2, 0.2, 0.2)
    high = CriticScore(0.8, 0.8, 0.8, 0.8, 0.8, 0.8)
    assert critic.passes_all([low, high], threshold=0.2) is True
    assert critic.all_pass([low, high], threshold=0.2) is False
