"""Batch-126 feature tests.

Methods under test:
  - OntologyLearningAdapter.best_feedback_score()
  - OntologyLearningAdapter.worst_feedback_score()
  - OntologyLearningAdapter.average_feedback_score()
  - OntologyLearningAdapter.feedback_above_fraction(threshold)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push(adapter, score):
    adapter.apply_feedback(score)


# ---------------------------------------------------------------------------
# best_feedback_score
# ---------------------------------------------------------------------------

class TestBestFeedbackScore:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.best_feedback_score() == 0.0

    def test_single(self):
        a = _make_adapter()
        _push(a, 0.7)
        assert a.best_feedback_score() == pytest.approx(0.7)

    def test_multiple(self):
        a = _make_adapter()
        for v in [0.3, 0.9, 0.6]:
            _push(a, v)
        assert a.best_feedback_score() == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# worst_feedback_score
# ---------------------------------------------------------------------------

class TestWorstFeedbackScore:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.worst_feedback_score() == 0.0

    def test_single(self):
        a = _make_adapter()
        _push(a, 0.4)
        assert a.worst_feedback_score() == pytest.approx(0.4)

    def test_multiple(self):
        a = _make_adapter()
        for v in [0.3, 0.9, 0.6]:
            _push(a, v)
        assert a.worst_feedback_score() == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# average_feedback_score
# ---------------------------------------------------------------------------

class TestAverageFeedbackScore:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.average_feedback_score() == 0.0

    def test_single(self):
        a = _make_adapter()
        _push(a, 0.6)
        assert a.average_feedback_score() == pytest.approx(0.6)

    def test_multiple(self):
        a = _make_adapter()
        for v in [0.4, 0.6, 0.8]:
            _push(a, v)
        assert a.average_feedback_score() == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# feedback_above_fraction
# ---------------------------------------------------------------------------

class TestFeedbackAboveFraction:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_above_fraction() == 0.0

    def test_all_above(self):
        a = _make_adapter()
        for v in [0.7, 0.8, 0.9]:
            _push(a, v)
        assert a.feedback_above_fraction(0.6) == pytest.approx(1.0)

    def test_none_above(self):
        a = _make_adapter()
        for v in [0.1, 0.2]:
            _push(a, v)
        assert a.feedback_above_fraction(0.6) == pytest.approx(0.0)

    def test_partial(self):
        a = _make_adapter()
        for v in [0.3, 0.7, 0.9]:
            _push(a, v)
        assert a.feedback_above_fraction(0.6) == pytest.approx(2.0 / 3.0)

    def test_exactly_at_threshold_not_counted(self):
        a = _make_adapter()
        _push(a, 0.6)
        assert a.feedback_above_fraction(0.6) == 0.0
