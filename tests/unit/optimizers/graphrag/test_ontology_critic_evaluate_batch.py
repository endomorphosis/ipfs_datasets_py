"""Tests for OntologyCritic.evaluate_batch() (batch 32).

Covers empty list, single ontology, multiple ontologies,
aggregated statistics, and public import.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    ExtractionStrategy,
    OntologyGenerationContext,
)


@pytest.fixture
def critic():
    return OntologyCritic()


@pytest.fixture
def ctx():
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


def _simple_ontology(n_entities: int = 3) -> dict:
    entities = [
        {"id": f"e{i}", "type": "Person", "text": f"Person{i}", "confidence": 0.8}
        for i in range(n_entities)
    ]
    relationships = [
        {
            "id": f"r{i}",
            "source": f"e{i}",
            "target": f"e{(i + 1) % n_entities}",
            "type": "knows",
            "confidence": 0.7,
        }
        for i in range(n_entities)
    ] if n_entities > 1 else []
    return {"entities": entities, "relationships": relationships}


class TestEvaluateBatchEmpty:
    def test_empty_list_returns_zero_count(self, critic, ctx):
        result = critic.evaluate_batch([], ctx)
        assert result["count"] == 0

    def test_empty_list_scores_are_empty(self, critic, ctx):
        result = critic.evaluate_batch([], ctx)
        assert result["scores"] == []

    def test_empty_list_aggregates_are_zero(self, critic, ctx):
        result = critic.evaluate_batch([], ctx)
        assert result["mean_overall"] == 0.0
        assert result["min_overall"] == 0.0
        assert result["max_overall"] == 0.0


class TestEvaluateBatchSingle:
    def test_single_ontology_count_is_one(self, critic, ctx):
        result = critic.evaluate_batch([_simple_ontology()], ctx)
        assert result["count"] == 1

    def test_single_ontology_scores_list_length(self, critic, ctx):
        result = critic.evaluate_batch([_simple_ontology()], ctx)
        assert len(result["scores"]) == 1

    def test_single_ontology_mean_equals_individual(self, critic, ctx):
        ontology = _simple_ontology()
        result = critic.evaluate_batch([ontology], ctx)
        individual = critic.evaluate_ontology(ontology, ctx)
        assert abs(result["mean_overall"] - individual.overall) < 1e-9

    def test_single_min_equals_max(self, critic, ctx):
        result = critic.evaluate_batch([_simple_ontology()], ctx)
        assert result["min_overall"] == result["max_overall"]


class TestEvaluateBatchMultiple:
    def test_multiple_count_correct(self, critic, ctx):
        ontologies = [_simple_ontology(i + 1) for i in range(4)]
        result = critic.evaluate_batch(ontologies, ctx)
        assert result["count"] == 4

    def test_multiple_scores_list_length(self, critic, ctx):
        ontologies = [_simple_ontology(i + 1) for i in range(3)]
        result = critic.evaluate_batch(ontologies, ctx)
        assert len(result["scores"]) == 3

    def test_mean_within_min_max(self, critic, ctx):
        ontologies = [_simple_ontology(i + 1) for i in range(5)]
        result = critic.evaluate_batch(ontologies, ctx)
        assert result["min_overall"] <= result["mean_overall"] <= result["max_overall"]

    def test_min_is_global_minimum(self, critic, ctx):
        ontologies = [_simple_ontology(i + 1) for i in range(5)]
        result = critic.evaluate_batch(ontologies, ctx)
        computed_min = min(s.overall for s in result["scores"])
        assert abs(result["min_overall"] - computed_min) < 1e-9

    def test_max_is_global_maximum(self, critic, ctx):
        ontologies = [_simple_ontology(i + 1) for i in range(5)]
        result = critic.evaluate_batch(ontologies, ctx)
        computed_max = max(s.overall for s in result["scores"])
        assert abs(result["max_overall"] - computed_max) < 1e-9

    def test_mean_computed_correctly(self, critic, ctx):
        ontologies = [_simple_ontology(i + 1) for i in range(4)]
        result = critic.evaluate_batch(ontologies, ctx)
        overalls = [s.overall for s in result["scores"]]
        expected_mean = sum(overalls) / len(overalls)
        assert abs(result["mean_overall"] - expected_mean) < 1e-9

    def test_result_has_expected_keys(self, critic, ctx):
        result = critic.evaluate_batch([_simple_ontology()], ctx)
        for key in ("scores", "mean_overall", "min_overall", "max_overall", "count"):
            assert key in result
