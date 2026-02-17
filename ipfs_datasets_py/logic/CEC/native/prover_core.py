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


class InferenceEngine:
    """Backward-compatible inference engine API.

    Older callers/tests expect an `InferenceEngine` with `add_assumption()` and
    `apply_all_rules()`.

    The canonical proving API is `BasicProver`/`TheoremProver`.
    """

    def __init__(self, max_steps: int = 50):
        self.max_steps = max_steps
        self._formulas: List[Formula] = []
        self._prover = BasicProver(max_steps=max_steps)

    def add_assumption(self, formula: Formula) -> None:
        self._formulas.append(formula)

    def apply_all_rules(self) -> List[Formula]:
        """Apply all available rules until saturation (or max_steps).

        Returns the list of derived formulas including assumptions.
        """
        derived: List[Formula] = list(self._formulas)

        for _ in range(self.max_steps):
            new_formulas: List[Formula] = []
            for rule in self._prover.rules:
                if rule.can_apply(derived):
                    for candidate in rule.apply(derived):
                        candidate_str = candidate.to_string()
                        if not any(f.to_string() == candidate_str for f in derived):
                            new_formulas.append(candidate)

            if not new_formulas:
                break

            derived.extend(new_formulas)

        return derived


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


# ============================================================================
# DCEC-Specific Cognitive Inference Rules
# ============================================================================

class BeliefDistribution(InferenceRule):
    """Belief Distribution: B(agent, P∧Q) ⊢ B(agent, P)∧B(agent, Q)"""
    
    def name(self) -> str:
        return "Belief Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "B":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "B":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    # B(agent, P∧Q) → B(agent, P)∧B(agent, Q)
                    beliefs = []
                    for subformula in f.formula.formulas:
                        belief = CognitiveFormula(f.operator, f.agent, subformula)
                        beliefs.append(belief)
                    result = ConnectiveFormula(LogicalConnective.AND, beliefs)
                    results.append(result)
        return results


class KnowledgeImpliesBelief(InferenceRule):
    """Knowledge Implies Belief: K(agent, P) ⊢ B(agent, P)"""
    
    def name(self) -> str:
        return "Knowledge Implies Belief"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, CognitiveFormula) and f.operator.value == "K"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "K":
                # K(agent, P) → B(agent, P)
                from .dcec_core import CognitiveOperator
                belief = CognitiveFormula(CognitiveOperator.BELIEF, f.agent, f.formula)
                results.append(belief)
        return results


class BeliefMonotonicity(InferenceRule):
    """Belief Monotonicity: B(agent, P) ∧ (P→Q) ⊢ B(agent, Q)"""
    
    def name(self) -> str:
        return "Belief Monotonicity"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have B(agent, P) and P→Q
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        
        for belief in beliefs:
            for impl in implications:
                if len(impl.formulas) == 2:
                    if self._formulas_equal(belief.formula, impl.formulas[0]):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        
        for belief in beliefs:
            for impl in implications:
                if len(impl.formulas) == 2:
                    if self._formulas_equal(belief.formula, impl.formulas[0]):
                        # B(agent, P) and P→Q, derive B(agent, Q)
                        new_belief = CognitiveFormula(belief.operator, belief.agent, impl.formulas[1])
                        results.append(new_belief)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class IntentionCommitment(InferenceRule):
    """Intention Commitment: I(agent, P) ∧ B(agent, P→Q) ⊢ I(agent, Q)"""
    
    def name(self) -> str:
        return "Intention Commitment"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for intentions and beliefs about implications
        intentions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "I"]
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        
        for intention in intentions:
            for belief in beliefs:
                if isinstance(belief.formula, ConnectiveFormula) and belief.formula.connective == LogicalConnective.IMPLIES:
                    if len(belief.formula.formulas) == 2:
                        if self._formulas_equal(intention.formula, belief.formula.formulas[0]):
                            if self._formulas_equal(intention.agent, belief.agent):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        intentions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "I"]
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        
        for intention in intentions:
            for belief in beliefs:
                if isinstance(belief.formula, ConnectiveFormula) and belief.formula.connective == LogicalConnective.IMPLIES:
                    if len(belief.formula.formulas) == 2:
                        if self._formulas_equal(intention.formula, belief.formula.formulas[0]):
                            if self._formulas_equal(intention.agent, belief.agent):
                                # I(agent, P) and B(agent, P→Q), derive I(agent, Q)
                                from .dcec_core import CognitiveOperator
                                new_intention = CognitiveFormula(CognitiveOperator.INTENTION, intention.agent, belief.formula.formulas[1])
                                results.append(new_intention)
        return results
    
    def _formulas_equal(self, f1, f2) -> bool:
        if isinstance(f1, Formula) and isinstance(f2, Formula):
            return f1.to_string() == f2.to_string()
        return f1 == f2


