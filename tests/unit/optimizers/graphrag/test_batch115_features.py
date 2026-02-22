"""Batch-115 feature tests.

Methods under test:
  - ExtractionConfig.relaxed(delta)
  - ExtractionConfig.tightened(delta)
  - OntologyPipeline.top_n_runs(n)
  - OntologyPipeline.score_momentum(window)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
    return ExtractionConfig(**kwargs)


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(pipeline, overall):
    from unittest.mock import MagicMock
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    pipeline._run_history.append(run)


# ---------------------------------------------------------------------------
# ExtractionConfig.relaxed
# ---------------------------------------------------------------------------

class TestRelaxed:
    def test_default_delta(self):
        cfg = _make_config(confidence_threshold=0.8)
        relaxed = cfg.relaxed()
        assert relaxed.confidence_threshold == pytest.approx(0.7)

    def test_custom_delta(self):
        cfg = _make_config(confidence_threshold=0.5)
        relaxed = cfg.relaxed(delta=0.2)
        assert relaxed.confidence_threshold == pytest.approx(0.3)

    def test_clamped_to_zero(self):
        cfg = _make_config(confidence_threshold=0.05)
        relaxed = cfg.relaxed()
        assert relaxed.confidence_threshold == pytest.approx(0.0)

    def test_original_unchanged(self):
        cfg = _make_config(confidence_threshold=0.8)
        cfg.relaxed()
        assert cfg.confidence_threshold == pytest.approx(0.8)

    def test_returns_new_config(self):
        cfg = _make_config()
        relaxed = cfg.relaxed()
        assert relaxed is not cfg


# ---------------------------------------------------------------------------
# ExtractionConfig.tightened
# ---------------------------------------------------------------------------

class TestTightened:
    def test_default_delta(self):
        cfg = _make_config(confidence_threshold=0.5)
        tightened = cfg.tightened()
        assert tightened.confidence_threshold == pytest.approx(0.6)

    def test_custom_delta(self):
        cfg = _make_config(confidence_threshold=0.7)
        tightened = cfg.tightened(delta=0.2)
        assert tightened.confidence_threshold == pytest.approx(0.9)

    def test_clamped_to_one(self):
        cfg = _make_config(confidence_threshold=0.95)
        tightened = cfg.tightened()
        assert tightened.confidence_threshold == pytest.approx(1.0)

    def test_original_unchanged(self):
        cfg = _make_config(confidence_threshold=0.6)
        cfg.tightened()
        assert cfg.confidence_threshold == pytest.approx(0.6)

    def test_returns_new_config(self):
        cfg = _make_config()
        tightened = cfg.tightened()
        assert tightened is not cfg


# ---------------------------------------------------------------------------
# OntologyPipeline.top_n_runs
# ---------------------------------------------------------------------------

class TestTopNRuns:
    def test_empty(self):
        p = _make_pipeline()
        assert p.top_n_runs() == []

    def test_returns_top_n_sorted(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.5, 0.7]:
            _push_run(p, v)
        top2 = p.top_n_runs(2)
        assert len(top2) == 2
        assert top2[0].score.overall == pytest.approx(0.9)
        assert top2[1].score.overall == pytest.approx(0.7)

    def test_n_larger_than_history(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert len(p.top_n_runs(10)) == 1

    def test_all_runs_with_large_n(self):
        p = _make_pipeline()
        for v in [0.4, 0.6, 0.8]:
            _push_run(p, v)
        top = p.top_n_runs(5)
        assert len(top) == 3


# ---------------------------------------------------------------------------
# OntologyPipeline.score_momentum
# ---------------------------------------------------------------------------

class TestScoreMomentum:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_momentum() == 0.0

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.score_momentum() == 0.0

    def test_improving_positive(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.7)
        assert p.score_momentum() > 0.0

    def test_declining_negative(self):
        p = _make_pipeline()
        _push_run(p, 0.9)
        _push_run(p, 0.5)
        assert p.score_momentum() < 0.0

    def test_flat_near_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        _push_run(p, 0.6)
        assert p.score_momentum() == pytest.approx(0.0)

    def test_custom_window(self):
        p = _make_pipeline()
        # Push many runs, last window=2 should be improving
        for v in [0.9, 0.1, 0.5, 0.8]:
            _push_run(p, v)
        assert p.score_momentum(window=2) > 0.0
