"""Batch-194 feature tests.

Methods under test:
  - OntologyOptimizer.history_span()
  - OntologyOptimizer.history_change_rate()
  - OntologyOptimizer.history_trend_direction()
  - OntologyCritic.dimension_top_k(score, k)
  - OntologyGenerator.entity_property_keys(result)
  - OntologyPipeline.run_score_mean()
  - OntologyLearningAdapter.feedback_negative_rate(threshold)
  - OntologyMediator.action_gini()
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


def _make_entity(eid, props=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, properties=props or {})


def _make_result(entities=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(entities=entities or [], relationships=[], confidence=1.0)


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


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


# ── OntologyOptimizer.history_span ───────────────────────────────────────────

class TestHistorySpan:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_span() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.history_span() == pytest.approx(0.0)

    def test_span_of_multiple(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_span() == pytest.approx(0.7)

    def test_uniform_history_span_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_span() == pytest.approx(0.0)


# ── OntologyOptimizer.history_change_rate ────────────────────────────────────

class TestHistoryChangeRate:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_change_rate() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_change_rate() == pytest.approx(0.0)

    def test_all_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_change_rate() == pytest.approx(0.0)

    def test_all_different_returns_one(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.3, 0.9]:
            _push_opt(o, v)
        assert o.history_change_rate() == pytest.approx(1.0)

    def test_partial_change(self):
        o = _make_optimizer()
        # [0.5, 0.5, 0.7, 0.7] — pairs: (0.5→0.5 no), (0.5→0.7 yes), (0.7→0.7 no) = 1/3
        for v in [0.5, 0.5, 0.7, 0.7]:
            _push_opt(o, v)
        assert o.history_change_rate() == pytest.approx(1 / 3)


# ── OntologyOptimizer.history_trend_direction ────────────────────────────────

class TestHistoryTrendDirection:
    def test_empty_returns_stable(self):
        o = _make_optimizer()
        assert o.history_trend_direction() == "stable"

    def test_single_returns_stable(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_trend_direction() == "stable"

    def test_improving_trend(self):
        o = _make_optimizer()
        for v in [0.2, 0.3, 0.7, 0.8]:
            _push_opt(o, v)
        assert o.history_trend_direction() == "improving"

    def test_declining_trend(self):
        o = _make_optimizer()
        for v in [0.8, 0.7, 0.3, 0.2]:
            _push_opt(o, v)
        assert o.history_trend_direction() == "declining"

    def test_flat_trend_stable(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_trend_direction() == "stable"


# ── OntologyCritic.dimension_top_k ───────────────────────────────────────────

class TestDimensionTopK:
    def test_top_1_returns_best_dimension(self):
        c = _make_critic()
        s = _make_score(completeness=0.9, consistency=0.3, clarity=0.5,
                        granularity=0.2, relationship_coherence=0.7, domain_alignment=0.1)
        result = c.dimension_top_k(s, k=1)
        assert result == ["completeness"]

    def test_top_3_sorted_descending(self):
        c = _make_critic()
        s = _make_score(completeness=0.9, consistency=0.8, clarity=0.7,
                        granularity=0.3, relationship_coherence=0.4, domain_alignment=0.2)
        result = c.dimension_top_k(s, k=3)
        assert result == ["completeness", "consistency", "clarity"]

    def test_k_larger_than_dims_returns_all(self):
        c = _make_critic()
        s = _make_score()  # all 0.5
        result = c.dimension_top_k(s, k=10)
        assert len(result) == 6  # only 6 dims exist


# ── OntologyGenerator.entity_property_keys ───────────────────────────────────

class TestEntityPropertyKeys:
    def test_empty_returns_empty_set(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_property_keys(r) == set()

    def test_single_entity_no_properties(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1")])
        assert g.entity_property_keys(r) == set()

    def test_union_of_all_keys(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", props={"name": "Alice", "age": 30}),
            _make_entity("e2", props={"name": "Bob", "role": "admin"}),
        ])
        keys = g.entity_property_keys(r)
        assert keys == {"name", "age", "role"}


# ── OntologyPipeline.run_score_mean ──────────────────────────────────────────

class TestRunScoreMean:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_mean() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.run_score_mean() == pytest.approx(0.6)

    def test_average_of_multiple(self):
        p = _make_pipeline()
        for v in [0.4, 0.6, 0.8]:
            _push_run(p, v)
        assert p.run_score_mean() == pytest.approx(0.6)


# ── OntologyLearningAdapter.feedback_negative_rate ───────────────────────────

class TestFeedbackNegativeRate:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_negative_rate() == pytest.approx(0.0)

    def test_all_negative(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3]:
            _push_feedback(a, v)
        assert a.feedback_negative_rate(threshold=0.4) == pytest.approx(1.0)

    def test_none_negative(self):
        a = _make_adapter()
        for v in [0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_negative_rate(threshold=0.4) == pytest.approx(0.0)

    def test_half_negative(self):
        a = _make_adapter()
        for v in [0.1, 0.3, 0.6, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_negative_rate(threshold=0.4) == pytest.approx(0.5)


# ── OntologyMediator.action_gini ─────────────────────────────────────────────

class TestActionGini:
    def test_no_actions_returns_zero(self):
        m = _make_mediator()
        assert m.action_gini() == pytest.approx(0.0)

    def test_single_action_returns_zero(self):
        m = _make_mediator()
        m._action_counts["expand"] = 5
        assert m.action_gini() == pytest.approx(0.0)

    def test_equal_distribution_gini_zero(self):
        m = _make_mediator()
        m._action_counts["a"] = 5
        m._action_counts["b"] = 5
        assert m.action_gini() == pytest.approx(0.0, abs=1e-6)

    def test_perfectly_concentrated_gini_positive(self):
        m = _make_mediator()
        m._action_counts["a"] = 100
        m._action_counts["b"] = 1
        assert m.action_gini() > 0.3
