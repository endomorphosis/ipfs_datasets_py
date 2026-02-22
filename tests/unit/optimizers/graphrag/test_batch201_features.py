"""Batch-201 feature tests.

Methods under test:
  - OntologyOptimizer.history_above_threshold_streak(threshold)
  - OntologyOptimizer.score_above_threshold_longest_streak(threshold)
  - OntologyGenerator.entity_max_property_count(result)
  - OntologyGenerator.entity_min_confidence_above(result, threshold)
  - OntologyGenerator.relationship_avg_type_length(result)
  - LogicValidator.node_in_degree(ontology)
  - LogicValidator.node_out_degree(ontology)
  - OntologyPipeline.run_score_above_first()
  - OntologyLearningAdapter.feedback_recent_positive_count(n, threshold)
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


def _make_entity(eid, confidence=1.0, properties=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence, properties=properties or {})


def _make_rel_mock(rel_type="is_a"):
    r = MagicMock()
    r.type = rel_type
    r.source_id = "src"
    r.target_id = "tgt"
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


# ── OntologyOptimizer.history_above_threshold_streak ─────────────────────────

class TestHistoryAboveThresholdStreak:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_above_threshold_streak() == 0

    def test_single_above_returns_one(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        assert o.history_above_threshold_streak() == 1

    def test_single_below_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        assert o.history_above_threshold_streak() == 0

    def test_trailing_streak(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.8, 0.9]:
            _push_opt(o, v)
        assert o.history_above_threshold_streak() == 3

    def test_streak_broken_in_middle(self):
        o = _make_optimizer()
        for v in [0.9, 0.9, 0.3, 0.9]:
            _push_opt(o, v)
        assert o.history_above_threshold_streak() == 1


# ── OntologyOptimizer.score_above_threshold_longest_streak ───────────────────

class TestScoreAboveThresholdLongestStreak:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_above_threshold_longest_streak() == 0

    def test_all_above(self):
        o = _make_optimizer()
        for v in [0.6, 0.7, 0.8]:
            _push_opt(o, v)
        assert o.score_above_threshold_longest_streak() == 3

    def test_split_streaks_returns_longest(self):
        o = _make_optimizer()
        for v in [0.8, 0.8, 0.3, 0.7, 0.7, 0.7]:
            _push_opt(o, v)
        assert o.score_above_threshold_longest_streak() == 3


# ── OntologyGenerator.entity_max_property_count ──────────────────────────────

class TestEntityMaxPropertyCount:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_max_property_count(r) == 0

    def test_no_properties_returns_zero(self):
        g = _make_generator()
        r = _make_result([_make_entity("a"), _make_entity("b")])
        assert g.entity_max_property_count(r) == 0

    def test_max_across_entities(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("a", properties={"x": 1}),
            _make_entity("b", properties={"x": 1, "y": 2, "z": 3}),
            _make_entity("c", properties={"x": 1, "y": 2}),
        ])
        assert g.entity_max_property_count(r) == 3


# ── OntologyGenerator.entity_min_confidence_above ────────────────────────────

class TestEntityMinConfidenceAbove:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_min_confidence_above(r) == pytest.approx(0.0)

    def test_no_qualifying_returns_zero(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", confidence=0.3)])
        assert g.entity_min_confidence_above(r, threshold=0.5) == pytest.approx(0.0)

    def test_returns_min_of_qualifying(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("a", confidence=0.6),
            _make_entity("b", confidence=0.8),
            _make_entity("c", confidence=0.3),
        ])
        assert g.entity_min_confidence_above(r, threshold=0.5) == pytest.approx(0.6)


# ── OntologyGenerator.relationship_avg_type_length ───────────────────────────

class TestRelationshipAvgTypeLength:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_avg_type_length(r) == pytest.approx(0.0)

    def test_single_relationship(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock("is_a")])
        assert g.relationship_avg_type_length(r) == pytest.approx(4.0)

    def test_average_of_two(self):
        g = _make_generator()
        r = _make_result(relationships=[
            _make_rel_mock("ab"),
            _make_rel_mock("abcd"),
        ])
        assert g.relationship_avg_type_length(r) == pytest.approx(3.0)


# ── LogicValidator.node_in_degree ─────────────────────────────────────────────

class TestNodeInDegree:
    def test_empty_returns_empty_dict(self):
        v = _make_validator()
        assert v.node_in_degree({}) == {}

    def test_in_degrees_correct(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "b"},
            {"source": "c", "target": "b"},
        ]}
        result = v.node_in_degree(onto)
        assert result == {"b": 3}

    def test_multiple_targets(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]}
        result = v.node_in_degree(onto)
        assert result["b"] == 1
        assert result["c"] == 1


# ── LogicValidator.node_out_degree ─────────────────────────────────────────────

class TestNodeOutDegree:
    def test_empty_returns_empty_dict(self):
        v = _make_validator()
        assert v.node_out_degree({}) == {}

    def test_out_degrees_correct(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "c"},
            {"source": "b", "target": "c"},
        ]}
        result = v.node_out_degree(onto)
        assert result["a"] == 2
        assert result["b"] == 1


# ── OntologyPipeline.run_score_above_first ────────────────────────────────────

class TestRunScoreAboveFirst:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_above_first() == 0

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_above_first() == 0

    def test_none_above_first(self):
        p = _make_pipeline()
        for v in [0.9, 0.5, 0.3]:
            _push_run(p, v)
        assert p.run_score_above_first() == 0

    def test_count_above_first(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.2]:
            _push_run(p, v)
        # first=0.3; 0.5 and 0.7 are above → 2
        assert p.run_score_above_first() == 2


# ── OntologyLearningAdapter.feedback_recent_positive_count ───────────────────

class TestFeedbackRecentPositiveCount:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_recent_positive_count() == 0

    def test_all_positive(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_recent_positive_count(n=3, threshold=0.5) == 3

    def test_only_recent_n_checked(self):
        a = _make_adapter()
        for v in [0.9, 0.9, 0.9, 0.1, 0.1]:
            _push_feedback(a, v)
        # last 3 are [0.9, 0.1, 0.1]
        assert a.feedback_recent_positive_count(n=3, threshold=0.5) == 1

    def test_threshold_boundary(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        # >= threshold → positive
        assert a.feedback_recent_positive_count(n=5, threshold=0.5) == 1
