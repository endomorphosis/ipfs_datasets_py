"""
Deontic Logic Integration Module for Legal Document Processing

This module provides comprehensive integration between SymbolicAI and deontic first-order logic
for legal document processing, enabling conversion of GraphRAG-processed documents into formal
logic representations compatible with multiple theorem provers.

Organized into subdirectories:
- bridges/: Prover and system bridges
- caching/: Proof caching systems
- reasoning/: Core reasoning engines
- converters/: Format converters
- domain/: Domain-specific tools (legal, medical, contracts)
- interactive/: Interactive construction tools
- symbolic/: SymbolicAI integration
- demos/: Demonstration scripts
"""

from typing import TYPE_CHECKING

import os

# Version information
__version__ = "0.2.0"
__author__ = "IPFS Datasets Python Team"

# ============================================================================
# Core Exports - Updated for new subdirectory structure
# ============================================================================

# Converters subsystem
from .converters.deontic_logic_core import (
    DeonticOperator, DeonticFormula, DeonticRuleSet, LegalAgent, LegalContext,
    TemporalCondition, TemporalOperator, DeonticLogicValidator,
    create_obligation, create_permission, create_prohibition
)
from .converters.deontic_logic_converter import (
    DeonticLogicConverter, ConversionContext, ConversionResult
)
from .converters.logic_translation_core import (
    LogicTranslationTarget, TranslationResult, AbstractLogicFormula, LogicTranslator,
    LeanTranslator, CoqTranslator, SMTTranslator
)
from .converters.modal_logic_extension import (
    ModalLogicSymbol, AdvancedLogicConverter, ModalFormula, LogicClassification
)

# Caching subsystem  
from .caching.ipld_logic_storage import (
    LogicIPLDStorage, LogicProvenanceTracker, LogicIPLDNode,
    LogicProvenanceChain, create_logic_storage_with_provenance
)

# Domain subsystem
from .domain.legal_domain_knowledge import (
    LegalDomainKnowledge, LegalDomain, LegalConceptType, LegalPattern, AgentPattern
)
from .domain.legal_symbolic_analyzer import (
    LegalSymbolicAnalyzer, LegalReasoningEngine, LegalAnalysisResult,
    DeonticProposition, LegalEntity, create_legal_analyzer, create_legal_reasoning_engine
)
from .domain.deontic_query_engine import (
    DeonticQueryEngine, QueryType, QueryResult, ComplianceResult,
    LogicConflict, create_query_engine, query_legal_rules
)

# Reasoning subsystem
from .reasoning.deontological_reasoning import (
    DeontologicalReasoningEngine, DeonticModality, ConflictType, DeonticStatement,
    DeonticConflict, DeonticExtractor, ConflictDetector, DeonticPatterns
)
from .reasoning.proof_execution_engine import (
    ProofExecutionEngine, ProofResult, ProofStatus, create_proof_engine,
    prove_formula, prove_with_all_provers, check_consistency
)
from .reasoning.logic_verification import (
    LogicVerifier, LogicAxiom, ConsistencyCheck, EntailmentResult
)

# Domain - Optional exports (require numpy)
try:
    from .domain.temporal_deontic_rag_store import (
        TemporalDeonticRAGStore, TheoremMetadata, ConsistencyResult
    )
except ImportError:
    TemporalDeonticRAGStore = None
    TheoremMetadata = None
    ConsistencyResult = None

try:
    from .domain.document_consistency_checker import (
        DocumentConsistencyChecker, DocumentAnalysis, DebugReport
    )
except ImportError:
    DocumentConsistencyChecker = None
    DocumentAnalysis = None
    DebugReport = None

# Bridges subsystem - SymbolicFOLBridge
from .bridges.symbolic_fol_bridge import SymbolicFOLBridge
# Symbolic subsystem - LogicPrimitives
from .symbolic.symbolic_logic_primitives import LogicPrimitives, create_logic_symbol

try:
    from .domain.symbolic_contracts import (
        ContractedFOLConverter, FOLInput, FOLOutput, create_fol_converter, validate_fol_input
    )
    SYMBOLIC_CONTRACTS_AVAILABLE = True
