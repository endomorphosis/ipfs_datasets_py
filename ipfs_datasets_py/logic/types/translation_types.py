"""Translation type definitions.

This module defines small, import-safe datatypes used by the logic subsystem.

Do NOT import heavy integration modules here; this file must remain safe to
import when users do ``import ipfs_datasets_py.logic.api``.
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
            "source_formula_id": getattr(self.source_formula, "formula_id", None) if self.source_formula else None,
        }


__all__ = [
    "LogicTranslationTarget",
    "TranslationResult",
    "AbstractLogicFormula",
]
"""
Translation Type Definitions

This module provides backward-compatible imports for translation-related types.
Types are still defined in integration/logic_translation_core.py but imported here
for centralized access and to prevent circular dependencies.

For internal use within the logic module, import from here:
    from ipfs_datasets_py.logic.types import LogicTranslationTarget, TranslationResult

For external use, the types are still available from their original location:
    from ipfs_datasets_py.logic.integration.logic_translation_core import TranslationResult
"""

# Re-export from original location to maintain backward compatibility
from ..integration.converters.logic_translation_core import (
    LogicTranslationTarget,
    TranslationResult,
    AbstractLogicFormula,
)

__all__ = [
    "LogicTranslationTarget",
    "TranslationResult",
    "AbstractLogicFormula",
]
