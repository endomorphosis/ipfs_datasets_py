"""
Unit tests for Batch 205 implementations.

Tests cover:
- OntologyOptimizer.score_skewness()
- OntologyCritic.dimension_skewness(score)
- OntologyGenerator.entity_confidence_kurtosis(result)
- OntologyGenerator.entity_text_length_std(result)
- OntologyLearningAdapter.feedback_rolling_mean(window)
- OntologyPipeline.run_score_skewness()
- OntologyPipeline.worst_score_decline()
- LogicValidator.avg_in_degree(ontology)  [alias for average_in_degree]
- LogicValidator.avg_out_degree(ontology)  [alias for average_out_degree]
"""
from __future__ import annotations

import math
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

def _make_result(
    confidences: list[float] | None = None,
    texts: list[str] | None = None,
) -> EntityExtractionResult:
    if confidences is None:
        confidences = [0.9, 0.7, 0.5]
    if texts is None:
        texts = [f"Ent{i}" for i in range(len(confidences))]
    entities = [
        Entity(id=f"e{i}", text=t, type="Person", confidence=c)
        for i, (c, t) in enumerate(zip(confidences, texts))
    ]
    return EntityExtractionResult(entities=entities, relationships=[], confidence=0.8)


def _report(score: float = 0.5) -> OptimizationReport:
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
        completeness=0.8,
        consistency=0.7,
        clarity=0.6,
        granularity=0.5,
        relationship_coherence=0.4,
        domain_alignment=0.3,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_pipeline_with(scores: list[float]) -> OntologyPipeline:
    pipeline = OntologyPipeline()
    for s in scores:
        run = MagicMock()
        run.score = MagicMock()
        run.score.overall = s
        pipeline._run_history.append(run)
    return pipeline


class _FakeRel:
    def __init__(self, src: str, tgt: str):
        self.source_id = src
        self.target_id = tgt


class _FakeOntology:
    def __init__(self, rels: list):
        self.relationships = rels


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_skewness
# ---------------------------------------------------------------------------

class TestScoreSkewness:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_skewness() == 0.0

    def test_fewer_than_three_returns_zero(self):
        opt = _optimizer_with([0.5, 0.6])
        assert opt.score_skewness() == 0.0

    def test_uniform_scores_returns_zero(self):
        opt = _optimizer_with([0.5, 0.5, 0.5])
        assert opt.score_skewness() == pytest.approx(0.0)

    def test_symmetric_distribution_near_zero(self):
        # [0.2, 0.5, 0.8] is symmetric
        opt = _optimizer_with([0.2, 0.5, 0.8])
        assert abs(opt.score_skewness()) < 1e-9

    def test_right_skewed_positive(self):
        # Many low values, one high → right skew (positive)
        opt = _optimizer_with([0.1, 0.1, 0.1, 0.9])
        assert opt.score_skewness() > 0.0

    def test_left_skewed_negative(self):
        # Many high values, one low → left skew (negative)
        opt = _optimizer_with([0.9, 0.9, 0.9, 0.1])
        assert opt.score_skewness() < 0.0

    def test_returns_float(self):
        opt = _optimizer_with([0.3, 0.5, 0.7])
        assert isinstance(opt.score_skewness(), float)

    def test_single_entry_returns_zero(self):
        opt = _optimizer_with([0.5])
        assert opt.score_skewness() == 0.0


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_skewness
# ---------------------------------------------------------------------------

