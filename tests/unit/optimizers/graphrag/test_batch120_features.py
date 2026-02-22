"""Batch-120 feature tests.

Methods under test:
  - OntologyPipeline.worst_n_runs(n)
  - OntologyPipeline.pass_rate(threshold)
  - OntologyPipeline.score_range()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(pipeline, overall):
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    pipeline._run_history.append(run)


# ---------------------------------------------------------------------------
# OntologyPipeline.worst_n_runs
# ---------------------------------------------------------------------------

class TestWorstNRuns:
    def test_empty(self):
        p = _make_pipeline()
        assert p.worst_n_runs() == []

    def test_returns_ascending_order(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.5, 0.7]:
            _push_run(p, v)
        bottom2 = p.worst_n_runs(2)
        assert len(bottom2) == 2
        assert bottom2[0].score.overall == pytest.approx(0.3)
        assert bottom2[1].score.overall == pytest.approx(0.5)

    def test_n_larger_than_history(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert len(p.worst_n_runs(10)) == 1

    def test_default_n(self):
        p = _make_pipeline()
        for v in [0.1, 0.4, 0.6, 0.8, 0.9]:
            _push_run(p, v)
        assert len(p.worst_n_runs()) == 3


# ---------------------------------------------------------------------------
# OntologyPipeline.pass_rate
# ---------------------------------------------------------------------------

class TestPassRate:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.pass_rate() == 0.0

    def test_all_pass(self):
        p = _make_pipeline()
        for v in [0.7, 0.8, 0.9]:
            _push_run(p, v)
        assert p.pass_rate() == pytest.approx(1.0)

    def test_none_pass(self):
        p = _make_pipeline()
        for v in [0.1, 0.2, 0.3]:
            _push_run(p, v)
        assert p.pass_rate() == pytest.approx(0.0)

    def test_partial_pass(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.9]:
            _push_run(p, v)
        assert p.pass_rate() == pytest.approx(2.0 / 3.0)

    def test_custom_threshold(self):
        p = _make_pipeline()
        for v in [0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert p.pass_rate(threshold=0.8) == pytest.approx(1.0 / 3.0)


# ---------------------------------------------------------------------------
# OntologyPipeline.score_range
# ---------------------------------------------------------------------------

class TestScoreRangePipeline:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        lo, hi = p.score_range()
        assert lo == 0.0 and hi == 0.0

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        lo, hi = p.score_range()
        assert lo == pytest.approx(0.7)
        assert hi == pytest.approx(0.7)

    def test_multiple_runs(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5]:
            _push_run(p, v)
        lo, hi = p.score_range()
        assert lo == pytest.approx(0.3)
        assert hi == pytest.approx(0.7)
