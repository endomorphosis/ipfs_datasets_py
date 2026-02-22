"""Batch-186 feature tests.

Methods under test:
  - OntologyOptimizer.history_momentum_score(window, alpha)
  - OntologyOptimizer.score_signed_sum()
  - OntologyCritic.score_classification(score)
  - OntologyCritic.dimension_rank_order(score)
  - OntologyGenerator.relationship_bidirectionality_rate(result)
  - OntologyGenerator.entity_text_length_mean(result)
  - OntologyPipeline.run_score_delta_sum()
  - OntologyPipeline.run_score_improving_fraction()
  - OntologyLearningAdapter.feedback_weighted_mean(weights)
  - OntologyLearningAdapter.feedback_last_score()
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


def _make_entity(eid, text=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=text or eid)


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


# ── OntologyOptimizer.history_momentum_score ──────────────────────────────────

class TestHistoryMomentumScore:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_momentum_score() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_momentum_score() == pytest.approx(0.0)

    def test_improving_positive(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.history_momentum_score() > 0

    def test_declining_negative(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push_opt(o, v)
        assert o.history_momentum_score() < 0

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.5, 0.6]:
            _push_opt(o, v)
        assert isinstance(o.history_momentum_score(), float)


# ── OntologyOptimizer.score_signed_sum ────────────────────────────────────────

class TestScoreSignedSum:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_signed_sum() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_signed_sum() == pytest.approx(0.0)

    def test_improving_positive(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.8)
        assert o.score_signed_sum() == pytest.approx(0.5)

    def test_declining_negative(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        _push_opt(o, 0.3)
        assert o.score_signed_sum() == pytest.approx(-0.5)


# ── OntologyCritic.score_classification ──────────────────────────────────────

class TestScoreClassification:
    def test_excellent(self):
        c = _make_critic()
        score = _make_score(**{d: 1.0 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.score_classification(score) == "excellent"

    def test_poor(self):
        c = _make_critic()
        score = _make_score(**{d: 0.0 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.score_classification(score) == "poor"

    def test_returns_string(self):
        c = _make_critic()
        assert isinstance(c.score_classification(_make_score()), str)

    def test_valid_bucket(self):
        c = _make_critic()
        valid = {"excellent", "good", "fair", "poor"}
        assert c.score_classification(_make_score()) in valid


# ── OntologyCritic.dimension_rank_order ──────────────────────────────────────

class TestDimensionRankOrder:
    def test_returns_list_of_6(self):
        c = _make_critic()
        result = c.dimension_rank_order(_make_score())
        assert isinstance(result, list)
        assert len(result) == 6

    def test_contains_all_dims(self):
        c = _make_critic()
        dims = {"completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"}
        assert set(c.dimension_rank_order(_make_score())) == dims

    def test_sorted_desc(self):
        c = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.1)
        ranked = c.dimension_rank_order(score)
        assert ranked[0] == "completeness"


# ── OntologyGenerator.relationship_bidirectionality_rate ─────────────────────

class TestRelationshipBidirectionalityRate:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.relationship_bidirectionality_rate(_make_result([], [])) == pytest.approx(0.0)

    def test_unidirectional_returns_zero(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b")]
        assert gen.relationship_bidirectionality_rate(_make_result([], rels)) == pytest.approx(0.0)

    def test_bidirectional_pair(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b"), _make_relationship("b", "a")]
        rate = gen.relationship_bidirectionality_rate(_make_result([], rels))
        assert rate > 0

    def test_returns_float(self):
        gen = _make_generator()
        assert isinstance(gen.relationship_bidirectionality_rate(_make_result([], [])), float)


# ── OntologyGenerator.entity_text_length_mean ────────────────────────────────

class TestEntityTextLengthMean:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_text_length_mean(_make_result([])) == pytest.approx(0.0)

    def test_single_entity(self):
        gen = _make_generator()
        entities = [_make_entity("e1", text="hello")]
        assert gen.entity_text_length_mean(_make_result(entities)) == pytest.approx(5.0)

    def test_mean_of_lengths(self):
        gen = _make_generator()
        entities = [_make_entity("e1", text="hi"), _make_entity("e2", text="hello")]
        # lengths 2 and 5 → mean 3.5
        assert gen.entity_text_length_mean(_make_result(entities)) == pytest.approx(3.5)


# ── OntologyPipeline.run_score_delta_sum ──────────────────────────────────────

class TestRunScoreDeltaSum:
    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_delta_sum() == pytest.approx(0.0)

    def test_improving_positive(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.8)
        assert p.run_score_delta_sum() == pytest.approx(0.5)

    def test_declining_negative(self):
        p = _make_pipeline()
        _push_run(p, 0.8)
        _push_run(p, 0.2)
        assert p.run_score_delta_sum() == pytest.approx(-0.6)


# ── OntologyPipeline.run_score_improving_fraction ────────────────────────────

class TestRunScoreImprovingFraction:
    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_improving_fraction() == pytest.approx(0.0)

    def test_all_improving(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        assert p.run_score_improving_fraction() == pytest.approx(1.0)

    def test_none_improving(self):
        p = _make_pipeline()
        for v in [0.9, 0.6, 0.3]:
            _push_run(p, v)
        assert p.run_score_improving_fraction() == pytest.approx(0.0)

    def test_half_improving(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        _push_run(p, 0.7)
        _push_run(p, 0.5)
        assert p.run_score_improving_fraction() == pytest.approx(0.5)


# ── OntologyLearningAdapter.feedback_weighted_mean ───────────────────────────

class TestFeedbackWeightedMean:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_weighted_mean() == pytest.approx(0.0)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_weighted_mean() == pytest.approx(0.7)

    def test_linear_ramp_weights_recency(self):
        a = _make_adapter()
        _push_feedback(a, 0.1)
        _push_feedback(a, 0.9)
        # weights = [1, 2]; weighted = (0.1*1 + 0.9*2)/3 = 1.9/3
        assert a.feedback_weighted_mean() == pytest.approx(1.9 / 3, rel=1e-3)

    def test_uniform_weights_equal_mean(self):
        a = _make_adapter()
        for v in [0.3, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_weighted_mean(weights=[1, 1]) == pytest.approx(0.5)


# ── OntologyLearningAdapter.feedback_last_score ───────────────────────────────

class TestFeedbackLastScore:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_last_score() == pytest.approx(0.0)

    def test_returns_last(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_last_score() == pytest.approx(0.9)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        assert a.feedback_last_score() == pytest.approx(0.4)
