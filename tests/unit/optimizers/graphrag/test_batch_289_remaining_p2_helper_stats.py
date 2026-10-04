"""Coverage for remaining GraphRAG P2 statistical helper methods."""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
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


def test_optimizer_critic_and_learning_adapter_stat_helpers() -> None:
    optimizer = OntologyOptimizer(enable_tracing=False)
    optimizer._history = [  # type: ignore[attr-defined]
        OptimizationReport(average_score=0.2, trend="a"),
        OptimizationReport(average_score=0.2, trend="b"),
        OptimizationReport(average_score=0.2, trend="c"),
        OptimizationReport(average_score=0.6, trend="d"),
    ]
    assert optimizer.history_skewness() > 0.0
    assert optimizer.score_plateau_length(tolerance=1e-9) == 3

    critic = OntologyCritic(use_llm=False)
    before = CriticScore(0.2, 0.7, 0.5, 0.3, 0.4, 0.6)
    after = CriticScore(0.3, 0.6, 0.7, 0.3, 0.5, 0.9)
    assert critic.dimension_std(after) > 0.0
    mask = critic.dimension_improvement_mask(before, after)
    assert mask["completeness"] is True
    assert mask["consistency"] is False
    assert mask["clarity"] is True

    adapter = OntologyLearningAdapter()
    adapter.apply_feedback(0.2, actions=[])
    adapter.apply_feedback(0.4, actions=[])
    adapter.apply_feedback(0.9, actions=[])
    assert adapter.feedback_decay_sum(decay=0.5) == pytest.approx(0.2 * 0.25 + 0.4 * 0.5 + 0.9)
    assert adapter.feedback_count_below(0.5) == 2


def test_generator_pipeline_validator_and_mediator_stat_helpers() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9),
            Entity(id="e2", type="Person", text="Bob", confidence=0.3),
            Entity(id="e3", type="Org", text="Acme", confidence=0.6),
        ],
        relationships=[],
        confidence=0.6,
    )
    assert gen.max_confidence_entity(result).id == "e1"
    assert gen.min_confidence_entity(result).id == "e2"
    assert gen.entity_confidence_std(result) == pytest.approx(
        (((0.9 - 0.6) ** 2 + (0.3 - 0.6) ** 2 + (0.6 - 0.6) ** 2) / 3) ** 0.5
    )

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline._run_history = [  # type: ignore[attr-defined]
        SimpleNamespace(score=SimpleNamespace(overall=0.5)),
        SimpleNamespace(score=SimpleNamespace(overall=0.9)),
        SimpleNamespace(score=SimpleNamespace(overall=0.2)),
        SimpleNamespace(score=SimpleNamespace(overall=0.8)),
    ]
    assert pipeline.best_k_scores(2) == [0.9, 0.8]
    assert pipeline.worst_k_scores(2) == [0.2, 0.5]

    validator = LogicValidator(use_cache=False)
    ontology = {
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "knows"},
            {"source_id": "e1", "target_id": "e2", "type": "knows"},
            {"source_id": "e2", "target_id": "e3", "type": "works_for"},
        ]
    }
    assert validator.relationship_diversity(ontology) == pytest.approx(
        -(2 / 3) * math.log2(2 / 3) - (1 / 3) * math.log2(1 / 3)
    )
    assert validator.entity_pair_count(ontology) == 2

    mediator = OntologyMediator(generator=Mock(), critic=Mock())
    mediator._feedback_history = [  # type: ignore[attr-defined]
        SimpleNamespace(score=0.1),
        SimpleNamespace(score=0.2),
        SimpleNamespace(score=0.3),
    ]
    assert mediator.feedback_age(0) == 2
    assert mediator.feedback_age(-1) == 0
    assert mediator.feedback_age(7) == -1
    assert mediator.clear_feedback() == 3
    assert mediator.feedback_history_size() == 0
