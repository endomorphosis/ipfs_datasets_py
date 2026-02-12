"""
Native Python 3 theorem prover for DCEC formulas.

This module provides a pure Python 3 implementation of automated
theorem proving for Deontic Cognitive Event Calculus, replacing
the Talos/SPASS-based approach.
"""

from typing import List, Set, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from abc import ABC, abstractmethod

from .dcec_core import (
    Formula,
    AtomicFormula,
    ConnectiveFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    QuantifiedFormula,
    LogicalConnective,
    Variable,
    Term,
)

try:
    from beartype import beartype
except ImportError:
    def beartype(func):
        return func

logger = logging.getLogger(__name__)


class ProofResult(Enum):
    """Result of a proof attempt."""
    PROVED = "proved"
    DISPROVED = "disproved"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    ERROR = "error"


class InferenceRule(ABC):
    """Abstract base class for inference rules."""
    
    @abstractmethod
    def name(self) -> str:
        """Get the name of this inference rule."""
        pass
    
    @abstractmethod
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if this rule can be applied to the given formulas."""
        pass
    
    @abstractmethod
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply this rule and return new formulas."""
        pass


class ModusPonens(InferenceRule):
    """Modus Ponens: From P and P→Q, derive Q."""
    
    def name(self) -> str:
        return "Modus Ponens"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have both P and P→Q
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                    if len(f2.formulas) == 2 and self._formulas_equal(f1, f2.formulas[0]):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                    if len(f2.formulas) == 2 and self._formulas_equal(f1, f2.formulas[0]):
                        # We have P and P→Q, so derive Q
                        results.append(f2.formulas[1])
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        """Simple formula equality check (can be improved)."""
        return f1.to_string() == f2.to_string()


class Simplification(InferenceRule):
    """Simplification: From P∧Q, derive P (and Q)."""
    
    def name(self) -> str:
        return "Simplification"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                # Add each conjunct
                results.extend(f.formulas)
        return results


class ConjunctionIntroduction(InferenceRule):
    """Conjunction Introduction: From P and Q, derive P∧Q."""
    
    def name(self) -> str:
        return "Conjunction Introduction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return len(formulas) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Create conjunctions of pairs of formulas
        results = []
        for i, f1 in enumerate(formulas):
            for f2 in formulas[i+1:]:
                conjunction = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
                results.append(conjunction)
        return results[:10]  # Limit to avoid explosion


@dataclass
class ProofStep:
    """Represents a single step in a proof."""
    formula: Formula
    rule: str
    premises: List[int] = field(default_factory=list)  # Indices of premises
    step_number: int = 0
    
    def __str__(self) -> str:
        premises_str = f" (from {self.premises})" if self.premises else ""
        return f"{self.step_number}. {self.formula.to_string()} [{self.rule}]{premises_str}"


@dataclass
class ProofTree:
    """Represents a complete proof."""
    goal: Formula
    axioms: List[Formula]
    steps: List[ProofStep]
    result: ProofResult
    
    def __str__(self) -> str:
        lines = [
            "Proof Tree:",
            f"Goal: {self.goal.to_string()}",
            f"Result: {self.result.value}",
            "",
            "Axioms:"
        ]
        for i, axiom in enumerate(self.axioms):
            lines.append(f"  A{i+1}. {axiom.to_string()}")
        
        lines.append("")
        lines.append("Proof:")
        for step in self.steps:
            lines.append(f"  {step}")
        
        return "\n".join(lines)


class ProofState:
    """Maintains the state during proof search."""
    
    def __init__(self, goal: Formula, axioms: List[Formula]):
        self.goal = goal
        self.axioms = axioms
        self.derived: List[Formula] = list(axioms)
        self.steps: List[ProofStep] = []
        
        # Add axioms as initial steps
        for i, axiom in enumerate(axioms):
            self.steps.append(ProofStep(
                formula=axiom,
                rule="Axiom",
                step_number=i+1
            ))
    
    def add_formula(self, formula: Formula, rule: str, premises: List[int]):
        """Add a newly derived formula."""
        self.derived.append(formula)
        step = ProofStep(
            formula=formula,
            rule=rule,
            premises=premises,
            step_number=len(self.steps) + 1
        )
        self.steps.append(step)
    
    def has_goal(self) -> bool:
        """Check if we've derived the goal."""
        goal_str = self.goal.to_string()
        return any(f.to_string() == goal_str for f in self.derived)
    
    def get_proof_tree(self, result: ProofResult) -> ProofTree:
        """Create a proof tree from current state."""
        return ProofTree(
            goal=self.goal,
            axioms=self.axioms,
            steps=self.steps,
            result=result
        )


