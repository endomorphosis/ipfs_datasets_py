"""Batch-141 feature tests.

Methods under test:
  - OntologyPipeline.is_plateau(window, tolerance)
  - OntologyPipeline.peak_run_index()
  - OntologyOptimizer.dominant_trend()
  - OntologyOptimizer.history_range()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, overall):
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    p._run_history.append(run)


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg, trend="stable"):
        self.average_score = avg
        self.trend = trend


def _push_opt(o, avg, trend="stable"):
    o._history.append(_FakeEntry(avg, trend))


# ---------------------------------------------------------------------------
# OntologyPipeline.is_plateau
# ---------------------------------------------------------------------------

class TestIsPlateau:
    def test_empty_returns_false(self):
        p = _make_pipeline()
        assert p.is_plateau() is False

    def test_single_run_returns_false(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.is_plateau() is False

    def test_stable_scores_plateau(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.7)
        assert p.is_plateau(tolerance=0.01) is True

    def test_volatile_scores_not_plateau(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.3, 0.9]:
            _push_run(p, v)
        assert p.is_plateau(tolerance=0.01) is False

    def test_within_tolerance(self):
        p = _make_pipeline()
        _push_run(p, 0.700)
        _push_run(p, 0.705)
        assert p.is_plateau(window=2, tolerance=0.01) is True


# ---------------------------------------------------------------------------
# OntologyPipeline.peak_run_index
# ---------------------------------------------------------------------------

class TestPeakRunIndex:
    def test_empty_returns_minus_one(self):
        p = _make_pipeline()
        assert p.peak_run_index() == -1

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.peak_run_index() == 0

    def test_peak_in_middle(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.5]:
            _push_run(p, v)
        assert p.peak_run_index() == 1

    def test_peak_at_end(self):
        p = _make_pipeline()
        for v in [0.1, 0.5, 0.8]:
            _push_run(p, v)
        assert p.peak_run_index() == 2

    def test_returns_int(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert isinstance(p.peak_run_index(), int)


# ---------------------------------------------------------------------------
# OntologyOptimizer.dominant_trend
# ---------------------------------------------------------------------------

class TestDominantTrend:
    def test_empty_returns_stable(self):
        o = _make_optimizer()
        assert o.dominant_trend() == "stable"

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.5, "improving")
        assert o.dominant_trend() == "improving"

    def test_majority_wins(self):
        o = _make_optimizer()
        _push_opt(o, 0.5, "improving")
        _push_opt(o, 0.6, "improving")
        _push_opt(o, 0.4, "declining")
        assert o.dominant_trend() == "improving"

    def test_returns_string(self):
        o = _make_optimizer()
        _push_opt(o, 0.5, "stable")
        assert isinstance(o.dominant_trend(), str)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_range
# ---------------------------------------------------------------------------

class TestHistoryRange:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_range() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_range() == pytest.approx(0.0)

    def test_known_range(self):
        o = _make_optimizer()
        _push_opt(o, 0.2)
        _push_opt(o, 0.8)
        assert o.history_range() == pytest.approx(0.6)

    def test_all_same_range_zero(self):
        o = _make_optimizer()
        for _ in range(3):
            _push_opt(o, 0.5)
        assert o.history_range() == pytest.approx(0.0)

    def test_non_negative(self):
        o = _make_optimizer()
        _push_opt(o, 0.9)
        _push_opt(o, 0.3)
        assert o.history_range() >= 0.0
