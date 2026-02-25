"""Batch-152 feature tests.

Methods under test:
  - OntologyPipeline.best_run_index()
  - OntologyPipeline.score_improvement_rate()
  - OntologyOptimizer.window_average(window)
  - OntologyMediator.feedback_history_size()
"""
import pytest
from unittest.mock import MagicMock


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


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    critic = MagicMock()
    return OntologyMediator(gen, critic)


# ---------------------------------------------------------------------------
# OntologyPipeline.best_run_index
# ---------------------------------------------------------------------------

class TestBestRunIndex:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], -1),
            ([0.6], 0),
            ([0.3, 0.5, 0.9], 2),
            ([0.9, 0.5, 0.3], 0),
            ([0.3, 0.9, 0.5], 1),
        ],
    )
    def test_best_run_index_scenarios(self, scores, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert p.best_run_index() == expected


# ---------------------------------------------------------------------------
# OntologyPipeline.score_improvement_rate
# ---------------------------------------------------------------------------

class TestScoreImprovementRate:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.5], 0.0),
            ([0.2, 0.8], 0.6),
            ([0.8, 0.2], -0.6),
            # (0.7 - 0.1) / 2 = 0.3
            ([0.1, 0.4, 0.7], 0.3),
        ],
    )
    def test_score_improvement_rate_scenarios(self, scores, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert p.score_improvement_rate() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyOptimizer.window_average
# ---------------------------------------------------------------------------

class TestWindowAverage:
    @pytest.mark.parametrize(
        "scores,window,expected",
        [
            ([], None, 0.0),
            ([0.6], None, 0.6),
            ([0.4, 0.6], 10, 0.5),
            # window=2 -> last 2: [0.9, 0.9]
            ([0.1, 0.9, 0.9], 2, 0.9),
            ([0.2, 0.4, 0.6, 0.8, 1.0], None, 0.6),
        ],
    )
    def test_window_average_scenarios(self, scores, window, expected):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        if window is None:
            result = o.window_average()
        else:
            result = o.window_average(window=window)
        assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyMediator.feedback_history_size
# ---------------------------------------------------------------------------

class TestFeedbackHistorySize:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.feedback_history_size() == 0

    def test_returns_non_negative(self):
        m = _make_mediator()
        assert m.feedback_history_size() >= 0

    def test_integer_return(self):
        m = _make_mediator()
        assert isinstance(m.feedback_history_size(), int)
