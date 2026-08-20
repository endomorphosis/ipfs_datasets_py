"""Logic syntax core public surface (``LogicSyntaxCore@1``).

LFP-016 joins the side-effect-free syntax-core modules into one reviewed export
list.  Package import is deliberately lazy: no network, subprocess, model load,
or installer is started at import time.  Symbols resolve from their owning leaf
modules only when accessed.
"""

from __future__ import annotations

import importlib
from typing import Any, Final


LOGIC_SYNTAX_CORE_INTERFACE: Final = "LogicSyntaxCore@1"
LOGIC_SYNTAX_CORE_VERSION: Final = "1.0.0"

# Owning leaf module → public symbols (joined only here; LFP-011..015 leave
# package publication to this module).
_EXPORTS: Final[dict[str, tuple[str, ...]]] = {
    "contracts": (
        "CONTRACTS_MODULE_VERSION",
        "CSTNodeRole",
        "DIAGNOSTIC_SCHEMA_VERSION",
        "DiagnosticSeverity",
        "LOGIC_CST_INTERFACE",
        "LOGIC_CST_SCHEMA_VERSION",
        "LOGIC_TOKEN_INTERFACE",
        "LOGIC_TOKEN_SCHEMA_VERSION",
        "LogicCST",
        "LogicCSTNode",
        "LogicToken",
        "MAX_AMBIGUITIES",
        "MAX_CST_NODES",
        "MAX_DIAGNOSTICS",
        "MAX_MEMORY_BYTES",
        "MAX_PARSE_DEPTH",
        "MAX_SOURCE_BYTES",
        "MAX_TIME_MS",
        "MAX_TOKENS",
        "PARSE_ARTIFACT_INTERFACE",
        "PARSE_ARTIFACT_SCHEMA_VERSION",
        "PARSE_LIMITS_SCHEMA_VERSION",
        "PARSE_REQUEST_INTERFACE",
        "PARSE_REQUEST_SCHEMA_VERSION",
        "ParseArtifact",
        "ParseLimits",
        "ParseMode",
        "ParseRequest",
        "ParseStatus",
        "SAFE_ENCODINGS",
        "SOURCE_DOCUMENT_INTERFACE",
        "SOURCE_DOCUMENT_SCHEMA_VERSION",
        "SOURCE_MAP_SCHEMA_VERSION",
        "SOURCE_RANGE_SCHEMA_VERSION",
        "SURFACE_AST_REF_SCHEMA_VERSION",
        "SourceDocument",
        "SourceMap",
        "SourceMapEntry",
        "SourceRange",
        "SurfaceASTRef",
        "SyntaxContractError",
        "SyntaxDiagnostic",
        "TokenKind",
        "assert_complete_coverage",
        "build_line_index",
        "canonical_json_bytes",
        "content_sha256",
        "normalize_encoding_name",
        "require_namespace_identity",
    ),
    "signatures": (
        "BOOL_SORT",
        "BOOL_SORT_NAME",
        "INDIVIDUAL_SORT",
        "INDIVIDUAL_SORT_NAME",
        "LOGIC_SIGNATURE_INTERFACE",
        "LOGIC_SIGNATURE_SCHEMA_VERSION",
        "LOGIC_SORT_SCHEMA_VERSION",
        "SIGNATURES_MODULE_VERSION",
        "SYMBOL_DECLARATION_SCHEMA_VERSION",
        "LogicSignature",
        "LogicSort",
        "SignatureError",
        "SortKind",
        "SymbolDeclaration",
        "SymbolKind",
        "atomic_sort",
        "declare_constant",
        "declare_function",
        "declare_predicate",
        "many_sorted_fol_signature",
        "parametric_sort",
        "propositional_signature",
    ),
    "ast": (
        "AST_MODULE_VERSION",
        "BINDER_SCHEMA_VERSION",
        "LOGIC_EXTENSION_NODE_INTERFACE",
        "LOGIC_EXTENSION_NODE_SCHEMA_VERSION",
        "LOGIC_NODE_SCHEMA_VERSION",
        "TYPED_EXPRESSION_INTERFACE",
        "TYPED_EXPRESSION_SCHEMA_VERSION",
        "AstError",
        "Binder",
        "ElaborationContext",
        "ExprCategory",
        "LogicExtensionNode",
        "LogicNode",
        "NodeKind",
        "TypedExpression",
        "elaborate",
        "elaborate_node",
        "mk_and",
        "mk_application",
        "mk_constant",
        "mk_equality",
        "mk_exists",
        "mk_extension",
        "mk_false",
        "mk_forall",
        "mk_iff",
        "mk_implies",
        "mk_let",
        "mk_not",
        "mk_or",
        "mk_predicate",
        "mk_true",
        "mk_variable",
    ),
    "algebra": (
        "ALGEBRA_MODULE_VERSION",
        "DEFAULT_ALGEBRA",
        "DEFAULT_ALGEBRA_LIMITS",
        "LOGIC_EXPRESSION_ALGEBRA_INTERFACE",
        "MAX_ALGEBRA_DEPTH",
        "MAX_ALGEBRA_NODES",
        "AlgebraError",
        "AlgebraLimits",
        "LogicExpressionAlgebra",
        "alpha_equivalent",
        "bound_variables",
        "free_variables",
        "semantic_identity",
        "substitute",
        "walk_bounded",
    ),
    "lexer": (
        "BOUNDED_LEXER_INTERFACE",
        "BoundedLexer",
        "LEXER_MODULE_VERSION",
        "LexResult",
        "lex_document",
    ),
    "diagnostics": (
        "CODE_COMMENT_DEPTH",
        "CODE_CONFUSABLE_CHARACTER",
        "CODE_DIAGNOSTIC_LIMIT",
        "CODE_INPUT_LIMIT",
        "CODE_MALFORMED_NUMBER",
        "CODE_NUL_CHARACTER",
        "CODE_TOKEN_LIMIT",
        "CODE_UNKNOWN_CHARACTER",
        "CODE_UNTERMINATED_COMMENT",
        "CODE_UNTERMINATED_STRING",
        "DIAGNOSTICS_MODULE_VERSION",
        "DiagnosticSink",
        "LOGIC_DIAGNOSTIC_INTERFACE",
        "LOGIC_SOURCE_MAP_INTERFACE",
        "LogicDiagnostic",
        "LogicSourceMap",
        "build_logic_source_map",
        "build_token_source_map",
        "diagnostics_have_code",
        "make_diagnostic",
    ),
    "registry": (
        "LOGIC_PARSER_DESCRIPTOR_INTERFACE",
        "LOGIC_PARSER_REGISTRY_INTERFACE",
        "PARSER_DESCRIPTOR_SCHEMA_VERSION",
        "PARSER_KEY_SCHEMA_VERSION",
        "PARSER_REGISTRY_SCHEMA_VERSION",
        "REGISTRY_MODULE_VERSION",
        "DuplicateParserError",
        "FrozenLogicParserRegistry",
        "ImplicitFallbackError",
        "LogicParser",
        "LogicParserDescriptor",
        "LogicParserRegistry",
        "ParserFactory",
        "ParserKey",
        "ParserRegistryError",
        "UnknownParserError",
        "empty_parser_registry",
    ),
    "elaboration": (
        "CODE_AMBIGUOUS_OVERLOAD",
        "CODE_ARITY_MISMATCH",
        "CODE_KIND_MISMATCH",
        "CODE_NOT_BACKEND_READY",
        "CODE_SORT_MISMATCH",
        "CODE_TYPECHECK_FAILED",
        "CODE_UNKNOWN_SIGNATURE",
        "CODE_UNKNOWN_SYMBOL",
        "CODE_UNRESOLVED_OVERLOAD",
        "DEFAULT_ELABORATOR",
        "DEFAULT_NORMALIZER",
        "ELABORATION_MODULE_VERSION",
        "ELABORATION_RESULT_SCHEMA_VERSION",
        "ELABORATOR_SCHEMA_VERSION",
        "LOGIC_ELABORATOR_INTERFACE",
        "OVERLOAD_SET_SCHEMA_VERSION",
        "ElaborationError",
        "ElaborationResult",
        "ElaborationStatus",
        "LogicElaborator",
        "LogicNormalizer",
        "LogicTypechecker",
        "OverloadCandidate",
        "OverloadSet",
        "TypecheckReport",
        "UnknownSignatureError",
        "UnresolvedOverloadError",
        "elaborate_expression",
        "normalize",
        "resolve_overload",
    ),
    "codec": (
        "CODED_ENVELOPE_SCHEMA_VERSION",
        "CODEC_MODULE_VERSION",
        "CODEC_SCHEMA_VERSION",
        "DEFAULT_CODEC",
        "SUPPORTED_ELABORATION_RESULT_VERSIONS",
        "SUPPORTED_ENVELOPE_VERSIONS",
        "SUPPORTED_LOGIC_NODE_VERSIONS",
        "SUPPORTED_SIGNATURE_VERSIONS",
        "SUPPORTED_TYPED_EXPRESSION_VERSIONS",
        "TYPED_LOGIC_CODEC_INTERFACE",
        "CodecEnvelope",
        "CodecError",
        "CodecKind",
        "TypedLogicCodec",
        "decode",
        "encode",
        "round_trip",
    ),
}

_EXPORT_MODULE: Final[dict[str, str]] = {
    name: module_name
    for module_name, names in _EXPORTS.items()
    for name in names
}

# Package-level constants live on this module (no leaf import required).
_LOCAL_EXPORTS: Final[frozenset[str]] = frozenset(
    {
        "LOGIC_SYNTAX_CORE_INTERFACE",
        "LOGIC_SYNTAX_CORE_VERSION",
    }
)

if len(_EXPORT_MODULE) != sum(len(names) for names in _EXPORTS.values()):
    raise RuntimeError("syntax_core package exports must have one owning module")

__all__ = sorted(_LOCAL_EXPORTS | set(_EXPORT_MODULE))


def __getattr__(name: str) -> Any:
    """Load a reviewed syntax-core symbol from its owning leaf module."""

    if name in _LOCAL_EXPORTS:
        value = globals()[name]
        return value
    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
