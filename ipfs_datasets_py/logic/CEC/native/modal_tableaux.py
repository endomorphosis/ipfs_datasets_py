"""
Modal Tableaux Algorithm for ShadowProver.

This module implements tableau-based proving for modal logics.
Tableaux are a refutation-based proof method that attempts to
construct a model for the negation of the formula.
"""

from typing import List, Set, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

from .shadow_prover import (
    ProofStep, ModalLogic
)

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class NodeStatus(Enum):
    """Status of a tableau node."""
    OPEN = "open"
    CLOSED = "closed"
    SATURATED = "saturated"


@dataclass
class TableauNode:
    """A node in a modal tableau.
    
    Attributes:
        formulas: Set of formulas at this node
        world: World identifier
        status: Node status
        parent: Parent node
        children: Child nodes
        accessible_worlds: Worlds accessible from this world
    """
    formulas: Set[str]
    world: int
    status: NodeStatus = NodeStatus.OPEN
    parent: Optional['TableauNode'] = None
    children: List['TableauNode'] = field(default_factory=list)
    accessible_worlds: Set[int] = field(default_factory=set)
    expanded_formulas: Set[str] = field(default_factory=set)
    
    def add_formula(self, formula: str) -> bool:
        """Add a formula to this node.
        
        Args:
            formula: Formula to add
            
        Returns:
            True if formula was new, False if already present
        """
        if formula in self.formulas:
            return False
        self.formulas.add(formula)
        return True
    
    def is_contradictory(self) -> bool:
        """Check if node contains a contradiction.
        
        Returns:
            True if node has both P and ¬P for some P
        """
        for formula in self.formulas:
            if formula.startswith("¬"):
                positive = formula[1:]
                if positive in self.formulas:
                    return True
            else:
                negative = f"¬{formula}"
                if negative in self.formulas:
                    return True
        return False
    
    def close(self) -> None:
        """Mark this node as closed."""
        self.status = NodeStatus.CLOSED


@dataclass
class ModalTableau:
    """A modal tableau for proving formulas.
    
    Attributes:
        root: Root node of the tableau
        logic: Modal logic system
        world_counter: Counter for generating world IDs
        proof_steps: Steps taken during proof construction
    """
    root: TableauNode
    logic: ModalLogic
    world_counter: int = 0
    proof_steps: List[ProofStep] = field(default_factory=list)
    
    def is_closed(self) -> bool:
        """Check if entire tableau is closed.
        
        Returns:
            True if all branches are closed
        """
        return self._is_branch_closed(self.root)
    
    def _is_branch_closed(self, node: TableauNode) -> bool:
        """Check if a branch starting at node is closed.
        
        Args:
            node: Starting node
            
        Returns:
            True if all paths from node are closed
        """
        if node.status == NodeStatus.CLOSED:
            return True
        
        if not node.children:
            return False
        
        return all(self._is_branch_closed(child) for child in node.children)
    
    def new_world(self) -> int:
        """Generate a new world ID.
        
        Returns:
            Unique world ID
        """
        self.world_counter += 1
        return self.world_counter


