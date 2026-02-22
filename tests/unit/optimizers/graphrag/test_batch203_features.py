"""Batch-203 feature tests.

Methods under test:
  - OntologyOptimizer.score_trailing_mean(n)
  - OntologyOptimizer.history_mean_last_n(n)
  - OntologyGenerator.entity_text_word_count_avg(result)
  - OntologyGenerator.relationship_symmetry_ratio(result)
  - LogicValidator.leaf_nodes(ontology)
  - OntologyPipeline.run_score_trend_slope()
  - OntologyLearningAdapter.feedback_best_k_mean(k)
  - OntologyMediator.action_max_consecutive()
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


def _make_entity(eid, text=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=text or eid)


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


# ── OntologyOptimizer.score_trailing_mean ────────────────────────────────────

class TestScoreTrailingMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_trailing_mean() == pytest.approx(0.0)

    def test_fewer_than_n(self):
        o = _make_optimizer()
        for v in [0.4, 0.6]:
            _push_opt(o, v)
        # only 2 entries, n=5 → mean of all 2
        assert o.score_trailing_mean(n=5) == pytest.approx(0.5)

    def test_trailing_n(self):
        o = _make_optimizer()
        for v in [0.1, 0.1, 0.8, 0.9]:
            _push_opt(o, v)
        # last 2: 0.8, 0.9 → mean=0.85
        assert o.score_trailing_mean(n=2) == pytest.approx(0.85)


# ── OntologyOptimizer.history_mean_last_n ────────────────────────────────────

class TestHistoryMeanLastN:
    def test_returns_same_as_trailing_mean(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6]:
            _push_opt(o, v)
        assert o.history_mean_last_n(n=2) == o.score_trailing_mean(n=2)

    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_mean_last_n() == pytest.approx(0.0)


# ── OntologyGenerator.entity_text_word_count_avg ─────────────────────────────

class TestEntityTextWordCountAvg:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_text_word_count_avg(r) == pytest.approx(0.0)

    def test_single_word(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", text="hello")])
        assert g.entity_text_word_count_avg(r) == pytest.approx(1.0)

    def test_multiple_words(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("a", text="hello world"),
            _make_entity("b", text="foo"),
        ])
        # avg of 2 and 1 = 1.5
        assert g.entity_text_word_count_avg(r) == pytest.approx(1.5)


# ── OntologyGenerator.relationship_symmetry_ratio ────────────────────────────

class TestRelationshipSymmetryRatio:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_symmetry_ratio(r) == pytest.approx(0.0)

    def test_no_symmetric_returns_zero(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("c", "d")]
        r = _make_result(relationships=rels)
        assert g.relationship_symmetry_ratio(r) == pytest.approx(0.0)

    def test_fully_symmetric(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("b", "a")]
        r = _make_result(relationships=rels)
        assert g.relationship_symmetry_ratio(r) == pytest.approx(1.0)

    def test_partially_symmetric(self):
        g = _make_generator()
        rels = [
            _make_rel_mock("a", "b"), _make_rel_mock("b", "a"),
            _make_rel_mock("c", "d"),
        ]
        r = _make_result(relationships=rels)
        # 2 out of 3 unique edges are symmetric
        assert g.relationship_symmetry_ratio(r) == pytest.approx(2.0 / 3.0)


# ── LogicValidator.leaf_nodes ─────────────────────────────────────────────────

class TestLeafNodes:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.leaf_nodes({}) == []

    def test_target_only_is_leaf(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        # b has no outgoing rels → leaf
        assert v.leaf_nodes(onto) == ["b"]

    def test_bridge_node_not_leaf(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]}
        # b is both source and target → not leaf; c is leaf
        assert v.leaf_nodes(onto) == ["c"]

    def test_returns_sorted(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "z"},
            {"source": "a", "target": "m"},
        ]}
        result = v.leaf_nodes(onto)
        assert result == sorted(result)


# ── OntologyPipeline.run_score_trend_slope ───────────────────────────────────

class TestRunScoreTrendSlope:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_trend_slope() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_trend_slope() == pytest.approx(0.0)

    def test_flat_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_trend_slope() == pytest.approx(0.0, abs=1e-9)

    def test_increasing_positive_slope(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_run(p, v)
        slope = p.run_score_trend_slope()
        assert slope > 0.0

    def test_decreasing_negative_slope(self):
        p = _make_pipeline()
        for v in [0.8, 0.6, 0.4, 0.2]:
            _push_run(p, v)
        slope = p.run_score_trend_slope()
        assert slope < 0.0


# ── OntologyLearningAdapter.feedback_best_k_mean ─────────────────────────────

class TestFeedbackBestKMean:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_best_k_mean() == pytest.approx(0.0)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_best_k_mean(k=3) == pytest.approx(0.7)

    def test_top_k_mean(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8, 0.9, 0.1]:
            _push_feedback(a, v)
        # top 3: 0.9, 0.8, 0.5 → mean = 2.2/3
        assert a.feedback_best_k_mean(k=3) == pytest.approx(2.2 / 3)


# ── OntologyMediator.action_max_consecutive ──────────────────────────────────

class TestActionMaxConsecutive:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_max_consecutive() == 0

    def test_single_action(self):
        m = _make_mediator()
        m._action_counts = {"refine": 5}
        assert m.action_max_consecutive() == 5

    def test_max_across_actions(self):
        m = _make_mediator()
        m._action_counts = {"a": 3, "b": 8, "c": 2}
        assert m.action_max_consecutive() == 8
