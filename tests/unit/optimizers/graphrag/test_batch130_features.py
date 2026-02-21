"""Batch-130 feature tests.

Methods under test:
  - OntologyOptimizer.score_at_index(index)
  - OntologyOptimizer.improvement_from_start()
  - OntologyOptimizer.is_improving_overall()
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"
        self.best_ontology = {}
        self.worst_ontology = {}
        self.metadata = {}


def _push(opt, avg):
    opt._history.append(_FakeEntry(avg))


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_at_index
# ---------------------------------------------------------------------------

class TestScoreAtIndex:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_at_index(0) == 0.0

    def test_first_entry(self):
        o = _make_optimizer()
        _push(o, 0.3)
        _push(o, 0.7)
        assert o.score_at_index(0) == pytest.approx(0.3)

    def test_last_entry_negative_index(self):
        o = _make_optimizer()
        _push(o, 0.3)
        _push(o, 0.7)
        assert o.score_at_index(-1) == pytest.approx(0.7)

    def test_out_of_range_returns_zero(self):
        o = _make_optimizer()
        _push(o, 0.5)
        assert o.score_at_index(99) == 0.0


# ---------------------------------------------------------------------------
# OntologyOptimizer.improvement_from_start
# ---------------------------------------------------------------------------

class TestImprovementFromStart:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.improvement_from_start() == 0.0

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push(o, 0.5)
        assert o.improvement_from_start() == 0.0

    def test_positive_improvement(self):
        o = _make_optimizer()
        _push(o, 0.3)
        _push(o, 0.8)
        assert o.improvement_from_start() == pytest.approx(0.5)

    def test_negative_improvement(self):
        o = _make_optimizer()
        _push(o, 0.9)
        _push(o, 0.4)
        assert o.improvement_from_start() == pytest.approx(-0.5)

    def test_uses_first_and_last(self):
        o = _make_optimizer()
        for v in [0.2, 0.8, 0.5, 0.9]:
            _push(o, v)
        assert o.improvement_from_start() == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# OntologyOptimizer.is_improving_overall
# ---------------------------------------------------------------------------

class TestIsImprovingOverall:
    def test_empty_is_false(self):
        o = _make_optimizer()
        assert o.is_improving_overall() is False

    def test_single_is_false(self):
        o = _make_optimizer()
        _push(o, 0.5)
        assert o.is_improving_overall() is False

    def test_improving(self):
        o = _make_optimizer()
        _push(o, 0.3)
        _push(o, 0.7)
        assert o.is_improving_overall() is True

    def test_declining(self):
        o = _make_optimizer()
        _push(o, 0.8)
        _push(o, 0.4)
        assert o.is_improving_overall() is False

    def test_equal_is_false(self):
        o = _make_optimizer()
        _push(o, 0.5)
        _push(o, 0.5)
        assert o.is_improving_overall() is False
