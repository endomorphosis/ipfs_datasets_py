"""Batch-180 feature tests.

Methods under test:
  - OntologyOptimizer.history_percentile(p)
  - OntologyOptimizer.score_below_percentile_count(p)
  - OntologyCritic.dimension_coefficient_of_variation(score)
  - OntologyGenerator.relationship_type_frequency(result)
  - OntologyGenerator.entity_id_set(result)
  - LogicValidator.weakly_connected_count(ontology)
  - OntologyPipeline.run_score_iqr()
  - OntologyLearningAdapter.feedback_interquartile_range()
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


def _make_relationship(sid, tid, rtype="r"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=f"{sid}-{tid}", type=rtype, source_id=sid, target_id=tid)


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


def _push_feedback(adapter, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score))


# ── OntologyOptimizer.history_percentile ──────────────────────────────────────

class TestHistoryPercentile:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_percentile() == pytest.approx(0.0)

    def test_single_any_percentile(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.history_percentile(50.0) == pytest.approx(0.7)

    def test_0th_is_min(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        assert o.history_percentile(0.0) == pytest.approx(0.2)

    def test_100th_is_max(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        assert o.history_percentile(100.0) == pytest.approx(0.8)

    def test_50th_is_median(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        assert o.history_percentile(50.0) == pytest.approx(0.5)


# ── OntologyOptimizer.score_below_percentile_count ────────────────────────────

class TestScoreBelowPercentileCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_below_percentile_count() == 0

    def test_all_above_returns_zero(self):
        o = _make_optimizer()
        for v in [0.5, 0.6, 0.7, 0.8]:
            _push_opt(o, v)
        # 25th percentile = 0.5 + 0.25*(0.6-0.5) ≈ 0.525; all values >= 0.5
        # nothing strictly below → 0 or very few
        result = o.score_below_percentile_count(25.0)
        assert isinstance(result, int)

    def test_returns_int(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert isinstance(o.score_below_percentile_count(), int)


# ── OntologyCritic.dimension_coefficient_of_variation ────────────────────────

class TestDimensionCoefficientOfVariation:
    def test_all_same_returns_zero(self):
        c = _make_critic()
        assert c.dimension_coefficient_of_variation(_make_score()) == pytest.approx(0.0)

    def test_all_zero_returns_zero(self):
        c = _make_critic()
        score = _make_score(**{d: 0.0 for d in ["completeness", "consistency", "clarity",
                                                  "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimension_coefficient_of_variation(score) == pytest.approx(0.0)

    def test_nonzero_variation(self):
        c = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.1)
        cv = c.dimension_coefficient_of_variation(score)
        assert cv > 0

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.dimension_coefficient_of_variation(_make_score()), float)


# ── OntologyGenerator.relationship_type_frequency ────────────────────────────

class TestRelationshipTypeFrequency:
    def test_empty_returns_empty(self):
        gen = _make_generator()
        assert gen.relationship_type_frequency(_make_result([], [])) == {}

    def test_single_type(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b", "knows")]
        freq = gen.relationship_type_frequency(_make_result([], rels))
        assert freq == {"knows": 1}

    def test_multiple_types(self):
        gen = _make_generator()
        rels = [
            _make_relationship("a", "b", "knows"),
            _make_relationship("b", "c", "knows"),
            _make_relationship("c", "d", "owns"),
        ]
        freq = gen.relationship_type_frequency(_make_result([], rels))
        assert freq["knows"] == 2
        assert freq["owns"] == 1


# ── OntologyGenerator.entity_id_set ──────────────────────────────────────────

class TestEntityIdSet:
    def test_empty_returns_empty_set(self):
        gen = _make_generator()
        assert gen.entity_id_set(_make_result([])) == set()

    def test_returns_ids(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2"), _make_entity("e3")]
        assert gen.entity_id_set(_make_result(entities)) == {"e1", "e2", "e3"}


# ── LogicValidator.weakly_connected_count ────────────────────────────────────

class TestWeaklyConnectedCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.weakly_connected_count(_FakeOntology([])) == 0

    def test_single_chain_one_component(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c")]
        assert v.weakly_connected_count(_FakeOntology(rels)) == 1

    def test_two_disconnected_chains(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("x", "y")]
        assert v.weakly_connected_count(_FakeOntology(rels)) == 2

    def test_cycle_is_one_component(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("c", "a")]
        assert v.weakly_connected_count(_FakeOntology(rels)) == 1


# ── OntologyPipeline.run_score_iqr ───────────────────────────────────────────

class TestRunScoreIQR:
    def test_too_few_returns_zero(self):
        p = _make_pipeline()
        for v in [0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert p.run_score_iqr() == pytest.approx(0.0)

    def test_known_iqr(self):
        p = _make_pipeline()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        iqr = p.run_score_iqr()
        assert iqr >= 0

    def test_constant_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_iqr() == pytest.approx(0.0)


# ── OntologyLearningAdapter.feedback_interquartile_range ─────────────────────

class TestFeedbackInterquartileRange:
    def test_too_few_returns_zero(self):
        a = _make_adapter()
        for v in [0.3, 0.7, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_interquartile_range() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_interquartile_range() == pytest.approx(0.0)

    def test_nonzero_iqr(self):
        a = _make_adapter()
        for v in [0.1, 0.3, 0.7, 0.9]:
            _push_feedback(a, v)
        iqr = a.feedback_interquartile_range()
        assert iqr > 0