except ImportError:
    ContractedFOLConverter = None
    FOLInput = None
    FOLOutput = None
    create_fol_converter = None
    validate_fol_input = None
    SYMBOLIC_CONTRACTS_AVAILABLE = False

# Bridges subsystem - TDFOL integrations
try:
    from .bridges.tdfol_cec_bridge import TDFOLCECBridge, EnhancedTDFOLProver, create_enhanced_prover
    TDFOL_CEC_AVAILABLE = True
except ImportError:
    TDFOL_CEC_AVAILABLE = False
    TDFOLCECBridge = None
    EnhancedTDFOLProver = None
    create_enhanced_prover = None

try:
    from .bridges.tdfol_shadowprover_bridge import (
        TDFOLShadowProverBridge, ModalAwareTDFOLProver, ModalLogicType, create_modal_aware_prover
    )
    TDFOL_SHADOWPROVER_AVAILABLE = True
except ImportError:
    TDFOL_SHADOWPROVER_AVAILABLE = False
    TDFOLShadowProverBridge = None
    ModalAwareTDFOLProver = None
    ModalLogicType = None
    create_modal_aware_prover = None

try:
    from .bridges.tdfol_grammar_bridge import (
        TDFOLGrammarBridge, NaturalLanguageTDFOLInterface, parse_nl, explain_formula
    )
    TDFOL_GRAMMAR_AVAILABLE = True
except ImportError:
    TDFOL_GRAMMAR_AVAILABLE = False
    TDFOLGrammarBridge = None
    NaturalLanguageTDFOLInterface = None
    parse_nl = None
    explain_formula = None

# Symbolic - Neurosymbolic API
try:
    from .symbolic.neurosymbolic_api import NeurosymbolicReasoner, ReasoningCapabilities, get_reasoner
    NEUROSYMBOLIC_API_AVAILABLE = True
except ImportError:
    NEUROSYMBOLIC_API_AVAILABLE = False
    NeurosymbolicReasoner = None
    ReasoningCapabilities = None
    get_reasoner = None

# SymbolicAI interactive tools (lazy/opt-in)
#
# Importing `ipfs_datasets_py.logic.integration` should be deterministic and must
# not mutate environment at import time. SymbolicAI setup is therefore lazy.
SYMBOLIC_AI_AVAILABLE = False


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
            from ..utils.engine_env import autoconfigure_engine_env

            autoconfigure_engine_env()

        import symai  # noqa: F401

        from .interactive.interactive_fol_constructor import InteractiveFOLConstructor
        from .interactive.interactive_fol_types import StatementRecord, SessionMetadata
        from .interactive.interactive_fol_utils import create_interactive_session, demo_interactive_session

        SYMBOLIC_AI_AVAILABLE = True
        return True
    except (ImportError, SystemExit):
        SYMBOLIC_AI_AVAILABLE = False
        return False


class _SymbolicAINotAvailable:
    def __init__(self, *args, **kwargs):
        raise ImportError(
            "SymbolicAI is not available. Install symai and call enable_symbolicai() to enable it."
        )


# Default placeholder; becomes the real class after `enable_symbolicai()`.
InteractiveFOLConstructor = _SymbolicAINotAvailable

# Configuration
DEFAULT_CONFIG = {
    "confidence_threshold": 0.7,
    "fallback_to_original": True,
    "enable_caching": True,
    "max_reasoning_steps": 10,
    "validation_strict": True
}

__all__ = [
    "DeonticLogicConverter", "ConversionContext", "ConversionResult",
    "LegalDomainKnowledge", "ProofExecutionEngine", "DeontologicalReasoningEngine",
    "SymbolicFOLBridge", "LogicPrimitives", "TDFOLCECBridge", "TDFOLGrammarBridge",
    "SYMBOLIC_AI_AVAILABLE", "TDFOL_CEC_AVAILABLE", "TDFOL_GRAMMAR_AVAILABLE"
]
