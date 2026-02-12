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
]

__version__ = "0.2.0"
