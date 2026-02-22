"""
Unit tests for Batch 207 implementations.

Tests cover:
- OntologyOptimizer.score_gini()  [alias for score_gini_coefficient]
- OntologyCritic.dimension_gini(score)
- OntologyGenerator.entity_confidence_gini(result)
- OntologyPipeline.run_score_gini()
- OntologyPipeline.first_improving_run()
- LogicValidator.degree_centrality(ontology)
- LogicValidator.max_degree_node_count(ontology)

Smoke tests for pre-existing Batch 207 items:
- OntologyOptimizer.history_percentile(p)
- OntologyLearningAdapter.feedback_gini()
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report(score: float) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


def _optimizer_with(scores: list[float]) -> OntologyOptimizer:
    opt = OntologyOptimizer()
    for s in scores:
        opt._history.append(_report(s))
    return opt


def _adapter_with(scores: list[float]) -> OntologyLearningAdapter:
    adapter = OntologyLearningAdapter(domain="test")
    for s in scores:
        adapter.apply_feedback(final_score=s, actions=[])
    return adapter


def _make_critic_score(**kwargs) -> CriticScore:
    defaults = dict(
        completeness=0.8, consistency=0.7, clarity=0.6,
        granularity=0.5, relationship_coherence=0.4, domain_alignment=0.3,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_result(confidences: list[float]) -> EntityExtractionResult:
    entities = [
        Entity(id=f"e{i}", text=f"T{i}", type="Person", confidence=c)
        for i, c in enumerate(confidences)
    ]
    return EntityExtractionResult(entities=entities, relationships=[], confidence=0.8)


def _make_pipeline_with(scores: list[float]) -> OntologyPipeline:
    pipeline = OntologyPipeline()
    for s in scores:
        run = MagicMock()
        run.score = MagicMock()
        run.score.overall = s
        pipeline._run_history.append(run)
    return pipeline


def _make_ontology(*pairs) -> dict:
    return {"relationships": [{"source": s, "target": t, "type": "r"} for s, t in pairs]}


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_gini (alias)
# ---------------------------------------------------------------------------

class TestScoreGini:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_gini() == 0.0

    def test_equal_scores_returns_zero(self):
        opt = _optimizer_with([0.5, 0.5, 0.5])
        assert opt.score_gini() == pytest.approx(0.0)

    def test_matches_score_gini_coefficient(self):
        opt = _optimizer_with([0.2, 0.5, 0.8])
        assert opt.score_gini() == pytest.approx(opt.score_gini_coefficient())

    def test_non_negative(self):
        opt = _optimizer_with([0.3, 0.6, 0.9])
        assert opt.score_gini() >= 0.0

    def test_at_most_one(self):
        opt = _optimizer_with([0.1, 0.9])
        assert opt.score_gini() <= 1.0

    def test_returns_float(self):
        opt = _optimizer_with([0.4, 0.6])
        assert isinstance(opt.score_gini(), float)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_gini
# ---------------------------------------------------------------------------

class TestDimensionGini:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_uniform_dims_returns_zero(self):
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert self.critic.dimension_gini(score) == pytest.approx(0.0)

    def test_all_zero_returns_zero(self):
        score = _make_critic_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert self.critic.dimension_gini(score) == 0.0

    def test_non_negative(self):
        score = _make_critic_score()
        assert self.critic.dimension_gini(score) >= 0.0

    def test_at_most_one(self):
        score = _make_critic_score()
        assert self.critic.dimension_gini(score) <= 1.0

    def test_more_spread_higher_gini(self):
        score_low = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.4,
        )
        score_high = _make_critic_score(
            completeness=0.9, consistency=0.1, clarity=0.1,
            granularity=0.1, relationship_coherence=0.1, domain_alignment=0.1,
        )
        assert self.critic.dimension_gini(score_high) > self.critic.dimension_gini(score_low)

    def test_returns_float(self):
        score = _make_critic_score()
        assert isinstance(self.critic.dimension_gini(score), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_gini
# ---------------------------------------------------------------------------

class TestEntityConfidenceGini:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result_returns_zero(self):
        result = _make_result([])
        assert self.gen.entity_confidence_gini(result) == 0.0

    def test_single_entity_returns_zero(self):
        result = _make_result([0.8])
        assert self.gen.entity_confidence_gini(result) == 0.0

    def test_equal_confidences_returns_zero(self):
        result = _make_result([0.5, 0.5, 0.5])
        assert self.gen.entity_confidence_gini(result) == pytest.approx(0.0)

    def test_all_zero_returns_zero(self):
        result = _make_result([0.0, 0.0, 0.0])
        assert self.gen.entity_confidence_gini(result) == 0.0

    def test_non_negative(self):
        result = _make_result([0.3, 0.6, 0.9])
        assert self.gen.entity_confidence_gini(result) >= 0.0

    def test_at_most_one(self):
        result = _make_result([0.1, 0.9])
        assert self.gen.entity_confidence_gini(result) <= 1.0

    def test_returns_float(self):
        result = _make_result([0.4, 0.6, 0.8])
        assert isinstance(self.gen.entity_confidence_gini(result), float)


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_gini
# ---------------------------------------------------------------------------

class TestRunScoreGini:
    def test_empty_returns_zero(self):
        pipeline = OntologyPipeline()
        assert pipeline.run_score_gini() == 0.0

    def test_single_run_returns_zero(self):
        pipeline = _make_pipeline_with([0.7])
        assert pipeline.run_score_gini() == 0.0

    def test_equal_scores_returns_zero(self):
        pipeline = _make_pipeline_with([0.5, 0.5, 0.5])
        assert pipeline.run_score_gini() == pytest.approx(0.0)

    def test_non_negative(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.8])
        assert pipeline.run_score_gini() >= 0.0

    def test_at_most_one(self):
        pipeline = _make_pipeline_with([0.1, 0.9])
        assert pipeline.run_score_gini() <= 1.0

    def test_returns_float(self):
        pipeline = _make_pipeline_with([0.4, 0.6])
        assert isinstance(pipeline.run_score_gini(), float)


# ---------------------------------------------------------------------------
# OntologyPipeline.first_improving_run
# ---------------------------------------------------------------------------

class TestFirstImprovingRun:
    def test_empty_returns_minus_one(self):
        pipeline = OntologyPipeline()
        assert pipeline.first_improving_run() == -1

    def test_single_run_returns_minus_one(self):
        pipeline = _make_pipeline_with([0.7])
        assert pipeline.first_improving_run() == -1

    def test_all_declining_returns_minus_one(self):
        pipeline = _make_pipeline_with([0.9, 0.7, 0.5])
        assert pipeline.first_improving_run() == -1

    def test_first_run_improves(self):
        pipeline = _make_pipeline_with([0.3, 0.7, 0.5])
        assert pipeline.first_improving_run() == 1

    def test_improvement_after_decline(self):
        pipeline = _make_pipeline_with([0.9, 0.5, 0.7])
        assert pipeline.first_improving_run() == 2

    def test_all_improving(self):
        pipeline = _make_pipeline_with([0.1, 0.3, 0.5, 0.7])
        assert pipeline.first_improving_run() == 1

    def test_equal_scores_returns_minus_one(self):
        pipeline = _make_pipeline_with([0.5, 0.5, 0.5])
        assert pipeline.first_improving_run() == -1

    def test_returns_int(self):
        pipeline = _make_pipeline_with([0.4, 0.6])
        assert isinstance(pipeline.first_improving_run(), int)


# ---------------------------------------------------------------------------
# LogicValidator.degree_centrality
# ---------------------------------------------------------------------------

class TestDegreeCentrality:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_returns_empty_dict(self):
        assert self.validator.degree_centrality({}) == {}

    def test_no_relationships_returns_empty_dict(self):
        assert self.validator.degree_centrality({"relationships": []}) == {}

    def test_single_edge_two_nodes(self):
        # a→b: a degree=1, b degree=1; n=2 → centrality = 1/(2-1) = 1.0
        ont = _make_ontology(("a", "b"))
        result = self.validator.degree_centrality(ont)
        assert result["a"] == pytest.approx(1.0)
        assert result["b"] == pytest.approx(1.0)

    def test_centrality_values_in_range(self):
        ont = _make_ontology(("a", "b"), ("a", "c"), ("b", "c"))
        result = self.validator.degree_centrality(ont)
        for v in result.values():
            assert 0.0 <= v <= 1.0

    def test_hub_has_highest_centrality(self):
        # hub→x, hub→y, hub→z: hub degree=3, x=y=z=1; n=4 → hub=3/3=1.0
        ont = _make_ontology(("hub", "x"), ("hub", "y"), ("hub", "z"))
        result = self.validator.degree_centrality(ont)
        assert result["hub"] == pytest.approx(1.0)
        assert result["x"] < result["hub"]

    def test_returns_dict(self):
        ont = _make_ontology(("x", "y"))
        assert isinstance(self.validator.degree_centrality(ont), dict)


# ---------------------------------------------------------------------------
# LogicValidator.max_degree_node_count
# ---------------------------------------------------------------------------

class TestMaxDegreeNodeCount:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_returns_zero(self):
        assert self.validator.max_degree_node_count({}) == 0

    def test_no_relationships_returns_zero(self):
        assert self.validator.max_degree_node_count({"relationships": []}) == 0

    def test_single_edge_two_max_nodes(self):
        # a→b: both have degree 1 → 2 nodes at max degree
        ont = _make_ontology(("a", "b"))
        assert self.validator.max_degree_node_count(ont) == 2

    def test_clear_single_max_node(self):
        # hub→x, hub→y, hub→z: hub degree=3, others 1 → 1 node at max
        ont = _make_ontology(("hub", "x"), ("hub", "y"), ("hub", "z"))
        assert self.validator.max_degree_node_count(ont) == 1

    def test_all_same_degree(self):
        # a→b, b→a: both degree=2 → 2 nodes at max
        ont = _make_ontology(("a", "b"), ("b", "a"))
        assert self.validator.max_degree_node_count(ont) == 2

    def test_returns_int(self):
        ont = _make_ontology(("x", "y"))
        assert isinstance(self.validator.max_degree_node_count(ont), int)

    def test_non_negative(self):
        ont = _make_ontology(("a", "b"), ("b", "c"))
        assert self.validator.max_degree_node_count(ont) >= 0


# ---------------------------------------------------------------------------
# Smoke tests for pre-existing Batch 207 items
# ---------------------------------------------------------------------------

class TestExistingBatch207Methods:
    def test_history_percentile_returns_float(self):
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        result = opt.history_percentile(50)
        assert isinstance(result, float)
        assert 0.3 <= result <= 0.9

    def test_feedback_gini_returns_float(self):
        adapter = _adapter_with([0.3, 0.5, 0.7])
        result = adapter.feedback_gini()
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
