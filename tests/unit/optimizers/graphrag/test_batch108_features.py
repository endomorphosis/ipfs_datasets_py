"""Batch-108 feature tests.

Methods under test:
  - OntologyPipeline.score_variance()
  - OntologyPipeline.score_stddev()
  - OntologyPipeline.passing_run_count(threshold)
  - OntologyPipeline.run_summary()
  - OntologyLearningAdapter.has_feedback()
  - OntologyLearningAdapter.recent_feedback(n)
  - OntologyLearningAdapter.feedback_score_stats()
  - OntologyLearningAdapter.feedback_percentile(p)
  - OntologyLearningAdapter.passing_feedback_fraction(threshold)
  - OntologyCritic.failing_scores(scores, threshold)
  - OntologyCritic.average_dimension(scores, dim)
  - OntologyCritic.score_summary(scores)
"""
import math
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline

    return OntologyPipeline()


def _push_pipeline_run(pipeline, overall: float):
    """Append a fake run result with the given overall score."""
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    pipeline._run_history.append(run)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
        OntologyLearningAdapter,
    )

    return OntologyLearningAdapter()


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic

    return OntologyCritic(use_llm=False)


def _make_critic_score(completeness=0.8, consistency=0.7, clarity=0.6,
                        granularity=0.5, domain_alignment=0.9):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore

    return CriticScore(
        completeness=completeness,
        consistency=consistency,
        clarity=clarity,
        granularity=granularity,
        domain_alignment=domain_alignment,
    )


# ---------------------------------------------------------------------------
# OntologyPipeline.score_variance
# ---------------------------------------------------------------------------

class TestPipelineScoreVariance:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_variance() == 0.0

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_pipeline_run(p, 0.7)
        assert p.score_variance() == 0.0

    def test_identical_scores_zero_variance(self):
        p = _make_pipeline()
        for _ in range(3):
            _push_pipeline_run(p, 0.8)
        assert p.score_variance() == pytest.approx(0.0)

    def test_varying_scores(self):
        p = _make_pipeline()
        _push_pipeline_run(p, 0.4)
        _push_pipeline_run(p, 0.6)
        assert p.score_variance() > 0.0


# ---------------------------------------------------------------------------
# OntologyPipeline.score_stddev
# ---------------------------------------------------------------------------

class TestPipelineScoreStddev:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_stddev() == 0.0

    def test_equals_sqrt_variance(self):
        p = _make_pipeline()
        _push_pipeline_run(p, 0.2)
        _push_pipeline_run(p, 0.4)
        _push_pipeline_run(p, 0.6)
        assert p.score_stddev() == pytest.approx(math.sqrt(p.score_variance()))


# ---------------------------------------------------------------------------
# OntologyPipeline.passing_run_count
# ---------------------------------------------------------------------------

class TestPassingRunCount:
    def test_no_runs(self):
        p = _make_pipeline()
        assert p.passing_run_count() == 0

    def test_all_above(self):
        p = _make_pipeline()
        for v in [0.7, 0.8, 0.9]:
            _push_pipeline_run(p, v)
        assert p.passing_run_count(0.6) == 3

    def test_none_above(self):
        p = _make_pipeline()
        _push_pipeline_run(p, 0.3)
        _push_pipeline_run(p, 0.5)
        assert p.passing_run_count(0.6) == 0

    def test_exact_threshold_excluded(self):
        p = _make_pipeline()
        _push_pipeline_run(p, 0.6)
        _push_pipeline_run(p, 0.7)
        assert p.passing_run_count(0.6) == 1


# ---------------------------------------------------------------------------
# OntologyPipeline.run_summary
# ---------------------------------------------------------------------------

class TestRunSummary:
    def test_empty(self):
        p = _make_pipeline()
        s = p.run_summary()
        assert s["count"] == 0
        assert s["trend"] == []

    def test_basic(self):
        p = _make_pipeline()
        _push_pipeline_run(p, 0.5)
        _push_pipeline_run(p, 0.7)
        s = p.run_summary()
        assert s["count"] == 2
        assert s["mean"] == pytest.approx(0.6)
        assert s["min"] == pytest.approx(0.5)
        assert s["max"] == pytest.approx(0.7)
        assert len(s["trend"]) == 2

    def test_trend_order_preserved(self):
        p = _make_pipeline()
        scores = [0.4, 0.9, 0.6]
        for v in scores:
            _push_pipeline_run(p, v)
        assert p.run_summary()["trend"] == pytest.approx(scores)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.has_feedback
# ---------------------------------------------------------------------------

class TestHasFeedback:
    def test_no_feedback_false(self):
        a = _make_adapter()
        assert a.has_feedback() is False

    def test_after_feedback_true(self):
        a = _make_adapter()
        a.apply_feedback(0.7)
        assert a.has_feedback() is True


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.recent_feedback
# ---------------------------------------------------------------------------

