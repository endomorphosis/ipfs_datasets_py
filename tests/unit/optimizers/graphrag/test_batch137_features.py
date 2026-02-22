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
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.top_k_history() == []

    def test_sorted_descending(self):
        o = _make_optimizer()
        for v in [0.3, 0.9, 0.6]:
            _push_opt(o, v)
        result = o.top_k_history(k=2)
        assert len(result) == 2
        assert result[0].average_score == pytest.approx(0.9)
        assert result[1].average_score == pytest.approx(0.6)

    def test_k_larger_than_history(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert len(o.top_k_history(k=10)) == 1

    def test_default_k_three(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5]:
            _push_opt(o, v)
        assert len(o.top_k_history()) == 3


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_score_std
# ---------------------------------------------------------------------------

class TestHistoryScoreStd:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_score_std() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_score_std() == pytest.approx(0.0)

    def test_identical_scores_zero_std(self):
        o = _make_optimizer()
        for _ in range(3):
            _push_opt(o, 0.7)
        assert o.history_score_std() == pytest.approx(0.0)

    def test_known_std(self):
        o = _make_optimizer()
        # scores [0.0, 1.0] → mean=0.5, variance=0.25, std=0.5
        _push_opt(o, 0.0)
        _push_opt(o, 1.0)
        assert o.history_score_std() == pytest.approx(0.5)

    def test_returns_float(self):
        o = _make_optimizer()
        _push_opt(o, 0.4)
        _push_opt(o, 0.6)
        assert isinstance(o.history_score_std(), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.count_entries_with_trend
# ---------------------------------------------------------------------------

class TestCountEntriesWithTrend:
    def test_empty_history_zero(self):
        o = _make_optimizer()
        assert o.count_entries_with_trend("improving") == 0

    def test_matching_count(self):
        o = _make_optimizer()
        _push_opt(o, 0.5, "improving")
        _push_opt(o, 0.6, "improving")
        _push_opt(o, 0.4, "stable")
        assert o.count_entries_with_trend("improving") == 2

    def test_no_match_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5, "stable")
        assert o.count_entries_with_trend("declining") == 0

    def test_default_trend_stable(self):
        """Entries with no explicit trend attribute count as 'stable'."""
        o = _make_optimizer()
        o._history.append(_FakeEntry(0.5))  # trend="stable"
        assert o.count_entries_with_trend("stable") == 1


# ---------------------------------------------------------------------------
# OntologyGenerator.confidence_histogram
# ---------------------------------------------------------------------------

class TestConfidenceHistogram:
    def test_empty_result(self):
        g = _make_generator()
        r = _make_result()
        hist = g.confidence_histogram(r, bins=5)
        assert isinstance(hist, dict)
        assert sum(hist.values()) == 0

    def test_bucket_count(self):
        g = _make_generator()
        r = _make_result(0.1, 0.5, 0.9)
        hist = g.confidence_histogram(r, bins=5)
        assert len(hist) == 5

    def test_total_equals_entity_count(self):
        g = _make_generator()
        r = _make_result(0.1, 0.3, 0.7, 0.95)
        hist = g.confidence_histogram(r, bins=4)
        assert sum(hist.values()) == 4

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
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result()
        assert g.mean_confidence(r) == pytest.approx(0.0)

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result(0.8)
        assert g.mean_confidence(r) == pytest.approx(0.8)

    def test_multiple_entities(self):
        g = _make_generator()
        r = _make_result(0.4, 0.6)
        assert g.mean_confidence(r) == pytest.approx(0.5)

    def test_all_same(self):
        g = _make_generator()
        r = _make_result(0.7, 0.7, 0.7)
        assert g.mean_confidence(r) == pytest.approx(0.7)
