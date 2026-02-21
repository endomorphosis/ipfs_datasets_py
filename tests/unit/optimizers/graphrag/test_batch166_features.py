"""Batch-166 feature tests.

Methods under test:
  - OntologyOptimizer.history_skewness()
  - OntologyCritic.dimension_std(score)
  - OntologyCritic.dimension_improvement_mask(before, after)
  - OntologyCritic.passing_dimensions(score, threshold)
  - OntologyGenerator.max_confidence_entity(result)
  - OntologyGenerator.min_confidence_entity(result)
  - OntologyGenerator.entity_confidence_std(result)
  - OntologyPipeline.best_k_scores(k)
  - OntologyPipeline.worst_k_scores(k)
"""
import pytest
from unittest.mock import MagicMock


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


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=1.0, metadata={}, errors=[]
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
# OntologyOptimizer.history_skewness
# ---------------------------------------------------------------------------

class TestHistorySkewness:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_skewness() == pytest.approx(0.0)

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.history_skewness() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.history_skewness() == pytest.approx(0.0)

    def test_symmetric_distribution(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.5, 0.5, 0.8]:
            _push_opt(o, v)
        # symmetric should be near 0
        assert abs(o.history_skewness()) < 0.5

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.8]:
            _push_opt(o, v)
        assert isinstance(o.history_skewness(), float)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_std
# ---------------------------------------------------------------------------

class TestDimensionStd:
    def test_all_equal_returns_zero(self):
        critic = _make_critic()
        score = _make_score()
        assert critic.dimension_std(score) == pytest.approx(0.0)

    def test_all_zero_returns_zero(self):
        critic = _make_critic()
        score = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert critic.dimension_std(score) == pytest.approx(0.0)

    def test_non_negative(self):
        critic = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.9)
        assert critic.dimension_std(score) >= 0.0

    def test_higher_spread_higher_std(self):
        critic = _make_critic()
        low_spread = _make_score(completeness=0.5, consistency=0.5, clarity=0.5,
                                 granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        high_spread = _make_score(completeness=0.0, consistency=1.0, clarity=0.0,
                                  granularity=1.0, relationship_coherence=0.0, domain_alignment=1.0)
        assert critic.dimension_std(high_spread) > critic.dimension_std(low_spread)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_improvement_mask
# ---------------------------------------------------------------------------

class TestDimensionImprovementMask:
    def test_all_improved(self):
        critic = _make_critic()
        before = _make_score()
        after = _make_score(completeness=0.9, consistency=0.9, clarity=0.9,
                            granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9)
        mask = critic.dimension_improvement_mask(before, after)
        assert all(mask.values())

    def test_none_improved(self):
        critic = _make_critic()
        before = _make_score(completeness=0.9, consistency=0.9, clarity=0.9,
                             granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9)
        after = _make_score()
        mask = critic.dimension_improvement_mask(before, after)
        assert not any(mask.values())

    def test_keys_are_dimensions(self):
        critic = _make_critic()
        mask = critic.dimension_improvement_mask(_make_score(), _make_score())
        assert set(mask.keys()) == set(critic._DIMENSIONS)


# ---------------------------------------------------------------------------
# OntologyCritic.passing_dimensions
# ---------------------------------------------------------------------------

class TestPassingDimensions:
    def test_none_passing(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        result = critic.passing_dimensions(score, threshold=0.5)
        assert result == []

    def test_all_passing(self):
        critic = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.9, clarity=0.9,
                            granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9)
        result = critic.passing_dimensions(score, threshold=0.5)
        assert len(result) == 6

    def test_partial(self):
        critic = _make_critic()
        score = _make_score(completeness=0.8)
        result = critic.passing_dimensions(score, threshold=0.5)
        assert "completeness" in result
        assert len(result) == 1


# ---------------------------------------------------------------------------
# OntologyGenerator.max/min_confidence_entity
# ---------------------------------------------------------------------------

class TestMaxMinConfidenceEntity:
    def test_empty_returns_none(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.max_confidence_entity(result) is None
        assert gen.min_confidence_entity(result) is None

    def test_single_entity(self):
        gen = _make_generator()
        e = _make_entity("e1", 0.7)
        result = _make_result([e])
        assert gen.max_confidence_entity(result).id == "e1"
        assert gen.min_confidence_entity(result).id == "e1"

    def test_max_and_min(self):
        gen = _make_generator()
        entities = [_make_entity("low", 0.1), _make_entity("mid", 0.5), _make_entity("high", 0.9)]
        result = _make_result(entities)
        assert gen.max_confidence_entity(result).id == "high"
        assert gen.min_confidence_entity(result).id == "low"


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_std
# ---------------------------------------------------------------------------

class TestEntityConfidenceStd:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_std(_make_result([])) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_confidence_std(_make_result([_make_entity("e1")])) == pytest.approx(0.0)

    def test_known_std(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.0), _make_entity("e2", 1.0)]
        result = _make_result(entities)
        # pop std of [0, 1] = 0.5
        assert gen.entity_confidence_std(result) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# OntologyPipeline.best_k_scores / worst_k_scores
# ---------------------------------------------------------------------------

class TestBestWorstKScores:
    def test_empty(self):
        p = _make_pipeline()
        assert p.best_k_scores(3) == []
        assert p.worst_k_scores(3) == []

    def test_best_sorted_desc(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.5, 0.1]:
            _push_run(p, v)
        best = p.best_k_scores(2)
        assert best == pytest.approx([0.9, 0.5])

    def test_worst_sorted_asc(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.5, 0.1]:
            _push_run(p, v)
        worst = p.worst_k_scores(2)
        assert worst == pytest.approx([0.1, 0.3])

    def test_fewer_than_k(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert len(p.best_k_scores(5)) == 1
        assert len(p.worst_k_scores(5)) == 1
