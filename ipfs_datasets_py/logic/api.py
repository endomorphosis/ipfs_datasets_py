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

import warnings

# Beartype can emit PEP585 deprecation warnings at import time for legacy type
# hints in some submodules. The superproject enforces that Quick Start imports
# are quiet, even under ``warnings.simplefilter('always')``.
try:  # pragma: no cover
	from beartype.roar import BeartypeDecorHintPep585DeprecationWarning  # type: ignore
except Exception:  # pragma: no cover
	BeartypeDecorHintPep585DeprecationWarning = None  # type: ignore

if BeartypeDecorHintPep585DeprecationWarning is not None:
	warnings.filterwarnings(
		"ignore",
		category=BeartypeDecorHintPep585DeprecationWarning,  # type: ignore[arg-type]
	)

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

# BW133: Populate UCAN delegation + conflict detector into namespace (best-effort)
_BW133_DELEGATION_AVAILABLE = False
_BW133_CONFLICT_AVAILABLE = False
_CD140_I18N_AVAILABLE = False  # CD140
try:
	from ipfs_datasets_py.mcp_server.ucan_delegation import (  # type: ignore[import-not-found]
		DelegationManager,
		get_delegation_manager,
	)
	_BW133_DELEGATION_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
	pass  # optional – mcp_server may be absent

try:
	from .CEC.nl.nl_policy_conflict_detector import (  # type: ignore[import-not-found]
		NLPolicyConflictDetector,
		PolicyConflict,
		detect_conflicts,
		detect_i18n_conflicts,  # CB138
		I18NConflictResult,  # CB138
	)
	_BW133_CONFLICT_AVAILABLE = True
	_CD140_I18N_AVAILABLE = True  # CD140
except (ImportError, ModuleNotFoundError):
	pass  # optional

try:
	from .integration.ucan_policy_bridge import (  # type: ignore[import-not-found]
		UCANPolicyBridge as _UCANPolicyBridge_check,  # already imported above
	)
	# evaluate_with_manager is a method, not a standalone symbol
except (ImportError, ModuleNotFoundError):
	pass


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
# BW133: conditionally extend __all__ with symbols that loaded successfully
if _BW133_DELEGATION_AVAILABLE:
	__all__ += ["DelegationManager", "get_delegation_manager"]
if _BW133_CONFLICT_AVAILABLE:
	__all__ += ["NLPolicyConflictDetector", "PolicyConflict", "detect_conflicts"]
# CD140: i18n conflict symbols
if _CD140_I18N_AVAILABLE:
	__all__ += ["detect_i18n_conflicts", "I18NConflictResult"]

# ---------------------------------------------------------------------------
# CN150: evaluate_with_manager convenience wrapper
# ---------------------------------------------------------------------------

def evaluate_with_manager(
    policy_cid: str,
    tool: str,
    *,
    actor: Optional[str] = None,
    leaf_cid: Optional[str] = None,
    at_time: Optional[float] = None,
    manager: Optional[Any] = None,
    audit_log: Optional[Any] = None,
) -> Optional[Any]:
    """CN150: Module-level convenience wrapper for :meth:`UCANPolicyBridge.evaluate_audited_with_manager`.

    Parameters
    ----------
    policy_cid:
        CID of the policy to evaluate against.
    tool:
        The tool/action being requested.
    actor:
        Optional actor DID.
    leaf_cid:
        Optional leaf delegation token CID.
    at_time:
        Optional Unix timestamp for temporal evaluation.
    manager:
        Optional :class:`~mcp_server.ucan_delegation.DelegationManager`.
    audit_log:
        Optional :class:`~mcp_server.policy_audit_log.PolicyAuditLog`.

    Returns
    -------
    :class:`~logic.integration.ucan_policy_bridge.BridgeEvaluationResult`, or
    ``None`` if the bridge module is unavailable.
    """
    try:
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import get_ucan_policy_bridge
        bridge = get_ucan_policy_bridge()
        return bridge.evaluate_audited_with_manager(
            policy_cid,
            tool=tool,
            actor=actor,
            leaf_cid=leaf_cid,
            at_time=at_time,
            manager=manager,
            audit_log=audit_log,
        )
    except (ImportError, ModuleNotFoundError, AttributeError) as exc:
        import logging as _logging
        _logging.getLogger(__name__).debug("evaluate_with_manager: unavailable: %s", exc)
        return None