class BasicProver:
    """
    A basic theorem prover for DCEC formulas.
    
    Uses forward chaining with a set of inference rules to
    attempt to derive the goal from the axioms.
    """
    
    def __init__(self, max_steps: int = 100):
        """
        Initialize the prover.
        
        Args:
            max_steps: Maximum number of inference steps
        """
        self.max_steps = max_steps
        self.rules: List[InferenceRule] = [
            ModusPonens(),
            Simplification(),
            ConjunctionIntroduction(),
        ]
    
    @beartype
    def prove(
        self,
        goal: Formula,
        axioms: List[Formula],
        timeout: Optional[float] = None
    ) -> ProofTree:
        """
        Attempt to prove a goal from axioms.
        
        Args:
            goal: The formula to prove
            axioms: List of axioms (assumed true)
            timeout: Optional timeout in seconds
            
        Returns:
            ProofTree with the result
        """
        logger.info(f"Attempting to prove: {goal.to_string()}")
        logger.info(f"With {len(axioms)} axiom(s)")
        
        state = ProofState(goal, axioms)
        
        # Check if goal is already in axioms
        if state.has_goal():
            logger.info("Goal is an axiom!")
            return state.get_proof_tree(ProofResult.PROVED)
        
        # Forward chaining
        for step_num in range(self.max_steps):
            # Try to apply each rule
            new_formulas = []
            
            for rule in self.rules:
                if rule.can_apply(state.derived):
                    try:
                        results = rule.apply(state.derived)
                        for result in results:
                            # Check if it's new
                            result_str = result.to_string()
                            if not any(f.to_string() == result_str for f in state.derived):
                                new_formulas.append((result, rule.name()))
                    except Exception as e:
                        logger.warning(f"Error applying {rule.name()}: {e}")
            
            # Add new formulas
            if not new_formulas:
                logger.info(f"No new formulas after {step_num+1} steps")
                break
            
            for formula, rule_name in new_formulas:
                state.add_formula(formula, rule_name, [])
                
                # Check if we've reached the goal
                if state.has_goal():
                    logger.info(f"Proof found in {step_num+1} steps!")
                    return state.get_proof_tree(ProofResult.PROVED)
        
        logger.info(f"Could not prove goal in {self.max_steps} steps")
        return state.get_proof_tree(ProofResult.UNKNOWN)
    
    @beartype
    def add_rule(self, rule: InferenceRule):
        """Add a custom inference rule."""
        self.rules.append(rule)
        logger.info(f"Added inference rule: {rule.name()}")


@dataclass
class ProofAttempt:
    """Result of a proof attempt."""
    goal: Formula
    axioms: List[Formula]
    proof_tree: Optional[ProofTree] = None
    result: ProofResult = ProofResult.UNKNOWN
    error_message: Optional[str] = None
    execution_time: float = 0.0
    
    def __str__(self) -> str:
        return f"ProofAttempt(result={self.result.value}, goal={self.goal.to_string()[:50]}...)"


