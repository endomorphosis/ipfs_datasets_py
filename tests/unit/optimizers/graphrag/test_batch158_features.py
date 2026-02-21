"""Batch-158 feature tests.

Methods under test:
  - OntologyCritic.all_dimensions_above(score, threshold)
  - OntologyLearningAdapter.feedback_in_range(lo, hi)
  - OntologyGenerator.avg_relationship_count(result)
  - OntologyOptimizer.history_variance()
"""
import pytest
from unittest.mock import MagicMock


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


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_entity(eid):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="Test", text=eid)


def _make_relationship(sid, oid):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=f"{sid}-{oid}", type="rel", source_id=sid, target_id=oid)


def _make_result(entities, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities,
        relationships=relationships or [],
        confidence=1.0,
        metadata={},
        errors=[],
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


# ---------------------------------------------------------------------------
# OntologyCritic.all_dimensions_above
# ---------------------------------------------------------------------------

class TestAllDimensionsAbove:
    def test_all_above_returns_true(self):
        critic = _make_critic()
        score = _make_score(completeness=0.8, consistency=0.9, clarity=0.7,
                            granularity=0.6, relationship_coherence=0.75, domain_alignment=0.85)
        assert critic.all_dimensions_above(score, threshold=0.5) is True

    def test_one_below_returns_false(self):
        critic = _make_critic()
        score = _make_score(completeness=0.3)  # below 0.5
        assert critic.all_dimensions_above(score, threshold=0.5) is False

    def test_equal_to_threshold_returns_false(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        assert critic.all_dimensions_above(score, threshold=0.5) is False

    def test_custom_threshold(self):
        critic = _make_critic()
        score = _make_score(completeness=0.2, consistency=0.2, clarity=0.2,
                            granularity=0.2, relationship_coherence=0.2, domain_alignment=0.2)
        assert critic.all_dimensions_above(score, threshold=0.1) is True


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_in_range
# ---------------------------------------------------------------------------

class TestFeedbackInRange:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.feedback_in_range(0.3, 0.7) == []

    def test_all_in_range(self):
        a = _make_adapter()
        for v in [0.4, 0.5, 0.6]:
            _push_feedback(a, v)
        result = a.feedback_in_range(0.3, 0.7)
        assert len(result) == 3

    def test_none_in_range(self):
        a = _make_adapter()
        for v in [0.1, 0.9]:
            _push_feedback(a, v)
        result = a.feedback_in_range(0.4, 0.6)
        assert result == []

    def test_boundary_inclusive(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.7)
        result = a.feedback_in_range(0.3, 0.7)
        assert len(result) == 2

    def test_partial_in_range(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8]:
            _push_feedback(a, v)
        result = a.feedback_in_range(0.4, 0.6)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# OntologyGenerator.avg_relationship_count
# ---------------------------------------------------------------------------

class TestAvgRelationshipCount:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.avg_relationship_count(result) == pytest.approx(0.0)

    def test_no_relationships(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        result = _make_result(entities)
        assert gen.avg_relationship_count(result) == pytest.approx(0.0)

    def test_equal_entities_and_relationships(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        rels = [Relationship(id="r1", type="rel", source_id="e1", target_id="e2"),
                Relationship(id="r2", type="rel", source_id="e2", target_id="e1")]
        result = _make_result(entities, rels)
        assert gen.avg_relationship_count(result) == pytest.approx(1.0)

    def test_more_relationships_than_entities(self):
        gen = _make_generator()
        entities = [_make_entity("e1")]
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        rels = [Relationship(id="r1", type="rel", source_id="e1", target_id="e1"),
                Relationship(id="r2", type="rel", source_id="e1", target_id="e1")]
        result = _make_result(entities, rels)
        assert gen.avg_relationship_count(result) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_variance
# ---------------------------------------------------------------------------

class TestHistoryVariance:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_variance() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_variance() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.6)
        assert o.history_variance() == pytest.approx(0.0)

    def test_known_variance(self):
        o = _make_optimizer()
        _push_opt(o, 0.0)
        _push_opt(o, 1.0)
        # population variance of [0, 1] = 0.25
        assert o.history_variance() == pytest.approx(0.25)

    def test_non_negative(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        assert o.history_variance() >= 0.0
