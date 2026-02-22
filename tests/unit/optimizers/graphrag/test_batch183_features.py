"""Batch-183 feature tests.

Methods under test:
  - OntologyOptimizer.history_outlier_count(z_thresh)
  - OntologyOptimizer.score_autocorrelation(lag)
  - OntologyCritic.dimension_spread(score)
  - OntologyCritic.top_dimension(score)
  - OntologyGenerator.relationship_coverage(result)
  - OntologyGenerator.entity_confidence_variance(result)
  - OntologyPipeline.run_score_kurtosis()
  - OntologyPipeline.run_score_sum()
  - OntologyLearningAdapter.feedback_below_mean_count()
  - OntologyLearningAdapter.feedback_above_median()
  - OntologyMediator.action_entropy()
  - OntologyMediator.total_action_count()
"""
import pytest
from unittest.mock import MagicMock


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


def _make_relationship(sid, tid, rtype="r"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=f"{sid}-{tid}", type=rtype, source_id=sid, target_id=tid)


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score))


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    gen = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=critic)


# ── OntologyOptimizer.history_outlier_count ───────────────────────────────────

class TestHistoryOutlierCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_outlier_count() == 0

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_outlier_count() == 0

    def test_all_same_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.history_outlier_count() == 0

    def test_detects_outlier(self):
        o = _make_optimizer()
        for _ in range(8):
            _push_opt(o, 0.5)
        _push_opt(o, 10.0)  # clear outlier
        assert o.history_outlier_count() >= 1

    def test_returns_int(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert isinstance(o.history_outlier_count(), int)


# ── OntologyOptimizer.score_autocorrelation ───────────────────────────────────

class TestScoreAutocorrelation:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_autocorrelation() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_autocorrelation() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.score_autocorrelation() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert isinstance(o.score_autocorrelation(), float)

    def test_in_range(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.5, 0.3]:
            _push_opt(o, v)
        ac = o.score_autocorrelation()
        assert -1.0 <= ac <= 1.0


# ── OntologyCritic.dimension_spread ───────────────────────────────────────────

class TestDimensionSpread:
    def test_all_same_returns_zero(self):
        c = _make_critic()
        assert c.dimension_spread(_make_score()) == pytest.approx(0.0)

    def test_full_range(self):
        c = _make_critic()
        score = _make_score(completeness=1.0, consistency=0.0)
        assert c.dimension_spread(score) == pytest.approx(1.0)

    def test_partial_range(self):
        c = _make_critic()
        score = _make_score(completeness=0.8, consistency=0.2)
        spread = c.dimension_spread(score)
        assert spread == pytest.approx(0.6)

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.dimension_spread(_make_score()), float)


# ── OntologyCritic.top_dimension ──────────────────────────────────────────────

class TestTopDimension:
    def test_returns_string(self):
        c = _make_critic()
        assert isinstance(c.top_dimension(_make_score()), str)

    def test_identifies_highest(self):
        c = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.1)
        assert c.top_dimension(score) == "completeness"

    def test_valid_dimension_name(self):
        c = _make_critic()
        dims = {"completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"}
        assert c.top_dimension(_make_score()) in dims


# ── OntologyGenerator.relationship_coverage ──────────────────────────────────

class TestRelationshipCoverage:
    def test_empty_entities_returns_zero(self):
        gen = _make_generator()
        assert gen.relationship_coverage(_make_result([])) == pytest.approx(0.0)

    def test_no_rels_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        assert gen.relationship_coverage(_make_result(entities)) == pytest.approx(0.0)

    def test_all_covered(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        rels = [_make_relationship("e1", "e2")]
        assert gen.relationship_coverage(_make_result(entities, rels)) == pytest.approx(1.0)

    def test_partial_coverage(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2"), _make_entity("e3")]
        rels = [_make_relationship("e1", "e2")]
        # e1, e2 covered; e3 not → 2/3
        assert gen.relationship_coverage(_make_result(entities, rels)) == pytest.approx(2 / 3)


# ── OntologyGenerator.entity_confidence_variance ─────────────────────────────

class TestEntityConfidenceVariance:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_variance(_make_result([])) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_variance(_make_result([_make_entity("e1")])) == pytest.approx(0.0)

    def test_all_same_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.5), _make_entity("e2", 0.5)]
        assert gen.entity_confidence_variance(_make_result(entities)) == pytest.approx(0.0)

    def test_nonzero_for_varied(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.1), _make_entity("e2", 0.9)]
        assert gen.entity_confidence_variance(_make_result(entities)) > 0


