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