class TheoremProver:
    """
    High-level interface to the theorem proving system.
    
    This class provides a clean API compatible with the TalosWrapper interface.
    """
    
    def __init__(self):
        """Initialize the theorem prover."""
        self.prover = BasicProver()
        self.proof_attempts: List[ProofAttempt] = []
        self._initialized = True
    
    def initialize(self) -> bool:
        """Initialize the prover (always succeeds for native implementation)."""
        self._initialized = True
        logger.info("Native theorem prover initialized")
        return True
    
    @beartype
    def prove_theorem(
        self,
        goal: Formula,
        axioms: Optional[List[Formula]] = None,
        timeout: Optional[float] = None
    ) -> ProofAttempt:
        """
        Prove a theorem.
        
        Args:
            goal: The formula to prove
            axioms: List of axioms (assumed true)
            timeout: Optional timeout in seconds
            
        Returns:
            ProofAttempt with results
        """
        import time
        
        axioms = axioms or []
        start_time = time.time()
        
        try:
            proof_tree = self.prover.prove(goal, axioms, timeout)
            execution_time = time.time() - start_time
            
            attempt = ProofAttempt(
                goal=goal,
                axioms=axioms,
                proof_tree=proof_tree,
                result=proof_tree.result,
                execution_time=execution_time
            )
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error during proof: {e}")
            attempt = ProofAttempt(
                goal=goal,
                axioms=axioms,
                result=ProofResult.ERROR,
                error_message=str(e),
                execution_time=execution_time
            )
        
        self.proof_attempts.append(attempt)
        return attempt
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about proof attempts."""
        if not self.proof_attempts:
            return {"total_attempts": 0}
        
        stats = {
            "total_attempts": len(self.proof_attempts),
            "proved": sum(1 for a in self.proof_attempts if a.result == ProofResult.PROVED),
            "disproved": sum(1 for a in self.proof_attempts if a.result == ProofResult.DISPROVED),
            "unknown": sum(1 for a in self.proof_attempts if a.result == ProofResult.UNKNOWN),
            "errors": sum(1 for a in self.proof_attempts if a.result == ProofResult.ERROR),
            "average_time": sum(a.execution_time for a in self.proof_attempts) / len(self.proof_attempts)
        }
        
        return stats
    
    def __repr__(self) -> str:
        return f"TheoremProver(attempts={len(self.proof_attempts)})"


class Weakening(InferenceRule):
    """Weakening: From P∧Q, derive P∨Q."""
    
    def name(self) -> str:
        return "Weakening"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                # From P∧Q derive P∨Q
                disjunction = ConnectiveFormula(LogicalConnective.OR, f.formulas)
                results.append(disjunction)
        return results


class DeMorgan(InferenceRule):
    """DeMorgan's Laws: ¬(P∧Q) ↔ (¬P∨¬Q) and ¬(P∨Q) ↔ (¬P∧¬Q)."""
    
    def name(self) -> str:
        return "DeMorgan"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective in [LogicalConnective.AND, LogicalConnective.OR]:
                        return True
            elif isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.AND, LogicalConnective.OR]:
                # Check if all sub-formulas are negations
                if all(isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.NOT for sub in f.formulas):
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            # ¬(P∧Q) → (¬P∨¬Q)
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.AND:
                        negated_parts = [ConnectiveFormula(LogicalConnective.NOT, [sub]) for sub in inner.formulas]
                        result = ConnectiveFormula(LogicalConnective.OR, negated_parts)
                        results.append(result)
                    # ¬(P∨Q) → (¬P∧¬Q)
                    elif isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.OR:
                        negated_parts = [ConnectiveFormula(LogicalConnective.NOT, [sub]) for sub in inner.formulas]
                        result = ConnectiveFormula(LogicalConnective.AND, negated_parts)
                        results.append(result)
            # (¬P∨¬Q) → ¬(P∧Q)
            elif isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if all(isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.NOT for sub in f.formulas):
                    inner_parts = [sub.formulas[0] for sub in f.formulas if len(sub.formulas) == 1]
                    inner_and = ConnectiveFormula(LogicalConnective.AND, inner_parts)
                    result = ConnectiveFormula(LogicalConnective.NOT, [inner_and])
                    results.append(result)
            # (¬P∧¬Q) → ¬(P∨Q)
            elif isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                if all(isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.NOT for sub in f.formulas):
                    inner_parts = [sub.formulas[0] for sub in f.formulas if len(sub.formulas) == 1]
                    inner_or = ConnectiveFormula(LogicalConnective.OR, inner_parts)
                    result = ConnectiveFormula(LogicalConnective.NOT, [inner_or])
                    results.append(result)
        return results


class Commutativity(InferenceRule):
    """Commutativity: P∧Q ↔ Q∧P and P∨Q ↔ Q∨P."""
    
    def name(self) -> str:
        return "Commutativity"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.AND, LogicalConnective.OR]
            and len(f.formulas) == 2
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and len(f.formulas) == 2:
                if f.connective in [LogicalConnective.AND, LogicalConnective.OR]:
                    # Swap the operands
                    swapped = ConnectiveFormula(f.connective, [f.formulas[1], f.formulas[0]])
                    results.append(swapped)
        return results


