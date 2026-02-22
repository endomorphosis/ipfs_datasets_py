"""Batch-187 feature tests.

Methods under test:
  - OntologyOptimizer.score_acceleration()
  - OntologyOptimizer.history_peak_count()
  - OntologyCritic.dimension_normalized_vector(score)
  - OntologyCritic.score_above_median(score, history)
  - OntologyGenerator.entity_confidence_mode(result)
  - OntologyGenerator.relationship_types_count(result)
  - OntologyPipeline.run_score_acceleration()
  - OntologyPipeline.run_score_peak_count()
  - OntologyLearningAdapter.feedback_acceleration()
  - OntologyLearningAdapter.feedback_first_score()
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


# ── OntologyOptimizer.score_acceleration ─────────────────────────────────────

class TestScoreAcceleration:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_acceleration() == pytest.approx(0.0)

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.score_acceleration() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.score_acceleration() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.9]:
            _push_opt(o, v)
        assert isinstance(o.score_acceleration(), float)


# ── OntologyOptimizer.history_peak_count ──────────────────────────────────────

class TestHistoryPeakCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_peak_count() == 0

    def test_monotone_returns_zero(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.history_peak_count() == 0

    def test_single_peak(self):
        o = _make_optimizer()
        for v in [0.3, 0.9, 0.3]:
            _push_opt(o, v)
        assert o.history_peak_count() == 1

    def test_multiple_peaks(self):
        o = _make_optimizer()
        for v in [0.3, 0.9, 0.3, 0.8, 0.2]:
            _push_opt(o, v)
        assert o.history_peak_count() == 2


# ── OntologyCritic.dimension_normalized_vector ───────────────────────────────

class TestDimensionNormalizedVector:
    def test_returns_list_of_6(self):
        c = _make_critic()
        result = c.dimension_normalized_vector(_make_score())
        assert len(result) == 6

    def test_unit_length(self):
        c = _make_critic()
        vec = c.dimension_normalized_vector(_make_score())
        mag = sum(v ** 2 for v in vec) ** 0.5
        assert mag == pytest.approx(1.0, rel=1e-5)

    def test_all_zero_returns_zeros(self):
        c = _make_critic()
        score = _make_score(**{d: 0.0 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimension_normalized_vector(score) == [0.0] * 6


# ── OntologyCritic.score_above_median ────────────────────────────────────────

class TestScoreAboveMedian:
    def test_empty_history_returns_true(self):
        c = _make_critic()
        assert c.score_above_median(_make_score(), []) is True

    def test_above_median(self):
        c = _make_critic()
        top = _make_score(**{d: 1.0 for d in ["completeness", "consistency", "clarity",
                                                "granularity", "relationship_coherence", "domain_alignment"]})
        history = [_make_score() for _ in range(5)]
        assert c.score_above_median(top, history) is True

    def test_below_median(self):
        c = _make_critic()
        bottom = _make_score(**{d: 0.0 for d in ["completeness", "consistency", "clarity",
                                                    "granularity", "relationship_coherence", "domain_alignment"]})
        history = [_make_score() for _ in range(5)]
        assert c.score_above_median(bottom, history) is False

    def test_returns_bool(self):
        c = _make_critic()
        assert isinstance(c.score_above_median(_make_score(), [_make_score()]), bool)


# ── OntologyGenerator.entity_confidence_mode ─────────────────────────────────

class TestEntityConfidenceMode:
    def test_empty_returns_half(self):
        gen = _make_generator()
        assert gen.entity_confidence_mode(_make_result([])) == pytest.approx(0.5)

    def test_returns_float(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.5)]
        assert isinstance(gen.entity_confidence_mode(_make_result(entities)), float)

    def test_dominant_bin(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", 0.9) for i in range(5)] + [_make_entity("ex", 0.1)]
        result = gen.entity_confidence_mode(_make_result(entities))
        # mode should be near 0.9
        assert result >= 0.8


# ── OntologyGenerator.relationship_types_count ───────────────────────────────

class TestRelationshipTypesCount:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.relationship_types_count(_make_result([], [])) == 0

    def test_single_type(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b", "knows"), _make_relationship("b", "c", "knows")]
        assert gen.relationship_types_count(_make_result([], rels)) == 1

    def test_multiple_types(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b", "knows"), _make_relationship("b", "c", "owns")]
        assert gen.relationship_types_count(_make_result([], rels)) == 2


# ── OntologyPipeline.run_score_acceleration ──────────────────────────────────

class TestRunScoreAcceleration:
    def test_two_runs_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.7)
        assert p.run_score_acceleration() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_acceleration() == pytest.approx(0.0)

    def test_returns_float(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.9]:
            _push_run(p, v)
        assert isinstance(p.run_score_acceleration(), float)


# ── OntologyPipeline.run_score_peak_count ────────────────────────────────────

class TestRunScorePeakCount:
    def test_too_few_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        _push_run(p, 0.7)
        assert p.run_score_peak_count() == 0

    def test_single_peak(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.3]:
            _push_run(p, v)
        assert p.run_score_peak_count() == 1

    def test_monotone_returns_zero(self):
        p = _make_pipeline()
        for v in [0.1, 0.5, 0.9]:
            _push_run(p, v)
        assert p.run_score_peak_count() == 0


# ── OntologyLearningAdapter.feedback_acceleration ────────────────────────────

class TestFeedbackAcceleration:
    def test_two_records_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.7)
        assert a.feedback_acceleration() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_acceleration() == pytest.approx(0.0)

    def test_returns_float(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.9]:
            _push_feedback(a, v)
        assert isinstance(a.feedback_acceleration(), float)


# ── OntologyLearningAdapter.feedback_first_score ─────────────────────────────

class TestFeedbackFirstScore:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_first_score() == pytest.approx(0.0)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        assert a.feedback_first_score() == pytest.approx(0.4)

    def test_returns_oldest(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_first_score() == pytest.approx(0.3)
