"""Batch 81: average_score, score_range, strip_low_confidence, top_recommended_action,
unique_types."""

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
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, etype: str = "TEST", conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(
        completeness=c, consistency=con, clarity=cl, granularity=g, domain_alignment=da
    )


def _make_report(score: float) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


# ---------------------------------------------------------------------------
# OntologyOptimizer.average_score
# ---------------------------------------------------------------------------


class TestAverageScore:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.average_score() == pytest.approx(0.0)

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.6))
        assert opt.average_score() == pytest.approx(0.6)

    def test_mean_of_multiple(self):
        opt = OntologyOptimizer()
        for v in [0.4, 0.6, 0.8]:
            opt._history.append(_make_report(v))
        assert opt.average_score() == pytest.approx(0.6, abs=1e-5)

    def test_returns_float(self):
        opt = OntologyOptimizer()
        assert isinstance(opt.average_score(), float)

    def test_consistent_with_score_history(self):
        opt = OntologyOptimizer()
        for v in [0.5, 0.7]:
            opt._history.append(_make_report(v))
        expected = sum(opt.score_history()) / len(opt.score_history())
        assert opt.average_score() == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# OntologyCritic.score_range
# ---------------------------------------------------------------------------


class TestScoreRange:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_zeros(self):
        lo, hi = self.critic.score_range([])
        assert lo == 0.0 and hi == 0.0

    def test_single_score(self):
        s = _make_score()
        lo, hi = self.critic.score_range([s])
        assert lo == pytest.approx(hi, abs=1e-6)

    def test_range_across_multiple(self):
        s1 = _make_score(c=0.1, con=0.1, cl=0.1, g=0.1, da=0.1)
        s2 = _make_score(c=0.9, con=0.9, cl=0.9, g=0.9, da=0.9)
        lo, hi = self.critic.score_range([s1, s2])
        assert lo < hi

    def test_returns_tuple(self):
        result = self.critic.score_range([_make_score()])
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_lo_le_hi(self):
        scores = [_make_score(c=i * 0.1, con=0.5, cl=0.5, g=0.5, da=0.5) for i in range(1, 10)]
        lo, hi = self.critic.score_range(scores)
        assert lo <= hi


# ---------------------------------------------------------------------------
# OntologyGenerator.strip_low_confidence
# ---------------------------------------------------------------------------


class TestStripLowConfidence:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_removes_below_threshold(self):
        e1 = _make_entity("1", "Alice", conf=0.3)
        e2 = _make_entity("2", "Bob", conf=0.8)
        r = _make_result(e1, e2)
        out = self.gen.strip_low_confidence(r, threshold=0.5)
        assert len(out.entities) == 1
        assert out.entities[0].id == "2"

    def test_keeps_at_threshold(self):
        e1 = _make_entity("1", "Alice", conf=0.5)
        r = _make_result(e1)
        out = self.gen.strip_low_confidence(r, threshold=0.5)
        assert len(out.entities) == 1

    def test_empty_result_unchanged(self):
        r = _make_result()
        out = self.gen.strip_low_confidence(r)
        assert out.entities == []

    def test_all_kept_when_all_above(self):
        entities = [_make_entity(str(i), f"E{i}", conf=0.9) for i in range(5)]
        r = _make_result(*entities)
        out = self.gen.strip_low_confidence(r, threshold=0.5)
        assert len(out.entities) == 5

    def test_returns_new_object(self):
        r = _make_result(_make_entity("1", "Alice", conf=0.8))
        out = self.gen.strip_low_confidence(r)
        assert out is not r

    def test_default_threshold_05(self):
        e1 = _make_entity("1", "Alice", conf=0.4)
        r = _make_result(e1)
        assert self.gen.strip_low_confidence(r).entities == []


# ---------------------------------------------------------------------------
# OntologyMediator.top_recommended_action
# ---------------------------------------------------------------------------


class TestTopRecommendedAction:
    def test_empty_returns_none(self):
        med = _make_mediator()
        assert med.top_recommended_action() is None

    def test_single_recommendation(self):
        med = _make_mediator()
        med._recommendation_counts["add_entity"] = 3
        assert med.top_recommended_action() == "add_entity"

    def test_returns_highest_count(self):
        med = _make_mediator()
        med._recommendation_counts["add_entity"] = 1
        med._recommendation_counts["merge_entities"] = 5
        med._recommendation_counts["remove_dup"] = 2
        assert med.top_recommended_action() == "merge_entities"

    def test_returns_string(self):
        med = _make_mediator()
        med._recommendation_counts["x"] = 1
        assert isinstance(med.top_recommended_action(), str)

    def test_cleared_returns_none(self):
        med = _make_mediator()
        med._recommendation_counts["x"] = 1
        med.clear_recommendation_history()
        assert med.top_recommended_action() is None


# ---------------------------------------------------------------------------
# EntityExtractionResult.unique_types
# ---------------------------------------------------------------------------


class TestUniqueTypes:
    def test_empty_result(self):
        r = _make_result()
        assert r.unique_types() == []

    def test_single_type(self):
        e1 = _make_entity("1", "Alice", "Person")
        r = _make_result(e1)
        assert r.unique_types() == ["Person"]

    def test_multiple_unique_types_sorted(self):
        e1 = _make_entity("1", "Alice", "Person")
        e2 = _make_entity("2", "ACME", "Org")
        r = _make_result(e1, e2)
        assert r.unique_types() == ["Org", "Person"]

    def test_deduplicates_types(self):
        e1 = _make_entity("1", "Alice", "Person")
        e2 = _make_entity("2", "Bob", "Person")
        r = _make_result(e1, e2)
        assert r.unique_types() == ["Person"]

    def test_returns_list(self):
        r = _make_result()
        assert isinstance(r.unique_types(), list)

    def test_sorted(self):
        types_in = ["Zebra", "Alpha", "Mike"]
        entities = [_make_entity(str(i), f"E{i}", t) for i, t in enumerate(types_in)]
        r = _make_result(*entities)
        result = r.unique_types()
        assert result == sorted(result)
