"""Batch-150 feature tests.

Methods under test:
  - OntologyOptimizer.history_autocorrelation(lag)
  - OntologyLearningAdapter.feedback_skewness()
  - OntologyGenerator.top_k_entities_by_confidence(result, k)
  - LogicValidator.longest_path(ontology, source)
"""
import pytest
from unittest.mock import MagicMock


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="Test", text=eid, confidence=confidence)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_autocorrelation
# ---------------------------------------------------------------------------

class TestHistoryAutocorrelation:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_autocorrelation() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_autocorrelation() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.6)
        assert o.history_autocorrelation() == pytest.approx(0.0)

    def test_trending_positive_autocorrelation(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5]:
            _push_opt(o, v)
        assert o.history_autocorrelation(lag=1) > 0

    def test_alternating_negative_autocorrelation(self):
        o = _make_optimizer()
        for v in [0.1, 0.9, 0.1, 0.9, 0.1]:
            _push_opt(o, v)
        assert o.history_autocorrelation(lag=1) < 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_skewness
# ---------------------------------------------------------------------------

class TestFeedbackSkewness:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_skewness() == pytest.approx(0.0)

    def test_two_records_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.6)
        assert a.feedback_skewness() == pytest.approx(0.0)

    def test_symmetric_returns_near_zero(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8]:
            _push_feedback(a, v)
        assert abs(a.feedback_skewness()) < 0.1

    def test_right_skewed_positive(self):
        a = _make_adapter()
        # mostly low values with one high outlier → right skew
        for v in [0.1, 0.1, 0.1, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_skewness() > 0

    def test_zero_variance_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_skewness() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyGenerator.top_k_entities_by_confidence
# ---------------------------------------------------------------------------

class TestTopKEntitiesByConfidence:
    def test_empty_result_returns_empty(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.top_k_entities_by_confidence(result, 3) == []

    def test_returns_at_most_k(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=i * 0.1) for i in range(5)]
        result = _make_result(entities)
        assert len(gen.top_k_entities_by_confidence(result, 2)) == 2

    def test_sorted_descending(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=i * 0.1) for i in range(4)]
        result = _make_result(entities)
        top = gen.top_k_entities_by_confidence(result, 3)
        confs = [e.confidence for e in top]
        assert confs == sorted(confs, reverse=True)

    def test_k_larger_than_entities_returns_all(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.3), _make_entity("e2", 0.7)]
        result = _make_result(entities)
        assert len(gen.top_k_entities_by_confidence(result, 10)) == 2

    def test_top_1_is_highest(self):
        gen = _make_generator()
        entities = [_make_entity("lo", 0.1), _make_entity("hi", 0.9)]
        result = _make_result(entities)
        top = gen.top_k_entities_by_confidence(result, 1)
        assert top[0].id == "hi"


# ---------------------------------------------------------------------------
# LogicValidator.longest_path
# ---------------------------------------------------------------------------

class TestLongestPath:
    def test_empty_ontology(self):
        v = _make_validator()
        assert v.longest_path({}, "A") == 0

    def test_isolated_source(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}
        assert v.longest_path(ont, "A") == 0

    def test_simple_chain(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "C"},
            ],
        }
        assert v.longest_path(ont, "A") == 2

    def test_branching_path(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "A", "object_id": "C"},
                {"subject_id": "C", "object_id": "D"},  # longer branch
            ],
        }
        assert v.longest_path(ont, "A") == 2

    def test_cycle_returns_minus_one(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "A"},
            ],
        }
        assert v.longest_path(ont, "A") == -1
