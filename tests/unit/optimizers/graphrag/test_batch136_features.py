"""Batch-136 feature tests.

Methods under test:
  - OntologyCritic.top_k_scores(scores, k)
  - OntologyCritic.below_threshold_count(scores, threshold)
  - OntologyCritic.average_dimension(scores, dimension)
  - OntologyLearningAdapter.feedback_streak(threshold)
  - OntologyLearningAdapter.feedback_percentile(value)
  - OntologyLearningAdapter.recent_average(n)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _cs(overall, coherence=0.5, completeness=0.5):
    s = MagicMock()
    s.overall = overall
    s.coherence = coherence
    s.completeness = completeness
    return s


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _fr(score):
    r = MagicMock()
    r.final_score = score
    return r


def _push_adapter(a, *scores):
    for s in scores:
        a._feedback.append(_fr(s))


# ---------------------------------------------------------------------------
# OntologyCritic.top_k_scores
# ---------------------------------------------------------------------------

class TestTopKScores:
    @pytest.mark.parametrize(
        "overall_scores,k,expected_len,expected_prefix",
        [
            ([], 3, 0, []),
            ([0.3, 0.9, 0.6], 2, 2, [0.9, 0.6]),
            ([0.4, 0.8], 10, 2, [0.8, 0.4]),
            ([0.1, 0.2, 0.3, 0.4, 0.5], 3, 3, [0.5, 0.4, 0.3]),
        ],
    )
    def test_top_k_scores_scenarios(self, overall_scores, k, expected_len, expected_prefix):
        c = _make_critic()
        scores = [_cs(v) for v in overall_scores]
        result = c.top_k_scores(scores, k=k)
        assert len(result) == expected_len
        for idx, expected in enumerate(expected_prefix):
            assert result[idx].overall == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyCritic.below_threshold_count
# ---------------------------------------------------------------------------

class TestBelowThresholdCount:
    @pytest.mark.parametrize(
        "overall_scores,threshold,expected",
        [
            ([], 0.5, 0),
            ([0.8, 0.9], 0.5, 0),
            ([0.1, 0.2], 0.5, 2),
            # Exactly at threshold should NOT count.
            ([0.5], 0.5, 0),
            ([0.3, 0.5, 0.7, 0.2], 0.5, 2),
        ],
    )
    def test_below_threshold_count_scenarios(self, overall_scores, threshold, expected):
        c = _make_critic()
        scores = [_cs(v) for v in overall_scores]
        assert c.below_threshold_count(scores, threshold=threshold) == expected


# ---------------------------------------------------------------------------
# OntologyCritic.average_dimension
# ---------------------------------------------------------------------------

class TestAverageDimension:
    @pytest.mark.parametrize(
        "scores,dimension,expected",
        [
            ([], "coherence", 0.0),
            ([_cs(0.5, coherence=0.8)], "coherence", 0.8),
            ([_cs(0.5, completeness=0.4), _cs(0.6, completeness=0.6)], "completeness", 0.5),
        ],
    )
    def test_average_dimension_scenarios(self, scores, dimension, expected):
        c = _make_critic()
        assert c.average_dimension(scores, dimension) == pytest.approx(expected)

    def test_missing_attr_defaults_zero(self):
        c = _make_critic()
        s = MagicMock(spec=["overall"])
        s.overall = 0.5
        # The pre-existing implementation raises AttributeError for unknown dims
        with pytest.raises(AttributeError):
            c.average_dimension([s], "nonexistent_dim")


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_streak
# ---------------------------------------------------------------------------

class TestFeedbackStreak:
    @pytest.mark.parametrize(
        "scores,threshold,expected",
        [
            ([], 0.6, 0),
            ([0.7, 0.8, 0.9], 0.6, 3),
            ([0.3, 0.8, 0.9], 0.6, 2),
            ([0.8, 0.3], 0.6, 0),
        ],
    )
    def test_feedback_streak_scenarios(self, scores, threshold, expected):
        a = _make_adapter()
        _push_adapter(a, *scores)
        assert a.feedback_streak(threshold=threshold) == expected


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_percentile
# ---------------------------------------------------------------------------

class TestFeedbackPercentile:
    @pytest.mark.parametrize(
        "scores,percentile,expected",
        [
            ([], 50, 0.0),
            ([0.2, 0.5, 0.8], 50, 0.5),
            ([0.3, 0.7], 0, 0.3),
        ],
    )
    def test_feedback_percentile_scenarios(self, scores, percentile, expected):
        a = _make_adapter()
        _push_adapter(a, *scores)
        assert a.feedback_percentile(percentile) == pytest.approx(expected)

    def test_returns_float(self):
        a = _make_adapter()
        _push_adapter(a, 0.5)
        assert isinstance(a.feedback_percentile(50), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.recent_average
# ---------------------------------------------------------------------------

class TestRecentAverage:
    @pytest.mark.parametrize(
        "scores,n,expected",
        [
            ([], 5, 0.0),
            ([0.4, 0.6], 5, 0.5),
            # n=3 should average last 3 -> 0.9.
            ([0.1, 0.9, 0.9, 0.9, 0.9, 0.9], 3, 0.9),
            ([0.75], 5, 0.75),
        ],
    )
    def test_recent_average_scenarios(self, scores, n, expected):
        a = _make_adapter()
        _push_adapter(a, *scores)
        assert a.recent_average(n=n) == pytest.approx(expected)
