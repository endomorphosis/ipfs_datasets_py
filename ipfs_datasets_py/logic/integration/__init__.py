"""Deontic logic integration package.

This package exposes a large surface area spanning converters, caching, reasoning,
bridges, and optional SymbolicAI tooling.

Import policy:
- Importing `ipfs_datasets_py.logic.integration` must be quiet/deterministic.
- Optional/heavy submodules are lazy-loaded via module-level `__getattr__`.
"""

from __future__ import annotations

import importlib
import os

__version__ = "0.2.0"
__author__ = "IPFS Datasets Python Team"


# ---------------------------------------------------------------------------
# SymbolicAI interactive tools (opt-in)
# ---------------------------------------------------------------------------

SYMBOLIC_AI_AVAILABLE = False


class _SymbolicAINotAvailable:
    def __init__(self, *args, **kwargs):
        raise ImportError(
            "SymbolicAI is not available. Install symai and call enable_symbolicai() to enable it."
        )


def _symbolicai_unavailable(*args, **kwargs):
    raise ImportError(
        "SymbolicAI is not available. Install symai and call enable_symbolicai() to enable it."
    )


# Default placeholders; become real objects after `enable_symbolicai()`.
InteractiveFOLConstructor = _SymbolicAINotAvailable
StatementRecord = None
SessionMetadata = None
create_interactive_session = _symbolicai_unavailable
demo_interactive_session = _symbolicai_unavailable


