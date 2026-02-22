"""Batch-189 feature tests.

Methods under test:
  - OntologyOptimizer.history_weighted_mean(weights)
  - OntologyOptimizer.score_consecutive_above(threshold)
  - OntologyCritic.dimension_percentile(score, p)
  - OntologyGenerator.entity_min_confidence(result)
  - OntologyGenerator.entity_max_confidence(result)
  - LogicValidator.edge_count(ontology)
  - OntologyPipeline.run_score_first()
  - OntologyLearningAdapter.feedback_trend_slope()
  - OntologyMediator.action_ratio(action)
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


def _make_entity(eid, confidence=0.5, props=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    e = Entity(id=eid, type="T", text=eid, confidence=confidence, properties=props or {})
    return e


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(entities=entities, relationships=[], confidence=1.0)


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


# ── OntologyOptimizer.history_weighted_mean ───────────────────────────────────

class TestHistoryWeightedMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_weighted_mean() == pytest.approx(0.0)

    def test_single_entry_same_as_value(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.history_weighted_mean() == pytest.approx(0.7)

    def test_linear_weights_favour_recent(self):
        o = _make_optimizer()
        _push_opt(o, 0.2)  # weight 1
        _push_opt(o, 0.8)  # weight 2
        # weighted = (1*0.2 + 2*0.8) / 3 = 1.8/3 = 0.6
        assert o.history_weighted_mean() == pytest.approx(0.6)

    def test_custom_equal_weights_gives_simple_mean(self):
        o = _make_optimizer()
        for v in [0.4, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.history_weighted_mean(weights=[1.0, 1.0, 1.0]) == pytest.approx(0.6)

    def test_custom_weights_zero_denominator_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_weighted_mean(weights=[0.0]) == pytest.approx(0.0)


# ── OntologyOptimizer.score_consecutive_above ─────────────────────────────────

class TestScoreConsecutiveAbove:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_consecutive_above() == 0

    def test_none_above_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.4, 0.5]:
            _push_opt(o, v)
        assert o.score_consecutive_above(threshold=0.6) == 0

    def test_trailing_streak_counted(self):
        o = _make_optimizer()
        for v in [0.5, 0.8, 0.9, 0.95]:
            _push_opt(o, v)
        assert o.score_consecutive_above(threshold=0.7) == 3

    def test_streak_broken_mid_history(self):
        o = _make_optimizer()
        for v in [0.9, 0.3, 0.8, 0.85]:
            _push_opt(o, v)
        # Trailing: 0.85, 0.8 — then 0.3 breaks streak
        assert o.score_consecutive_above(threshold=0.7) == 2

    def test_all_above_returns_full_count(self):
        o = _make_optimizer()
        for v in [0.8, 0.85, 0.9]:
            _push_opt(o, v)
        assert o.score_consecutive_above(threshold=0.5) == 3


# ── OntologyCritic.dimension_percentile ──────────────────────────────────────

class TestDimensionPercentile:
    def test_50th_is_median(self):
        c = _make_critic()
        s = _make_score(
            completeness=0.2, consistency=0.4, clarity=0.6,
            granularity=0.8, relationship_coherence=0.9, domain_alignment=1.0,
        )
        # sorted: [0.2, 0.4, 0.6, 0.8, 0.9, 1.0] — 50th percentile
        result = c.dimension_percentile(s, 50.0)
        assert 0.6 <= result <= 0.8  # interpolated median region

    def test_0th_is_min(self):
        c = _make_critic()
        s = _make_score(completeness=0.1, consistency=0.5, clarity=0.5,
                        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        assert c.dimension_percentile(s, 0.0) == pytest.approx(0.1)

    def test_100th_is_max(self):
        c = _make_critic()
        s = _make_score(completeness=0.5, consistency=0.5, clarity=0.5,
                        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.9)
        assert c.dimension_percentile(s, 100.0) == pytest.approx(0.9)

    def test_uniform_any_percentile_returns_value(self):
        c = _make_critic()
        s = _make_score(completeness=0.6, consistency=0.6, clarity=0.6,
                        granularity=0.6, relationship_coherence=0.6, domain_alignment=0.6)
        assert c.dimension_percentile(s, 75.0) == pytest.approx(0.6)


# ── OntologyGenerator.entity_min_confidence ──────────────────────────────────

class TestEntityMinConfidence:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_min_confidence(r) == pytest.approx(0.0)

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", confidence=0.7)])
        assert g.entity_min_confidence(r) == pytest.approx(0.7)

    def test_multiple_returns_min(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", confidence=0.9),
            _make_entity("e2", confidence=0.3),
            _make_entity("e3", confidence=0.6),
        ])
        assert g.entity_min_confidence(r) == pytest.approx(0.3)


# ── OntologyGenerator.entity_max_confidence ──────────────────────────────────

class TestEntityMaxConfidence:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_max_confidence(r) == pytest.approx(0.0)

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", confidence=0.4)])
        assert g.entity_max_confidence(r) == pytest.approx(0.4)

    def test_multiple_returns_max(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", confidence=0.9),
            _make_entity("e2", confidence=0.3),
            _make_entity("e3", confidence=0.6),
        ])
        assert g.entity_max_confidence(r) == pytest.approx(0.9)


# ── LogicValidator.edge_count ─────────────────────────────────────────────────

class TestEdgeCount:
    def test_empty_ontology(self):
        v = _make_validator()
        assert v.edge_count({}) == 0

    def test_no_relationships_key(self):
        v = _make_validator()
        assert v.edge_count({"entities": []}) == 0

    def test_counts_relationships(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
            {"source": "c", "target": "a"},
        ]}
        assert v.edge_count(onto) == 3

    def test_single_relationship(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "x", "target": "y"}]}
        assert v.edge_count(onto) == 1


# ── OntologyPipeline.run_score_first ─────────────────────────────────────────

class TestRunScoreFirst:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_first() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.77)
        assert p.run_score_first() == pytest.approx(0.77)

    def test_returns_first_not_last(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.8)
        _push_run(p, 0.9)
        assert p.run_score_first() == pytest.approx(0.3)


# ── OntologyLearningAdapter.feedback_trend_slope ──────────────────────────────

class TestFeedbackTrendSlope:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_trend_slope() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_trend_slope() == pytest.approx(0.0)

    def test_increasing_trend_positive_slope(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_trend_slope() > 0

    def test_decreasing_trend_negative_slope(self):
        a = _make_adapter()
        for v in [0.8, 0.6, 0.4, 0.2]:
            _push_feedback(a, v)
        assert a.feedback_trend_slope() < 0

    def test_flat_trend_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_trend_slope() == pytest.approx(0.0)


# ── OntologyMediator.action_ratio ────────────────────────────────────────────

class TestActionRatio:
    def test_no_actions_returns_zero(self):
        m = _make_mediator()
        assert m.action_ratio("expand") == pytest.approx(0.0)

    def test_single_action_returns_one(self):
        m = _make_mediator()
        m._action_counts["expand"] = 5
        assert m.action_ratio("expand") == pytest.approx(1.0)

    def test_unknown_action_returns_zero(self):
        m = _make_mediator()
        m._action_counts["expand"] = 5
        assert m.action_ratio("prune") == pytest.approx(0.0)

    def test_fraction_of_total(self):
        m = _make_mediator()
        m._action_counts["expand"] = 3
        m._action_counts["prune"] = 1
        # expand = 3/4 = 0.75
        assert m.action_ratio("expand") == pytest.approx(0.75)
        assert m.action_ratio("prune") == pytest.approx(0.25)

    def test_equal_actions(self):
        m = _make_mediator()
        m._action_counts["a"] = 2
        m._action_counts["b"] = 2
        assert m.action_ratio("a") == pytest.approx(0.5)