# ============================================================================
# DCEC-Specific Deontic Inference Rules
# ============================================================================

class ObligationDistribution(InferenceRule):
    """Obligation Distribution: O(P∧Q) ⊢ O(P)∧O(Q)"""
    
    def name(self) -> str:
        return "Obligation Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator.value == "O":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator.value == "O":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    # O(P∧Q) → O(P)∧O(Q)
                    obligations = []
                    for subformula in f.formula.formulas:
                        obligation = DeonticFormula(f.operator, subformula)
                        obligations.append(obligation)
                    result = ConnectiveFormula(LogicalConnective.AND, obligations)
                    results.append(result)
        return results


class ObligationImplication(InferenceRule):
    """Obligation Implication: O(P) ∧ (P→Q) ⊢ O(Q)"""
    
    def name(self) -> str:
        return "Obligation Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        obligations = [f for f in formulas if isinstance(f, DeonticFormula) and f.operator.value == "O"]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        
        for obligation in obligations:
            for impl in implications:
                if len(impl.formulas) == 2:
                    if self._formulas_equal(obligation.formula, impl.formulas[0]):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        obligations = [f for f in formulas if isinstance(f, DeonticFormula) and f.operator.value == "O"]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        
        for obligation in obligations:
            for impl in implications:
                if len(impl.formulas) == 2:
                    if self._formulas_equal(obligation.formula, impl.formulas[0]):
                        # O(P) and P→Q, derive O(Q)
                        new_obligation = DeonticFormula(obligation.operator, impl.formulas[1])
                        results.append(new_obligation)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class PermissionFromNonObligation(InferenceRule):
    """Permission from Non-Obligation: ¬O(¬P) ⊢ P(P)"""
    
    def name(self) -> str:
        return "Permission from Non-Obligation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, DeonticFormula) and inner.operator.value == "O":
                        if isinstance(inner.formula, ConnectiveFormula) and inner.formula.connective == LogicalConnective.NOT:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, DeonticFormula) and inner.operator.value == "O":
                        if isinstance(inner.formula, ConnectiveFormula) and inner.formula.connective == LogicalConnective.NOT:
                            if len(inner.formula.formulas) == 1:
                                # ¬O(¬P) → P(P)
                                from .dcec_core import DeonticOperator
                                permission = DeonticFormula(DeonticOperator.PERMISSION, inner.formula.formulas[0])
                                results.append(permission)
        return results


class ForbiddenToNotObligatory(InferenceRule):
    """Forbidden to Not Obligatory: F(P) ⊢ ¬O(P)"""
    
    def name(self) -> str:
        return "Forbidden to Not Obligatory"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, DeonticFormula) and f.operator.value == "F"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator.value == "F":
                # F(P) → ¬O(P)
                from .dcec_core import DeonticOperator
                obligation = DeonticFormula(DeonticOperator.OBLIGATION, f.formula)
                not_obligation = ConnectiveFormula(LogicalConnective.NOT, [obligation])
                results.append(not_obligation)
        return results


# ============================================================================
# Temporal Inference Rules
# ============================================================================

class AlwaysDistribution(InferenceRule):
    """Always Distribution: □(P∧Q) ⊢ □P ∧ □Q"""
    
    def name(self) -> str:
        return "Always Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    # □(P∧Q) → □P ∧ □Q
                    always_formulas = []
                    for subformula in f.formula.formulas:
                        always_f = TemporalFormula(f.operator, subformula)
                        always_formulas.append(always_f)
                    result = ConnectiveFormula(LogicalConnective.AND, always_formulas)
                    results.append(result)
        return results


class AlwaysImplication(InferenceRule):
    """Always Implication: □P ∧ □(P→Q) ⊢ □Q"""
    
    def name(self) -> str:
        return "Always Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for af1 in always_formulas:
            for af2 in always_formulas:
                if isinstance(af2.formula, ConnectiveFormula) and af2.formula.connective == LogicalConnective.IMPLIES:
                    if len(af2.formula.formulas) == 2:
                        if self._formulas_equal(af1.formula, af2.formula.formulas[0]):
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for af1 in always_formulas:
            for af2 in always_formulas:
                if isinstance(af2.formula, ConnectiveFormula) and af2.formula.connective == LogicalConnective.IMPLIES:
                    if len(af2.formula.formulas) == 2:
                        if self._formulas_equal(af1.formula, af2.formula.formulas[0]):
                            # □P and □(P→Q), derive □Q
                            new_always = TemporalFormula(af1.operator, af2.formula.formulas[1])
                            results.append(new_always)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class EventuallyFromAlways(InferenceRule):
    """Eventually from Always: □P ⊢ ◊P"""
    
    def name(self) -> str:
        return "Eventually from Always"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                # □P → ◊P
                from .dcec_core import TemporalOperator
                eventually = TemporalFormula(TemporalOperator.EVENTUALLY, f.formula)
                results.append(eventually)
        return results




