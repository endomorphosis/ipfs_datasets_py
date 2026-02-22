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
    def test_empty_returns_minus_one(self):
        p = _make_pipeline()
        assert p.best_run_index() == -1

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.best_run_index() == 0

    def test_best_is_last(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.9]:
            _push_run(p, v)
        assert p.best_run_index() == 2

    def test_best_is_first(self):
        p = _make_pipeline()
        for v in [0.9, 0.5, 0.3]:
            _push_run(p, v)
        assert p.best_run_index() == 0

    def test_best_is_middle(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.5]:
            _push_run(p, v)
        assert p.best_run_index() == 1


# ---------------------------------------------------------------------------
# OntologyPipeline.score_improvement_rate
# ---------------------------------------------------------------------------

class TestScoreImprovementRate:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_improvement_rate() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.score_improvement_rate() == pytest.approx(0.0)

    def test_positive_improvement(self):
        p = _make_pipeline()
        _push_run(p, 0.2)
        _push_run(p, 0.8)
        assert p.score_improvement_rate() == pytest.approx(0.6)

    def test_negative_improvement(self):
        p = _make_pipeline()
        _push_run(p, 0.8)
        _push_run(p, 0.2)
        assert p.score_improvement_rate() == pytest.approx(-0.6)

    def test_three_steps_rate(self):
        p = _make_pipeline()
        for v in [0.1, 0.4, 0.7]:
            _push_run(p, v)
        # (0.7 - 0.1) / 2 = 0.3
        assert p.score_improvement_rate() == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# OntologyOptimizer.window_average
# ---------------------------------------------------------------------------

class TestWindowAverage:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.window_average() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.6)
        assert o.window_average() == pytest.approx(0.6)

    def test_window_larger_than_history(self):
        o = _make_optimizer()
        for v in [0.4, 0.6]:
            _push_opt(o, v)
        assert o.window_average(window=10) == pytest.approx(0.5)

    def test_window_trims_to_recent(self):
        o = _make_optimizer()
        for v in [0.1, 0.9, 0.9]:
            _push_opt(o, v)
        # window=2 → last 2: [0.9, 0.9]
        assert o.window_average(window=2) == pytest.approx(0.9)

    def test_default_window(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8, 1.0]:
            _push_opt(o, v)
        assert o.window_average() == pytest.approx(0.6)


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
