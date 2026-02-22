"""Batch-207 feature tests.

Methods under test:
  - OntologyOptimizer.score_rebound_count()
  - OntologyOptimizer.history_zscore_last()
  - OntologyGenerator.entity_diversity_score(result)
  - OntologyGenerator.relationship_density_by_type(result)
  - LogicValidator.cycle_count_estimate(ontology)
  - OntologyPipeline.run_score_above_mean_count()
  - OntologyLearningAdapter.feedback_std_last_n(n)
  - OntologyMediator.action_entropy_normalized()
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


def _make_entity(eid, etype="T"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid)


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


# ── OntologyOptimizer.score_rebound_count ────────────────────────────────────

class TestScoreReboundCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_rebound_count() == 0

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        for v in [0.7, 0.5]:
            _push_opt(o, v)
        assert o.score_rebound_count() == 0

    def test_single_rebound(self):
        o = _make_optimizer()
        for v in [0.7, 0.3, 0.8]:
            _push_opt(o, v)
        # 0.3 is a local minimum → 1 rebound
        assert o.score_rebound_count() == 1

    def test_no_rebound_when_monotone_increasing(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.score_rebound_count() == 0


# ── OntologyOptimizer.history_zscore_last ────────────────────────────────────

class TestHistoryZscoreLast:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_zscore_last() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_zscore_last() == pytest.approx(0.0)

    def test_positive_z_when_last_above_mean(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_zscore_last() > 0.0

    def test_negative_z_when_last_below_mean(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.1]:
            _push_opt(o, v)
        assert o.history_zscore_last() < 0.0


# ── OntologyGenerator.entity_diversity_score ─────────────────────────────────

class TestEntityDiversityScore:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_diversity_score(r) == pytest.approx(0.0)

    def test_all_same_type(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", "T"), _make_entity("b", "T")])
        assert g.entity_diversity_score(r) == pytest.approx(0.5)

    def test_all_unique_types_returns_one(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("a", "Person"),
            _make_entity("b", "Org"),
            _make_entity("c", "Place"),
        ])
        assert g.entity_diversity_score(r) == pytest.approx(1.0)


# ── OntologyGenerator.relationship_density_by_type ───────────────────────────

class TestRelationshipDensityByType:
    def test_empty_returns_empty_dict(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_density_by_type(r) == {}

    def test_single_type_returns_one(self):
        g = _make_generator()
        rels = [_make_rel_mock("is_a"), _make_rel_mock("is_a")]
        r = _make_result(relationships=rels)
        result = g.relationship_density_by_type(r)
        assert result["is_a"] == pytest.approx(1.0)

    def test_two_types_equal_split(self):
        g = _make_generator()
        rels = [_make_rel_mock("is_a"), _make_rel_mock("part_of")]
        r = _make_result(relationships=rels)
        result = g.relationship_density_by_type(r)
        assert sum(result.values()) == pytest.approx(1.0)
        assert result["is_a"] == pytest.approx(0.5)


# ── LogicValidator.cycle_count_estimate ──────────────────────────────────────

class TestCycleCountEstimate:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.cycle_count_estimate({}) == 0

    def test_simple_tree_no_cycles(self):
        v = _make_validator()
        # a→b→c: V=3, E=2, C=1 → cycles = max(0, 2-3+1) = 0
        onto = {"relationships": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]}
        assert v.cycle_count_estimate(onto) == 0

    def test_self_loop_is_one_cycle(self):
        v = _make_validator()
        # a→a: V=1, E=1, C=1 → cycles = max(0, 1-1+1) = 1
        onto = {"relationships": [{"source": "a", "target": "a"}]}
        assert v.cycle_count_estimate(onto) == 1


# ── OntologyPipeline.run_score_above_mean_count ──────────────────────────────

class TestRunScoreAboveMeanCount:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_above_mean_count() == 0

    def test_uniform_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_above_mean_count() == 0

    def test_two_above_mean(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        # mean=0.6; 0.7 and 0.9 above → 2
        assert p.run_score_above_mean_count() == 2


# ── OntologyLearningAdapter.feedback_std_last_n ──────────────────────────────

class TestFeedbackStdLastN:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_std_last_n() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_std_last_n() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_std_last_n() == pytest.approx(0.0)

    def test_last_n_std(self):
        a = _make_adapter()
        for v in [0.1, 0.1, 0.8, 0.9]:
            _push_feedback(a, v)
        # last 2: [0.8, 0.9] mean=0.85, std=0.05
        assert a.feedback_std_last_n(n=2) == pytest.approx(0.05)


# ── OntologyMediator.action_entropy_normalized ───────────────────────────────

class TestActionEntropyNormalized:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_entropy_normalized() == pytest.approx(0.0)

    def test_single_type_returns_zero(self):
        m = _make_mediator()
        m._action_counts = {"refine": 5}
        assert m.action_entropy_normalized() == pytest.approx(0.0)

    def test_equal_distribution_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 5}
        assert m.action_entropy_normalized() == pytest.approx(1.0)

    def test_partial_diversity(self):
        m = _make_mediator()
        m._action_counts = {"a": 9, "b": 1}
        result = m.action_entropy_normalized()
        assert 0.0 < result < 1.0
