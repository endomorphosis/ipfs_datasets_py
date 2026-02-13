"""FOL (First-Order Logic) Type Definitions

This module provides type definitions specific to first-order logic operations.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from .common_types import LogicOperator, Quantifier, ComplexityMetrics, ConfidenceScore


class FOLOutputFormat(Enum):
    """Output formats for FOL conversion."""
    PROLOG = "prolog"
    TPTP = "tptp"
    JSON = "json"
    DEFEASIBLE = "defeasible"
    SMTLIB = "smtlib"
    NATURAL_LANGUAGE = "natural_language"


class PredicateCategory(Enum):
    """Categories of predicates in FOL."""
    ENTITY = "entity"
    ACTION = "action"
    RELATION = "relation"
    PROPERTY = "property"
    TEMPORAL = "temporal"
    MODAL = "modal"
    UNKNOWN = "unknown"


@dataclass
class Predicate:
    """Represents a predicate in first-order logic."""
    name: str
    arity: int
    category: PredicateCategory = PredicateCategory.UNKNOWN
    definition: Optional[str] = None
    
    def to_string(self) -> str:
        """Convert predicate to string representation."""
        if self.arity == 0:
            return self.name
        args = ", ".join(f"x{i}" for i in range(self.arity))
        return f"{self.name}({args})"


@dataclass
class FOLFormula:
    """Represents a first-order logic formula."""
    formula_string: str
    predicates: List[Predicate] = field(default_factory=list)
    quantifiers: List[Quantifier] = field(default_factory=list)
    operators: List[LogicOperator] = field(default_factory=list)
    variables: List[str] = field(default_factory=list)
    complexity: Optional[ComplexityMetrics] = None
    confidence: ConfidenceScore = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_predicate_names(self) -> List[str]:
        """Get list of predicate names."""
        return [p.name for p in self.predicates]
    
    def has_quantifiers(self) -> bool:
        """Check if formula has quantifiers."""
        return len(self.quantifiers) > 0


@dataclass
class FOLConversionResult:
    """Result of converting natural language to FOL."""
    source_text: str
    fol_formula: FOLFormula
    output_format: FOLOutputFormat
    formatted_output: str
    confidence: ConfidenceScore
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_high_confidence(self, threshold: float = 0.7) -> bool:
        """Check if conversion has high confidence."""
        return self.confidence >= threshold


@dataclass
class PredicateExtraction:
    """Result of predicate extraction from text."""
    text: str
    predicates_by_category: Dict[PredicateCategory, List[Predicate]]
    total_predicates: int
    confidence: ConfidenceScore
    
    def get_all_predicates(self) -> List[Predicate]:
        """Get all extracted predicates."""
        all_preds = []
        for preds in self.predicates_by_category.values():
            all_preds.extend(preds)
        return all_preds


__all__ = [
    "FOLOutputFormat",
    "PredicateCategory",
    "Predicate",
    "FOLFormula",
    "FOLConversionResult",
    "PredicateExtraction",
]