class Distribution(InferenceRule):
    """Distribution: P∨(Q∧R) ↔ (P∨Q)∧(P∨R) and P∧(Q∨R) ↔ (P∧Q)∨(P∧R)."""
    
    def name(self) -> str:
        return "Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula):
                # Check for P∨(Q∧R) pattern
                if f.connective == LogicalConnective.OR and len(f.formulas) == 2:
                    for sub in f.formulas:
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.AND:
                            return True
                # Check for P∧(Q∨R) pattern
                elif f.connective == LogicalConnective.AND and len(f.formulas) == 2:
                    for sub in f.formulas:
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.OR:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and len(f.formulas) == 2:
                # P∨(Q∧R) → (P∨Q)∧(P∨R)
                if f.connective == LogicalConnective.OR:
                    for i, sub in enumerate(f.formulas):
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.AND:
                            p = f.formulas[1-i]  # The other formula
                            q_and_r = sub.formulas
                            if len(q_and_r) >= 2:
                                distributed = [
                                    ConnectiveFormula(LogicalConnective.OR, [p, q_and_r[0]]),
                                    ConnectiveFormula(LogicalConnective.OR, [p, q_and_r[1]])
                                ]
                                result = ConnectiveFormula(LogicalConnective.AND, distributed)
                                results.append(result)
                # P∧(Q∨R) → (P∧Q)∨(P∧R)
                elif f.connective == LogicalConnective.AND:
                    for i, sub in enumerate(f.formulas):
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.OR:
                            p = f.formulas[1-i]  # The other formula
                            q_or_r = sub.formulas
                            if len(q_or_r) >= 2:
                                distributed = [
                                    ConnectiveFormula(LogicalConnective.AND, [p, q_or_r[0]]),
                                    ConnectiveFormula(LogicalConnective.AND, [p, q_or_r[1]])
                                ]
                                result = ConnectiveFormula(LogicalConnective.OR, distributed)
                                results.append(result)
        return results


class DisjunctiveSyllogism(InferenceRule):
    """Disjunctive Syllogism: From ¬P and P∨Q, derive Q."""
    
    def name(self) -> str:
        return "Disjunctive Syllogism"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have ¬P and P∨Q for some P, Q
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.NOT:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        if len(f1.formulas) == 1 and len(f2.formulas) >= 2:
                            negated = f1.formulas[0]
                            for disjunct in f2.formulas:
                                if self._formulas_equal(negated, disjunct):
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.NOT:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        if len(f1.formulas) == 1:
                            negated = f1.formulas[0]
                            # Find the negated formula in the disjunction
                            for i, disjunct in enumerate(f2.formulas):
                                if self._formulas_equal(negated, disjunct):
                                    # Derive the other disjuncts
                                    remaining = [f2.formulas[j] for j in range(len(f2.formulas)) if j != i]
                                    if len(remaining) == 1:
                                        results.append(remaining[0])
                                    elif len(remaining) > 1:
                                        results.append(ConnectiveFormula(LogicalConnective.OR, remaining))
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        """Simple formula equality check."""
        return f1.to_string() == f2.to_string()


class ImplicationElimination(InferenceRule):
    """Implication Elimination: P→Q is equivalent to ¬P∨Q."""
    
    def name(self) -> str:
        return "Implication Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # P→Q becomes ¬P∨Q
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    q = f.formulas[1]
                    result = ConnectiveFormula(LogicalConnective.OR, [not_p, q])
                    results.append(result)
        return results


class CutElimination(InferenceRule):
    """Cut Elimination (Transitivity): From P→Q and Q→R, derive P→R."""
    
    def name(self) -> str:
        return "Cut Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            # Check if consequent of f1 matches antecedent of f2
                            if self._formulas_equal(f1.formulas[1], f2.formulas[0]):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            # P→Q and Q→R gives P→R
                            if self._formulas_equal(f1.formulas[1], f2.formulas[0]):
                                result = ConnectiveFormula(LogicalConnective.IMPLIES, [f1.formulas[0], f2.formulas[1]])
                                results.append(result)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        """Simple formula equality check."""
        return f1.to_string() == f2.to_string()


