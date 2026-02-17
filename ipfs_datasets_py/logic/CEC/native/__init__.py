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
    InferenceEngine,
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
    clean_dcec_expression,
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
    "InferenceEngine",
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
    "clean_dcec_expression",
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

# Phase 4D: Problem file parser
try:
    from .problem_parser import (
        TPTPParser,
        CustomProblemParser,
        ProblemParser,
        TPTPFormula,
        parse_problem_file,
        parse_problem_string,
    )
    
    __all__.extend([
        "TPTPParser",
        "CustomProblemParser",
        "ProblemParser",
        "TPTPFormula",
        "parse_problem_file",
        "parse_problem_string",
    ])
    
    PROBLEM_PARSER_AVAILABLE = True
except ImportError:
    PROBLEM_PARSER_AVAILABLE = False

# Version reflects completion of all Phase 4 components
__version__ = "1.0.0"
