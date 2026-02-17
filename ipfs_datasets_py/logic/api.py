"""Stable public API surface for :mod:`ipfs_datasets_py.logic`.

This module is intended to be the canonical import surface for external users.
It must remain lightweight and deterministic at import time.

Design rules:
- Only thin re-exports (no side effects)
- No network access, disk writes, or environment mutation during import
- Optional dependencies must not be required to import this module

Example:

    from ipfs_datasets_py.logic.api import FOLConverter, DeonticConverter
"""

from __future__ import annotations

# Core converters
from .fol import FOLConverter, convert_text_to_fol
from .deontic import DeonticConverter, convert_legal_text_to_deontic

# Common primitives (errors, base converter abstractions, caches)
from .common import (
	LogicError,
	ConversionError,
	ValidationError,
	ProofError,
	TranslationError,
	BridgeError,
	ConfigurationError,
	DeonticError,
	ModalError,
	TemporalError,
	LogicConverter,
	ChainedConverter,
	ConversionResult,
	ConversionStatus,
	ValidationResult,
	UtilityMonitor,
	track_performance,
	with_caching,
	get_global_stats,
	clear_global_cache,
	reset_global_stats,
	BoundedCache,
	ProofCache,
	CachedProofResult,
	get_global_cache,
)

# Shared types
from .types import (
	DeonticOperator,
	DeonticFormula,
	DeonticRuleSet,
	LegalAgent,
	LegalContext,
	TemporalCondition,
	TemporalOperator,
	ProofStatus,
	ProofResult,
	ProofStep,
	LogicTranslationTarget,
	TranslationResult,
	AbstractLogicFormula,
	Formula,
	Predicate,
	Variable,
	Constant,
	And,
	Or,
	Not,
	Implies,
	Forall,
	Exists,
	LogicOperator,
	Quantifier,
	FormulaType,
	ConfidenceScore,
	ComplexityScore,
	ComplexityMetrics,
	Prover,
	Converter,
	BridgeCapability,
	BridgeMetadata,
	BridgeConfig,
	ProverRecommendation,
	FOLOutputFormat,
	PredicateCategory,
	FOLFormula,
	FOLConversionResult,
	PredicateExtraction,
)

__all__ = [
	# FOL
	"FOLConverter",
	"convert_text_to_fol",
	# Deontic
	"DeonticConverter",
	"convert_legal_text_to_deontic",
	# Common errors
	"LogicError",
	"ConversionError",
	"ValidationError",
	"ProofError",
	"TranslationError",
	"BridgeError",
	"ConfigurationError",
	"DeonticError",
	"ModalError",
	"TemporalError",
	# Common converter abstractions
	"LogicConverter",
	"ChainedConverter",
	"ConversionResult",
	"ConversionStatus",
	"ValidationResult",
	# Monitoring
	"UtilityMonitor",
	"track_performance",
	"with_caching",
	"get_global_stats",
	"clear_global_cache",
	"reset_global_stats",
	# Caching
	"BoundedCache",
	"ProofCache",
	"CachedProofResult",
	"get_global_cache",
	# Types (selection)
	"DeonticOperator",
	"DeonticFormula",
	"DeonticRuleSet",
	"LegalAgent",
	"LegalContext",
	"TemporalCondition",
	"TemporalOperator",
	"ProofStatus",
	"ProofResult",
	"ProofStep",
	"LogicTranslationTarget",
	"TranslationResult",
	"AbstractLogicFormula",
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
	"LogicOperator",
	"Quantifier",
	"FormulaType",
	"ConfidenceScore",
	"ComplexityScore",
	"ComplexityMetrics",
	"Prover",
	"Converter",
	"BridgeCapability",
	"BridgeMetadata",
	"BridgeConfig",
	"ProverRecommendation",
	"FOLOutputFormat",
	"PredicateCategory",
	"FOLFormula",
	"FOLConversionResult",
	"PredicateExtraction",
]