class DoubleNegation(InferenceRule):
    """Double Negation: ¬¬P ↔ P."""
    
    def name(self) -> str:
        return "Double Negation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.NOT:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.NOT:
                        if len(inner.formulas) == 1:
                            # ¬¬P → P
                            results.append(inner.formulas[0])
        return results



class Contraposition(InferenceRule):
    """Contraposition: P→Q is equivalent to ¬Q→¬P."""
    
    def name(self) -> str:
        return "Contraposition"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # P→Q becomes ¬Q→¬P
                    not_q = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[1]])
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    result = ConnectiveFormula(LogicalConnective.IMPLIES, [not_q, not_p])
                    results.append(result)
        return results


class HypotheticalSyllogism(InferenceRule):
    """Hypothetical Syllogism: From (P→Q) and (Q→R), derive (P→R).
    This is similar to Cut Elimination but treated as a separate rule."""
    
    def name(self) -> str:
        return "Hypothetical Syllogism"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have two implications where consequent of first matches antecedent of second
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            if self._formulas_equal(f1.formulas[1], f2.formulas[0]):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            if self._formulas_equal(f1.formulas[1], f2.formulas[0]):
                                # (P→Q) and (Q→R) gives (P→R)
                                result = ConnectiveFormula(LogicalConnective.IMPLIES, [f1.formulas[0], f2.formulas[1]])
                                results.append(result)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class Exportation(InferenceRule):
    """Exportation: (P∧Q)→R is equivalent to P→(Q→R)."""
    
    def name(self) -> str:
        return "Exportation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # Check if antecedent is conjunction
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.AND:
                        return True
            # Also handle reverse: P→(Q→R) to (P∧Q)→R
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    if isinstance(f.formulas[1], ConnectiveFormula) and f.formulas[1].connective == LogicalConnective.IMPLIES:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # Case 1: (P∧Q)→R becomes P→(Q→R)
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.AND:
                        if len(f.formulas[0].formulas) == 2:
                            p = f.formulas[0].formulas[0]
                            q = f.formulas[0].formulas[1]
                            r = f.formulas[1]
                            inner = ConnectiveFormula(LogicalConnective.IMPLIES, [q, r])
                            result = ConnectiveFormula(LogicalConnective.IMPLIES, [p, inner])
                            results.append(result)
                    
                    # Case 2: P→(Q→R) becomes (P∧Q)→R
                    if isinstance(f.formulas[1], ConnectiveFormula) and f.formulas[1].connective == LogicalConnective.IMPLIES:
                        if len(f.formulas[1].formulas) == 2:
                            p = f.formulas[0]
                            q = f.formulas[1].formulas[0]
                            r = f.formulas[1].formulas[1]
                            conjunction = ConnectiveFormula(LogicalConnective.AND, [p, q])
                            result = ConnectiveFormula(LogicalConnective.IMPLIES, [conjunction, r])
                            results.append(result)
        return results


class Absorption(InferenceRule):
    """Absorption: P→Q is equivalent to P→(P∧Q).
    Also: P∨(P∧Q) ≡ P and P∧(P∨Q) ≡ P."""
    
    def name(self) -> str:
        return "Absorption"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            # Implication form
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                return True
            # Disjunction/conjunction forms
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                if len(f.formulas) == 2:
                    # Check if one side is simpler version of the other
                    for i in range(2):
                        other = f.formulas[1-i]
                        if isinstance(other, ConnectiveFormula):
                            if any(self._formulas_equal(f.formulas[i], sub) for sub in other.formulas):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            # P→Q becomes P→(P∧Q)
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    p = f.formulas[0]
                    q = f.formulas[1]
                    conjunction = ConnectiveFormula(LogicalConnective.AND, [p, q])
                    result = ConnectiveFormula(LogicalConnective.IMPLIES, [p, conjunction])
                    results.append(result)
            
            # P∨(P∧Q) becomes P
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if len(f.formulas) == 2:
                    for i in range(2):
                        p = f.formulas[i]
                        other = f.formulas[1-i]
                        if isinstance(other, ConnectiveFormula) and other.connective == LogicalConnective.AND:
                            if any(self._formulas_equal(p, sub) for sub in other.formulas):
                                results.append(p)
            
            # P∧(P∨Q) becomes P
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                if len(f.formulas) == 2:
                    for i in range(2):
                        p = f.formulas[i]
                        other = f.formulas[1-i]
                        if isinstance(other, ConnectiveFormula) and other.connective == LogicalConnective.OR:
                            if any(self._formulas_equal(p, sub) for sub in other.formulas):
                                results.append(p)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class Association(InferenceRule):
    """Association: (P∨Q)∨R ≡ P∨(Q∨R) and (P∧Q)∧R ≡ P∧(Q∧R)."""
    
    def name(self) -> str:
        return "Association"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                # Check if we have nested same operator
                for sub in f.formulas:
                    if isinstance(sub, ConnectiveFormula) and sub.connective == f.connective:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                # Re-associate: flatten and rebuild differently
                if len(f.formulas) >= 2:
                    # Collect all formulas at this level
                    collected = []
                    for sub in f.formulas:
                        if isinstance(sub, ConnectiveFormula) and sub.connective == f.connective:
                            collected.extend(sub.formulas)
                        else:
                            collected.append(sub)
                    
                    # Rebuild with different grouping
                    if len(collected) >= 3:
                        # Create (first, (rest...))
                        if len(collected[1:]) == 1:
                            inner = collected[1]
                        else:
                            inner = ConnectiveFormula(f.connective, collected[1:])
                        result = ConnectiveFormula(f.connective, [collected[0], inner])
                        results.append(result)
        return results


