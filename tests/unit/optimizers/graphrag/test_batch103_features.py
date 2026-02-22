"""Batch 103: convergence_rate, history_as_list, confidence_band, relationships_for_entity."""

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
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=f"E{eid}", type="PERSON", confidence=conf)


def _make_rel(source: str, target: str) -> Relationship:
    return Relationship(id=f"{source}-{target}", source_id=source, target_id=target,
                        type="RELATED", confidence=0.8)


def _make_result(entities=None, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities or []),
        relationships=list(rels or []),
        confidence=0.8,
        metadata={},
    )


class _FakeEntry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {}
        self.worst_ontology = {}


# ---------------------------------------------------------------------------
# OntologyOptimizer.convergence_rate
# ---------------------------------------------------------------------------


class TestConvergenceRate:
    def test_empty(self):
        assert OntologyOptimizer().convergence_rate() == pytest.approx(0.0)

    def test_single(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.5))
        assert opt.convergence_rate() == pytest.approx(0.0)

    def test_all_converged(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.5), _FakeEntry(0.5), _FakeEntry(0.5)])
        assert opt.convergence_rate() == pytest.approx(1.0)

    def test_none_converged(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.0), _FakeEntry(0.5), _FakeEntry(1.0)])
        assert opt.convergence_rate() == pytest.approx(0.0)

    def test_returns_float(self):
        assert isinstance(OntologyOptimizer().convergence_rate(), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_as_list
# ---------------------------------------------------------------------------


class TestHistoryAsList:
    def test_empty(self):
        assert OntologyOptimizer().history_as_list() == []

    def test_values(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.3), _FakeEntry(0.7)])
        assert opt.history_as_list() == pytest.approx([0.3, 0.7])

    def test_returns_list(self):
        assert isinstance(OntologyOptimizer().history_as_list(), list)

    def test_insertion_order(self):
        opt = OntologyOptimizer()
        scores = [0.2, 0.5, 0.8]
        opt._history.extend([_FakeEntry(s) for s in scores])
        assert opt.history_as_list() == pytest.approx(scores)


# ---------------------------------------------------------------------------
# EntityExtractionResult.confidence_band
# ---------------------------------------------------------------------------


class TestConfidenceBand:
    def test_empty(self):
        assert _make_result().confidence_band() == []

    def test_all_in_default_band(self):
        r = _make_result([_make_entity("1", 0.5)])
        assert len(r.confidence_band()) == 1

    def test_filters_correctly(self):
        r = _make_result([_make_entity("1", 0.3), _make_entity("2", 0.7)])
        result = r.confidence_band(0.5, 0.9)
        assert len(result) == 1
        assert result[0].id == "2"

    def test_inclusive_bounds(self):
        r = _make_result([_make_entity("1", 0.5), _make_entity("2", 0.8)])
        result = r.confidence_band(0.5, 0.8)
        assert len(result) == 2

    def test_returns_list(self):
        assert isinstance(_make_result().confidence_band(), list)


# ---------------------------------------------------------------------------
# OntologyGenerator.relationships_for_entity
# ---------------------------------------------------------------------------


class TestRelationshipsForEntity:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_no_rels(self):
        r = _make_result([_make_entity("e1")])
        assert self.gen.relationships_for_entity(r, "e1") == []

    def test_source_match(self):
        ents = [_make_entity("e1"), _make_entity("e2")]
        rels = [_make_rel("e1", "e2")]
        r = _make_result(ents, rels)
        assert len(self.gen.relationships_for_entity(r, "e1")) == 1

    def test_target_match(self):
        ents = [_make_entity("e1"), _make_entity("e2")]
        rels = [_make_rel("e1", "e2")]
        r = _make_result(ents, rels)
        assert len(self.gen.relationships_for_entity(r, "e2")) == 1

    def test_no_match(self):
        r = _make_result([_make_entity("e1")], [_make_rel("e1", "e1")])
        assert self.gen.relationships_for_entity(r, "xyz") == []

    def test_returns_list(self):
        assert isinstance(self.gen.relationships_for_entity(_make_result(), "e1"), list)