# CN150: conditionally extend __all__
_CN150_BRIDGE_AVAILABLE = False
try:
    from ipfs_datasets_py.logic.integration.ucan_policy_bridge import (  # noqa: F811
        UCANPolicyBridge as _UCANPolicyBridge,
    )
    _CN150_BRIDGE_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    pass

# CN150: extend __all__ only if symbols are loadable
if _CN150_BRIDGE_AVAILABLE:
    __all__ += ["evaluate_with_manager"]
# CJ146: detect_i18n_clauses
try:
    from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (  # noqa: F401
        detect_i18n_clauses,
    )
    __all__ += ["detect_i18n_clauses"]
except (ImportError, ModuleNotFoundError):
    pass


# ---------------------------------------------------------------------------
# CT156: I18NConflictReport + detect_all_languages convenience
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dataclass, field as _field
from typing import Dict as _Dict, List as _List


@_dataclass
class I18NConflictReport:
    """CT156: Multi-language conflict detection report.

    Collects :class:`~logic.CEC.nl.nl_policy_conflict_detector.PolicyConflict`
    results for each language scanned by :func:`detect_all_languages`.

    Attributes
    ----------
    by_language:
        Mapping of ISO 639-1 language code → list of :class:`PolicyConflict`.
    """

    by_language: _Dict[str, _List[Any]] = _field(default_factory=dict)

    @property
    def total_conflicts(self) -> int:
        """Total number of conflicts across all languages."""
        return sum(len(v) for v in self.by_language.values())

    @property
    def languages_with_conflicts(self) -> _List[str]:
        """Languages that produced at least one conflict."""
        return sorted(lang for lang, conflicts in self.by_language.items() if conflicts)

    def to_dict(self) -> Any:
        """Return a plain-dict representation suitable for JSON serialisation."""
        return {
            lang: [c.to_dict() for c in conflicts]
            for lang, conflicts in self.by_language.items()
        }

    def most_conflicted_language(self) -> Optional[str]:
        """EG195: Return the language with the highest conflict count.

        Returns ``None`` when no conflicts have been detected across any
        language (i.e. :attr:`total_conflicts` is 0).

        When multiple languages share the same maximum count the one that
        appears first in the :attr:`by_language` insertion order is
        returned (deterministic for a fixed :func:`detect_all_languages`
        call).

        Returns
        -------
        str or None
            ISO 639-1 language code with the most conflicts, or ``None``.
        """
        best: Optional[str] = None
        best_count = 0
        for lang, conflicts in self.by_language.items():
            n = len(conflicts)
            if n > best_count:
                best = lang
                best_count = n
        return best

    def conflict_density(self) -> float:
        """EL200: Average number of conflicts per supported language.

        Computes ``total_conflicts / number_of_language_slots``.  Returns
        ``0.0`` when :attr:`by_language` is empty (no languages scanned).

        Returns
        -------
        float
            Mean conflicts-per-language, or ``0.0`` for an empty report.
        """
        n = len(self.by_language)
        if n == 0:
            return 0.0
        return self.total_conflicts / n

    def least_conflicted_language(self) -> Optional[str]:
        """EV210: Return the language with the lowest (non-zero) conflict count.

        Returns ``None`` when no language has any conflicts.  When all
        populated languages have the same count, returns the first in
        :attr:`by_language` insertion order.

        Returns
        -------
        str or None
            ISO 639-1 language code with the fewest conflicts among
            languages that have at least one, or ``None``.
        """
        best: Optional[str] = None
        best_count: Optional[int] = None
        for lang, conflicts in self.by_language.items():
            n = len(conflicts)
            if n > 0 and (best_count is None or n < best_count):
                best = lang
                best_count = n
        return best

    def languages_above_threshold(self, n: int) -> _List[str]:
        """FC217: Return languages with more than *n* conflicts.

        Parameters
        ----------
        n:
            Minimum conflict count threshold (exclusive).  Languages with
            ``len(conflicts) > n`` are returned.

        Returns
        -------
        List[str]
            Sorted list of ISO 639-1 language codes whose conflict count
            exceeds *n*.  Empty when no language exceeds the threshold.
        """
        return sorted(
            lang for lang, conflicts in self.by_language.items()
            if len(conflicts) > n
        )


