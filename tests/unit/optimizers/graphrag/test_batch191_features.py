"""Batch-191 feature tests.

Methods under test:
  - OntologyOptimizer.history_above_mean_count()
  - OntologyOptimizer.score_delta_mean()
  - OntologyOptimizer.history_median()
  - OntologyOptimizer.score_above_rolling_mean(window)
  - OntologyCritic.dimension_mean(score)
  - OntologyGenerator.entity_count_with_confidence_above(result, threshold)
  - OntologyGenerator.relationship_avg_confidence(result)
  - OntologyPipeline.run_score_delta()
  - OntologyLearningAdapter.feedback_score_sum()
  - OntologyMediator.action_least_frequent()
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


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_rel_mock(confidence=0.8):
    r = MagicMock()
    r.confidence = confidence
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


# ── OntologyOptimizer.history_above_mean_count ───────────────────────────────

class TestHistoryAboveMeanCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_above_mean_count() == 0

    def test_uniform_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_above_mean_count() == 0

    def test_half_above(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        # mean = 0.5; 0.6 and 0.8 are above → 2
        assert o.history_above_mean_count() == 2

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.history_above_mean_count() == 0


# ── OntologyOptimizer.score_delta_mean ───────────────────────────────────────

class TestScoreDeltaMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_delta_mean() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_delta_mean() == pytest.approx(0.0)

    def test_constant_scores_delta_zero(self):
        o = _make_optimizer()
        for _ in range(3):
            _push_opt(o, 0.5)
        assert o.score_delta_mean() == pytest.approx(0.0)

    def test_linearly_increasing(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        # all deltas = 0.2 → mean = 0.2
        assert o.score_delta_mean() == pytest.approx(0.2)

    def test_mixed_deltas(self):
        o = _make_optimizer()
        for v in [0.5, 0.8, 0.3]:
            _push_opt(o, v)
        # deltas: +0.3, -0.5 → mean = -0.1
        assert o.score_delta_mean() == pytest.approx(-0.1)


# ── OntologyOptimizer.history_median ─────────────────────────────────────────

class TestHistoryMedian:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_median() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.6)
        assert o.history_median() == pytest.approx(0.6)

    def test_odd_count(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_median() == pytest.approx(0.5)

    def test_even_count(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.history_median() == pytest.approx(0.5)


# ── OntologyOptimizer.score_above_rolling_mean ───────────────────────────────

class TestScoreAboveRollingMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_above_rolling_mean() == 0

    def test_uniform_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.score_above_rolling_mean() == 0

    def test_early_entries_above_low_rolling_mean(self):
        o = _make_optimizer()
        # history: [0.9, 0.9, 0.1, 0.1, 0.1]  rolling window=3 mean = 0.1
        for v in [0.9, 0.9, 0.1, 0.1, 0.1]:
            _push_opt(o, v)
        result = o.score_above_rolling_mean(window=3)
        assert result == 2  # first two entries (0.9) > 0.1


# ── OntologyCritic.dimension_mean ────────────────────────────────────────────

class TestDimensionMean:
    def test_uniform_score(self):
        c = _make_critic()
        s = _make_score()  # all 0.5
        assert c.dimension_mean(s) == pytest.approx(0.5)

    def test_varied_scores(self):
        c = _make_critic()
        s = _make_score(
            completeness=0.2, consistency=0.4, clarity=0.6,
            granularity=0.8, relationship_coherence=1.0, domain_alignment=0.0,
        )
        # sum = 3.0, n = 6 → mean = 0.5
        assert c.dimension_mean(s) == pytest.approx(0.5)

    def test_all_zero(self):
        c = _make_critic()
        s = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert c.dimension_mean(s) == pytest.approx(0.0)


# ── OntologyGenerator.entity_count_with_confidence_above ─────────────────────

class TestEntityCountWithConfidenceAbove:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_count_with_confidence_above(r) == 0

    def test_none_above_threshold(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", confidence=0.3), _make_entity("e2", confidence=0.5)])
        assert g.entity_count_with_confidence_above(r, threshold=0.7) == 0

    def test_all_above_threshold(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", 0.9), _make_entity("e2", 0.8)])
        assert g.entity_count_with_confidence_above(r, threshold=0.7) == 2

    def test_partial(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", 0.9),
            _make_entity("e2", 0.5),
            _make_entity("e3", 0.75),
        ])
        assert g.entity_count_with_confidence_above(r, threshold=0.7) == 2


# ── OntologyGenerator.relationship_avg_confidence ────────────────────────────

class TestRelationshipAvgConfidence:
    def test_no_relationships_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_avg_confidence(r) == pytest.approx(0.0)

    def test_single_relationship(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock(confidence=0.7)])
        assert g.relationship_avg_confidence(r) == pytest.approx(0.7)

    def test_average_of_multiple(self):
        g = _make_generator()
        rels = [_make_rel_mock(confidence=c) for c in [0.4, 0.8, 0.6]]
        r = _make_result(relationships=rels)
        assert g.relationship_avg_confidence(r) == pytest.approx(0.6)


# ── OntologyPipeline.run_score_delta ─────────────────────────────────────────

class TestRunScoreDelta:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_delta() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_delta() == pytest.approx(0.0)

    def test_improving_positive_delta(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.7)
        assert p.run_score_delta() == pytest.approx(0.4)

    def test_declining_negative_delta(self):
        p = _make_pipeline()
        _push_run(p, 0.8)
        _push_run(p, 0.5)
        _push_run(p, 0.3)
        assert p.run_score_delta() == pytest.approx(-0.5)


# ── OntologyLearningAdapter.feedback_score_sum ───────────────────────────────

class TestFeedbackScoreSum:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_score_sum() == pytest.approx(0.0)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_score_sum() == pytest.approx(0.7)

    def test_sum_of_all(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_score_sum() == pytest.approx(1.5)


# ── OntologyMediator.action_least_frequent ───────────────────────────────────

class TestActionLeastFrequent:
    def test_no_actions_returns_empty_string(self):
        m = _make_mediator()
        assert m.action_least_frequent() == ""

    def test_single_action(self):
        m = _make_mediator()
        m._action_counts["expand"] = 5
        assert m.action_least_frequent() == "expand"

    def test_returns_least_frequent(self):
        m = _make_mediator()
        m._action_counts["expand"] = 7
        m._action_counts["prune"] = 2
        m._action_counts["merge"] = 5
        assert m.action_least_frequent() == "prune"
