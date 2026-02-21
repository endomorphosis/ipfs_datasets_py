"""Batch 89: load_feedback_from_list, score_std, merge, snapshot_count, quick_check."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import math
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, etype: str = "PERSON") -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=0.8)


def _make_rel(rid: str, src: str, tgt: str) -> Relationship:
    return Relationship(id=rid, source_id=src, target_id=tgt, type="X")


def _make_result(entities=None, rels=None, conf=0.8) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=entities or [], relationships=rels or [], confidence=conf, metadata={}
    )


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(completeness=c, consistency=con, clarity=cl, granularity=g, relationship_coherence=da, domain_alignment=da)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.load_feedback_from_list
# ---------------------------------------------------------------------------


class TestLoadFeedbackFromList:
    def test_empty_list(self):
        adapter = OntologyLearningAdapter()
        assert adapter.load_feedback_from_list([]) == 0

    def test_adds_records(self):
        adapter = OntologyLearningAdapter()
        records = [FeedbackRecord(final_score=0.5), FeedbackRecord(final_score=0.7)]
        n = adapter.load_feedback_from_list(records)
        assert n == 2

    def test_appends_to_existing(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.5))
        adapter.load_feedback_from_list([FeedbackRecord(final_score=0.8)])
        assert len(adapter._feedback) == 2

    def test_returns_total_count(self):
        adapter = OntologyLearningAdapter()
        n = adapter.load_feedback_from_list(
            [FeedbackRecord(final_score=s) for s in [0.1, 0.2, 0.3]]
        )
        assert n == 3

    def test_returns_int(self):
        adapter = OntologyLearningAdapter()
        assert isinstance(adapter.load_feedback_from_list([]), int)


# ---------------------------------------------------------------------------
# OntologyCritic.score_std
# ---------------------------------------------------------------------------


class TestScoreStd:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_zero(self):
        assert self.critic.score_std([]) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        assert self.critic.score_std([_make_score()]) == pytest.approx(0.0)

    def test_identical_scores_zero_std(self):
        scores = [_make_score(c=0.5, con=0.5, cl=0.5, g=0.5, da=0.5)] * 4
        assert self.critic.score_std(scores) == pytest.approx(0.0, abs=1e-9)

    def test_nonzero_std(self):
        high = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        low = _make_score(c=0.0, con=0.0, cl=0.0, g=0.0, da=0.0)
        assert self.critic.score_std([high, low]) > 0.0

    def test_returns_float(self):
        assert isinstance(self.critic.score_std([_make_score()]), float)


# ---------------------------------------------------------------------------
# EntityExtractionResult.merge
# ---------------------------------------------------------------------------


class TestMerge:
    def test_empty_merge(self):
        r = _make_result()
        merged = r.merge(_make_result())
        assert merged.entities == []

    def test_combines_entities(self):
        r1 = _make_result(entities=[_make_entity("1", "A")])
        r2 = _make_result(entities=[_make_entity("2", "B")])
        merged = r1.merge(r2)
        assert len(merged.entities) == 2

    def test_deduplicates_by_id(self):
        e = _make_entity("1", "A")
        r1 = _make_result(entities=[e])
        r2 = _make_result(entities=[_make_entity("2", "a")])  # same text lowercased
        merged = r1.merge(r2)
        assert len(merged.entities) == 1

    def test_self_takes_priority(self):
        e1 = Entity(id="1", text="Alice", type="PERSON", confidence=0.9)
        e2 = Entity(id="2", text="alice", type="ORG", confidence=0.5)  # same text
        r1 = _make_result(entities=[e1])
        r2 = _make_result(entities=[e2])
        merged = r1.merge(r2)
        assert merged.entities[0].confidence == pytest.approx(0.9)

    def test_combines_relationships(self):
        rel1 = _make_rel("r1", "e1", "e2")
        rel2 = _make_rel("r2", "e3", "e4")
        r1 = _make_result(rels=[rel1])
        r2 = _make_result(rels=[rel2])
        merged = r1.merge(r2)
        assert len(merged.relationships) == 2

    def test_returns_extraction_result(self):
        assert isinstance(_make_result().merge(_make_result()), EntityExtractionResult)


# ---------------------------------------------------------------------------
# OntologyMediator.snapshot_count
# ---------------------------------------------------------------------------


class TestSnapshotCount:
    def test_zero_initially(self):
        med = _make_mediator()
        assert med.snapshot_count() == 0

    def test_increments_after_stash(self):
        med = _make_mediator()
        med.stash({})
        assert med.snapshot_count() == 1

    def test_equals_get_undo_depth(self):
        med = _make_mediator()
        med.stash({})
        med.stash({})
        assert med.snapshot_count() == med.get_undo_depth()

    def test_zero_after_reset(self):
        med = _make_mediator()
        med.stash({})
        med.reset_all_state()
        assert med.snapshot_count() == 0

    def test_returns_int(self):
        assert isinstance(_make_mediator().snapshot_count(), int)


# ---------------------------------------------------------------------------
# LogicValidator.quick_check
# ---------------------------------------------------------------------------


class TestQuickCheck:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology_is_valid(self):
        assert self.validator.quick_check({"entities": [], "relationships": []}) is True

    def test_returns_bool(self):
        result = self.validator.quick_check({"entities": [], "relationships": []})
        assert isinstance(result, bool)

    def test_agrees_with_is_consistent(self):
        ont = {"entities": [{"id": "e1", "text": "Alice"}], "relationships": []}
        assert self.validator.quick_check(ont) == self.validator.is_consistent(ont)