def enable_symbolicai(*, autoconfigure_env: bool | None = None) -> bool:
    """Enable SymbolicAI-backed interactive tooling.

    This is intentionally opt-in to avoid import-time side effects.

    Args:
        autoconfigure_env: If True, calls `autoconfigure_engine_env()` before
            importing `symai`. If None, controlled by env var
            `IPFS_DATASETS_SYMBOLICAI_AUTOCONFIGURE`.

    Returns:
        True if SymbolicAI tooling is available after enabling.
    """

    global SYMBOLIC_AI_AVAILABLE
    global InteractiveFOLConstructor, StatementRecord, SessionMetadata
    global create_interactive_session, demo_interactive_session

    if SYMBOLIC_AI_AVAILABLE:
        return True

    if autoconfigure_env is None:
        autoconfigure_env = os.environ.get("IPFS_DATASETS_SYMBOLICAI_AUTOCONFIGURE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }

    try:
        if autoconfigure_env:
            from ...utils.engine_env import autoconfigure_engine_env

            autoconfigure_engine_env()

        import symai  # noqa: F401

        from .interactive.interactive_fol_constructor import InteractiveFOLConstructor
        from .interactive.interactive_fol_types import SessionMetadata, StatementRecord
        from .interactive.interactive_fol_utils import create_interactive_session, demo_interactive_session

        SYMBOLIC_AI_AVAILABLE = True
        return True
    except (ImportError, SystemExit):
        SYMBOLIC_AI_AVAILABLE = False
        return False


DEFAULT_CONFIG = {
    "confidence_threshold": 0.7,
    "fallback_to_original": True,
    "enable_caching": True,
    "max_reasoning_steps": 10,
    "validation_strict": True,
}


# ---------------------------------------------------------------------------
# Lazy exports
# ---------------------------------------------------------------------------

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Converters subsystem
    "DeonticOperator": (".converters.deontic_logic_core", "DeonticOperator"),
    "DeonticFormula": (".converters.deontic_logic_core", "DeonticFormula"),
    "DeonticRuleSet": (".converters.deontic_logic_core", "DeonticRuleSet"),
    "LegalAgent": (".converters.deontic_logic_core", "LegalAgent"),
    "LegalContext": (".converters.deontic_logic_core", "LegalContext"),
    "TemporalCondition": (".converters.deontic_logic_core", "TemporalCondition"),
    "TemporalOperator": (".converters.deontic_logic_core", "TemporalOperator"),
    "DeonticLogicValidator": (".converters.deontic_logic_core", "DeonticLogicValidator"),
    "create_obligation": (".converters.deontic_logic_core", "create_obligation"),
    "create_permission": (".converters.deontic_logic_core", "create_permission"),
    "create_prohibition": (".converters.deontic_logic_core", "create_prohibition"),

    "DeonticLogicConverter": (".converters.deontic_logic_converter", "DeonticLogicConverter"),
    "ConversionContext": (".converters.deontic_logic_converter", "ConversionContext"),
    "ConversionResult": (".converters.deontic_logic_converter", "ConversionResult"),

    "LogicTranslationTarget": (".converters.logic_translation_core", "LogicTranslationTarget"),
    "TranslationResult": (".converters.logic_translation_core", "TranslationResult"),
    "AbstractLogicFormula": (".converters.logic_translation_core", "AbstractLogicFormula"),
    "LogicTranslator": (".converters.logic_translation_core", "LogicTranslator"),
    "LeanTranslator": (".converters.logic_translation_core", "LeanTranslator"),
    "CoqTranslator": (".converters.logic_translation_core", "CoqTranslator"),
    "SMTTranslator": (".converters.logic_translation_core", "SMTTranslator"),

    "ModalLogicSymbol": (".converters.modal_logic_extension", "ModalLogicSymbol"),
    "AdvancedLogicConverter": (".converters.modal_logic_extension", "AdvancedLogicConverter"),
    "ModalFormula": (".converters.modal_logic_extension", "ModalFormula"),
    "LogicClassification": (".converters.modal_logic_extension", "LogicClassification"),

    # Caching subsystem
    "LogicIPLDStorage": (".caching.ipld_logic_storage", "LogicIPLDStorage"),
    "LogicProvenanceTracker": (".caching.ipld_logic_storage", "LogicProvenanceTracker"),
    "LogicIPLDNode": (".caching.ipld_logic_storage", "LogicIPLDNode"),
    "LogicProvenanceChain": (".caching.ipld_logic_storage", "LogicProvenanceChain"),
    "create_logic_storage_with_provenance": (
        ".caching.ipld_logic_storage",
        "create_logic_storage_with_provenance",
    ),

    # Domain subsystem
    "LegalDomainKnowledge": (".domain.legal_domain_knowledge", "LegalDomainKnowledge"),
    "LegalDomain": (".domain.legal_domain_knowledge", "LegalDomain"),
    "LegalConceptType": (".domain.legal_domain_knowledge", "LegalConceptType"),
    "LegalPattern": (".domain.legal_domain_knowledge", "LegalPattern"),
    "AgentPattern": (".domain.legal_domain_knowledge", "AgentPattern"),

    "LegalSymbolicAnalyzer": (".domain.legal_symbolic_analyzer", "LegalSymbolicAnalyzer"),
    "LegalReasoningEngine": (".domain.legal_symbolic_analyzer", "LegalReasoningEngine"),
    "LegalAnalysisResult": (".domain.legal_symbolic_analyzer", "LegalAnalysisResult"),
    "DeonticProposition": (".domain.legal_symbolic_analyzer", "DeonticProposition"),
    "LegalEntity": (".domain.legal_symbolic_analyzer", "LegalEntity"),
    "create_legal_analyzer": (".domain.legal_symbolic_analyzer", "create_legal_analyzer"),
    "create_legal_reasoning_engine": (
        ".domain.legal_symbolic_analyzer",
        "create_legal_reasoning_engine",
    ),

    "DeonticQueryEngine": (".domain.deontic_query_engine", "DeonticQueryEngine"),
    "QueryType": (".domain.deontic_query_engine", "QueryType"),
    "QueryResult": (".domain.deontic_query_engine", "QueryResult"),
    "ComplianceResult": (".domain.deontic_query_engine", "ComplianceResult"),
    "LogicConflict": (".domain.deontic_query_engine", "LogicConflict"),
    "create_query_engine": (".domain.deontic_query_engine", "create_query_engine"),
    "query_legal_rules": (".domain.deontic_query_engine", "query_legal_rules"),

    # Reasoning subsystem
    "DeontologicalReasoningEngine": (
        ".reasoning.deontological_reasoning",
        "DeontologicalReasoningEngine",
    ),
    "DeonticModality": (".reasoning.deontological_reasoning", "DeonticModality"),
    "ConflictType": (".reasoning.deontological_reasoning", "ConflictType"),
    "DeonticStatement": (".reasoning.deontological_reasoning", "DeonticStatement"),
    "DeonticConflict": (".reasoning.deontological_reasoning", "DeonticConflict"),
    "DeonticExtractor": (".reasoning.deontological_reasoning", "DeonticExtractor"),
    "ConflictDetector": (".reasoning.deontological_reasoning", "ConflictDetector"),
    "DeonticPatterns": (".reasoning.deontological_reasoning", "DeonticPatterns"),

    "ProofExecutionEngine": (".reasoning.proof_execution_engine", "ProofExecutionEngine"),
    "ProofResult": (".reasoning.proof_execution_engine", "ProofResult"),
    "ProofStatus": (".reasoning.proof_execution_engine", "ProofStatus"),
    "create_proof_engine": (".reasoning.proof_execution_engine", "create_proof_engine"),
    "prove_formula": (".reasoning.proof_execution_engine", "prove_formula"),
    "prove_with_all_provers": (
        ".reasoning.proof_execution_engine",
        "prove_with_all_provers",
    ),
    "check_consistency": (".reasoning.proof_execution_engine", "check_consistency"),

    "LogicVerifier": (".reasoning.logic_verification", "LogicVerifier"),
    "LogicAxiom": (".reasoning.logic_verification", "LogicAxiom"),
    "ConsistencyCheck": (".reasoning.logic_verification", "ConsistencyCheck"),
    "EntailmentResult": (".reasoning.logic_verification", "EntailmentResult"),

    # Bridges / primitives
    "SymbolicFOLBridge": (".bridges.symbolic_fol_bridge", "SymbolicFOLBridge"),
    "LogicPrimitives": (".symbolic.symbolic_logic_primitives", "LogicPrimitives"),
    "create_logic_symbol": (".symbolic.symbolic_logic_primitives", "create_logic_symbol"),

    # Symbolic contracts (pydantic optional)
    "FOLInput": (".domain.symbolic_contracts", "FOLInput"),
    "FOLOutput": (".domain.symbolic_contracts", "FOLOutput"),
    "ContractedFOLConverter": (".domain.symbolic_contracts", "ContractedFOLConverter"),
    "create_fol_converter": (".domain.symbolic_contracts", "create_fol_converter"),
    "validate_fol_input": (".domain.symbolic_contracts", "validate_fol_input"),

    # Optional bridges
    "TDFOLCECBridge": (".bridges.tdfol_cec_bridge", "TDFOLCECBridge"),
    "EnhancedTDFOLProver": (".bridges.tdfol_cec_bridge", "EnhancedTDFOLProver"),
    "create_enhanced_prover": (".bridges.tdfol_cec_bridge", "create_enhanced_prover"),

    "TDFOLShadowProverBridge": (
        ".bridges.tdfol_shadowprover_bridge",
        "TDFOLShadowProverBridge",
    ),
    "ModalAwareTDFOLProver": (
        ".bridges.tdfol_shadowprover_bridge",
        "ModalAwareTDFOLProver",
    ),
    "ModalLogicType": (".bridges.tdfol_shadowprover_bridge", "ModalLogicType"),
    "create_modal_aware_prover": (
        ".bridges.tdfol_shadowprover_bridge",
        "create_modal_aware_prover",
    ),

    "TDFOLGrammarBridge": (".bridges.tdfol_grammar_bridge", "TDFOLGrammarBridge"),
    "NaturalLanguageTDFOLInterface": (
        ".bridges.tdfol_grammar_bridge",
        "NaturalLanguageTDFOLInterface",
    ),
    "parse_nl": (".bridges.tdfol_grammar_bridge", "parse_nl"),
    "explain_formula": (".bridges.tdfol_grammar_bridge", "explain_formula"),

    # Optional neurosymbolic API
    "NeurosymbolicReasoner": (".symbolic.neurosymbolic_api", "NeurosymbolicReasoner"),
    "ReasoningCapabilities": (".symbolic.neurosymbolic_api", "ReasoningCapabilities"),
    "get_reasoner": (".symbolic.neurosymbolic_api", "get_reasoner"),
}


