"""Batch-208 feature tests.

Methods under test:
  - OntologyOptimizer.history_top_k_mean(k)
  - OntologyOptimizer.score_second_derivative()
  - OntologyGenerator.entity_id_prefix_groups(result, prefix_len)
  - OntologyGenerator.relationship_cross_type_count(result)
  - LogicValidator.acyclic_check(ontology)
  - OntologyPipeline.run_score_oscillation()
  - OntologyLearningAdapter.feedback_recovery_count(threshold)
  - OntologyMediator.action_balance_score()
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
    r.type = "rel"
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


# ── OntologyOptimizer.history_top_k_mean ─────────────────────────────────────

class TestHistoryTopKMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_top_k_mean() == pytest.approx(0.0)

    def test_fewer_than_k_returns_mean_of_all(self):
        o = _make_optimizer()
        for v in [0.4, 0.6]:
            _push_opt(o, v)
        assert o.history_top_k_mean(k=5) == pytest.approx(0.5)

    def test_top_3(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.8, 0.9, 0.2]:
            _push_opt(o, v)
        # top 3: 0.9, 0.8, 0.5 → mean = 2.2/3
        assert o.history_top_k_mean(k=3) == pytest.approx(2.2 / 3)


# ── OntologyOptimizer.score_second_derivative ────────────────────────────────

class TestScoreSecondDerivative:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_second_derivative() == pytest.approx(0.0)

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.7]:
            _push_opt(o, v)
        assert o.score_second_derivative() == pytest.approx(0.0)

    def test_constant_acceleration_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        # linear trend → 2nd derivative = 0
        assert o.score_second_derivative() == pytest.approx(0.0)

    def test_positive_acceleration(self):
        o = _make_optimizer()
        for v in [0.3, 0.4, 0.7]:
            _push_opt(o, v)
        # 0.7 - 2*0.4 + 0.3 = 0.7 - 0.8 + 0.3 = 0.2
        assert o.score_second_derivative() == pytest.approx(0.2)


# ── OntologyGenerator.entity_id_prefix_groups ────────────────────────────────

class TestEntityIdPrefixGroups:
    def test_empty_returns_empty_dict(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_id_prefix_groups(r) == {}

    def test_groups_by_prefix(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("abc"),
            _make_entity("abd"),
            _make_entity("xyz"),
        ])
        result = g.entity_id_prefix_groups(r, prefix_len=2)
        assert set(result.keys()) == {"ab", "xy"}
        assert sorted(result["ab"]) == ["abc", "abd"]
        assert result["xy"] == ["xyz"]

    def test_single_char_prefix(self):
        g = _make_generator()
        r = _make_result([_make_entity("apple"), _make_entity("ant")])
        result = g.entity_id_prefix_groups(r, prefix_len=1)
        assert "a" in result
        assert len(result["a"]) == 2


# ── OntologyGenerator.relationship_cross_type_count ──────────────────────────

class TestRelationshipCrossTypeCount:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(entities=[], relationships=[])
        assert g.relationship_cross_type_count(r) == 0

    def test_same_type_returns_zero(self):
        g = _make_generator()
        entities = [_make_entity("a", "T"), _make_entity("b", "T")]
        rels = [_make_rel_mock("a", "b")]
        r = _make_result(entities=entities, relationships=rels)
        assert g.relationship_cross_type_count(r) == 0

    def test_cross_type_counted(self):
        g = _make_generator()
        entities = [_make_entity("a", "Person"), _make_entity("b", "Org")]
        rels = [_make_rel_mock("a", "b")]
        r = _make_result(entities=entities, relationships=rels)
        assert g.relationship_cross_type_count(r) == 1


# ── LogicValidator.acyclic_check ──────────────────────────────────────────────

class TestAcyclicCheck:
    def test_empty_is_acyclic(self):
        v = _make_validator()
        assert v.acyclic_check({}) is True

    def test_tree_is_acyclic(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]}
        assert v.acyclic_check(onto) is True

    def test_self_loop_not_acyclic(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "a"}]}
        assert v.acyclic_check(onto) is False

    def test_cycle_not_acyclic(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
            {"source": "c", "target": "a"},
        ]}
        assert v.acyclic_check(onto) is False


# ── OntologyPipeline.run_score_oscillation ───────────────────────────────────

class TestRunScoreOscillation:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_oscillation() == 0

    def test_two_runs_returns_zero(self):
        p = _make_pipeline()
        for v in [0.3, 0.7]:
            _push_run(p, v)
        assert p.run_score_oscillation() == 0

    def test_single_oscillation(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.4]:
            _push_run(p, v)
        # deltas: +0.4, -0.3 → 1 sign change
        assert p.run_score_oscillation() == 1

    def test_multiple_oscillations(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.4, 0.8, 0.5]:
            _push_run(p, v)
        # deltas: +, -, +, - → 3 oscillations
        assert p.run_score_oscillation() == 3


# ── OntologyLearningAdapter.feedback_recovery_count ──────────────────────────

class TestFeedbackRecoveryCount:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_recovery_count() == 0

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_recovery_count() == 0

    def test_no_recovery(self):
        a = _make_adapter()
        for v in [0.8, 0.9, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_recovery_count() == 0

    def test_single_recovery(self):
        a = _make_adapter()
        for v in [0.8, 0.3, 0.7]:
            _push_feedback(a, v)
        # 0.3 below, then 0.7 above → 1 recovery
        assert a.feedback_recovery_count() == 1


# ── OntologyMediator.action_balance_score ─────────────────────────────────────

class TestActionBalanceScore:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_balance_score() == pytest.approx(0.0)

    def test_single_type_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"refine": 5}
        assert m.action_balance_score() == pytest.approx(1.0)

    def test_equal_distribution_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 5, "c": 5}
        assert m.action_balance_score() == pytest.approx(1.0)

    def test_imbalanced(self):
        m = _make_mediator()
        m._action_counts = {"a": 1, "b": 10}
        assert m.action_balance_score() == pytest.approx(0.1)
