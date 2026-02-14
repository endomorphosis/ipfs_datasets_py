"""
Logic Verification Types

This module defines the type definitions, dataclasses, and enumerations
used by the Logic Verification system.

Extracted from logic_verification.py to improve modularity and
prevent circular dependencies.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple


class VerificationResult(Enum):
    """Enumeration for verification results."""
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class LogicAxiom:
    """
    Represents a logical axiom or rule.
    
    Attributes:
        name: Unique name for the axiom
        formula: Logical formula representation
        description: Human-readable explanation
        axiom_type: Type of axiom (user_defined, built_in, derived)
        confidence: Confidence score (0.0-1.0)
        metadata: Additional metadata dictionary
        
    Example:
        >>> axiom = LogicAxiom(
        ...     name="modus_ponens",
        ...     formula="((P → Q) ∧ P) → Q",
        ...     description="If P implies Q and P is true, then Q is true",
        ...     axiom_type="built_in"
        ... )
    """
    name: str
    formula: str
    description: str
    axiom_type: str = "user_defined"  # user_defined, built_in, derived
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProofStep:
    """
    Represents a single step in a logical proof.
    
    Attributes:
        step_number: Position in the proof sequence
        formula: Logical formula at this step
        justification: Explanation for this step
        rule_applied: Name of the inference rule used
        premises: List of formulas used as premises
        confidence: Confidence score for this step (0.0-1.0)
        
    Example:
        >>> step = ProofStep(
        ...     step_number=1,
        ...     formula="P → Q",
        ...     justification="Given premise",
        ...     rule_applied="premise",
        ...     premises=[]
        ... )
    """
    step_number: int
    formula: str
    justification: str
    rule_applied: str
    premises: List[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class ProofResult:
    """
    Result of a proof attempt.
    
    Attributes:
        is_valid: Whether the proof is valid
        conclusion: The conclusion being proved
        steps: List of proof steps
        confidence: Overall confidence score (0.0-1.0)
        method_used: Method used for proof generation
        time_taken: Time taken in seconds
        errors: List of error messages
        
    Example:
        >>> result = ProofResult(
        ...     is_valid=True,
        ...     conclusion="Q",
        ...     steps=[step1, step2],
        ...     confidence=0.95,
        ...     method_used="symbolic"
        ... )
    """
    is_valid: bool
    conclusion: str
    steps: List[ProofStep]
    confidence: float
    method_used: str
    time_taken: float = 0.0
    errors: List[str] = field(default_factory=list)


@dataclass
class ConsistencyCheck:
    """
    Result of consistency checking.
    
    Attributes:
        is_consistent: Whether the formulas are consistent
        conflicting_formulas: Pairs of conflicting formulas
        confidence: Confidence score (0.0-1.0)
        explanation: Human-readable explanation
        method_used: Method used for checking (symbolic, fallback)
        
    Example:
        >>> check = ConsistencyCheck(
        ...     is_consistent=False,
        ...     conflicting_formulas=[("P", "¬P")],
        ...     confidence=0.9,
        ...     explanation="Direct contradiction found"
        ... )
    """
    is_consistent: bool
    conflicting_formulas: List[Tuple[str, str]] = field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""
    method_used: str = "fallback"


@dataclass
class EntailmentResult:
    """
    Result of entailment checking.
    
    Attributes:
        entails: Whether premises entail the conclusion
        premises: List of premise formulas
        conclusion: Conclusion formula
        confidence: Confidence score (0.0-1.0)
        counterexample: Optional counterexample if entailment fails
        explanation: Human-readable explanation
        
    Example:
        >>> result = EntailmentResult(
        ...     entails=True,
        ...     premises=["P → Q", "P"],
        ...     conclusion="Q",
        ...     confidence=1.0,
        ...     explanation="Follows by modus ponens"
        ... )
    """
    entails: bool
    premises: List[str]
    conclusion: str
    confidence: float
    counterexample: Optional[Dict[str, Any]] = None
    explanation: str = ""


# Export all types
__all__ = [
    'VerificationResult',
    'LogicAxiom',
    'ProofStep',
    'ProofResult',
    'ConsistencyCheck',
    'EntailmentResult',
]