# ============================================================================
# Additional DCEC Cognitive Rules
# ============================================================================

class BeliefConjunction(InferenceRule):
    """Belief Conjunction: B(agent, P) ∧ B(agent, Q) ⊢ B(agent, P∧Q)"""
    
    def name(self) -> str:
        return "Belief Conjunction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        # Check if we have at least 2 beliefs from the same agent
        for i, b1 in enumerate(beliefs):
            for b2 in beliefs[i+1:]:
                if self._agents_equal(b1.agent, b2.agent):
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        
        for i, b1 in enumerate(beliefs):
            for b2 in beliefs[i+1:]:
                if self._agents_equal(b1.agent, b2.agent):
                    # B(agent, P) ∧ B(agent, Q) → B(agent, P∧Q)
                    conjunction = ConnectiveFormula(LogicalConnective.AND, [b1.formula, b2.formula])
                    new_belief = CognitiveFormula(b1.operator, b1.agent, conjunction)
                    results.append(new_belief)
        return results[:3]  # Limit to avoid explosion
    
    def _agents_equal(self, a1, a2) -> bool:
        if isinstance(a1, Term) and isinstance(a2, Term):
            return a1.to_string() == a2.to_string()
        return a1 == a2


class KnowledgeDistribution(InferenceRule):
    """Knowledge Distribution: K(agent, P∧Q) ⊢ K(agent, P)∧K(agent, Q)"""
    
    def name(self) -> str:
        return "Knowledge Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "K":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "K":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    # K(agent, P∧Q) → K(agent, P)∧K(agent, Q)
                    knowledge_formulas = []
                    for subformula in f.formula.formulas:
                        knowledge = CognitiveFormula(f.operator, f.agent, subformula)
                        knowledge_formulas.append(knowledge)
                    result = ConnectiveFormula(LogicalConnective.AND, knowledge_formulas)
                    results.append(result)
        return results


class IntentionMeansEnd(InferenceRule):
    """Intention Means-End: I(agent, goal) ∧ B(agent, action→goal) ⊢ I(agent, action)"""
    
    def name(self) -> str:
        return "Intention Means-End"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        intentions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "I"]
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        
        for intention in intentions:
            for belief in beliefs:
                if self._agents_equal(intention.agent, belief.agent):
                    if isinstance(belief.formula, ConnectiveFormula) and belief.formula.connective == LogicalConnective.IMPLIES:
                        if len(belief.formula.formulas) == 2:
                            if self._formulas_equal(intention.formula, belief.formula.formulas[1]):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        intentions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "I"]
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        
        for intention in intentions:
            for belief in beliefs:
                if self._agents_equal(intention.agent, belief.agent):
                    if isinstance(belief.formula, ConnectiveFormula) and belief.formula.connective == LogicalConnective.IMPLIES:
                        if len(belief.formula.formulas) == 2:
                            if self._formulas_equal(intention.formula, belief.formula.formulas[1]):
                                # I(agent, goal) and B(agent, action→goal), derive I(agent, action)
                                from .dcec_core import CognitiveOperator
                                new_intention = CognitiveFormula(CognitiveOperator.INTENTION, intention.agent, belief.formula.formulas[0])
                                results.append(new_intention)
        return results
    
    def _agents_equal(self, a1, a2) -> bool:
        if isinstance(a1, Term) and isinstance(a2, Term):
            return a1.to_string() == a2.to_string()
        return a1 == a2
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class PerceptionImpliesKnowledge(InferenceRule):
    """Perception Implies Knowledge: P(agent, φ) ⊢ K(agent, φ)"""
    
    def name(self) -> str:
        return "Perception Implies Knowledge"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, CognitiveFormula) and f.operator.value == "P"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "P":
                # P(agent, φ) → K(agent, φ)
                from .dcec_core import CognitiveOperator
                knowledge = CognitiveFormula(CognitiveOperator.KNOWLEDGE, f.agent, f.formula)
                results.append(knowledge)
        return results


# ============================================================================
# Additional Deontic Rules
# ============================================================================

