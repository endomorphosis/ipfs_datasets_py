"""Batch-181 feature tests.

Methods under test:
  - OntologyOptimizer.history_entropy_change()
  - OntologyOptimizer.score_variance_trend()
  - OntologyCritic.dimensions_at_max_count(score, threshold)
  - OntologyCritic.dimension_harmonic_mean(score)
  - OntologyGenerator.entity_source_span_coverage(result)
  - OntologyGenerator.relationship_density(result)
  - OntologyPipeline.score_variance_trend()
  - OntologyPipeline.run_score_coefficient_of_variation()
  - OntologyLearningAdapter.feedback_entropy()
  - OntologyLearningAdapter.feedback_positive_fraction()
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


def _make_entity(eid, confidence=0.5, source_span=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence, source_span=source_span)


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


# ── OntologyOptimizer.history_entropy_change ─────────────────────────────────

class TestHistoryEntropyChange:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_entropy_change() == pytest.approx(0.0)

    def test_too_few_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.history_entropy_change() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9, 0.2, 0.4, 0.6]:
            _push_opt(o, v)
        result = o.history_entropy_change()
        assert isinstance(result, float)

    def test_constant_history_returns_zero(self):
        o = _make_optimizer()
        for _ in range(8):
            _push_opt(o, 0.5)
        assert o.history_entropy_change() == pytest.approx(0.0)


# ── OntologyOptimizer.score_variance_trend ────────────────────────────────────

class TestScoreVarianceTrend:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_variance_trend() == pytest.approx(0.0)

    def test_too_few_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.7]:
            _push_opt(o, v)
        assert o.score_variance_trend() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(8):
            _push_opt(o, 0.5)
        assert o.score_variance_trend() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.5, 0.5, 0.1, 0.9]:
            _push_opt(o, v)
        assert isinstance(o.score_variance_trend(), float)


# ── OntologyCritic.dimensions_at_max_count ───────────────────────────────────

class TestDimensionsAtMaxCount:
    def test_none_at_max(self):
        c = _make_critic()
        assert c.dimensions_at_max_count(_make_score()) == 0

    def test_some_at_max(self):
        c = _make_critic()
        score = _make_score(completeness=0.95, consistency=0.95)
        assert c.dimensions_at_max_count(score, threshold=0.9) == 2

    def test_all_at_max(self):
        c = _make_critic()
        score = _make_score(**{d: 1.0 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimensions_at_max_count(score, threshold=0.9) == 6

    def test_returns_int(self):
        c = _make_critic()
        assert isinstance(c.dimensions_at_max_count(_make_score()), int)


# ── OntologyCritic.dimension_harmonic_mean ───────────────────────────────────

class TestDimensionHarmonicMean:
    def test_all_same_equals_that_value(self):
        c = _make_critic()
        assert c.dimension_harmonic_mean(_make_score()) == pytest.approx(0.5, rel=1e-3)

    def test_all_one(self):
        c = _make_critic()
        score = _make_score(**{d: 1.0 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimension_harmonic_mean(score) == pytest.approx(1.0, rel=1e-3)

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.dimension_harmonic_mean(_make_score()), float)

    def test_harmonic_leq_arithmetic(self):
        c = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.1)
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        arith = sum(getattr(score, d) for d in dims) / 6
        assert c.dimension_harmonic_mean(score) <= arith + 1e-9


# ── OntologyGenerator.entity_source_span_coverage ───────────────────────────

class TestEntitySourceSpanCoverage:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_source_span_coverage(_make_result([])) == pytest.approx(0.0)

    def test_none_with_span_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        assert gen.entity_source_span_coverage(_make_result(entities)) == pytest.approx(0.0)

    def test_half_with_span(self):
        gen = _make_generator()
        entities = [_make_entity("e1", source_span=(0, 5)), _make_entity("e2")]
        assert gen.entity_source_span_coverage(_make_result(entities)) == pytest.approx(0.5)

    def test_all_with_span(self):
        gen = _make_generator()
        entities = [_make_entity("e1", source_span=(0, 5)), _make_entity("e2", source_span=(6, 10))]
        assert gen.entity_source_span_coverage(_make_result(entities)) == pytest.approx(1.0)


# ── OntologyGenerator.relationship_density ───────────────────────────────────

class TestRelationshipDensity:
    def test_empty_entities_returns_zero(self):
        gen = _make_generator()
        assert gen.relationship_density(_make_result([])) == pytest.approx(0.0)

    def test_no_rels_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        assert gen.relationship_density(_make_result(entities)) == pytest.approx(0.0)

    def test_ratio(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        rels = [_make_relationship("e1", "e2")]
        assert gen.relationship_density(_make_result(entities, rels)) == pytest.approx(0.5)


# ── OntologyPipeline.score_variance_trend ────────────────────────────────────

class TestPipelineScoreVarianceTrend:
    def test_too_few_returns_zero(self):
        p = _make_pipeline()
        for v in [0.3, 0.7]:
            _push_run(p, v)
        assert p.score_variance_trend() == pytest.approx(0.0)

    def test_returns_float(self):
        p = _make_pipeline()
        for v in [0.5, 0.5, 0.2, 0.8]:
            _push_run(p, v)
        assert isinstance(p.score_variance_trend(), float)

    def test_constant_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.score_variance_trend() == pytest.approx(0.0)


# ── OntologyPipeline.run_score_coefficient_of_variation ──────────────────────

class TestRunScoreCoefficientOfVariation:
    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.run_score_coefficient_of_variation() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_coefficient_of_variation() == pytest.approx(0.0)

    def test_returns_float(self):
        p = _make_pipeline()
        for v in [0.3, 0.7]:
            _push_run(p, v)
        assert isinstance(p.run_score_coefficient_of_variation(), float)


# ── OntologyLearningAdapter.feedback_entropy ─────────────────────────────────

class TestFeedbackEntropy:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_entropy() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_entropy() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_entropy() == pytest.approx(0.0)

    def test_diverse_has_positive_entropy(self):
        a = _make_adapter()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_entropy() > 0


# ── OntologyLearningAdapter.feedback_positive_fraction ───────────────────────

class TestFeedbackPositiveFraction:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_positive_fraction() == pytest.approx(0.0)

    def test_all_positive(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_positive_fraction() == pytest.approx(1.0)

    def test_none_positive(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3]:
            _push_feedback(a, v)
        assert a.feedback_positive_fraction() == pytest.approx(0.0)

    def test_half_positive(self):
        a = _make_adapter()
        for v in [0.3, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_positive_fraction() == pytest.approx(0.5)
