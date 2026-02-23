"""
Unit tests for Batch 208 implementations.

Tests cover new methods:
- OntologyOptimizer.score_trend_slope()
- OntologyCritic.score_dimension_variance(score)
- OntologyGenerator.relationship_type_count(result)
- OntologyPipeline.last_improving_run()
- LogicValidator.closeness_centrality_approx(ontology)
- LogicValidator.reciprocal_edge_count(ontology)

Smoke tests for pre-existing Batch 208 items:
- OntologyOptimizer.history_variance()
- OntologyCritic.dimension_variance(scores, dim)
- OntologyGenerator.relationship_type_counts(result)
- OntologyLearningAdapter.feedback_trend_slope()
- OntologyPipeline.run_score_variance()
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


def _make_result_with_rels(types: list[str]) -> EntityExtractionResult:
    rels = [
        Relationship(id=f"r{i}", source_id="a", target_id="b", type=t)
        for i, t in enumerate(types)
    ]
    return EntityExtractionResult(entities=[], relationships=rels, confidence=0.8)


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
# OntologyOptimizer.score_trend_slope
# ---------------------------------------------------------------------------

class TestScoreTrendSlope:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_trend_slope() == 0.0

    def test_single_entry_returns_zero(self):
        opt = _optimizer_with([0.5])
        assert opt.score_trend_slope() == 0.0

    def test_constant_scores_returns_zero(self):
        opt = _optimizer_with([0.5, 0.5, 0.5])
        assert opt.score_trend_slope() == pytest.approx(0.0)

    def test_linearly_increasing_positive_slope(self):
        # [0.2, 0.4, 0.6, 0.8]: slope should be 0.2
        opt = _optimizer_with([0.2, 0.4, 0.6, 0.8])
        assert opt.score_trend_slope() == pytest.approx(0.2, abs=1e-9)

    def test_linearly_decreasing_negative_slope(self):
        # [0.8, 0.6, 0.4, 0.2]: slope should be -0.2
        opt = _optimizer_with([0.8, 0.6, 0.4, 0.2])
        assert opt.score_trend_slope() == pytest.approx(-0.2, abs=1e-9)

    def test_two_points_known_slope(self):
        # [0.3, 0.7]: x=[0,1], slope = (0.7-0.3) / 1 = 0.4
        opt = _optimizer_with([0.3, 0.7])
        assert opt.score_trend_slope() == pytest.approx(0.4, abs=1e-9)

    def test_returns_float(self):
        opt = _optimizer_with([0.3, 0.5, 0.7])
        assert isinstance(opt.score_trend_slope(), float)

    def test_noisy_but_positive_trend(self):
        # General increasing trend despite some noise
        opt = _optimizer_with([0.2, 0.35, 0.3, 0.5, 0.45, 0.6])
        assert opt.score_trend_slope() > 0.0


# ---------------------------------------------------------------------------
# OntologyCritic.score_dimension_variance
# ---------------------------------------------------------------------------

class TestScoreDimensionVariance:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_uniform_dims_returns_zero(self):
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert self.critic.score_dimension_variance(score) == pytest.approx(0.0)

    def test_known_value(self):
        # vals=[0.8,0.7,0.6,0.5,0.4,0.3]: mean=0.55
        # variance = ((0.25+0.15+0.05+0.05+0.15+0.25)/6) * (each^2 adjusted)
        # = sum((v-0.55)^2)/6 = (0.0625+0.0225+0.0025+0.0025+0.0225+0.0625)/6
        # = 0.175/6 = 0.029167
        score = _make_critic_score()  # defaults: 0.8,0.7,0.6,0.5,0.4,0.3
        assert self.critic.score_dimension_variance(score) == pytest.approx(0.175 / 6, abs=1e-9)

    def test_max_spread_high_variance(self):
        # [0,0,0,1,1,1] → mean=0.5; variance = 3*(0.25)+3*(0.25) / 6 = 0.25
        score = _make_critic_score(
            completeness=1.0, consistency=1.0, clarity=1.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert self.critic.score_dimension_variance(score) == pytest.approx(0.25)

    def test_non_negative(self):
        score = _make_critic_score()
        assert self.critic.score_dimension_variance(score) >= 0.0

    def test_returns_float(self):
        score = _make_critic_score()
        assert isinstance(self.critic.score_dimension_variance(score), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_type_count
# ---------------------------------------------------------------------------

class TestRelationshipTypeCount:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result_returns_zero(self):
        result = EntityExtractionResult(entities=[], relationships=[], confidence=0.8)
        assert self.gen.relationship_type_count(result) == 0

    def test_single_type_returns_one(self):
        result = _make_result_with_rels(["owns", "owns", "owns"])
        assert self.gen.relationship_type_count(result) == 1

    def test_two_types(self):
        result = _make_result_with_rels(["owns", "owns", "causes"])
        assert self.gen.relationship_type_count(result) == 2

    def test_all_unique_types(self):
        result = _make_result_with_rels(["owns", "causes", "contains", "requires"])
        assert self.gen.relationship_type_count(result) == 4

    def test_returns_int(self):
        result = _make_result_with_rels(["owns"])
        assert isinstance(self.gen.relationship_type_count(result), int)

    def test_non_negative(self):
        result = _make_result_with_rels(["type1", "type2"])
        assert self.gen.relationship_type_count(result) >= 0


# ---------------------------------------------------------------------------
# OntologyPipeline.last_improving_run
# ---------------------------------------------------------------------------

class TestLastImprovingRun:
    def test_empty_returns_minus_one(self):
        pipeline = OntologyPipeline()
        assert pipeline.last_improving_run() == -1

    def test_single_run_returns_minus_one(self):
        pipeline = _make_pipeline_with([0.7])
        assert pipeline.last_improving_run() == -1

    def test_all_declining_returns_minus_one(self):
        pipeline = _make_pipeline_with([0.9, 0.7, 0.5])
        assert pipeline.last_improving_run() == -1

    def test_last_run_improves(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.7])
        assert pipeline.last_improving_run() == 2

    def test_multiple_improving_returns_last(self):
        # runs: [0.3, 0.7, 0.5, 0.9]: improving at idx 1 (0.7>0.3) and idx 3 (0.9>0.5)
        pipeline = _make_pipeline_with([0.3, 0.7, 0.5, 0.9])
        assert pipeline.last_improving_run() == 3

    def test_improvement_then_decline(self):
        # [0.3, 0.8, 0.5, 0.4]: improving at idx 1 only → last=1
        pipeline = _make_pipeline_with([0.3, 0.8, 0.5, 0.4])
        assert pipeline.last_improving_run() == 1

    def test_equal_scores_returns_minus_one(self):
        pipeline = _make_pipeline_with([0.5, 0.5, 0.5])
        assert pipeline.last_improving_run() == -1

    def test_returns_int(self):
        pipeline = _make_pipeline_with([0.4, 0.6])
        assert isinstance(pipeline.last_improving_run(), int)

    def test_last_always_geq_first(self):
        # last_improving_run must be >= first_improving_run when both exist
        pipeline = _make_pipeline_with([0.1, 0.5, 0.3, 0.9])
        assert pipeline.last_improving_run() >= pipeline.first_improving_run()


# ---------------------------------------------------------------------------
# LogicValidator.closeness_centrality_approx
# ---------------------------------------------------------------------------

class TestClosenessCentralityApprox:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_returns_empty(self):
        assert self.validator.closeness_centrality_approx({}) == {}

    def test_no_relationships_returns_empty(self):
        assert self.validator.closeness_centrality_approx({"relationships": []}) == {}

    def test_single_edge_returns_dict(self):
        ont = _make_ontology(("a", "b"))
        result = self.validator.closeness_centrality_approx(ont)
        assert set(result.keys()) == {"a", "b"}

    def test_centrality_non_negative(self):
        ont = _make_ontology(("a", "b"), ("b", "c"), ("c", "a"))
        result = self.validator.closeness_centrality_approx(ont)
        for v in result.values():
            assert v >= 0.0

    def test_hub_has_higher_centrality(self):
        # hub connected to x, y, z; x/y/z only connected to hub
        ont = _make_ontology(("hub", "x"), ("hub", "y"), ("hub", "z"))
        result = self.validator.closeness_centrality_approx(ont)
        # hub reaches all 3 at distance 1 → C(hub)=3/3=1.0
        # x reaches hub at dist 1, y/z at dist 2 → C(x)=3/(1+2+2)=0.6
        assert result["hub"] > result["x"]

    def test_hub_centrality_known_value(self):
        # hub→x, hub→y, hub→z (undirected view)
        ont = _make_ontology(("hub", "x"), ("hub", "y"), ("hub", "z"))
        result = self.validator.closeness_centrality_approx(ont)
        assert result["hub"] == pytest.approx(1.0)

    def test_returns_dict_of_floats(self):
        ont = _make_ontology(("a", "b"))
        result = self.validator.closeness_centrality_approx(ont)
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, float)


# ---------------------------------------------------------------------------
# LogicValidator.reciprocal_edge_count
# ---------------------------------------------------------------------------

class TestReciprocalEdgeCount:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_returns_zero(self):
        assert self.validator.reciprocal_edge_count({}) == 0

    def test_no_relationships_returns_zero(self):
        assert self.validator.reciprocal_edge_count({"relationships": []}) == 0

    def test_no_reciprocal_edges(self):
        # a→b, b→c: no reverse edges
        ont = _make_ontology(("a", "b"), ("b", "c"))
        assert self.validator.reciprocal_edge_count(ont) == 0

    def test_single_reciprocal_pair(self):
        # a→b and b→a: 1 reciprocal pair
        ont = _make_ontology(("a", "b"), ("b", "a"))
        assert self.validator.reciprocal_edge_count(ont) == 1

    def test_two_reciprocal_pairs(self):
        # a↔b and c↔d: 2 pairs
        ont = _make_ontology(("a", "b"), ("b", "a"), ("c", "d"), ("d", "c"))
        assert self.validator.reciprocal_edge_count(ont) == 2

    def test_mixed_graph(self):
        # a→b, b→a (1 pair), a→c (no pair)
        ont = _make_ontology(("a", "b"), ("b", "a"), ("a", "c"))
        assert self.validator.reciprocal_edge_count(ont) == 1

    def test_returns_int(self):
        ont = _make_ontology(("x", "y"))
        assert isinstance(self.validator.reciprocal_edge_count(ont), int)

    def test_non_negative(self):
        ont = _make_ontology(("a", "b"), ("c", "d"))
        assert self.validator.reciprocal_edge_count(ont) >= 0


# ---------------------------------------------------------------------------
# Smoke tests for pre-existing Batch 208 items
# ---------------------------------------------------------------------------

class TestExistingBatch208Methods:
    def test_history_variance_returns_float(self):
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        result = opt.history_variance()
        assert isinstance(result, float)
        assert result >= 0.0

    def test_dimension_variance_list_version(self):
        critic = OntologyCritic()
        scores = [_make_critic_score(completeness=0.3), _make_critic_score(completeness=0.7)]
        result = critic.dimension_variance(scores, "completeness")
        assert isinstance(result, float)
        assert result == pytest.approx(0.04)  # mean=0.5; var=((0.2^2+0.2^2)/2)=0.04

    def test_relationship_type_counts_returns_dict(self):
        gen = OntologyGenerator()
        rels = [
            Relationship(id="r1", source_id="a", target_id="b", type="owns"),
            Relationship(id="r2", source_id="b", target_id="c", type="causes"),
            Relationship(id="r3", source_id="c", target_id="a", type="owns"),
        ]
        result_obj = EntityExtractionResult(entities=[], relationships=rels, confidence=0.8)
        counts = gen.relationship_type_counts(result_obj)
        assert isinstance(counts, dict)
        assert counts.get("owns") == 2
        assert counts.get("causes") == 1

    def test_feedback_trend_slope_returns_float(self):
        adapter = _adapter_with([0.3, 0.5, 0.7, 0.9])
        result = adapter.feedback_trend_slope()
        assert isinstance(result, float)

    def test_run_score_variance_returns_float(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.7, 0.9])
        result = pipeline.run_score_variance()
        assert isinstance(result, float)
        assert result >= 0.0