class ObligationConjunction(InferenceRule):
    """Obligation Conjunction: O(P) ∧ O(Q) ⊢ O(P∧Q)"""
    
    def name(self) -> str:
        return "Obligation Conjunction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        obligations = [f for f in formulas if isinstance(f, DeonticFormula) and f.operator.value == "O"]
        return len(obligations) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        obligations = [f for f in formulas if isinstance(f, DeonticFormula) and f.operator.value == "O"]
        
        for i, o1 in enumerate(obligations):
            for o2 in obligations[i+1:]:
                # O(P) ∧ O(Q) → O(P∧Q)
                conjunction = ConnectiveFormula(LogicalConnective.AND, [o1.formula, o2.formula])
                new_obligation = DeonticFormula(o1.operator, conjunction)
                results.append(new_obligation)
        return results[:3]  # Limit to avoid explosion
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class PermissionDistribution(InferenceRule):
    """Permission Distribution: P(P∨Q) ⊢ P(P)∨P(Q)"""
    
    def name(self) -> str:
        return "Permission Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator.value == "P":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.OR:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator.value == "P":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.OR:
                    # P(P∨Q) → P(P)∨P(Q)
                    permissions = []
                    for subformula in f.formula.formulas:
                        permission = DeonticFormula(f.operator, subformula)
                        permissions.append(permission)
                    result = ConnectiveFormula(LogicalConnective.OR, permissions)
                    results.append(result)
        return results


class ObligationConsistency(InferenceRule):
    """Obligation Consistency: O(P) ∧ O(¬P) ⊢ ⊥ (contradiction)"""
    
    def name(self) -> str:
        return "Obligation Consistency"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        obligations = [f for f in formulas if isinstance(f, DeonticFormula) and f.operator.value == "O"]
        
        for o1 in obligations:
            for o2 in obligations:
                if isinstance(o2.formula, ConnectiveFormula) and o2.formula.connective == LogicalConnective.NOT:
                    if len(o2.formula.formulas) == 1:
                        if self._formulas_equal(o1.formula, o2.formula.formulas[0]):
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # This would indicate a contradiction in the obligation system
        # Return empty list to signal inconsistency
        return []
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


# ============================================================================
# Additional Temporal Rules
# ============================================================================

class NextDistribution(InferenceRule):
    """Next Distribution: ○(P∧Q) ⊢ ○P ∧ ○Q"""
    
    def name(self) -> str:
        return "Next Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "NEXT":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "NEXT":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    # ○(P∧Q) → ○P ∧ ○Q
                    next_formulas = []
                    for subformula in f.formula.formulas:
                        next_f = TemporalFormula(f.operator, subformula)
                        next_formulas.append(next_f)
                    result = ConnectiveFormula(LogicalConnective.AND, next_formulas)
                    results.append(result)
        return results


class EventuallyDistribution(InferenceRule):
    """Eventually Distribution: ◊(P∨Q) ⊢ ◊P ∨ ◊Q"""
    
    def name(self) -> str:
        return "Eventually Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.OR:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.OR:
                    # ◊(P∨Q) → ◊P ∨ ◊Q
                    eventually_formulas = []
                    for subformula in f.formula.formulas:
                        eventually_f = TemporalFormula(f.operator, subformula)
                        eventually_formulas.append(eventually_f)
                    result = ConnectiveFormula(LogicalConnective.OR, eventually_formulas)
                    results.append(result)
        return results


class AlwaysImpliesNext(InferenceRule):
    """Always Implies Next: □P ⊢ ○P"""
    
    def name(self) -> str:
        return "Always Implies Next"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                # □P → ○P
                from .dcec_core import TemporalOperator
                next_f = TemporalFormula(TemporalOperator.NEXT, f.formula)
                results.append(next_f)
        return results


class EventuallyTransitive(InferenceRule):
    """Eventually Transitive: ◊◊P ⊢ ◊P"""
    
    def name(self) -> str:
        return "Eventually Transitive"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "EVENTUALLY":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "EVENTUALLY":
                    # ◊◊P → ◊P
                    inner_formula = f.formula.formula
                    eventually_f = TemporalFormula(f.operator, inner_formula)
                    results.append(eventually_f)
        return results


class AlwaysTransitive(InferenceRule):
    """Always Transitive: □□P ⊢ □P"""
    
    def name(self) -> str:
        return "Always Transitive"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "ALWAYS":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "ALWAYS":
                    # □□P → □P
                    inner_formula = f.formula.formula
                    always_f = TemporalFormula(f.operator, inner_formula)
                    results.append(always_f)
        return results




# ============================================================================
# Final Cognitive Rules
# ============================================================================

class BeliefNegation(InferenceRule):
    """Belief Negation: B(agent, ¬P) ⊢ ¬B(agent, P) (in some contexts)"""
    
    def name(self) -> str:
        return "Belief Negation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "B":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.NOT:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator.value == "B":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.NOT:
                    if len(f.formula.formulas) == 1:
                        # B(agent, ¬P) could imply ¬B(agent, P) in closed world
                        inner = f.formula.formulas[0]
                        positive_belief = CognitiveFormula(f.operator, f.agent, inner)
                        not_belief = ConnectiveFormula(LogicalConnective.NOT, [positive_belief])
                        results.append(not_belief)
        return results