class TableauProver:
    """Tableau-based prover for modal logics.
    
    Uses the tableau method to prove formulas in various modal logics.
    """
    
    def __init__(self, logic: ModalLogic):
        """Initialize tableau prover.
        
        Args:
            logic: Modal logic system to use
        """
        self.logic = logic
    
    @beartype  # type: ignore[untyped-decorator]
    def prove(self, goal: str, assumptions: Optional[List[str]] = None) -> Tuple[bool, ModalTableau]:
        """Prove a goal using tableau method.
        
        The tableau method attempts to refute ¬goal. If the refutation
        succeeds (tableau closes), the goal is proven.
        
        Args:
            goal: Formula to prove
            assumptions: Optional assumptions
            
        Returns:
            Tuple of (success, tableau)
        """
        # Initialize tableau with ¬goal
        negated_goal = self._negate(goal)
        root_formulas = {negated_goal}
        
        # Add assumptions
        if assumptions:
            root_formulas.update(assumptions)
        
        root = TableauNode(formulas=root_formulas, world=0)
        tableau = ModalTableau(root=root, logic=self.logic)
        
        # Expand tableau
        self._expand_tableau(tableau, root)
        
        # Check if tableau is closed
        success = tableau.is_closed()
        
        return success, tableau
    
    def _expand_tableau(self, tableau: ModalTableau, node: TableauNode,
                       max_depth: int = 100) -> None:
        """Expand a tableau node by applying tableau rules.
        
        Args:
            tableau: The tableau
            node: Node to expand
            max_depth: Maximum expansion depth
        """
        if max_depth <= 0:
            return
        
        # Check for contradictions
        if node.is_contradictory():
            node.close()
            return
        
        # Apply propositional rules
        if self._apply_propositional_rules(tableau, node):
            # Continue expansion after applying rules
            for child in node.children:
                self._expand_tableau(tableau, child, max_depth - 1)
            return
        
        # Apply modal rules
        if self._apply_modal_rules(tableau, node):
            for child in node.children:
                self._expand_tableau(tableau, child, max_depth - 1)
            return
        
        # Node is saturated
        node.status = NodeStatus.SATURATED
    
    def _apply_propositional_rules(self, tableau: ModalTableau, node: TableauNode) -> bool:
        """Apply propositional tableau rules.
        
        Args:
            tableau: The tableau
            node: Node to apply rules to
            
        Returns:
            True if any rule was applied
        """
        formulas = list(node.formulas)
        
        for formula in formulas:
            # Skip already-expanded formulas to prevent infinite loops
            if formula in node.expanded_formulas:
                continue

            # α-rules (conjunctions)
            if "∧" in formula:
                # P∧Q → P, Q
                parts = formula.split("∧", 1)
                if len(parts) == 2:
                    node.expanded_formulas.add(formula)
                    node.add_formula(parts[0].strip())
                    node.add_formula(parts[1].strip())
                    return True
            
            # β-rules (disjunctions)
            elif "∨" in formula:
                # P∨Q → branch into P and Q
                parts = formula.split("∨", 1)
                if len(parts) == 2:
                    node.expanded_formulas.add(formula)
                    # Children inherit parent formulas except the disjunction
                    inherited = node.formulas - {formula}
                    inherited_expanded = node.expanded_formulas.copy()
                    # Create two child nodes
                    child1 = TableauNode(
                        formulas=inherited.copy(),
                        world=node.world,
                        parent=node,
                        expanded_formulas=inherited_expanded.copy()
                    )
                    child1.add_formula(parts[0].strip())
                    
                    child2 = TableauNode(
                        formulas=inherited.copy(),
                        world=node.world,
                        parent=node,
                        expanded_formulas=inherited_expanded.copy()
                    )
                    child2.add_formula(parts[1].strip())
                    
                    node.children.extend([child1, child2])
                    return True
            
            # Double negation
            elif formula.startswith("¬¬"):
                # ¬¬P → P
                node.expanded_formulas.add(formula)
                node.add_formula(formula[2:])
                return True
        
        return False
    
    def _apply_modal_rules(self, tableau: ModalTableau, node: TableauNode) -> bool:
        """Apply modal tableau rules.
        
        Args:
            tableau: The tableau
            node: Node to apply rules to
            
        Returns:
            True if any rule was applied
        """
        formulas = list(node.formulas)
        
        for formula in formulas:
            if formula in node.expanded_formulas:
                continue

            # □-formula (necessity)
            if formula.startswith("□"):
                inner = formula[1:]
                # Create accessible world
                if not node.accessible_worlds:
                    node.expanded_formulas.add(formula)
                    new_world = tableau.new_world()
                    node.accessible_worlds.add(new_world)
                    
                    # Create child node in new world
                    child = TableauNode(
                        formulas={inner},
                        world=new_world,
                        parent=node
                    )
                    node.children.append(child)
                    return True
            
            # ◇-formula (possibility)
            elif formula.startswith("◇"):
                inner = formula[1:]
                node.expanded_formulas.add(formula)
                # Must create new accessible world
                new_world = tableau.new_world()
                node.accessible_worlds.add(new_world)
                
                child = TableauNode(
                    formulas={inner},
                    world=new_world,
                    parent=node
                )
                node.children.append(child)
                return True
        
        # Apply logic-specific rules
        if self.logic == ModalLogic.T:
            # T: □P → P (reflexivity)
            if self._apply_t_rule(node):
                return True
        
        elif self.logic == ModalLogic.S4:
            # S4: □P → P and □P → □□P
            if self._apply_s4_rules(node):
                return True
        
        elif self.logic == ModalLogic.S5:
            # S5: all worlds are mutually accessible
            if self._apply_s5_rules(node):
                return True
        
        return False
    
    def _apply_t_rule(self, node: TableauNode) -> bool:
        """Apply T axiom: □P → P.
        
        Args:
            node: Node to apply rule to
            
        Returns:
            True if rule was applied
        """
        for formula in node.formulas:
            if formula.startswith("□"):
                inner = formula[1:]
                if node.add_formula(inner):
                    return True
        return False
    
    def _apply_s4_rules(self, node: TableauNode) -> bool:
        """Apply S4 axioms.
        
        Args:
            node: Node to apply rules to
            
        Returns:
            True if any rule was applied
        """
        # First apply T rule
        if self._apply_t_rule(node):
            return True
        
        # Then apply 4 rule: □P → □□P
        for formula in node.formulas:
            if formula.startswith("□"):
                nested = f"□{formula}"
                if node.add_formula(nested):
                    return True
        
        return False
    
    def _apply_s5_rules(self, node: TableauNode) -> bool:
        """Apply S5 axioms.
        
        Args:
            node: Node to apply rules to
            
        Returns:
            True if any rule was applied
        """
        # Apply S4 rules first
        if self._apply_s4_rules(node):
            return True
        
        # Apply 5 rule: ◇P → □◇P
        for formula in node.formulas:
            if formula.startswith("◇"):
                nested = f"□{formula}"
                if node.add_formula(nested):
                    return True
        
        return False
    
    def _negate(self, formula: str) -> str:
        """Negate a formula.
        
        Args:
            formula: Formula to negate
            
        Returns:
            Negated formula
        """
        if formula.startswith("¬"):
            return formula[1:]  # Remove negation
        return f"¬{formula}"


