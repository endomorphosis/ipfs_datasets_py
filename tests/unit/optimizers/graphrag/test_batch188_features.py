"""Batch-188 feature tests.

Methods under test:
  - OntologyOptimizer.history_valley_count()
  - OntologyOptimizer.score_trend_correlation()
  - OntologyCritic.dimension_cosine_similarity(score1, score2)
  - OntologyCritic.score_distance(score1, score2)
  - OntologyGenerator.entity_confidence_std(result)
  - OntologyGenerator.entity_avg_property_count(result)
  - LogicValidator.self_loop_count(ontology)
  - LogicValidator.node_count(ontology)
  - OntologyPipeline.run_score_trend_direction()
  - OntologyLearningAdapter.feedback_improvement_count()
  - OntologyLearningAdapter.feedback_decline_count()
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


def _make_entity(eid, confidence=0.5, props=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence, properties=props or {})


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


# ── OntologyOptimizer.history_valley_count ───────────────────────────────────

class TestHistoryValleyCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_valley_count() == 0

    def test_monotone_returns_zero(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push_opt(o, v)
        assert o.history_valley_count() == 0

    def test_single_valley(self):
        o = _make_optimizer()
        for v in [0.9, 0.2, 0.9]:
            _push_opt(o, v)
        assert o.history_valley_count() == 1

    def test_multiple_valleys(self):
        o = _make_optimizer()
        for v in [0.8, 0.2, 0.9, 0.1, 0.8]:
            _push_opt(o, v)
        assert o.history_valley_count() == 2


# ── OntologyOptimizer.score_trend_correlation ─────────────────────────────────

class TestScoreTrendCorrelation:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_trend_correlation() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_trend_correlation() == pytest.approx(0.0)

    def test_perfect_uptrend_returns_one(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.score_trend_correlation() == pytest.approx(1.0, rel=1e-5)

    def test_perfect_downtrend_returns_minus_one(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5, 0.3, 0.1]:
            _push_opt(o, v)
        assert o.score_trend_correlation() == pytest.approx(-1.0, rel=1e-5)

    def test_in_range(self):
        o = _make_optimizer()
        for v in [0.5, 0.3, 0.7, 0.4]:
            _push_opt(o, v)
        c = o.score_trend_correlation()
        assert -1.0 <= c <= 1.0


# ── OntologyCritic.dimension_cosine_similarity ───────────────────────────────

class TestDimensionCosineSimilarity:
    def test_same_score_returns_one(self):
        c = _make_critic()
        s = _make_score()
        assert c.dimension_cosine_similarity(s, s) == pytest.approx(1.0, rel=1e-5)

    def test_zero_vector_returns_zero(self):
        c = _make_critic()
        zero = _make_score(**{d: 0.0 for d in ["completeness", "consistency", "clarity",
                                                  "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimension_cosine_similarity(zero, _make_score()) == pytest.approx(0.0)

    def test_in_range(self):
        c = _make_critic()
        s1 = _make_score(completeness=0.9, consistency=0.1)
        s2 = _make_score(completeness=0.1, consistency=0.9)
        sim = c.dimension_cosine_similarity(s1, s2)
        assert -1.0 <= sim <= 1.0

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.dimension_cosine_similarity(_make_score(), _make_score()), float)


# ── OntologyCritic.score_distance ─────────────────────────────────────────────

class TestScoreDistance:
    def test_same_score_returns_zero(self):
        c = _make_critic()
        s = _make_score()
        assert c.score_distance(s, s) == pytest.approx(0.0)

    def test_non_negative(self):
        c = _make_critic()
        assert c.score_distance(_make_score(), _make_score(completeness=0.9)) >= 0

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.score_distance(_make_score(), _make_score()), float)


# ── OntologyGenerator.entity_confidence_std ──────────────────────────────────

class TestEntityConfidenceStd:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_std(_make_result([])) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_std(_make_result([_make_entity("e1")])) == pytest.approx(0.0)

    def test_all_same_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.5), _make_entity("e2", 0.5)]
        assert gen.entity_confidence_std(_make_result(entities)) == pytest.approx(0.0)

    def test_nonzero_for_varied(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.1), _make_entity("e2", 0.9)]
        assert gen.entity_confidence_std(_make_result(entities)) > 0


# ── OntologyGenerator.entity_avg_property_count ───────────────────────────────

class TestEntityAvgPropertyCount:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_avg_property_count(_make_result([])) == pytest.approx(0.0)

    def test_no_properties_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        assert gen.entity_avg_property_count(_make_result(entities)) == pytest.approx(0.0)

    def test_average(self):
        gen = _make_generator()
        entities = [
            _make_entity("e1", props={"k1": "v1", "k2": "v2"}),
            _make_entity("e2"),
        ]
        # (2 + 0) / 2 = 1.0
        assert gen.entity_avg_property_count(_make_result(entities)) == pytest.approx(1.0)


# ── LogicValidator.self_loop_count ────────────────────────────────────────────

class TestSelfLoopCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.self_loop_count({"relationships": []}) == 0

    def test_no_self_loops(self):
        v = _make_validator()
        ont = {"relationships": [
            {"source_id": "a", "target_id": "b", "type": "r"},
            {"source_id": "b", "target_id": "c", "type": "r"},
        ]}
        assert v.self_loop_count(ont) == 0

    def test_one_self_loop(self):
        v = _make_validator()
        ont = {"relationships": [
            {"source_id": "a", "target_id": "a", "type": "r"},
            {"source_id": "b", "target_id": "c", "type": "r"},
        ]}
        assert v.self_loop_count(ont) == 1

    def test_multiple_self_loops(self):
        v = _make_validator()
        ont = {"relationships": [
            {"source_id": "a", "target_id": "a", "type": "r"},
            {"source_id": "b", "target_id": "b", "type": "r"},
        ]}
        assert v.self_loop_count(ont) == 2


# ── LogicValidator.node_count ─────────────────────────────────────────────────

class TestNodeCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.node_count(_FakeOntology([])) == 0

    def test_single_edge(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        assert v.node_count(_FakeOntology(rels)) == 2

    def test_shared_nodes(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c")]
        # nodes: a, b, c
        assert v.node_count(_FakeOntology(rels)) == 3


# ── OntologyPipeline.run_score_trend_direction ────────────────────────────────

class TestRunScoreTrendDirection:
    def test_single_run_returns_stable(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_trend_direction() == "stable"

    def test_improving(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert p.run_score_trend_direction() == "improving"

    def test_declining(self):
        p = _make_pipeline()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push_run(p, v)
        assert p.run_score_trend_direction() == "declining"

    def test_returns_string(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        _push_run(p, 0.5)
        assert isinstance(p.run_score_trend_direction(), str)


# ── OntologyLearningAdapter.feedback_improvement_count ───────────────────────

class TestFeedbackImprovementCount:
    def test_single_record_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_improvement_count() == 0

    def test_all_improving(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_improvement_count() == 2

    def test_none_improving(self):
        a = _make_adapter()
        for v in [0.9, 0.7, 0.5]:
            _push_feedback(a, v)
        assert a.feedback_improvement_count() == 0


# ── OntologyLearningAdapter.feedback_decline_count ───────────────────────────

class TestFeedbackDeclineCount:
    def test_single_record_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_decline_count() == 0

    def test_all_declining(self):
        a = _make_adapter()
        for v in [0.9, 0.7, 0.5]:
            _push_feedback(a, v)
        assert a.feedback_decline_count() == 2

    def test_none_declining(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_decline_count() == 0
