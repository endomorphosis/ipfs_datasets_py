"""Batch-176 feature tests.

Methods under test:
  - OntologyOptimizer.history_kurtosis()
  - OntologyOptimizer.score_ewma(alpha)
  - OntologyCritic.dimension_min(score)
  - OntologyCritic.dimension_max(score)
  - OntologyCritic.dimension_range(score)
  - OntologyGenerator.entity_confidence_skewness(result)
  - OntologyGenerator.unique_relationship_types(result)
  - OntologyLearningAdapter.feedback_min()
  - OntologyLearningAdapter.feedback_max()
  - OntologyLearningAdapter.feedback_cumulative_sum()
"""
import pytest


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


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


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score))


# ── OntologyOptimizer.history_kurtosis ────────────────────────────────────────

class TestHistoryKurtosis:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_kurtosis() == pytest.approx(0.0)

    def test_fewer_than_four_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.history_kurtosis() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.history_kurtosis() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert isinstance(o.history_kurtosis(), float)


# ── OntologyOptimizer.score_ewma ──────────────────────────────────────────────

class TestScoreEWMA:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_ewma() == pytest.approx(0.0)

    def test_single_returns_score(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        assert o.score_ewma() == pytest.approx(0.8)

    def test_alpha_one_returns_last(self):
        o = _make_optimizer()
        _push_opt(o, 0.2)
        _push_opt(o, 0.9)
        assert o.score_ewma(alpha=1.0) == pytest.approx(0.9)

    def test_returns_float(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert isinstance(o.score_ewma(), float)


# ── OntologyCritic dimension_min / dimension_max / dimension_range ────────────

class TestDimensionMinMax:
    def test_dimension_min_returns_lowest(self):
        c = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.9)
        assert c.dimension_min(score) == "completeness"

    def test_dimension_max_returns_highest(self):
        c = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.9)
        assert c.dimension_max(score) == "consistency"

    def test_dimension_range_zero_when_all_same(self):
        c = _make_critic()
        assert c.dimension_range(_make_score()) == pytest.approx(0.0)

    def test_dimension_range_value(self):
        c = _make_critic()
        score = _make_score(completeness=0.2, consistency=0.8)
        assert c.dimension_range(score) >= 0.6


# ── OntologyGenerator.entity_confidence_skewness ─────────────────────────────

class TestEntityConfidenceSkewness:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_skewness(_make_result([])) == pytest.approx(0.0)

    def test_too_few_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.5), _make_entity("e2", 0.7)]
        assert gen.entity_confidence_skewness(_make_result(entities)) == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", 0.5) for i in range(5)]
        assert gen.entity_confidence_skewness(_make_result(entities)) == pytest.approx(0.0)

    def test_returns_float(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", c) for i, c in enumerate([0.1, 0.5, 0.5, 0.5, 0.9])]
        result = gen.entity_confidence_skewness(_make_result(entities))
        assert isinstance(result, float)


# ── OntologyGenerator.unique_relationship_types ───────────────────────────────

class TestUniqueRelationshipTypes:
    def test_empty_returns_empty_set(self):
        gen = _make_generator()
        assert gen.unique_relationship_types(_make_result([], [])) == set()

    def test_single_type(self):
        gen = _make_generator()
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        rels = [Relationship(id="r1", type="knows", source_id="a", target_id="b")]
        assert gen.unique_relationship_types(_make_result([], rels)) == {"knows"}

    def test_multiple_types(self):
        gen = _make_generator()
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        rels = [
            Relationship(id="r1", type="knows", source_id="a", target_id="b"),
            Relationship(id="r2", type="owns", source_id="b", target_id="c"),
            Relationship(id="r3", type="knows", source_id="c", target_id="a"),
        ]
        types = gen.unique_relationship_types(_make_result([], rels))
        assert types == {"knows", "owns"}


# ── OntologyLearningAdapter.feedback_min / feedback_max ──────────────────────

class TestFeedbackMinMax:
    def test_empty_min_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_min() == pytest.approx(0.0)

    def test_empty_max_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_max() == pytest.approx(0.0)

    def test_min_value(self):
        a = _make_adapter()
        for v in [0.9, 0.2, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_min() == pytest.approx(0.2)

    def test_max_value(self):
        a = _make_adapter()
        for v in [0.9, 0.2, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_max() == pytest.approx(0.9)


# ── OntologyLearningAdapter.feedback_cumulative_sum ──────────────────────────

class TestFeedbackCumulativeSum:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.feedback_cumulative_sum() == []

    def test_values(self):
        a = _make_adapter()
        _push_feedback(a, 0.2)
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.5)
        cs = a.feedback_cumulative_sum()
        assert cs == pytest.approx([0.2, 0.5, 1.0])

    def test_length_matches_feedback(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3, 0.4]:
            _push_feedback(a, v)
        assert len(a.feedback_cumulative_sum()) == 4