_AVAILABILITY_EXPORTS: dict[str, str] = {
    "TDFOL_CEC_AVAILABLE": ".bridges.tdfol_cec_bridge",
    "TDFOL_SHADOWPROVER_AVAILABLE": ".bridges.tdfol_shadowprover_bridge",
    "TDFOL_GRAMMAR_AVAILABLE": ".bridges.tdfol_grammar_bridge",
    "NEUROSYMBOLIC_API_AVAILABLE": ".symbolic.neurosymbolic_api",
}


def __getattr__(name: str):
    if name in _AVAILABILITY_EXPORTS:
        module_name = _AVAILABILITY_EXPORTS[name]
        try:
            importlib.import_module(module_name, __name__)
            value = True
        except Exception:
            value = False
        globals()[name] = value
        return value

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(
        set(list(globals().keys()) + list(_LAZY_EXPORTS.keys()) + list(_AVAILABILITY_EXPORTS.keys()))
    )


__all__ = sorted(
    {
        "__version__",
        "__author__",
        "DEFAULT_CONFIG",
        "SYMBOLIC_AI_AVAILABLE",
        "enable_symbolicai",
        "InteractiveFOLConstructor",
        "StatementRecord",
        "SessionMetadata",
        "create_interactive_session",
        "demo_interactive_session",
        *_LAZY_EXPORTS.keys(),
        *_AVAILABILITY_EXPORTS.keys(),
    }
)
