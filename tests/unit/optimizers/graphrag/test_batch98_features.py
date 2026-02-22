"""Batch 98: average_confidence, distinct_types, relationship_density, score_gap, score_stddev."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, conf: float = 0.8, etype: str = "PERSON") -> Entity:
    return Entity(id=eid, text=f"E{eid}", type=etype, confidence=conf)


def _make_rel(source: str, target: str) -> Relationship:
    return Relationship(id=f"{source}-{target}", source_id=source, target_id=target,
                        type="RELATED", confidence=0.8)


def _make_result(entities=None, relationships=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities or []),
        relationships=list(relationships or []),
        confidence=0.8,
        metadata={},
    )


def _make_score(v: float) -> CriticScore:
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, relationship_coherence=v, domain_alignment=v)


class _FakeEntry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {}
        self.worst_ontology = {}


# ---------------------------------------------------------------------------
# EntityExtractionResult.average_confidence
# ---------------------------------------------------------------------------


class TestAverageConfidence:
    def test_empty(self):
        assert _make_result().average_confidence() == pytest.approx(0.0)

    def test_single_entity(self):
        r = _make_result([_make_entity("1", 0.6)])
        assert r.average_confidence() == pytest.approx(0.6)

    def test_mean(self):
        r = _make_result([_make_entity("1", 0.4), _make_entity("2", 0.8)])
        assert r.average_confidence() == pytest.approx(0.6)

    def test_returns_float(self):
        assert isinstance(_make_result().average_confidence(), float)


# ---------------------------------------------------------------------------
# EntityExtractionResult.distinct_types
# ---------------------------------------------------------------------------


class TestDistinctTypes:
    def test_empty(self):
        assert _make_result().distinct_types() == []

    def test_unique(self):
        r = _make_result([_make_entity("1", etype="PERSON"), _make_entity("2", etype="ORG")])
        assert r.distinct_types() == ["ORG", "PERSON"]

    def test_dedup(self):
        r = _make_result([_make_entity("1", etype="A"), _make_entity("2", etype="A")])
        assert r.distinct_types() == ["A"]

    def test_sorted(self):
        r = _make_result([_make_entity("1", etype="Z"), _make_entity("2", etype="A")])
        types = r.distinct_types()
        assert types == sorted(types)

    def test_returns_list(self):
        assert isinstance(_make_result().distinct_types(), list)


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_density
# ---------------------------------------------------------------------------


class TestRelationshipDensity:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_no_entities(self):
        assert self.gen.relationship_density(_make_result()) == pytest.approx(0.0)

    def test_no_relationships(self):
        r = _make_result([_make_entity("1"), _make_entity("2")])
        assert self.gen.relationship_density(r) == pytest.approx(0.0)

    def test_density_calculation(self):
        entities = [_make_entity("1"), _make_entity("2")]
        rels = [_make_rel("1", "2")]
        r = _make_result(entities, rels)
        assert self.gen.relationship_density(r) == pytest.approx(0.5)

    def test_returns_float(self):
        assert isinstance(self.gen.relationship_density(_make_result()), float)


# ---------------------------------------------------------------------------
# OntologyCritic.score_gap
# ---------------------------------------------------------------------------


class TestScoreGap:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty(self):
        assert self.critic.score_gap([]) == pytest.approx(0.0)

    def test_single(self):
        assert self.critic.score_gap([_make_score(0.7)]) == pytest.approx(0.0)

    def test_gap(self):
        scores = [_make_score(0.3), _make_score(0.7)]
        assert self.critic.score_gap(scores) == pytest.approx(0.4, abs=0.01)

    def test_returns_float(self):
        assert isinstance(self.critic.score_gap([]), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_stddev
# ---------------------------------------------------------------------------


class TestScoreStddev:
    def test_empty(self):
        assert OntologyOptimizer().score_stddev() == pytest.approx(0.0)

    def test_identical_scores(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.5), _FakeEntry(0.5)])
        assert opt.score_stddev() == pytest.approx(0.0)

    def test_non_zero(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.0), _FakeEntry(1.0)])
        assert opt.score_stddev() == pytest.approx(0.5)

    def test_returns_float(self):
        assert isinstance(OntologyOptimizer().score_stddev(), float)
