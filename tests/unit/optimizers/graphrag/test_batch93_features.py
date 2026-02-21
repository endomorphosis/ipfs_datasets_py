"""Batch 93: score_range, log_snapshot, confidence_histogram, warmup, contradiction_count."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=f"E{eid}", type="PERSON", confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(completeness=c, consistency=con, clarity=cl, granularity=g, domain_alignment=da)


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


# ---------------------------------------------------------------------------
# OntologyCritic.score_range
# ---------------------------------------------------------------------------


class TestScoreRange:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_zeros(self):
        assert self.critic.score_range([]) == (pytest.approx(0.0), pytest.approx(0.0))

    def test_single_score(self):
        s = _make_score()
        lo, hi = self.critic.score_range([s])
        assert lo == pytest.approx(hi)
        assert lo == pytest.approx(s.overall)

    def test_multiple_scores(self):
        high = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        low = _make_score(c=0.0, con=0.0, cl=0.0, g=0.0, da=0.0)
        lo, hi = self.critic.score_range([high, low])
        assert lo < hi

    def test_returns_tuple(self):
        assert isinstance(self.critic.score_range([]), tuple)


# ---------------------------------------------------------------------------
# OntologyMediator.log_snapshot
# ---------------------------------------------------------------------------


class TestLogSnapshot:
    def test_increases_stack(self):
        med = _make_mediator()
        med.log_snapshot("before", {"entities": []})
        assert med.snapshot_count() == 1

    def test_label_in_action_entries(self):
        med = _make_mediator()
        med.log_snapshot("my_label", {})
        entries = med.action_log()
        assert any("my_label" in str(e.get("action", "")) for e in entries)

    def test_deep_copy(self):
        med = _make_mediator()
        ont = {"entities": ["a"]}
        med.log_snapshot("snap", ont)
        ont["entities"].append("b")
        peeked = med.peek_undo()
        assert "b" not in peeked["entities"]

    def test_undo_restores_snapshot(self):
        med = _make_mediator()
        ont = {"entities": ["x"]}
        med.log_snapshot("s", ont)
        restored = med.undo_last_action()
        assert restored["entities"] == ["x"]


# ---------------------------------------------------------------------------
# EntityExtractionResult.confidence_histogram
# ---------------------------------------------------------------------------


class TestConfidenceHistogram:
    def test_empty_result(self):
        hist = _make_result().confidence_histogram()
        assert sum(hist.values()) == 0

    def test_buckets_sum_to_entity_count(self):
        entities = [_make_entity(str(i), conf=i * 0.1) for i in range(1, 6)]
        result = _make_result(*entities)
        hist = result.confidence_histogram(bins=5)
        assert sum(hist.values()) == len(entities)

    def test_default_bins(self):
        hist = _make_result().confidence_histogram()
        assert len(hist) == 5

    def test_custom_bins(self):
        hist = _make_result().confidence_histogram(bins=10)
        assert len(hist) == 10

    def test_returns_dict(self):
        assert isinstance(_make_result().confidence_histogram(), dict)


# ---------------------------------------------------------------------------
# OntologyPipeline.warmup
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_history_unchanged(self):
        p = OntologyPipeline()
        p.warmup(3)
        assert p.total_runs() == 0

    def test_warmup_after_run(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.warmup(2)
        assert p.total_runs() == 1

    def test_returns_none(self):
        p = OntologyPipeline()
        assert p.warmup() is None


# ---------------------------------------------------------------------------
# LogicValidator.contradiction_count
# ---------------------------------------------------------------------------


class TestContradictionCount:
    def setup_method(self):
        self.v = LogicValidator()

    def test_empty_returns_zero(self):
        assert self.v.contradiction_count({"entities": [], "relationships": []}) == 0

    def test_agrees_with_count_contradictions(self):
        ont = {"entities": [], "relationships": []}
        assert self.v.contradiction_count(ont) == self.v.count_contradictions(ont)

    def test_returns_int(self):
        assert isinstance(self.v.contradiction_count({}), int)