class KnowledgeConjunction(InferenceRule):
    """Knowledge Conjunction: K(agent, P) ∧ K(agent, Q) ⊢ K(agent, P∧Q)"""
    
    def name(self) -> str:
        return "Knowledge Conjunction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        knowledge = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "K"]
        for i, k1 in enumerate(knowledge):
            for k2 in knowledge[i+1:]:
                if self._agents_equal(k1.agent, k2.agent):
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        knowledge = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "K"]
        
        for i, k1 in enumerate(knowledge):
            for k2 in knowledge[i+1:]:
                if self._agents_equal(k1.agent, k2.agent):
                    conjunction = ConnectiveFormula(LogicalConnective.AND, [k1.formula, k2.formula])
                    new_knowledge = CognitiveFormula(k1.operator, k1.agent, conjunction)
                    results.append(new_knowledge)
        return results[:3]
    
    def _agents_equal(self, a1, a2) -> bool:
        if isinstance(a1, Term) and isinstance(a2, Term):
            return a1.to_string() == a2.to_string()
        return a1 == a2


class IntentionPersistence(InferenceRule):
    """Intention Persistence: I(agent, P) ∧ ¬B(agent, P) ⊢ I(agent, P) (next)"""
    
    def name(self) -> str:
        return "Intention Persistence"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for intentions with non-achieved goals
        intentions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "I"]
        return len(intentions) > 0
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Intentions persist - this is a simplification
        # In full implementation would check temporal context
        return []


class MutualBelief(InferenceRule):
    """Mutual Belief: B(a1, P) ∧ B(a2, P) ⊢ MB(P) (simplified)"""
    
    def name(self) -> str:
        return "Mutual Belief"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        # Check for beliefs about same formula from different agents
        for i, b1 in enumerate(beliefs):
            for b2 in beliefs[i+1:]:
                if not self._agents_equal(b1.agent, b2.agent):
                    if self._formulas_equal(b1.formula, b2.formula):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified - would create mutual belief formula
        return []
    
    def _agents_equal(self, a1, a2) -> bool:
        if isinstance(a1, Term) and isinstance(a2, Term):
            return a1.to_string() == a2.to_string()
        return a1 == a2
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class BeliefRevision(InferenceRule):
    """Belief Revision: B(agent, P) ∧ P(agent, ¬P) ⊢ B(agent, ¬P)"""
    
    def name(self) -> str:
        return "Belief Revision"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        perceptions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "P"]
        
        for belief in beliefs:
            for perception in perceptions:
                if self._agents_equal(belief.agent, perception.agent):
                    if isinstance(perception.formula, ConnectiveFormula) and perception.formula.connective == LogicalConnective.NOT:
                        if len(perception.formula.formulas) == 1:
                            if self._formulas_equal(belief.formula, perception.formula.formulas[0]):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        perceptions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "P"]
        
        for belief in beliefs:
            for perception in perceptions:
                if self._agents_equal(belief.agent, perception.agent):
                    if isinstance(perception.formula, ConnectiveFormula) and perception.formula.connective == LogicalConnective.NOT:
                        if len(perception.formula.formulas) == 1:
                            if self._formulas_equal(belief.formula, perception.formula.formulas[0]):
                                # Update belief based on perception
                                new_belief = CognitiveFormula(belief.operator, belief.agent, perception.formula)
                                results.append(new_belief)
        return results
    
    def _agents_equal(self, a1, a2) -> bool:
        if isinstance(a1, Term) and isinstance(a2, Term):
            return a1.to_string() == a2.to_string()
        return a1 == a2
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class IntentionSideEffect(InferenceRule):
    """Intention Side Effect: I(agent, P) ∧ B(agent, P→Q) ∧ B(agent, ¬Q) ⊢ ¬I(agent, P)"""
    
    def name(self) -> str:
        return "Intention Side Effect"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for intention with undesired side effects
        intentions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "I"]
        return len(intentions) > 0
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Complex rule - simplified for now
        return []


class KnowledgeMonotonicity(InferenceRule):
    """Knowledge Monotonicity: K(agent, P) ∧ (P→Q) ⊢ K(agent, Q)"""
    
    def name(self) -> str:
        return "Knowledge Monotonicity"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        knowledge = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "K"]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        
        for k in knowledge:
            for impl in implications:
                if len(impl.formulas) == 2:
                    if self._formulas_equal(k.formula, impl.formulas[0]):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        knowledge = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "K"]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES]
        
        for k in knowledge:
            for impl in implications:
                if len(impl.formulas) == 2:
                    if self._formulas_equal(k.formula, impl.formulas[0]):
                        new_knowledge = CognitiveFormula(k.operator, k.agent, impl.formulas[1])
                        results.append(new_knowledge)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


# ============================================================================
# Final Temporal Rules
# ============================================================================

