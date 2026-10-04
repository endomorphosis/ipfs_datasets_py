"""Batch 92: history_summary, has_run, is_empty, latest_batch_size, sorted_entities."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=text, type="PERSON", confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


class _FakeEntry:
    def __init__(self, score: float, trend: str = "stable", batch_size: int = 0):
        self.average_score = score
        self.trend = trend
        self.metadata = {"batch_size": batch_size}


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_summary
# ---------------------------------------------------------------------------


class TestHistorySummary:
    def test_empty_history(self):
        opt = OntologyOptimizer()
        d = opt.history_summary()
        assert d["count"] == 0
        assert d["min"] == pytest.approx(0.0)
        assert d["max"] == pytest.approx(0.0)
        assert d["mean"] == pytest.approx(0.0)
        assert d["trend"] == "n/a"

    def test_with_entries(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.4, "stable"), _FakeEntry(0.8, "improving")])
        d = opt.history_summary()
        assert d["count"] == 2
        assert d["min"] == pytest.approx(0.4)
        assert d["max"] == pytest.approx(0.8)
        assert d["mean"] == pytest.approx(0.6)
        assert d["trend"] == "improving"

    def test_returns_dict(self):
        assert isinstance(OntologyOptimizer().history_summary(), dict)


# ---------------------------------------------------------------------------
# OntologyOptimizer.latest_batch_size
# ---------------------------------------------------------------------------


class TestLatestBatchSize:
    def test_empty_returns_zero(self):
        assert OntologyOptimizer().latest_batch_size() == 0

    def test_returns_batch_size(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.5, batch_size=7))
        assert opt.latest_batch_size() == 7

    def test_last_entry_wins(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.5, batch_size=3), _FakeEntry(0.7, batch_size=10)])
        assert opt.latest_batch_size() == 10

    def test_returns_int(self):
        assert isinstance(OntologyOptimizer().latest_batch_size(), int)


# ---------------------------------------------------------------------------
# OntologyPipeline.has_run
# ---------------------------------------------------------------------------


class TestHasRun:
    def test_false_before_run(self):
        p = OntologyPipeline()
        assert p.has_run() is False

    def test_true_after_run(self):
        p = OntologyPipeline()
        p.run("Alice.")
        assert p.has_run() is True

    def test_false_after_reset(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.reset()
        assert p.has_run() is False

    def test_returns_bool(self):
        assert isinstance(OntologyPipeline().has_run(), bool)


# ---------------------------------------------------------------------------
# LogicValidator.is_empty
# ---------------------------------------------------------------------------


class TestIsEmpty:
    def setup_method(self):
        self.v = LogicValidator()

    def test_empty_dict(self):
        assert self.v.is_empty({}) is True

    def test_empty_lists(self):
        assert self.v.is_empty({"entities": [], "relationships": []}) is True

    def test_non_empty_entities(self):
        assert self.v.is_empty({"entities": [{"id": "e1"}]}) is False

    def test_non_empty_relationships(self):
        assert self.v.is_empty({"entities": [], "relationships": [{"id": "r1"}]}) is False

    def test_returns_bool(self):
        assert isinstance(self.v.is_empty({}), bool)


# ---------------------------------------------------------------------------
# OntologyGenerator.sorted_entities
# ---------------------------------------------------------------------------


class TestSortedEntities:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty(self):
        assert self.gen.sorted_entities(_make_result()) == []

    def test_sorted_by_confidence_descending(self):
        e1 = _make_entity("1", "A", conf=0.3)
        e2 = _make_entity("2", "B", conf=0.9)
        e3 = _make_entity("3", "C", conf=0.6)
        result = _make_result(e1, e2, e3)
        sorted_ents = self.gen.sorted_entities(result, key="confidence")
        confs = [e.confidence for e in sorted_ents]
        assert confs == sorted(confs, reverse=True)

    def test_sorted_ascending(self):
        e1 = _make_entity("1", "A", conf=0.9)
        e2 = _make_entity("2", "B", conf=0.1)
        result = _make_result(e1, e2)
        sorted_ents = self.gen.sorted_entities(result, key="confidence", reverse=False)
        assert sorted_ents[0].confidence < sorted_ents[1].confidence

    def test_sorted_by_text(self):
        e1 = _make_entity("1", "Charlie")
        e2 = _make_entity("2", "Alice")
        e3 = _make_entity("3", "Bob")
        result = _make_result(e1, e2, e3)
        sorted_ents = self.gen.sorted_entities(result, key="text", reverse=False)
        assert [e.text for e in sorted_ents] == ["Alice", "Bob", "Charlie"]

    def test_returns_list(self):
        assert isinstance(self.gen.sorted_entities(_make_result()), list)

    def test_original_unchanged(self):
        e1 = _make_entity("1", "A", conf=0.3)
        e2 = _make_entity("2", "B", conf=0.9)
        result = _make_result(e1, e2)
        self.gen.sorted_entities(result)
        assert result.entities[0].confidence == pytest.approx(0.3)
