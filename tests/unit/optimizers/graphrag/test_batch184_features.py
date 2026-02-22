"""Batch-184 feature tests.

Methods under test:
  - OntologyOptimizer.history_cross_mean_count()
  - OntologyOptimizer.score_recent_max(window)
  - OntologyOptimizer.score_recent_min(window)
  - OntologyCritic.bottom_dimension(score)
  - OntologyCritic.score_above_threshold_count(score, threshold)
  - OntologyGenerator.entity_property_count(result)
  - OntologyGenerator.entity_types_set(result)
  - OntologyPipeline.run_score_geometric_mean()
  - OntologyPipeline.best_run_index()
  - OntologyLearningAdapter.feedback_min_max_ratio()
  - OntologyLearningAdapter.feedback_count()
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


def _make_entity(eid, etype="T", props=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid, properties=props or {})


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


# ── OntologyOptimizer.history_cross_mean_count ────────────────────────────────

class TestHistoryCrossMeanCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_cross_mean_count() == 0

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_cross_mean_count() == 0

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.history_cross_mean_count() == 0

    def test_alternating_counts_crossings(self):
        o = _make_optimizer()
        # alternating above/below mean (0.5) → many crossings
        for v in [0.3, 0.7, 0.3, 0.7]:
            _push_opt(o, v)
        assert o.history_cross_mean_count() >= 1

    def test_returns_int(self):
        o = _make_optimizer()
        for v in [0.3, 0.7]:
            _push_opt(o, v)
        assert isinstance(o.history_cross_mean_count(), int)


# ── OntologyOptimizer.score_recent_max ───────────────────────────────────────

class TestScoreRecentMax:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_recent_max() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.score_recent_max() == pytest.approx(0.7)

    def test_uses_window(self):
        o = _make_optimizer()
        for v in [0.9, 0.3, 0.5]:
            _push_opt(o, v)
        # window=2 → last 2 = [0.3, 0.5]; max = 0.5
        assert o.score_recent_max(window=2) == pytest.approx(0.5)


# ── OntologyOptimizer.score_recent_min ───────────────────────────────────────

class TestScoreRecentMin:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_recent_min() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        assert o.score_recent_min() == pytest.approx(0.3)

    def test_uses_window(self):
        o = _make_optimizer()
        for v in [0.1, 0.7, 0.9]:
            _push_opt(o, v)
        # window=2 → last 2 = [0.7, 0.9]; min = 0.7
        assert o.score_recent_min(window=2) == pytest.approx(0.7)


# ── OntologyCritic.bottom_dimension ──────────────────────────────────────────

class TestBottomDimension:
    def test_returns_string(self):
        c = _make_critic()
        assert isinstance(c.bottom_dimension(_make_score()), str)

    def test_identifies_lowest(self):
        c = _make_critic()
        score = _make_score(consistency=0.05)
        assert c.bottom_dimension(score) == "consistency"

    def test_valid_dimension_name(self):
        c = _make_critic()
        dims = {"completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"}
        assert c.bottom_dimension(_make_score()) in dims


# ── OntologyCritic.score_above_threshold_count ───────────────────────────────

class TestScoreAboveThresholdCount:
    def test_none_above_default(self):
        c = _make_critic()
        # all dims = 0.5 < 0.7
        assert c.score_above_threshold_count(_make_score()) == 0

    def test_all_above(self):
        c = _make_critic()
        score = _make_score(**{d: 0.8 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.score_above_threshold_count(score) == 6

    def test_some_above(self):
        c = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.8)
        assert c.score_above_threshold_count(score, threshold=0.7) == 2

    def test_returns_int(self):
        c = _make_critic()
        assert isinstance(c.score_above_threshold_count(_make_score()), int)


# ── OntologyGenerator.entity_property_count ──────────────────────────────────

class TestEntityPropertyCount:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_property_count(_make_result([])) == 0

    def test_no_properties(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        assert gen.entity_property_count(_make_result(entities)) == 0

    def test_counts_properties(self):
        gen = _make_generator()
        entities = [
            _make_entity("e1", props={"k1": "v1", "k2": "v2"}),
            _make_entity("e2", props={"k3": "v3"}),
        ]
        assert gen.entity_property_count(_make_result(entities)) == 3

    def test_returns_int(self):
        gen = _make_generator()
        assert isinstance(gen.entity_property_count(_make_result([])), int)


# ── OntologyGenerator.entity_types_set ───────────────────────────────────────

class TestEntityTypesSet:
    def test_empty_returns_empty_set(self):
        gen = _make_generator()
        assert gen.entity_types_set(_make_result([])) == set()

    def test_single_type(self):
        gen = _make_generator()
        entities = [_make_entity("e1", etype="Person")]
        assert gen.entity_types_set(_make_result(entities)) == {"Person"}

    def test_multiple_types(self):
        gen = _make_generator()
        entities = [
            _make_entity("e1", etype="Person"),
            _make_entity("e2", etype="Place"),
            _make_entity("e3", etype="Person"),
        ]
        assert gen.entity_types_set(_make_result(entities)) == {"Person", "Place"}


# ── OntologyPipeline.run_score_geometric_mean ─────────────────────────────────

class TestRunScoreGeometricMean:
    def test_no_runs_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_geometric_mean() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_geometric_mean() == pytest.approx(0.5, rel=1e-3)

    def test_all_same(self):
        p = _make_pipeline()
        for _ in range(3):
            _push_run(p, 0.6)
        assert p.run_score_geometric_mean() == pytest.approx(0.6, rel=1e-3)

    def test_geom_leq_arith(self):
        p = _make_pipeline()
        vals = [0.3, 0.5, 0.7]
        for v in vals:
            _push_run(p, v)
        arith = sum(vals) / len(vals)
        assert p.run_score_geometric_mean() <= arith + 1e-9


# ── OntologyPipeline.best_run_index ──────────────────────────────────────────

class TestBestRunIndex:
    def test_no_runs_returns_minus_one(self):
        p = _make_pipeline()
        assert p.best_run_index() == -1

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.best_run_index() == 0

    def test_identifies_best(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.9)
        _push_run(p, 0.5)
        assert p.best_run_index() == 1

    def test_returns_int(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert isinstance(p.best_run_index(), int)


# ── OntologyLearningAdapter.feedback_min_max_ratio ───────────────────────────

class TestFeedbackMinMaxRatio:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_min_max_ratio() == pytest.approx(0.0)

    def test_all_same_returns_one(self):
        a = _make_adapter()
        for _ in range(3):
            _push_feedback(a, 0.6)
        assert a.feedback_min_max_ratio() == pytest.approx(1.0)

    def test_ratio(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.8)
        assert a.feedback_min_max_ratio() == pytest.approx(0.5)


# ── OntologyLearningAdapter.feedback_count ───────────────────────────────────

class TestFeedbackCount:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_count() == 0

    def test_counts_records(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        assert a.feedback_count() == 5

    def test_returns_int(self):
        a = _make_adapter()
        assert isinstance(a.feedback_count(), int)
