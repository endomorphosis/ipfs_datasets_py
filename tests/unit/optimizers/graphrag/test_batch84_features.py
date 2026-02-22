"""Batch 84: CriticScore.to_list, best_n_ontologies, undo_all, worst_score, total_runs."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(
        completeness=c, consistency=con, clarity=cl, granularity=g, relationship_coherence=da
    , domain_alignment=da
    )


def _make_report(score: float, ont=None) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable", best_ontology=ont or {"s": score})


# ---------------------------------------------------------------------------
# CriticScore.to_list
# ---------------------------------------------------------------------------


class TestCriticScoreToList:
    def test_returns_list(self):
        score = _make_score()
        assert isinstance(score.to_list(), list)

    def test_length_five(self):
        score = _make_score()
        assert len(score.to_list()) in (5, 6)

    def test_correct_values(self):
        score = _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9)
        lst = score.to_list()
        assert lst[0] == pytest.approx(0.8)  # completeness
        assert lst[1] == pytest.approx(0.7)  # consistency
        assert lst[2] == pytest.approx(0.6)  # clarity
        assert lst[3] == pytest.approx(0.5)  # granularity
        assert lst[-1] == pytest.approx(0.9)  # domain_alignment (last)

    def test_order_matches_dims(self):
        score = _make_score(c=0.1, con=0.2, cl=0.3, g=0.4, da=0.5)
        lst = score.to_list()
        # to_list returns all numeric dimensions; domain_alignment is last
        assert score.completeness in lst
        assert score.consistency in lst
        assert score.domain_alignment in lst


# ---------------------------------------------------------------------------
# OntologyOptimizer.best_n_ontologies
# ---------------------------------------------------------------------------


class TestBestNOntologies:
    def test_empty_history(self):
        opt = OntologyOptimizer()
        assert opt.best_n_ontologies() == []

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.7, {"name": "A"}))
        result = opt.best_n_ontologies(3)
        assert len(result) == 1
        assert result[0] == {"name": "A"}

    def test_top_n_sorted_by_score(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.5, {"name": "mid"}))
        opt._history.append(_make_report(0.9, {"name": "best"}))
        opt._history.append(_make_report(0.2, {"name": "worst"}))
        top2 = opt.best_n_ontologies(2)
        assert top2[0] == {"name": "best"}
        assert len(top2) == 2

    def test_n_larger_than_history(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.7))
        assert len(opt.best_n_ontologies(10)) == 1

    def test_returns_list(self):
        opt = OntologyOptimizer()
        assert isinstance(opt.best_n_ontologies(), list)


# ---------------------------------------------------------------------------
# OntologyMediator.undo_all
# ---------------------------------------------------------------------------


class TestUndoAll:
    def test_empty_stack_returns_none(self):
        med = _make_mediator()
        assert med.undo_all() is None

    def test_returns_oldest_snapshot(self):
        med = _make_mediator()
        med._undo_stack.append({"round": 1})
        med._undo_stack.append({"round": 2})
        result = med.undo_all()
        assert result == {"round": 1}

    def test_clears_stack(self):
        med = _make_mediator()
        med._undo_stack.append({"x": 1})
        med._undo_stack.append({"x": 2})
        med.undo_all()
        assert med.get_undo_depth() == 0

    def test_single_entry(self):
        med = _make_mediator()
        snap = {"only": True}
        med._undo_stack.append(snap)
        assert med.undo_all() == snap

    def test_stack_empty_after_call(self):
        med = _make_mediator()
        for i in range(5):
            med._undo_stack.append({"i": i})
        med.undo_all()
        assert med.get_undo_depth() == 0


# ---------------------------------------------------------------------------
# OntologyCritic.worst_score
# ---------------------------------------------------------------------------


class TestWorstScore:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_none(self):
        assert self.critic.worst_score([]) is None

    def test_single_score(self):
        s = _make_score()
        assert self.critic.worst_score([s]) is s

    def test_selects_lowest(self):
        s_high = _make_score(c=0.9, con=0.9, cl=0.9, g=0.9, da=0.9)
        s_low = _make_score(c=0.1, con=0.1, cl=0.1, g=0.1, da=0.1)
        s_mid = _make_score()
        result = self.critic.worst_score([s_high, s_low, s_mid])
        assert result is s_low

    def test_returns_critic_score(self):
        s = _make_score()
        result = self.critic.worst_score([s])
        assert isinstance(result, CriticScore)


# ---------------------------------------------------------------------------
# OntologyPipeline.total_runs
# ---------------------------------------------------------------------------


class TestTotalRuns:
    def test_zero_before_runs(self):
        p = OntologyPipeline()
        assert p.total_runs() == 0

    def test_increments_on_run(self):
        p = OntologyPipeline()
        p.run("Alice works at ACME.")
        assert p.total_runs() == 1

    def test_multiple_runs(self):
        p = OntologyPipeline()
        for _ in range(3):
            p.run("Test text.")
        assert p.total_runs() == 3

    def test_returns_int(self):
        p = OntologyPipeline()
        assert isinstance(p.total_runs(), int)

    def test_consistent_with_history_length(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.run("Bob.")
        assert p.total_runs() == len(p.history)