def detect_all_languages(text: str) -> "I18NConflictReport":
    """CT156/DJ172/DN176/DO177/ED192/EM201/FK225/FL226/FU235/FV236: Run full-clause conflict detection across all supported languages.

    Calls :func:`~logic.CEC.nl.nl_policy_conflict_detector.detect_i18n_clauses`
    for French (``"fr"``), Spanish (``"es"``), German (``"de"``),
    English (``"en"``), Portuguese (``"pt"``), Dutch (``"nl"``),
    Italian (``"it"``), Japanese (``"ja"``), Chinese (``"zh"``),
    Korean (``"ko"``), Arabic (``"ar"``), Swedish (``"sv"``), and
    Russian (``"ru"``),
    and returns a combined :class:`I18NConflictReport`.

    English, Dutch, Italian, Japanese, Chinese, Korean, Arabic, Swedish, and
    Russian passes use inline deontic keywords (no separate parser module is
    required) so they are always available.  Portuguese requires
    ``portuguese_parser.py``; an ``ImportError`` results in an empty list for
    that language slot.

    Parameters
    ----------
    text:
        Raw natural-language text to analyse.

    Returns
    -------
    :class:`I18NConflictReport`
        Report with per-language conflict lists (empty list when no conflict
        or when the parser module is unavailable).
    """
    _SUPPORTED_LANGS = ("fr", "es", "de", "en", "pt", "nl", "it", "ja", "zh", "ko", "ar", "sv", "ru", "el", "tr", "hi", "pl", "vi", "th", "id")  # FK225/FL226/FU235/FV236/GA241/GB242/GC243/GL252/GM253/GV262/GW263
    report = I18NConflictReport()
    try:
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (  # noqa: F401
            detect_i18n_clauses as _detect_i18n_clauses,
        )
        _available = True
    except (ImportError, ModuleNotFoundError):
        _available = False
    for lang in _SUPPORTED_LANGS:
        if _available:
            try:
                report.by_language[lang] = _detect_i18n_clauses(text, lang)
            except Exception:
                report.by_language[lang] = []
        else:
            report.by_language[lang] = []
    return report


# CT156: extend __all__
__all__ += ["I18NConflictReport", "detect_all_languages"]

# DW185: compile_explain_iter re-export
_DW185_COMPILER_AVAILABLE = False
try:
    from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (  # type: ignore[import-not-found]
        NLUCANPolicyCompiler as _NLUCANPolicyCompiler_dw185,
    )
    # compile_explain_iter is an instance method; expose a module-level wrapper
    def compile_explain_iter(sentences: _List[str], policy_id: Optional[str] = None, max_lines: Optional[int] = None):  # type: ignore[misc]
        """DW185: Module-level wrapper for :meth:`NLUCANPolicyCompiler.compile_explain_iter`.

        Creates a fresh :class:`NLUCANPolicyCompiler` and delegates to its
        ``compile_explain_iter`` method.  Returns a generator of explanation lines.

        Parameters
        ----------
        sentences:
            Plain-English policy statements.
        policy_id:
            Optional policy identifier override.
        max_lines:
            Optional limit on lines yielded (``None`` = all lines).

        Yields
        ------
        str
            Explanation lines.
        """
        compiler = _NLUCANPolicyCompiler_dw185()
        yield from compiler.compile_explain_iter(sentences, policy_id=policy_id, max_lines=max_lines)
    _DW185_COMPILER_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    pass

if _DW185_COMPILER_AVAILABLE:
    __all__ += ["compile_explain_iter"]
