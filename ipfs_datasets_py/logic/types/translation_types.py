"""Translation type definitions (import-safe).

These backward-compatible datatypes are used by the core logic subsystem and must not import
`ipfs_datasets_py.logic.integration` (or other heavy optional subsystems) at
import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .deontic_types import DeonticFormula


class LogicTranslationTarget(Enum):
    """Supported theorem prover and logic system targets."""

    LEAN = "lean"
    COQ = "coq"
    ISABELLE = "isabelle"
    SMT_LIB = "smt-lib"
    TPTP = "tptp"
    Z3 = "z3"
    VAMPIRE = "vampire"
    E_PROVER = "eprover"
    AGDA = "agda"
    HOL = "hol"
    PVS = "pvs"


@dataclass
class TranslationResult:
    """Result of translating a formula to a target format."""

    target: LogicTranslationTarget
    translated_formula: str
    success: bool
    confidence: float = 1.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target.value,
            "translated_formula": self.translated_formula,
            "success": self.success,
            "confidence": self.confidence,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "dependencies": list(self.dependencies),
        }


@dataclass
class AbstractLogicFormula:
    """Platform-independent intermediate representation for translation."""

    formula_type: str
    operators: List[str]
    variables: List[Tuple[str, str]]
    quantifiers: List[Tuple[str, str, str]]
    propositions: List[str]
    logical_structure: Dict[str, Any]
    source_formula: Optional[DeonticFormula] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_type": self.formula_type,
            "operators": list(self.operators),
            "variables": list(self.variables),
            "quantifiers": list(self.quantifiers),
            "propositions": list(self.propositions),
            "logical_structure": dict(self.logical_structure),
            "source_formula_id": getattr(self.source_formula, "formula_id", None)
            if self.source_formula
            else None,
        }


__all__ = [
    "LogicTranslationTarget",
    "TranslationResult",
    "AbstractLogicFormula",
]