class ResolutionProver:
    """Resolution-based prover for propositional logic.
    
    Uses resolution rule: (A∨P) ∧ (¬P∨B) → (A∨B)
    """
    
    def __init__(self) -> None:
        """Initialize resolution prover."""
        self.clauses: Set[frozenset] = set()
    
    @beartype  # type: ignore[untyped-decorator]
    def prove(self, goal: str, assumptions: Optional[List[str]] = None) -> Tuple[bool, List[ProofStep]]:
        """Prove a goal using resolution.
        
        Args:
            goal: Formula to prove (in CNF)
            assumptions: Assumptions (in CNF)
            
        Returns:
            Tuple of (success, proof_steps)
        """
        # Convert to clausal form
        self.clauses = set()
        
        # Add negated goal
        negated_goal = self._to_clauses(f"¬{goal}")
        self.clauses.update(negated_goal)
        
        # Add assumptions
        if assumptions:
            for assumption in assumptions:
                clauses = self._to_clauses(assumption)
                self.clauses.update(clauses)
        
        # Apply resolution
        proof_steps = []
        max_iterations = 1000
        
        for i in range(max_iterations):
            # Try to derive empty clause (contradiction)
            new_clauses = self._resolution_step()
            
            if frozenset() in new_clauses:
                # Empty clause derived - proof successful
                proof_steps.append(ProofStep(
                    rule_name="Resolution",
                    premises=list(self.clauses),
                    conclusion="⊥",
                    justification="Empty clause derived"
                ))
                return True, proof_steps
            
            # Add new clauses
            old_size = len(self.clauses)
            self.clauses.update(new_clauses)
            
            # If no new clauses, we're done
            if len(self.clauses) == old_size:
                break
        
        return False, proof_steps
    
    def _resolution_step(self) -> Set[frozenset]:
        """Perform one step of resolution.
        
        Returns:
            Set of newly derived clauses
        """
        new_clauses = set()
        clause_list = list(self.clauses)
        
        for i, clause1 in enumerate(clause_list):
            for clause2 in clause_list[i+1:]:
                # Try to resolve clause1 and clause2
                resolvents = self._resolve(clause1, clause2)
                new_clauses.update(resolvents)
        
        return new_clauses
    
    def _resolve(self, clause1: frozenset, clause2: frozenset) -> Set[frozenset]:
        """Resolve two clauses.
        
        Args:
            clause1: First clause
            clause2: Second clause
            
        Returns:
            Set of resolvents
        """
        resolvents = set()
        
        for lit1 in clause1:
            # Find complementary literal
            neg_lit1 = self._negate_literal(lit1)
            
            if neg_lit1 in clause2:
                # Resolve on this literal
                resolvent = (clause1 - {lit1}) | (clause2 - {neg_lit1})
                resolvents.add(frozenset(resolvent))
        
        return resolvents
    
    def _negate_literal(self, literal: str) -> str:
        """Negate a literal.
        
        Args:
            literal: Literal to negate
            
        Returns:
            Negated literal
        """
        if literal.startswith("¬"):
            return literal[1:]
        return f"¬{literal}"
    
    def _to_clauses(self, formula: str) -> Set[frozenset]:
        """Convert formula to clausal form (CNF).
        
        This is a simplified implementation. Full implementation
        would handle arbitrary formulas.
        
        Args:
            formula: Formula to convert
            
        Returns:
            Set of clauses
        """
        # Simplified: assume already in CNF or simple form
        if "∧" in formula:
            # Multiple clauses
            parts = formula.split("∧")
            clauses = set()
            for part in parts:
                clause = self._parse_clause(part.strip())
                clauses.add(frozenset(clause))
            return clauses
        else:
            # Single clause
            clause = self._parse_clause(formula)
            return {frozenset(clause)}
    
    def _parse_clause(self, clause_str: str) -> List[str]:
        """Parse a clause string.
        
        Args:
            clause_str: Clause as string
            
        Returns:
            List of literals
        """
        if "∨" in clause_str:
            return [lit.strip() for lit in clause_str.split("∨")]
        else:
            return [clause_str.strip()]


def create_tableau_prover(logic: ModalLogic) -> TableauProver:
    """Factory function to create a tableau prover.
    
    Args:
        logic: Modal logic system
        
    Returns:
        TableauProver instance
    """
    return TableauProver(logic)


def create_resolution_prover() -> ResolutionProver:
    """Factory function to create a resolution prover.
    
    Returns:
        ResolutionProver instance
    """
    return ResolutionProver()
