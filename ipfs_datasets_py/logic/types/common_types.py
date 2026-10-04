"""Common type definitions for the logic module.

This module must remain lightweight and free of import-time side effects.
It provides shared enums, protocols, and small dataclasses used across
`ipfs_datasets_py.logic.*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from .proof_types import ProofResult


ConfidenceScore = float  # Range: 0.0 to 1.0
ComplexityScore = int  # Range: 0 to 100


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
    """High-level categories of logical formulas."""

    FOL = "first_order_logic"
    MODAL = "modal_logic"
    TEMPORAL = "temporal_logic"
    DEONTIC = "deontic_logic"
    MIXED = "mixed_logic"
    ARITHMETIC = "arithmetic"
    QUANTIFIED = "quantified"
    PROPOSITIONAL = "propositional"


@dataclass(slots=True)
class ComplexityMetrics:
    """Metrics for formula complexity analysis."""

    quantifier_depth: int = 0
    nesting_level: int = 0
    operator_count: int = 0
    variable_count: int = 0
    predicate_count: int = 0
    complexity_score: ComplexityScore = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "quantifier_depth": self.quantifier_depth,
            "nesting_level": self.nesting_level,
            "operator_count": self.operator_count,
            "variable_count": self.variable_count,
            "predicate_count": self.predicate_count,
            "complexity_score": int(self.complexity_score),
        }


@runtime_checkable
class Formula(Protocol):
    """Protocol for logical formula objects."""

    def to_string(self) -> str: ...

    def get_complexity(self) -> ComplexityMetrics: ...


@runtime_checkable
class Prover(Protocol):
    """Protocol for theorem provers."""

    def prove(self, formula: str, timeout: int = 30) -> "ProofResult": ...

    def get_name(self) -> str: ...


@runtime_checkable
class Converter(Protocol):
    """Protocol for logic converters."""

    def convert(self, formula: str, source_format: str, target_format: str) -> str: ...


FormulaT = TypeVar("FormulaT", bound=Formula)
ProverT = TypeVar("ProverT", bound=Prover)
ConverterT = TypeVar("ConverterT", bound=Converter)


__all__ = [
    "ConfidenceScore",
    "ComplexityScore",
    "LogicOperator",
    "Quantifier",
    "FormulaType",
    "ComplexityMetrics",
    "Formula",
    "Prover",
    "Converter",
    "FormulaT",
    "ProverT",
    "ConverterT",
]