# ── OntologyPipeline.run_score_kurtosis ───────────────────────────────────────

class TestRunScoreKurtosis:
    def test_too_few_returns_zero(self):
        p = _make_pipeline()
        for v in [0.5, 0.6, 0.7]:
            _push_run(p, v)
        assert p.run_score_kurtosis() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        p = _make_pipeline()
        for _ in range(5):
            _push_run(p, 0.5)
        assert p.run_score_kurtosis() == pytest.approx(0.0)

    def test_returns_float(self):
        p = _make_pipeline()
        for v in [0.1, 0.5, 0.5, 0.5, 0.9]:
            _push_run(p, v)
        assert isinstance(p.run_score_kurtosis(), float)


# ── OntologyPipeline.run_score_sum ────────────────────────────────────────────

class TestRunScoreSum:
    def test_no_runs_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_sum() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.run_score_sum() == pytest.approx(0.7)

    def test_multiple_runs(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        assert p.run_score_sum() == pytest.approx(1.5)


# ── OntologyLearningAdapter.feedback_below_mean_count ────────────────────────

class TestFeedbackBelowMeanCount:
    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_below_mean_count() == 0

    def test_all_same_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_below_mean_count() == 0

    def test_one_below(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.7)
        # mean = 0.5; only 0.3 < 0.5
        assert a.feedback_below_mean_count() == 1

    def test_returns_int(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert isinstance(a.feedback_below_mean_count(), int)


# ── OntologyLearningAdapter.feedback_above_median ────────────────────────────

class TestFeedbackAboveMedian:
    def test_empty_returns_empty_list(self):
        a = _make_adapter()
        assert a.feedback_above_median() == []

    def test_fewer_than_two_returns_empty(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_above_median() == []

    def test_one_above(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.9]:
            _push_feedback(a, v)
        # median = 0.5; only record with 0.9 > 0.5
        result = a.feedback_above_median()
        assert len(result) == 1
        assert result[0].final_score == pytest.approx(0.9)


# ── OntologyMediator.action_entropy ──────────────────────────────────────────

class TestActionEntropy:
    def test_no_actions_returns_zero(self):
        m = _make_mediator()
        assert m.action_entropy() == pytest.approx(0.0)

    def test_single_action_returns_zero(self):
        m = _make_mediator()
        m._action_counts["add_entity"] = 5
        assert m.action_entropy() == pytest.approx(0.0)

    def test_two_equal_actions_positive(self):
        m = _make_mediator()
        m._action_counts["add_entity"] = 3
        m._action_counts["remove_entity"] = 3
        assert m.action_entropy() > 0

    def test_returns_float(self):
        m = _make_mediator()
        m._action_counts["add_entity"] = 1
        assert isinstance(m.action_entropy(), float)


# ── OntologyMediator.total_action_count ──────────────────────────────────────

class TestTotalActionCount:
    def test_no_actions_returns_zero(self):
        m = _make_mediator()
        assert m.total_action_count() == 0

    def test_sums_counts(self):
        m = _make_mediator()
        m._action_counts["add_entity"] = 3
        m._action_counts["remove_entity"] = 2
        assert m.total_action_count() == 5

    def test_returns_int(self):
        m = _make_mediator()
        assert isinstance(m.total_action_count(), int)
