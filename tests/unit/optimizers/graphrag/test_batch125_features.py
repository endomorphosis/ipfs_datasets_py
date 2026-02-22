"""Batch-125 feature tests.

Methods under test:
  - OntologyPipeline.run_count_above(threshold)
  - OntologyPipeline.average_score()
  - OntologyPipeline.best_score()
  - OntologyPipeline.worst_score()
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
# OntologyPipeline.run_count_above
# ---------------------------------------------------------------------------

class TestRunCountAbove:
    def test_empty(self):
        p = _make_pipeline()
        assert p.run_count_above() == 0

    def test_all_above(self):
        p = _make_pipeline()
        for v in [0.7, 0.8, 0.9]:
            _push_run(p, v)
        assert p.run_count_above(0.6) == 3

    def test_none_above(self):
        p = _make_pipeline()
        for v in [0.1, 0.2]:
            _push_run(p, v)
        assert p.run_count_above(0.6) == 0

    def test_exactly_at_threshold_not_counted(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.run_count_above(0.6) == 0

    def test_custom_threshold(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.9]:
            _push_run(p, v)
        assert p.run_count_above(0.5) == 2


# ---------------------------------------------------------------------------
# OntologyPipeline.average_score
# ---------------------------------------------------------------------------

class TestAverageScore:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.average_score() == 0.0

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.average_score() == pytest.approx(0.7)

    def test_multiple_runs(self):
        p = _make_pipeline()
        for v in [0.4, 0.6, 0.8]:
            _push_run(p, v)
        assert p.average_score() == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# OntologyPipeline.best_score
# ---------------------------------------------------------------------------

class TestBestScore:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.best_score() == 0.0

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.best_score() == pytest.approx(0.5)

    def test_returns_max(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.6]:
            _push_run(p, v)
        assert p.best_score() == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# OntologyPipeline.worst_score
# ---------------------------------------------------------------------------

class TestWorstScore:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.worst_score() == 0.0

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.worst_score() == pytest.approx(0.5)

    def test_returns_min(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.6]:
            _push_run(p, v)
        assert p.worst_score() == pytest.approx(0.3)
