"""Batch-206 feature tests.

Methods under test:
  - OntologyOptimizer.score_relative_to_best()
  - OntologyOptimizer.history_decline_rate()
  - OntologyGenerator.entity_property_value_types(result)
  - OntologyGenerator.relationship_types_sorted(result)
  - LogicValidator.connected_components_count(ontology)
  - OntologyPipeline.run_score_ema(alpha)
  - OntologyLearningAdapter.feedback_mean_last_n(n)
  - OntologyMediator.action_pct_of_total(action_name)
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


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    return OntologyMediator(generator=MagicMock(), critic=MagicMock())


# ── OntologyOptimizer.score_relative_to_best ─────────────────────────────────

class TestScoreRelativeToBest:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_relative_to_best() == pytest.approx(0.0)

    def test_single_entry_returns_one(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.score_relative_to_best() == pytest.approx(1.0)

    def test_last_is_best(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.score_relative_to_best() == pytest.approx(1.0)

    def test_last_below_best(self):
        o = _make_optimizer()
        for v in [0.5, 0.9, 0.6]:
            _push_opt(o, v)
        # last=0.6, best=0.9 → 0.6/0.9 ≈ 0.667
        assert o.score_relative_to_best() == pytest.approx(0.6 / 0.9)


# ── OntologyOptimizer.history_decline_rate ───────────────────────────────────

class TestHistoryDeclineRate:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_decline_rate() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_decline_rate() == pytest.approx(0.0)

    def test_all_declining(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.history_decline_rate() == pytest.approx(1.0)

    def test_half_declining(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.5, 0.9]:
            _push_opt(o, v)
        # steps: +, -, + → 1/3 decline
        assert o.history_decline_rate() == pytest.approx(1 / 3)


# ── OntologyGenerator.entity_property_value_types ────────────────────────────

class TestEntityPropertyValueTypes:
    def test_no_entities_returns_empty(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_property_value_types(r) == set()

    def test_no_properties_returns_empty(self):
        g = _make_generator()
        r = _make_result([_make_entity("a")])
        assert g.entity_property_value_types(r) == set()

    def test_identifies_str_type(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", properties={"name": "hello"})])
        assert "str" in g.entity_property_value_types(r)

    def test_identifies_multiple_types(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", properties={"name": "hello", "count": 5})])
        types = g.entity_property_value_types(r)
        assert "str" in types
        assert "int" in types


# ── OntologyGenerator.relationship_types_sorted ──────────────────────────────

class TestRelationshipTypesSorted:
    def test_empty_returns_empty(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_types_sorted(r) == []

    def test_returns_sorted_unique_types(self):
        g = _make_generator()
        rels = [
            _make_rel_mock("is_a"),
            _make_rel_mock("part_of"),
            _make_rel_mock("is_a"),
        ]
        r = _make_result(relationships=rels)
        result = g.relationship_types_sorted(r)
        assert result == sorted(set(result))
        assert "is_a" in result
        assert "part_of" in result


# ── LogicValidator.connected_components_count ────────────────────────────────

class TestConnectedComponentsCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.connected_components_count({}) == 0

    def test_single_edge_one_component(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        assert v.connected_components_count(onto) == 1

    def test_two_disconnected_components(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "c", "target": "d"},
        ]}
        assert v.connected_components_count(onto) == 2

    def test_all_connected(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]}
        assert v.connected_components_count(onto) == 1


# ── OntologyPipeline.run_score_ema ────────────────────────────────────────────

class TestRunScoreEma:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_ema() == pytest.approx(0.0)

    def test_single_run_returns_score(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.run_score_ema() == pytest.approx(0.7)

    def test_uniform_returns_same(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_ema() == pytest.approx(0.5)

    def test_ema_weights_recent(self):
        p = _make_pipeline()
        _push_run(p, 0.0)
        _push_run(p, 1.0)
        # ema = 0.3*1.0 + 0.7*0.0 = 0.3
        assert p.run_score_ema(alpha=0.3) == pytest.approx(0.3)


# ── OntologyLearningAdapter.feedback_mean_last_n ─────────────────────────────

class TestFeedbackMeanLastN:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_mean_last_n() == pytest.approx(0.0)

    def test_last_n_average(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.8, 0.9]:
            _push_feedback(a, v)
        # last 2: 0.8, 0.9 → mean=0.85
        assert a.feedback_mean_last_n(n=2) == pytest.approx(0.85)

    def test_n_larger_than_feedback(self):
        a = _make_adapter()
        for v in [0.4, 0.6]:
            _push_feedback(a, v)
        assert a.feedback_mean_last_n(n=10) == pytest.approx(0.5)


# ── OntologyMediator.action_pct_of_total ──────────────────────────────────────

class TestActionPctOfTotal:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_pct_of_total("x") == pytest.approx(0.0)

    def test_unknown_action_returns_zero(self):
        m = _make_mediator()
        m._action_counts = {"a": 5}
        assert m.action_pct_of_total("unknown") == pytest.approx(0.0)

    def test_sole_action_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"refine": 7}
        assert m.action_pct_of_total("refine") == pytest.approx(1.0)

    def test_percentage_correct(self):
        m = _make_mediator()
        m._action_counts = {"a": 3, "b": 7}
        assert m.action_pct_of_total("a") == pytest.approx(0.3)
        assert m.action_pct_of_total("b") == pytest.approx(0.7)
