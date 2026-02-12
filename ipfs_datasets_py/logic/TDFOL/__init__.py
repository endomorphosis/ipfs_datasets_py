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

from .tdfol_parser import (
    TDFOLLexer,
    TDFOLParser,
    parse_tdfol,
    parse_tdfol_safe,
)

from .tdfol_dcec_parser import (
    DCECStringParser,
    parse_dcec,
    parse_dcec_safe,
)

from .tdfol_prover import (
    ProofResult,
    ProofStatus,
    ProofStep,
    TDFOLProver,
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