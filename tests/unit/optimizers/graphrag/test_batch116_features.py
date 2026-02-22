"""Batch-116 feature tests.

Methods under test:
  - OntologyMediator.apply_action_bulk(actions)
  - OntologyLearningAdapter.score_range()
  - OntologyLearningAdapter.feedback_count_above(threshold)
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


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    adapter.apply_feedback(score)


# ---------------------------------------------------------------------------
# OntologyMediator.apply_action_bulk
# ---------------------------------------------------------------------------

class TestApplyActionBulk:
    def test_empty_list(self):
        m = _make_mediator()
        result = m.apply_action_bulk([])
        assert result == 0

    def test_returns_count(self):
        m = _make_mediator()
        assert m.apply_action_bulk(["a", "b", "c"]) == 3

    def test_counts_recorded(self):
        m = _make_mediator()
        m.apply_action_bulk(["add_entity", "add_entity", "remove_rel"])
        stats = m.get_action_stats()
        assert stats.get("add_entity", 0) == 2
        assert stats.get("remove_rel", 0) == 1

    def test_increments_existing(self):
        m = _make_mediator()
        m.apply_action_bulk(["x"])
        m.apply_action_bulk(["x", "x"])
        assert m.get_action_stats()["x"] == 3

    def test_reflects_in_total_action_count(self):
        m = _make_mediator()
        m.apply_action_bulk(["a", "b"])
        # total_action_count sums all action counts
        total = m.total_action_count()
        assert total >= 2


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.score_range
# ---------------------------------------------------------------------------

class TestScoreRange:
    def test_no_feedback_zero_range(self):
        a = _make_adapter()
        lo, hi = a.score_range()
        assert lo == 0.0 and hi == 0.0

    def test_single_feedback(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        lo, hi = a.score_range()
        assert lo == pytest.approx(0.7)
        assert hi == pytest.approx(0.7)

    def test_multiple_feedback(self):
        a = _make_adapter()
        for v in [0.4, 0.9, 0.6]:
            _push_feedback(a, v)
        lo, hi = a.score_range()
        assert lo == pytest.approx(0.4)
        assert hi == pytest.approx(0.9)

    def test_matches_feedback_score_range(self):
        a = _make_adapter()
        for v in [0.3, 0.8]:
            _push_feedback(a, v)
        assert a.score_range() == a.feedback_score_range()


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_count_above
# ---------------------------------------------------------------------------

class TestFeedbackCountAbove:
    def test_no_feedback(self):
        a = _make_adapter()
        assert a.feedback_count_above() == 0

    def test_all_above(self):
        a = _make_adapter()
        for v in [0.7, 0.8, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_count_above(0.6) == 3

    def test_none_above(self):
        a = _make_adapter()
        for v in [0.1, 0.2]:
            _push_feedback(a, v)
        assert a.feedback_count_above(0.6) == 0

    def test_partial(self):
        a = _make_adapter()
        for v in [0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_count_above(0.6) == 2

    def test_custom_threshold(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_count_above(0.4) == 2