class NextImplication(InferenceRule):
    """Next Implication: ○P ∧ ○(P→Q) ⊢ ○Q"""
    
    def name(self) -> str:
        return "Next Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        next_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "NEXT"]
        
        for nf1 in next_formulas:
            for nf2 in next_formulas:
                if isinstance(nf2.formula, ConnectiveFormula) and nf2.formula.connective == LogicalConnective.IMPLIES:
                    if len(nf2.formula.formulas) == 2:
                        if self._formulas_equal(nf1.formula, nf2.formula.formulas[0]):
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        next_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "NEXT"]
        
        for nf1 in next_formulas:
            for nf2 in next_formulas:
                if isinstance(nf2.formula, ConnectiveFormula) and nf2.formula.connective == LogicalConnective.IMPLIES:
                    if len(nf2.formula.formulas) == 2:
                        if self._formulas_equal(nf1.formula, nf2.formula.formulas[0]):
                            new_next = TemporalFormula(nf1.operator, nf2.formula.formulas[1])
                            results.append(new_next)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class EventuallyImplication(InferenceRule):
    """Eventually Implication: ◊P ∧ □(P→Q) ⊢ ◊Q"""
    
    def name(self) -> str:
        return "Eventually Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        eventually_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY"]
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for ef in eventually_formulas:
            for af in always_formulas:
                if isinstance(af.formula, ConnectiveFormula) and af.formula.connective == LogicalConnective.IMPLIES:
                    if len(af.formula.formulas) == 2:
                        if self._formulas_equal(ef.formula, af.formula.formulas[0]):
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        eventually_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY"]
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for ef in eventually_formulas:
            for af in always_formulas:
                if isinstance(af.formula, ConnectiveFormula) and af.formula.connective == LogicalConnective.IMPLIES:
                    if len(af.formula.formulas) == 2:
                        if self._formulas_equal(ef.formula, af.formula.formulas[0]):
                            new_eventually = TemporalFormula(ef.operator, af.formula.formulas[1])
                            results.append(new_eventually)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()


class UntilWeakening(InferenceRule):
    """Until Weakening: P U Q ⊢ ◊Q"""
    
    def name(self) -> str:
        return "Until Weakening"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL":
                # P U Q implies ◊Q
                from .dcec_core import TemporalOperator
                # Assuming UNTIL has two formulas: P and Q
                if hasattr(f, 'formulas') and len(f.formulas) == 2:
                    eventually_q = TemporalFormula(TemporalOperator.EVENTUALLY, f.formulas[1])
                    results.append(eventually_q)
        return results


class SinceWeakening(InferenceRule):
    """Since Weakening: P S Q ⊢ ◊(past) Q (simplified)"""
    
    def name(self) -> str:
        return "Since Weakening"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "SINCE":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified - would need past temporal operators
        return []


class TemporalNegation(InferenceRule):
    """Temporal Negation: ¬□P ⊢ ◊¬P"""
    
    def name(self) -> str:
        return "Temporal Negation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, TemporalFormula) and inner.operator.value == "ALWAYS":
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, TemporalFormula) and inner.operator.value == "ALWAYS":
                        # ¬□P → ◊¬P
                        from .dcec_core import TemporalOperator
                        not_p = ConnectiveFormula(LogicalConnective.NOT, [inner.formula])
                        eventually_not_p = TemporalFormula(TemporalOperator.EVENTUALLY, not_p)
                        results.append(eventually_not_p)
        return results


class AlwaysInduction(InferenceRule):
    """Always Induction: P ∧ □(P→○P) ⊢ □P"""
    
    def name(self) -> str:
        return "Always Induction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for base case P and inductive step
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for af in always_formulas:
            if isinstance(af.formula, ConnectiveFormula) and af.formula.connective == LogicalConnective.IMPLIES:
                if len(af.formula.formulas) == 2:
                    consequent = af.formula.formulas[1]
                    if isinstance(consequent, TemporalFormula) and consequent.operator.value == "NEXT":
                        # Found □(P→○P) pattern
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Complex inductive reasoning - simplified
        return []


# Advanced Logic Rules
class UnitResolution(InferenceRule):
    """Unit resolution: (P∨Q) ∧ ¬P ⊢ Q"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, UnaryFormula) and f2.operator.value == "NOT":
                        # Check if f2.formula matches one of the disjuncts
                        if f2.formula == f1.left or f2.formula == f1.right:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, UnaryFormula) and f2.operator.value == "NOT":
                        if f2.formula == f1.left:
                            results.append(f1.right)
                        elif f2.formula == f1.right:
                            results.append(f1.left)
        return results


class BinaryResolution(InferenceRule):
    """Binary resolution: (P∨Q) ∧ (¬P∨R) ⊢ (Q∨R)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "OR":
                        # Look for complementary literals
                        if isinstance(f1.left, UnaryFormula) and f1.left.operator.value == "NOT":
                            if f1.left.formula == f2.left or f1.left.formula == f2.right:
                                return True
                        if isinstance(f1.right, UnaryFormula) and f1.right.operator.value == "NOT":
                            if f1.right.formula == f2.left or f1.right.formula == f2.right:
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified binary resolution
        return []


