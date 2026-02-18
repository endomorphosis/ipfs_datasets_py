"""
Modal Tableaux for TDFOL

This module implements modal tableaux decision procedures for modal logics K, T, D, S4, and S5.
Modal tableaux provide automated theorem proving for modal formulas by systematically exploring
possible worlds and their accessibility relations.

Supported Modal Logics:
- K: Basic modal logic (no constraints)
- T: Reflexive (□φ → φ)
- D: Serial (◊⊤, consistency requirement)
- S4: Reflexive + Transitive (□φ → □□φ)
- S5: Equivalence relation (reflexive + symmetric + transitive)

The tableaux method works by:
1. Starting with formulas at the root world
2. Applying expansion rules to decompose formulas
3. Creating new worlds for modal formulas
4. Checking for contradictions (closure)
5. If all branches close, the original formula is valid
6. If an open branch remains, we can extract a countermodel
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any

from .tdfol_core import (
    Formula,
    UnaryFormula,
    BinaryFormula,
    LogicOperator,
    TemporalFormula,
    TemporalOperator,
    DeonticFormula,
    DeonticOperator,
    Predicate,
    Variable,
)
from .exceptions import ProofError

logger = logging.getLogger(__name__)


class ModalLogicType(Enum):
    """Types of modal logics supported by tableaux."""
    K = "K"   # Basic modal logic
    T = "T"   # Reflexive
    D = "D"   # Serial
    S4 = "S4" # Reflexive + Transitive
    S5 = "S5" # Equivalence relation


@dataclass
class World:
    """Represents a possible world in the Kripke structure."""
    id: int
    formulas: Set[Formula] = field(default_factory=set)
    negated_formulas: Set[Formula] = field(default_factory=set)
    
    def add_formula(self, formula: Formula, negated: bool = False) -> None:
        """Add a formula to this world."""
        if negated:
            self.negated_formulas.add(formula)
        else:
            self.formulas.add(formula)
    
    def has_contradiction(self) -> bool:
        """Check if this world contains a contradiction (φ and ¬φ)."""
        return bool(self.formulas & self.negated_formulas)
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, World):
            return NotImplemented
        return self.id == other.id


@dataclass
class TableauxBranch:
    """Represents a branch in the tableaux tree."""
    worlds: Dict[int, World] = field(default_factory=dict)
    accessibility: Dict[int, Set[int]] = field(default_factory=dict)
    current_world: int = 0
    is_closed: bool = False
    next_world_id: int = 1
    
    def create_world(self) -> World:
        """Create a new world and return it."""
        world = World(id=self.next_world_id)
        self.worlds[world.id] = world
        self.accessibility[world.id] = set()
        self.next_world_id += 1
        return world
    
    def add_accessibility(self, from_world: int, to_world: int) -> None:
        """Add an accessibility relation between worlds."""
        if from_world not in self.accessibility:
            self.accessibility[from_world] = set()
        self.accessibility[from_world].add(to_world)
    
    def get_accessible_worlds(self, from_world: int) -> Set[int]:
        """Get all worlds accessible from the given world."""
        return self.accessibility.get(from_world, set()).copy()
    
    def close_branch(self) -> None:
        """Mark this branch as closed (contradictory)."""
        self.is_closed = True
    
    def copy(self) -> TableauxBranch:
        """Create a deep copy of this branch."""
        new_branch = TableauxBranch(
            worlds={wid: World(id=w.id, formulas=w.formulas.copy(), negated_formulas=w.negated_formulas.copy())
                    for wid, w in self.worlds.items()},
            accessibility={k: v.copy() for k, v in self.accessibility.items()},
            current_world=self.current_world,
            is_closed=self.is_closed,
            next_world_id=self.next_world_id
        )
        return new_branch


@dataclass
class TableauxResult:
    """Result of a tableaux proof attempt."""
    is_valid: bool
    closed_branches: int
    total_branches: int
    open_branch: Optional[TableauxBranch] = None
    proof_steps: List[str] = field(default_factory=list)
    

class ModalTableaux:
    """
    Modal tableaux prover for K, T, D, S4, S5 logics.
    
    The tableaux method systematically explores possible worlds to determine
    if a modal formula is valid (true in all models) for the given logic.
    
    Usage:
        tableaux = ModalTableaux(logic_type=ModalLogicType.S4)
        result = tableaux.prove(formula)
        if result.is_valid:
            print("Formula is S4-valid!")
        else:
            print(f"Countermodel: {result.open_branch}")
    """
    
    def __init__(self, logic_type: ModalLogicType = ModalLogicType.K):
        """
        Initialize modal tableaux prover.
        
        Args:
            logic_type: The type of modal logic (K, T, D, S4, or S5)
        """
        self.logic_type = logic_type
        self.max_worlds = 100  # Prevent infinite loops
        self.max_depth = 50    # Maximum expansion depth
    
    def prove(self, formula: Formula) -> TableauxResult:
        """
        Attempt to prove a formula using modal tableaux.
        
        To check validity of φ, we try to prove ¬φ is unsatisfiable.
        If all branches close, φ is valid.
        
        Args:
            formula: The formula to prove
            
        Returns:
            TableauxResult with proof information
        """
        logger.info(f"Starting tableaux proof for {formula} in logic {self.logic_type.value}")
        
        # Start with negation of formula (check if ¬φ is unsatisfiable)
        initial_branch = TableauxBranch()
        root_world = World(id=0)
        initial_branch.worlds[0] = root_world
        initial_branch.accessibility[0] = set()
        
        # Add negated formula to root world
        root_world.add_formula(formula, negated=True)
        
        # Apply reflexivity for T, S4, S5
        if self.logic_type in {ModalLogicType.T, ModalLogicType.S4, ModalLogicType.S5}:
            initial_branch.add_accessibility(0, 0)
        
        # Expand the tableaux
        branches = [initial_branch]
        proof_steps = []
        depth = 0
        
        while depth < self.max_depth:
            depth += 1
            new_branches = []
            all_closed = True
            
            for branch in branches:
                if branch.is_closed:
                    new_branches.append(branch)
                    continue
                
                # Try to expand this branch
                expanded = self._expand_branch(branch, proof_steps)
                
                if not expanded:
                    # No more expansions possible
                    all_closed = False
                    new_branches.append(branch)
                else:
                    new_branches.extend(expanded)
            
            branches = new_branches
            
            # Check if all branches are closed
            closed_count = sum(1 for b in branches if b.is_closed)
            if closed_count == len(branches):
                return TableauxResult(
                    is_valid=True,
                    closed_branches=closed_count,
                    total_branches=len(branches),
                    proof_steps=proof_steps
                )
            
            # Check if we have stable open branches (no changes)
            if not any(self._can_expand(b) for b in branches if not b.is_closed):
                break
        
        # We have open branches - formula is not valid
        open_branch = next((b for b in branches if not b.is_closed), None)
        closed_count = sum(1 for b in branches if b.is_closed)
        
        return TableauxResult(
            is_valid=False,
            closed_branches=closed_count,
            total_branches=len(branches),
            open_branch=open_branch,
            proof_steps=proof_steps
        )
    
    def _can_expand(self, branch: TableauxBranch) -> bool:
        """Check if a branch can be expanded further."""
        if branch.is_closed:
            return False
        
        for world in branch.worlds.values():
            # Check for unexpanded formulas
            for formula in world.formulas | world.negated_formulas:
                if self._needs_expansion(formula):
                    return True
        
        return False
    
    def _needs_expansion(self, formula: Formula) -> bool:
        """Check if a formula needs expansion."""
        # Conjunctions, disjunctions, implications, modals need expansion
        if isinstance(formula, (UnaryFormula, BinaryFormula)):
            return True
        if isinstance(formula, (TemporalFormula, DeonticFormula)):
            return True
        return False
    
    def _expand_branch(self, branch: TableauxBranch, proof_steps: List[str]) -> List[TableauxBranch]:
        """
        Expand a branch by applying tableaux rules.
        
        Returns a list of new branches (may split for disjunctions).
        """
        if branch.is_closed:
            return [branch]
        
        # Find a formula to expand in any world
        for world_id, world in branch.worlds.items():
            # Check formulas (positive)
            for formula in list(world.formulas):
                result = self._expand_formula(branch, world_id, formula, negated=False, proof_steps=proof_steps)
                if result:
                    return result
            
            # Check negated formulas
            for formula in list(world.negated_formulas):
                result = self._expand_formula(branch, world_id, formula, negated=True, proof_steps=proof_steps)
                if result:
                    return result
        
        return [branch]
    
    def _expand_formula(
        self,
        branch: TableauxBranch,
        world_id: int,
        formula: Formula,
        negated: bool,
        proof_steps: List[str]
    ) -> Optional[List[TableauxBranch]]:
        """Expand a single formula, returning new branches if split occurs."""
        world = branch.worlds[world_id]
        
        # Remove formula from expansion set (mark as processed)
        if negated:
            if formula not in world.negated_formulas:
                return None
            world.negated_formulas.discard(formula)
        else:
            if formula not in world.formulas:
                return None
            world.formulas.discard(formula)
        
        # Handle different formula types
        if isinstance(formula, BinaryFormula):
            return self._expand_binary(branch, world_id, formula, negated, proof_steps)
        elif isinstance(formula, UnaryFormula):
            return self._expand_unary(branch, world_id, formula, negated, proof_steps)
        elif isinstance(formula, TemporalFormula):
            return self._expand_temporal(branch, world_id, formula, negated, proof_steps)
        elif isinstance(formula, DeonticFormula):
            return self._expand_deontic(branch, world_id, formula, negated, proof_steps)
        else:
            # Atomic formula - check for contradiction
            world.add_formula(formula, negated)
            if world.has_contradiction():
                branch.close_branch()
                proof_steps.append(f"Branch closed: contradiction at world {world_id}")
            return [branch]
    
    def _expand_binary(
        self,
        branch: TableauxBranch,
        world_id: int,
        formula: BinaryFormula,
        negated: bool,
        proof_steps: List[str]
    ) -> List[TableauxBranch]:
        """Expand binary formulas (AND, OR, IMPLIES)."""
        world = branch.worlds[world_id]
        op = formula.operator
        
        if op == LogicOperator.AND:
            if not negated:
                # φ ∧ ψ: Add both φ and ψ
                world.add_formula(formula.left, negated=False)
                world.add_formula(formula.right, negated=False)
                proof_steps.append(f"AND expansion at world {world_id}")
                return [branch]
            else:
                # ¬(φ ∧ ψ): Split into ¬φ | ¬ψ
                branch1 = branch.copy()
                branch2 = branch.copy()
                branch1.worlds[world_id].add_formula(formula.left, negated=True)
                branch2.worlds[world_id].add_formula(formula.right, negated=True)
                proof_steps.append(f"Negated AND split at world {world_id}")
                return [branch1, branch2]
        
        elif op == LogicOperator.OR:
            if not negated:
                # φ ∨ ψ: Split into φ | ψ
                branch1 = branch.copy()
                branch2 = branch.copy()
                branch1.worlds[world_id].add_formula(formula.left, negated=False)
                branch2.worlds[world_id].add_formula(formula.right, negated=False)
                proof_steps.append(f"OR split at world {world_id}")
                return [branch1, branch2]
            else:
                # ¬(φ ∨ ψ): Add both ¬φ and ¬ψ
                world.add_formula(formula.left, negated=True)
                world.add_formula(formula.right, negated=True)
                proof_steps.append(f"Negated OR expansion at world {world_id}")
                return [branch]
        
        elif op == LogicOperator.IMPLIES:
            if not negated:
                # φ → ψ: Split into ¬φ | ψ
                branch1 = branch.copy()
                branch2 = branch.copy()
                branch1.worlds[world_id].add_formula(formula.left, negated=True)
                branch2.worlds[world_id].add_formula(formula.right, negated=False)
                proof_steps.append(f"IMPLIES split at world {world_id}")
                return [branch1, branch2]
            else:
                # ¬(φ → ψ): Add φ and ¬ψ
                world.add_formula(formula.left, negated=False)
                world.add_formula(formula.right, negated=True)
                proof_steps.append(f"Negated IMPLIES expansion at world {world_id}")
                return [branch]
        
        return [branch]
    
    def _expand_unary(
        self,
        branch: TableauxBranch,
        world_id: int,
        formula: UnaryFormula,
        negated: bool,
        proof_steps: List[str]
    ) -> List[TableauxBranch]:
        """Expand unary formulas (NOT)."""
        world = branch.worlds[world_id]
        
        if formula.operator == LogicOperator.NOT:
            # ¬¬φ becomes φ
            world.add_formula(formula.operand, negated=not negated)
            proof_steps.append(f"Double negation at world {world_id}")
        
        return [branch]
    
    def _expand_temporal(
        self,
        branch: TableauxBranch,
        world_id: int,
        formula: TemporalFormula,
        negated: bool,
        proof_steps: List[str]
    ) -> List[TableauxBranch]:
        """Expand temporal formulas (□, ◊) using modal rules."""
        world = branch.worlds[world_id]
        op = formula.operator
        
        if op == TemporalOperator.ALWAYS:  # □ (box)
            if not negated:
                # □φ: Add φ to all accessible worlds
                accessible = branch.get_accessible_worlds(world_id)
                if not accessible:
                    # Create a new world if needed
                    new_world = branch.create_world()
                    branch.add_accessibility(world_id, new_world.id)
                    accessible = {new_world.id}
                
                for acc_world_id in accessible:
                    branch.worlds[acc_world_id].add_formula(formula.operand, negated=False)
                
                proof_steps.append(f"BOX expansion at world {world_id} to {len(accessible)} worlds")
            else:
                # ¬□φ: Create new accessible world with ¬φ
                new_world = branch.create_world()
                branch.add_accessibility(world_id, new_world.id)
                new_world.add_formula(formula.operand, negated=True)
                proof_steps.append(f"Negated BOX: created world {new_world.id}")
        
        elif op == TemporalOperator.EVENTUALLY:  # ◊ (diamond)
            if not negated:
                # ◊φ: Create new accessible world with φ
                new_world = branch.create_world()
                branch.add_accessibility(world_id, new_world.id)
                new_world.add_formula(formula.operand, negated=False)
                proof_steps.append(f"DIAMOND: created world {new_world.id}")
            else:
                # ¬◊φ: Add ¬φ to all accessible worlds
                accessible = branch.get_accessible_worlds(world_id)
                if not accessible:
                    new_world = branch.create_world()
                    branch.add_accessibility(world_id, new_world.id)
                    accessible = {new_world.id}
                
                for acc_world_id in accessible:
                    branch.worlds[acc_world_id].add_formula(formula.operand, negated=True)
                
                proof_steps.append(f"Negated DIAMOND expansion at world {world_id}")
        
        # Apply logic-specific rules
        self._apply_logic_constraints(branch, world_id, formula, negated, proof_steps)
        
        return [branch]
    
    def _expand_deontic(
        self,
        branch: TableauxBranch,
        world_id: int,
        formula: DeonticFormula,
        negated: bool,
        proof_steps: List[str]
    ) -> List[TableauxBranch]:
        """Expand deontic formulas (O, P, F) - treat as modal operators."""
        # Deontic logic: O (obligation), P (permission), F (forbidden)
        # O φ ≡ □φ in deontic possible worlds
        # P φ ≡ ◊φ in deontic possible worlds
        # F φ ≡ ¬P φ ≡ □¬φ
        
        world = branch.worlds[world_id]
        op = formula.operator
        
        if op == DeonticOperator.OBLIGATION:  # O
            # Similar to □ (box)
            if not negated:
                accessible = branch.get_accessible_worlds(world_id)
                if not accessible:
                    new_world = branch.create_world()
                    branch.add_accessibility(world_id, new_world.id)
                    accessible = {new_world.id}
                
                for acc_world_id in accessible:
                    branch.worlds[acc_world_id].add_formula(formula.operand, negated=False)
                
                proof_steps.append(f"OBLIGATION expansion at world {world_id}")
            else:
                new_world = branch.create_world()
                branch.add_accessibility(world_id, new_world.id)
                new_world.add_formula(formula.operand, negated=True)
                proof_steps.append(f"Negated OBLIGATION: created world {new_world.id}")
        
        elif op == DeonticOperator.PERMISSION:  # P
            # Similar to ◊ (diamond)
            if not negated:
                new_world = branch.create_world()
                branch.add_accessibility(world_id, new_world.id)
                new_world.add_formula(formula.operand, negated=False)
                proof_steps.append(f"PERMISSION: created world {new_world.id}")
            else:
                accessible = branch.get_accessible_worlds(world_id)
                if not accessible:
                    new_world = branch.create_world()
                    branch.add_accessibility(world_id, new_world.id)
                    accessible = {new_world.id}
                
                for acc_world_id in accessible:
                    branch.worlds[acc_world_id].add_formula(formula.operand, negated=True)
                
                proof_steps.append(f"Negated PERMISSION expansion at world {world_id}")
        
        elif op == DeonticOperator.FORBIDDEN:  # F
            # F φ ≡ O(¬φ) ≡ □¬φ
            if not negated:
                accessible = branch.get_accessible_worlds(world_id)
                if not accessible:
                    new_world = branch.create_world()
                    branch.add_accessibility(world_id, new_world.id)
                    accessible = {new_world.id}
                
                for acc_world_id in accessible:
                    branch.worlds[acc_world_id].add_formula(formula.operand, negated=True)
                
                proof_steps.append(f"FORBIDDEN expansion at world {world_id}")
            else:
                new_world = branch.create_world()
                branch.add_accessibility(world_id, new_world.id)
                new_world.add_formula(formula.operand, negated=False)
                proof_steps.append(f"Negated FORBIDDEN: created world {new_world.id}")
        
        return [branch]
    
    def _apply_logic_constraints(
        self,
        branch: TableauxBranch,
        world_id: int,
        formula: Formula,
        negated: bool,
        proof_steps: List[str]
    ) -> None:
        """Apply logic-specific constraints (T, D, S4, S5)."""
        
        if self.logic_type == ModalLogicType.T:
            # T: Reflexive - □φ → φ
            if isinstance(formula, TemporalFormula) and formula.operator == TemporalOperator.ALWAYS:
                if not negated:
                    # □φ implies φ at current world
                    branch.worlds[world_id].add_formula(formula.operand, negated=False)
                    proof_steps.append(f"T-reflexivity: □φ → φ at world {world_id}")
        
        elif self.logic_type == ModalLogicType.S4:
            # S4: Reflexive + Transitive - □φ → □□φ
            if isinstance(formula, TemporalFormula) and formula.operator == TemporalOperator.ALWAYS:
                if not negated:
                    # Reflexivity
                    branch.worlds[world_id].add_formula(formula.operand, negated=False)
                    # Transitivity: propagate □φ through accessible worlds
                    accessible = branch.get_accessible_worlds(world_id)
                    for acc_id in accessible:
                        # Add □φ to accessible worlds (creates transitivity)
                        branch.worlds[acc_id].add_formula(formula, negated=False)
                    proof_steps.append(f"S4-transitivity at world {world_id}")
        
        elif self.logic_type == ModalLogicType.S5:
            # S5: Equivalence relation - all worlds access each other
            # In S5, we can optimize by treating all worlds as equivalent
            if isinstance(formula, TemporalFormula):
                # Add formula to all worlds (equivalence means universal accessibility)
                for w_id in branch.worlds:
                    if isinstance(formula, TemporalFormula) and formula.operator == TemporalOperator.ALWAYS:
                        if not negated:
                            branch.worlds[w_id].add_formula(formula.operand, negated=False)
                proof_steps.append(f"S5-equivalence: formula at all worlds")


def prove_modal_formula(
    formula: Formula,
    logic_type: ModalLogicType = ModalLogicType.K
) -> TableauxResult:
    """
    Convenience function to prove a modal formula.
    
    Args:
        formula: The formula to prove
        logic_type: The modal logic to use (K, T, D, S4, S5)
        
    Returns:
        TableauxResult indicating validity
        
    Example:
        >>> from tdfol_core import parse_tdfol
        >>> formula = parse_tdfol("□P → P")  # Valid in T, S4, S5, not K
        >>> result = prove_modal_formula(formula, ModalLogicType.T)
        >>> print(result.is_valid)
        True
    """
    tableaux = ModalTableaux(logic_type=logic_type)
    return tableaux.prove(formula)