class TestDimensionSkewness:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_uniform_dims_returns_zero(self):
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert self.critic.dimension_skewness(score) == pytest.approx(0.0)

    def test_symmetric_dims_near_zero(self):
        # [0.1, 0.3, 0.5, 0.5, 0.7, 0.9] is symmetric
        score = _make_critic_score(
            completeness=0.9, consistency=0.7, clarity=0.5,
            granularity=0.5, relationship_coherence=0.3, domain_alignment=0.1,
        )
        assert abs(self.critic.dimension_skewness(score)) < 1e-6

    def test_returns_float(self):
        score = _make_critic_score()
        assert isinstance(self.critic.dimension_skewness(score), float)

    def test_right_skew_positive(self):
        # Many low, one high
        score = _make_critic_score(
            completeness=0.9, consistency=0.1, clarity=0.1,
            granularity=0.1, relationship_coherence=0.1, domain_alignment=0.1,
        )
        assert self.critic.dimension_skewness(score) > 0.0

    def test_left_skew_negative(self):
        # Many high, one low
        score = _make_critic_score(
            completeness=0.1, consistency=0.9, clarity=0.9,
            granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9,
        )
        assert self.critic.dimension_skewness(score) < 0.0


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_kurtosis
# ---------------------------------------------------------------------------

class TestEntityConfidenceKurtosis:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result_returns_zero(self):
        result = _make_result(confidences=[])
        assert self.gen.entity_confidence_kurtosis(result) == 0.0

    def test_fewer_than_four_returns_zero(self):
        result = _make_result(confidences=[0.5, 0.6, 0.7])
        assert self.gen.entity_confidence_kurtosis(result) == 0.0

    def test_identical_confidences_returns_zero(self):
        # When all confidences are identical, std=0 → returns 0.0
        result = _make_result(confidences=[0.5, 0.5, 0.5, 0.5])
        assert self.gen.entity_confidence_kurtosis(result) == 0.0  # std=0 → 0

    def test_known_value_normal_like(self):
        # For [0.1, 0.3, 0.5, 0.7, 0.9]:
        # mean=0.5, variance = ((0.4^2+0.2^2+0^2+0.2^2+0.4^2)/5) = (0.16+0.04+0+0.04+0.16)/5=0.08
        # std^4=0.08^2=0.0064; 4th moments: 0.4^4+0.2^4+0+0.2^4+0.4^4 = 0.0256*2+0.0016*2 = 0.0544
        # kurt = (0.0544/5)/0.0064 - 3 = 0.01088/0.0064 - 3 = 1.7 - 3 = -1.3
        result = _make_result(confidences=[0.1, 0.3, 0.5, 0.7, 0.9])
        k = self.gen.entity_confidence_kurtosis(result)
        assert k == pytest.approx(-1.3, abs=1e-9)

    def test_returns_float(self):
        result = _make_result(confidences=[0.3, 0.5, 0.7, 0.9])
        assert isinstance(self.gen.entity_confidence_kurtosis(result), float)

    def test_can_be_negative(self):
        # Uniform spread → negative excess kurtosis (platykurtic)
        result = _make_result(confidences=[0.0, 0.33, 0.67, 1.0])
        assert self.gen.entity_confidence_kurtosis(result) < 0.0


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_text_length_std
# ---------------------------------------------------------------------------

class TestEntityTextLengthStd:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_returns_zero(self):
        result = _make_result(confidences=[])
        assert self.gen.entity_text_length_std(result) == 0.0

    def test_single_entity_returns_zero(self):
        result = _make_result(confidences=[0.9], texts=["Alice"])
        assert self.gen.entity_text_length_std(result) == 0.0

    def test_uniform_length_returns_zero(self):
        result = _make_result(confidences=[0.9, 0.8, 0.7], texts=["abc", "def", "ghi"])
        assert self.gen.entity_text_length_std(result) == pytest.approx(0.0)

    def test_known_values(self):
        # lengths = [1, 3] → mean=2, variance = (1+1)/2 = 1, std=1
        result = _make_result(confidences=[0.9, 0.8], texts=["a", "abc"])
        assert self.gen.entity_text_length_std(result) == pytest.approx(1.0)

    def test_non_negative(self):
        result = _make_result(confidences=[0.9, 0.8, 0.7], texts=["Alice", "Bob", "CharlieOrg"])
        assert self.gen.entity_text_length_std(result) >= 0.0

    def test_returns_float(self):
        result = _make_result(confidences=[0.9, 0.8], texts=["A", "BB"])
        assert isinstance(self.gen.entity_text_length_std(result), float)

    def test_longer_texts_more_spread(self):
        low_spread = _make_result(confidences=[0.9, 0.8, 0.7], texts=["abc", "abcd", "abcde"])
        high_spread = _make_result(confidences=[0.9, 0.8, 0.7], texts=["a", "aaaa", "aaaaaaaaaa"])
        assert self.gen.entity_text_length_std(high_spread) > self.gen.entity_text_length_std(low_spread)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_rolling_mean
