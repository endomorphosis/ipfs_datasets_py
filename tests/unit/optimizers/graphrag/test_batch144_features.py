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
    @pytest.mark.parametrize(
        "scores,alpha,expected_len,expected_idx,expected",
        [
            ([], 0.3, 0, None, None),
            ([0.6], 0.3, 1, 0, 0.6),
            ([0.3, 0.5, 0.7], 0.3, 3, None, None),
            ([0.4, 0.8], 0.5, 2, 0, 0.4),
            # ewma[1] = 0.5 * 1.0 + 0.5 * 0.0 = 0.5
            ([0.0, 1.0], 0.5, 2, 1, 0.5),
        ],
    )
    def test_score_ewma_scenarios(self, scores, alpha, expected_len, expected_idx, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        result = p.score_ewma(alpha=alpha)
        assert len(result) == expected_len
        if expected_idx is not None:
            assert result[expected_idx] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyPipeline.trend_slope
# ---------------------------------------------------------------------------

class TestTrendSlope:
    @pytest.mark.parametrize(
        "scores,predicate",
        [
            ([], lambda slope: slope == pytest.approx(0.0)),
            ([0.5], lambda slope: slope == pytest.approx(0.0)),
            ([0.1, 0.5, 0.9], lambda slope: slope > 0.0),
            ([0.9, 0.5, 0.1], lambda slope: slope < 0.0),
            ([0.5, 0.5, 0.5], lambda slope: slope == pytest.approx(0.0)),
        ],
    )
    def test_trend_slope_scenarios(self, scores, predicate):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert predicate(p.trend_slope())


# ---------------------------------------------------------------------------
# OntologyOptimizer.min_score
# ---------------------------------------------------------------------------

class TestMinScore:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.3, 0.7, 0.5], 0.3),
            ([0.8], 0.8),
        ],
    )
    def test_min_score_scenarios(self, scores, expected):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert o.min_score() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyOptimizer.max_score
# ---------------------------------------------------------------------------

class TestMaxScore:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.3, 0.9, 0.5], 0.9),
            ([0.4], 0.4),
        ],
    )
    def test_max_score_scenarios(self, scores, expected):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert o.max_score() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyOptimizer.median_score
# ---------------------------------------------------------------------------

class TestOptimizerMedianScore:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.2, 0.6, 0.9], 0.6),
            ([0.2, 0.4, 0.6, 0.8], 0.5),
            ([0.75], 0.75),
        ],
    )
    def test_optimizer_median_score_scenarios(self, scores, expected):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert o.median_score() == pytest.approx(expected)
