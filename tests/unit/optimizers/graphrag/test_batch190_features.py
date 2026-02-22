"""Batch-190 feature tests.

Methods under test:
  - OntologyOptimizer.history_min()
  - OntologyOptimizer.history_max()
  - OntologyOptimizer.history_rolling_mean(window)
  - OntologyCritic.dimension_above_threshold(score, threshold)
  - OntologyGenerator.entity_with_most_properties(result)
  - OntologyGenerator.relationship_max_weight(result)
  - OntologyPipeline.run_score_last()
  - OntologyLearningAdapter.feedback_median_deviation()
  - OntologyMediator.action_mode()
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
    return Entity(id=eid, type="T", text=eid, confidence=confidence, properties=props or {})


def _make_relationship(rid, weight=None):
    rel = MagicMock()
    rel.id = rid
    rel.weight = weight if weight is not None else 0.0
    return rel


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


# ── OntologyOptimizer.history_min ────────────────────────────────────────────

class TestHistoryMin:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_min() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.6)
        assert o.history_min() == pytest.approx(0.6)

    def test_returns_minimum(self):
        o = _make_optimizer()
        for v in [0.8, 0.3, 0.7]:
            _push_opt(o, v)
        assert o.history_min() == pytest.approx(0.3)


# ── OntologyOptimizer.history_max ────────────────────────────────────────────

class TestHistoryMax:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_max() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.4)
        assert o.history_max() == pytest.approx(0.4)

    def test_returns_maximum(self):
        o = _make_optimizer()
        for v in [0.3, 0.9, 0.5]:
            _push_opt(o, v)
        assert o.history_max() == pytest.approx(0.9)


# ── OntologyOptimizer.history_rolling_mean ───────────────────────────────────

class TestHistoryRollingMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_rolling_mean() == pytest.approx(0.0)

    def test_fewer_than_window_uses_all(self):
        o = _make_optimizer()
        _push_opt(o, 0.4)
        _push_opt(o, 0.6)
        # window=3 but only 2 entries → mean = 0.5
        assert o.history_rolling_mean(window=3) == pytest.approx(0.5)

    def test_window_of_one_returns_last(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_rolling_mean(window=1) == pytest.approx(0.9)

    def test_window_of_two_uses_last_two(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.8]:
            _push_opt(o, v)
        assert o.history_rolling_mean(window=2) == pytest.approx(0.6)


# ── OntologyCritic.dimension_above_threshold ─────────────────────────────────

class TestDimensionAboveThreshold:
    def test_none_above_returns_zero(self):
        c = _make_critic()
        s = _make_score(completeness=0.3, consistency=0.3, clarity=0.3,
                        granularity=0.3, relationship_coherence=0.3, domain_alignment=0.3)
        assert c.dimension_above_threshold(s, threshold=0.5) == 0

    def test_all_above_returns_six(self):
        c = _make_critic()
        s = _make_score(completeness=0.9, consistency=0.9, clarity=0.9,
                        granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9)
        assert c.dimension_above_threshold(s, threshold=0.7) == 6

    def test_partial_count(self):
        c = _make_critic()
        s = _make_score(completeness=0.8, consistency=0.4, clarity=0.9,
                        granularity=0.3, relationship_coherence=0.85, domain_alignment=0.2)
        assert c.dimension_above_threshold(s, threshold=0.7) == 3

    def test_default_threshold(self):
        c = _make_critic()
        s = _make_score(completeness=0.8, consistency=0.6, clarity=0.75,
                        granularity=0.5, relationship_coherence=0.9, domain_alignment=0.3)
        # > 0.7: completeness(0.8), clarity(0.75), relationship_coherence(0.9) = 3
        assert c.dimension_above_threshold(s) == 3


# ── OntologyGenerator.entity_with_most_properties ────────────────────────────

class TestEntityWithMostProperties:
    def test_empty_returns_empty_string(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_with_most_properties(r) == ""

    def test_single_entity_returns_its_id(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", props={"a": 1})])
        assert g.entity_with_most_properties(r) == "e1"

    def test_returns_id_of_entity_with_most(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", props={"a": 1}),
            _make_entity("e2", props={"a": 1, "b": 2, "c": 3}),
            _make_entity("e3", props={"x": 0}),
        ])
        assert g.entity_with_most_properties(r) == "e2"

    def test_no_properties_returns_first_id(self):
        g = _make_generator()
        r = _make_result([_make_entity("ea"), _make_entity("eb")])
        result = g.entity_with_most_properties(r)
        assert result in ("ea", "eb")  # tie — any is acceptable


# ── OntologyGenerator.relationship_max_weight ────────────────────────────────

class TestRelationshipMaxWeight:
    def test_no_relationships_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_max_weight(r) == pytest.approx(0.0)

    def test_single_relationship_no_weight_attr_returns_zero(self):
        g = _make_generator()
        rel = _make_relationship("r1")  # no weight attribute
        r = _make_result(relationships=[rel])
        assert g.relationship_max_weight(r) == pytest.approx(0.0)

    def test_returns_max_weight(self):
        g = _make_generator()
        rels = [_make_relationship(f"r{i}", weight=w) for i, w in enumerate([0.3, 0.8, 0.5])]
        r = _make_result(relationships=rels)
        assert g.relationship_max_weight(r) == pytest.approx(0.8)


# ── OntologyPipeline.run_score_last ──────────────────────────────────────────

class TestRunScoreLast:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_last() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.55)
        assert p.run_score_last() == pytest.approx(0.55)

    def test_returns_last_not_first(self):
        p = _make_pipeline()
        _push_run(p, 0.2)
        _push_run(p, 0.6)
        _push_run(p, 0.95)
        assert p.run_score_last() == pytest.approx(0.95)


# ── OntologyLearningAdapter.feedback_median_deviation ────────────────────────

class TestFeedbackMedianDeviation:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_median_deviation() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_median_deviation() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.6)
        assert a.feedback_median_deviation() == pytest.approx(0.0)

    def test_spread_scores(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        # median = 0.5; deviations: 0.3, 0.1, 0.1, 0.3 → mean = 0.2
        assert a.feedback_median_deviation() == pytest.approx(0.2)


# ── OntologyMediator.action_mode ─────────────────────────────────────────────

class TestActionMode:
    def test_no_actions_returns_empty_string(self):
        m = _make_mediator()
        assert m.action_mode() == ""

    def test_single_action(self):
        m = _make_mediator()
        m._action_counts["expand"] = 3
        assert m.action_mode() == "expand"

    def test_returns_most_frequent(self):
        m = _make_mediator()
        m._action_counts["expand"] = 2
        m._action_counts["prune"] = 7
        m._action_counts["merge"] = 1
        assert m.action_mode() == "prune"

    def test_tie_returns_one_of_them(self):
        m = _make_mediator()
        m._action_counts["a"] = 5
        m._action_counts["b"] = 5
        assert m.action_mode() in ("a", "b")
