"""Bulk coverage for remaining GraphRAG helper methods."""

from __future__ import annotations

from types import SimpleNamespace
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
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def _result() -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9, properties={"x": 1}),
            Entity(id="e2", type="Person", text="Bob", confidence=0.4),
            Entity(id="e3", type="Organization", text="Acme", confidence=0.7),
        ],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.8),
            Relationship(id="r2", source_id="e1", target_id="e9", type="broken", confidence=0.6),
        ],
        confidence=0.65,
    )


def _score(v: float) -> CriticScore:
    return CriticScore(v, v, v, v, v, v)


def test_entity_result_helpers_top_entities_types_and_stats() -> None:
    result = _result()
    assert [e.id for e in result.top_entities(2)] == ["e1", "e3"]
    assert [e.id for e in result.entities_of_type("person")] == ["e1", "e2"]
    stats = result.confidence_stats()
    assert stats["count"] == 3.0
    assert stats["max"] == 0.9
    assert stats["min"] == 0.4


def test_extraction_config_clone_diff_and_is_strict() -> None:
    cfg = ExtractionConfig(confidence_threshold=0.81, max_entities=10)
    clone = cfg.clone()
    assert clone is not cfg
    assert clone.to_dict() == cfg.to_dict()
    assert cfg.is_strict() is True

    other = cfg.with_threshold(0.5)
    diff = cfg.diff(other)
    assert "confidence_threshold" in diff
    assert diff["confidence_threshold"]["self"] == 0.81
    assert diff["confidence_threshold"]["other"] == 0.5


def test_generator_validate_confidence_clone_add_remove_and_normalize() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = _result()

    issues = gen.validate_result(result)
    assert any("unknown target_id 'e9'" in msg for msg in issues)

    stats = gen.confidence_stats(result)
    assert stats["count"] == 3.0
    assert stats["max"] == 0.9

    cloned = gen.clone_result(result)
    assert cloned is not result
    assert cloned.entities[0].id == "e1"

    added = gen.add_entity(result, Entity(id="e4", type="Person", text="Eve", confidence=0.2))
    assert len(added.entities) == 4
    removed = gen.remove_entity(added, "e1")
    assert all(e.id != "e1" for e in removed.entities)
    assert all(r.source_id != "e1" and r.target_id != "e1" for r in removed.relationships)

    diversity = gen.type_diversity(result)
    assert diversity == 2

    normalized = gen.normalize_confidence(result)
    norm_vals = [e.confidence for e in normalized.entities]
    assert min(norm_vals) == 0.0
    assert max(norm_vals) == 1.0


def test_critic_score_list_helpers() -> None:
    critic = OntologyCritic(use_llm=False)
    scores = [_score(0.2), _score(0.7), _score(0.9)]

    failing = critic.failing_scores(scores, threshold=0.7)
    assert [round(s.overall, 6) for s in failing] == [0.2, 0.7]

    assert critic.average_dimension(scores, "completeness") == pytest.approx((0.2 + 0.7 + 0.9) / 3)

    summary = critic.score_summary(scores)
    assert summary["count"] == 3
    assert summary["passing_fraction"] == pytest.approx(2 / 3)

    assert critic.percentile_overall(scores, 50) == pytest.approx(0.7)
    norm = critic.normalize_scores(scores)
    assert len(norm) == 3
    assert min(s.overall for s in norm) >= 0.0
    assert max(s.overall for s in norm) <= 1.0


def test_optimizer_pipeline_mediator_learning_validator_helper_sets() -> None:
    optimizer = OntologyOptimizer(enable_tracing=False)
    optimizer._history = [  # type: ignore[attr-defined]
        OptimizationReport(average_score=0.2, trend="declining"),
        OptimizationReport(average_score=0.3, trend="improving"),
        OptimizationReport(average_score=0.31, trend="flat"),
    ]
    assert optimizer.trend_string(window=3) in {"improving", "declining", "flat", "volatile"}
    assert len(optimizer.entries_above_score(0.25)) == 2
    assert optimizer.running_average(2) == pytest.approx([0.25, 0.305])
    assert optimizer.score_iqr() >= 0.0
    assert optimizer.has_improved(0.29) is True

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline._run_history = [  # type: ignore[attr-defined]
        SimpleNamespace(score=SimpleNamespace(overall=0.2)),
        SimpleNamespace(score=SimpleNamespace(overall=0.6)),
        SimpleNamespace(score=SimpleNamespace(overall=0.8)),
    ]
    assert pipeline.score_variance() == pytest.approx(((0.2 - 0.5333333333333333) ** 2 + (0.6 - 0.5333333333333333) ** 2 + (0.8 - 0.5333333333333333) ** 2) / 3)
    assert pipeline.score_stddev() == pytest.approx(pipeline.score_variance() ** 0.5)
    assert pipeline.passing_run_count(0.5) == 2
    rs = pipeline.run_summary()
    assert rs["count"] == 3 and rs["min"] == 0.2 and rs["max"] == 0.8
    assert pipeline.is_stable(threshold=0.2, window=3) is True

    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    mediator.apply_action_bulk(["a", "b", "a"])
    mediator.stash({"entities": [], "relationships": []})
    assert mediator.total_action_count() == 3
    assert mediator.top_actions(1) == ["a"]
    assert mediator.undo_depth() == 1
    assert mediator.most_frequent_action() == "a"
    assert mediator.action_count_total() == 3

    adapter = OntologyLearningAdapter()
    adapter.apply_feedback(0.1, actions=[])
    adapter.apply_feedback(0.9, actions=[])
    stats = adapter.feedback_score_stats()
    assert stats["count"] == 2 and stats["min"] == 0.1 and stats["max"] == 0.9
    assert len(adapter.recent_feedback(1)) == 1
    assert adapter.has_feedback() is True
    assert adapter.feedback_percentile(50) == pytest.approx(0.9)
    assert adapter.passing_feedback_fraction(0.6) == pytest.approx(0.5)

    validator = LogicValidator(use_cache=False)
    ontology = {
        "entities": [{"id": "e1", "type": "Person"}, {"id": "e2", "type": "Org"}],
        "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e9"}],
    }
    assert validator.all_entity_ids(ontology) == ["e1", "e2"]
    assert validator.all_relationship_ids(ontology) == ["r1"]
    assert validator.entity_type_set(ontology) == {"Person", "Org"}
    assert validator.dangling_references(ontology) == ["e9"]
