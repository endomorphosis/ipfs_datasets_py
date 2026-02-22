"""Batch-192 feature tests.

Methods under test:
  - OntologyOptimizer.history_first()
  - OntologyOptimizer.history_last()
  - OntologyOptimizer.score_first()
  - OntologyOptimizer.score_last()
  - OntologyCritic.dimension_below_threshold(score, threshold)
  - OntologyGenerator.entity_confidence_range(result)
  - OntologyGenerator.relationship_min_confidence(result)
  - OntologyPipeline.run_improvement_rate()
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


# ── OntologyOptimizer.history_first ──────────────────────────────────────────

class TestHistoryFirst:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_first() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.history_first() == pytest.approx(0.7)

    def test_returns_first_not_last(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_first() == pytest.approx(0.3)


# ── OntologyOptimizer.history_last ───────────────────────────────────────────

class TestHistoryLast:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_last() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.4)
        assert o.history_last() == pytest.approx(0.4)

    def test_returns_last_not_first(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_last() == pytest.approx(0.9)


# ── OntologyOptimizer.score_first / score_last (aliases) ─────────────────────

class TestScoreFirstLast:
    def test_score_first_matches_history_first(self):
        o = _make_optimizer()
        for v in [0.2, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.score_first() == pytest.approx(o.history_first())

    def test_score_last_matches_history_last(self):
        o = _make_optimizer()
        for v in [0.2, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.score_last() == pytest.approx(o.history_last())

    def test_empty_score_first_zero(self):
        o = _make_optimizer()
        assert o.score_first() == pytest.approx(0.0)

    def test_empty_score_last_zero(self):
        o = _make_optimizer()
        assert o.score_last() == pytest.approx(0.0)


# ── OntologyCritic.dimension_below_threshold ─────────────────────────────────

class TestDimensionBelowThreshold:
    def test_none_below_returns_zero(self):
        c = _make_critic()
        s = _make_score(completeness=0.8, consistency=0.8, clarity=0.8,
                        granularity=0.8, relationship_coherence=0.8, domain_alignment=0.8)
        assert c.dimension_below_threshold(s, threshold=0.5) == 0

    def test_all_below_returns_six(self):
        c = _make_critic()
        s = _make_score(completeness=0.1, consistency=0.1, clarity=0.1,
                        granularity=0.1, relationship_coherence=0.1, domain_alignment=0.1)
        assert c.dimension_below_threshold(s, threshold=0.5) == 6

    def test_partial(self):
        c = _make_critic()
        s = _make_score(completeness=0.2, consistency=0.8, clarity=0.1,
                        granularity=0.9, relationship_coherence=0.3, domain_alignment=0.7)
        # below 0.5: completeness(0.2), clarity(0.1), relationship_coherence(0.3) = 3
        assert c.dimension_below_threshold(s, threshold=0.5) == 3

    def test_default_threshold(self):
        c = _make_critic()
        s = _make_score(completeness=0.4, consistency=0.6, clarity=0.3,
                        granularity=0.7, relationship_coherence=0.2, domain_alignment=0.8)
        # < 0.5: completeness(0.4), clarity(0.3), relationship_coherence(0.2) = 3
        assert c.dimension_below_threshold(s) == 3


# ── OntologyGenerator.entity_confidence_range ────────────────────────────────

class TestEntityConfidenceRange:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_confidence_range(r) == pytest.approx(0.0)

    def test_single_entity_returns_zero(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", 0.7)])
        assert g.entity_confidence_range(r) == pytest.approx(0.0)

    def test_range_of_multiple(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", 0.2),
            _make_entity("e2", 0.9),
            _make_entity("e3", 0.5),
        ])
        assert g.entity_confidence_range(r) == pytest.approx(0.7)


# ── OntologyGenerator.relationship_min_confidence ────────────────────────────

class TestRelationshipMinConfidence:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_min_confidence(r) == pytest.approx(0.0)

    def test_single_relationship(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock(confidence=0.6)])
        assert g.relationship_min_confidence(r) == pytest.approx(0.6)

    def test_minimum_of_multiple(self):
        g = _make_generator()
        rels = [_make_rel_mock(c) for c in [0.9, 0.3, 0.7]]
        r = _make_result(relationships=rels)
        assert g.relationship_min_confidence(r) == pytest.approx(0.3)


# ── OntologyPipeline.run_improvement_rate ────────────────────────────────────

class TestRunImprovementRate:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_improvement_rate() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_improvement_rate() == pytest.approx(0.0)

    def test_all_improving(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert p.run_improvement_rate() == pytest.approx(1.0)

    def test_all_declining(self):
        p = _make_pipeline()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push_run(p, v)
        assert p.run_improvement_rate() == pytest.approx(0.0)

    def test_half_improving(self):
        p = _make_pipeline()
        for v in [0.5, 0.8, 0.3, 0.9]:
            _push_run(p, v)
        # pairs: (0.5→0.8 ✓), (0.8→0.3 ✗), (0.3→0.9 ✓) → 2/3
        assert p.run_improvement_rate() == pytest.approx(2 / 3)
