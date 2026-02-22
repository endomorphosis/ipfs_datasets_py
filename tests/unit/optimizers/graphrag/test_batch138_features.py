"""Batch-138 feature tests.

Methods under test:
  - OntologyPipeline.rolling_average(window)
  - OntologyPipeline.score_at_run(index)
  - OntologyPipeline.score_percentile(value)
  - ExtractionConfig.combined_score()
  - ExtractionConfig.similarity_to(other)
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


def _make_config(threshold=0.5, max_entities=100):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
    return ExtractionConfig(confidence_threshold=threshold, max_entities=max_entities)


# ---------------------------------------------------------------------------
# OntologyPipeline.rolling_average
# ---------------------------------------------------------------------------

class TestRollingAverage:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.rolling_average() == []

    def test_same_length_as_history(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6]:
            _push_run(p, v)
        result = p.rolling_average(window=2)
        assert len(result) == 3

    def test_first_element_is_first_score(self):
        p = _make_pipeline()
        _push_run(p, 0.4)
        _push_run(p, 0.8)
        result = p.rolling_average(window=5)
        assert result[0] == pytest.approx(0.4)

    def test_windowed_average(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6]:
            _push_run(p, v)
        result = p.rolling_average(window=2)
        # index 1 → avg(0.2, 0.4) = 0.3
        assert result[1] == pytest.approx(0.3)

    def test_all_same(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        result = p.rolling_average(window=3)
        assert all(v == pytest.approx(0.5) for v in result)


# ---------------------------------------------------------------------------
# OntologyPipeline.score_at_run
# ---------------------------------------------------------------------------

class TestScoreAtRun:
    def test_first_run(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        assert p.score_at_run(0) == pytest.approx(0.3)

    def test_negative_index(self):
        p = _make_pipeline()
        _push_run(p, 0.1)
        _push_run(p, 0.9)
        assert p.score_at_run(-1) == pytest.approx(0.9)

    def test_out_of_range_raises(self):
        p = _make_pipeline()
        with pytest.raises(IndexError):
            p.score_at_run(99)

    def test_middle_run(self):
        p = _make_pipeline()
        for v in [0.1, 0.5, 0.9]:
            _push_run(p, v)
        assert p.score_at_run(1) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# OntologyPipeline.score_percentile
# ---------------------------------------------------------------------------

class TestScorePercentile:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_percentile(0.5) == pytest.approx(0.0)

    def test_below_all(self):
        p = _make_pipeline()
        for v in [0.6, 0.7, 0.8]:
            _push_run(p, v)
        assert p.score_percentile(0.5) == pytest.approx(0.0)

    def test_above_some(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_run(p, v)
        # 0.5 is above 0.2 and 0.4 → 2/4 = 50%
        pct = p.score_percentile(0.5)
        assert pct == pytest.approx(50.0)

    def test_returns_float(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert isinstance(p.score_percentile(0.5), float)


# ---------------------------------------------------------------------------
# ExtractionConfig.combined_score
# ---------------------------------------------------------------------------

class TestCombinedScore:
    def test_returns_float(self):
        c = _make_config()
        assert isinstance(c.combined_score(), float)

    def test_higher_threshold_higher_score(self):
        low = _make_config(threshold=0.3)
        high = _make_config(threshold=0.9)
        assert high.combined_score() > low.combined_score()

    def test_bounded(self):
        c = _make_config(threshold=1.0, max_entities=10000)
        assert 0.0 <= c.combined_score() <= 2.0

    def test_zero_entities(self):
        c = _make_config(threshold=0.5, max_entities=0)
        score = c.combined_score()
        assert score == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# ExtractionConfig.similarity_to
# ---------------------------------------------------------------------------

class TestSimilarityTo:
    def test_identical_configs(self):
        c1 = _make_config(threshold=0.6)
        c2 = _make_config(threshold=0.6)
        assert c1.similarity_to(c2) == pytest.approx(1.0)

    def test_max_difference(self):
        c1 = _make_config(threshold=0.0)
        c2 = _make_config(threshold=1.0)
        assert c1.similarity_to(c2) == pytest.approx(0.0)

    def test_partial_difference(self):
        c1 = _make_config(threshold=0.5)
        c2 = _make_config(threshold=0.8)
        assert c1.similarity_to(c2) == pytest.approx(0.7)

    def test_symmetric(self):
        c1 = _make_config(threshold=0.4)
        c2 = _make_config(threshold=0.7)
        assert c1.similarity_to(c2) == pytest.approx(c2.similarity_to(c1))
