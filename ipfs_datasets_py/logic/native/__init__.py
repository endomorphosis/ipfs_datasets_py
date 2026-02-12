"""
Native Python 3 implementation of Cognitive Event Calculus components.

This package provides pure Python 3 implementations of:
- DCEC (Deontic Cognitive Event Calculus) logic system
- Theorem proving capabilities
- Natural language conversion

These native implementations replace the Python 2 based submodules.
"""

from .dcec_core import (
    # Operators
    DeonticOperator,
    CognitiveOperator,
    LogicalConnective,
    TemporalOperator,
    # Types
    Sort,
    Variable,
    Function,
    Predicate,
    # Terms
    Term,
    VariableTerm,
    FunctionTerm,
    # Formulas
    Formula,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    QuantifiedFormula,
    # Statements
    DCECStatement,
)

from .dcec_namespace import (
    DCECNamespace,
    DCECContainer,
)

from .prover_core import (
    ProofResult,
    ProofTree,
    ProofAttempt,
    TheoremProver,
)

from .nl_converter import (
    ConversionResult,
    NaturalLanguageConverter,
)

from .dcec_cleaning import (
    strip_whitespace,
    strip_comments,
    consolidate_parens,
    check_parens,
    get_matching_close_paren,
    tuck_functions,
)

from .dcec_parsing import (
    ParseToken,
    remove_comments,
    functorize_symbols,
    replace_synonyms,
    prefix_logical_functions,
    prefix_emdas,
)

__all__ = [
    # Operators
    "DeonticOperator",
    "CognitiveOperator",
    "LogicalConnective",
    "TemporalOperator",
    # Types
    "Sort",
    "Variable",
    "Function",
    "Predicate",
    # Terms
    "Term",
    "VariableTerm",
    "FunctionTerm",
    # Formulas
    "Formula",
    "AtomicFormula",
    "DeonticFormula",
    "CognitiveFormula",
    "TemporalFormula",
    "ConnectiveFormula",
    "QuantifiedFormula",
    # Statements
    "DCECStatement",
    # Namespace
    "DCECNamespace",
    "DCECContainer",
    # Prover
    "ProofResult",
    "ProofTree",
    "ProofAttempt",
    "TheoremProver",
    # NL Converter
    "ConversionResult",
    "NaturalLanguageConverter",
    # Cleaning utilities
    "strip_whitespace",
    "strip_comments",
    "consolidate_parens",
    "check_parens",
    "get_matching_close_paren",
    "tuck_functions",
    # Parsing
    "ParseToken",
    "remove_comments",
    "functorize_symbols",
    "replace_synonyms",
    "prefix_logical_functions",
    "prefix_emdas",
]

__version__ = "0.3.0"
