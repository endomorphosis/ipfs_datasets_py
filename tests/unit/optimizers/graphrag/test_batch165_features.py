"""Batch-165 feature tests.

Methods under test:
  - OntologyGenerator.entity_confidence_variance(result)
  - LogicValidator.cycle_count(ontology)
  - OntologyPipeline.run_trend(n)
  - OntologyLearningAdapter.feedback_above_median()
"""
import pytest
from unittest.mock import MagicMock


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities,
        relationships=[],
        confidence=1.0,
        metadata={},
        errors=[],
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _ont(entities, rels):
    return {"entities": entities, "relationships": rels}


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_variance
# ---------------------------------------------------------------------------

class TestEntityConfidenceVariance:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.entity_confidence_variance(result) == pytest.approx(0.0)

    def test_single_entity_returns_zero(self):
        gen = _make_generator()
        result = _make_result([_make_entity("e1", 0.7)])
        assert gen.entity_confidence_variance(result) == pytest.approx(0.0)

    def test_constant_confidences(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", 0.6) for i in range(5)]
        result = _make_result(entities)
        assert gen.entity_confidence_variance(result) == pytest.approx(0.0)

    def test_known_variance(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.0), _make_entity("e2", 1.0)]
        result = _make_result(entities)
        # population variance of [0, 1] = 0.25
        assert gen.entity_confidence_variance(result) == pytest.approx(0.25)

    def test_non_negative(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", i * 0.1) for i in range(6)]
        result = _make_result(entities)
        assert gen.entity_confidence_variance(result) >= 0.0


# ---------------------------------------------------------------------------
# LogicValidator.cycle_count
# ---------------------------------------------------------------------------

class TestCycleCount:
    def test_empty_graph_no_cycles(self):
        v = _make_validator()
        assert v.cycle_count(_ont([], [])) == 0

    def test_dag_no_cycles(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            [
                {"source": "a", "target": "b", "type": "r"},
                {"source": "b", "target": "c", "type": "r"},
            ],
        )
        assert v.cycle_count(ont) == 0

    def test_self_loop(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}],
            [{"source": "a", "target": "a", "type": "r"}],
        )
        assert v.cycle_count(ont) >= 1

    def test_simple_cycle(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}],
            [
                {"source": "a", "target": "b", "type": "r"},
                {"source": "b", "target": "a", "type": "r"},
            ],
        )
        assert v.cycle_count(ont) >= 1


# ---------------------------------------------------------------------------
# OntologyPipeline.run_trend
# ---------------------------------------------------------------------------

class TestRunTrend:
    def test_empty_returns_flat(self):
        p = _make_pipeline()
        assert p.run_trend() == "flat"

    def test_single_run_returns_flat(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_trend() == "flat"

    def test_increasing_trend_up(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert p.run_trend() == "up"

    def test_decreasing_trend_down(self):
        p = _make_pipeline()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push_run(p, v)
        assert p.run_trend() == "down"

    def test_constant_returns_flat(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_trend() == "flat"


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_above_median
# ---------------------------------------------------------------------------

class TestFeedbackAboveMedian:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.feedback_above_median() == []

    def test_single_record_returns_empty(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_above_median() == []

    def test_all_above_median(self):
        a = _make_adapter()
        for v in [0.1, 0.5, 0.8, 0.9]:
            _push_feedback(a, v)
        result = a.feedback_above_median()
        scores = [r.final_score for r in result]
        assert all(s > 0.5 for s in scores)

    def test_none_above_median(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3, 0.4]:
            _push_feedback(a, v)
        result = a.feedback_above_median()
        # median of [0.1,0.2,0.3,0.4] = (0.2+0.3)/2 = 0.25
        assert all(r.final_score > 0.25 for r in result)
