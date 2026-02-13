"""
Shared Type Definitions for Logic Module

This module contains type definitions shared across the logic module to avoid
circular dependencies between tools, integration, TDFOL, and other submodules.

Moved from various locations during Phase 2 refactoring to centralize type
definitions and resolve circular import issues.
"""

# Import and re-export core types for convenience
from .deontic_types import (
    DeonticOperator,
    DeonticFormula,
    DeonticRuleSet,
    LegalAgent,
    LegalContext,
    TemporalCondition,
    TemporalOperator,
)

from .proof_types import (
    ProofStatus,
    ProofResult,
    ProofStep,
)

from .translation_types import (
    LogicTranslationTarget,
    TranslationResult,
    AbstractLogicFormula,
)

__all__ = [
    # Deontic types
    "DeonticOperator",
    "DeonticFormula",
    "DeonticRuleSet",
    "LegalAgent",
    "LegalContext",
    "TemporalCondition",
    "TemporalOperator",
    # Proof types
    "ProofStatus",
    "ProofResult",
    "ProofStep",
    # Translation types
    "LogicTranslationTarget",
    "TranslationResult",
    "AbstractLogicFormula",
]
