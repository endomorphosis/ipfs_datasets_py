"""Batch-172 feature tests.

Methods under test:
  - OntologyOptimizer.__repr__
  - OntologyOptimizer.score_cumulative_max()
  - OntologyPipeline.__repr__
  - FeedbackRecord.__repr__
  - OntologyLearningAdapter.feedback_ewma(alpha)
  - OntologyLearningAdapter.feedback_normalized()
  - LogicValidator.fanout_ratio(ontology)
  - LogicValidator.symmetric_pair_count(ontology)
  - OntologyMediator.most_improved_action()
  - OntologyCritic.score_is_above_baseline(score, baseline)
"""
import pytest
from unittest.mock import MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_pipeline(domain="test"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline(domain=domain)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score, actions=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score, action_types=actions or []))


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


class _FakeRel:
    def __init__(self, src, tgt, rtype="r"):
        self.source_id = src
        self.target_id = tgt
        self.type = rtype


class _FakeOntology:
    def __init__(self, rels):
        self.relationships = rels


# ── OntologyOptimizer.__repr__ ────────────────────────────────────────────────

class TestOptimizerRepr:
    def test_repr_contains_class_name(self):
        o = _make_optimizer()
        r = repr(o)
        assert "OntologyOptimizer" in r

    def test_repr_contains_history_len(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert "history_len=1" in repr(o)

    def test_repr_is_str(self):
        assert isinstance(repr(_make_optimizer()), str)


# ── OntologyOptimizer.score_cumulative_max ────────────────────────────────────

class TestScoreCumulativeMax:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.score_cumulative_max() == []

    def test_monotone_increasing(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.6]:
            _push_opt(o, v)
        result = o.score_cumulative_max()
        assert result == pytest.approx([0.3, 0.5, 0.7, 0.7])

    def test_all_same(self):
        o = _make_optimizer()
        for _ in range(3):
            _push_opt(o, 0.5)
        assert o.score_cumulative_max() == pytest.approx([0.5, 0.5, 0.5])

    def test_length_matches_history(self):
        o = _make_optimizer()
        for v in [0.1, 0.9, 0.5]:
            _push_opt(o, v)
        assert len(o.score_cumulative_max()) == 3


# ── OntologyPipeline.__repr__ ─────────────────────────────────────────────────

class TestPipelineRepr:
    def test_repr_contains_class_name(self):
        assert "OntologyPipeline" in repr(_make_pipeline())

    def test_repr_contains_domain(self):
        assert "test" in repr(_make_pipeline("test"))

    def test_repr_contains_runs(self):
        p = _make_pipeline()
        assert "runs=0" in repr(p)


# ── FeedbackRecord.__repr__ ───────────────────────────────────────────────────

class TestFeedbackRecordRepr:
    def test_repr_contains_class_name(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
        r = FeedbackRecord(final_score=0.75)
        assert "FeedbackRecord" in repr(r)

    def test_repr_contains_score(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
        r = FeedbackRecord(final_score=0.75)
        assert "0.750" in repr(r)


# ── OntologyLearningAdapter.feedback_ewma ────────────────────────────────────

class TestFeedbackEWMA:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_ewma() == pytest.approx(0.0)

    def test_single_record_returns_score(self):
        a = _make_adapter()
        _push_feedback(a, 0.8)
        assert a.feedback_ewma() == pytest.approx(0.8)

    def test_ewma_weights_recent_higher(self):
        a = _make_adapter()
        _push_feedback(a, 0.0)
        _push_feedback(a, 1.0)
        # with alpha=1.0 (fully reactive), last value dominates
        assert a.feedback_ewma(alpha=1.0) == pytest.approx(1.0)

    def test_returns_float(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert isinstance(a.feedback_ewma(), float)


# ── OntologyLearningAdapter.feedback_normalized ───────────────────────────────

class TestFeedbackNormalized:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.feedback_normalized() == []

    def test_single_record_returns_empty(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_normalized() == []

    def test_identical_returns_zeros(self):
        a = _make_adapter()
        for _ in range(3):
            _push_feedback(a, 0.5)
        assert a.feedback_normalized() == [0.0, 0.0, 0.0]

    def test_normalised_range(self):
        a = _make_adapter()
        _push_feedback(a, 0.0)
        _push_feedback(a, 0.5)
        _push_feedback(a, 1.0)
        n = a.feedback_normalized()
        assert n[0] == pytest.approx(0.0)
        assert n[-1] == pytest.approx(1.0)


# ── LogicValidator.fanout_ratio ───────────────────────────────────────────────

class TestFanoutRatio:
    def _make_validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        return LogicValidator()

    def test_no_rels_returns_zero(self):
        v = self._make_validator()
        assert v.fanout_ratio(_FakeOntology([])) == pytest.approx(0.0)

    def test_all_unique_targets_returns_one(self):
        v = self._make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("a", "c"), _FakeRel("a", "d")]
        assert v.fanout_ratio(_FakeOntology(rels)) == pytest.approx(1.0)

    def test_same_target_reduces_ratio(self):
        v = self._make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("c", "b")]  # same target b
        ratio = v.fanout_ratio(_FakeOntology(rels))
        assert ratio == pytest.approx(0.5)


# ── LogicValidator.symmetric_pair_count ───────────────────────────────────────

class TestSymmetricPairCount:
    def _make_validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        return LogicValidator()

    def test_no_rels_returns_zero(self):
        v = self._make_validator()
        assert v.symmetric_pair_count(_FakeOntology([])) == 0

    def test_no_symmetric_pairs(self):
        v = self._make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c")]
        assert v.symmetric_pair_count(_FakeOntology(rels)) == 0

    def test_one_symmetric_pair(self):
        v = self._make_validator()
        rels = [_FakeRel("a", "b", "knows"), _FakeRel("b", "a", "knows")]
        assert v.symmetric_pair_count(_FakeOntology(rels)) == 1

    def test_different_types_not_symmetric(self):
        v = self._make_validator()
        rels = [_FakeRel("a", "b", "knows"), _FakeRel("b", "a", "likes")]
        assert v.symmetric_pair_count(_FakeOntology(rels)) == 0


# ── OntologyMediator.most_improved_action ─────────────────────────────────────

class TestMostImprovedAction:
    def _make_mediator(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        return OntologyMediator(generator=OntologyGenerator(), critic=OntologyCritic(use_llm=False))

    def test_no_feedback_returns_none(self):
        m = self._make_mediator()
        assert m.most_improved_action() is None

    def test_single_action(self):
        m = self._make_mediator()
        m._action_counts["merge"] = 3
        result = m.most_improved_action()
        assert result == "merge"

    def test_best_action_selected(self):
        m = self._make_mediator()
        m._action_counts["split"] = 1
        m._action_counts["merge"] = 5
        result = m.most_improved_action()
        assert result == "merge"


# ── OntologyCritic.score_is_above_baseline ────────────────────────────────────

class TestScoreIsAboveBaseline:
    def test_all_above_returns_true(self):
        critic = _make_critic()
        score = _make_score(**{d: 0.9 for d in
                               ["completeness", "consistency", "clarity",
                                "granularity", "relationship_coherence", "domain_alignment"]})
        assert critic.score_is_above_baseline(score, baseline=0.5)

    def test_one_below_returns_false(self):
        critic = _make_critic()
        score = _make_score(completeness=0.3)
        assert not critic.score_is_above_baseline(score, baseline=0.5)

    def test_at_baseline_returns_false(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        assert not critic.score_is_above_baseline(score, baseline=0.5)

    def test_custom_baseline(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        assert critic.score_is_above_baseline(score, baseline=0.4)
