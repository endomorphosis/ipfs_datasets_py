"""Batch-137 feature tests.

Methods under test:
  - OntologyOptimizer.top_k_history(k)
  - OntologyOptimizer.history_score_std()
  - OntologyOptimizer.count_entries_with_trend(trend)
  - OntologyGenerator.confidence_histogram(result, bins)
  - OntologyGenerator.mean_confidence(result)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg, trend="stable"):
        self.average_score = avg
        self.trend = trend
        self.best_ontology = {}
        self.worst_ontology = {}
        self.metadata = {}


def _push_opt(opt, avg, trend="stable"):
    opt._history.append(_FakeEntry(avg, trend))


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_result(*confidences):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, EntityExtractionResult
    entities = [
        Entity(id=f"e{i}", type="TYPE", text=f"e{i}", properties={}, confidence=c)
        for i, c in enumerate(confidences)
    ]
    return EntityExtractionResult(entities=entities, relationships=[], confidence=0.5, metadata={}, errors=[])


# ---------------------------------------------------------------------------
# OntologyOptimizer.top_k_history
# ---------------------------------------------------------------------------

class TestTopKHistory:
    @pytest.mark.parametrize(
        "values,k,expected_len,expected_prefix",
        [
            ([], 3, 0, []),
            ([0.3, 0.9, 0.6], 2, 2, [0.9, 0.6]),
            ([0.5], 10, 1, [0.5]),
            ([0.1, 0.2, 0.3, 0.4, 0.5], 3, 3, [0.5, 0.4, 0.3]),
        ],
    )
    def test_top_k_history_scenarios(self, values, k, expected_len, expected_prefix):
        o = _make_optimizer()
        for v in values:
            _push_opt(o, v)
        result = o.top_k_history(k=k)
        assert len(result) == expected_len
        for idx, expected in enumerate(expected_prefix):
            assert result[idx].average_score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_score_std
# ---------------------------------------------------------------------------

class TestHistoryScoreStd:
    @pytest.mark.parametrize(
        "values,expected",
        [
            ([], 0.0),
            ([0.5], 0.0),
            ([0.7, 0.7, 0.7], 0.0),
            # scores [0.0, 1.0] -> mean=0.5, variance=0.25, std=0.5
            ([0.0, 1.0], 0.5),
        ],
    )
    def test_history_score_std_scenarios(self, values, expected):
        o = _make_optimizer()
        for v in values:
            _push_opt(o, v)
        assert o.history_score_std() == pytest.approx(expected)

    def test_returns_float(self):
        o = _make_optimizer()
        _push_opt(o, 0.4)
        _push_opt(o, 0.6)
        assert isinstance(o.history_score_std(), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.count_entries_with_trend
# ---------------------------------------------------------------------------

class TestCountEntriesWithTrend:
    @pytest.mark.parametrize(
        "entries,trend,expected",
        [
            ([], "improving", 0),
            ([(0.5, "improving"), (0.6, "improving"), (0.4, "stable")], "improving", 2),
            ([(0.5, "stable")], "declining", 0),
        ],
    )
    def test_count_entries_with_trend_scenarios(self, entries, trend, expected):
        o = _make_optimizer()
        for avg, trend_label in entries:
            _push_opt(o, avg, trend_label)
        assert o.count_entries_with_trend(trend) == expected

    def test_default_trend_stable(self):
        """Entries with no explicit trend attribute count as 'stable'."""
        o = _make_optimizer()
        o._history.append(_FakeEntry(0.5))
        assert o.count_entries_with_trend("stable") == 1


# ---------------------------------------------------------------------------
# OntologyGenerator.confidence_histogram
# ---------------------------------------------------------------------------

class TestConfidenceHistogram:
    @pytest.mark.parametrize(
        "confidences,bins,expected_total,expected_buckets",
        [
            ([], 5, 0, 5),
            ([0.1, 0.5, 0.9], 5, 3, 5),
            ([0.1, 0.3, 0.7, 0.95], 4, 4, 4),
        ],
    )
    def test_confidence_histogram_scenarios(self, confidences, bins, expected_total, expected_buckets):
        g = _make_generator()
        r = _make_result(*confidences)
        hist = g.confidence_histogram(r, bins=bins)
        assert isinstance(hist, dict)
        assert sum(hist.values()) == expected_total
        assert len(hist) == expected_buckets

    def test_one_in_first_bucket(self):
        g = _make_generator()
        r = _make_result(0.05)
        hist = g.confidence_histogram(r, bins=5)
        # 0.05 falls in [0.00-0.20)
        assert hist["0.00-0.20"] == 1


# ---------------------------------------------------------------------------
# OntologyGenerator.mean_confidence
# ---------------------------------------------------------------------------

class TestMeanConfidence:
    @pytest.mark.parametrize(
        "confidences,expected",
        [
            ([], 0.0),
            ([0.8], 0.8),
            ([0.4, 0.6], 0.5),
            ([0.7, 0.7, 0.7], 0.7),
        ],
    )
    def test_mean_confidence_scenarios(self, confidences, expected):
        g = _make_generator()
        r = _make_result(*confidences)
        assert g.mean_confidence(r) == pytest.approx(expected)
