"""Batch-162 feature tests.

Methods under test:
  - OntologyMediator.action_count_unique()
  - OntologyLearningAdapter.feedback_improvement_rate()
  - OntologyPipeline.run_score_deltas()
  - OntologyGenerator.relationship_type_counts(result)
"""
import pytest
from unittest.mock import MagicMock, patch


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    critic = MagicMock()
    return OntologyMediator(gen, critic)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


def _make_entity(eid, etype="Person"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid)


def _make_relationship(rid, rtype):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=rid, type=rtype, source_id="a", target_id="b")


def _make_result(entities=None, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=rels or [],
        confidence=1.0,
        metadata={},
        errors=[],
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


# ---------------------------------------------------------------------------
# OntologyMediator.action_count_unique
# ---------------------------------------------------------------------------

class TestActionCountUnique:
    def test_no_actions_returns_zero(self):
        m = _make_mediator()
        assert m.action_count_unique() == 0

    def test_one_action_type(self):
        m = _make_mediator()
        m._action_counts["add_entity"] = 3
        assert m.action_count_unique() == 1

    def test_multiple_action_types(self):
        m = _make_mediator()
        m._action_counts["add_entity"] = 2
        m._action_counts["remove_entity"] = 1
        m._action_counts["refine"] = 5
        assert m.action_count_unique() == 3


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_improvement_rate
# ---------------------------------------------------------------------------

class TestFeedbackImprovementRate:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_improvement_rate() == pytest.approx(0.0)

    def test_single_record_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_improvement_rate() == pytest.approx(0.0)

    def test_all_improving(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_improvement_rate() == pytest.approx(1.0)

    def test_no_improvement(self):
        a = _make_adapter()
        for v in [0.9, 0.7, 0.5]:
            _push_feedback(a, v)
        assert a.feedback_improvement_rate() == pytest.approx(0.0)

    def test_half_improving(self):
        a = _make_adapter()
        for v in [0.5, 0.8, 0.6, 0.9]:
            _push_feedback(a, v)
        # pairs: (0.5->0.8 up), (0.8->0.6 down), (0.6->0.9 up) = 2/3
        assert a.feedback_improvement_rate() == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_deltas
# ---------------------------------------------------------------------------

class TestRunScoreDeltas:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.run_score_deltas() == []

    def test_single_run_returns_empty(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_deltas() == []

    def test_two_runs(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.7)
        deltas = p.run_score_deltas()
        assert deltas == pytest.approx([0.4])

    def test_three_runs(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.4]:
            _push_run(p, v)
        deltas = p.run_score_deltas()
        assert deltas == pytest.approx([0.3, -0.1])

    def test_length_is_n_minus_one(self):
        p = _make_pipeline()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert len(p.run_score_deltas()) == 4


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_type_counts
# ---------------------------------------------------------------------------

class TestRelationshipTypeCounts:
    def test_empty_returns_empty(self):
        gen = _make_generator()
        result = _make_result()
        assert gen.relationship_type_counts(result) == {}

    def test_single_type(self):
        gen = _make_generator()
        rels = [_make_relationship("r1", "has"), _make_relationship("r2", "has")]
        result = _make_result(rels=rels)
        counts = gen.relationship_type_counts(result)
        assert counts == {"has": 2}

    def test_multiple_types(self):
        gen = _make_generator()
        rels = [
            _make_relationship("r1", "has"),
            _make_relationship("r2", "is"),
            _make_relationship("r3", "has"),
        ]
        result = _make_result(rels=rels)
        counts = gen.relationship_type_counts(result)
        assert counts == {"has": 2, "is": 1}