class Resolution(InferenceRule):
    """Resolution: From (P∨Q) and (¬P∨R), derive (Q∨R)."""
    
    def name(self) -> str:
        return "Resolution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have two disjunctions where one literal is negated in the other
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.OR:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        # Check for complementary literals
                        for lit1 in f1.formulas:
                            for lit2 in f2.formulas:
                                if self._are_complementary(lit1, lit2):
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.OR:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        # Find complementary literals
                        for i, lit1 in enumerate(f1.formulas):
                            for j, lit2 in enumerate(f2.formulas):
                                if self._are_complementary(lit1, lit2):
                                    # Resolve
                                    remaining1 = [f1.formulas[k] for k in range(len(f1.formulas)) if k != i]
                                    remaining2 = [f2.formulas[k] for k in range(len(f2.formulas)) if k != j]
                                    all_remaining = remaining1 + remaining2
                                    
                                    if len(all_remaining) == 0:
                                        # Contradiction resolved to empty clause (skip)
                                        continue
                                    elif len(all_remaining) == 1:
                                        results.append(all_remaining[0])
                                    else:
                                        result = ConnectiveFormula(LogicalConnective.OR, all_remaining)
                                        results.append(result)
        return results
    
    def _are_complementary(self, f1: Formula, f2: Formula) -> bool:
        """Check if two formulas are complementary (P and ¬P)."""
        # Check if f1 is ¬f2
        if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.NOT:
            if len(f1.formulas) == 1:
                return self._formulas_equal(f1.formulas[0], f2)
        # Check if f2 is ¬f1
        if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.NOT:
            if len(f2.formulas) == 1:
                return self._formulas_equal(f2.formulas[0], f1)
        return False
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class Transposition(InferenceRule):
    """Transposition: (P→Q) is equivalent to (¬Q→¬P).
    This is the same as Contraposition but named differently in some systems."""
    
    def name(self) -> str:
        return "Transposition"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # P→Q becomes ¬Q→¬P
                    not_q = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[1]])
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    result = ConnectiveFormula(LogicalConnective.IMPLIES, [not_q, not_p])
                    results.append(result)
        return results


class MaterialImplication(InferenceRule):
    """Material Implication: P→Q is equivalent to ¬P∨Q.
    This is the same as Implication Elimination."""
    
    def name(self) -> str:
        return "Material Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            # Forward: P→Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                return True
            # Reverse: ¬P∨Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if len(f.formulas) == 2:
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.NOT:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            # P→Q becomes ¬P∨Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    q = f.formulas[1]
                    result = ConnectiveFormula(LogicalConnective.OR, [not_p, q])
                    results.append(result)
            
            # ¬P∨Q becomes P→Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if len(f.formulas) == 2:
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.NOT:
                        if len(f.formulas[0].formulas) == 1:
                            p = f.formulas[0].formulas[0]
                            q = f.formulas[1]
                            result = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
                            results.append(result)
        return results