class TestRecentFeedback:
    def test_empty_adapter(self):
        a = _make_adapter()
        assert a.recent_feedback() == []

    def test_returns_last_n(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
            a.apply_feedback(v)
        result = a.recent_feedback(3)
        assert len(result) == 3
        assert result[-1].final_score == pytest.approx(0.6)

    def test_n_larger_than_history(self):
        a = _make_adapter()
        a.apply_feedback(0.5)
        result = a.recent_feedback(10)
        assert len(result) == 1

    def test_n_zero_returns_empty(self):
        a = _make_adapter()
        a.apply_feedback(0.8)
        assert a.recent_feedback(0) == []


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_score_stats
# ---------------------------------------------------------------------------

class TestFeedbackScoreStats:
    def test_empty(self):
        a = _make_adapter()
        s = a.feedback_score_stats()
        assert s["count"] == 0
        assert s["mean"] == 0.0

    def test_single(self):
        a = _make_adapter()
        a.apply_feedback(0.8)
        s = a.feedback_score_stats()
        assert s["count"] == 1
        assert s["mean"] == pytest.approx(0.8)
        assert s["min"] == pytest.approx(0.8)
        assert s["max"] == pytest.approx(0.8)

    def test_std_nonzero(self):
        a = _make_adapter()
        a.apply_feedback(0.2)
        a.apply_feedback(0.8)
        s = a.feedback_score_stats()
        assert s["std"] > 0.0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_percentile
# ---------------------------------------------------------------------------

class TestFeedbackPercentile:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_percentile(50) == 0.0

    def test_median(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8]:
            a.apply_feedback(v)
        assert a.feedback_percentile(50) == pytest.approx(0.5)

    def test_p0_returns_min(self):
        a = _make_adapter()
        a.apply_feedback(0.3)
        a.apply_feedback(0.7)
        assert a.feedback_percentile(0) == pytest.approx(0.3)

    def test_p100_returns_max(self):
        a = _make_adapter()
        a.apply_feedback(0.3)
        a.apply_feedback(0.7)
        assert a.feedback_percentile(100) == pytest.approx(0.7)

    def test_raises_out_of_range(self):
        a = _make_adapter()
        with pytest.raises(ValueError):
            a.feedback_percentile(101)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.passing_feedback_fraction
# ---------------------------------------------------------------------------

class TestPassingFeedbackFraction:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.passing_feedback_fraction() == 0.0

    def test_all_passing(self):
        a = _make_adapter()
        a.apply_feedback(0.8)
        a.apply_feedback(0.9)
        assert a.passing_feedback_fraction(0.6) == pytest.approx(1.0)

    def test_none_passing(self):
        a = _make_adapter()
        a.apply_feedback(0.3)
        a.apply_feedback(0.4)
        assert a.passing_feedback_fraction(0.6) == pytest.approx(0.0)

    def test_half_passing(self):
        a = _make_adapter()
        a.apply_feedback(0.9)
        a.apply_feedback(0.3)
        assert a.passing_feedback_fraction(0.6) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# OntologyCritic.failing_scores
# ---------------------------------------------------------------------------

class TestFailingScores:
    def test_empty(self):
        c = _make_critic()
        assert c.failing_scores([]) == []

    def test_all_pass(self):
        c = _make_critic()
        s = _make_critic_score(0.8, 0.8, 0.8, 0.8, 0.8)
        result = c.failing_scores([s], threshold=0.5)
        assert result == []

    def test_all_fail(self):
        c = _make_critic()
        s = _make_critic_score(0.1, 0.1, 0.1, 0.1, 0.1)
        result = c.failing_scores([s], threshold=0.6)
        assert len(result) == 1

    def test_mixed(self):
        c = _make_critic()
        passing = _make_critic_score(0.9, 0.9, 0.9, 0.9, 0.9)
        failing = _make_critic_score(0.1, 0.1, 0.1, 0.1, 0.1)
        result = c.failing_scores([passing, failing], threshold=0.6)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# OntologyCritic.average_dimension
# ---------------------------------------------------------------------------

class TestAverageDimension:
    def test_empty_returns_zero(self):
        c = _make_critic()
        assert c.average_dimension([], "completeness") == 0.0

    def test_completeness(self):
        c = _make_critic()
        s1 = _make_critic_score(completeness=0.4)
        s2 = _make_critic_score(completeness=0.8)
        assert c.average_dimension([s1, s2], "completeness") == pytest.approx(0.6)

    def test_domain_alignment(self):
        c = _make_critic()
        s = _make_critic_score(domain_alignment=0.7)
        assert c.average_dimension([s], "domain_alignment") == pytest.approx(0.7)

    def test_invalid_dim_raises(self):
        c = _make_critic()
        s = _make_critic_score()
        with pytest.raises(AttributeError):
            c.average_dimension([s], "nonexistent_dim")


# ---------------------------------------------------------------------------
# OntologyCritic.score_summary
# ---------------------------------------------------------------------------

class TestScoreSummary:
    def test_empty(self):
        c = _make_critic()
        s = c.score_summary([])
        assert s["count"] == 0
        assert s["mean"] == 0.0
        assert s["passing_fraction"] == 0.0

    def test_single_score(self):
        c = _make_critic()
        score = _make_critic_score(0.9, 0.9, 0.9, 0.9, 0.9)
        s = c.score_summary([score])
        assert s["count"] == 1
        assert s["passing_fraction"] == pytest.approx(1.0)

    def test_all_keys_present(self):
        c = _make_critic()
        s = c.score_summary([_make_critic_score()])
        for key in ("count", "mean", "min", "max", "passing_fraction"):
            assert key in s

    def test_passing_fraction_half(self):
        c = _make_critic()
        high = _make_critic_score(0.9, 0.9, 0.9, 0.9, 0.9)
        low = _make_critic_score(0.1, 0.1, 0.1, 0.1, 0.1)
        s = c.score_summary([high, low])
        assert s["passing_fraction"] == pytest.approx(0.5)