# ---------------------------------------------------------------------------

class TestFeedbackRollingMean:
    def test_empty_feedback_returns_empty(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_rolling_mean() == []

    def test_fewer_than_window_returns_empty(self):
        adapter = _adapter_with([0.5, 0.6])
        assert adapter.feedback_rolling_mean(window=3) == []

    def test_window_one_returns_each_score(self):
        adapter = _adapter_with([0.5, 0.6, 0.7])
        result = adapter.feedback_rolling_mean(window=1)
        assert result == pytest.approx([0.5, 0.6, 0.7])

    def test_window_equals_length(self):
        adapter = _adapter_with([0.4, 0.6, 0.8])
        result = adapter.feedback_rolling_mean(window=3)
        assert len(result) == 1
        assert result[0] == pytest.approx(0.6)

    def test_window_two(self):
        adapter = _adapter_with([0.4, 0.6, 0.8, 1.0])
        result = adapter.feedback_rolling_mean(window=2)
        assert len(result) == 3
        assert result[0] == pytest.approx(0.5)
        assert result[1] == pytest.approx(0.7)
        assert result[2] == pytest.approx(0.9)

    def test_uniform_scores(self):
        adapter = _adapter_with([0.5, 0.5, 0.5])
        result = adapter.feedback_rolling_mean(window=2)
        assert all(v == pytest.approx(0.5) for v in result)

    def test_returns_list_of_floats(self):
        adapter = _adapter_with([0.3, 0.5, 0.7])
        result = adapter.feedback_rolling_mean(window=2)
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_small_window_clamped_to_one(self):
        adapter = _adapter_with([0.4, 0.6, 0.8])
        # window=0 should be clamped to 1
        result = adapter.feedback_rolling_mean(window=0)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_skewness
# ---------------------------------------------------------------------------

class TestRunScoreSkewness:
    def test_empty_returns_zero(self):
        pipeline = OntologyPipeline()
        assert pipeline.run_score_skewness() == 0.0

    def test_fewer_than_three_returns_zero(self):
        pipeline = _make_pipeline_with([0.5, 0.6])
        assert pipeline.run_score_skewness() == 0.0

    def test_uniform_scores_returns_zero(self):
        pipeline = _make_pipeline_with([0.5, 0.5, 0.5])
        assert pipeline.run_score_skewness() == pytest.approx(0.0)

    def test_right_skewed_positive(self):
        pipeline = _make_pipeline_with([0.1, 0.1, 0.1, 0.9])
        assert pipeline.run_score_skewness() > 0.0

    def test_left_skewed_negative(self):
        pipeline = _make_pipeline_with([0.9, 0.9, 0.9, 0.1])
        assert pipeline.run_score_skewness() < 0.0

    def test_returns_float(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.7])
        assert isinstance(pipeline.run_score_skewness(), float)

    def test_symmetric_distribution_near_zero(self):
        pipeline = _make_pipeline_with([0.2, 0.5, 0.8])
        assert abs(pipeline.run_score_skewness()) < 1e-9


# ---------------------------------------------------------------------------
# OntologyPipeline.worst_score_decline
# ---------------------------------------------------------------------------

