"""Batch 78: worst_ontology, dedup_by_text_prefix, is_consistent,
critical_weaknesses, peek_undo, serialize_to_file/from_file, random_sample."""

from __future__ import annotations

import sys
import pathlib
import tempfile
import os

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    FeedbackRecord,
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, conf: float = 0.8, span=None) -> Entity:
    return Entity(id=eid, text=text, type="TEST", confidence=conf, source_span=span)


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
        completeness=c, consistency=con, clarity=cl, granularity=g, relationship_coherence=da
    , domain_alignment=da
    )


def _make_report(score: float, ontology: dict | None = None) -> OptimizationReport:
    return OptimizationReport(
        average_score=score,
        trend="stable",
        best_ontology=ontology or {"entities": []},
    )


# ---------------------------------------------------------------------------
# OntologyOptimizer.worst_ontology
# ---------------------------------------------------------------------------


class TestWorstOntology:
    def test_empty_history_returns_none(self):
        opt = OntologyOptimizer()
        assert opt.worst_ontology() is None

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.5, {"entities": ["A"]}))
        assert opt.worst_ontology() == {"entities": ["A"]}

    def test_selects_lowest_score(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.9, {"name": "best"}))
        opt._history.append(_make_report(0.3, {"name": "worst"}))
        opt._history.append(_make_report(0.6, {"name": "mid"}))
        assert opt.worst_ontology() == {"name": "worst"}

    def test_distinct_from_best_ontology(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.9, {"name": "best"}))
        opt._history.append(_make_report(0.2, {"name": "worst"}))
        assert opt.best_ontology() != opt.worst_ontology()

    def test_returns_dict_or_none(self):
        opt = OntologyOptimizer()
        result = opt.worst_ontology()
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# OntologyGenerator.dedup_by_text_prefix
# ---------------------------------------------------------------------------


class TestDedupByTextPrefix:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_no_duplicates_unchanged(self):
        e1 = _make_entity("1", "Alice")
        e2 = _make_entity("2", "Bob")
        r = _make_result(e1, e2)
        out = self.gen.dedup_by_text_prefix(r, prefix_len=3)
        assert len(out.entities) == 2

    def test_duplicate_prefix_keeps_higher_confidence(self):
        e1 = _make_entity("1", "Alice", conf=0.5)
        e2 = _make_entity("2", "Alic", conf=0.9)
        r = _make_result(e1, e2)
        out = self.gen.dedup_by_text_prefix(r, prefix_len=4)
        assert len(out.entities) == 1
        assert out.entities[0].confidence == 0.9

    def test_prefix_len_one(self):
        e1 = _make_entity("1", "Alpha", conf=0.3)
        e2 = _make_entity("2", "Apple", conf=0.8)
        r = _make_result(e1, e2)
        out = self.gen.dedup_by_text_prefix(r, prefix_len=1)
        assert len(out.entities) == 1

    def test_relationships_pruned_for_removed_entities(self):
        e1 = _make_entity("1", "Alpha", conf=0.3)
        e2 = _make_entity("2", "Apple", conf=0.8)
        e3 = _make_entity("3", "Bob", conf=0.9)
        rel = Relationship(id="r1", source_id="1", target_id="3", type="knows", confidence=0.9)
        r = EntityExtractionResult(
            entities=[e1, e2, e3], relationships=[rel], confidence=0.8, metadata={}
        )
        out = self.gen.dedup_by_text_prefix(r, prefix_len=1)
        # "1" (Alpha) removed, relationship should be gone
        kept_ids = {e.id for e in out.entities}
        assert all(rel.source_id in kept_ids and rel.target_id in kept_ids for rel in out.relationships)

    def test_invalid_prefix_len_raises(self):
        r = _make_result()
        with pytest.raises(ValueError):
            self.gen.dedup_by_text_prefix(r, prefix_len=0)

    def test_empty_result_unchanged(self):
        r = _make_result()
        out = self.gen.dedup_by_text_prefix(r)
        assert out.entities == []


# ---------------------------------------------------------------------------
# LogicValidator.is_consistent
# ---------------------------------------------------------------------------


class TestIsConsistent:
    def setup_method(self):
        self.v = LogicValidator()

    def test_empty_ontology_consistent(self):
        assert self.v.is_consistent({"entities": [], "relationships": []})

    def test_returns_bool(self):
        result = self.v.is_consistent({"entities": []})
        assert isinstance(result, bool)

    def test_consistent_when_no_contradictions(self):
        assert self.v.is_consistent({}) is True

    def test_matches_count_contradictions(self):
        ont = {"entities": [{"id": "e1", "type": "X"}]}
        assert self.v.is_consistent(ont) == (self.v.count_contradictions(ont) == 0)


# ---------------------------------------------------------------------------
# OntologyCritic.critical_weaknesses
# ---------------------------------------------------------------------------


