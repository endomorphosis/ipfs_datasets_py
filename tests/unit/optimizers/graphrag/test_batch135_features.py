"""Batch-135 feature tests.

Methods under test:
  - LogicValidator.has_cycle(ontology)
  - LogicValidator.cycle_participant_count(ontology)
  - OntologyMediator.undo_stack_summary()
  - OntologyMediator.undo_stack_depth()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _ont_rels(*pairs):
    """Build a minimal ontology dict with directed relationships."""
    rels = [{"source_id": s, "target_id": t} for s, t in pairs]
    return {"relationships": rels}


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    crit = MagicMock()
    return OntologyMediator(gen, crit)


# ---------------------------------------------------------------------------
# LogicValidator.has_cycle
# ---------------------------------------------------------------------------

class TestHasCycle:
    def test_empty_ontology_no_cycle(self):
        v = _make_validator()
        assert v.has_cycle({}) is False

    def test_simple_cycle(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("B", "C"), ("C", "A"))
        assert v.has_cycle(ont) is True

    def test_no_cycle_dag(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("B", "C"), ("A", "C"))
        assert v.has_cycle(ont) is False

    def test_self_loops_ignored(self):
        """Self-loops (source==target) are excluded from adjacency."""
        v = _make_validator()
        ont = _ont_rels(("A", "A"))
        assert v.has_cycle(ont) is False

    def test_two_component_one_cycle(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("C", "D"), ("D", "C"))
        assert v.has_cycle(ont) is True

    def test_single_edge_no_cycle(self):
        v = _make_validator()
        ont = _ont_rels(("X", "Y"))
        assert v.has_cycle(ont) is False


# ---------------------------------------------------------------------------
# LogicValidator.cycle_participant_count
# ---------------------------------------------------------------------------

class TestCycleParticipantCount:
    def test_empty_ontology(self):
        v = _make_validator()
        assert v.cycle_participant_count({}) == 0

    def test_simple_triangle_cycle(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("B", "C"), ("C", "A"))
        # All 3 are in the cycle
        assert v.cycle_participant_count(ont) == 3

    def test_dag_no_participants(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("B", "C"))
        assert v.cycle_participant_count(ont) == 0

    def test_returns_int(self):
        v = _make_validator()
        ont = _ont_rels(("X", "Y"), ("Y", "X"))
        result = v.cycle_participant_count(ont)
        assert isinstance(result, int)

    def test_non_negative(self):
        v = _make_validator()
        ont = _ont_rels(("P", "Q"), ("Q", "R"), ("R", "P"), ("R", "S"))
        assert v.cycle_participant_count(ont) >= 0


# ---------------------------------------------------------------------------
# OntologyMediator.undo_stack_summary
# ---------------------------------------------------------------------------

class TestUndoStackSummary:
    def test_no_stack_returns_empty(self):
        m = _make_mediator()
        # Remove attribute if present to test graceful default
        m.__dict__.pop("_undo_stack", None)
        assert m.undo_stack_summary() == []

    def test_empty_stack_returns_empty(self):
        m = _make_mediator()
        m._undo_stack = []
        assert m.undo_stack_summary() == []

    def test_dict_items_use_action_key(self):
        m = _make_mediator()
        m._undo_stack = [{"action": "ADD_ENTITY"}, {"action": "REMOVE_REL"}]
        result = m.undo_stack_summary()
        assert result == ["ADD_ENTITY", "REMOVE_REL"]

    def test_string_items_preserved(self):
        m = _make_mediator()
        m._undo_stack = ["step_one", "step_two"]
        result = m.undo_stack_summary()
        assert result == ["step_one", "step_two"]

    def test_length_matches_stack(self):
        m = _make_mediator()
        m._undo_stack = [{"action": "X"}, {"action": "Y"}, {"action": "Z"}]
        assert len(m.undo_stack_summary()) == 3


# ---------------------------------------------------------------------------
# OntologyMediator.undo_stack_depth
# ---------------------------------------------------------------------------

class TestUndoStackDepth:
    def test_no_stack_returns_zero(self):
        m = _make_mediator()
        m.__dict__.pop("_undo_stack", None)
        assert m.undo_stack_depth() == 0

    def test_empty_stack_returns_zero(self):
        m = _make_mediator()
        m._undo_stack = []
        assert m.undo_stack_depth() == 0

    def test_three_items(self):
        m = _make_mediator()
        m._undo_stack = ["a", "b", "c"]
        assert m.undo_stack_depth() == 3

    def test_returns_int(self):
        m = _make_mediator()
        m._undo_stack = [{"action": "MERGE"}]
        assert isinstance(m.undo_stack_depth(), int)
