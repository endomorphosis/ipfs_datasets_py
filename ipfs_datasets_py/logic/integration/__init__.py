"""
Deontic Logic Integration Module for Legal Document Processing

This module provides comprehensive integration between SymbolicAI and deontic first-order logic
for legal document processing, enabling conversion of GraphRAG-processed documents into formal
logic representations compatible with multiple theorem provers.

Key Components:
- DeonticLogicCore: Core deontic logic primitives and data structures
- LegalDomainKnowledge: Legal domain knowledge base for pattern recognition
- DeonticLogicConverter: Main converter from GraphRAG to deontic logic
- LogicTranslationCore: Multi-theorem prover translation engine
- SymbolicFOLBridge: Core bridge between SymbolicAI and FOL system
- SymbolicLogicPrimitives: Custom logic primitives for SymbolicAI
- SymbolicContracts: Contract-based validation for logic formulas
- InteractiveFOLConstructor: Interactive logic construction interface
- ModalLogicExtension: Extended support for modal and temporal logic
- LogicVerification: Advanced logic verification and proof support

Usage:
    from ipfs_datasets_py.logic.integration import (
        DeonticLogicConverter, LegalDomainKnowledge, ConversionContext
    )
    
    # Convert GraphRAG to deontic logic
    knowledge = LegalDomainKnowledge()
    converter = DeonticLogicConverter(knowledge)
    context = ConversionContext("contract.pdf", legal_domain=LegalDomain.CONTRACT)
    result = converter.convert_knowledge_graph_to_logic(knowledge_graph, context)
    
    # Translate to theorem provers
    from ipfs_datasets_py.logic.integration import LeanTranslator, CoqTranslator
    lean_translator = LeanTranslator()
    coq_translator = CoqTranslator()
    
    for formula in result.deontic_formulas:
        lean_result = lean_translator.translate_deontic_formula(formula)
        coq_result = coq_translator.translate_deontic_formula(formula)
"""

from typing import TYPE_CHECKING

# Version information
__version__ = "0.2.0"
__author__ = "IPFS Datasets Python Team"

# Core deontic logic exports
from ..tools.deontic_logic_core import (
    DeonticOperator,
    DeonticFormula,
    DeonticRuleSet,
    LegalAgent,
    LegalContext,
    TemporalCondition,
    TemporalOperator,
    DeonticLogicValidator,
    create_obligation,
    create_permission,
    create_prohibition
)

# Legal domain knowledge exports
from .legal_domain_knowledge import (
    LegalDomainKnowledge,
    LegalDomain,
    LegalConceptType,
    LegalPattern,
    AgentPattern
)

# Logic translation exports
from ..tools.logic_translation_core import (
    LogicTranslationTarget,
    TranslationResult,
    AbstractLogicFormula,
    LogicTranslator,
    LeanTranslator,
    CoqTranslator,
    SMTTranslator
)

# Main conversion engine exports
from .deontic_logic_converter import (
    DeonticLogicConverter,
    ConversionContext,
    ConversionResult
)

# IPLD logic storage exports
from .ipld_logic_storage import (
    LogicIPLDStorage,
    LogicProvenanceTracker,
    LogicIPLDNode,
    LogicProvenanceChain,
    create_logic_storage_with_provenance
)

# Legal SymbolicAI analysis exports
from .legal_symbolic_analyzer import (
    LegalSymbolicAnalyzer,
    LegalReasoningEngine,
    LegalAnalysisResult,
    DeonticProposition,
    LegalEntity,
    create_legal_analyzer,
    create_legal_reasoning_engine
)

# Deontic logic query engine exports
from .deontic_query_engine import (
    DeonticQueryEngine,
    QueryType,
    QueryResult,
    ComplianceResult,
    LogicConflict,
    create_query_engine,
    query_legal_rules
)

# Deontological reasoning exports
from .deontological_reasoning import (
    DeontologicalReasoningEngine,
    DeonticModality,
    ConflictType,
    DeonticStatement,
    DeonticConflict,
    DeonticExtractor,
    ConflictDetector,
    DeonticPatterns,
)

# Proof execution engine exports
from .proof_execution_engine import (
    ProofExecutionEngine,
    ProofResult,
    ProofStatus,
    create_proof_engine,
    prove_formula,
    prove_with_all_provers,
    check_consistency
)

# Temporal deontic RAG system exports (optional - requires numpy)
try:
    from .temporal_deontic_rag_store import (
        TemporalDeonticRAGStore,
        TheoremMetadata,
        ConsistencyResult
    )
except ImportError:
    TemporalDeonticRAGStore = None
    TheoremMetadata = None
    ConsistencyResult = None

# Document consistency checker exports (optional - requires numpy)
try:
    from .document_consistency_checker import (
        DocumentConsistencyChecker,
        DocumentAnalysis,
        DebugReport
    )
except ImportError:
    DocumentConsistencyChecker = None
    DocumentAnalysis = None
    DebugReport = None

# Legacy SymbolicAI exports
from ..tools.symbolic_fol_bridge import SymbolicFOLBridge
from ..tools.symbolic_logic_primitives import LogicPrimitives, create_logic_symbol

# Symbolic contracts (optional - requires pydantic)
try:
    from .symbolic_contracts import (
        ContractedFOLConverter,
        FOLInput,
        FOLOutput,
        create_fol_converter,
        validate_fol_input,
    )
    SYMBOLIC_CONTRACTS_AVAILABLE = True
except ImportError:
    ContractedFOLConverter = None
    FOLInput = None
    FOLOutput = None
    create_fol_converter = None
    validate_fol_input = None
    SYMBOLIC_CONTRACTS_AVAILABLE = False

