"""Batch-163 feature tests.

Methods under test:
  - OntologyLearningAdapter.feedback_last_n(n)
  - OntologyLearningAdapter.feedback_top_n(n)
  - OntologyOptimizer.history_change_count()
  - LogicValidator.path_exists(ontology, source, target)
"""
import pytest
from unittest.mock import MagicMock


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _ont(entities, rels):
    return {"entities": entities, "relationships": rels}


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_last_n
# ---------------------------------------------------------------------------

class TestFeedbackLastN:
    def test_empty(self):
        a = _make_adapter()
        assert a.feedback_last_n(3) == []

    def test_fewer_than_n(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        result = a.feedback_last_n(5)
        assert len(result) == 1

    def test_exactly_n(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7]:
            _push_feedback(a, v)
        result = a.feedback_last_n(3)
        assert len(result) == 3

    def test_more_than_n(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.8, 0.9]:
            _push_feedback(a, v)
        result = a.feedback_last_n(2)
        assert len(result) == 2
        scores = [r.final_score for r in result]
        assert scores == pytest.approx([0.8, 0.9])

    def test_n_zero_returns_empty(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_last_n(0) == []


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_top_n
# ---------------------------------------------------------------------------

class TestFeedbackTopN:
    def test_empty(self):
        a = _make_adapter()
        assert a.feedback_top_n(3) == []

    def test_top_one(self):
        a = _make_adapter()
        for v in [0.3, 0.9, 0.5]:
            _push_feedback(a, v)
        result = a.feedback_top_n(1)
        assert len(result) == 1
        assert result[0].final_score == pytest.approx(0.9)

    def test_sorted_descending(self):
        a = _make_adapter()
        for v in [0.4, 0.8, 0.2, 0.7]:
            _push_feedback(a, v)
        result = a.feedback_top_n(4)
        scores = [r.final_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_fewer_than_n(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        result = a.feedback_top_n(10)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_change_count
# ---------------------------------------------------------------------------

class TestHistoryChangeCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_change_count() == 0

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.history_change_count() == 0

    def test_monotone_increasing_no_changes(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.history_change_count() == 0

    def test_zigzag(self):
        o = _make_optimizer()
        for v in [0.3, 0.8, 0.2, 0.9]:
            _push_opt(o, v)
        assert o.history_change_count() == 2

    def test_single_change(self):
        o = _make_optimizer()
        for v in [0.5, 0.8, 0.3]:
            _push_opt(o, v)
        assert o.history_change_count() == 1


# ---------------------------------------------------------------------------
# LogicValidator.path_exists
# ---------------------------------------------------------------------------

class TestPathExists:
    def test_same_source_and_target(self):
        v = _make_validator()
        ont = _ont([], [])
        assert v.path_exists(ont, "a", "a") is True

    def test_direct_edge(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}],
            [{"source": "a", "target": "b", "type": "rel"}],
        )
        assert v.path_exists(ont, "a", "b") is True

    def test_no_path(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}],
            [],
        )
        assert v.path_exists(ont, "a", "b") is False

    def test_multi_hop_path(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            [
                {"source": "a", "target": "b", "type": "rel"},
                {"source": "b", "target": "c", "type": "rel"},
            ],
        )
        assert v.path_exists(ont, "a", "c") is True

    def test_directed_not_reverse(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}],
            [{"source": "a", "target": "b", "type": "rel"}],
        )
        assert v.path_exists(ont, "b", "a") is False