class TestCriticalWeaknesses:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_no_weaknesses_high_scores(self):
        score = _make_score(c=0.9, con=0.8, cl=0.7, g=0.6, da=0.9)
        assert self.critic.critical_weaknesses(score) == {}

    def test_all_below_threshold(self):
        score = _make_score(c=0.1, con=0.2, cl=0.3, g=0.4, da=0.1)
        weak = self.critic.critical_weaknesses(score)
        assert len(weak) == 5

    def test_partial_weaknesses(self):
        score = _make_score(c=0.9, con=0.3, cl=0.9, g=0.1, da=0.9)
        weak = self.critic.critical_weaknesses(score)
        assert "consistency" in weak
        assert "granularity" in weak
        assert "completeness" not in weak

    def test_values_below_threshold(self):
        score = _make_score(c=0.4)
        weak = self.critic.critical_weaknesses(score)
        assert all(v < 0.5 for v in weak.values())

    def test_custom_threshold(self):
        score = _make_score(c=0.7, con=0.7, cl=0.7, g=0.7, da=0.7)
        weak = self.critic.critical_weaknesses(score, threshold=0.8)
        assert len(weak) == 5

    def test_returns_dict(self):
        score = _make_score()
        assert isinstance(self.critic.critical_weaknesses(score), dict)


# ---------------------------------------------------------------------------
# OntologyMediator.peek_undo
# ---------------------------------------------------------------------------


class TestPeekUndo:
    def test_empty_stack_returns_none(self):
        med = _make_mediator()
        assert med.peek_undo() is None

    def test_returns_top_snapshot(self):
        med = _make_mediator()
        snap = {"entities": ["x"], "tag": "batch78"}
        med._undo_stack.append(snap)
        assert med.peek_undo() is snap

    def test_does_not_pop(self):
        med = _make_mediator()
        snap = {"tag": "test"}
        med._undo_stack.append(snap)
        med.peek_undo()
        assert med.get_undo_depth() == 1

    def test_returns_last_push(self):
        med = _make_mediator()
        med._undo_stack.append({"seq": 1})
        med._undo_stack.append({"seq": 2})
        assert med.peek_undo()["seq"] == 2

    def test_none_when_cleared(self):
        med = _make_mediator()
        med._undo_stack.append({"x": 1})
        med._undo_stack.pop()
        assert med.peek_undo() is None


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.serialize_to_file / from_file
# ---------------------------------------------------------------------------


class TestSerializeToFile:
    def test_round_trip_empty(self):
        adapter = OntologyLearningAdapter(base_threshold=0.55)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            adapter.serialize_to_file(path)
            adapter2 = OntologyLearningAdapter.from_file(path)
            assert adapter2._current_threshold == pytest.approx(0.55, abs=1e-6)
            assert len(adapter2._feedback) == 0
        finally:
            os.unlink(path)

    def test_round_trip_with_feedback(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.7, action_types=["add_entity"]))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            adapter.serialize_to_file(path)
            adapter2 = OntologyLearningAdapter.from_file(path)
            assert len(adapter2._feedback) == 1
            assert adapter2._feedback[0].final_score == pytest.approx(0.7, abs=1e-6)
        finally:
            os.unlink(path)

    def test_creates_valid_json_file(self):
        import json
        adapter = OntologyLearningAdapter()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            adapter.serialize_to_file(path)
            data = json.load(open(path))
            assert "current_threshold" in data
        finally:
            os.unlink(path)

    def test_action_types_preserved(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.6, action_types=["merge"]))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            adapter.serialize_to_file(path)
            adapter2 = OntologyLearningAdapter.from_file(path)
            assert adapter2._feedback[0].action_types == ["merge"]
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# EntityExtractionResult.random_sample
# ---------------------------------------------------------------------------


class TestRandomSample:
    def test_sample_smaller_than_total(self):
        entities = [_make_entity(str(i), f"E{i}") for i in range(10)]
        r = _make_result(*entities)
        sampled = r.random_sample(5)
        assert len(sampled.entities) == 5

    def test_sample_larger_returns_all(self):
        entities = [_make_entity(str(i), f"E{i}") for i in range(3)]
        r = _make_result(*entities)
        sampled = r.random_sample(10)
        assert len(sampled.entities) == 3

    def test_sample_zero(self):
        entities = [_make_entity("1", "Alice")]
        r = _make_result(*entities)
        sampled = r.random_sample(0)
        assert len(sampled.entities) == 0

    def test_returns_new_object(self):
        entities = [_make_entity(str(i), f"E{i}") for i in range(5)]
        r = _make_result(*entities)
        assert r.random_sample(3) is not r

    def test_relationships_pruned(self):
        e1 = _make_entity("1", "Alice")
        e2 = _make_entity("2", "Bob")
        rel = Relationship(id="r1", source_id="1", target_id="2", type="knows", confidence=0.9)
        r = EntityExtractionResult(entities=[e1, e2], relationships=[rel], confidence=0.8, metadata={})
        # sample only 1 entity — relationship must be removed
        sampled = r.random_sample(1)
        kept_ids = {e.id for e in sampled.entities}
        for rr in sampled.relationships:
            assert rr.source_id in kept_ids and rr.target_id in kept_ids
