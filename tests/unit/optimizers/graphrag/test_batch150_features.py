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
    @pytest.mark.parametrize(
        "scores,lag,predicate",
        [
            ([], 1, lambda value: value == pytest.approx(0.0)),
            ([0.5], 1, lambda value: value == pytest.approx(0.0)),
            ([0.6, 0.6, 0.6, 0.6, 0.6], 1, lambda value: value == pytest.approx(0.0)),
            ([0.1, 0.2, 0.3, 0.4, 0.5], 1, lambda value: value > 0),
            ([0.1, 0.9, 0.1, 0.9, 0.1], 1, lambda value: value < 0),
        ],
    )
    def test_history_autocorrelation_scenarios(self, scores, lag, predicate):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert predicate(o.history_autocorrelation(lag=lag))


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_skewness
# ---------------------------------------------------------------------------

class TestFeedbackSkewness:
    @pytest.mark.parametrize(
        "scores,predicate",
        [
            ([], lambda value: value == pytest.approx(0.0)),
            ([0.4, 0.6], lambda value: value == pytest.approx(0.0)),
            ([0.2, 0.5, 0.8], lambda value: abs(value) < 0.1),
            # mostly low values with one high outlier -> right skew
            ([0.1, 0.1, 0.1, 0.9], lambda value: value > 0),
            ([0.5, 0.5, 0.5, 0.5], lambda value: value == pytest.approx(0.0)),
        ],
    )
    def test_feedback_skewness_scenarios(self, scores, predicate):
        a = _make_adapter()
        for v in scores:
            _push_feedback(a, v)
        assert predicate(a.feedback_skewness())


# ---------------------------------------------------------------------------
# OntologyGenerator.top_k_entities_by_confidence
# ---------------------------------------------------------------------------

class TestTopKEntitiesByConfidence:
    @pytest.mark.parametrize(
        "entities,k,expected_len,predicate",
        [
            ([], 3, 0, None),
            ([_make_entity(f"e{i}", confidence=i * 0.1) for i in range(5)], 2, 2, None),
            (
                [_make_entity(f"e{i}", confidence=i * 0.1) for i in range(4)],
                3,
                3,
                lambda top: [e.confidence for e in top] == sorted([e.confidence for e in top], reverse=True),
            ),
            ([_make_entity("e1", 0.3), _make_entity("e2", 0.7)], 10, 2, None),
            ([_make_entity("lo", 0.1), _make_entity("hi", 0.9)], 1, 1, lambda top: top[0].id == "hi"),
        ],
    )
    def test_top_k_entities_by_confidence_scenarios(self, entities, k, expected_len, predicate):
        gen = _make_generator()
        result = _make_result(entities)
        top = gen.top_k_entities_by_confidence(result, k)
        assert len(top) == expected_len
        if predicate is not None:
            assert predicate(top)


# ---------------------------------------------------------------------------
# LogicValidator.longest_path
# ---------------------------------------------------------------------------

class TestLongestPath:
    @pytest.mark.parametrize(
        "ontology,source,expected",
        [
            ({}, "A", 0),
            ({"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}, "A", 0),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "B", "object_id": "C"}],
                },
                "A",
                2,
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
                    "relationships": [
                        {"subject_id": "A", "object_id": "B"},
                        {"subject_id": "A", "object_id": "C"},
                        {"subject_id": "C", "object_id": "D"},
                    ],
                },
                "A",
                2,
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "B", "object_id": "A"}],
                },
                "A",
                -1,
            ),
        ],
    )
    def test_longest_path_scenarios(self, ontology, source, expected):
        v = _make_validator()
        assert v.longest_path(ontology, source) == expected
