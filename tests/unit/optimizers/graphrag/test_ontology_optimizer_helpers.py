"""Deterministic unit tests for pure OntologyOptimizer helper methods.

Tests:
- _compute_std: standard deviation computation
- _determine_trend: trend detection based on history
- _generate_recommendations: score-to-recommendation mapping
- _compute_score_distribution: dimension score aggregation
- _identify_patterns: pattern counting across sessions
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


def _make_report(score: float) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


def _make_session(score: float, dims: dict | None = None):
    """Create a minimal MediatorState-like session stub."""
    dim_vals = dims or {}
    cs = SimpleNamespace(
        overall=score,
        completeness=dim_vals.get("completeness"),
        consistency=dim_vals.get("consistency"),
        clarity=dim_vals.get("clarity"),
        granularity=dim_vals.get("granularity"),
        domain_alignment=dim_vals.get("domain_alignment"),
    )
    return SimpleNamespace(
        critic_scores=[cs],
        critic_score=cs,
        current_round=2,
    )


@pytest.fixture
def opt():
    return OntologyOptimizer()


class TestComputeStd:
    def test_empty_list_returns_zero(self, opt):
        assert opt._compute_std([]) == 0.0

    def test_single_element_returns_zero(self, opt):
        assert opt._compute_std([0.7]) == 0.0

    def test_all_identical_returns_zero(self, opt):
        assert opt._compute_std([0.5, 0.5, 0.5]) == pytest.approx(0.0)

    def test_known_std(self, opt):
        # std([0, 1]) = 0.5
        result = opt._compute_std([0.0, 1.0])
        assert result == pytest.approx(0.5)

    def test_larger_set(self, opt):
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        mean = sum(scores) / len(scores)
        expected = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5
        assert opt._compute_std(scores) == pytest.approx(expected)


class TestDetermineTrend:
    def test_no_history_returns_baseline(self, opt):
        assert opt._determine_trend(0.7) == "baseline"

    def test_improvement_more_than_5pct(self, opt):
        opt._history.append(_make_report(0.5))
        assert opt._determine_trend(0.56) == "improving"

    def test_degradation_more_than_5pct(self, opt):
        opt._history.append(_make_report(0.8))
        assert opt._determine_trend(0.74) == "degrading"

    def test_stable_within_5pct(self, opt):
        opt._history.append(_make_report(0.7))
        assert opt._determine_trend(0.72) == "stable"

    def test_exactly_5pct_improvement_is_improving(self, opt):
        opt._history.append(_make_report(0.5))
        assert opt._determine_trend(0.5501) == "improving"

    def test_exactly_5pct_degradation_is_degrading(self, opt):
        opt._history.append(_make_report(0.8))
        assert opt._determine_trend(0.7499) == "degrading"


class TestGenerateRecommendations:
    def test_low_score_recommends_strategy(self, opt):
        recs = opt._generate_recommendations(0.4, [0.4], {})
        assert any("hybrid" in r.lower() or "strategy" in r.lower() for r in recs)

    def test_medium_low_recommends_domain_templates(self, opt):
        recs = opt._generate_recommendations(0.7, [0.7], {})
        assert any("domain" in r.lower() or "dimension" in r.lower() for r in recs)

    def test_medium_high_recommends_validation(self, opt):
        recs = opt._generate_recommendations(0.8, [0.8], {})
        assert any("validation" in r.lower() or "threshold" in r.lower() for r in recs)

    def test_high_score_maintain_config(self, opt):
        recs = opt._generate_recommendations(0.9, [0.9], {})
        assert any("maintain" in r.lower() for r in recs)

    def test_high_variance_adds_recommendation(self, opt):
        scores = [0.2, 0.9]  # std ~= 0.35
        recs = opt._generate_recommendations(0.55, scores, {})
        assert any("variance" in r.lower() for r in recs)

    def test_low_variance_no_variance_recommendation(self, opt):
        scores = [0.9, 0.91, 0.89]  # std < 0.15
        recs = opt._generate_recommendations(0.9, scores, {})
        assert not any("variance" in r.lower() for r in recs)


class TestComputeScoreDistribution:
    def test_empty_returns_zeros(self, opt):
        result = opt._compute_score_distribution([])
        assert all(v == 0.0 for v in result.values())

    def test_known_dimension_scores(self, opt):
        sessions = [_make_session(0.8, {"completeness": 0.6, "clarity": 0.9})]
        dist = opt._compute_score_distribution(sessions)
        assert dist["completeness"] == pytest.approx(0.6)
        assert dist["clarity"] == pytest.approx(0.9)

    def test_averages_multiple_sessions(self, opt):
        sessions = [
            _make_session(0.7, {"completeness": 0.4}),
            _make_session(0.8, {"completeness": 0.8}),
        ]
        dist = opt._compute_score_distribution(sessions)
        assert dist["completeness"] == pytest.approx(0.6)

    def test_missing_dim_yields_zero(self, opt):
        sessions = [_make_session(0.7, {})]
        dist = opt._compute_score_distribution(sessions)
        assert dist["completeness"] == 0.0


class TestIdentifyPatterns:
    def test_empty_returns_zero_counts(self, opt):
        patterns = opt._identify_patterns([])
        assert patterns["session_count"] == 0
        assert patterns["avg_final_score"] == 0.0

    def test_session_count_correct(self, opt):
        sessions = [_make_session(0.7)] * 3
        patterns = opt._identify_patterns(sessions)
        assert patterns["session_count"] == 3

    def test_avg_convergence_rounds(self, opt):
        sessions = [_make_session(0.7)] * 2  # each has current_round=2
        patterns = opt._identify_patterns(sessions)
        assert patterns["avg_convergence_rounds"] == pytest.approx(2.0)
