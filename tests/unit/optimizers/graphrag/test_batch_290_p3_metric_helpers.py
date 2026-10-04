"""Coverage for remaining P3 GraphRAG metric helper methods."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    EntityExtractionResult,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_optimizer_gini_and_critic_dimension_correlation() -> None:
    optimizer = OntologyOptimizer(enable_tracing=False)
    optimizer._history = [  # type: ignore[attr-defined]
        OptimizationReport(average_score=0.0, trend="flat"),
        OptimizationReport(average_score=0.0, trend="flat"),
        OptimizationReport(average_score=1.0, trend="up"),
    ]
    assert optimizer.score_gini_coefficient() == pytest.approx(2.0 / 3.0)

    critic = OntologyCritic(use_llm=False)
    a = [
        CriticScore(0.1, 0.0, 0.0, 0.0, 0.0, 0.0),
        CriticScore(0.3, 0.0, 0.0, 0.0, 0.0, 0.0),
        CriticScore(0.9, 0.0, 0.0, 0.0, 0.0, 0.0),
    ]
    b = [
        CriticScore(0.9, 0.0, 0.0, 0.0, 0.0, 0.0),
        CriticScore(0.7, 0.0, 0.0, 0.0, 0.0, 0.0),
        CriticScore(0.1, 0.0, 0.0, 0.0, 0.0, 0.0),
    ]
    assert critic.dimension_correlation(a, b, dimension="completeness") == pytest.approx(-1.0)


def test_pipeline_histogram_and_validator_graph_diameter() -> None:
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline._run_history = [  # type: ignore[attr-defined]
        SimpleNamespace(score=SimpleNamespace(overall=0.10)),
        SimpleNamespace(score=SimpleNamespace(overall=0.20)),
        SimpleNamespace(score=SimpleNamespace(overall=0.74)),
        SimpleNamespace(score=SimpleNamespace(overall=1.00)),
    ]
    hist = pipeline.score_histogram(bins=4)
    assert hist == {
        "0.00-0.25": 2,
        "0.25-0.50": 0,
        "0.50-0.75": 1,
        "0.75-1.00": 1,
    }

    validator = LogicValidator(use_cache=False)
    ontology = {
        "entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}, {"id": "e4"}],
        "relationships": [
            {"source_id": "e1", "target_id": "e2"},
            {"source_id": "e2", "target_id": "e3"},
            {"source_id": "e1", "target_id": "e4"},
        ],
    }
    assert validator.graph_diameter(ontology) == 2


def test_generator_relationship_confidence_avg_alias() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = EntityExtractionResult(
        entities=[],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e2", type="x", confidence=0.2),
            Relationship(id="r2", source_id="e2", target_id="e3", type="y", confidence=0.8),
        ],
        confidence=0.0,
    )
    assert gen.relationship_confidence_avg(result) == pytest.approx(0.5)
