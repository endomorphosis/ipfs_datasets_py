"""Batch-178 feature tests.

Methods under test:
  - OntologyOptimizer.history_second_derivative()
  - OntologyCritic.score_reliability(scores)
  - OntologyGenerator.entity_relation_ratio(result)
  - OntologyGenerator.relationship_confidence_std(result)
  - LogicValidator.max_dag_depth(ontology)
  - OntologyLearningAdapter.feedback_rate_of_change()
  - OntologyLearningAdapter.feedback_above_mean_count()
  - OntologyPipeline.run_score_median()
  - OntologyPipeline.run_count_above(threshold)
"""
import pytest
from unittest.mock import MagicMock


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_relationship(sid, tid, confidence=1.0):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=f"{sid}-{tid}", type="r", source_id=sid, target_id=tid, confidence=confidence)


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


class _FakeRel:
    def __init__(self, src, tgt):
        self.source_id = src
        self.target_id = tgt
        self.type = "r"


class _FakeOntology:
    def __init__(self, rels):
        self.relationships = rels


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score))


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


# ── OntologyOptimizer.history_second_derivative ───────────────────────────────

class TestHistorySecondDerivative:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.history_second_derivative() == []

    def test_two_entries_returns_empty(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.5)
        assert o.history_second_derivative() == []

    def test_constant_returns_zeros(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        result = o.history_second_derivative()
        assert all(v == pytest.approx(0.0) for v in result)

    def test_linear_returns_zeros(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7]:
            _push_opt(o, v)
        result = o.history_second_derivative()
        assert all(v == pytest.approx(0.0) for v in result)

    def test_accelerating_positive_second_deriv(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.5, 1.0]:  # gaps: 0.1, 0.3, 0.5 → second: 0.2, 0.2
            _push_opt(o, v)
        result = o.history_second_derivative()
        assert len(result) == 2
        assert all(r > 0 for r in result)

    def test_length_is_n_minus_2(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.6, 0.8]:
            _push_opt(o, v)
        assert len(o.history_second_derivative()) == 3


# ── OntologyCritic.score_reliability ──────────────────────────────────────────

class TestScoreReliability:
    def test_empty_returns_zero(self):
        c = _make_critic()
        assert c.score_reliability([]) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        c = _make_critic()
        assert c.score_reliability([_make_score()]) == pytest.approx(0.0)

    def test_identical_scores_high_reliability(self):
        c = _make_critic()
        scores = [_make_score() for _ in range(4)]
        # identical overall → std=0 → reliability=1.0
        # but overall may be 0 for all since scores are equal → std=0 → 1.0
        assert c.score_reliability(scores) == pytest.approx(1.0)

    def test_result_in_range(self):
        c = _make_critic()
        scores = [_make_score(completeness=0.2), _make_score(completeness=0.8)]
        r = c.score_reliability(scores)
        assert 0.0 <= r <= 1.0


# ── OntologyGenerator.entity_relation_ratio ───────────────────────────────────

class TestEntityRelationRatio:
    def test_no_rels_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1")]
        assert gen.entity_relation_ratio(_make_result(entities, [])) == pytest.approx(0.0)

    def test_equal_counts(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        rels = [_make_relationship("e1", "e2")]
        # 2 entities / 1 rel = 2.0
        assert gen.entity_relation_ratio(_make_result(entities, rels)) == pytest.approx(2.0)

    def test_more_rels_than_entities(self):
        gen = _make_generator()
        entities = [_make_entity("e1")]
        rels = [_make_relationship("e1", "e2"), _make_relationship("e1", "e3")]
        assert gen.entity_relation_ratio(_make_result(entities, rels)) == pytest.approx(0.5)


# ── OntologyGenerator.relationship_confidence_std ────────────────────────────

class TestRelationshipConfidenceStd:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.relationship_confidence_std(_make_result([], [])) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b", 0.8)]
        assert gen.relationship_confidence_std(_make_result([], rels)) == pytest.approx(0.0)

    def test_known_std(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b", 0.0), _make_relationship("b", "c", 1.0)]
        # pop std of [0, 1] = 0.5
        assert gen.relationship_confidence_std(_make_result([], rels)) == pytest.approx(0.5)


# ── LogicValidator.max_dag_depth ──────────────────────────────────────────────

class TestMaxDAGDepth:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.max_dag_depth(_FakeOntology([])) == 0

    def test_single_rel(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        assert v.max_dag_depth(_FakeOntology(rels)) == 1

    def test_chain_depth(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("c", "d")]
        assert v.max_dag_depth(_FakeOntology(rels)) == 3

    def test_parallel_branches(self):
        v = _make_validator()
        rels = [_FakeRel("root", "a"), _FakeRel("root", "b"), _FakeRel("a", "c")]
        assert v.max_dag_depth(_FakeOntology(rels)) == 2


# ── OntologyLearningAdapter.feedback_rate_of_change ──────────────────────────

class TestFeedbackRateOfChange:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_rate_of_change() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        a = _make_adapter()
        for _ in range(3):
            _push_feedback(a, 0.5)
        assert a.feedback_rate_of_change() == pytest.approx(0.0)

    def test_nonzero_change(self):
        a = _make_adapter()
        _push_feedback(a, 0.0)
        _push_feedback(a, 1.0)
        assert a.feedback_rate_of_change() == pytest.approx(1.0)


# ── OntologyLearningAdapter.feedback_above_mean_count ────────────────────────

class TestFeedbackAboveMeanCount:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_above_mean_count() == 0

    def test_all_same_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_above_mean_count() == 0

    def test_basic(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8, 0.9]:
            _push_feedback(a, v)
        # mean = 0.6; above: 0.8, 0.9 → 2
        assert a.feedback_above_mean_count() == 2


# ── OntologyPipeline.run_score_median ────────────────────────────────────────

class TestRunScoreMedian:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_median() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_median() == pytest.approx(0.0)

    def test_odd_count_median(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.8]:
            _push_run(p, v)
        assert p.run_score_median() == pytest.approx(0.5)

    def test_even_count_median(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_run(p, v)
        assert p.run_score_median() == pytest.approx(0.5)


# ── OntologyPipeline.run_count_above ─────────────────────────────────────────

class TestRunCountAbove:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_count_above(0.7) == 0

    def test_all_above(self):
        p = _make_pipeline()
        for v in [0.8, 0.9, 1.0]:
            _push_run(p, v)
        assert p.run_count_above(0.7) == 3

    def test_none_above(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.6]:
            _push_run(p, v)
        assert p.run_count_above(0.7) == 0

    def test_some_above(self):
        p = _make_pipeline()
        for v in [0.5, 0.8, 0.9]:
            _push_run(p, v)
        assert p.run_count_above(0.7) == 2
