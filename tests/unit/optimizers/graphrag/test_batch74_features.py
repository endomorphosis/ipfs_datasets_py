"""Batch-74 feature tests.

Covers:
- OntologyOptimizer.best_ontology()
- OntologyMediator.undo_last_action()
- OntologyGenerator.filter_entities(result, ...)
- OntologyGenerator.extract_noun_phrases(text)
- OntologyLearningAdapter.reset_feedback()
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    OntologyGenerationContext,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=crit, max_rounds=3)


def _report(avg: float, best_ont=None) -> OptimizationReport:
    return OptimizationReport(
        average_score=avg,
        trend="stable",
        best_ontology=best_ont,
    )


def _entity(eid="e1", etype="Person", text="Alice", conf=0.9) -> Entity:
    return Entity(id=eid, type=etype, text=text, confidence=conf)


def _result(*entities, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities),
        relationships=list(rels or []),
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# OntologyOptimizer.best_ontology
# ---------------------------------------------------------------------------

class TestBestOntology:
    def test_empty_history_returns_none(self):
        opt = OntologyOptimizer()
        assert opt.best_ontology() is None

    def test_returns_best_from_report(self):
        opt = OntologyOptimizer()
        ont = {"entities": [{"id": "e1", "type": "T"}]}
        opt._history.append(_report(0.6, best_ont=ont))
        assert opt.best_ontology() is ont

    def test_picks_highest_score(self):
        opt = OntologyOptimizer()
        ont_low = {"label": "low"}
        ont_high = {"label": "high"}
        opt._history.append(_report(0.5, best_ont=ont_low))
        opt._history.append(_report(0.9, best_ont=ont_high))
        assert opt.best_ontology() is ont_high

    def test_none_if_no_best_ontology_set(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.7, best_ont=None))
        assert opt.best_ontology() is None

    def test_returns_dict_or_none(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.8, best_ont={"k": "v"}))
        result = opt.best_ontology()
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# OntologyMediator.undo_last_action
# ---------------------------------------------------------------------------

class TestUndoLastAction:
    def test_empty_stack_raises(self):
        with pytest.raises(IndexError):
            _mediator().undo_last_action()

    def test_pops_last_state(self):
        med = _mediator()
        state = {"entities": [], "relationships": []}
        med._undo_stack.append(state)
        result = med.undo_last_action()
        assert result is state

    def test_stack_shrinks(self):
        med = _mediator()
        med._undo_stack.extend([{}, {}, {}])
        med.undo_last_action()
        assert med.get_undo_depth() == 2

    def test_lifo_order(self):
        med = _mediator()
        med._undo_stack.extend([{"order": 1}, {"order": 2}])
        assert med.undo_last_action() == {"order": 2}
        assert med.undo_last_action() == {"order": 1}

    def test_returns_none_after_exhausted(self):
        med = _mediator()
        med._undo_stack.append({"x": 1})
        med.undo_last_action()
        with pytest.raises(IndexError):
            med.undo_last_action()


# ---------------------------------------------------------------------------
# OntologyGenerator.filter_entities
# ---------------------------------------------------------------------------

class TestFilterEntities:
    def test_returns_extraction_result(self):
        gen = OntologyGenerator()
        r = _result(_entity())
        assert isinstance(gen.filter_entities(r), EntityExtractionResult)

    def test_filter_by_type(self):
        gen = OntologyGenerator()
        e1 = _entity("e1", "Person", "Alice")
        e2 = _entity("e2", "Org", "ACME")
        r = _result(e1, e2)
        filtered = gen.filter_entities(r, allowed_types=["Person"])
        assert len(filtered.entities) == 1
        assert filtered.entities[0].type == "Person"

    def test_filter_by_confidence(self):
        gen = OntologyGenerator()
        e1 = _entity("e1", conf=0.9)
        e2 = _entity("e2", conf=0.3)
        r = _result(e1, e2)
        filtered = gen.filter_entities(r, min_confidence=0.5)
        assert len(filtered.entities) == 1

    def test_filter_by_text(self):
        gen = OntologyGenerator()
        e1 = _entity("e1", text="Alice Smith")
        e2 = _entity("e2", text="Bob Jones")
        r = _result(e1, e2)
        filtered = gen.filter_entities(r, text_contains="alice")
        assert len(filtered.entities) == 1

    def test_removes_orphaned_rels(self):
        gen = OntologyGenerator()
        e1 = _entity("e1", "Person", "Alice")
        e2 = _entity("e2", "Org", "ACME")
        rel = Relationship(id="r1", source_id="e1", target_id="e2", type="member")
        r = _result(e1, e2, rels=[rel])
        filtered = gen.filter_entities(r, allowed_types=["Person"])
        assert len(filtered.relationships) == 0

    def test_type_case_insensitive(self):
        gen = OntologyGenerator()
        e = _entity("e1", "PERSON", "Alice")
        r = _result(e)
        filtered = gen.filter_entities(r, allowed_types=["person"])
        assert len(filtered.entities) == 1

    def test_no_criteria_keeps_all(self):
        gen = OntologyGenerator()
        r = _result(_entity("e1"), _entity("e2", "Org"))
        assert len(gen.filter_entities(r).entities) == 2


# ---------------------------------------------------------------------------
# OntologyGenerator.extract_noun_phrases
# ---------------------------------------------------------------------------

class TestExtractNounPhrases:
    def test_returns_list(self):
        gen = OntologyGenerator()
        assert isinstance(gen.extract_noun_phrases("Alice ran fast"), list)

    def test_empty_text(self):
        gen = OntologyGenerator()
        assert gen.extract_noun_phrases("") == []

    def test_phrases_are_strings(self):
        gen = OntologyGenerator()
        for np in gen.extract_noun_phrases("The quick brown fox"):
            assert isinstance(np, str)

    def test_title_case_included(self):
        gen = OntologyGenerator()
        phrases = gen.extract_noun_phrases("Alice Smith met Bob Jones")
        combined = " ".join(phrases)
        assert "Alice" in combined or "Smith" in combined


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.reset_feedback
# ---------------------------------------------------------------------------

class TestResetFeedback:
    def test_returns_int(self):
        ada = OntologyLearningAdapter()
        assert isinstance(ada.reset_feedback(), int)

    def test_clears_feedback(self):
        ada = OntologyLearningAdapter()
        ada.apply_feedback(0.8)
        ada.apply_feedback(0.7)
        ada.reset_feedback()
        assert len(ada._feedback) == 0

    def test_returns_count(self):
        ada = OntologyLearningAdapter()
        ada.apply_feedback(0.8)
        ada.apply_feedback(0.7)
        assert ada.reset_feedback() == 2

    def test_preserves_threshold(self):
        ada = OntologyLearningAdapter(base_threshold=0.4)
        ada.apply_feedback(0.9)
        threshold_before = ada._current_threshold
        ada.reset_feedback()
        assert ada._current_threshold == threshold_before

    def test_zero_if_empty(self):
        ada = OntologyLearningAdapter()
        assert ada.reset_feedback() == 0

    def test_preserves_action_counts(self):
        ada = OntologyLearningAdapter()
        ada.apply_feedback(0.8, actions=["refine"])
        ada.reset_feedback()
        assert ada._action_count.get("refine", 0) == 1
