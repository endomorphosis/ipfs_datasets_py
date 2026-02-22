"""Batch-164 feature tests.

Methods under test:
  - OntologyCritic.dimension_mean(score)
  - OntologyCritic.dimension_count_above(score, threshold)
  - OntologyGenerator.entity_text_lengths(result)
  - OntologyPipeline.run_score_variance()
  - OntologyOptimizer.score_moving_sum(n)
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


def _make_entity(eid, text):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=text)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities,
        relationships=[],
        confidence=1.0,
        metadata={},
        errors=[],
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
# OntologyCritic.dimension_mean
# ---------------------------------------------------------------------------

class TestDimensionMean:
    def test_all_equal(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        assert critic.dimension_mean(score) == pytest.approx(0.5)

    def test_mixed(self):
        critic = _make_critic()
        score = _make_score(completeness=1.0, consistency=0.0, clarity=0.5,
                            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        mean = critic.dimension_mean(score)
        assert 0.0 < mean < 1.0

    def test_all_zero(self):
        critic = _make_critic()
        score = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert critic.dimension_mean(score) == pytest.approx(0.0)

    def test_all_one(self):
        critic = _make_critic()
        score = _make_score(completeness=1.0, consistency=1.0, clarity=1.0,
                            granularity=1.0, relationship_coherence=1.0, domain_alignment=1.0)
        assert critic.dimension_mean(score) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_count_above
# ---------------------------------------------------------------------------

class TestDimensionCountAbove:
    def test_none_above(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        assert critic.dimension_count_above(score, threshold=0.5) == 0

    def test_all_above(self):
        critic = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.8, clarity=0.7,
                            granularity=0.6, relationship_coherence=0.75, domain_alignment=0.85)
        assert critic.dimension_count_above(score, threshold=0.5) == 6

    def test_partial(self):
        critic = _make_critic()
        score = _make_score(completeness=0.8, consistency=0.2)  # rest default 0.5
        assert critic.dimension_count_above(score, threshold=0.5) == 1


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_text_lengths
# ---------------------------------------------------------------------------

class TestEntityTextLengths:
    def test_empty_result(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.entity_text_lengths(result) == []

    def test_single_entity(self):
        gen = _make_generator()
        result = _make_result([_make_entity("e1", "hello")])
        assert gen.entity_text_lengths(result) == [5]

    def test_multiple_entities(self):
        gen = _make_generator()
        entities = [_make_entity("e1", "ab"), _make_entity("e2", "xyz")]
        result = _make_result(entities)
        assert gen.entity_text_lengths(result) == [2, 3]


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_variance
# ---------------------------------------------------------------------------

class TestRunScoreVariance:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_variance() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_variance() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.6)
        assert p.run_score_variance() == pytest.approx(0.0)

    def test_known_variance(self):
        p = _make_pipeline()
        _push_run(p, 0.0)
        _push_run(p, 1.0)
        # population variance of [0, 1] = 0.25
        assert p.run_score_variance() == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_moving_sum
# ---------------------------------------------------------------------------

class TestScoreMovingSum:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_moving_sum() == pytest.approx(0.0)

    def test_sum_all_within_window(self):
        o = _make_optimizer()
        for v in [0.3, 0.4, 0.5]:
            _push_opt(o, v)
        assert o.score_moving_sum(5) == pytest.approx(1.2)

    def test_windowed_sum(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.8, 0.9]:
            _push_opt(o, v)
        # last 2: 0.8 + 0.9 = 1.7
        assert o.score_moving_sum(2) == pytest.approx(1.7)
