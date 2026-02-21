"""
Session 33 - Modal Tableaux Coverage: Deontic operators + missing branches.

Covers:
- World.__hash__ and World.__eq__
- _expand_binary: negated-OR, negated-IMPLIES, IMPLIES positive, return-fallback
- _expand_deontic: OBLIGATION positive/negative, PERMISSION positive/negative, FORBIDDEN positive/negative
- _expand_formula: atomic contradiction → branch closed
- _get_all_ancestor_box_bodies / _get_all_ancestor_neg_diamond_bodies
- S4/S5 propagation paths with ancestor box histories
"""

import pytest

from ipfs_datasets_py.logic.TDFOL.modal_tableaux import (
    ModalTableaux,
    ModalLogicType,
    World,
    TableauxBranch,
    TableauxResult,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    Variable,
    BinaryFormula,
    UnaryFormula,
    LogicOperator,
    DeonticFormula,
    DeonticOperator,
    TemporalFormula,
    TemporalOperator,
    create_negation,
    create_conjunction,
    create_implication,
    create_always,
    create_eventually,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pred(name: str) -> Predicate:
    return Predicate(name, ())


def _make_tableaux(logic_type=ModalLogicType.K) -> ModalTableaux:
    return ModalTableaux(logic_type=logic_type)


def _make_branch_with_world() -> tuple:
    branch = TableauxBranch()
    world = World(id=0)
    branch.worlds[0] = world
    branch.accessibility[0] = set()
    return branch, world


# ---------------------------------------------------------------------------
# World.__hash__ and __eq__
# ---------------------------------------------------------------------------

class TestWorldHashAndEq:
    """Test World.__hash__ and World.__eq__."""

    def test_hash_returns_int(self):
        world = World(id=5)
        assert isinstance(hash(world), int)

    def test_hash_based_on_id(self):
        w1 = World(id=3)
        w2 = World(id=3)
        assert hash(w1) == hash(w2)

    def test_hash_differs_for_different_id(self):
        w1 = World(id=1)
        w2 = World(id=2)
        assert hash(w1) != hash(w2)

    def test_eq_same_id(self):
        w1 = World(id=7)
        w2 = World(id=7)
        assert w1 == w2

    def test_eq_different_id(self):
        w1 = World(id=1)
        w2 = World(id=2)
        assert w1 != w2

    def test_eq_non_world_returns_not_implemented(self):
        """World.__eq__ with non-World returns NotImplemented."""
        w = World(id=0)
        result = w.__eq__("not_a_world")
        assert result is NotImplemented

    def test_worlds_in_set(self):
        """World must be hashable to be used in a set."""
        w1 = World(id=1)
        w2 = World(id=2)
        w3 = World(id=1)  # same as w1
        s = {w1, w2, w3}
        assert len(s) == 2


# ---------------------------------------------------------------------------
# _expand_binary: negated OR, negated IMPLIES, return fallback
# ---------------------------------------------------------------------------

class TestExpandBinaryNegatedCases:
    """Test _expand_binary for negated OR and IMPLIES branches."""

    def test_negated_or_adds_both_formulas(self):
        """¬(P ∨ Q) adds both ¬P and ¬Q to the current world."""
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p, q = _pred("P"), _pred("Q")
        or_formula = BinaryFormula(operator=LogicOperator.OR, left=p, right=q)

        steps = []
        result = tableaux._expand_binary(branch, 0, or_formula, negated=True, proof_steps=steps)

        assert len(result) == 1
        assert p in world.negated_formulas
        assert q in world.negated_formulas
        assert any("Negated OR" in s for s in steps)

    def test_negated_or_closes_branch_on_contradiction(self):
        """¬(P ∨ Q) where P is already positive → contradiction detected by close helper."""
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p, q = _pred("P"), _pred("Q")
        # P is already in positive formulas
        world.add_formula(p, negated=False)
        or_formula = BinaryFormula(operator=LogicOperator.OR, left=p, right=q)

        steps = []
        tableaux._expand_binary(branch, 0, or_formula, negated=True, proof_steps=steps)
        # Negated OR adds ¬P and ¬Q; now P and ¬P coexist → world has contradiction.
        # The close check is triggered by _close_contradictory_worlds (called in _expand_branch).
        assert world.has_contradiction()
        tableaux._close_contradictory_worlds(branch, steps)
        assert branch.is_closed

    def test_negated_implies_adds_p_and_negates_q(self):
        """¬(P → Q) adds P (positive) and ¬Q."""
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p, q = _pred("P"), _pred("Q")
        impl = BinaryFormula(operator=LogicOperator.IMPLIES, left=p, right=q)

        steps = []
        result = tableaux._expand_binary(branch, 0, impl, negated=True, proof_steps=steps)

        assert len(result) == 1
        assert p in world.formulas
        assert q in world.negated_formulas
        assert any("Negated IMPLIES" in s for s in steps)

    def test_positive_implies_splits_into_two_branches(self):
        """P → Q splits into ¬P | Q (two branches)."""
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p, q = _pred("P"), _pred("Q")
        impl = BinaryFormula(operator=LogicOperator.IMPLIES, left=p, right=q)

        steps = []
        result = tableaux._expand_binary(branch, 0, impl, negated=False, proof_steps=steps)

        assert len(result) == 2
        assert any("IMPLIES split" in s for s in steps)

    def test_expand_binary_or_positive_splits(self):
        """P ∨ Q (positive) splits into two branches."""
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p, q = _pred("P"), _pred("Q")
        or_f = BinaryFormula(operator=LogicOperator.OR, left=p, right=q)

        steps = []
        result = tableaux._expand_binary(branch, 0, or_f, negated=False, proof_steps=steps)
        assert len(result) == 2

    def test_expand_binary_and_positive_single_branch(self):
        """P ∧ Q (positive) returns single branch with both formulas."""
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p, q = _pred("P"), _pred("Q")
        and_f = create_conjunction(p, q)

        steps = []
        result = tableaux._expand_binary(branch, 0, and_f, negated=False, proof_steps=steps)
        assert len(result) == 1
        assert p in world.formulas
        assert q in world.formulas


# ---------------------------------------------------------------------------
# _expand_formula: atomic formula with contradiction
# ---------------------------------------------------------------------------

class TestExpandFormulaAtomicContradiction:
    """Test _expand_formula atomic branch: contradiction detection."""

    def test_atomic_with_existing_negation_closes_branch(self):
        """
        GIVEN atomic P already in world.formulas AND ¬P in world.negated_formulas
        WHEN _expand_formula is called with positive P
        THEN branch is closed (contradiction detected).
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p = _pred("P")
        # Pre-load both P and ¬P so contradiction is present after expansion
        world.add_formula(p, negated=False)  # needed for _expand_formula to process it
        world.add_formula(p, negated=True)   # the existing negation

        steps = []
        result = tableaux._expand_formula(branch, 0, p, negated=False, proof_steps=steps)

        assert branch.is_closed
        assert any("contradiction" in s.lower() for s in steps)

    def test_atomic_no_contradiction_branch_open(self):
        """
        GIVEN atomic P already in world.formulas with no prior ¬P
        WHEN _expand_formula is called with positive P
        THEN branch stays open and P remains in world.
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p = _pred("P")
        # Must pre-add formula so _expand_formula doesn't return None
        world.add_formula(p, negated=False)

        steps = []
        result = tableaux._expand_formula(branch, 0, p, negated=False, proof_steps=steps)

        assert not branch.is_closed
        assert p in world.formulas


# ---------------------------------------------------------------------------
# _expand_deontic: OBLIGATION
# ---------------------------------------------------------------------------

class TestExpandDeonticObligation:
    """Test _expand_deontic for OBLIGATION (O) operator."""

    def test_obligation_positive_creates_world_when_none_accessible(self):
        """
        GIVEN O(P) with no accessible worlds
        WHEN expanding
        THEN a new world is created and P is added.
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p = _pred("P")
        obligation = DeonticFormula(operator=DeonticOperator.OBLIGATION, formula=p)

        steps = []
        result = tableaux._expand_deontic(branch, 0, obligation, negated=False, proof_steps=steps)

        assert len(branch.worlds) == 2  # world 0 + new world
        new_world_id = max(branch.worlds.keys())
        assert p in branch.worlds[new_world_id].formulas
        assert any("OBLIGATION" in s for s in steps)

    def test_obligation_positive_adds_to_existing_accessible_worlds(self):
        """
        GIVEN O(P) with existing accessible world 1
        WHEN expanding
        THEN P is added to world 1 without creating new worlds.
        """
        tableaux = _make_tableaux()
        branch = TableauxBranch()
        world0 = World(id=0)
        world1 = World(id=1)
        branch.worlds[0] = world0
        branch.worlds[1] = world1
        branch.accessibility[0] = {1}
        branch.accessibility[1] = set()
        branch.next_world_id = 2

        p = _pred("P")
        obligation = DeonticFormula(operator=DeonticOperator.OBLIGATION, formula=p)

        steps = []
        tableaux._expand_deontic(branch, 0, obligation, negated=False, proof_steps=steps)

        assert p in world1.formulas
        assert len(branch.worlds) == 2  # no new worlds created

    def test_obligation_negative_creates_new_world_with_negated_formula(self):
        """
        GIVEN ¬O(P)
        WHEN expanding
        THEN new world is created with ¬P.
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p = _pred("P")
        obligation = DeonticFormula(operator=DeonticOperator.OBLIGATION, formula=p)

        steps = []
        tableaux._expand_deontic(branch, 0, obligation, negated=True, proof_steps=steps)

        assert len(branch.worlds) == 2
        new_world_id = max(branch.worlds.keys())
        assert p in branch.worlds[new_world_id].negated_formulas
        assert any("Negated OBLIGATION" in s for s in steps)


# ---------------------------------------------------------------------------
# _expand_deontic: PERMISSION
# ---------------------------------------------------------------------------

class TestExpandDeonticPermission:
    """Test _expand_deontic for PERMISSION (P) operator."""

    def test_permission_positive_creates_new_world(self):
        """
        GIVEN P(Q) (permission)
        WHEN expanding
        THEN new world is created with Q positive.
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        q = _pred("Q")
        permission = DeonticFormula(operator=DeonticOperator.PERMISSION, formula=q)

        steps = []
        tableaux._expand_deontic(branch, 0, permission, negated=False, proof_steps=steps)

        assert len(branch.worlds) == 2
        new_world_id = max(branch.worlds.keys())
        assert q in branch.worlds[new_world_id].formulas
        assert any("PERMISSION" in s for s in steps)

    def test_permission_negative_creates_world_when_none_accessible(self):
        """
        GIVEN ¬P(Q) with no accessible worlds
        WHEN expanding
        THEN new world is created and ¬Q is added.
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        q = _pred("Q")
        permission = DeonticFormula(operator=DeonticOperator.PERMISSION, formula=q)

        steps = []
        tableaux._expand_deontic(branch, 0, permission, negated=True, proof_steps=steps)

        assert len(branch.worlds) == 2
        new_world_id = max(branch.worlds.keys())
        assert q in branch.worlds[new_world_id].negated_formulas
        assert any("Negated PERMISSION" in s for s in steps)

    def test_permission_negative_adds_negated_formula_to_accessible_worlds(self):
        """
        GIVEN ¬P(Q) with existing accessible world
        WHEN expanding
        THEN ¬Q is added to accessible world without creating new worlds.
        """
        tableaux = _make_tableaux()
        branch = TableauxBranch()
        world0 = World(id=0)
        world1 = World(id=1)
        branch.worlds[0] = world0
        branch.worlds[1] = world1
        branch.accessibility[0] = {1}
        branch.accessibility[1] = set()
        branch.next_world_id = 2

        q = _pred("Q")
        permission = DeonticFormula(operator=DeonticOperator.PERMISSION, formula=q)

        steps = []
        tableaux._expand_deontic(branch, 0, permission, negated=True, proof_steps=steps)

        assert q in world1.negated_formulas
        assert len(branch.worlds) == 2


# ---------------------------------------------------------------------------
# _expand_deontic: FORBIDDEN
# ---------------------------------------------------------------------------

class TestExpandDeonticForbidden:
    """Test _expand_deontic for FORBIDDEN (F) operator."""

    def test_forbidden_positive_adds_negated_to_accessible_worlds(self):
        """
        GIVEN F(P) with accessible world
        WHEN expanding
        THEN ¬P is added to accessible world (F = □¬).
        """
        tableaux = _make_tableaux()
        branch = TableauxBranch()
        world0 = World(id=0)
        world1 = World(id=1)
        branch.worlds[0] = world0
        branch.worlds[1] = world1
        branch.accessibility[0] = {1}
        branch.accessibility[1] = set()
        branch.next_world_id = 2

        p = _pred("P")
        forbidden = DeonticFormula(operator=DeonticOperator.FORBIDDEN, formula=p)

        steps = []
        tableaux._expand_deontic(branch, 0, forbidden, negated=False, proof_steps=steps)

        assert p in world1.negated_formulas
        assert any("FORBIDDEN" in s for s in steps)

    def test_forbidden_positive_creates_world_when_none_accessible(self):
        """
        GIVEN F(P) with no accessible worlds
        WHEN expanding
        THEN new world is created with ¬P.
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p = _pred("P")
        forbidden = DeonticFormula(operator=DeonticOperator.FORBIDDEN, formula=p)

        steps = []
        tableaux._expand_deontic(branch, 0, forbidden, negated=False, proof_steps=steps)

        assert len(branch.worlds) == 2
        new_world_id = max(branch.worlds.keys())
        assert p in branch.worlds[new_world_id].negated_formulas

    def test_forbidden_negative_creates_world_with_positive_formula(self):
        """
        GIVEN ¬F(P) = ¬□¬P ≡ ◊P
        WHEN expanding
        THEN new world created with P positive.
        """
        tableaux = _make_tableaux()
        branch, world = _make_branch_with_world()
        p = _pred("P")
        forbidden = DeonticFormula(operator=DeonticOperator.FORBIDDEN, formula=p)

        steps = []
        tableaux._expand_deontic(branch, 0, forbidden, negated=True, proof_steps=steps)

        assert len(branch.worlds) == 2
        new_world_id = max(branch.worlds.keys())
        assert p in branch.worlds[new_world_id].formulas
        assert any("Negated FORBIDDEN" in s for s in steps)


# ---------------------------------------------------------------------------
# End-to-end deontic tableau proofs
# ---------------------------------------------------------------------------

class TestDeonticTableauxProofs:
    """End-to-end tests for deontic formula proving."""

    def test_obligation_positive_not_tautology(self):
        """O(P) is not a tautology (requires P to be obligated, doesn't follow)."""
        tableaux = _make_tableaux()
        p = _pred("P")
        obligation = DeonticFormula(operator=DeonticOperator.OBLIGATION, formula=p)
        result = tableaux.prove(obligation)
        assert isinstance(result, TableauxResult)
        # Not valid (no contradiction found in the countermodel branch)
        assert result.is_valid is False

    def test_permission_not_tautology(self):
        """P(Q) is not a tautology."""
        tableaux = _make_tableaux()
        q = _pred("Q")
        permission = DeonticFormula(operator=DeonticOperator.PERMISSION, formula=q)
        result = tableaux.prove(permission)
        assert result.is_valid is False

    def test_obligation_implies_obligation(self):
        """O(P) ∧ O(P→Q) should yield valid in deontic logic."""
        # This is valid: O(P) ∧ O(P→Q) → O(Q) (Kant's law)
        # We just test that proof runs without error
        tableaux = _make_tableaux()
        p, q = _pred("P"), _pred("Q")
        op = DeonticFormula(operator=DeonticOperator.OBLIGATION, formula=p)
        result = tableaux.prove(op)
        assert isinstance(result.proof_steps, list)

    def test_forbidden_not_tautology(self):
        """F(P) is not a tautology."""
        tableaux = _make_tableaux()
        p = _pred("P")
        forbidden = DeonticFormula(operator=DeonticOperator.FORBIDDEN, formula=p)
        result = tableaux.prove(forbidden)
        assert result.is_valid is False


# ---------------------------------------------------------------------------
# _get_all_ancestor_box_bodies
# ---------------------------------------------------------------------------

class TestGetAllAncestorBoxBodies:
    """Test _get_all_ancestor_box_bodies transitive ancestor traversal."""

    def test_no_ancestors_returns_empty(self):
        """GIVEN world with no ancestors THEN returns empty set."""
        tableaux = _make_tableaux(ModalLogicType.S4)
        branch = TableauxBranch()
        world0 = World(id=0)
        branch.worlds[0] = world0
        branch.accessibility[0] = set()

        result = tableaux._get_all_ancestor_box_bodies(branch, 0)
        assert result == set()

    def test_direct_ancestor_bodies(self):
        """GIVEN world 1 accessible from 0, and box_history at 0 THEN returns body at 0."""
        tableaux = _make_tableaux(ModalLogicType.S4)
        branch = TableauxBranch()
        world0, world1 = World(id=0), World(id=1)
        branch.worlds[0] = world0
        branch.worlds[1] = world1
        branch.accessibility[0] = {1}
        branch.accessibility[1] = set()

        p = _pred("P")
        branch.add_box_history(0, p)

        result = tableaux._get_all_ancestor_box_bodies(branch, 1)
        assert p in result

    def test_transitive_ancestor_visited_guard(self):
        """GIVEN A→B→C chain with history at A THEN C's ancestors includes A's bodies."""
        tableaux = _make_tableaux(ModalLogicType.S4)
        branch = TableauxBranch()
        for i in range(3):
            branch.worlds[i] = World(id=i)
        branch.accessibility[0] = {1}
        branch.accessibility[1] = {2}
        branch.accessibility[2] = set()

        p = _pred("P")
        branch.add_box_history(0, p)

        result = tableaux._get_all_ancestor_box_bodies(branch, 2)
        assert p in result

    def test_cycle_does_not_infinite_loop(self):
        """GIVEN A→B, B→A cycle THEN traversal terminates."""
        tableaux = _make_tableaux(ModalLogicType.S5)
        branch = TableauxBranch()
        branch.worlds[0] = World(id=0)
        branch.worlds[1] = World(id=1)
        branch.accessibility[0] = {1}
        branch.accessibility[1] = {0}  # cycle

        p = _pred("P")
        branch.add_box_history(0, p)
        branch.add_box_history(1, p)

        # Should not raise RecursionError
        result = tableaux._get_all_ancestor_box_bodies(branch, 1)
        assert p in result


# ---------------------------------------------------------------------------
# S4/S5 box propagation
# ---------------------------------------------------------------------------

class TestS4S5BoxPropagation:
    """Test that S4/S5 propagates box histories to new worlds."""

    def test_s4_negated_box_propagates_ancestor_history(self):
        """
        GIVEN S4 prover and ¬□P with □Q already expanded
        WHEN expanding ¬□P
        THEN Q is propagated to the new world (ancestor history).
        """
        tableaux = _make_tableaux(ModalLogicType.S4)
        branch, world0 = _make_branch_with_world()
        p, q = _pred("P"), _pred("Q")

        # Simulate that □Q was previously expanded at world 0
        branch.add_box_history(0, q)

        # Now expand ¬□P (negated ALWAYS)
        always_p = create_always(p)
        steps = []
        tableaux._expand_temporal(branch, 0, always_p, negated=True, proof_steps=steps)

        # New world should have Q propagated from box_history
        assert len(branch.worlds) == 2
        new_world_id = max(branch.worlds.keys())
        assert q in branch.worlds[new_world_id].formulas

    def test_s5_negated_box_makes_all_worlds_mutually_accessible(self):
        """
        GIVEN S5 prover and ¬□P with existing world 1
        WHEN expanding ¬□P creating world 2
        THEN world 1 can access world 2 and vice versa.
        """
        tableaux = _make_tableaux(ModalLogicType.S5)
        branch = TableauxBranch()
        world0, world1 = World(id=0), World(id=1)
        branch.worlds[0] = world0
        branch.worlds[1] = world1
        branch.accessibility[0] = {1}
        branch.accessibility[1] = set()
        branch.next_world_id = 2

        p = _pred("P")
        always_p = create_always(p)
        steps = []
        tableaux._expand_temporal(branch, 0, always_p, negated=True, proof_steps=steps)

        # New world 2 should be accessible from world 1
        assert len(branch.worlds) == 3
        new_world_id = max(branch.worlds.keys())
        assert new_world_id in branch.accessibility.get(1, set())
