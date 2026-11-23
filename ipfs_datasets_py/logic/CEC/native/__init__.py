"""
Native Python 3 implementation of Cognitive Event Calculus components.

This package provides pure Python 3 implementations of:
- DCEC (Deontic Cognitive Event Calculus) logic system
- Theorem proving capabilities
- Natural language conversion

These native implementations replace the Python 2 based submodules.
"""

# Importing an IR submodule must not initialize unrelated public services.
from threading import RLock as _RLock

_public_exports_lock = _RLock()
_public_exports_ready = False
_public_exports_loading = False
_public_export_names = frozenset(('AtomicFormula', 'CACHING_AVAILABLE', 'CECCachedProofResult', 'CachedTheoremProver', 'Category', 'CognitiveCalculusProver', 'CognitiveFormula', 'CognitiveOperator', 'CompositeGrammar', 'ConnectiveFormula', 'ConversionResult', 'CustomProblemParser', 'DCECContainer', 'DCECEnglishGrammar', 'DCECNamespace', 'DCECParsingError', 'DCECPrototypeNamespace', 'DCECStatement', 'DeonticFormula', 'DeonticOperator', 'Formula', 'Function', 'FunctionTerm', 'GRAMMAR_AVAILABLE', 'GrammarEngine', 'GrammarRule', 'HAVE_CACHE', 'HAVE_ZKP', 'InferenceEngine', 'InferenceRule', 'KProver', 'LEGAL_IR_LIFECYCLE_SCHEMA_VERSION', 'LexicalEntry', 'LogicalConnective', 'ModalLogic', 'ModalOperator', 'ModalTableau', 'NaturalLanguageConverter', 'NodeStatus', 'PROBLEM_PARSER_AVAILABLE', 'ParseNode', 'ParseToken', 'Predicate', 'ProblemFile', 'ProblemParser', 'ProblemReader', 'ProofAttempt', 'ProofResult', 'ProofStatus', 'ProofStep', 'ProofTree', 'ProvingMethod', 'QuantifiedFormula', 'ResolutionProver', 'S4Prover', 'S5Prover', 'SHADOWPROVER_AVAILABLE', 'ShadowProver', 'Sort', 'TPTPFormula', 'TPTPParser', 'TableauNode', 'TableauProver', 'TemporalFormula', 'TemporalOperator', 'Term', 'TheoremProver', 'UnifiedCECProofResult', 'Variable', 'VariableTerm', 'ZKPCECProver', 'ZKP_AVAILABLE', '__all__', '__version__', 'check_parens', 'clean_dcec_expression', 'compile_lifecycle_events', 'consolidate_parens', 'create_cognitive_prover', 'create_dcec_grammar', 'create_hybrid_prover', 'create_prover', 'create_resolution_prover', 'create_tableau_prover', 'functorize_symbols', 'get_global_cached_prover', 'get_matching_close_paren', 'make_binary_rule', 'make_unary_rule', 'parse_dcec_string', 'parse_expression_to_token', 'parse_problem_file', 'parse_problem_string', 'prefix_emdas', 'prefix_logical_functions', 'remove_comments', 'replace_synonyms', 'strip_comments', 'strip_whitespace', 'token_to_formula', 'tokenize_dcec', 'tuck_functions', 'validate_formula'))

# Reload retains a module dictionary. Restore its prior optional bindings only
# inside the legacy sequence, where the original imports can overwrite them.
_previous_public_exports = {
    name: globals()[name] for name in _public_export_names
    if name in globals() and name not in {"__all__", "ProofTree", "__version__", "tokenize_dcec"}
}
for _name in _public_export_names:
    if _name not in {"__version__", "tokenize_dcec"}:
        globals().pop(_name, None)
del _name

__version__ = "1.1.0"

def tokenize_dcec(expression: str):
    """Tokenize a DCEC expression string into a list of tokens."""
    import re

    # Simple tokenizer: split on whitespace and parentheses
    tokens = re.findall(r"[()]|[^\s()]+", expression)
    return tokens


