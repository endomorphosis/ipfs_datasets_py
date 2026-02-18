"""
Temporal Deontic First-Order Logic (TDFOL) Module

This module provides a unified framework for reasoning about temporal, deontic,
and first-order logic. It combines:
- First-Order Logic (FOL): predicates, quantifiers, variables, functions
- Deontic Logic: obligations (O), permissions (P), prohibitions (F)
- Temporal Logic: temporal operators (□, ◊, X, U, S)

The TDFOL system enables neurosymbolic reasoning combining:
- Symbolic theorem proving
- Neural pattern matching
- Knowledge graph integration
- Vector-based retrieval
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .tdfol_core import (
    # Enumerations
    DeonticOperator,
    LogicOperator,
    Quantifier,
    Sort,
    TemporalOperator,
    
    # Terms
    Constant,
    FunctionApplication,
    Term,
    Variable,
    
    # Formulas
    BinaryFormula,
    BinaryTemporalFormula,
    DeonticFormula,
    Formula,
    Predicate,
    QuantifiedFormula,
    TemporalFormula,
    UnaryFormula,
    
    # Knowledge Base
    TDFOLKnowledgeBase,
    
    # Utility Functions
    create_always,
    create_conjunction,
    create_disjunction,
    create_eventually,
    create_existential,
    create_implication,
    create_negation,
    create_next,
    create_obligation,
    create_permission,
    create_prohibition,
    create_universal,
    create_until,
)

# Keep package imports quiet/deterministic: do not import optional/heavy submodules
# (parsers, DCEC integration, prover, cache, rule loaders) at import time.

if TYPE_CHECKING:
    from .tdfol_parser import TDFOLLexer, TDFOLParser, parse_tdfol, parse_tdfol_safe
    from .tdfol_dcec_parser import DCECStringParser, parse_dcec, parse_dcec_safe
    from .tdfol_prover import ProofResult, ProofStatus, ProofStep, TDFOLProver
    from .tdfol_proof_cache import (
        TDFOLProofCache,
        get_global_proof_cache,
        clear_global_proof_cache,
        TDFOLProofResult,
    )
    from .tdfol_inference_rules import TDFOLInferenceRule, get_all_tdfol_rules
    from .nl.tdfol_nl_preprocessor import NLPreprocessor, ProcessedDocument, Entity
    from .proof_tree_visualizer import (
        ProofTreeVisualizer,
        ProofTreeNode,
        NodeType,
        TreeStyle,
        VerbosityLevel,
        visualize_proof,
    )

__all__ = [
    # Enumerations
    "DeonticOperator",
    "LogicOperator",
    "Quantifier",
    "Sort",
    "TemporalOperator",
    
    # Terms
    "Constant",
    "FunctionApplication",
    "Term",
    "Variable",
    
    # Formulas
    "BinaryFormula",
    "BinaryTemporalFormula",
    "DeonticFormula",
    "Formula",
    "Predicate",
    "QuantifiedFormula",
    "TemporalFormula",
    "UnaryFormula",
    
    # Knowledge Base
    "TDFOLKnowledgeBase",
    
    # Parser
    "TDFOLLexer",
    "TDFOLParser",
    "parse_tdfol",
    "parse_tdfol_safe",
    
    # DCEC Parser
    "DCECStringParser",
    "parse_dcec",
    "parse_dcec_safe",
    
    # Prover
    "ProofResult",
    "ProofStatus",
    "ProofStep",
    "TDFOLProver",
    
    # Proof Cache
    "TDFOLProofCache",
    "get_global_proof_cache",
    "clear_global_proof_cache",
    "TDFOLProofResult",
    
    # Inference Rules
    "TDFOLInferenceRule",
    "get_all_tdfol_rules",
    
    # Natural Language Processing (Phase 7)
    "NLPreprocessor",
    "ProcessedDocument",
    "Entity",
    
    # Proof Tree Visualizer (Phase 11)
    "ProofTreeVisualizer",
    "ProofTreeNode",
    "NodeType",
    "TreeStyle",
    "VerbosityLevel",
    "visualize_proof",
    
    # Utility Functions
    "create_always",
    "create_conjunction",
    "create_disjunction",
    "create_eventually",
    "create_existential",
    "create_implication",
    "create_negation",
    "create_next",
    "create_obligation",
    "create_permission",
    "create_prohibition",
    "create_universal",
    "create_until",
]

__version__ = "1.0.0"


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Parser
    "TDFOLLexer": (".tdfol_parser", "TDFOLLexer"),
    "TDFOLParser": (".tdfol_parser", "TDFOLParser"),
    "parse_tdfol": (".tdfol_parser", "parse_tdfol"),
    "parse_tdfol_safe": (".tdfol_parser", "parse_tdfol_safe"),
    # DCEC Parser
    "DCECStringParser": (".tdfol_dcec_parser", "DCECStringParser"),
    "parse_dcec": (".tdfol_dcec_parser", "parse_dcec"),
    "parse_dcec_safe": (".tdfol_dcec_parser", "parse_dcec_safe"),
    # Prover
    "ProofResult": (".tdfol_prover", "ProofResult"),
    "ProofStatus": (".tdfol_prover", "ProofStatus"),
    "ProofStep": (".tdfol_prover", "ProofStep"),
    "TDFOLProver": (".tdfol_prover", "TDFOLProver"),
    # Proof Cache
    "TDFOLProofCache": (".tdfol_proof_cache", "TDFOLProofCache"),
    "get_global_proof_cache": (".tdfol_proof_cache", "get_global_proof_cache"),
    "clear_global_proof_cache": (".tdfol_proof_cache", "clear_global_proof_cache"),
    "TDFOLProofResult": (".tdfol_proof_cache", "TDFOLProofResult"),
    # Inference Rules
    "TDFOLInferenceRule": (".tdfol_inference_rules", "TDFOLInferenceRule"),
    "get_all_tdfol_rules": (".tdfol_inference_rules", "get_all_tdfol_rules"),
    # Natural Language Processing
    "NLPreprocessor": (".nl.tdfol_nl_preprocessor", "NLPreprocessor"),
    "ProcessedDocument": (".nl.tdfol_nl_preprocessor", "ProcessedDocument"),
    "Entity": (".nl.tdfol_nl_preprocessor", "Entity"),
    # Proof Tree Visualizer
    "ProofTreeVisualizer": (".proof_tree_visualizer", "ProofTreeVisualizer"),
    "ProofTreeNode": (".proof_tree_visualizer", "ProofTreeNode"),
    "NodeType": (".proof_tree_visualizer", "NodeType"),
    "TreeStyle": (".proof_tree_visualizer", "TreeStyle"),
    "VerbosityLevel": (".proof_tree_visualizer", "VerbosityLevel"),
    "visualize_proof": (".proof_tree_visualizer", "visualize_proof"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value