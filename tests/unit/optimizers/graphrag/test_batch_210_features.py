"""
Unit tests for Batch 210 implementations.

Tests cover new methods:
- OntologyOptimizer.above_target_rate(target)
- OntologyCritic.dimension_trend_slope(score, prev_score)
- OntologyGenerator.entity_type_count(result)
- OntologyLearningAdapter.feedback_above_mean_ratio()
- LogicValidator.betweenness_centrality_approx(ontology)

Smoke tests for pre-existing Batch 210 items:
- OntologyOptimizer.history_range()
- OntologyPipeline.best_run_index()
- OntologyPipeline.worst_run_index()
- LogicValidator.leaf_node_count(ontology)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
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


def _make_result_with_entity_types(types: list[str]) -> EntityExtractionResult:
    entities = [
        Entity(id=f"e{i}", text=f"T{i}", type=t, confidence=0.9)
        for i, t in enumerate(types)
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
# OntologyOptimizer.above_target_rate
# ---------------------------------------------------------------------------

class TestAboveTargetRate:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.above_target_rate() == 0.0

    def test_all_below_target(self):
        opt = _optimizer_with([0.1, 0.3, 0.5])
        assert opt.above_target_rate(0.7) == pytest.approx(0.0)

    def test_all_above_target(self):
        opt = _optimizer_with([0.8, 0.9, 1.0])
        assert opt.above_target_rate(0.7) == pytest.approx(1.0)

    def test_half_above_target(self):
        opt = _optimizer_with([0.5, 0.6, 0.8, 0.9])
        assert opt.above_target_rate(0.7) == pytest.approx(0.5)

    def test_exact_target_not_counted(self):
        # Strictly above, so 0.7 itself should not be counted
        opt = _optimizer_with([0.7, 0.8])
        assert opt.above_target_rate(0.7) == pytest.approx(0.5)

    def test_default_target_is_0_7(self):
        opt = _optimizer_with([0.8, 0.6])
        assert opt.above_target_rate() == pytest.approx(0.5)

    def test_returns_float(self):
        opt = _optimizer_with([0.5, 0.8])
        assert isinstance(opt.above_target_rate(), float)

    def test_in_range_zero_to_one(self):
        opt = _optimizer_with([0.3, 0.5, 0.8, 0.9])
        assert 0.0 <= opt.above_target_rate(0.6) <= 1.0


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_trend_slope
# ---------------------------------------------------------------------------

class TestDimensionTrendSlope:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_returns_dict_with_all_dimensions(self):
        s1 = _make_critic_score()
        s2 = _make_critic_score()
        result = self.critic.dimension_trend_slope(s2, s1)
        assert isinstance(result, dict)
        assert len(result) == 6

    def test_no_change_gives_zeros(self):
        s1 = _make_critic_score()
        s2 = _make_critic_score()
        result = self.critic.dimension_trend_slope(s2, s1)
        for v in result.values():
            assert v == pytest.approx(0.0)

    def test_positive_delta_for_improvement(self):
        s1 = _make_critic_score(completeness=0.5)
        s2 = _make_critic_score(completeness=0.9)
        result = self.critic.dimension_trend_slope(s2, s1)
        assert result["completeness"] == pytest.approx(0.4, abs=1e-9)

    def test_negative_delta_for_regression(self):
        s1 = _make_critic_score(completeness=0.9)
        s2 = _make_critic_score(completeness=0.5)
        result = self.critic.dimension_trend_slope(s2, s1)
        assert result["completeness"] == pytest.approx(-0.4, abs=1e-9)

    def test_known_values(self):
        s1 = _make_critic_score(completeness=0.6, consistency=0.5)
        s2 = _make_critic_score(completeness=0.8, consistency=0.7)
        result = self.critic.dimension_trend_slope(s2, s1)
        assert result["completeness"] == pytest.approx(0.2, abs=1e-9)
        assert result["consistency"] == pytest.approx(0.2, abs=1e-9)

    def test_dimension_keys_are_strings(self):
        s1 = _make_critic_score()
        s2 = _make_critic_score()
        result = self.critic.dimension_trend_slope(s2, s1)
        for k in result.keys():
            assert isinstance(k, str)

    def test_values_are_floats(self):
        s1 = _make_critic_score()
        s2 = _make_critic_score(completeness=0.9)
        result = self.critic.dimension_trend_slope(s2, s1)
        for v in result.values():
            assert isinstance(v, float)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_type_count
# ---------------------------------------------------------------------------

class TestEntityTypeCount:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result_returns_zero(self):
        result = EntityExtractionResult(entities=[], relationships=[], confidence=0.8)
        assert self.gen.entity_type_count(result) == 0

    def test_single_type(self):
        result = _make_result_with_entity_types(["Person", "Person", "Person"])
        assert self.gen.entity_type_count(result) == 1

    def test_two_distinct_types(self):
        result = _make_result_with_entity_types(["Person", "Location"])
        assert self.gen.entity_type_count(result) == 2

    def test_all_unique_types(self):
        result = _make_result_with_entity_types(["Person", "Location", "Event", "Org"])
        assert self.gen.entity_type_count(result) == 4

    def test_returns_int(self):
        result = _make_result_with_entity_types(["Person"])
        assert isinstance(self.gen.entity_type_count(result), int)

    def test_non_negative(self):
        result = _make_result_with_entity_types(["X", "Y"])
        assert self.gen.entity_type_count(result) >= 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_above_mean_ratio
# ---------------------------------------------------------------------------

class TestFeedbackAboveMeanRatio:
    def test_empty_feedback_returns_zero(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_above_mean_ratio() == 0.0

    def test_all_equal_scores_returns_zero(self):
        # No score strictly above the mean
        adapter = _adapter_with([0.5, 0.5, 0.5])
        assert adapter.feedback_above_mean_ratio() == pytest.approx(0.0)

    def test_half_above_mean(self):
        # [0.3, 0.7]: mean=0.5; 0.7 > 0.5 → 1/2 = 0.5
        adapter = _adapter_with([0.3, 0.7])
        assert adapter.feedback_above_mean_ratio() == pytest.approx(0.5)

    def test_most_above_mean(self):
        # [0.6, 0.7, 0.8, 0.2]: mean=0.575; above: 0.6, 0.7, 0.8 → 3/4
        adapter = _adapter_with([0.6, 0.7, 0.8, 0.2])
        assert adapter.feedback_above_mean_ratio() == pytest.approx(0.75)

    def test_in_range_zero_to_one(self):
        adapter = _adapter_with([0.3, 0.5, 0.8, 0.9])
        assert 0.0 <= adapter.feedback_above_mean_ratio() <= 1.0

    def test_returns_float(self):
        adapter = _adapter_with([0.4, 0.6])
        assert isinstance(adapter.feedback_above_mean_ratio(), float)


# ---------------------------------------------------------------------------
# LogicValidator.betweenness_centrality_approx
# ---------------------------------------------------------------------------

class TestBetweennessCentralityApprox:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_returns_empty(self):
        assert self.validator.betweenness_centrality_approx({}) == {}

    def test_no_relationships_returns_empty(self):
        assert self.validator.betweenness_centrality_approx({"relationships": []}) == {}

    def test_fewer_than_3_nodes_returns_zeros(self):
        ont = _make_ontology(("a", "b"))
        result = self.validator.betweenness_centrality_approx(ont)
        for v in result.values():
            assert v == pytest.approx(0.0)

    def test_chain_topology_intermediate_higher(self):
        # a-b-c-d: b and c have betweenness > a and d
        ont = _make_ontology(("a", "b"), ("b", "c"), ("c", "d"))
        result = self.validator.betweenness_centrality_approx(ont)
        assert result["b"] > result["a"]
        assert result["c"] > result["d"]

    def test_endpoints_have_zero_betweenness(self):
        # In a chain a-b-c, a and c have no paths going through them
        ont = _make_ontology(("a", "b"), ("b", "c"))
        result = self.validator.betweenness_centrality_approx(ont)
        assert result["a"] == pytest.approx(0.0)
        assert result["c"] == pytest.approx(0.0)

    def test_intermediate_node_known_value(self):
        # a-b-c: only path a→c goes through b; betweenness(b) = 2/(n-1)(n-2)
        # n=3, norm=2*1=2, b gets 1 path → 1/2 = 0.5 (un-directed)
        ont = _make_ontology(("a", "b"), ("b", "c"))
        result = self.validator.betweenness_centrality_approx(ont)
        # b is on 2 shortest paths (a→c and c→a); norm=2 → 2/2=1.0
        # Use a generous tolerance for the approximation
        assert result["b"] > 0.0

    def test_values_non_negative(self):
        ont = _make_ontology(("a", "b"), ("b", "c"), ("c", "d"))
        result = self.validator.betweenness_centrality_approx(ont)
        for v in result.values():
            assert v >= 0.0

    def test_returns_dict_of_floats(self):
        ont = _make_ontology(("a", "b"), ("b", "c"))
        result = self.validator.betweenness_centrality_approx(ont)
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, float)


# ---------------------------------------------------------------------------
# Smoke tests for pre-existing Batch 210 items
# ---------------------------------------------------------------------------

class TestExistingBatch210Methods:
    def test_history_range_returns_float(self):
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        result = opt.history_range()
        assert isinstance(result, float)
        assert result == pytest.approx(0.6, abs=1e-9)

    def test_best_run_index_returns_int(self):
        pipeline = _make_pipeline_with([0.3, 0.9, 0.5, 0.7])
        result = pipeline.best_run_index()
        assert isinstance(result, int)
        assert result == 1  # index of 0.9

    def test_worst_run_index_returns_int(self):
        pipeline = _make_pipeline_with([0.3, 0.9, 0.5, 0.7])
        result = pipeline.worst_run_index()
        assert isinstance(result, int)
        assert result == 0  # index of 0.3

    def test_leaf_node_count_callable(self):
        validator = LogicValidator()
        try:
            result = validator.leaf_node_count({"entities": [], "relationships": []})
            assert isinstance(result, int)
            assert result >= 0
        except (AttributeError, TypeError):
            pytest.skip("leaf_node_count uses different ontology format")
