"""
Unit tests for Batch 204 implementations.

Tests cover:
- OntologyOptimizer.score_iqr()
- OntologyOptimizer.history_rolling_std(window)
- OntologyCritic.dimension_iqr(score)
- OntologyCritic.dimension_coefficient_of_variation(score)
- OntologyGenerator.entity_confidence_geometric_mean(result)
- OntologyGenerator.entity_confidence_harmonic_mean(result)
- OntologyGenerator.relationship_confidence_iqr(result)
- OntologyLearningAdapter.feedback_iqr()
- OntologyPipeline.best_score_improvement()
- OntologyPipeline.rounds_without_improvement()
- LogicValidator.most_connected_node(ontology)
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
    rel_confidences: list[float] | None = None,
) -> EntityExtractionResult:
    if confidences is None:
        confidences = [0.9, 0.7, 0.5]
    entities = [
        Entity(id=f"e{i}", text=f"Ent{i}", type="Person", confidence=c)
        for i, c in enumerate(confidences)
    ]
    rels = []
    if rel_confidences:
        for i, c in enumerate(rel_confidences):
            rels.append(
                Relationship(
                    id=f"r{i}",
                    source_id=f"e{i}",
                    target_id=f"e{(i+1) % len(entities)}",
                    type="related_to",
                    confidence=c,
                )
            )
    return EntityExtractionResult(entities=entities, relationships=rels, confidence=0.8)


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


def _make_ontology(*pairs) -> dict:
    """Build a minimal ontology dict from (source, target) relationship pairs."""
    rels = [{"source": s, "target": t, "type": "related_to"} for s, t in pairs]
    entities = list({s for s, _ in pairs} | {t for _, t in pairs})
    return {
        "entities": [{"id": e, "text": e} for e in entities],
        "relationships": rels,
    }


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_iqr
# ---------------------------------------------------------------------------

class TestScoreIqr:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_iqr() == 0.0

    def test_fewer_than_four_returns_zero(self):
        opt = _optimizer_with([0.5, 0.6, 0.7])
        assert opt.score_iqr() == 0.0

    def test_uniform_scores_iqr_zero(self):
        opt = _optimizer_with([0.5, 0.5, 0.5, 0.5])
        assert opt.score_iqr() == pytest.approx(0.0)

    def test_known_values(self):
        # scores sorted = [0.1, 0.3, 0.7, 0.9]
        # n=4, q1_idx=4//4=1→0.3, q3_idx=(3*4)//4=3→0.9 → IQR=0.6
        opt = _optimizer_with([0.9, 0.1, 0.7, 0.3])
        assert opt.score_iqr() == pytest.approx(0.6, abs=1e-9)

    def test_non_negative(self):
        opt = _optimizer_with([0.2, 0.8, 0.5, 0.6, 0.3, 0.9])
        assert opt.score_iqr() >= 0.0

    def test_returns_float(self):
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        assert isinstance(opt.score_iqr(), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_rolling_std
# ---------------------------------------------------------------------------

class TestHistoryRollingStd:
    def test_empty_history_returns_empty(self):
        opt = OntologyOptimizer()
        assert opt.history_rolling_std() == []

    def test_fewer_than_window_returns_empty(self):
        opt = _optimizer_with([0.5, 0.6])
        assert opt.history_rolling_std(window=3) == []

    def test_window_two_on_two_entries(self):
        opt = _optimizer_with([0.4, 0.6])
        result = opt.history_rolling_std(window=2)
        assert len(result) == 1
        # mean=0.5; variance = 2*(0.01)/2=0.01; std=0.1
        assert result[0] == pytest.approx(0.1, abs=1e-9)

    def test_uniform_scores_std_zero(self):
        opt = _optimizer_with([0.5, 0.5, 0.5, 0.5])
        result = opt.history_rolling_std(window=2)
        assert all(v == pytest.approx(0.0) for v in result)

    def test_correct_length(self):
        opt = _optimizer_with([0.1, 0.3, 0.5, 0.7, 0.9])
        result = opt.history_rolling_std(window=3)
        assert len(result) == 3  # 5 - 3 + 1

    def test_returns_list_of_floats(self):
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        result = opt.history_rolling_std(window=2)
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_small_window_clamped_to_two(self):
        opt = _optimizer_with([0.4, 0.6])
        result = opt.history_rolling_std(window=1)
        # window clamped to 2; result should have 1 entry
        assert len(result) == 1


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_iqr
# ---------------------------------------------------------------------------

class TestDimensionIqr:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_uniform_dims_iqr_zero(self):
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert self.critic.dimension_iqr(score) == pytest.approx(0.0)

    def test_spread_dimensions(self):
        # dims sorted = [0.0, 0.2, 0.5, 0.7, 0.9, 1.0]
        # n=6, q1_idx=1→0.2, q3_idx=4→0.9 → IQR=0.7
        score = _make_critic_score(
            completeness=1.0, consistency=0.0, clarity=0.5,
            granularity=0.2, relationship_coherence=0.9, domain_alignment=0.7,
        )
        assert self.critic.dimension_iqr(score) == pytest.approx(0.7, abs=1e-9)

    def test_non_negative(self):
        score = _make_critic_score()
        assert self.critic.dimension_iqr(score) >= 0.0

    def test_returns_float(self):
        score = _make_critic_score()
        assert isinstance(self.critic.dimension_iqr(score), float)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_coefficient_of_variation
# ---------------------------------------------------------------------------

class TestDimensionCoefficientOfVariation:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_uniform_dims_cv_zero(self):
        score = _make_critic_score(
            completeness=0.7, consistency=0.7, clarity=0.7,
            granularity=0.7, relationship_coherence=0.7, domain_alignment=0.7,
        )
        assert self.critic.dimension_coefficient_of_variation(score) == pytest.approx(0.0)

    def test_zero_mean_returns_zero(self):
        score = _make_critic_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert self.critic.dimension_coefficient_of_variation(score) == 0.0

    def test_non_negative(self):
        score = _make_critic_score()
        assert self.critic.dimension_coefficient_of_variation(score) >= 0.0

    def test_returns_float(self):
        score = _make_critic_score()
        assert isinstance(self.critic.dimension_coefficient_of_variation(score), float)

    def test_higher_spread_higher_cv(self):
        # Low spread
        s_low = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        # High spread
        s_high = _make_critic_score(
            completeness=0.1, consistency=0.9, clarity=0.2,
            granularity=0.8, relationship_coherence=0.3, domain_alignment=0.7,
        )
        assert (
            self.critic.dimension_coefficient_of_variation(s_high)
            > self.critic.dimension_coefficient_of_variation(s_low)
        )


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_geometric_mean
# ---------------------------------------------------------------------------

class TestEntityConfidenceGeometricMean:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result_returns_zero(self):
        result = _make_result(confidences=[])
        assert self.gen.entity_confidence_geometric_mean(result) == 0.0

    def test_any_zero_confidence_returns_zero(self):
        result = _make_result(confidences=[0.8, 0.0, 0.9])
        assert self.gen.entity_confidence_geometric_mean(result) == 0.0

    def test_all_same_confidence(self):
        result = _make_result(confidences=[0.5, 0.5, 0.5])
        assert self.gen.entity_confidence_geometric_mean(result) == pytest.approx(0.5)

    def test_known_values(self):
        # geo_mean([0.25, 1.0]) = sqrt(0.25) = 0.5
        result = _make_result(confidences=[0.25, 1.0])
        assert self.gen.entity_confidence_geometric_mean(result) == pytest.approx(0.5, abs=1e-9)

    def test_gm_le_am(self):
        result = _make_result(confidences=[0.3, 0.7])
        gm = self.gen.entity_confidence_geometric_mean(result)
        am = (0.3 + 0.7) / 2
        assert gm <= am + 1e-9

    def test_returns_float(self):
        result = _make_result(confidences=[0.8, 0.9])
        assert isinstance(self.gen.entity_confidence_geometric_mean(result), float)

    def test_single_entity(self):
        result = _make_result(confidences=[0.6])
        assert self.gen.entity_confidence_geometric_mean(result) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_harmonic_mean
# ---------------------------------------------------------------------------

class TestEntityConfidenceHarmonicMean:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result_returns_zero(self):
        result = _make_result(confidences=[])
        assert self.gen.entity_confidence_harmonic_mean(result) == 0.0

    def test_any_zero_confidence_returns_zero(self):
        result = _make_result(confidences=[0.8, 0.0, 0.9])
        assert self.gen.entity_confidence_harmonic_mean(result) == 0.0

    def test_all_same_confidence(self):
        result = _make_result(confidences=[0.5, 0.5, 0.5])
        assert self.gen.entity_confidence_harmonic_mean(result) == pytest.approx(0.5)

    def test_known_values(self):
        # hm([0.5, 1.0]) = 2 / (1/0.5 + 1/1.0) = 2 / 3 ≈ 0.6667
        result = _make_result(confidences=[0.5, 1.0])
        assert self.gen.entity_confidence_harmonic_mean(result) == pytest.approx(2 / 3, abs=1e-9)

    def test_hm_le_gm_le_am(self):
        result = _make_result(confidences=[0.3, 0.9])
        hm = self.gen.entity_confidence_harmonic_mean(result)
        gm = self.gen.entity_confidence_geometric_mean(result)
        am = (0.3 + 0.9) / 2
        assert hm <= gm + 1e-9
        assert gm <= am + 1e-9

    def test_returns_float(self):
        result = _make_result(confidences=[0.8, 0.9])
        assert isinstance(self.gen.entity_confidence_harmonic_mean(result), float)

    def test_single_entity(self):
        result = _make_result(confidences=[0.6])
        assert self.gen.entity_confidence_harmonic_mean(result) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_confidence_iqr
# ---------------------------------------------------------------------------

class TestRelationshipConfidenceIqr:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_rels_returns_zero(self):
        result = _make_result(confidences=[0.8, 0.9])
        assert self.gen.relationship_confidence_iqr(result) == 0.0

    def test_fewer_than_four_returns_zero(self):
        result = _make_result(confidences=[0.8, 0.9, 0.7], rel_confidences=[0.5, 0.7, 0.9])
        assert self.gen.relationship_confidence_iqr(result) == 0.0

    def test_known_values(self):
        # sorted [0.2, 0.4, 0.6, 0.8]
        # n=4, q1_idx=1→0.4, q3_idx=3→0.8 → IQR=0.4
        result = _make_result(
            confidences=[0.9, 0.8, 0.7, 0.6],
            rel_confidences=[0.8, 0.2, 0.6, 0.4],
        )
        assert self.gen.relationship_confidence_iqr(result) == pytest.approx(0.4, abs=1e-9)

    def test_non_negative(self):
        result = _make_result(
            confidences=[0.9, 0.8, 0.7, 0.6],
            rel_confidences=[0.3, 0.5, 0.7, 0.9],
        )
        assert self.gen.relationship_confidence_iqr(result) >= 0.0

    def test_returns_float(self):
        result = _make_result(
            confidences=[0.9, 0.8, 0.7, 0.6],
            rel_confidences=[0.3, 0.5, 0.7, 0.9],
        )
        assert isinstance(self.gen.relationship_confidence_iqr(result), float)

    def test_uniform_rels_iqr_zero(self):
        result = _make_result(
            confidences=[0.9, 0.8, 0.7, 0.6],
            rel_confidences=[0.5, 0.5, 0.5, 0.5],
        )
        assert self.gen.relationship_confidence_iqr(result) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_iqr
# ---------------------------------------------------------------------------

class TestFeedbackIqr:
    def test_empty_feedback_returns_zero(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_iqr() == 0.0

    def test_fewer_than_four_returns_zero(self):
        adapter = _adapter_with([0.5, 0.6, 0.7])
        assert adapter.feedback_iqr() == 0.0

    def test_uniform_feedback_iqr_zero(self):
        adapter = _adapter_with([0.5, 0.5, 0.5, 0.5])
        assert adapter.feedback_iqr() == pytest.approx(0.0)

    def test_known_values(self):
        # sorted [0.1, 0.3, 0.7, 0.9]
        # n=4, q1_idx=1→0.3, q3_idx=3→0.9 → IQR=0.6
        adapter = _adapter_with([0.9, 0.1, 0.7, 0.3])
        assert adapter.feedback_iqr() == pytest.approx(0.6, abs=1e-9)

    def test_non_negative(self):
        adapter = _adapter_with([0.2, 0.8, 0.5, 0.6])
        assert adapter.feedback_iqr() >= 0.0

    def test_returns_float(self):
        adapter = _adapter_with([0.3, 0.5, 0.7, 0.9])
        assert isinstance(adapter.feedback_iqr(), float)


# ---------------------------------------------------------------------------
# OntologyPipeline.best_score_improvement
# ---------------------------------------------------------------------------

class TestBestScoreImprovement:
    def test_empty_returns_zero(self):
        pipeline = OntologyPipeline()
        assert pipeline.best_score_improvement() == 0.0

    def test_single_run_returns_zero(self):
        pipeline = _make_pipeline_with([0.7])
        assert pipeline.best_score_improvement() == 0.0

    def test_monotonically_increasing(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.8])
        # max improvement = 0.8 - 0.5 = 0.3
        assert pipeline.best_score_improvement() == pytest.approx(0.3, abs=1e-9)

    def test_only_declining_returns_zero(self):
        pipeline = _make_pipeline_with([0.9, 0.7, 0.5])
        assert pipeline.best_score_improvement() == 0.0

    def test_mixed_returns_max_positive_delta(self):
        # deltas: [0.2, -0.1, 0.5, -0.3] → max = 0.5
        pipeline = _make_pipeline_with([0.1, 0.3, 0.2, 0.7, 0.4])
        assert pipeline.best_score_improvement() == pytest.approx(0.5, abs=1e-9)

    def test_non_negative(self):
        pipeline = _make_pipeline_with([0.7, 0.5, 0.8, 0.6])
        assert pipeline.best_score_improvement() >= 0.0

    def test_returns_float(self):
        pipeline = _make_pipeline_with([0.4, 0.6])
        assert isinstance(pipeline.best_score_improvement(), float)


# ---------------------------------------------------------------------------
# OntologyPipeline.rounds_without_improvement
# ---------------------------------------------------------------------------

class TestRoundsWithoutImprovement:
    def test_empty_returns_zero(self):
        pipeline = OntologyPipeline()
        assert pipeline.rounds_without_improvement() == 0

    def test_single_run_returns_zero(self):
        pipeline = _make_pipeline_with([0.7])
        assert pipeline.rounds_without_improvement() == 0

    def test_all_improving_returns_zero(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.7, 0.9])
        assert pipeline.rounds_without_improvement() == 0

    def test_all_declining_returns_count(self):
        pipeline = _make_pipeline_with([0.9, 0.7, 0.5, 0.3])
        assert pipeline.rounds_without_improvement() == 3

    def test_last_two_no_improve(self):
        pipeline = _make_pipeline_with([0.3, 0.7, 0.6, 0.5])
        assert pipeline.rounds_without_improvement() == 2

    def test_last_run_improves_returns_zero(self):
        pipeline = _make_pipeline_with([0.5, 0.4, 0.9])
        assert pipeline.rounds_without_improvement() == 0

    def test_returns_int(self):
        pipeline = _make_pipeline_with([0.5, 0.4])
        assert isinstance(pipeline.rounds_without_improvement(), int)


# ---------------------------------------------------------------------------
# LogicValidator.most_connected_node
# ---------------------------------------------------------------------------

class TestMostConnectedNode:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_returns_empty(self):
        assert self.validator.most_connected_node({}) == ""

    def test_no_relationships_returns_empty(self):
        ont = {"entities": [{"id": "a"}], "relationships": []}
        assert self.validator.most_connected_node(ont) == ""

    def test_single_relationship(self):
        ont = _make_ontology(("a", "b"))
        # a: degree 1 (source), b: degree 1 (target) — either valid
        result = self.validator.most_connected_node(ont)
        assert result in ("a", "b")

    def test_clear_winner(self):
        # "hub" has 3 connections; others have 1 each
        ont = _make_ontology(("hub", "x"), ("hub", "y"), ("hub", "z"))
        assert self.validator.most_connected_node(ont) == "hub"

    def test_bidirectional_highest_degree(self):
        # a→b, b→a, a→c: a is source in 2 rels (→b, →c) and target in 1 rel (←b) = degree 3
        # b is source in 1 rel (→a) and target in 1 rel (←a) = degree 2
        # c is target in 1 rel = degree 1 → most connected = a
        ont = _make_ontology(("a", "b"), ("b", "a"), ("a", "c"))
        # a: source in 2 rels (→b, →c), target in 1 rel (←b): degree=3
        # b: source in 1 rel, target in 1 rel: degree=2
        assert self.validator.most_connected_node(ont) == "a"

    def test_returns_string(self):
        ont = _make_ontology(("x", "y"))
        result = self.validator.most_connected_node(ont)
        assert isinstance(result, str)
