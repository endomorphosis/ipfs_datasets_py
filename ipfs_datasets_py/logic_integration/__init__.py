"""
SymbolicAI Logic Integration Module

This module provides integration between SymbolicAI and the IPFS Datasets FOL system,
enabling enhanced natural language understanding, semantic reasoning, and contract-based
validation for logical formula construction.

Key Components:
- SymbolicFOLBridge: Core bridge between SymbolicAI and FOL system
- SymbolicLogicPrimitives: Custom logic primitives for SymbolicAI
- SymbolicContracts: Contract-based validation for logic formulas
- InteractiveFOLConstructor: Interactive logic construction interface
- ModalLogicExtension: Extended support for modal and temporal logic
- LogicVerification: Advanced logic verification and proof support

Usage:
    from ipfs_datasets_py.logic_integration import SymbolicFOLBridge
    
    bridge = SymbolicFOLBridge()
    symbol = bridge.create_semantic_symbol("All cats are animals")
    fol_formula = bridge.semantic_to_fol(symbol)
"""

from typing import TYPE_CHECKING

# Version information
__version__ = "0.1.0"
__author__ = "IPFS Datasets Python Team"

# Core exports
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