def _initialize_public_exports():
    global AtomicFormula, CACHING_AVAILABLE, CECCachedProofResult, CachedTheoremProver, Category, CognitiveCalculusProver, CognitiveFormula, CognitiveOperator, CompositeGrammar, ConnectiveFormula, ConversionResult, CustomProblemParser, DCECContainer, DCECEnglishGrammar, DCECNamespace, DCECParsingError, DCECPrototypeNamespace, DCECStatement, DeonticFormula, DeonticOperator, Formula, Function, FunctionTerm, GRAMMAR_AVAILABLE, GrammarEngine, GrammarRule, HAVE_CACHE, HAVE_ZKP, InferenceEngine, InferenceRule, KProver, LEGAL_IR_LIFECYCLE_SCHEMA_VERSION, LexicalEntry, LogicalConnective, ModalLogic, ModalOperator, ModalTableau, NaturalLanguageConverter, NodeStatus, PROBLEM_PARSER_AVAILABLE, ParseNode, ParseToken, Predicate, ProblemFile, ProblemParser, ProblemReader, ProofAttempt, ProofResult, ProofStatus, ProofStep, ProvingMethod, QuantifiedFormula, ResolutionProver, S4Prover, S5Prover, SHADOWPROVER_AVAILABLE, ShadowProver, Sort, TPTPFormula, TPTPParser, TableauNode, TableauProver, TemporalFormula, TemporalOperator, Term, TheoremProver, UnifiedCECProofResult, Variable, VariableTerm, ZKPCECProver, ZKP_AVAILABLE, _legacy_all, _legacy_proof_tree, check_parens, clean_dcec_expression, compile_lifecycle_events, consolidate_parens, create_cognitive_prover, create_dcec_grammar, create_hybrid_prover, create_prover, create_resolution_prover, create_tableau_prover, functorize_symbols, get_global_cached_prover, get_matching_close_paren, make_binary_rule, make_unary_rule, parse_dcec_string, parse_expression_to_token, parse_problem_file, parse_problem_string, prefix_emdas, prefix_logical_functions, remove_comments, replace_synonyms, strip_comments, strip_whitespace, token_to_formula, tuck_functions, validate_formula

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
        ProofTree as _legacy_proof_tree,
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

    from .legal_ir_lifecycle import (
        LEGAL_IR_LIFECYCLE_SCHEMA_VERSION,
        compile_lifecycle_events,
    )

    _legacy_all = [
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
        "LEGAL_IR_LIFECYCLE_SCHEMA_VERSION",
        "compile_lifecycle_events",
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

        _legacy_all.extend(
            [
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
            ]
        )

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
            ProofTree as _legacy_proof_tree,
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

        _legacy_all.extend(
            [
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
            ]
        )

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

        _legacy_all.extend(
            [
                "TPTPParser",
                "CustomProblemParser",
                "ProblemParser",
                "TPTPFormula",
                "parse_problem_file",
                "parse_problem_string",
            ]
        )

        PROBLEM_PARSER_AVAILABLE = True
    except ImportError:
        PROBLEM_PARSER_AVAILABLE = False

    # Phase 3+: Proof caching and ZKP integration
    try:
        from .cec_proof_cache import (
            CECCachedProofResult,
            CachedTheoremProver,
            get_global_cached_prover,
            HAVE_CACHE,
        )

        from .cec_zkp_integration import (
            ProvingMethod,
            UnifiedCECProofResult,
            ZKPCECProver,
            create_hybrid_prover,
            HAVE_ZKP,
        )

        _legacy_all.extend(
            [
                "CECCachedProofResult",
                "CachedTheoremProver",
                "get_global_cached_prover",
                "HAVE_CACHE",
                "ProvingMethod",
                "UnifiedCECProofResult",
                "ZKPCECProver",
                "create_hybrid_prover",
                "HAVE_ZKP",
            ]
        )

        CACHING_AVAILABLE = True
        ZKP_AVAILABLE = HAVE_ZKP
    except ImportError as e:
        CACHING_AVAILABLE = False
        ZKP_AVAILABLE = False

    # Version reflects completion of all Phase 4 components + caching/ZKP




    # Export tokenize_dcec
    _legacy_all.append("tokenize_dcec")

    # Export InferenceRule from inference_rules for Phase 4B
    try:
        from .inference_rules.base import InferenceRule

        _legacy_all.append("InferenceRule")
    except ImportError:
        pass


def _load_public_exports():
    global _public_exports_ready, _public_exports_loading
    if _public_exports_ready:
        return
    with _public_exports_lock:
        if _public_exports_ready or _public_exports_loading:
            return
        _public_exports_loading = True
        try:
            globals().update(_previous_public_exports)
            _previous_public_exports.clear()
            _initialize_public_exports()
            # Publish these only after their final legacy order is resolved.
            globals().update(__all__=_legacy_all, ProofTree=_legacy_proof_tree)
            _public_exports_ready = True
        finally:
            _public_exports_loading = False


def __getattr__(name):
    if name not in _public_export_names:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    _load_public_exports()
    if _public_exports_loading:
        # Same-thread circular imports see the legacy binding at this stage.
        alias = {"ProofTree": "_legacy_proof_tree", "__all__": "_legacy_all"}.get(name)
        if alias is not None and alias in globals():
            return globals()[alias]
    try:
        return globals()[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None


def __dir__():
    _load_public_exports()
    return sorted(globals())