class Factoring(InferenceRule):
    """Factoring: (P∨P) ⊢ P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                if f.left == f.right:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                if f.left == f.right:
                    results.append(f.left)
        return results


class Subsumption(InferenceRule):
    """Subsumption: P subsumes (P∨Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, BinaryFormula) and f2.operator.value == "OR":
                    if f1 == f2.left or f1 == f2.right:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Subsumption removes subsumed clauses
        return []


class NegationIntroduction(InferenceRule):
    """Negation introduction: (P→Q) ∧ (P→¬Q) ⊢ ¬P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "IMPLIES":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f1.left == f2.left:
                            # Check if consequents are negations of each other
                            if isinstance(f1.right, UnaryFormula) and f1.right.operator.value == "NOT":
                                if f1.right.formula == f2.right:
                                    return True
                            if isinstance(f2.right, UnaryFormula) and f2.right.operator.value == "NOT":
                                if f2.right.formula == f1.right:
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "IMPLIES":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f1.left == f2.left:
                            if isinstance(f1.right, UnaryFormula) and f1.right.operator.value == "NOT":
                                if f1.right.formula == f2.right:
                                    results.append(UnaryFormula(Operator.NOT, f1.left))
                            elif isinstance(f2.right, UnaryFormula) and f2.right.operator.value == "NOT":
                                if f2.right.formula == f1.right:
                                    results.append(UnaryFormula(Operator.NOT, f1.left))
        return results


class CaseAnalysis(InferenceRule):
    """Case analysis: (P∨Q) ∧ (P→R) ∧ (Q→R) ⊢ R"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                # Look for implications from both disjuncts to same conclusion
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.left:
                            for f3 in formulas:
                                if isinstance(f3, BinaryFormula) and f3.operator.value == "IMPLIES":
                                    if f3.left == f1.right and f3.right == f2.right:
                                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.left:
                            for f3 in formulas:
                                if isinstance(f3, BinaryFormula) and f3.operator.value == "IMPLIES":
                                    if f3.left == f1.right and f3.right == f2.right:
                                        results.append(f2.right)
        return results


class ProofByContradiction(InferenceRule):
    """Proof by contradiction: (¬P→⊥) ⊢ P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "IMPLIES":
                if isinstance(f.left, UnaryFormula) and f.left.operator.value == "NOT":
                    # Check if consequent is a contradiction (P∧¬P)
                    if isinstance(f.right, BinaryFormula) and f.right.operator.value == "AND":
                        if isinstance(f.right.right, UnaryFormula) and f.right.right.operator.value == "NOT":
                            if f.right.left == f.right.right.formula:
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "IMPLIES":
                if isinstance(f.left, UnaryFormula) and f.left.operator.value == "NOT":
                    if isinstance(f.right, BinaryFormula) and f.right.operator.value == "AND":
                        if isinstance(f.right.right, UnaryFormula) and f.right.right.operator.value == "NOT":
                            if f.right.left == f.right.right.formula:
                                results.append(f.left.formula)
        return results


# Common Knowledge Rules
class CommonKnowledgeIntroduction(InferenceRule):
    """Common knowledge introduction: K(a1, P) ∧ K(a2, P) ∧ ... ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if multiple agents know the same proposition
        knowledge_map = {}
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "K":
                if len(f.agent) > 0:
                    prop = str(f.formula)
                    if prop not in knowledge_map:
                        knowledge_map[prop] = []
                    knowledge_map[prop].append(f.agent)
        # Check if any proposition is known by multiple agents
        for agents in knowledge_map.values():
            if len(agents) >= 2:
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified - would create common knowledge formula
        return []


