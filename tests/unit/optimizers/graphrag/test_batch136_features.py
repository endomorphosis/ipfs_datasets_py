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
    def test_empty_returns_empty(self):
        c = _make_critic()
        assert c.top_k_scores([]) == []

    def test_returns_sorted_desc(self):
        c = _make_critic()
        scores = [_cs(0.3), _cs(0.9), _cs(0.6)]
        result = c.top_k_scores(scores, k=2)
        assert len(result) == 2
        assert result[0].overall == pytest.approx(0.9)
        assert result[1].overall == pytest.approx(0.6)

    def test_k_larger_than_list(self):
        c = _make_critic()
        scores = [_cs(0.4), _cs(0.8)]
        assert len(c.top_k_scores(scores, k=10)) == 2

    def test_default_k_is_three(self):
        c = _make_critic()
        scores = [_cs(v) for v in [0.1, 0.2, 0.3, 0.4, 0.5]]
        assert len(c.top_k_scores(scores)) == 3


# ---------------------------------------------------------------------------
# OntologyCritic.below_threshold_count
# ---------------------------------------------------------------------------

class TestBelowThresholdCount:
    def test_empty(self):
        c = _make_critic()
        assert c.below_threshold_count([]) == 0

    def test_all_above(self):
        c = _make_critic()
        assert c.below_threshold_count([_cs(0.8), _cs(0.9)], threshold=0.5) == 0

    def test_all_below(self):
        c = _make_critic()
        assert c.below_threshold_count([_cs(0.1), _cs(0.2)], threshold=0.5) == 2

    def test_strict_lt(self):
        """Exactly at threshold should NOT count."""
        c = _make_critic()
        assert c.below_threshold_count([_cs(0.5)], threshold=0.5) == 0

    def test_mixed(self):
        c = _make_critic()
        scores = [_cs(0.3), _cs(0.5), _cs(0.7), _cs(0.2)]
        assert c.below_threshold_count(scores, threshold=0.5) == 2


# ---------------------------------------------------------------------------
# OntologyCritic.average_dimension
# ---------------------------------------------------------------------------

class TestAverageDimension:
    def test_empty_returns_zero(self):
        c = _make_critic()
        assert c.average_dimension([], "coherence") == 0.0

    def test_single(self):
        c = _make_critic()
        assert c.average_dimension([_cs(0.5, coherence=0.8)], "coherence") == pytest.approx(0.8)

    def test_multiple(self):
        c = _make_critic()
        scores = [_cs(0.5, completeness=0.4), _cs(0.6, completeness=0.6)]
        assert c.average_dimension(scores, "completeness") == pytest.approx(0.5)

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
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_streak() == 0

    def test_all_pass(self):
        a = _make_adapter()
        _push_adapter(a, 0.7, 0.8, 0.9)
        assert a.feedback_streak(threshold=0.6) == 3

    def test_streak_breaks(self):
        a = _make_adapter()
        _push_adapter(a, 0.3, 0.8, 0.9)
        assert a.feedback_streak(threshold=0.6) == 2

    def test_latest_below_returns_zero(self):
        a = _make_adapter()
        _push_adapter(a, 0.8, 0.3)
        assert a.feedback_streak(threshold=0.6) == 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_percentile
# ---------------------------------------------------------------------------

class TestFeedbackPercentile:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_percentile(50) == pytest.approx(0.0)

    def test_median(self):
        a = _make_adapter()
        _push_adapter(a, 0.2, 0.5, 0.8)
        assert a.feedback_percentile(50) == pytest.approx(0.5)

    def test_p0_returns_min(self):
        a = _make_adapter()
        _push_adapter(a, 0.3, 0.7)
        assert a.feedback_percentile(0) == pytest.approx(0.3)

    def test_returns_float(self):
        a = _make_adapter()
        _push_adapter(a, 0.5)
        assert isinstance(a.feedback_percentile(50), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.recent_average
# ---------------------------------------------------------------------------

class TestRecentAverage:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.recent_average() == pytest.approx(0.0)

    def test_all_within_window(self):
        a = _make_adapter()
        _push_adapter(a, 0.4, 0.6)
        assert a.recent_average(n=5) == pytest.approx(0.5)

    def test_window_limits(self):
        a = _make_adapter()
        _push_adapter(a, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9)
        # n=3 should average last 3 → 0.9
        assert a.recent_average(n=3) == pytest.approx(0.9)

    def test_single_record(self):
        a = _make_adapter()
        _push_adapter(a, 0.75)
        assert a.recent_average() == pytest.approx(0.75)
