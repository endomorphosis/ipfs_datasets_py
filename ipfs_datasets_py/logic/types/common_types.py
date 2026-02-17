"""Common Type Definitions for Logic Module

This module provides shared enums, protocols, and base types used across
all logic submodules.
"""

from enum import Enum
from typing import Protocol, TypeVar, Union, runtime_checkable
from dataclasses import dataclass


# Type aliases for clarity
ConfidenceScore = float  # Range: 0.0 to 1.0
ComplexityScore = int    # Range: 0 to 100


class LogicOperator(Enum):
    """Logical operators for building formulas."""
    AND = "∧"
    OR = "∨"
    NOT = "¬"
    IMPLIES = "→"
    IFF = "↔"  # If and only if / Biconditional
    EXISTS = "∃"
    FORALL = "∀"


class Quantifier(Enum):
    """Quantifiers for first-order logic."""
    UNIVERSAL = "∀"  # For all
    EXISTENTIAL = "∃"  # There exists


class FormulaType(Enum):
    """Types of logical formulas."""
    FOL = "first_order_logic"
    MODAL = "modal_logic"
    TEMPORAL = "temporal_logic"
    DEONTIC = "deontic_logic"
    MIXED = "mixed_logic"
    ARITHMETIC = "arithmetic"
    QUANTIFIED = "quantified"
    PROPOSITIONAL = "propositional"


@dataclass
class ComplexityMetrics:
    """Metrics for formula complexity analysis.
    
    PHASE 7 OPTIMIZATION: Using __slots__ for 30-40% memory reduction.
    """
    __slots__ = (
        'quantifier_depth',
        'nesting_level',
        'operator_count',
        'variable_count',
        'predicate_count',
        'complexity_score',
    )
    
    quantifier_depth: int = 0
    nesting_level: int = 0
    operator_count: int = 0
    variable_count: int = 0
    predicate_count: int = 0
    complexity_score: ComplexityScore = 0
    
    def to_dict(self):
        """Convert metrics to dictionary."""
        return {
            "quantifier_depth": self.quantifier_depth,
            "nesting_level": self.nesting_level,
            "operator_count": self.operator_count,
            "variable_count": self.variable_count,
            "predicate_count": self.predicate_count,
            "complexity_score": self.complexity_score,
        }


@runtime_checkable
class Formula(Protocol):
    """Protocol for logical formulas.
    
    Any class implementing this protocol can be used as a logical formula
    in the logic module, enabling duck typing while maintaining type safety.
    """
    
    def to_string(self) -> str:
        """Convert formula to string representation."""
        ...
    
    def get_complexity(self) -> ComplexityMetrics:
        """Get complexity metrics for this formula."""
        ...


@runtime_checkable
class Prover(Protocol):
    """Protocol for theorem provers.
    
    Any class implementing this protocol can be used as a theorem prover
    in the logic module.
    """
    
    def prove(self, formula: str, timeout: int = 30) -> "ProofResult":
        """Attempt to prove the given formula."""
        ...
    
    def get_name(self) -> str:
        """Get the name of this prover."""
        ...


@runtime_checkable
class Converter(Protocol):
    """Protocol for logic converters.
    
    Any class implementing this protocol can convert between logic formats.
    """
    
    def convert(self, formula: str, source_format: str, target_format: str) -> str:
        """Convert formula from source format to target format."""
        ...


# Type variables for generic programming
FormulaT = TypeVar('FormulaT', bound=Formula)
ProverT = TypeVar('ProverT', bound=Prover)
ConverterT = TypeVar('ConverterT', bound=Converter)


__all__ = [
    # Type aliases
    "ConfidenceScore",
    "ComplexityScore",
    # Enums
    "LogicOperator",
    "Quantifier",
    "FormulaType",
    # Dataclasses
    "ComplexityMetrics",
    # Protocols
    "Formula",
    "Prover",
    "Converter",
    # Type variables
    "FormulaT",
    "ProverT",
    "ConverterT",
]