class ClaviusLaw(InferenceRule):
    """Clavius Law: (¬P→P) → P (if not-P implies P, then P must be true)."""
    
    def name(self) -> str:
        return "Clavius Law"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # Check if antecedent is ¬P and consequent is P
                    ant = f.formulas[0]
                    cons = f.formulas[1]
                    if isinstance(ant, ConnectiveFormula) and ant.connective == LogicalConnective.NOT:
                        if len(ant.formulas) == 1:
                            if self._formulas_equal(ant.formulas[0], cons):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    ant = f.formulas[0]
                    cons = f.formulas[1]
                    if isinstance(ant, ConnectiveFormula) and ant.connective == LogicalConnective.NOT:
                        if len(ant.formulas) == 1:
                            if self._formulas_equal(ant.formulas[0], cons):
                                # (¬P→P) gives P
                                results.append(cons)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class Idempotence(InferenceRule):
    """Idempotence: P∨P ≡ P and P∧P ≡ P."""
    
    def name(self) -> str:
        return "Idempotence"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                if len(f.formulas) >= 2:
                    # Check if all subformulas are the same
                    first = f.formulas[0].to_string()
                    if all(sub.to_string() == first for sub in f.formulas[1:]):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                if len(f.formulas) >= 2:
                    first = f.formulas[0].to_string()
                    if all(sub.to_string() == first for sub in f.formulas[1:]):
                        # P∨P... or P∧P... becomes P
                        results.append(f.formulas[0])
        return results


class BiconditionalIntroduction(InferenceRule):
    """Biconditional Introduction: From (P→Q) and (Q→P), derive (P↔Q)."""
    
    def name(self) -> str:
        return "Biconditional Introduction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for two implications that are converses
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            # Check if f1 is P→Q and f2 is Q→P
                            if (self._formulas_equal(f1.formulas[0], f2.formulas[1]) and
                                self._formulas_equal(f1.formulas[1], f2.formulas[0])):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            if (self._formulas_equal(f1.formulas[0], f2.formulas[1]) and
                                self._formulas_equal(f1.formulas[1], f2.formulas[0])):
                                # (P→Q) and (Q→P) gives (P↔Q)
                                result = ConnectiveFormula(LogicalConnective.BICONDITIONAL, 
                                                          [f1.formulas[0], f1.formulas[1]])
                                results.append(result)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class BiconditionalElimination(InferenceRule):
    """Biconditional Elimination: From (P↔Q), derive (P→Q) and (Q→P)."""
    
    def name(self) -> str:
        return "Biconditional Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.BICONDITIONAL
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.BICONDITIONAL:
                if len(f.formulas) == 2:
                    # (P↔Q) gives (P→Q) and (Q→P)
                    impl1 = ConnectiveFormula(LogicalConnective.IMPLIES, [f.formulas[0], f.formulas[1]])
                    impl2 = ConnectiveFormula(LogicalConnective.IMPLIES, [f.formulas[1], f.formulas[0]])
                    results.extend([impl1, impl2])
        return results