# Optional imports (only available if SymbolicAI is installed)
try:
    # Attempt to populate required engine env vars from existing auth (e.g. OPENAI_API_KEY)
    from ..utils.engine_env import autoconfigure_engine_env
    autoconfigure_engine_env()

    import symai
    SYMBOLIC_AI_AVAILABLE = True
    
    # Export advanced components only if SymbolicAI is available
    from .interactive_fol_constructor import InteractiveFOLConstructor
    from .interactive_fol_types import StatementRecord, SessionMetadata
    from .interactive_fol_utils import create_interactive_session, demo_interactive_session
    from ..tools.modal_logic_extension import ModalLogicSymbol, AdvancedLogicConverter, ModalFormula, LogicClassification
    from .logic_verification import LogicVerifier, LogicAxiom, ProofResult, ConsistencyCheck, EntailmentResult
    
    __all__ = [
        "SymbolicFOLBridge",        "LogicPrimitives",
        "ContractedFOLConverter",
        "FOLInput",
        "FOLOutput",
        "create_logic_symbol",
        "create_fol_converter",
        "validate_fol_input",
        "InteractiveFOLConstructor",
        "StatementRecord",
        "SessionMetadata",
        "create_interactive_session",
        "demo_interactive_session",
        "ModalLogicSymbol",
        "AdvancedLogicConverter",
        "ModalFormula",
        "LogicClassification", 
        "LogicVerifier",
        "LogicAxiom",
        "ProofResult",
        "ConsistencyCheck",
        "EntailmentResult",
        "SYMBOLIC_AI_AVAILABLE"
    ]
    
except (ImportError, SystemExit):
    SYMBOLIC_AI_AVAILABLE = False
    
    # Provide fallback stubs when SymbolicAI is not available
    class _SymbolicAINotAvailable:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "SymbolicAI is not available (not installed or misconfigured). "
                "To enable it, install and configure SymbolicAI (symai)."
            )
    
    InteractiveFOLConstructor = _SymbolicAINotAvailable
    ModalLogicSymbol = _SymbolicAINotAvailable
    AdvancedLogicConverter = _SymbolicAINotAvailable
    LogicVerifier = _SymbolicAINotAvailable
    
    __all__ = [
        "SymbolicFOLBridge",
        "LogicPrimitives",
        "ContractedFOLConverter", 
        "FOLInput",
        "FOLOutput",
        "create_logic_symbol",
        "create_fol_converter",
        "validate_fol_input",
        "SYMBOLIC_AI_AVAILABLE"
    ]

# Configuration
DEFAULT_CONFIG = {
    "confidence_threshold": 0.7,
    "fallback_to_original": True,
    "enable_caching": True,
    "max_reasoning_steps": 10,
    "validation_strict": True
}

# ============================================================================
# TDFOL-CEC-ShadowProver Integration (Neurosymbolic Architecture)
# ============================================================================

# TDFOL-CEC Bridge exports
try:
    from .tdfol_cec_bridge import (
        TDFOLCECBridge,
        EnhancedTDFOLProver,
        create_enhanced_prover,
    )
    TDFOL_CEC_AVAILABLE = True
except ImportError as e:
    TDFOL_CEC_AVAILABLE = False
    TDFOLCECBridge = None
    EnhancedTDFOLProver = None
    create_enhanced_prover = None

# TDFOL-ShadowProver Bridge exports
try:
    from .tdfol_shadowprover_bridge import (
        TDFOLShadowProverBridge,
        ModalAwareTDFOLProver,
        ModalLogicType,
        create_modal_aware_prover,
    )
    TDFOL_SHADOWPROVER_AVAILABLE = True
except ImportError as e:
    TDFOL_SHADOWPROVER_AVAILABLE = False
    TDFOLShadowProverBridge = None
    ModalAwareTDFOLProver = None
    ModalLogicType = None
    create_modal_aware_prover = None

# TDFOL-Grammar Bridge exports
try:
    from .tdfol_grammar_bridge import (
        TDFOLGrammarBridge,
        NaturalLanguageTDFOLInterface,
        parse_nl,
        explain_formula,
    )
    TDFOL_GRAMMAR_AVAILABLE = True
except ImportError as e:
    TDFOL_GRAMMAR_AVAILABLE = False
    TDFOLGrammarBridge = None
    NaturalLanguageTDFOLInterface = None
    parse_nl = None
    explain_formula = None

# Unified Neurosymbolic API
try:
    from .neurosymbolic_api import (
        NeurosymbolicReasoner,
        ReasoningCapabilities,
        get_reasoner,
    )
    NEUROSYMBOLIC_API_AVAILABLE = True
except ImportError as e:
    NEUROSYMBOLIC_API_AVAILABLE = False
    NeurosymbolicReasoner = None
    ReasoningCapabilities = None
    get_reasoner = None

# Update __all__ to include neurosymbolic exports
if NEUROSYMBOLIC_API_AVAILABLE:
    __all__.extend([
        # TDFOL-CEC Bridge
        "TDFOLCECBridge",
        "EnhancedTDFOLProver",
        "create_enhanced_prover",
        "TDFOL_CEC_AVAILABLE",
        
        # TDFOL-ShadowProver Bridge
        "TDFOLShadowProverBridge",
        "ModalAwareTDFOLProver",
        "ModalLogicType",
        "create_modal_aware_prover",
        "TDFOL_SHADOWPROVER_AVAILABLE",
        
        # TDFOL-Grammar Bridge
        "TDFOLGrammarBridge",
        "NaturalLanguageTDFOLInterface",
        "parse_nl",
        "explain_formula",
        "TDFOL_GRAMMAR_AVAILABLE",
        
        # Unified API
        "NeurosymbolicReasoner",
        "ReasoningCapabilities",
        "get_reasoner",
        "NEUROSYMBOLIC_API_AVAILABLE",
    ])

