"""
Shared Type Definitions for Logic Module

This module contains type definitions shared across the logic module to avoid
circular dependencies between tools, integration, TDFOL, and other submodules.

Moved from various locations during Phase 2 refactoring to centralize type
definitions and resolve circular import issues.
"""

from __future__ import annotations

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

from ..TDFOL.tdfol_core import (
    Formula as TDFOLFormula,
    Predicate as TDFOLPredicate,
    Variable as TDFOLVariable,
    Constant as TDFOLConstant,
    create_conjunction,
    create_disjunction,
    create_negation,
    create_implication,
    create_universal,
    create_existential,
)


Formula = TDFOLFormula
Predicate = TDFOLPredicate
Variable = TDFOLVariable
Constant = TDFOLConstant


def And(left: Formula, right: Formula) -> Formula:
    return create_conjunction(left, right)


def Or(left: Formula, right: Formula) -> Formula:
    return create_disjunction(left, right)


def Not(formula: Formula) -> Formula:
    return create_negation(formula)


def Implies(antecedent: Formula, consequent: Formula) -> Formula:
    return create_implication(antecedent, consequent)


def Forall(variable: Variable, formula: Formula) -> Formula:
    return create_universal(variable, formula)


def Exists(variable: Variable, formula: Formula) -> Formula:
    return create_existential(variable, formula)

from .translation_types import (
    LogicTranslationTarget,
    TranslationResult,
    AbstractLogicFormula,
)

from .common_types import (
    LogicOperator,
    Quantifier,
    FormulaType,
    ConfidenceScore,
    ComplexityScore,
    ComplexityMetrics,
    Formula as FormulaProtocol,
    Prover,
    Converter,
)

from .bridge_types import (
    BridgeCapability,
    ConversionStatus,
    BridgeMetadata,
    ConversionResult,
    BridgeConfig,
    ProverRecommendation,
)

# Explicit bridge conversion aliases to avoid confusion with
# ipfs_datasets_py.logic.common.converters.ConversionResult/ConversionStatus.
BridgeConversionStatus = ConversionStatus
BridgeConversionResult = ConversionResult

from .fol_types import (
    FOLOutputFormat,
    PredicateCategory,
    Predicate as FOLPredicate,
    FOLFormula,
    FOLConversionResult,
    PredicateExtraction,
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

    # TDFOL core term/formula helpers (compat)
    "Formula",
    "Predicate",
    "Variable",
    "Constant",
    "And",
    "Or",
    "Not",
    "Implies",
    "Forall",
    "Exists",
    # Common types
    "LogicOperator",
    "Quantifier",
    "FormulaType",
    "ConfidenceScore",
    "ComplexityScore",
    "ComplexityMetrics",
    "Prover",
    "Converter",
    # Bridge types
    "BridgeCapability",
    "ConversionStatus",
    "BridgeConversionStatus",
    "BridgeMetadata",
    "ConversionResult",
    "BridgeConversionResult",
    "BridgeConfig",
    "ProverRecommendation",
    # FOL types
    "FOLOutputFormat",
    "PredicateCategory",
    "FOLPredicate",
    "FOLFormula",
    "FOLConversionResult",
    "PredicateExtraction",
]
