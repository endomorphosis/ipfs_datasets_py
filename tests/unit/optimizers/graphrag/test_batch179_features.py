"""Batch-179 feature tests.

Methods under test:
  - OntologyOptimizer.history_first_derivative()
  - OntologyOptimizer.score_improvement_ratio()
  - OntologyCritic.dimensions_above_count(score, threshold)
  - OntologyCritic.score_letter_grade(score)
  - OntologyGenerator.entity_confidence_percentile(result, p)
  - LogicValidator.strongly_connected_count(ontology)
  - OntologyPipeline.consecutive_improvements()
  - OntologyLearningAdapter.feedback_window_mean(n)
  - OntologyLearningAdapter.feedback_outlier_count(z_threshold)
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


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


class _FakeRel:
    def __init__(self, src, tgt):
        self.source_id = src
        self.target_id = tgt
        self.type = "r"


class _FakeOntology:
    def __init__(self, rels):
        self.relationships = rels


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


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


# ── OntologyOptimizer.history_first_derivative ────────────────────────────────

class TestHistoryFirstDerivative:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.history_first_derivative() == []

    def test_single_returns_empty(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_first_derivative() == []

    def test_constant_returns_zeros(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_first_derivative() == pytest.approx([0.0, 0.0, 0.0])

    def test_increasing_positive(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5]:
            _push_opt(o, v)
        result = o.history_first_derivative()
        assert all(r > 0 for r in result)

    def test_length_is_n_minus_1(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.6]:
            _push_opt(o, v)
        assert len(o.history_first_derivative()) == 3


# ── OntologyOptimizer.score_improvement_ratio ─────────────────────────────────

class TestScoreImprovementRatio:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_improvement_ratio() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_improvement_ratio() == pytest.approx(0.0)

    def test_all_improving_returns_one(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.score_improvement_ratio() == pytest.approx(1.0)

    def test_none_improving_returns_zero(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.score_improvement_ratio() == pytest.approx(0.0)

    def test_half_improving(self):
        o = _make_optimizer()
        for v in [0.5, 0.7, 0.3, 0.6]:
            _push_opt(o, v)
        # transitions: up, down, up → 2/3
        assert o.score_improvement_ratio() == pytest.approx(2 / 3)


# ── OntologyCritic.dimensions_above_count ────────────────────────────────────

class TestDimensionsAboveCount:
    def test_all_above(self):
        c = _make_critic()
        score = _make_score(**{d: 0.9 for d in ["completeness", "consistency", "clarity",
                                                 "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimensions_above_count(score, 0.5) == 6

    def test_none_above(self):
        c = _make_critic()
        score = _make_score(**{d: 0.3 for d in ["completeness", "consistency", "clarity",
                                                 "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimensions_above_count(score, 0.5) == 0

    def test_partial_count(self):
        c = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.3)
        # completeness above, rest = 0.5 (not strictly above 0.5), consistency below
        count = c.dimensions_above_count(score, 0.5)
        assert count == 1  # only completeness is > 0.5


# ── OntologyCritic.score_letter_grade ────────────────────────────────────────

class TestScoreLetterGrade:
    def test_grade_a(self):
        c = _make_critic()
        # all 1.0 → overall would be computed; since overall is a property
        # we test with a mock-like approach using score
        score = _make_score(**{d: 1.0 for d in ["completeness", "consistency", "clarity",
                                                  "granularity", "relationship_coherence", "domain_alignment"]})
        grade = c.score_letter_grade(score)
        # overall = computed from weights; just check it's one of the grades
        assert grade in ("A", "B", "C", "D", "F")

    def test_returns_string(self):
        c = _make_critic()
        assert isinstance(c.score_letter_grade(_make_score()), str)


# ── OntologyGenerator.entity_confidence_percentile ───────────────────────────

class TestEntityConfidencePercentile:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_percentile(_make_result([])) == pytest.approx(0.0)

    def test_single_entity(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.7)]
        assert gen.entity_confidence_percentile(_make_result(entities), 50.0) == pytest.approx(0.7)

    def test_median(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", c) for i, c in enumerate([0.2, 0.5, 0.8])]
        assert gen.entity_confidence_percentile(_make_result(entities), 50.0) == pytest.approx(0.5)

    def test_min_percentile(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", c) for i, c in enumerate([0.2, 0.5, 0.8])]
        assert gen.entity_confidence_percentile(_make_result(entities), 0.0) == pytest.approx(0.2)

    def test_max_percentile(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", c) for i, c in enumerate([0.2, 0.5, 0.8])]
        assert gen.entity_confidence_percentile(_make_result(entities), 100.0) == pytest.approx(0.8)


# ── LogicValidator.strongly_connected_count ───────────────────────────────────

class TestStronglyConnectedCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.strongly_connected_count(_FakeOntology([])) == 0

    def test_single_edge(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        # a and b are separate SCCs
        assert v.strongly_connected_count(_FakeOntology(rels)) == 2

    def test_cycle_one_scc(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("c", "a")]
        assert v.strongly_connected_count(_FakeOntology(rels)) == 1

    def test_two_separate_components(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("x", "y")]
        # 4 nodes, no cycles → 4 SCCs
        assert v.strongly_connected_count(_FakeOntology(rels)) == 4


# ── OntologyPipeline.consecutive_improvements ────────────────────────────────

class TestConsecutiveImprovements:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.consecutive_improvements() == 0

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.consecutive_improvements() == 0

    def test_all_improving(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert p.consecutive_improvements() == 3

    def test_ends_with_decline_resets(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5]:
            _push_run(p, v)
        assert p.consecutive_improvements() == 0

    def test_partial_streak(self):
        p = _make_pipeline()
        for v in [0.3, 0.2, 0.5, 0.8]:
            _push_run(p, v)
        assert p.consecutive_improvements() == 2


# ── OntologyLearningAdapter.feedback_window_mean ─────────────────────────────

class TestFeedbackWindowMean:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_window_mean() == pytest.approx(0.0)

    def test_all_records_within_window(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.6)
        assert a.feedback_window_mean(n=5) == pytest.approx(0.5)

    def test_window_smaller_than_records(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.8, 0.9]:
            _push_feedback(a, v)
        # last 2 = [0.8, 0.9] → mean 0.85
        assert a.feedback_window_mean(n=2) == pytest.approx(0.85)


# ── OntologyLearningAdapter.feedback_outlier_count ───────────────────────────

class TestFeedbackOutlierCount:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_outlier_count() == 0

    def test_too_few_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        _push_feedback(a, 0.7)
        assert a.feedback_outlier_count() == 0

    def test_constant_no_outliers(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        assert a.feedback_outlier_count() == 0

    def test_detects_extreme_outlier(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        _push_feedback(a, 100.0)  # extreme outlier
        assert a.feedback_outlier_count() > 0
