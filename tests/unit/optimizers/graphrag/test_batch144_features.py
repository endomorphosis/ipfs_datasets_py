"""Batch-144 feature tests.

Methods under test:
  - OntologyPipeline.score_ewma(alpha)
  - OntologyPipeline.trend_slope()
  - OntologyOptimizer.min_score()
  - OntologyOptimizer.max_score()
  - OntologyOptimizer.median_score()
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
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


# ---------------------------------------------------------------------------
# OntologyPipeline.score_ewma
# ---------------------------------------------------------------------------

class TestScoreEwma:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.score_ewma() == []

    def test_single_run_equal(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        result = p.score_ewma()
        assert len(result) == 1
        assert result[0] == pytest.approx(0.6)

    def test_same_length_as_history(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        result = p.score_ewma(alpha=0.3)
        assert len(result) == 3

    def test_first_element_is_first_score(self):
        p = _make_pipeline()
        _push_run(p, 0.4)
        _push_run(p, 0.8)
        result = p.score_ewma(alpha=0.5)
        assert result[0] == pytest.approx(0.4)

    def test_ewma_smooths_values(self):
        p = _make_pipeline()
        _push_run(p, 0.0)
        _push_run(p, 1.0)
        result = p.score_ewma(alpha=0.5)
        # ewma[1] = 0.5 * 1.0 + 0.5 * 0.0 = 0.5
        assert result[1] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# OntologyPipeline.trend_slope
# ---------------------------------------------------------------------------

class TestTrendSlope:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.trend_slope() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.trend_slope() == pytest.approx(0.0)

    def test_positive_slope(self):
        p = _make_pipeline()
        for v in [0.1, 0.5, 0.9]:
            _push_run(p, v)
        assert p.trend_slope() > 0.0

    def test_negative_slope(self):
        p = _make_pipeline()
        for v in [0.9, 0.5, 0.1]:
            _push_run(p, v)
        assert p.trend_slope() < 0.0

    def test_flat_returns_zero(self):
        p = _make_pipeline()
        for _ in range(3):
            _push_run(p, 0.5)
        assert p.trend_slope() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyOptimizer.min_score
# ---------------------------------------------------------------------------

class TestMinScore:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.min_score() == pytest.approx(0.0)

    def test_known_min(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.min_score() == pytest.approx(0.3)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        assert o.min_score() == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# OntologyOptimizer.max_score
# ---------------------------------------------------------------------------

class TestMaxScore:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.max_score() == pytest.approx(0.0)

    def test_known_max(self):
        o = _make_optimizer()
        for v in [0.3, 0.9, 0.5]:
            _push_opt(o, v)
        assert o.max_score() == pytest.approx(0.9)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.4)
        assert o.max_score() == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# OntologyOptimizer.median_score
# ---------------------------------------------------------------------------

class TestOptimizerMedianScore:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.median_score() == pytest.approx(0.0)

    def test_odd_count(self):
        o = _make_optimizer()
        for v in [0.2, 0.6, 0.9]:
            _push_opt(o, v)
        assert o.median_score() == pytest.approx(0.6)

    def test_even_count(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.median_score() == pytest.approx(0.5)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.75)
        assert o.median_score() == pytest.approx(0.75)
