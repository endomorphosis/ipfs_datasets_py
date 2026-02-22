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

from typing import Any, Optional

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

# ── NL→UCAN deontic policy pipeline (lazy imports, no hard dependency) ────────
# These are available when the CEC/nl and integration sub-packages are present.
# All imports are wrapped so that importing ``logic.api`` never fails even when
# optional dependencies (py-ucan, cryptography, etc.) are absent.


def _lazy_nl_ucan():
	"""Return the NL-UCAN pipeline symbols as a namespace, or None on import error."""
	try:
		from .CEC.nl.nl_to_policy_compiler import NLToDCECCompiler, compile_nl_to_policy  # type: ignore[import-not-found]
		from .CEC.nl.dcec_to_ucan_bridge import DCECToUCANBridge  # type: ignore[import-not-found]
		from .CEC.nl.grammar_nl_policy_compiler import GrammarNLPolicyCompiler  # type: ignore[import-not-found]
		from .integration.nl_ucan_policy_compiler import NLUCANPolicyCompiler  # type: ignore[import-not-found]
		from .integration.ucan_policy_bridge import (  # type: ignore[import-not-found]
			UCANPolicyBridge,
			SignedPolicyResult,
			BridgeCompileResult,
			BridgeEvaluationResult,
		)
		return dict(
			NLToDCECCompiler=NLToDCECCompiler,
			compile_nl_to_policy=compile_nl_to_policy,
			DCECToUCANBridge=DCECToUCANBridge,
			GrammarNLPolicyCompiler=GrammarNLPolicyCompiler,
			NLUCANPolicyCompiler=NLUCANPolicyCompiler,
			UCANPolicyBridge=UCANPolicyBridge,
			SignedPolicyResult=SignedPolicyResult,
			BridgeCompileResult=BridgeCompileResult,
			BridgeEvaluationResult=BridgeEvaluationResult,
		)
	except Exception:
		return None


def _api_compile_nl_to_policy(text: str, **kw) -> Any:  # type: ignore[return]
	"""Compile *text* to a :class:`PolicyObject` via the NL→UCAN pipeline."""
	ns = _lazy_nl_ucan()
	if ns is None:
		raise ImportError(
			"NL→UCAN pipeline is not available.  Ensure the logic/CEC and "
			"logic/integration sub-packages are importable."
		)
	return ns["compile_nl_to_policy"](text, **kw)


def _api_evaluate_nl_policy(nl_text: str, *, tool: str, actor: Optional[str] = None, **kw) -> Any:  # type: ignore[return]
	"""Compile *nl_text* and evaluate it against *tool*/*actor*."""
	from .integration.ucan_policy_bridge import compile_and_evaluate as _ce  # type: ignore[import-not-found]
	return _ce(nl_text, tool=tool, actor=actor, **kw)


async def _api_build_signed_delegation(nl_text: str, *, audience_did: str, **kw) -> Any:  # type: ignore[return]
	"""Compile *nl_text* and sign the resulting delegation tokens (Phase 2b)."""
	ns = _lazy_nl_ucan()
	if ns is None:
		raise ImportError("NL→UCAN pipeline is not available.")
	bridge = ns["UCANPolicyBridge"]()
	return await bridge.compile_and_sign(nl_text, audience_did=audience_did, **kw)


# Public aliases that appear in __all__
compile_nl_to_policy = _api_compile_nl_to_policy
evaluate_nl_policy = _api_evaluate_nl_policy
build_signed_delegation = _api_build_signed_delegation

# Populate NL-UCAN names into module namespace (best-effort)
_nl_ucan_ns = _lazy_nl_ucan()
if _nl_ucan_ns:
	NLToDCECCompiler = _nl_ucan_ns["NLToDCECCompiler"]
	DCECToUCANBridge = _nl_ucan_ns["DCECToUCANBridge"]
	GrammarNLPolicyCompiler = _nl_ucan_ns["GrammarNLPolicyCompiler"]
	NLUCANPolicyCompiler = _nl_ucan_ns["NLUCANPolicyCompiler"]
	UCANPolicyBridge = _nl_ucan_ns["UCANPolicyBridge"]
	SignedPolicyResult = _nl_ucan_ns["SignedPolicyResult"]
	BridgeCompileResult = _nl_ucan_ns["BridgeCompileResult"]
	BridgeEvaluationResult = _nl_ucan_ns["BridgeEvaluationResult"]


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
	# NL→UCAN policy pipeline (Phase 1-3)
	"compile_nl_to_policy",
	"evaluate_nl_policy",
	"build_signed_delegation",
	"NLToDCECCompiler",
	"DCECToUCANBridge",
	"NLUCANPolicyCompiler",
	"GrammarNLPolicyCompiler",
	"UCANPolicyBridge",
	"SignedPolicyResult",
	"BridgeCompileResult",
	"BridgeEvaluationResult",
]
