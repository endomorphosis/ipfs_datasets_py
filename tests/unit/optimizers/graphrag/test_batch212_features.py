"""Batch-212 feature tests.

Methods under test:
  - OntologyOptimizer.score_mean_top_k(k)
  - OntologyOptimizer.history_last_n_range(n)
  - OntologyGenerator.entity_confidence_below_mean_count(result)
  - OntologyGenerator.relationship_self_loop_ids(result)
  - LogicValidator.redundancy_score(ontology)
  - OntologyPipeline.run_above_target_count(target)
  - OntologyLearningAdapter.feedback_mean_change()
  - OntologyMediator.action_last_n_most_common(n)
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


def _make_entity(eid, confidence=1.0):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


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


# ── OntologyOptimizer.score_mean_top_k ───────────────────────────────────────

class TestScoreMeanTopK:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_mean_top_k() == pytest.approx(0.0)

    def test_single_returns_value(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        assert o.score_mean_top_k(k=3) == pytest.approx(0.8)

    def test_top_3_mean(self):
        o = _make_optimizer()
        for v in [0.2, 0.6, 0.9, 0.4]:
            _push_opt(o, v)
        # top 3: 0.9, 0.6, 0.4 → mean = 1.9/3
        assert o.score_mean_top_k(k=3) == pytest.approx((0.9 + 0.6 + 0.4) / 3)

    def test_k_larger_than_history(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.score_mean_top_k(k=10) == pytest.approx(0.5)


# ── OntologyOptimizer.history_last_n_range ───────────────────────────────────

class TestHistoryLastNRange:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_last_n_range() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_last_n_range(n=5) == pytest.approx(0.0)

    def test_range_of_last_3(self):
        o = _make_optimizer()
        for v in [0.1, 0.9, 0.2, 0.8]:
            _push_opt(o, v)
        # last 3: 0.9, 0.2, 0.8 → range = 0.9 - 0.2
        assert o.history_last_n_range(n=3) == pytest.approx(0.7)


# ── OntologyGenerator.entity_confidence_below_mean_count ─────────────────────

class TestEntityConfidenceBelowMeanCount:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_confidence_below_mean_count(r) == 0

    def test_single_returns_zero(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", 0.5)])
        assert g.entity_confidence_below_mean_count(r) == 0

    def test_below_mean(self):
        g = _make_generator()
        # mean = (0.2 + 0.8) / 2 = 0.5; only first is below
        r = _make_result([_make_entity("a", 0.2), _make_entity("b", 0.8)])
        assert g.entity_confidence_below_mean_count(r) == 1


# ── OntologyGenerator.relationship_self_loop_ids ─────────────────────────────

class TestRelationshipSelfLoopIds:
    def test_empty_returns_empty(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_self_loop_ids(r) == []

    def test_no_loops(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock("a", "b")])
        assert g.relationship_self_loop_ids(r) == []

    def test_detects_loops(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "a"), _make_rel_mock("b", "c")]
        r = _make_result(relationships=rels)
        assert g.relationship_self_loop_ids(r) == ["a"]


# ── LogicValidator.redundancy_score ──────────────────────────────────────────

class TestRedundancyScore:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.redundancy_score({}) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        assert v.redundancy_score(onto) == pytest.approx(0.0)

    def test_all_duplicates(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "b"},
        ]}
        # 1 duplicate out of 2 total → 0.5
        assert v.redundancy_score(onto) == pytest.approx(0.5)

    def test_no_duplicates(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]}
        assert v.redundancy_score(onto) == pytest.approx(0.0)


# ── OntologyPipeline.run_above_target_count ───────────────────────────────────

class TestRunAboveTargetCount:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_above_target_count() == 0

    def test_all_above(self):
        p = _make_pipeline()
        for v in [0.8, 0.9]:
            _push_run(p, v)
        assert p.run_above_target_count(target=0.7) == 2

    def test_none_above(self):
        p = _make_pipeline()
        for v in [0.3, 0.5]:
            _push_run(p, v)
        assert p.run_above_target_count(target=0.7) == 0

    def test_some_above(self):
        p = _make_pipeline()
        for v in [0.5, 0.8, 0.9]:
            _push_run(p, v)
        assert p.run_above_target_count(target=0.7) == 2


# ── OntologyLearningAdapter.feedback_mean_change ─────────────────────────────

class TestFeedbackMeanChange:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_mean_change() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_mean_change() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        a = _make_adapter()
        for v in [0.5, 0.5, 0.5]:
            _push_feedback(a, v)
        assert a.feedback_mean_change() == pytest.approx(0.0)

    def test_increasing(self):
        a = _make_adapter()
        for v in [0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_mean_change() == pytest.approx(0.2)


# ── OntologyMediator.action_last_n_most_common ───────────────────────────────

class TestActionLastNMostCommon:
    def test_empty_returns_empty_str(self):
        m = _make_mediator()
        assert m.action_last_n_most_common() == ""

    def test_single_type(self):
        m = _make_mediator()
        m._action_counts = {"prune": 5}
        assert m.action_last_n_most_common() == "prune"

    def test_most_common(self):
        m = _make_mediator()
        m._action_counts = {"prune": 5, "expand": 3, "merge": 1}
        assert m.action_last_n_most_common() == "prune"

    def test_with_log(self):
        m = _make_mediator()
        m._action_log = ["a", "b", "a", "c", "a"]
        assert m.action_last_n_most_common(n=5) == "a"
