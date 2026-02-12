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

from .dcec_prototypes import (
    DCECPrototypeNamespace,
)

from .dcec_integration import (
    parse_expression_to_token,
    token_to_formula,
    parse_dcec_string,
    validate_formula,
    DCECParsingError,
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
    # Prototypes
    "DCECPrototypeNamespace",
    # Integration
    "parse_expression_to_token",
    "token_to_formula",
    "parse_dcec_string",
    "validate_formula",
    "DCECParsingError",
]

__version__ = "0.5.0"

# Phase 4C: Grammar-based NL processing
try:
    from .grammar_engine import (
        GrammarEngine,
        Category,
        GrammarRule,
        LexicalEntry,
        ParseNode,
        CompositeGrammar,
        make_binary_rule,
        make_unary_rule,
    )
    
    from .dcec_english_grammar import (
        DCECEnglishGrammar,
        create_dcec_grammar,
    )
    
    __all__.extend([
        "GrammarEngine",
        "Category",
        "GrammarRule",
        "LexicalEntry",
        "ParseNode",
        "CompositeGrammar",
        "make_binary_rule",
        "make_unary_rule",
        "DCECEnglishGrammar",
        "create_dcec_grammar",
    ])
    
    GRAMMAR_AVAILABLE = True
except ImportError:
    GRAMMAR_AVAILABLE = False

# Update version to 0.6.0 for Phase 4C
__version__ = "0.6.0"

# Phase 4D: ShadowProver modal logic theorem prover
try:
    from .shadow_prover import (
        ShadowProver,
        KProver,
        S4Prover,
        S5Prover,
        CognitiveCalculusProver,
        ModalLogic,
        ProofStatus,
        ProofStep,
        ProofTree,
        ProblemFile,
        ModalOperator,
        ProblemReader,
        create_prover,
        create_cognitive_prover,
    )
    
    from .modal_tableaux import (
        TableauNode,
        ModalTableau,
        TableauProver,
        ResolutionProver,
        NodeStatus,
        create_tableau_prover,
        create_resolution_prover,
    )
    
    __all__.extend([
        "ShadowProver",
        "KProver",
        "S4Prover",
        "S5Prover",
        "CognitiveCalculusProver",
        "ModalLogic",
        "ProofStatus",
        "ProofStep",
        "ProofTree",
        "ProblemFile",
        "ModalOperator",
        "ProblemReader",
        "create_prover",
        "create_cognitive_prover",
        "TableauNode",
        "ModalTableau",
        "TableauProver",
        "ResolutionProver",
        "NodeStatus",
        "create_tableau_prover",
        "create_resolution_prover",
    ])
    
    SHADOWPROVER_AVAILABLE = True
except ImportError:
    SHADOWPROVER_AVAILABLE = False

# Update version to 0.7.0 for Phase 4D
__version__ = "0.7.0"
