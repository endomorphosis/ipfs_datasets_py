"""
Logic Verification Utilities

This module provides utility functions and helpers for the Logic
Verification system, including convenience functions and axiom initialization.

Extracted from logic_verification.py to improve modularity.
"""

import re
from typing import List, Dict, Any, TYPE_CHECKING
try:
    from beartype import beartype  # type: ignore
except Exception:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func

if TYPE_CHECKING:
    from .logic_verification import LogicVerifier
    from .logic_verification_types import (
        LogicAxiom, ConsistencyCheck, EntailmentResult, ProofResult, ProofStep
    )


def get_basic_axioms() -> List["LogicAxiom"]:
    """
    Get the standard set of basic logical axioms.
    
    Returns a list of fundamental logical axioms including modus ponens,
    modus tollens, law of excluded middle, law of non-contradiction,
    universal instantiation, and existential generalization.
    
    Returns:
        List of LogicAxiom objects representing basic logical rules
        
    Example:
        >>> axioms = get_basic_axioms()
        >>> len(axioms)
        6
        >>> axioms[0].name
        'modus_ponens'
    """
    from .logic_verification_types import LogicAxiom
    
    return [
        LogicAxiom(
            name="modus_ponens",
            formula="((P → Q) ∧ P) → Q",
            description="Modus Ponens: If P implies Q and P is true, then Q is true",
            axiom_type="built_in"
        ),
        LogicAxiom(
            name="modus_tollens", 
            formula="((P → Q) ∧ ¬Q) → ¬P",
            description="Modus Tollens: If P implies Q and Q is false, then P is false",
            axiom_type="built_in"
        ),
        LogicAxiom(
            name="law_of_excluded_middle",
            formula="P ∨ ¬P",
            description="Law of Excluded Middle: Either P or not P",
            axiom_type="built_in"
        ),
        LogicAxiom(
            name="law_of_noncontradiction",
            formula="¬(P ∧ ¬P)",
            description="Law of Non-contradiction: P and not P cannot both be true",
            axiom_type="built_in"
        ),
        LogicAxiom(
            name="universal_instantiation",
            formula="∀x P(x) → P(a)",
            description="Universal Instantiation: If P holds for all x, then P holds for any specific a",
            axiom_type="built_in"
        ),
        LogicAxiom(
            name="existential_generalization",
            formula="P(a) → ∃x P(x)",
            description="Existential Generalization: If P holds for a specific a, then there exists an x such that P(x)",
            axiom_type="built_in"
        )
    ]


def get_basic_proof_rules() -> List[dict]:
    """
    Get basic proof rules for fallback reasoning.
    
    Returns a list of basic inference rules that can be used for
    proof generation when advanced reasoning is not available.
    
    Returns:
        List of dictionaries containing rule names and patterns
        
    Example:
        >>> rules = get_basic_proof_rules()
        >>> len(rules) >= 3
        True
    """
    return [
        {"name": "modus_ponens", "pattern": r"P.*Q.*P"},
        {"name": "modus_tollens", "pattern": r"P.*Q.*¬Q"},
        {"name": "hypothetical_syllogism", "pattern": r"P.*Q.*Q.*R"}
    ]


def validate_formula_syntax(formula: str) -> bool:
    """
    Basic validation of formula syntax.
    
    Checks for empty formulas and balanced parentheses.
    
    Args:
        formula: Logical formula to validate
        
    Returns:
        True if formula passes basic syntax checks, False otherwise
        
    Example:
        >>> validate_formula_syntax("P ∧ Q")
        True
        >>> validate_formula_syntax("P ∧ (Q")
        False
        >>> validate_formula_syntax("")
        False
    """
    if not formula or not formula.strip():
        return False
    
    # Check for balanced parentheses
    paren_count = 0
    for char in formula:
        if char == '(':
            paren_count += 1
        elif char == ')':
            paren_count -= 1
        if paren_count < 0:
            return False
    
    return paren_count == 0


def parse_proof_steps(proof_text: str) -> List["ProofStep"]:
    """
    Parse proof steps from text output.
    
    Extracts structured proof steps from natural language proof text,
    looking for patterns like "Step 1: P → Q (premise)".
    
    Args:
        proof_text: Text containing proof steps
        
    Returns:
        List of ProofStep objects
        
    Example:
        >>> text = "Step 1: P → Q (premise)\\nStep 2: P (premise)"
        >>> steps = parse_proof_steps(text)
        >>> len(steps)
        2
        >>> steps[0].formula
        'P → Q'
    """
    from .logic_verification_types import ProofStep
    
    steps = []
    lines = proof_text.split('\n')
    
    step_pattern = r'Step\s+(\d+):\s*(.+?)\s*\((.+?)\)'
    
    for line in lines:
        match = re.search(step_pattern, line, re.IGNORECASE)
        if match:
            step_num = int(match.group(1))
            formula = match.group(2).strip()
            justification = match.group(3).strip()
            
            steps.append(ProofStep(
                step_number=step_num,
                formula=formula,
                justification=justification,
                rule_applied="symbolic_reasoning"
            ))
    
    return steps


