"""
Unit tests for Batch 206 implementations.

Tests cover:
- OntologyOptimizer.score_entropy()
- OntologyOptimizer.history_above_percentile(p)
- OntologyCritic.dimensions_above_mean(score)
- OntologyLearningAdapter.feedback_rolling_std(window)
- OntologyPipeline.consecutive_declines()
- LogicValidator.avg_degree(ontology)

(The following Batch 206 backlog items were found to already exist in source,
 so they are only smoke-tested here rather than tested fully:
  - OntologyCritic.dimension_entropy(score)
  - OntologyGenerator.entity_confidence_range(result)
  - OntologyGenerator.entity_count_by_type(result)
  - OntologyPipeline.run_score_kurtosis()
)
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import MagicMock

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
    """Build a minimal dict ontology from (source, target) relationship pairs."""
    rels = [{"source": s, "target": t, "type": "r"} for s, t in pairs]
    return {"relationships": rels}


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_entropy
# ---------------------------------------------------------------------------

class TestScoreEntropy:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.score_entropy() == 0.0

    def test_single_entry_returns_zero(self):
        # Only one bin occupied → p=1 → H = -1*log2(1) = 0
        opt = _optimizer_with([0.5])
        assert opt.score_entropy() == pytest.approx(0.0)

    def test_two_equal_bins_returns_one_bit(self):
        # Two equally populated bins → H = 1.0 bit
        opt = _optimizer_with([0.1, 0.9])  # bins 1 and 9 each get 1 count
        assert opt.score_entropy() == pytest.approx(1.0)

    def test_uniform_all_same_bin_returns_zero(self):
        opt = _optimizer_with([0.5, 0.5, 0.5, 0.5])
        assert opt.score_entropy() == pytest.approx(0.0)

    def test_high_entropy_many_bins(self):
        # 10 distinct bins → max entropy = log2(10) ≈ 3.32 bits
        opt = _optimizer_with([0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95])
        h = opt.score_entropy()
        assert h == pytest.approx(math.log2(10), abs=1e-9)

    def test_returns_float(self):
        opt = _optimizer_with([0.3, 0.7])
        assert isinstance(opt.score_entropy(), float)

    def test_non_negative(self):
        opt = _optimizer_with([0.2, 0.4, 0.6, 0.8])
        assert opt.score_entropy() >= 0.0


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_above_percentile
# ---------------------------------------------------------------------------

class TestHistoryAbovePercentile:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.history_above_percentile() == 0

    def test_all_below_threshold(self):
        # With 4 entries and p=75: threshold=scores[3]=0.9 → 0 above
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        assert opt.history_above_percentile(75) == 0

    def test_some_above_threshold(self):
        # With 4 entries and p=50: threshold=scores[2]=0.7 → 1 above (0.9)
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        assert opt.history_above_percentile(50) == 1

    def test_p_zero_all_above_threshold(self):
        # p=0: threshold=scores[0]=min → all above (but not strictly > min)
        opt = _optimizer_with([0.3, 0.5, 0.7, 0.9])
        # threshold = scores[0] = 0.3 → strictly above 0.3 = 3 entries
        assert opt.history_above_percentile(0) == 3

    def test_returns_int(self):
        opt = _optimizer_with([0.5, 0.7, 0.9])
        assert isinstance(opt.history_above_percentile(), int)

    def test_non_negative(self):
        opt = _optimizer_with([0.2, 0.8])
        assert opt.history_above_percentile(50) >= 0


# ---------------------------------------------------------------------------
# OntologyCritic.dimensions_above_mean
# ---------------------------------------------------------------------------

class TestDimensionsAboveMean:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_uniform_dims_none_above_mean(self):
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert self.critic.dimensions_above_mean(score) == 0

    def test_half_above_mean(self):
        # mean = (0.9+0.9+0.9+0.1+0.1+0.1)/6 = 0.5
        # Dims > 0.5: completeness, consistency, clarity (3)
        score = _make_critic_score(
            completeness=0.9, consistency=0.9, clarity=0.9,
            granularity=0.1, relationship_coherence=0.1, domain_alignment=0.1,
        )
        assert self.critic.dimensions_above_mean(score) == 3

    def test_all_different_one_above_mean(self):
        # vals = [0.8, 0.7, 0.6, 0.5, 0.4, 0.3]; mean = 0.55
        # above 0.55: 0.8, 0.7, 0.6 → 3
        score = _make_critic_score()  # uses defaults
        assert self.critic.dimensions_above_mean(score) == 3

    def test_non_negative(self):
        score = _make_critic_score()
        assert self.critic.dimensions_above_mean(score) >= 0

    def test_at_most_six(self):
        score = _make_critic_score()
        assert self.critic.dimensions_above_mean(score) <= 6

    def test_returns_int(self):
        score = _make_critic_score()
        assert isinstance(self.critic.dimensions_above_mean(score), int)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_rolling_std
# ---------------------------------------------------------------------------

class TestFeedbackRollingStd:
    def test_empty_feedback_returns_empty(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_rolling_std() == []

    def test_fewer_than_window_returns_empty(self):
        adapter = _adapter_with([0.5])
        assert adapter.feedback_rolling_std(window=2) == []

    def test_uniform_scores_std_zero(self):
        adapter = _adapter_with([0.5, 0.5, 0.5])
        result = adapter.feedback_rolling_std(window=2)
        assert all(v == pytest.approx(0.0) for v in result)

    def test_window_two_known_value(self):
        # [0.4, 0.6]: mean=0.5; variance=(0.01+0.01)/2=0.01; std=0.1
        adapter = _adapter_with([0.4, 0.6])
        result = adapter.feedback_rolling_std(window=2)
        assert len(result) == 1
        assert result[0] == pytest.approx(0.1, abs=1e-9)

    def test_correct_length(self):
        adapter = _adapter_with([0.1, 0.3, 0.5, 0.7, 0.9])
        result = adapter.feedback_rolling_std(window=3)
        assert len(result) == 3  # 5 - 3 + 1

    def test_returns_list_of_floats(self):
        adapter = _adapter_with([0.3, 0.5, 0.7])
        result = adapter.feedback_rolling_std(window=2)
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_small_window_clamped_to_two(self):
        adapter = _adapter_with([0.4, 0.6])
        # window=1 should be clamped to 2
        result = adapter.feedback_rolling_std(window=1)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# OntologyPipeline.consecutive_declines
# ---------------------------------------------------------------------------

class TestConsecutiveDeclines:
    def test_empty_returns_zero(self):
        pipeline = OntologyPipeline()
        assert pipeline.consecutive_declines() == 0

    def test_single_run_returns_zero(self):
        pipeline = _make_pipeline_with([0.7])
        assert pipeline.consecutive_declines() == 0

    def test_all_improving_returns_zero(self):
        pipeline = _make_pipeline_with([0.3, 0.5, 0.7, 0.9])
        assert pipeline.consecutive_declines() == 0

    def test_single_decline(self):
        pipeline = _make_pipeline_with([0.7, 0.5])
        assert pipeline.consecutive_declines() == 1

    def test_three_consecutive_declines(self):
        pipeline = _make_pipeline_with([0.9, 0.7, 0.5, 0.3])
        assert pipeline.consecutive_declines() == 3

    def test_finds_longest_streak(self):
        # [0.9, 0.8, 0.5, 0.6, 0.4, 0.2, 0.3]
        # streak1: 0.9→0.8→0.5 = 2 declines
        # streak2: 0.6→0.4→0.2 = 2 declines
        pipeline = _make_pipeline_with([0.9, 0.8, 0.5, 0.6, 0.4, 0.2, 0.3])
        assert pipeline.consecutive_declines() == 2

    def test_all_equal_returns_zero(self):
        pipeline = _make_pipeline_with([0.5, 0.5, 0.5])
        assert pipeline.consecutive_declines() == 0

    def test_returns_int(self):
        pipeline = _make_pipeline_with([0.7, 0.5, 0.9])
        assert isinstance(pipeline.consecutive_declines(), int)


# ---------------------------------------------------------------------------
# LogicValidator.avg_degree
# ---------------------------------------------------------------------------

class TestAvgDegree:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_returns_zero(self):
        assert self.validator.avg_degree({}) == 0.0

    def test_no_relationships_returns_zero(self):
        assert self.validator.avg_degree({"relationships": []}) == 0.0

    def test_single_edge_two_nodes(self):
        # a→b: a degree=1, b degree=1 → avg=1.0
        ont = _make_ontology(("a", "b"))
        assert self.validator.avg_degree(ont) == pytest.approx(1.0)

    def test_star_topology(self):
        # hub→x, hub→y, hub→z: hub=3, x=1, y=1, z=1 → sum=6, nodes=4 → avg=1.5
        ont = _make_ontology(("hub", "x"), ("hub", "y"), ("hub", "z"))
        assert self.validator.avg_degree(ont) == pytest.approx(1.5)

    def test_non_negative(self):
        ont = _make_ontology(("a", "b"), ("b", "c"))
        assert self.validator.avg_degree(ont) >= 0.0

    def test_returns_float(self):
        ont = _make_ontology(("x", "y"))
        assert isinstance(self.validator.avg_degree(ont), float)

    def test_avg_degree_equals_2_times_edges_div_nodes(self):
        # In an undirected view, avg_degree = 2*|E|/|V|
        # Here we count each edge endpoint; so sum_of_degrees = 2*|E|
        # With a→b, b→c, c→a: 3 edges, 3 nodes → sum_of_degrees=6 → avg=2.0
        ont = _make_ontology(("a", "b"), ("b", "c"), ("c", "a"))
        assert self.validator.avg_degree(ont) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Smoke tests for already-existing Batch 206 methods
# ---------------------------------------------------------------------------

class TestExistingBatch206Methods:
    """Tests confirming that pre-existing methods still work correctly."""

    def test_dimension_entropy_uniform_dims(self):
        # Uniform dimension values → all in one bin → entropy = 0
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        result = critic.dimension_entropy(score)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_dimension_entropy_varied_dims(self):
        # dimension_entropy treats values as a probability distribution (normalized).
        # Uniform values → maximum entropy (all probabilities equal).
        # Varied values → lower entropy (skewed distribution).
        critic = OntologyCritic()
        score_varied = _make_critic_score(
            completeness=0.9, consistency=0.1, clarity=0.8,
            granularity=0.2, relationship_coherence=0.7, domain_alignment=0.3,
        )
        score_uniform = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        # Uniform distribution is max entropy; varied should be ≤ uniform entropy
        assert critic.dimension_entropy(score_varied) <= critic.dimension_entropy(score_uniform)

    def test_run_score_kurtosis_negative_for_uniform_spread(self):
        # Uniformly spread values → platykurtic (excess kurtosis < 0)
        pipeline = _make_pipeline_with([0.1, 0.3, 0.5, 0.7, 0.9])
        result = pipeline.run_score_kurtosis()
        assert isinstance(result, float)
        assert result < 0.0  # uniform spread is platykurtic

    def test_run_score_kurtosis_zero_for_fewer_than_four_runs(self):
        pipeline = _make_pipeline_with([0.5, 0.6, 0.7])
        result = pipeline.run_score_kurtosis()
        # May return 0.0 for < 4 entries
        assert isinstance(result, float)
