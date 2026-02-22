"""Batch-202 feature tests.

Methods under test:
  - OntologyOptimizer.score_delta_abs_mean()
  - OntologyOptimizer.history_improving_count()
  - OntologyGenerator.entity_unique_types(result)
  - OntologyGenerator.relationship_bidirectional_count(result)
  - LogicValidator.bridge_nodes(ontology)
  - OntologyPipeline.run_score_below_last()
  - OntologyLearningAdapter.feedback_oscillation_count(threshold)
  - OntologyMediator.action_diversity_ratio()
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


def _make_entity(eid, etype="T"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid)


def _make_rel_mock(source_id, target_id):
    r = MagicMock()
    r.source_id = source_id
    r.target_id = target_id
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


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    return OntologyMediator(generator=MagicMock(), critic=MagicMock())


# ── OntologyOptimizer.score_delta_abs_mean ────────────────────────────────────

class TestScoreDeltaAbsMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_delta_abs_mean() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_delta_abs_mean() == pytest.approx(0.0)

    def test_two_entries(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.score_delta_abs_mean() == pytest.approx(0.4)

    def test_known_mean(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.3, 0.7]:
            _push_opt(o, v)
        # deltas: 0.2, 0.1, 0.4 → mean = 0.7/3 ≈ 0.2333
        assert o.score_delta_abs_mean() == pytest.approx(0.7 / 3, rel=1e-6)


# ── OntologyOptimizer.history_improving_count ────────────────────────────────

class TestHistoryImprovingCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_improving_count() == 0

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_improving_count() == 0

    def test_monotone_decreasing(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.history_improving_count() == 0

    def test_monotone_increasing(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.history_improving_count() == 2

    def test_mixed(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.4, 0.7]:
            _push_opt(o, v)
        # improvements at: 0→1 (0.5>0.3), 2→3 (0.7>0.4) → 2
        assert o.history_improving_count() == 2


# ── OntologyGenerator.entity_unique_types ────────────────────────────────────

class TestEntityUniqueTypes:
    def test_empty_returns_empty_set(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_unique_types(r) == set()

    def test_single_type(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", "Person"), _make_entity("b", "Person")])
        assert g.entity_unique_types(r) == {"Person"}

    def test_multiple_types(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("a", "Person"),
            _make_entity("b", "Org"),
            _make_entity("c", "Place"),
        ])
        assert g.entity_unique_types(r) == {"Person", "Org", "Place"}


# ── OntologyGenerator.relationship_bidirectional_count ───────────────────────

class TestRelationshipBidirectionalCount:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_bidirectional_count(r) == 0

    def test_unidirectional_returns_zero(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("c", "d")]
        r = _make_result(relationships=rels)
        assert g.relationship_bidirectional_count(r) == 0

    def test_one_bidirectional_pair(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("b", "a")]
        r = _make_result(relationships=rels)
        assert g.relationship_bidirectional_count(r) == 1

    def test_two_bidirectional_pairs(self):
        g = _make_generator()
        rels = [
            _make_rel_mock("a", "b"), _make_rel_mock("b", "a"),
            _make_rel_mock("c", "d"), _make_rel_mock("d", "c"),
        ]
        r = _make_result(relationships=rels)
        assert g.relationship_bidirectional_count(r) == 2


# ── LogicValidator.bridge_nodes ───────────────────────────────────────────────

class TestBridgeNodes:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.bridge_nodes({}) == []

    def test_no_bridges(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        # a is only source, b is only target → no bridge
        result = v.bridge_nodes(onto)
        assert result == []

    def test_bridge_node_identified(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "bridge"},
            {"source": "bridge", "target": "c"},
        ]}
        result = v.bridge_nodes(onto)
        assert result == ["bridge"]

    def test_returns_sorted(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "z"},
            {"source": "z", "target": "b"},
            {"source": "c", "target": "m"},
            {"source": "m", "target": "d"},
        ]}
        result = v.bridge_nodes(onto)
        assert result == sorted(result)


# ── OntologyPipeline.run_score_below_last ─────────────────────────────────────

class TestRunScoreBelowLast:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_below_last() == 0

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_below_last() == 0

    def test_all_below_last(self):
        p = _make_pipeline()
        for v in [0.1, 0.2, 0.3]:
            _push_run(p, v)
        # last=0.3; 0.1 and 0.2 are below → 2
        assert p.run_score_below_last() == 2

    def test_none_below_last(self):
        p = _make_pipeline()
        for v in [0.9, 0.7, 0.5]:
            _push_run(p, v)
        assert p.run_score_below_last() == 0


# ── OntologyLearningAdapter.feedback_oscillation_count ───────────────────────

class TestFeedbackOscillationCount:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_oscillation_count() == 0

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_oscillation_count() == 0

    def test_all_above_no_oscillation(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_oscillation_count() == 0

    def test_single_crossing(self):
        a = _make_adapter()
        _push_feedback(a, 0.8)
        _push_feedback(a, 0.3)
        assert a.feedback_oscillation_count() == 1

    def test_multiple_oscillations(self):
        a = _make_adapter()
        for v in [0.8, 0.3, 0.7, 0.2]:
            _push_feedback(a, v)
        # crossings at: 0.8→0.3, 0.3→0.7, 0.7→0.2 → 3
        assert a.feedback_oscillation_count() == 3


# ── OntologyMediator.action_diversity_ratio ──────────────────────────────────

class TestActionDiversityRatio:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_diversity_ratio() == pytest.approx(0.0)

    def test_single_action_type_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"refine": 1}
        assert m.action_diversity_ratio() == pytest.approx(1.0)

    def test_two_types_equal_count(self):
        m = _make_mediator()
        m._action_counts = {"a": 1, "b": 1}
        # 2 types / 2 total = 1.0
        assert m.action_diversity_ratio() == pytest.approx(1.0)

    def test_dominated_ratio(self):
        m = _make_mediator()
        m._action_counts = {"a": 9, "b": 1}
        # 2 types / 10 total = 0.2
        assert m.action_diversity_ratio() == pytest.approx(0.2)