def are_contradictory(formula1: str, formula2: str) -> bool:
    """
    Check if two formulas are obviously contradictory.
    
    Performs basic contradiction detection by checking for direct negation
    patterns like "P" vs "¬P".
    
    Args:
        formula1: First formula
        formula2: Second formula
        
    Returns:
        True if formulas are contradictory, False otherwise
        
    Example:
        >>> are_contradictory("P", "¬P")
        True
        >>> are_contradictory("P", "Q")
        False
    """
    # Check for direct negation
    if formula1.startswith('¬') and formula1[1:].strip() == formula2.strip():
        return True
    if formula2.startswith('¬') and formula2[1:].strip() == formula1.strip():
        return True
    
    # Check for patterns like "P" and "¬P"
    f1_clean = formula1.strip()
    f2_clean = formula2.strip()
    
    if f1_clean.startswith('¬') and f1_clean[1:].strip() == f2_clean:
        return True
    if f2_clean.startswith('¬') and f2_clean[1:].strip() == f1_clean:
        return True
    
    return False


# Convenience functions for quick verification
@beartype
def verify_consistency(formulas: List[str]) -> "ConsistencyCheck":
    """
    Quick consistency check for a list of formulas.
    
    Creates a LogicVerifier instance and checks if the given formulas
    are mutually consistent (i.e., can all be true at the same time).
    
    Args:
        formulas: List of logical formulas to check
        
    Returns:
        ConsistencyCheck result with details about consistency
        
    Example:
        >>> result = verify_consistency(["P", "¬P"])
        >>> result.is_consistent
        False
    """
    from .logic_verification import LogicVerifier
    verifier = LogicVerifier()
    return verifier.check_consistency(formulas)


@beartype
def verify_entailment(premises: List[str], conclusion: str) -> "EntailmentResult":
    """
    Quick entailment check.
    
    Creates a LogicVerifier instance and checks if the premises
    logically entail the conclusion.
    
    Args:
        premises: List of premise formulas
        conclusion: Conclusion formula to verify
        
    Returns:
        EntailmentResult with details about the entailment
        
    Example:
        >>> result = verify_entailment(["P → Q", "P"], "Q")
        >>> result.entails
        True
    """
    from .logic_verification import LogicVerifier
    verifier = LogicVerifier()
    return verifier.check_entailment(premises, conclusion)


@beartype
def generate_proof(premises: List[str], conclusion: str) -> "ProofResult":
    """
    Quick proof generation.
    
    Creates a LogicVerifier instance and attempts to generate a
    step-by-step proof showing how the conclusion follows from premises.
    
    Args:
        premises: List of premise formulas
        conclusion: Conclusion to prove
        
    Returns:
        ProofResult with proof steps and validity information
        
    Example:
        >>> result = generate_proof(["P → Q", "P"], "Q")
        >>> result.is_valid
        True
        >>> len(result.steps) > 0
        True
    """
    from .logic_verification import LogicVerifier
    verifier = LogicVerifier()
    return verifier.generate_proof(premises, conclusion)


def create_logic_verifier(use_symbolic_ai: bool = True, fallback_enabled: bool = True) -> "LogicVerifier":
    """
    Factory function to create a LogicVerifier instance.
    
    This is the recommended way to create a LogicVerifier,
    providing a clean API for verifier creation.
    
    Args:
        use_symbolic_ai: Whether to use SymbolicAI for enhanced verification
        fallback_enabled: Whether to allow fallback methods when SymbolicAI fails
        
    Returns:
        LogicVerifier instance ready for use
        
    Example:
        >>> verifier = create_logic_verifier(use_symbolic_ai=True)
        >>> result = verifier.check_consistency(["P", "Q"])
    """
    from .logic_verification import LogicVerifier
    return LogicVerifier(use_symbolic_ai=use_symbolic_ai, fallback_enabled=fallback_enabled)


# Export utility functions
__all__ = [
    'get_basic_axioms',
    'get_basic_proof_rules',
    'validate_formula_syntax',
    'parse_proof_steps',
    'are_contradictory',
    'verify_consistency',
    'verify_entailment',
    'generate_proof',
    'create_logic_verifier',
]
