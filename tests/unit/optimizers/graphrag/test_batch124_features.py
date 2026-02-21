"""Batch-124 feature tests.

Methods under test:
  - OntologyOptimizer.history_slice(start, end)
  - OntologyOptimizer.score_above_count(threshold)
  - OntologyOptimizer.first_entry_above(threshold)
  - OntologyOptimizer.last_entry_above(threshold)
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
# OntologyOptimizer.history_slice
# ---------------------------------------------------------------------------

class TestHistorySlice:
    def test_empty(self):
        o = _make_optimizer()
        assert o.history_slice(0, 5) == []

    def test_full_slice(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5]:
            _push(o, v)
        slc = o.history_slice(0, 5)
        assert len(slc) == 5

    def test_partial_slice(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3]:
            _push(o, v)
        slc = o.history_slice(1, 3)
        assert len(slc) == 2
        assert slc[0].average_score == pytest.approx(0.2)

    def test_empty_range(self):
        o = _make_optimizer()
        _push(o, 0.5)
        assert o.history_slice(2, 5) == []


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_above_count
# ---------------------------------------------------------------------------

class TestScoreAboveCount:
    def test_empty(self):
        o = _make_optimizer()
        assert o.score_above_count(0.5) == 0

    def test_all_above(self):
        o = _make_optimizer()
        for v in [0.7, 0.8, 0.9]:
            _push(o, v)
        assert o.score_above_count(0.6) == 3

    def test_none_above(self):
        o = _make_optimizer()
        for v in [0.1, 0.2]:
            _push(o, v)
        assert o.score_above_count(0.6) == 0

    def test_partial(self):
        o = _make_optimizer()
        for v in [0.4, 0.7, 0.9]:
            _push(o, v)
        assert o.score_above_count(0.6) == 2


# ---------------------------------------------------------------------------
# OntologyOptimizer.first_entry_above
# ---------------------------------------------------------------------------

class TestFirstEntryAbove:
    def test_empty_returns_none(self):
        o = _make_optimizer()
        assert o.first_entry_above(0.5) is None

    def test_no_match_returns_none(self):
        o = _make_optimizer()
        for v in [0.1, 0.2]:
            _push(o, v)
        assert o.first_entry_above(0.5) is None

    def test_returns_first(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.9]:
            _push(o, v)
        entry = o.first_entry_above(0.6)
        assert entry.average_score == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# OntologyOptimizer.last_entry_above
# ---------------------------------------------------------------------------

class TestLastEntryAbove:
    def test_empty_returns_none(self):
        o = _make_optimizer()
        assert o.last_entry_above(0.5) is None

    def test_no_match_returns_none(self):
        o = _make_optimizer()
        for v in [0.1, 0.2]:
            _push(o, v)
        assert o.last_entry_above(0.5) is None

    def test_returns_last(self):
        o = _make_optimizer()
        for v in [0.7, 0.8, 0.3]:
            _push(o, v)
        entry = o.last_entry_above(0.6)
        assert entry.average_score == pytest.approx(0.8)

    def test_only_one_above(self):
        o = _make_optimizer()
        for v in [0.3, 0.9, 0.2]:
            _push(o, v)
        entry = o.last_entry_above(0.7)
        assert entry.average_score == pytest.approx(0.9)
