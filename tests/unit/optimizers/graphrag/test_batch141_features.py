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
    @pytest.mark.parametrize(
        "scores,window,tolerance,expected",
        [
            ([], 5, 0.01, False),
            ([0.5], 5, 0.01, False),
            ([0.7, 0.7, 0.7, 0.7], 5, 0.01, True),
            ([0.3, 0.9, 0.3, 0.9], 5, 0.01, False),
            ([0.700, 0.705], 2, 0.01, True),
        ],
    )
    def test_is_plateau_scenarios(self, scores, window, tolerance, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert p.is_plateau(window=window, tolerance=tolerance) is expected


# ---------------------------------------------------------------------------
# OntologyPipeline.peak_run_index
# ---------------------------------------------------------------------------

class TestPeakRunIndex:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], -1),
            ([0.6], 0),
            ([0.3, 0.9, 0.5], 1),
            ([0.1, 0.5, 0.8], 2),
        ],
    )
    def test_peak_run_index_scenarios(self, scores, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert p.peak_run_index() == expected

    def test_returns_int(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert isinstance(p.peak_run_index(), int)


# ---------------------------------------------------------------------------
# OntologyOptimizer.dominant_trend
# ---------------------------------------------------------------------------

class TestDominantTrend:
    @pytest.mark.parametrize(
        "entries,expected",
        [
            ([], "stable"),
            ([(0.5, "improving")], "improving"),
            ([(0.5, "improving"), (0.6, "improving"), (0.4, "declining")], "improving"),
        ],
    )
    def test_dominant_trend_scenarios(self, entries, expected):
        o = _make_optimizer()
        for score, trend in entries:
            _push_opt(o, score, trend)
        assert o.dominant_trend() == expected

    def test_returns_string(self):
        o = _make_optimizer()
        _push_opt(o, 0.5, "stable")
        assert isinstance(o.dominant_trend(), str)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_range
# ---------------------------------------------------------------------------

class TestHistoryRange:
    @pytest.mark.parametrize(
        "values,expected",
        [
            ([], 0.0),
            ([0.5], 0.0),
            ([0.2, 0.8], 0.6),
            ([0.5, 0.5, 0.5], 0.0),
        ],
    )
    def test_history_range_scenarios(self, values, expected):
        o = _make_optimizer()
        for v in values:
            _push_opt(o, v)
        assert o.history_range() == pytest.approx(expected)

    def test_non_negative(self):
        o = _make_optimizer()
        _push_opt(o, 0.9)
        _push_opt(o, 0.3)
        assert o.history_range() >= 0.0
