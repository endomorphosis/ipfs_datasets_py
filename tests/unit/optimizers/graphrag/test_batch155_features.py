"""Batch-155 feature tests.

Methods under test:
  - OntologyPipeline.scores_above_mean()
  - OntologyGenerator.entity_count_by_type(result)
  - OntologyLearningAdapter.best_domain()
  - OntologyOptimizer.score_momentum_delta(window)
"""
import pytest
from unittest.mock import MagicMock


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, overall):
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    p._run_history.append(run)


def _make_entity(eid, etype="Person"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score, domain=None):
    r = MagicMock()
    r.final_score = score
    r.domain = domain
    a._feedback.append(r)


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


# ---------------------------------------------------------------------------
# OntologyPipeline.scores_above_mean
# ---------------------------------------------------------------------------

class TestScoresAboveMean:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.scores_above_mean() == []

    def test_all_equal_returns_empty(self):
        p = _make_pipeline()
        for _ in range(3):
            _push_run(p, 0.5)
        assert p.scores_above_mean() == []

    def test_above_mean_count(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.8, 0.9]:
            _push_run(p, v)
        # mean = 0.575; above: 0.8, 0.9
        result = p.scores_above_mean()
        assert len(result) == 2

    def test_all_scores_are_above_mean(self):
        p = _make_pipeline()
        for v in [0.2, 0.8]:
            _push_run(p, v)
        result = p.scores_above_mean()
        scores = [r.score.overall for r in result]
        assert all(s > 0.5 for s in scores)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_count_by_type
# ---------------------------------------------------------------------------

class TestEntityCountByType:
    def test_empty_returns_empty(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.entity_count_by_type(result) == {}

    def test_single_type(self):
        gen = _make_generator()
        entities = [_make_entity("e1", "Person"), _make_entity("e2", "Person")]
        result = _make_result(entities)
        counts = gen.entity_count_by_type(result)
        assert counts == {"Person": 2}

    def test_multiple_types(self):
        gen = _make_generator()
        entities = [
            _make_entity("e1", "Person"),
            _make_entity("e2", "Org"),
            _make_entity("e3", "Person"),
        ]
        result = _make_result(entities)
        counts = gen.entity_count_by_type(result)
        assert counts["Person"] == 2
        assert counts["Org"] == 1

    def test_total_equals_entity_count(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", f"T{i % 3}") for i in range(9)]
        result = _make_result(entities)
        counts = gen.entity_count_by_type(result)
        assert sum(counts.values()) == 9


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.best_domain
# ---------------------------------------------------------------------------

class TestBestDomain:
    def test_empty_returns_empty_string(self):
        a = _make_adapter()
        assert a.best_domain() == ""

    def test_single_domain(self):
        a = _make_adapter()
        _push_feedback(a, 0.7, domain="tech")
        assert a.best_domain() == "tech"

    def test_returns_highest_avg_domain(self):
        a = _make_adapter()
        _push_feedback(a, 0.3, domain="medicine")
        _push_feedback(a, 0.9, domain="law")
        _push_feedback(a, 0.8, domain="law")
        # law avg=0.85, medicine avg=0.3 → best is law
        assert a.best_domain() == "law"


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_momentum_delta
# ---------------------------------------------------------------------------

class TestScoreMomentumDelta:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_momentum_delta() == pytest.approx(0.0)

    def test_too_few_returns_zero(self):
        o = _make_optimizer()
        for v in [0.5, 0.6, 0.7]:
            _push_opt(o, v)
        assert o.score_momentum_delta(window=3) == pytest.approx(0.0)

    def test_positive_momentum(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]:
            _push_opt(o, v)
        assert o.score_momentum_delta(window=3) > 0

    def test_negative_momentum(self):
        o = _make_optimizer()
        for v in [0.8, 0.9, 1.0, 0.1, 0.2, 0.3]:
            _push_opt(o, v)
        assert o.score_momentum_delta(window=3) < 0

    def test_flat_returns_zero(self):
        o = _make_optimizer()
        for _ in range(6):
            _push_opt(o, 0.5)
        assert o.score_momentum_delta(window=3) == pytest.approx(0.0)
