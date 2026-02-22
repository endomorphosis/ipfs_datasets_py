"""Batch-204 feature tests.

Methods under test:
  - OntologyOptimizer.history_stagnation_rate(tolerance)
  - OntologyOptimizer.score_vs_baseline(baseline)
  - OntologyGenerator.entity_confidence_entropy(result)
  - LogicValidator.root_nodes(ontology)
  - LogicValidator.relationship_loop_count(ontology)
  - OntologyPipeline.run_score_rolling_std(window)
  - OntologyLearningAdapter.feedback_worst_k_mean(k)
  - OntologyMediator.action_least_recent()
"""
import math
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


def _make_entity(eid, confidence=1.0):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_result(entities=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=[],
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


# ── OntologyOptimizer.history_stagnation_rate ────────────────────────────────

class TestHistoryStagnationRate:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_stagnation_rate() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_stagnation_rate() == pytest.approx(0.0)

    def test_all_stagnant(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_stagnation_rate() == pytest.approx(1.0)

    def test_no_stagnation(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_stagnation_rate(tolerance=0.005) == pytest.approx(0.0)

    def test_half_stagnant(self):
        o = _make_optimizer()
        for v in [0.5, 0.5, 0.8, 0.9]:
            _push_opt(o, v)
        # pairs: (0.5,0.5) stagnant, (0.5,0.8) not, (0.8,0.9) not → 1/3
        assert o.history_stagnation_rate(tolerance=0.005) == pytest.approx(1 / 3)


# ── OntologyOptimizer.score_vs_baseline ──────────────────────────────────────

class TestScoreVsBaseline:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_vs_baseline() == pytest.approx(0.0)

    def test_above_baseline(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        assert o.score_vs_baseline(baseline=0.5) == pytest.approx(0.3)

    def test_below_baseline(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        assert o.score_vs_baseline(baseline=0.5) == pytest.approx(-0.2)

    def test_at_baseline(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_vs_baseline(baseline=0.5) == pytest.approx(0.0)


# ── OntologyGenerator.entity_confidence_entropy ──────────────────────────────

class TestEntityConfidenceEntropy:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_confidence_entropy(r) == pytest.approx(0.0)

    def test_uniform_confidence_returns_zero(self):
        g = _make_generator()
        # all in same bucket
        r = _make_result([_make_entity("a", 0.5), _make_entity("b", 0.55)])
        assert g.entity_confidence_entropy(r) == pytest.approx(0.0)

    def test_two_equal_buckets_entropy(self):
        g = _make_generator()
        # 0.1 → bucket 1, 0.9 → bucket 9
        r = _make_result([_make_entity("a", 0.1), _make_entity("b", 0.9)])
        # H = -2*(0.5 * ln(0.5)) = ln(2) ≈ 0.693
        assert g.entity_confidence_entropy(r) == pytest.approx(math.log(2))

    def test_returns_non_negative(self):
        g = _make_generator()
        r = _make_result([_make_entity(f"e{i}", i * 0.1) for i in range(5)])
        assert g.entity_confidence_entropy(r) >= 0.0


# ── LogicValidator.root_nodes ─────────────────────────────────────────────────

class TestRootNodes:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.root_nodes({}) == []

    def test_source_only_is_root(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        assert v.root_nodes(onto) == ["a"]

    def test_bridge_node_not_root(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]}
        # b is both source and target → not root
        assert v.root_nodes(onto) == ["a"]

    def test_returns_sorted(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "z", "target": "m"},
            {"source": "a", "target": "m"},
        ]}
        result = v.root_nodes(onto)
        assert result == sorted(result)


# ── LogicValidator.relationship_loop_count ────────────────────────────────────

class TestRelationshipLoopCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.relationship_loop_count({}) == 0

    def test_no_loops(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        assert v.relationship_loop_count(onto) == 0

    def test_one_loop(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "a"},
            {"source": "a", "target": "b"},
        ]}
        assert v.relationship_loop_count(onto) == 1

    def test_multiple_loops(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "a"},
            {"source": "b", "target": "b"},
        ]}
        assert v.relationship_loop_count(onto) == 2


# ── OntologyPipeline.run_score_rolling_std ────────────────────────────────────

class TestRunScoreRollingStd:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_rolling_std() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_rolling_std() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_rolling_std() == pytest.approx(0.0)

    def test_window_uses_last_n(self):
        p = _make_pipeline()
        for v in [0.1, 0.1, 0.8, 0.9]:
            _push_run(p, v)
        # last 2: [0.8, 0.9] mean=0.85, std=0.05
        assert p.run_score_rolling_std(window=2) == pytest.approx(0.05)


# ── OntologyLearningAdapter.feedback_worst_k_mean ─────────────────────────────

class TestFeedbackWorstKMean:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_worst_k_mean() == pytest.approx(0.0)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_worst_k_mean(k=3) == pytest.approx(0.7)

    def test_bottom_k_mean(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8, 0.9, 0.1]:
            _push_feedback(a, v)
        # bottom 3: 0.1, 0.2, 0.5 → mean = 0.8/3
        assert a.feedback_worst_k_mean(k=3) == pytest.approx(0.8 / 3)


# ── OntologyMediator.action_least_recent ──────────────────────────────────────

class TestActionLeastRecent:
    def test_empty_returns_empty_string(self):
        m = _make_mediator()
        assert m.action_least_recent() == ""

    def test_single_type(self):
        m = _make_mediator()
        m._action_counts = {"refine": 5}
        assert m.action_least_recent() == "refine"

    def test_returns_min_count(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 1, "c": 3}
        assert m.action_least_recent() == "b"

    def test_tie_returns_lexicographic_first(self):
        m = _make_mediator()
        m._action_counts = {"z": 1, "a": 1, "m": 1}
        assert m.action_least_recent() == "a"
