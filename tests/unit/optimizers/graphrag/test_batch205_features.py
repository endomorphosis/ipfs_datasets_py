"""Batch-205 feature tests.

Methods under test:
  - OntologyOptimizer.score_mean_above_baseline(baseline)
  - OntologyOptimizer.history_volatility_ratio()
  - OntologyGenerator.entity_with_longest_text(result)
  - OntologyGenerator.relationship_weight_entropy(result)
  - LogicValidator.max_path_length_estimate(ontology)
  - OntologyPipeline.run_improvement_fraction()
  - OntologyLearningAdapter.feedback_above_own_mean_count()
  - OntologyMediator.action_round_with_most()
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


def _make_entity(eid, text=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=text or eid)


def _make_rel_mock(weight=1.0):
    r = MagicMock()
    r.weight = weight
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


# ── OntologyOptimizer.score_mean_above_baseline ──────────────────────────────

class TestScoreMeanAboveBaseline:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_mean_above_baseline() == pytest.approx(0.0)

    def test_none_above_baseline_returns_zero(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3]:
            _push_opt(o, v)
        assert o.score_mean_above_baseline(baseline=0.5) == pytest.approx(0.0)

    def test_all_above_returns_mean(self):
        o = _make_optimizer()
        for v in [0.6, 0.8]:
            _push_opt(o, v)
        assert o.score_mean_above_baseline(baseline=0.5) == pytest.approx(0.7)

    def test_partial_above(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.9]:
            _push_opt(o, v)
        # above 0.5: 0.7, 0.9 → mean = 0.8
        assert o.score_mean_above_baseline(baseline=0.5) == pytest.approx(0.8)


# ── OntologyOptimizer.history_volatility_ratio ───────────────────────────────

class TestHistoryVolatilityRatio:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_volatility_ratio() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_volatility_ratio() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_volatility_ratio() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        result = o.history_volatility_ratio()
        assert isinstance(result, float)
        assert result >= 0.0


# ── OntologyGenerator.entity_with_longest_text ───────────────────────────────

class TestEntityWithLongestText:
    def test_empty_returns_none(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_with_longest_text(r) is None

    def test_single_entity_returned(self):
        g = _make_generator()
        e = _make_entity("a", text="hello")
        r = _make_result([e])
        assert g.entity_with_longest_text(r) is e

    def test_returns_longest(self):
        g = _make_generator()
        e_short = _make_entity("a", text="hi")
        e_long = _make_entity("b", text="a much longer text here")
        r = _make_result([e_short, e_long])
        assert g.entity_with_longest_text(r) is e_long


# ── OntologyGenerator.relationship_weight_entropy ────────────────────────────

class TestRelationshipWeightEntropy:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_weight_entropy(r) == pytest.approx(0.0)

    def test_uniform_weights_returns_zero(self):
        g = _make_generator()
        rels = [_make_rel_mock(weight=0.5), _make_rel_mock(weight=0.5)]
        r = _make_result(relationships=rels)
        assert g.relationship_weight_entropy(r) == pytest.approx(0.0)

    def test_two_different_buckets(self):
        g = _make_generator()
        rels = [_make_rel_mock(weight=0.1), _make_rel_mock(weight=0.9)]
        r = _make_result(relationships=rels)
        # two equal buckets → H = ln(2)
        assert g.relationship_weight_entropy(r) == pytest.approx(math.log(2))


# ── LogicValidator.max_path_length_estimate ──────────────────────────────────

class TestMaxPathLengthEstimate:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.max_path_length_estimate({}) == 0

    def test_single_edge_depth_one(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        assert v.max_path_length_estimate(onto) == 1

    def test_chain_length(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
            {"source": "c", "target": "d"},
        ]}
        assert v.max_path_length_estimate(onto) == 3

    def test_branching_returns_max(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "root", "target": "b"},
            {"source": "root", "target": "c"},
            {"source": "c", "target": "d"},
        ]}
        # max path: root→c→d = 2
        assert v.max_path_length_estimate(onto) == 2


# ── OntologyPipeline.run_improvement_fraction ────────────────────────────────

class TestRunImprovementFraction:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_improvement_fraction() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_improvement_fraction() == pytest.approx(0.0)

    def test_monotone_increasing(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        assert p.run_improvement_fraction() == pytest.approx(1.0)

    def test_monotone_decreasing(self):
        p = _make_pipeline()
        for v in [0.7, 0.5, 0.3]:
            _push_run(p, v)
        assert p.run_improvement_fraction() == pytest.approx(0.0)

    def test_half_improving(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5, 0.9]:
            _push_run(p, v)
        # steps: 0.3→0.7 ✓, 0.7→0.5 ✗, 0.5→0.9 ✓ → 2/3
        assert p.run_improvement_fraction() == pytest.approx(2 / 3)


# ── OntologyLearningAdapter.feedback_above_own_mean_count ────────────────────

class TestFeedbackAboveOwnMeanCount:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_above_own_mean_count() == 0

    def test_uniform_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_above_own_mean_count() == 0

    def test_two_above_mean(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8, 0.9]:
            _push_feedback(a, v)
        # mean = 0.6; 0.8 and 0.9 above → 2
        assert a.feedback_above_own_mean_count() == 2


# ── OntologyMediator.action_round_with_most ──────────────────────────────────

class TestActionRoundWithMost:
    def test_empty_returns_empty_string(self):
        m = _make_mediator()
        assert m.action_round_with_most() == ""

    def test_single_type(self):
        m = _make_mediator()
        m._action_counts = {"refine": 5}
        assert m.action_round_with_most() == "refine"

    def test_returns_max_count(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 1, "c": 3}
        assert m.action_round_with_most() == "a"

    def test_tie_returns_lexicographic_last(self):
        m = _make_mediator()
        m._action_counts = {"z": 5, "a": 5, "m": 5}
        assert m.action_round_with_most() == "z"
