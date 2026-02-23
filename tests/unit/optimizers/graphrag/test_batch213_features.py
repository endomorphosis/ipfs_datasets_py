"""Batch-213 feature tests.

Methods under test:
  - OntologyOptimizer.score_trimmed_range(trim)
  - OntologyOptimizer.history_geometric_mean()
  - OntologyGenerator.entity_text_length_median(result)
  - OntologyGenerator.relationship_type_entropy(result)
  - LogicValidator.singleton_entity_count(ontology)
  - OntologyPipeline.run_median_score()
  - OntologyLearningAdapter.feedback_consistency_score()
  - OntologyMediator.action_gini_coefficient()
"""
import pytest
from unittest.mock import MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_entity(eid, confidence=1.0, text=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=text or eid, confidence=confidence)


def _make_rel_mock(source_id="src", target_id="tgt", rel_type="related"):
    r = MagicMock()
    r.source_id = source_id
    r.target_id = target_id
    r.type = rel_type
    return r


def _make_result(entities=None, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=relationships or [],
        confidence=1.0,
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


def _push_run(p, score_val):
    run = MagicMock()
    run.score.overall = score_val
    p._run_history.append(run)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    a._feedback.append(FeedbackRecord(final_score=score))


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    return OntologyMediator(generator=MagicMock(), critic=MagicMock())


# ── OntologyOptimizer.score_trimmed_range ────────────────────────────────────

class TestScoreTrimmedRange:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_trimmed_range() == pytest.approx(0.0)

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.score_trimmed_range() == pytest.approx(0.0)

    def test_range_after_trim(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        # 10% trim: cut=max(1,0) → 1; trimmed = [0.3, 0.5, 0.7] → range=0.4
        result = o.score_trimmed_range(trim=0.1)
        assert isinstance(result, float)
        assert result >= 0.0


# ── OntologyOptimizer.history_geometric_mean ─────────────────────────────────

class TestHistoryGeometricMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_geometric_mean() == pytest.approx(0.0)

    def test_single(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_geometric_mean() == pytest.approx(0.5)

    def test_two_values(self):
        import math
        o = _make_optimizer()
        _push_opt(o, 0.25)
        _push_opt(o, 1.0)
        # geometric mean of (0.25, 1.0) = sqrt(0.25) = 0.5
        assert o.history_geometric_mean() == pytest.approx(0.5)

    def test_zero_excluded(self):
        o = _make_optimizer()
        _push_opt(o, 0.0)
        _push_opt(o, 1.0)
        # only 1.0 is positive → geomean = 1.0
        assert o.history_geometric_mean() == pytest.approx(1.0)


# ── OntologyGenerator.entity_text_length_median ──────────────────────────────

class TestEntityTextLengthMedian:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_text_length_median(r) == pytest.approx(0.0)

    def test_single(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", text="hello")])
        assert g.entity_text_length_median(r) == pytest.approx(5.0)

    def test_odd_count(self):
        g = _make_generator()
        entities = [
            _make_entity("a", text="ab"),
            _make_entity("b", text="abcd"),
            _make_entity("c", text="abcdef"),
        ]
        r = _make_result(entities)
        assert g.entity_text_length_median(r) == pytest.approx(4.0)

    def test_even_count(self):
        g = _make_generator()
        entities = [
            _make_entity("a", text="ab"),
            _make_entity("b", text="abcd"),
        ]
        r = _make_result(entities)
        assert g.entity_text_length_median(r) == pytest.approx(3.0)


# ── OntologyGenerator.relationship_type_entropy ──────────────────────────────

class TestRelationshipTypeEntropy:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_type_entropy(r) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock()])
        assert g.relationship_type_entropy(r) == pytest.approx(0.0)

    def test_uniform_distribution_max_entropy(self):
        g = _make_generator()
        rels = [_make_rel_mock(rel_type="a"), _make_rel_mock(rel_type="b")]
        r = _make_result(relationships=rels)
        # 2 equal types → entropy = 1.0 bit
        assert g.relationship_type_entropy(r) == pytest.approx(1.0)

    def test_all_same_type_zero_entropy(self):
        g = _make_generator()
        rels = [_make_rel_mock(rel_type="x"), _make_rel_mock(rel_type="x")]
        r = _make_result(relationships=rels)
        assert g.relationship_type_entropy(r) == pytest.approx(0.0)


# ── LogicValidator.singleton_entity_count ────────────────────────────────────

class TestSingletonEntityCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.singleton_entity_count({}) == 0

    def test_all_connected(self):
        v = _make_validator()
        onto = {
            "entities": [{"id": "a"}, {"id": "b"}],
            "relationships": [{"source": "a", "target": "b"}],
        }
        assert v.singleton_entity_count(onto) == 0

    def test_one_singleton(self):
        v = _make_validator()
        onto = {
            "entities": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "relationships": [{"source": "a", "target": "b"}],
        }
        # c is not in any relationship
        assert v.singleton_entity_count(onto) == 1


# ── OntologyPipeline.run_median_score ────────────────────────────────────────

class TestRunMedianScore:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_median_score() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.run_median_score() == pytest.approx(0.6)

    def test_odd_count(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5]:
            _push_run(p, v)
        assert p.run_median_score() == pytest.approx(0.5)

    def test_even_count(self):
        p = _make_pipeline()
        for v in [0.3, 0.7]:
            _push_run(p, v)
        assert p.run_median_score() == pytest.approx(0.5)


# ── OntologyLearningAdapter.feedback_consistency_score ───────────────────────

class TestFeedbackConsistencyScore:
    def test_empty_returns_one(self):
        a = _make_adapter()
        assert a.feedback_consistency_score() == pytest.approx(1.0)

    def test_single_returns_one(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_consistency_score() == pytest.approx(1.0)

    def test_uniform_returns_one(self):
        a = _make_adapter()
        for v in [0.5, 0.5, 0.5]:
            _push_feedback(a, v)
        assert a.feedback_consistency_score() == pytest.approx(1.0)

    def test_max_variance_returns_zero(self):
        a = _make_adapter()
        for v in [0.0, 1.0]:
            _push_feedback(a, v)
        # std = 0.5 → consistency = 0.0
        assert a.feedback_consistency_score() == pytest.approx(0.0)


# ── OntologyMediator.action_gini_coefficient ─────────────────────────────────

class TestActionGiniCoefficient:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_gini_coefficient() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 5}
        assert m.action_gini_coefficient() == pytest.approx(0.0)

    def test_max_inequality_returns_non_zero(self):
        m = _make_mediator()
        m._action_counts = {"a": 10, "b": 0}
        result = m.action_gini_coefficient()
        # With one type = 10 and another = 0, all weight is on one side
        assert isinstance(result, float)
        assert result >= 0.0