class ConstructiveDilemma(InferenceRule):
    """Constructive Dilemma: From (P→Q), (R→S), and (P∨R), derive (Q∨S)."""
    
    def name(self) -> str:
        return "Constructive Dilemma"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have two implications and a disjunction matching their antecedents
        has_disjunction = False
        has_implications = 0
        
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                has_disjunction = True
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                has_implications += 1
        
        return has_disjunction and has_implications >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        
        # Find implications and disjunctions
        implications = [f for f in formulas 
                       if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        disjunctions = [f for f in formulas
                       if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR]
        
        for disj in disjunctions:
            if len(disj.formulas) == 2:
                p_or_r = disj.formulas
                
                # Find matching implications
                for i, impl1 in enumerate(implications):
                    for impl2 in implications[i+1:]:
                        if len(impl1.formulas) == 2 and len(impl2.formulas) == 2:
                            # Check if antecedents match the disjunction
                            if ((self._formulas_equal(impl1.formulas[0], p_or_r[0]) and
                                 self._formulas_equal(impl2.formulas[0], p_or_r[1])) or
                                (self._formulas_equal(impl1.formulas[0], p_or_r[1]) and
                                 self._formulas_equal(impl2.formulas[0], p_or_r[0]))):
                                # Create Q∨S
                                result = ConnectiveFormula(LogicalConnective.OR,
                                                          [impl1.formulas[1], impl2.formulas[1]])
                                results.append(result)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class DestructiveDilemma(InferenceRule):
    """Destructive Dilemma: From (P→Q), (R→S), and (¬Q∨¬S), derive (¬P∨¬R)."""
    
    def name(self) -> str:
        return "Destructive Dilemma"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have two implications and a disjunction of negations
        has_neg_disjunction = False
        has_implications = 0
        
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                # Check if disjuncts are negations
                if len(f.formulas) == 2:
                    if (isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.NOT and
                        isinstance(f.formulas[1], ConnectiveFormula) and f.formulas[1].connective == LogicalConnective.NOT):
                        has_neg_disjunction = True
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                has_implications += 1
        
        return has_neg_disjunction and has_implications >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        
        implications = [f for f in formulas
                       if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        
        for disj in formulas:
            if isinstance(disj, ConnectiveFormula) and disj.connective == LogicalConnective.OR:
                if len(disj.formulas) == 2:
                    if (isinstance(disj.formulas[0], ConnectiveFormula) and disj.formulas[0].connective == LogicalConnective.NOT and
                        isinstance(disj.formulas[1], ConnectiveFormula) and disj.formulas[1].connective == LogicalConnective.NOT):
                        
                        neg_q = disj.formulas[0]
                        neg_s = disj.formulas[1]
                        
                        if len(neg_q.formulas) == 1 and len(neg_s.formulas) == 1:
                            q = neg_q.formulas[0]
                            s = neg_s.formulas[0]
                            
                            # Find matching implications
                            for i, impl1 in enumerate(implications):
                                for impl2 in implications[i+1:]:
                                    if len(impl1.formulas) == 2 and len(impl2.formulas) == 2:
                                        if ((self._formulas_equal(impl1.formulas[1], q) and
                                             self._formulas_equal(impl2.formulas[1], s)) or
                                            (self._formulas_equal(impl1.formulas[1], s) and
                                             self._formulas_equal(impl2.formulas[1], q))):
                                            # Create ¬P∨¬R
                                            not_p = ConnectiveFormula(LogicalConnective.NOT, [impl1.formulas[0]])
                                            not_r = ConnectiveFormula(LogicalConnective.NOT, [impl2.formulas[0]])
                                            result = ConnectiveFormula(LogicalConnective.OR, [not_p, not_r])
                                            results.append(result)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class TautologyIntroduction(InferenceRule):
    """Tautology Introduction: From P, derive P∨¬P (law of excluded middle)."""
    
    def name(self) -> str:
        return "Tautology Introduction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Can always introduce a tautology
        return len(formulas) > 0
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            # For any P, add P∨¬P
            not_f = ConnectiveFormula(LogicalConnective.NOT, [f])
            tautology = ConnectiveFormula(LogicalConnective.OR, [f, not_f])
            results.append(tautology)
        return results[:1]  # Just return one tautology to avoid explosion


class ContradictionElimination(InferenceRule):
    """Contradiction Elimination (Ex Falso Quodlibet): From P∧¬P, derive any Q."""
    
    def name(self) -> str:
        return "Contradiction Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for contradictions P and ¬P
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.NOT:
                    if len(f2.formulas) == 1:
                        if self._formulas_equal(f1, f2.formulas[0]):
                            return True
        
        # Also check for explicit P∧¬P
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                for i, sub1 in enumerate(f.formulas):
                    for sub2 in f.formulas[i+1:]:
                        if isinstance(sub2, ConnectiveFormula) and sub2.connective == LogicalConnective.NOT:
                            if len(sub2.formulas) == 1:
                                if self._formulas_equal(sub1, sub2.formulas[0]):
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # If we have a contradiction, we could derive anything
        # For practical purposes, just return an empty list or a marker
        # In a real system, this would be handled by the proof strategy
        return []
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class ConjunctionElimination(InferenceRule):
    """Conjunction Elimination: From P∧Q, derive both P and Q separately.
    This is similar to Simplification but explicitly derives both."""
    
    def name(self) -> str:
        return "Conjunction Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                # Return all conjuncts
                results.extend(f.formulas)
        return results
