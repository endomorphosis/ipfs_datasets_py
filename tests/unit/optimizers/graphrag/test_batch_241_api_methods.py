"""Batch 241 tests for new API helpers in mediator/pipeline."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerationContext,
    OntologyGenerator,
    DataType,
    ExtractionStrategy,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic


def _score_stub(**kwargs):
    base = {
        "completeness": 0.4,
        "consistency": 0.5,
        "clarity": 0.4,
        "overall": 0.5,
        "recommendations": ["Add properties to improve clarity"],
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _basic_context():
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="test",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


def test_batch_suggest_strategies_returns_ordered_results():
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    critic = OntologyCritic(use_llm=False)
    mediator = OntologyMediator(generator=generator, critic=critic, max_rounds=1)
    ctx = _basic_context()

    ontologies = [
        {"entities": [], "relationships": []},
        {"entities": [{"id": "e1", "type": "Thing", "text": "A"}], "relationships": []},
    ]
    scores = [_score_stub(), _score_stub(clarity=0.3)]

    result = mediator.batch_suggest_strategies(ontologies, scores, ctx, max_workers=1)

    assert result["success_count"] == 2
    assert result["error_count"] == 0
    assert len(result["strategies"]) == 2
    assert result["strategies"][0] is not None
    assert result["strategies"][1] is not None


def test_batch_suggest_strategies_mismatch_raises():
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    critic = OntologyCritic(use_llm=False)
    mediator = OntologyMediator(generator=generator, critic=critic, max_rounds=1)
    ctx = _basic_context()

    with pytest.raises(ValueError):
        mediator.batch_suggest_strategies([{ "entities": [] }], [], ctx)


def test_compare_strategies_ranks_best():
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    critic = OntologyCritic(use_llm=False)
    mediator = OntologyMediator(generator=generator, critic=critic, max_rounds=1)

    strategies = [
        {"action": "normalize_names", "priority": "low", "estimated_impact": 0.05},
        {"action": "add_missing_properties", "priority": "high", "estimated_impact": 0.12},
    ]

    result = mediator.compare_strategies(strategies)

    assert result["best_strategy"]["action"] == "add_missing_properties"
    assert len(result["ranked_strategies"]) == 2
    assert result["summary"]["count"] == 2


def test_export_refinement_history_empty_returns_list():
    pipeline = OntologyPipeline(domain="test", use_llm=False, max_rounds=1)

    pipeline.run("Simple input", refine=False)
    history = pipeline.export_refinement_history()

    assert isinstance(history, list)
    assert history == []

    payload = pipeline.export_refinement_history(format="json")
    assert payload == "[]"
