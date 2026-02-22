"""Batch-131 feature tests.

Methods under test:
  - ExtractionConfig.describe()
  - OntologyGenerator.filter_low_confidence(result, threshold)
  - OntologyCritic.passing_rate(scores, threshold)
  - OntologyCritic.score_spread(scores)
  - OntologyMediator.most_used_action()
  - OntologyMediator.least_used_action()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(threshold=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
    return ExtractionConfig(confidence_threshold=threshold)


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_entity(eid, confidence=0.8):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="person", text=eid, properties={}, confidence=confidence)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(entities=entities, relationships=[], confidence=0.8)


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _score(overall):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(
        completeness=overall, consistency=overall, clarity=overall,
        granularity=overall, relationship_coherence=overall, domain_alignment=overall,
    )


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    critic = MagicMock()
    return OntologyMediator(generator=gen, critic=critic)


# ---------------------------------------------------------------------------
# ExtractionConfig.describe
# ---------------------------------------------------------------------------

class TestDescribe:
    def test_returns_string(self):
        cfg = _make_cfg()
        assert isinstance(cfg.describe(), str)

    def test_contains_class_name(self):
        cfg = _make_cfg()
        assert "ExtractionConfig" in cfg.describe()

    def test_contains_threshold(self):
        cfg = _make_cfg(threshold=0.75)
        assert "0.75" in cfg.describe()


# ---------------------------------------------------------------------------
# OntologyGenerator.filter_low_confidence
# ---------------------------------------------------------------------------

class TestFilterLowConfidence:
    def test_empty(self):
        g = _make_generator()
        result = _make_result([])
        filtered = g.filter_low_confidence(result)
        assert filtered.entities == []

    def test_all_above_threshold_kept(self):
        g = _make_generator()
        result = _make_result([_make_entity("a", 0.8), _make_entity("b", 0.9)])
        filtered = g.filter_low_confidence(result, threshold=0.5)
        assert len(filtered.entities) == 2

    def test_filters_low_confidence(self):
        g = _make_generator()
        result = _make_result([
            _make_entity("a", 0.3),
            _make_entity("b", 0.7),
        ])
        filtered = g.filter_low_confidence(result, threshold=0.5)
        assert len(filtered.entities) == 1
        assert filtered.entities[0].id == "b"

    def test_exactly_at_threshold_kept(self):
        g = _make_generator()
        result = _make_result([_make_entity("a", 0.5)])
        filtered = g.filter_low_confidence(result, threshold=0.5)
        assert len(filtered.entities) == 1


# ---------------------------------------------------------------------------
# OntologyCritic.passing_rate
# ---------------------------------------------------------------------------

class TestPassingRate:
    def test_empty(self):
        c = _make_critic()
        assert c.passing_rate([]) == 0.0

    def test_all_passing(self):
        c = _make_critic()
        scores = [_score(0.8), _score(0.9)]
        assert c.passing_rate(scores, 0.6) == pytest.approx(1.0)

    def test_none_passing(self):
        c = _make_critic()
        scores = [_score(0.2), _score(0.4)]
        assert c.passing_rate(scores, 0.6) == pytest.approx(0.0)

    def test_partial(self):
        c = _make_critic()
        scores = [_score(0.3), _score(0.7), _score(0.9)]
        assert c.passing_rate(scores, 0.6) == pytest.approx(2.0 / 3.0)


# ---------------------------------------------------------------------------
# OntologyCritic.score_spread
# ---------------------------------------------------------------------------

class TestScoreSpread:
    def test_empty(self):
        c = _make_critic()
        assert c.score_spread([]) == 0.0

    def test_single(self):
        c = _make_critic()
        assert c.score_spread([_score(0.5)]) == 0.0

    def test_spread(self):
        c = _make_critic()
        scores = [_score(0.2), _score(0.8)]
        assert c.score_spread(scores) == pytest.approx(0.6)

    def test_equal_scores(self):
        c = _make_critic()
        scores = [_score(0.5), _score(0.5)]
        assert c.score_spread(scores) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyMediator.most_used_action / least_used_action
# ---------------------------------------------------------------------------

class TestMostLeastUsedAction:
    def test_most_empty_returns_none(self):
        m = _make_mediator()
        assert m.most_used_action() is None

    def test_least_empty_returns_none(self):
        m = _make_mediator()
        assert m.least_used_action() is None

    def test_most_used(self):
        m = _make_mediator()
        m.apply_action_bulk(["a", "a", "b"])
        assert m.most_used_action() == "a"

    def test_least_used(self):
        m = _make_mediator()
        m.apply_action_bulk(["a", "a", "b"])
        assert m.least_used_action() == "b"

    def test_single_action(self):
        m = _make_mediator()
        m.apply_action_bulk(["x"])
        assert m.most_used_action() == "x"
        assert m.least_used_action() == "x"