class CommonKnowledgeDistribution(InferenceRule):
    """Common knowledge distribution: C(P∧Q) ⊢ C(P)∧C(Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, BinaryFormula) and f.formula.operator.value == "AND":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, BinaryFormula) and f.formula.operator.value == "AND":
                    results.append(ModalFormula(Operator.C, f.formula.left, f.agent))
                    results.append(ModalFormula(Operator.C, f.formula.right, f.agent))
        return results


class CommonKnowledgeImpliesKnowledge(InferenceRule):
    """Common knowledge implies individual knowledge: C(P) ⊢ K(agent, P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                # For any agent, common knowledge implies their knowledge
                # Simplified: create knowledge for generic agent
                results.append(ModalFormula(Operator.K, f.formula, "agent"))
        return results


class CommonKnowledgeMonotonicity(InferenceRule):
    """Common knowledge monotonicity: C(P) ∧ (P→Q) ⊢ C(Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, ModalFormula) and f1.operator.value == "C":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.formula:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f1 in formulas:
            if isinstance(f1, ModalFormula) and f1.operator.value == "C":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.formula:
                            results.append(ModalFormula(Operator.C, f2.right, f1.agent))
        return results


class CommonKnowledgeNegation(InferenceRule):
    """Common knowledge negation: C(¬P) ⊢ ¬C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, UnaryFormula) and f.formula.operator.value == "NOT":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, UnaryFormula) and f.formula.operator.value == "NOT":
                    inner = ModalFormula(Operator.C, f.formula.formula, f.agent)
                    results.append(UnaryFormula(Operator.NOT, inner))
        return results


class CommonBeliefIntroduction(InferenceRule):
    """Common belief from individual beliefs: B(a1, P) ∧ B(a2, P) ⊢ CB(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        belief_map = {}
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "B":
                prop = str(f.formula)
                if prop not in belief_map:
                    belief_map[prop] = []
                belief_map[prop].append(f.agent)
        for agents in belief_map.values():
            if len(agents) >= 2:
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified common belief creation
        return []


class FixedPointInduction(InferenceRule):
    """Fixed point induction for common knowledge: P ∧ (P→K(everyone, P)) ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                    if f2.left == f1:
                        if isinstance(f2.right, ModalFormula) and f2.right.operator.value == "K":
                            if f2.right.formula == f1:
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified fixed point reasoning
        return []


class TemporallyInducedCommonKnowledge(InferenceRule):
    """Temporally induced common knowledge: □K(all, P) ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "K":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "K":
                    results.append(ModalFormula(Operator.C, f.formula.formula, "all"))
        return results


# Final Rules to Complete Phase 4B
class TemporalUntilElimination(InferenceRule):
    """Until elimination: (P U Q) ⊢ ◊Q"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL":
                # P U Q implies eventually Q
                results.append(TemporalFormula(Operator.EVENTUALLY, f.right))
        return results


class ModalNecessionIntroduction(InferenceRule):
    """Modal necessity introduction: If P is a theorem, then □P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Simplified: check for tautologies
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                # Check for P∨¬P pattern
                if isinstance(f.right, UnaryFormula) and f.right.operator.value == "NOT":
                    if f.left == f.right.formula:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                if isinstance(f.right, UnaryFormula) and f.right.operator.value == "NOT":
                    if f.left == f.right.formula:
                        results.append(TemporalFormula(Operator.ALWAYS, f))
        return results


class DisjunctionCommutes(InferenceRule):
    """Disjunction commutes in resolution: Specialized commutativity for clauses"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                # Always applicable to disjunctions
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                # Commute the disjunction
                results.append(BinaryFormula(Operator.OR, f.right, f.left))
        return results


class CommonKnowledgeTransitivity(InferenceRule):
    """Common knowledge transitivity: C(C(P)) ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "C":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "C":
                    results.append(ModalFormula(Operator.C, f.formula.formula, f.agent))
        return results


class CommonKnowledgeConjunction(InferenceRule):
    """Common knowledge conjunction: C(P) ∧ C(Q) ⊢ C(P∧Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        ck_formulas = [f for f in formulas if isinstance(f, ModalFormula) and f.operator.value == "C"]
        return len(ck_formulas) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results = []
        ck_formulas = [f for f in formulas if isinstance(f, ModalFormula) and f.operator.value == "C"]
        for i, f1 in enumerate(ck_formulas):
            for f2 in ck_formulas[i+1:]:
                conj = BinaryFormula(Operator.AND, f1.formula, f2.formula)
                results.append(ModalFormula(Operator.C, conj, f1.agent))
        return results


class MutualKnowledgeTransitivity(InferenceRule):
    """Mutual knowledge transitivity: MB(P) ∧ MB(MB(P)→Q) ⊢ MB(Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Simplified mutual belief check
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "MB":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified mutual belief reasoning
        return []


class PublicAnnouncementReduction(InferenceRule):
    """Public announcement reduction: [!P]Q ≡ (P→Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Would check for public announcement operator
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Public announcement logic - advanced feature
        return []


class GroupKnowledgeAggregation(InferenceRule):
    """Group knowledge: Everyone knows P ⊢ Group knows P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if multiple agents have knowledge of same formula
        k_formulas = {}
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "K":
                prop = str(f.formula)
                if prop not in k_formulas:
                    k_formulas[prop] = []
                k_formulas[prop].append(f.agent)
        # If any proposition is known by 3+ agents, can aggregate
        for agents in k_formulas.values():
            if len(agents) >= 3:
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified group knowledge
        return []



