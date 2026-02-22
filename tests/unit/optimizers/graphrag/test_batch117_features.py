"""Batch-117 feature tests.

Methods under test:
  - OntologyOptimizer.best_streak()
  - OntologyOptimizer.worst_streak()
  - OntologyOptimizer.score_percentile_rank(score)
  - OntologyOptimizer.score_momentum(window)
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
# OntologyOptimizer.best_streak
# ---------------------------------------------------------------------------

class TestBestStreak:
    def test_empty(self):
        o = _make_optimizer()
        assert o.best_streak() == 0

    def test_single_entry(self):
        o = _make_optimizer()
        _push(o, 0.5)
        assert o.best_streak() == 0

    def test_all_improving(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7]:
            _push(o, v)
        assert o.best_streak() == 3

    def test_all_declining(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push(o, v)
        assert o.best_streak() == 0

    def test_mixed(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.3, 0.6, 0.8, 0.7]:
            _push(o, v)
        # streaks: +1, -1, +1, +1, -1 → best=2
        assert o.best_streak() == 2


# ---------------------------------------------------------------------------
# OntologyOptimizer.worst_streak
# ---------------------------------------------------------------------------

class TestWorstStreak:
    def test_empty(self):
        o = _make_optimizer()
        assert o.worst_streak() == 0

    def test_all_declining(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push(o, v)
        assert o.worst_streak() == 3

    def test_all_improving(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push(o, v)
        assert o.worst_streak() == 0

    def test_mixed(self):
        o = _make_optimizer()
        for v in [0.8, 0.6, 0.4, 0.5, 0.7]:
            _push(o, v)
        assert o.worst_streak() == 2


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_percentile_rank
# ---------------------------------------------------------------------------

class TestScorePercentileRank:
    def test_empty(self):
        o = _make_optimizer()
        assert o.score_percentile_rank(0.5) == 0.0

    def test_above_all(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6]:
            _push(o, v)
        rank = o.score_percentile_rank(0.9)
        assert rank == pytest.approx(100.0)

    def test_below_all(self):
        o = _make_optimizer()
        for v in [0.4, 0.6, 0.8]:
            _push(o, v)
        rank = o.score_percentile_rank(0.1)
        assert rank == pytest.approx(0.0)

    def test_median_value(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push(o, v)
        rank = o.score_percentile_rank(0.5)
        assert 33.0 < rank <= 67.0


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_momentum
# ---------------------------------------------------------------------------

class TestScoreMomentum:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_momentum() == 0.0

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push(o, 0.5)
        assert o.score_momentum() == 0.0

    def test_improving(self):
        o = _make_optimizer()
        _push(o, 0.3)
        _push(o, 0.7)
        assert o.score_momentum() > 0.0

    def test_declining(self):
        o = _make_optimizer()
        _push(o, 0.9)
        _push(o, 0.5)
        assert o.score_momentum() < 0.0

    def test_flat(self):
        o = _make_optimizer()
        _push(o, 0.6)
        _push(o, 0.6)
        assert o.score_momentum() == pytest.approx(0.0)

    def test_window_limits_entries(self):
        o = _make_optimizer()
        for v in [0.9, 0.1, 0.3, 0.5]:
            _push(o, v)
        # last 2 entries: 0.3→0.5 = improving
        assert o.score_momentum(window=2) > 0.0