class TestWorstScoreDecline:
    def test_empty_returns_zero(self):
        pipeline = OntologyPipeline()
        assert pipeline.worst_score_decline() == 0.0

    def test_single_run_returns_zero(self):
        pipeline = _make_pipeline_with([0.7])
        assert pipeline.worst_score_decline() == 0.0

    def test_monotonically_improving(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.8])
        assert pipeline.worst_score_decline() == 0.0

    def test_monotonically_declining(self):
        # Declines: 0.9-0.7=0.2, 0.7-0.5=0.2, 0.5-0.3=0.2 → max=0.2
        pipeline = _make_pipeline_with([0.9, 0.7, 0.5, 0.3])
        assert pipeline.worst_score_decline() == pytest.approx(0.2, abs=1e-9)

    def test_mixed_find_max_decline(self):
        # [0.7, 0.5, 0.9, 0.2] → declines: 0.2, 0, 0.7 → max=0.7
        pipeline = _make_pipeline_with([0.7, 0.5, 0.9, 0.2])
        assert pipeline.worst_score_decline() == pytest.approx(0.7, abs=1e-9)

    def test_non_negative(self):
        pipeline = _make_pipeline_with([0.5, 0.9, 0.3, 0.8])
        assert pipeline.worst_score_decline() >= 0.0

    def test_returns_float(self):
        pipeline = _make_pipeline_with([0.5, 0.4])
        assert isinstance(pipeline.worst_score_decline(), float)


# ---------------------------------------------------------------------------
# LogicValidator.avg_in_degree / avg_out_degree  (aliases)
# ---------------------------------------------------------------------------

class TestAvgInOutDegree:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_avg_in_empty_ontology_returns_zero(self):
        assert self.validator.avg_in_degree(_FakeOntology([])) == pytest.approx(0.0)

    def test_avg_out_empty_ontology_returns_zero(self):
        assert self.validator.avg_out_degree(_FakeOntology([])) == pytest.approx(0.0)

    def test_avg_in_single_edge(self):
        # 2 nodes, 1 edge a→b: b has in-degree 1, a has 0 → avg = 1/2 = 0.5
        rels = [_FakeRel("a", "b")]
        assert self.validator.avg_in_degree(_FakeOntology(rels)) == pytest.approx(0.5)

    def test_avg_out_single_edge(self):
        # 2 nodes, 1 edge a→b: a has out-degree 1, b has 0 → avg = 1/2 = 0.5
        rels = [_FakeRel("a", "b")]
        assert self.validator.avg_out_degree(_FakeOntology(rels)) == pytest.approx(0.5)

    def test_avg_in_equals_average_in_degree(self):
        rels = [_FakeRel("a", "c"), _FakeRel("b", "c")]
        ont = _FakeOntology(rels)
        assert self.validator.avg_in_degree(ont) == pytest.approx(
            self.validator.average_in_degree(ont)
        )

    def test_avg_out_equals_average_out_degree(self):
        rels = [_FakeRel("a", "c"), _FakeRel("b", "c")]
        ont = _FakeOntology(rels)
        assert self.validator.avg_out_degree(ont) == pytest.approx(
            self.validator.average_out_degree(ont)
        )

    def test_avg_in_multiple_edges(self):
        # a→c, b→c: c in-degree=2, a in-degree=0, b in-degree=0 → avg=2/3
        rels = [_FakeRel("a", "c"), _FakeRel("b", "c")]
        assert self.validator.avg_in_degree(_FakeOntology(rels)) == pytest.approx(2 / 3, abs=1e-9)

    def test_avg_out_multiple_edges(self):
        # a→c, b→c: a out-degree=1, b out-degree=1, c out-degree=0 → avg=2/3
        rels = [_FakeRel("a", "c"), _FakeRel("b", "c")]
        assert self.validator.avg_out_degree(_FakeOntology(rels)) == pytest.approx(2 / 3, abs=1e-9)

    def test_returns_float(self):
        rels = [_FakeRel("x", "y")]
        assert isinstance(self.validator.avg_in_degree(_FakeOntology(rels)), float)
        assert isinstance(self.validator.avg_out_degree(_FakeOntology(rels)), float)

    def test_sum_in_equals_sum_out(self):
        # Total in-degrees always equals total out-degrees
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("a", "c")]
        ont = _FakeOntology(rels)
        # Same number of rels → same sum; nodes same too → same average
        assert self.validator.avg_in_degree(ont) == pytest.approx(
            self.validator.avg_out_degree(ont)
        )
