"""Batch 85: best_score, has_entity, action_count_for, is_passing, last_score."""

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
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=text, type="TEST", confidence=conf)


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


# ---------------------------------------------------------------------------
# OntologyCritic.best_score
# ---------------------------------------------------------------------------


class TestBestScore:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_none(self):
        assert self.critic.best_score([]) is None

    def test_single_score(self):
        s = _make_score()
        assert self.critic.best_score([s]) is s

    def test_selects_highest(self):
        s_high = _make_score(c=0.9, con=0.9, cl=0.9, g=0.9, da=0.9)
        s_low = _make_score(c=0.1, con=0.1, cl=0.1, g=0.1, da=0.1)
        s_mid = _make_score()
        assert self.critic.best_score([s_low, s_high, s_mid]) is s_high

    def test_opposite_of_worst_score(self):
        s_high = _make_score(c=0.9, con=0.9, cl=0.9, g=0.9, da=0.9)
        s_low = _make_score(c=0.1, con=0.1, cl=0.1, g=0.1, da=0.1)
        scores = [s_low, s_high]
        assert self.critic.best_score(scores) is not self.critic.worst_score(scores)

    def test_returns_critic_score(self):
        s = _make_score()
        assert isinstance(self.critic.best_score([s]), CriticScore)


# ---------------------------------------------------------------------------
# EntityExtractionResult.has_entity
# ---------------------------------------------------------------------------


class TestHasEntity:
    def test_found_exact(self):
        e1 = _make_entity("1", "Alice")
        r = _make_result(e1)
        assert r.has_entity("Alice") is True

    def test_not_found(self):
        r = _make_result()
        assert r.has_entity("Alice") is False

    def test_case_insensitive_default(self):
        e1 = _make_entity("1", "Alice")
        r = _make_result(e1)
        assert r.has_entity("alice") is True

    def test_case_sensitive(self):
        e1 = _make_entity("1", "Alice")
        r = _make_result(e1)
        assert r.has_entity("alice", case_sensitive=True) is False

    def test_case_sensitive_match(self):
        e1 = _make_entity("1", "Alice")
        r = _make_result(e1)
        assert r.has_entity("Alice", case_sensitive=True) is True

    def test_returns_bool(self):
        r = _make_result()
        assert isinstance(r.has_entity("X"), bool)


# ---------------------------------------------------------------------------
# OntologyMediator.action_count_for
# ---------------------------------------------------------------------------


class TestActionCountFor:
    def test_zero_for_missing_action(self):
        med = _make_mediator()
        assert med.action_count_for("add_entity") == 0

    def test_returns_count(self):
        med = _make_mediator()
        med._action_counts["add_entity"] = 5
        assert med.action_count_for("add_entity") == 5

    def test_zero_after_reset(self):
        med = _make_mediator()
        med._action_counts["x"] = 3
        med.reset_all_state()
        assert med.action_count_for("x") == 0

    def test_returns_int(self):
        med = _make_mediator()
        assert isinstance(med.action_count_for("any"), int)

    def test_different_actions_independent(self):
        med = _make_mediator()
        med._action_counts["a"] = 2
        med._action_counts["b"] = 7
        assert med.action_count_for("a") == 2
        assert med.action_count_for("b") == 7


# ---------------------------------------------------------------------------
# CriticScore.is_passing
# ---------------------------------------------------------------------------


class TestIsPassing:
    def test_high_score_passes(self):
        score = _make_score(c=0.9, con=0.9, cl=0.9, g=0.9, da=0.9)
        assert score.is_passing() is True

    def test_low_score_fails(self):
        score = _make_score(c=0.1, con=0.1, cl=0.1, g=0.1, da=0.1)
        assert score.is_passing() is False

    def test_at_threshold_passes(self):
        # Build a score with overall exactly 0.6
        # overall = weighted sum; easier to just check with custom threshold
        score = _make_score()
        assert score.is_passing(threshold=score.overall) is True

    def test_custom_high_threshold(self):
        score = _make_score(c=0.5, con=0.5, cl=0.5, g=0.5, da=0.5)
        assert score.is_passing(threshold=0.99) is False

    def test_returns_bool(self):
        score = _make_score()
        assert isinstance(score.is_passing(), bool)


# ---------------------------------------------------------------------------
# OntologyPipeline.last_score
# ---------------------------------------------------------------------------


class TestPipelineLastScore:
    def test_zero_before_runs(self):
        p = OntologyPipeline()
        assert p.last_score() == pytest.approx(0.0)

    def test_after_run_nonzero_or_zero(self):
        p = OntologyPipeline()
        p.run("Alice at ACME Corp.")
        score = p.last_score()
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_returns_float(self):
        p = OntologyPipeline()
        assert isinstance(p.last_score(), float)

    def test_consistent_with_history_last_score(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.run("Bob.")
        assert p.last_score() == pytest.approx(p.history[-1].score.overall)
