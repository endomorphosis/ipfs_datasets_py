"""Batch-209 feature tests.

Methods under test:
  - OntologyOptimizer.history_rank_of_last()
  - OntologyOptimizer.score_nearest_neighbor_delta()
  - OntologyGenerator.entity_multi_property_count(result)
  - OntologyGenerator.relationship_avg_id_pair_length(result)
  - LogicValidator.has_disconnected_subgraphs(ontology)
  - OntologyPipeline.run_score_max_run()
  - OntologyLearningAdapter.feedback_z_score_last()
  - OntologyMediator.action_uniformity_index()
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


def _make_entity(eid, properties=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, properties=properties or {})


def _make_rel_mock(source_id="src", target_id="tgt"):
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


# ── OntologyOptimizer.history_rank_of_last ───────────────────────────────────

class TestHistoryRankOfLast:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_rank_of_last() == 0

    def test_single_entry_rank_one(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_rank_of_last() == 1

    def test_last_is_best_rank_one(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_rank_of_last() == 1

    def test_last_is_worst_rank_last(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.1]:
            _push_opt(o, v)
        assert o.history_rank_of_last() == 3


# ── OntologyOptimizer.score_nearest_neighbor_delta ───────────────────────────

class TestScoreNearestNeighborDelta:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_nearest_neighbor_delta() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_nearest_neighbor_delta() == pytest.approx(0.0)

    def test_known_delta(self):
        o = _make_optimizer()
        for v in [0.3, 0.8]:
            _push_opt(o, v)
        assert o.score_nearest_neighbor_delta() == pytest.approx(0.5)

    def test_always_non_negative(self):
        o = _make_optimizer()
        for v in [0.9, 0.3]:
            _push_opt(o, v)
        assert o.score_nearest_neighbor_delta() >= 0.0


# ── OntologyGenerator.entity_multi_property_count ────────────────────────────

class TestEntityMultiPropertyCount:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_multi_property_count(r) == 0

    def test_no_multi_property_entities(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("a", {"x": 1}),
            _make_entity("b", {}),
        ])
        assert g.entity_multi_property_count(r) == 0

    def test_counts_multi_property(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("a", {"x": 1, "y": 2}),
            _make_entity("b", {"z": 3}),
            _make_entity("c", {"p": 4, "q": 5, "r": 6}),
        ])
        assert g.entity_multi_property_count(r) == 2


# ── OntologyGenerator.relationship_avg_id_pair_length ────────────────────────

class TestRelationshipAvgIdPairLength:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_avg_id_pair_length(r) == pytest.approx(0.0)

    def test_known_avg(self):
        g = _make_generator()
        rels = [_make_rel_mock("ab", "cd")]  # len(ab)+len(cd) = 4
        r = _make_result(relationships=rels)
        assert g.relationship_avg_id_pair_length(r) == pytest.approx(4.0)

    def test_average_of_two(self):
        g = _make_generator()
        rels = [_make_rel_mock("ab", "cd"), _make_rel_mock("abcd", "ef")]
        # 4 + 6 = 10; avg = 5
        r = _make_result(relationships=rels)
        assert g.relationship_avg_id_pair_length(r) == pytest.approx(5.0)


# ── LogicValidator.has_disconnected_subgraphs ─────────────────────────────────

class TestHasDisconnectedSubgraphs:
    def test_empty_is_not_disconnected(self):
        v = _make_validator()
        assert v.has_disconnected_subgraphs({}) is False

    def test_single_component_false(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        assert v.has_disconnected_subgraphs(onto) is False

    def test_two_components_true(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "c", "target": "d"},
        ]}
        assert v.has_disconnected_subgraphs(onto) is True


# ── OntologyPipeline.run_score_max_run ───────────────────────────────────────

class TestRunScoreMaxRun:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_max_run() == 0

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_max_run() == 0

    def test_monotone_increasing(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        assert p.run_score_max_run() == 2

    def test_max_run_across_split(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5, 0.6, 0.8]:
            _push_run(p, v)
        # runs: [1], [2] → max=2
        assert p.run_score_max_run() == 2


# ── OntologyLearningAdapter.feedback_z_score_last ─────────────────────────────

class TestFeedbackZScoreLast:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_z_score_last() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_z_score_last() == pytest.approx(0.0)

    def test_last_above_mean_positive(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_z_score_last() > 0.0

    def test_last_below_mean_negative(self):
        a = _make_adapter()
        for v in [0.9, 0.7, 0.1]:
            _push_feedback(a, v)
        assert a.feedback_z_score_last() < 0.0


# ── OntologyMediator.action_uniformity_index ──────────────────────────────────

class TestActionUniformityIndex:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_uniformity_index() == pytest.approx(0.0)

    def test_single_type_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"a": 5}
        assert m.action_uniformity_index() == pytest.approx(1.0)

    def test_equal_counts_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 5, "c": 5}
        assert m.action_uniformity_index() == pytest.approx(1.0)

    def test_imbalanced_returns_less_than_one(self):
        m = _make_mediator()
        m._action_counts = {"a": 1, "b": 100}
        result = m.action_uniformity_index()
        assert 0.0 <= result < 1.0
