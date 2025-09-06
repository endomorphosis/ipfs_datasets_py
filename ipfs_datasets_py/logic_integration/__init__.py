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
    from ipfs_datasets_py.logic_integration import (
        DeonticLogicConverter, LegalDomainKnowledge, ConversionContext
    )
    
    # Convert GraphRAG to deontic logic
    knowledge = LegalDomainKnowledge()
    converter = DeonticLogicConverter(knowledge)
    context = ConversionContext("contract.pdf", legal_domain=LegalDomain.CONTRACT)
    result = converter.convert_knowledge_graph_to_logic(knowledge_graph, context)
    
    # Translate to theorem provers
    from ipfs_datasets_py.logic_integration import LeanTranslator, CoqTranslator
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
from .deontic_logic_core import (
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
from .logic_translation_core import (
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

# Legacy SymbolicAI exports
from .symbolic_fol_bridge import SymbolicFOLBridge
from .symbolic_logic_primitives import LogicPrimitives
from .symbolic_contracts import (
    ContractedFOLConverter,
    FOLInput,
    FOLOutput,
)

# Optional imports (only available if SymbolicAI is installed)
try:
    import symai
    SYMBOLIC_AI_AVAILABLE = True
    
    # Export advanced components only if SymbolicAI is available
    from .interactive_fol_constructor import InteractiveFOLConstructor
    from .modal_logic_extension import ModalLogicSymbol, AdvancedLogicConverter, ModalFormula, LogicClassification
    from .logic_verification import LogicVerifier, LogicAxiom, ProofResult, ConsistencyCheck, EntailmentResult
    
    __all__ = [
        "SymbolicFOLBridge",        "LogicPrimitives",
        "ContractedFOLConverter",
        "FOLInput",
        "FOLOutput",
        "InteractiveFOLConstructor",
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
    
except ImportError:
    SYMBOLIC_AI_AVAILABLE = False
    
    # Provide fallback stubs when SymbolicAI is not available
    class _SymbolicAINotAvailable:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "SymbolicAI is not installed. Install with: pip install symbolicai>=0.13.1"
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
