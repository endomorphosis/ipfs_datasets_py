"""Batch 87: stash, format_report, relationships_for, evaluate_list, score_variance."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerationContext,
    ExtractionConfig,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator, ValidationResult
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, etype: str = "PERSON") -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=0.8)


def _make_relationship(rid: str, src: str, tgt: str) -> Relationship:
    return Relationship(id=rid, source_id=src, target_id=tgt, type="RELATED")


def _make_result(*entities: Entity, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities),
        relationships=rels or [],
        confidence=0.8,
        metadata={},
    )


def _make_mediator():
    gen = __import__(
        "ipfs_datasets_py.optimizers.graphrag.ontology_generator",
        fromlist=["OntologyGenerator"],
    ).OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_ctx():
    return OntologyGenerationContext(
        data_source="test",
        data_type="text",
        domain="general",
    )


# ---------------------------------------------------------------------------
# OntologyMediator.stash
# ---------------------------------------------------------------------------


class TestStash:
    def test_returns_depth(self):
        med = _make_mediator()
        depth = med.stash({"entities": [], "relationships": []})
        assert depth == 1

    def test_increments_stack(self):
        med = _make_mediator()
        med.stash({})
        med.stash({})
        assert med.get_undo_depth() == 2

    def test_stash_is_deep_copy(self):
        med = _make_mediator()
        ont = {"entities": ["a"]}
        med.stash(ont)
        ont["entities"].append("b")
        peeked = med.peek_undo()
        assert "b" not in peeked["entities"]

    def test_undo_after_stash(self):
        med = _make_mediator()
        ont = {"entities": ["x"]}
        med.stash(ont)
        restored = med.undo_last_action()
        assert restored["entities"] == ["x"]

    def test_returns_int(self):
        med = _make_mediator()
        assert isinstance(med.stash({}), int)


# ---------------------------------------------------------------------------
# LogicValidator.format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_returns_string(self):
        vr = ValidationResult(is_consistent=True)
        assert isinstance(self.validator.format_report(vr), str)

    def test_consistent_label(self):
        vr = ValidationResult(is_consistent=True)
        assert "CONSISTENT" in self.validator.format_report(vr)

    def test_inconsistent_label(self):
        vr = ValidationResult(is_consistent=False, contradictions=["A vs B"])
        report = self.validator.format_report(vr)
        assert "INCONSISTENT" in report

    def test_contradictions_listed(self):
        vr = ValidationResult(is_consistent=False, contradictions=["Conflict1", "Conflict2"])
        report = self.validator.format_report(vr)
        assert "Conflict1" in report and "Conflict2" in report

    def test_confidence_present(self):
        vr = ValidationResult(is_consistent=True, confidence=0.95)
        assert "0.95" in self.validator.format_report(vr)


# ---------------------------------------------------------------------------
# EntityExtractionResult.relationships_for
# ---------------------------------------------------------------------------


class TestRelationshipsFor:
    def test_returns_all_involving_entity(self):
        e1 = _make_entity("e1", "Alice")
        e2 = _make_entity("e2", "Bob")
        r1 = _make_relationship("r1", "e1", "e2")
        r2 = _make_relationship("r2", "e2", "e1")
        r3 = _make_relationship("r3", "e2", "e2")
        result = _make_result(e1, e2, rels=[r1, r2, r3])
        rels = result.relationships_for("e1")
        assert len(rels) == 2
        ids = {r.id for r in rels}
        assert "r1" in ids and "r2" in ids

    def test_empty_when_no_rels(self):
        e = _make_entity("x", "X")
        result = _make_result(e)
        assert result.relationships_for("x") == []

    def test_unknown_entity_returns_empty(self):
        result = _make_result()
        assert result.relationships_for("ghost") == []

    def test_returns_list(self):
        result = _make_result()
        assert isinstance(result.relationships_for("any"), list)


# ---------------------------------------------------------------------------
# OntologyCritic.evaluate_list
# ---------------------------------------------------------------------------


class TestEvaluateList:
    def setup_method(self):
        self.critic = OntologyCritic()
        self.ctx = _make_ctx()

    def test_empty_input(self):
        assert self.critic.evaluate_list([], self.ctx) == []

    def test_length_matches(self):
        onts = [{"entities": [], "relationships": []} for _ in range(3)]
        scores = self.critic.evaluate_list(onts, self.ctx)
        assert len(scores) == 3

    def test_returns_critic_scores(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        onts = [{"entities": [], "relationships": []}]
        scores = self.critic.evaluate_list(onts, self.ctx)
        assert all(isinstance(s, CriticScore) for s in scores)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.score_variance
# ---------------------------------------------------------------------------


class TestScoreVariance:
    def test_empty_returns_zero(self):
        adapter = OntologyLearningAdapter()
        assert adapter.score_variance() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.7))
        assert adapter.score_variance() == pytest.approx(0.0)

    def test_identical_scores_zero_variance(self):
        adapter = OntologyLearningAdapter()
        for _ in range(5):
            adapter._feedback.append(FeedbackRecord(final_score=0.5))
        assert adapter.score_variance() == pytest.approx(0.0)

    def test_nonzero_variance(self):
        adapter = OntologyLearningAdapter()
        for s in [0.0, 1.0]:
            adapter._feedback.append(FeedbackRecord(final_score=s))
        assert adapter.score_variance() > 0.0

    def test_returns_float(self):
        adapter = OntologyLearningAdapter()
        assert isinstance(adapter.score_variance(), float)
