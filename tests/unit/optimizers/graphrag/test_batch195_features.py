"""Batch-195 feature tests.

Methods under test:
  - OntologyOptimizer.history_cumulative_sum()
  - OntologyOptimizer.score_normalized()
  - OntologyOptimizer.history_decay_sum(decay)
  - OntologyCritic.dimension_bottom_k(score, k)
  - OntologyGenerator.entity_text_max_length(result)
  - OntologyGenerator.relationship_type_diversity(result)
  - OntologyPipeline.run_score_std()
  - OntologyLearningAdapter.feedback_weighted_sum(decay)
  - OntologyMediator.action_count_per_round()
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


def _make_entity(eid, text=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=text or eid)


def _make_rel_mock(rel_type="rel"):
    r = MagicMock()
    r.type = rel_type
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


# ── OntologyOptimizer.history_cumulative_sum ─────────────────────────────────

class TestHistoryCumulativeSum:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_cumulative_sum() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.history_cumulative_sum() == pytest.approx(0.7)

    def test_sum_of_all(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.history_cumulative_sum() == pytest.approx(1.5)


# ── OntologyOptimizer.score_normalized ───────────────────────────────────────

class TestScoreNormalized:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_normalized() == pytest.approx(0.0)

    def test_single_entry_returns_one(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        assert o.score_normalized() == pytest.approx(1.0)

    def test_last_is_max_returns_one(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.score_normalized() == pytest.approx(1.0)

    def test_last_below_max(self):
        o = _make_optimizer()
        for v in [0.5, 0.9, 0.4]:
            _push_opt(o, v)
        # last = 0.4, max = 0.9 → 0.4/0.9
        assert o.score_normalized() == pytest.approx(0.4 / 0.9)


# ── OntologyOptimizer.history_decay_sum ──────────────────────────────────────

class TestHistoryDecaySum:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_decay_sum() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.history_decay_sum() == pytest.approx(0.7)

    def test_decay_weighs_recent_more(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)  # oldest — decay^1
        _push_opt(o, 0.8)  # newest — decay^0
        # sum = 0.8 * 1.0 + 0.3 * 0.9 = 0.8 + 0.27 = 1.07
        assert o.history_decay_sum(decay=0.9) == pytest.approx(1.07)


# ── OntologyCritic.dimension_bottom_k ────────────────────────────────────────

class TestDimensionBottomK:
    def test_bottom_1_returns_worst_dimension(self):
        c = _make_critic()
        s = _make_score(completeness=0.1, consistency=0.8, clarity=0.5,
                        granularity=0.9, relationship_coherence=0.6, domain_alignment=0.3)
        result = c.dimension_bottom_k(s, k=1)
        assert result == ["completeness"]

    def test_bottom_3_sorted_ascending(self):
        c = _make_critic()
        s = _make_score(completeness=0.1, consistency=0.2, clarity=0.3,
                        granularity=0.8, relationship_coherence=0.9, domain_alignment=0.7)
        result = c.dimension_bottom_k(s, k=3)
        assert result == ["completeness", "consistency", "clarity"]

    def test_k_larger_than_dims_returns_all(self):
        c = _make_critic()
        s = _make_score()
        result = c.dimension_bottom_k(s, k=10)
        assert len(result) == 6


# ── OntologyGenerator.entity_text_max_length ─────────────────────────────────

class TestEntityTextMaxLength:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_text_max_length(r) == 0

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", text="hello")])
        assert g.entity_text_max_length(r) == 5

    def test_max_of_multiple(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", text="hi"),
            _make_entity("e2", text="greetings"),
            _make_entity("e3", text="hey"),
        ])
        assert g.entity_text_max_length(r) == 9


# ── OntologyGenerator.relationship_type_diversity ────────────────────────────

class TestRelationshipTypeDiversity:
    def test_no_relationships_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_type_diversity(r) == 0

    def test_all_same_type_returns_one(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock("owns"), _make_rel_mock("owns")])
        assert g.relationship_type_diversity(r) == 1

    def test_distinct_types(self):
        g = _make_generator()
        rels = [_make_rel_mock(t) for t in ["owns", "causes", "contains", "causes"]]
        r = _make_result(relationships=rels)
        assert g.relationship_type_diversity(r) == 3


# ── OntologyPipeline.run_score_std ───────────────────────────────────────────

class TestRunScoreStd:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_std() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.run_score_std() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        p = _make_pipeline()
        for _ in range(3):
            _push_run(p, 0.5)
        assert p.run_score_std() == pytest.approx(0.0)

    def test_std_of_known_values(self):
        p = _make_pipeline()
        for v in [0.4, 0.6]:
            _push_run(p, v)
        # mean = 0.5, variance = 0.01, std = 0.1
        assert p.run_score_std() == pytest.approx(0.1)


# ── OntologyLearningAdapter.feedback_weighted_sum ────────────────────────────

class TestFeedbackWeightedSum:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_weighted_sum() == pytest.approx(0.0)

    def test_single_record_no_decay(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_weighted_sum() == pytest.approx(0.7)

    def test_decay_weighs_recent_more(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)  # oldest
        _push_feedback(a, 0.8)  # newest (weight = 1.0)
        # 0.8 * 1.0 + 0.3 * 0.9 = 0.8 + 0.27 = 1.07
        assert a.feedback_weighted_sum(decay=0.9) == pytest.approx(1.07)


# ── OntologyMediator.action_count_per_round ──────────────────────────────────

class TestActionCountPerRound:
    def test_no_actions_returns_zero(self):
        m = _make_mediator()
        assert m.action_count_per_round() == pytest.approx(0.0)

    def test_actions_with_no_rounds_defaults_to_one(self):
        m = _make_mediator()
        m._action_counts["expand"] = 5
        m._action_counts["prune"] = 3
        assert m.action_count_per_round() == pytest.approx(8.0)

    def test_actions_divided_by_rounds(self):
        m = _make_mediator()
        m._action_counts["expand"] = 6
        m._round_history = [MagicMock(), MagicMock(), MagicMock()]
        assert m.action_count_per_round() == pytest.approx(2.0)
