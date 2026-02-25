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
    @pytest.mark.parametrize(
        "scores,window,expected_len,expected_idx,expected_value",
        [
            ([], 3, 0, None, None),
            ([0.2, 0.4, 0.6], 2, 3, 1, 0.3),
            ([0.4, 0.8], 5, 2, 0, 0.4),
        ],
    )
    def test_rolling_average_scenarios(self, scores, window, expected_len, expected_idx, expected_value):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        result = p.rolling_average(window=window)
        assert len(result) == expected_len
        if expected_idx is not None:
            assert result[expected_idx] == pytest.approx(expected_value)

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
    @pytest.mark.parametrize(
        "scores,index,expected",
        [
            ([0.3], 0, 0.3),
            ([0.1, 0.9], -1, 0.9),
            ([0.1, 0.5, 0.9], 1, 0.5),
        ],
    )
    def test_score_at_run_scenarios(self, scores, index, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert p.score_at_run(index) == pytest.approx(expected)

    def test_out_of_range_raises(self):
        p = _make_pipeline()
        with pytest.raises(IndexError):
            p.score_at_run(99)


# ---------------------------------------------------------------------------
# OntologyPipeline.score_percentile
# ---------------------------------------------------------------------------

class TestScorePercentile:
    @pytest.mark.parametrize(
        "scores,value,expected",
        [
            ([], 0.5, 0.0),
            ([0.6, 0.7, 0.8], 0.5, 0.0),
            # 0.5 is above 0.2 and 0.4 -> 2/4 = 50%.
            ([0.2, 0.4, 0.6, 0.8], 0.5, 50.0),
        ],
    )
    def test_score_percentile_scenarios(self, scores, value, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert p.score_percentile(value) == pytest.approx(expected)

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

    @pytest.mark.parametrize(
        "threshold,max_entities,predicate",
        [
            (1.0, 10000, lambda score: 0.0 <= score <= 2.0),
            (0.5, 0, lambda score: score == pytest.approx(0.5, abs=0.01)),
        ],
    )
    def test_combined_score_scenarios(self, threshold, max_entities, predicate):
        c = _make_config(threshold=threshold, max_entities=max_entities)
        assert predicate(c.combined_score())

    def test_higher_threshold_higher_score(self):
        low = _make_config(threshold=0.3)
        high = _make_config(threshold=0.9)
        assert high.combined_score() > low.combined_score()


# ---------------------------------------------------------------------------
# ExtractionConfig.similarity_to
# ---------------------------------------------------------------------------

class TestSimilarityTo:
    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (0.6, 0.6, 1.0),
            (0.0, 1.0, 0.0),
            (0.5, 0.8, 0.7),
        ],
    )
    def test_similarity_to_scenarios(self, left, right, expected):
        c1 = _make_config(threshold=left)
        c2 = _make_config(threshold=right)
        assert c1.similarity_to(c2) == pytest.approx(expected)

    def test_symmetric(self):
        c1 = _make_config(threshold=0.4)
        c2 = _make_config(threshold=0.7)
        assert c1.similarity_to(c2) == pytest.approx(c2.similarity_to(c1))
