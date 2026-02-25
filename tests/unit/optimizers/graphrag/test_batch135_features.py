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
    @pytest.mark.parametrize(
        "ontology,expected",
        [
            ({}, False),
            (_ont_rels(("A", "B"), ("B", "C"), ("C", "A")), True),
            (_ont_rels(("A", "B"), ("B", "C"), ("A", "C")), False),
            # Self-loops (source==target) are excluded from adjacency.
            (_ont_rels(("A", "A")), False),
            (_ont_rels(("A", "B"), ("C", "D"), ("D", "C")), True),
            (_ont_rels(("X", "Y")), False),
        ],
    )
    def test_has_cycle_scenarios(self, ontology, expected):
        v = _make_validator()
        assert v.has_cycle(ontology) is expected


# ---------------------------------------------------------------------------
# LogicValidator.cycle_participant_count
# ---------------------------------------------------------------------------

class TestCycleParticipantCount:
    @pytest.mark.parametrize(
        "ontology,expected_count",
        [
            ({}, 0),
            # All 3 are in the cycle.
            (_ont_rels(("A", "B"), ("B", "C"), ("C", "A")), 3),
            (_ont_rels(("A", "B"), ("B", "C")), 0),
        ],
    )
    def test_cycle_participant_count_scenarios(self, ontology, expected_count):
        v = _make_validator()
        assert v.cycle_participant_count(ontology) == expected_count

    def test_cycle_participant_count_returns_int(self):
        v = _make_validator()
        ont = _ont_rels(("X", "Y"), ("Y", "X"))
        result = v.cycle_participant_count(ont)
        assert isinstance(result, int)

    def test_cycle_participant_count_non_negative(self):
        v = _make_validator()
        ont = _ont_rels(("P", "Q"), ("Q", "R"), ("R", "P"), ("R", "S"))
        assert v.cycle_participant_count(ont) >= 0


# ---------------------------------------------------------------------------
# OntologyMediator.undo_stack_summary
# ---------------------------------------------------------------------------

class TestUndoStackSummary:
    @pytest.mark.parametrize(
        "stack_state,expected",
        [
            ("missing", []),
            ([], []),
            ([{"action": "ADD_ENTITY"}, {"action": "REMOVE_REL"}], ["ADD_ENTITY", "REMOVE_REL"]),
            (["step_one", "step_two"], ["step_one", "step_two"]),
        ],
    )
    def test_undo_stack_summary_scenarios(self, stack_state, expected):
        m = _make_mediator()
        if stack_state == "missing":
            # Remove attribute if present to test graceful default.
            m.__dict__.pop("_undo_stack", None)
        else:
            m._undo_stack = stack_state
        assert m.undo_stack_summary() == expected

    def test_undo_stack_summary_length_matches_stack(self):
        m = _make_mediator()
        m._undo_stack = [{"action": "X"}, {"action": "Y"}, {"action": "Z"}]
        assert len(m.undo_stack_summary()) == 3


# ---------------------------------------------------------------------------
# OntologyMediator.undo_stack_depth
# ---------------------------------------------------------------------------

class TestUndoStackDepth:
    @pytest.mark.parametrize(
        "stack_state,expected",
        [
            ("missing", 0),
            ([], 0),
            (["a", "b", "c"], 3),
        ],
    )
    def test_undo_stack_depth_scenarios(self, stack_state, expected):
        m = _make_mediator()
        if stack_state == "missing":
            m.__dict__.pop("_undo_stack", None)
        else:
            m._undo_stack = stack_state
        assert m.undo_stack_depth() == expected

    def test_undo_stack_depth_returns_int(self):
        m = _make_mediator()
        m._undo_stack = [{"action": "MERGE"}]
        assert isinstance(m.undo_stack_depth(), int)
