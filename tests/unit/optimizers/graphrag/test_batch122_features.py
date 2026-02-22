"""Batch-122 feature tests.

Methods under test:
  - OntologyMediator.action_frequency()
  - OntologyMediator.has_actions()
  - OntologyMediator.action_diversity()
  - OntologyLearningAdapter.all_feedback_above(threshold)
  - OntologyLearningAdapter.feedback_scores()
  - OntologyLearningAdapter.domain_threshold_delta()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    critic = MagicMock()
    return OntologyMediator(generator=gen, critic=critic)


def _make_adapter(base_threshold=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter(base_threshold=base_threshold)


def _push_feedback(adapter, score):
    adapter.apply_feedback(score)


# ---------------------------------------------------------------------------
# OntologyMediator.action_frequency
# ---------------------------------------------------------------------------

class TestActionFrequency:
    def test_empty(self):
        m = _make_mediator()
        assert m.action_frequency() == {}

    def test_single_action(self):
        m = _make_mediator()
        m.apply_action_bulk(["a", "a", "a"])
        freq = m.action_frequency()
        assert freq["a"] == pytest.approx(1.0)

    def test_multiple_actions_sum_to_one(self):
        m = _make_mediator()
        m.apply_action_bulk(["a", "b", "c", "a"])
        freq = m.action_frequency()
        assert sum(freq.values()) == pytest.approx(1.0)

    def test_proportions(self):
        m = _make_mediator()
        m.apply_action_bulk(["x", "x", "y"])
        freq = m.action_frequency()
        assert freq["x"] == pytest.approx(2.0 / 3.0)
        assert freq["y"] == pytest.approx(1.0 / 3.0)


# ---------------------------------------------------------------------------
# OntologyMediator.has_actions
# ---------------------------------------------------------------------------

class TestHasActions:
    def test_empty_is_false(self):
        m = _make_mediator()
        assert m.has_actions() is False

    def test_after_bulk_is_true(self):
        m = _make_mediator()
        m.apply_action_bulk(["a"])
        assert m.has_actions() is True

    def test_after_reset_is_false(self):
        m = _make_mediator()
        m.apply_action_bulk(["a"])
        m.reset_action_counts()
        assert m.has_actions() is False


# ---------------------------------------------------------------------------
# OntologyMediator.action_diversity
# ---------------------------------------------------------------------------

class TestActionDiversity:
    def test_empty_is_zero(self):
        m = _make_mediator()
        assert m.action_diversity() == 0

    def test_single_type(self):
        m = _make_mediator()
        m.apply_action_bulk(["a", "a"])
        assert m.action_diversity() == 1

    def test_multiple_types(self):
        m = _make_mediator()
        m.apply_action_bulk(["a", "b", "c"])
        assert m.action_diversity() == 3


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.all_feedback_above
# ---------------------------------------------------------------------------

class TestAllFeedbackAbove:
    def test_empty_is_true(self):
        a = _make_adapter()
        assert a.all_feedback_above() is True

    def test_all_above(self):
        a = _make_adapter()
        for v in [0.7, 0.8, 0.9]:
            _push_feedback(a, v)
        assert a.all_feedback_above(0.6) is True

    def test_one_below(self):
        a = _make_adapter()
        _push_feedback(a, 0.8)
        _push_feedback(a, 0.4)
        assert a.all_feedback_above(0.6) is False


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_scores
# ---------------------------------------------------------------------------

class TestFeedbackScores:
    def test_empty(self):
        a = _make_adapter()
        assert a.feedback_scores() == []

    def test_returns_in_order(self):
        a = _make_adapter()
        vals = [0.3, 0.7, 0.5]
        for v in vals:
            _push_feedback(a, v)
        scores = a.feedback_scores()
        assert len(scores) == 3
        assert scores[0] == pytest.approx(0.3)

    def test_returns_list(self):
        a = _make_adapter()
        _push_feedback(a, 0.6)
        assert isinstance(a.feedback_scores(), list)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.domain_threshold_delta
# ---------------------------------------------------------------------------

class TestDomainThresholdDelta:
    def test_no_feedback_is_zero(self):
        a = _make_adapter(base_threshold=0.5)
        assert a.domain_threshold_delta() == pytest.approx(0.0)

    def test_after_adjustment_nonzero(self):
        a = _make_adapter(base_threshold=0.5)
        # Add enough feedback to trigger adjustment (min_samples=3 by default)
        for v in [0.9, 0.9, 0.9, 0.9, 0.9]:
            _push_feedback(a, v)
        # Threshold adjusts based on feedback; delta should be non-zero
        assert a.domain_threshold_delta() != pytest.approx(0.0)
