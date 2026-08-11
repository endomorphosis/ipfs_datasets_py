"""SMT-LIB2 frontend converged on the shared artifact pipeline.

Interface: ``SMTLIBFrontend@2`` (LFP2-011).

Wraps the controlled SMT-LIB 2.6 subset from :mod:`smtlib` and emits:

* ``ParseArtifact@2`` — source/CST/surface lineage with exact spans
* ``ElaborationArtifact@2`` — typed expression bound to parse/source digests
* ``LogicFrontendDescriptor@1`` — shared conformance registration surface

Supported constructs round-trip semantically (parse → elaborate → print →
re-parse preserves symbol/sort tables and assertion shapes).  Unsupported
vendor/theory features and duplicate declarations fail closed with exact
source spans.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.smt.compiler import (
    SmtQueryMode,
    SmtSort,
    SmtTerm,
    SmtTermKind,
)
from ipfs_datasets_py.logic.parsers.frontend_contract import (
    FRONTEND_CONTRACT_GOAL_ID,
    ExpectedDisposition,
    FeatureScopedFixture,
    FixtureKind,
    FrontendFeature,
    FrontendLimits,
    LogicFrontendDescriptor,
    PrinterContract,
    PrinterGuarantee,
    RecoveryPolicy,
    SharedFrontendConformance,
    UnsupportedBehavior,
    build_baseline_fixture_set,
    make_elaboration_artifact_output,
    make_parse_artifact_output,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers import smtlib as _v1
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    TypedExpression,
    mk_extension,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_STRING_CHARS,
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.registry import ParserKey
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    LogicSort,
    SortKind,
    SymbolDeclaration,
    declare_constant,
    declare_function,
    declare_predicate,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SMTLIB_FRONTEND_INTERFACE: Final = "SMTLIBFrontend@2"
SMTLIB_V2_MODULE_VERSION: Final = "1.0.0"
SMTLIB_V2_PARSE_RESULT_SCHEMA: Final = "smtlib2-v2-parse-result/v1"
SMTLIB_V2_TASK_ID: Final = "LFP2-011"
SMTLIB_V2_GOAL_ID: Final = FRONTEND_CONTRACT_GOAL_ID

SMTLIB_NOTATION_ID: Final = _v1.SMTLIB2_NOTATION_ID
SMTLIB_NOTATION_VERSION: Final = _v1.SMTLIB2_NOTATION_VERSION
SMTLIB_PROFILE_ID: Final = _v1.SMTLIB2_PROFILE_ID
SMTLIB_FAMILY_ID: Final = _v1.SMTLIB2_FAMILY_ID

SMTLIB_SCRIPT_PAYLOAD_SCHEMA: Final = "smtlib.script/v1"
SMTLIB_ASSERTION_PAYLOAD_SCHEMA: Final = "smtlib.assertion/v1"
SMTLIB_TERM_PAYLOAD_SCHEMA: Final = "smtlib.term/v1"
SMTLIB_DESCRIPTOR_ID: Final = "frontend:smtlib2:v2:smt-core"

# Re-export stable diagnostic codes so callers and tests share one vocabulary.
CODE_EMPTY_INPUT: Final = _v1.CODE_EMPTY_INPUT
CODE_INPUT_LIMIT: Final = _v1.CODE_INPUT_LIMIT
CODE_TOKEN_LIMIT: Final = _v1.CODE_TOKEN_LIMIT
CODE_PARSE_DEPTH: Final = _v1.CODE_PARSE_DEPTH
CODE_UNBALANCED: Final = _v1.CODE_UNBALANCED
CODE_UNEXPECTED_TOKEN: Final = _v1.CODE_UNEXPECTED_TOKEN
CODE_MALFORMED_SEXPR: Final = _v1.CODE_MALFORMED_SEXPR
CODE_UNSUPPORTED_COMMAND: Final = _v1.CODE_UNSUPPORTED_COMMAND
CODE_UNKNOWN_COMMAND: Final = _v1.CODE_UNKNOWN_COMMAND
CODE_UNSUPPORTED_THEORY: Final = _v1.CODE_UNSUPPORTED_THEORY
CODE_UNKNOWN_THEORY: Final = _v1.CODE_UNKNOWN_THEORY
CODE_UNDECLARED_SYMBOL: Final = _v1.CODE_UNDECLARED_SYMBOL
CODE_UNDECLARED_SORT: Final = _v1.CODE_UNDECLARED_SORT
CODE_ARITY_MISMATCH: Final = _v1.CODE_ARITY_MISMATCH
CODE_KIND_MISMATCH: Final = _v1.CODE_KIND_MISMATCH
CODE_MALFORMED_COMMAND: Final = _v1.CODE_MALFORMED_COMMAND
CODE_MALFORMED_TERM: Final = _v1.CODE_MALFORMED_TERM
CODE_MALFORMED_SORT: Final = _v1.CODE_MALFORMED_SORT
CODE_DUPLICATE_SYMBOL: Final = _v1.CODE_DUPLICATE_SYMBOL
CODE_DUPLICATE_SORT: Final = _v1.CODE_DUPLICATE_SORT
CODE_UNSUPPORTED_FEATURE: Final = _v1.CODE_UNSUPPORTED_FEATURE
CODE_TYPECHECK_FAILED: Final = _v1.CODE_TYPECHECK_FAILED
CODE_BRIDGE_FAILED: Final = _v1.CODE_BRIDGE_FAILED
CODE_TRAILING_INPUT: Final = _v1.CODE_TRAILING_INPUT
CODE_UNTERMINATED_STRING: Final = _v1.CODE_UNTERMINATED_STRING
CODE_UNTERMINATED_QUOTE: Final = _v1.CODE_UNTERMINATED_QUOTE
CODE_INVALID_LITERAL: Final = _v1.CODE_INVALID_LITERAL

SUPPORTED_COMMANDS: Final = _v1.SUPPORTED_COMMANDS
UNSUPPORTED_COMMANDS: Final = _v1.UNSUPPORTED_COMMANDS
SUPPORTED_LOGICS: Final = _v1.SUPPORTED_LOGICS
SUPPORTED_THEORIES: Final = _v1.SUPPORTED_THEORIES
UNSUPPORTED_THEORIES: Final = _v1.UNSUPPORTED_THEORIES

DEFAULT_PARSE_LIMITS: Final = ParseLimits(
    max_input_bytes=65_536,
    max_tokens=16_384,
    max_depth=512,
    max_diagnostics=256,
    max_time_ms=30_000,
    max_memory_bytes=16_777_216,
)

DEFAULT_FRONTEND_LIMITS: Final = FrontendLimits(
    parse_limits=DEFAULT_PARSE_LIMITS,
    max_output_bytes=65_536,
    max_print_depth=512,
)

_STABLE_DIAGNOSTICS: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            CODE_EMPTY_INPUT,
            CODE_INPUT_LIMIT,
            CODE_TOKEN_LIMIT,
            CODE_PARSE_DEPTH,
            CODE_UNBALANCED,
            CODE_UNEXPECTED_TOKEN,
            CODE_MALFORMED_SEXPR,
            CODE_UNSUPPORTED_COMMAND,
            CODE_UNKNOWN_COMMAND,
            CODE_UNSUPPORTED_THEORY,
            CODE_UNKNOWN_THEORY,
            CODE_UNDECLARED_SYMBOL,
            CODE_UNDECLARED_SORT,
            CODE_ARITY_MISMATCH,
            CODE_KIND_MISMATCH,
            CODE_MALFORMED_COMMAND,
            CODE_MALFORMED_TERM,
            CODE_MALFORMED_SORT,
            CODE_DUPLICATE_SYMBOL,
            CODE_DUPLICATE_SORT,
            CODE_UNSUPPORTED_FEATURE,
            CODE_TYPECHECK_FAILED,
            CODE_BRIDGE_FAILED,
            CODE_TRAILING_INPUT,
            CODE_UNTERMINATED_STRING,
            CODE_UNTERMINATED_QUOTE,
            CODE_INVALID_LITERAL,
        }
    )
)

_UNSUPPORTED_NODES: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            "vendor.assert_soft",
            "vendor.check_sat_assuming",
            "vendor.declare_heap",
            "vendor.declare_oracle_fun",
            "vendor.define_fun_rec",
            "vendor.get_proof",
            "vendor.get_value",
            "vendor.maximize",
            "vendor.minimize",
            "vendor.synth_fun",
            "theory.bags",
            "theory.separation_logic",
            "theory.sequences_full",
            "theory.sets_full",
            "theory.transcendentals",
        }
    )
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SMTLIBV2Error(SyntaxContractError):
    """Base error for the SMT-LIB v2 frontend."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_MALFORMED_SEXPR,
        range: SourceRange | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.range = range
        self.message = message


class SMTLIBV2ParseError(SMTLIBV2Error):
    """Raised by raising helpers when parse/elaboration fails closed."""


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    remediation: str = "",
    diagnostic_id: str,
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=diagnostic_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


def _unique_diagnostics(
    diagnostics: Sequence[SyntaxDiagnostic],
    *,
    prefix: str = "diag:smtlib-v2",
) -> tuple[SyntaxDiagnostic, ...]:
    """Re-bind diagnostic ids so artifact lineage uniqueness holds."""

    out: list[SyntaxDiagnostic] = []
    for index, item in enumerate(diagnostics, start=1):
        out.append(
            SyntaxDiagnostic(
                diagnostic_id=f"{prefix}:{index}",
                code=item.code,
                message=item.message,
                severity=item.severity,
                range=item.range,
                remediation=item.remediation,
                related_diagnostic_ids=(),
                metadata={
                    **dict(item.metadata),
                    "source_diagnostic_id": item.diagnostic_id,
                },
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Token / CST construction from S-expressions
# ---------------------------------------------------------------------------


def _atom_token_kind(atom: _v1.SAtom) -> str:
    if atom.kind == "numeral" or atom.kind == "decimal":
        return TokenKind.NUMBER.value
    if atom.kind == "string":
        return TokenKind.STRING.value
    if atom.kind == "keyword":
        return TokenKind.KEYWORD.value
    if atom.kind in {"bv", "quoted", "symbol"}:
        return TokenKind.IDENTIFIER.value
    return TokenKind.SYMBOL.value


def _atom_lexeme(atom: _v1.SAtom) -> str:
    if atom.kind == "string":
        escaped = atom.value.replace('"', '""')
        return f'"{escaped}"'
    if atom.kind == "quoted":
        return f"|{atom.value}|"
    return atom.value


def _collect_tokens(
    forms: Sequence[_v1.SExpr],
    *,
    document_id: str,
    source_length: int,
) -> tuple[LogicToken, ...]:
    tokens: list[LogicToken] = []
    counter = [0]

    def clamp(span: SourceRange) -> SourceRange | None:
        start = max(0, min(span.start, source_length))
        end = max(start, min(span.end, source_length))
        if end <= start and span.end > span.start:
            return None
        return SourceRange(start=start, end=end)

    def emit(kind: str, lexeme: str, span: SourceRange) -> None:
        clipped = clamp(span)
        if clipped is None:
            return
        # Skip empty-range tokens with non-empty lexemes.
        if clipped.is_empty:
            return
        # Truncate lexeme to stay within contract ceilings.
        safe_lexeme = lexeme[:MAX_STRING_CHARS] if len(lexeme) > MAX_STRING_CHARS else lexeme
        counter[0] += 1
        tokens.append(
            LogicToken(
                token_id=f"tok:smtlib-v2:{counter[0]}",
                kind=kind,
                lexeme=safe_lexeme,
                range=clipped,
                document_id=document_id,
            )
        )

    def walk(node: _v1.SExpr) -> None:
        if isinstance(node, _v1.SAtom):
            span = node.range or SourceRange(0, 0)
            emit(_atom_token_kind(node), _atom_lexeme(node), span)
            return
        if not isinstance(node, _v1.SList):
            return
        span = node.range
        if span is not None and span.end > span.start:
            emit(TokenKind.OPERATOR.value, "(", SourceRange(span.start, span.start + 1))
        for item in node.items:
            walk(item)
        if span is not None and span.end > span.start:
            emit(TokenKind.OPERATOR.value, ")", SourceRange(span.end - 1, span.end))

    for form in forms:
        walk(form)
    tokens.sort(key=lambda item: (item.range.start, item.range.end, item.token_id))
    seen: set[str] = set()
    unique: list[LogicToken] = []
    for token in tokens:
        key = f"{token.range.start}:{token.range.end}:{token.lexeme}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(token)
    return tuple(
        LogicToken(
            token_id=f"tok:smtlib-v2:{index}",
            kind=token.kind,
            lexeme=token.lexeme,
            range=token.range,
            document_id=document_id,
            metadata=dict(token.metadata),
        )
        for index, token in enumerate(unique, start=1)
    )


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:smtlib-v2:1",
) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind
            if isinstance(token.kind, str)
            else str(token.kind),
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for token in tokens
        if token.kind != TokenKind.EOF.value
    )
    covered = [token.range for token in tokens if token.kind != TokenKind.EOF.value]
    holes: list[LogicCSTNode] = []
    cursor = 0
    for item in sorted(covered, key=lambda value: value.start):
        if item.start > cursor:
            holes.append(
                LogicCSTNode(
                    node_id=f"node:gap:{cursor}:{item.start}",
                    kind="gap",
                    range=SourceRange(start=cursor, end=item.start),
                    role=CSTNodeRole.GAP,
                )
            )
        cursor = max(cursor, item.end)
    if cursor < document.byte_length:
        holes.append(
            LogicCSTNode(
                node_id=f"node:gap:{cursor}:{document.byte_length}",
                kind="gap",
                range=SourceRange(start=cursor, end=document.byte_length),
                role=CSTNodeRole.GAP,
            )
        )
    leaves = tuple(sorted((*children, *holes), key=lambda node: node.range.start))
    if not leaves and document.byte_length == 0:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=(),
        )
    else:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=leaves,
        )
    return LogicCST(
        cst_id=cst_id,
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _surface_from_forms(
    forms: Sequence[_v1.SExpr],
) -> tuple[SurfaceASTRef, ...]:
    refs: list[SurfaceASTRef] = []
    child_ids: list[str] = []
    for index, form in enumerate(forms, start=1):
        node_id = f"ast:smtlib:cmd:{index}"
        child_ids.append(node_id)
        kind = "command"
        if isinstance(form, _v1.SList):
            head = form.head_symbol()
            if head:
                kind = f"command.{head.replace('-', '_')}"
        span = getattr(form, "range", None) or SourceRange(0, 0)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=kind if kind[0].islower() else kind.lower(),
                range=span,
                child_ids=(),
                metadata={
                    "head": (
                        form.head_symbol()
                        if isinstance(form, _v1.SList)
                        else None
                    )
                },
            )
        )
    if refs:
        full_start = min(item.range.start for item in refs)
        full_end = max(item.range.end for item in refs)
        refs.insert(
            0,
            SurfaceASTRef(
                node_id="ast:smtlib:script",
                kind="script",
                range=SourceRange(full_start, full_end),
                child_ids=tuple(child_ids),
            ),
        )
    return tuple(refs)


def _source_map_from_forms(
    forms: Sequence[_v1.SExpr],
    *,
    document_id: str,
    map_id: str = "smap:smtlib-v2:1",
) -> SourceMap:
    entries: list[SourceMapEntry] = []
    for index, form in enumerate(forms, start=1):
        span = getattr(form, "range", None)
        if span is None:
            continue
        head = form.head_symbol() if isinstance(form, _v1.SList) else None
        role = "command"
        if head:
            # SourceMapEntry.role must match _TOKEN_KIND_RE.
            role = f"command.{head.replace('-', '_')}"
        entries.append(
            SourceMapEntry(
                entry_id=f"smap:cmd:{index}",
                range=span,
                role=role if role[0].islower() else "command",
                metadata={"head": head} if head else {},
            )
        )
    return SourceMap(
        map_id=map_id,
        document_id=document_id,
        entries=tuple(entries),
    )


# ---------------------------------------------------------------------------
# Typed projection: SmtlibDocument → TypedExpression
# ---------------------------------------------------------------------------


def _smt_sort_to_logic_sort(sort: SmtSort) -> LogicSort:
    name = sort.name
    # Parametric surface sorts become atomic names that remain stable ids.
    if sort.parameters:
        safe_params = "_".join(
            str(item).replace(" ", "_").replace("(", "").replace(")", "")
            for item in sort.parameters
        )
        name = f"{sort.name}_{safe_params}"
    # Logic sort names must match _SORT_NAME_RE.
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"S_{cleaned}" if cleaned else "S_unknown"
    if cleaned == "Bool":
        return BOOL_SORT
    return LogicSort(name=cleaned, kind=SortKind.ATOMIC)


def _safe_symbol_name(name: str) -> str | None:
    """Return a LogicSignature-safe symbol name, or None when not representable."""

    if not name:
        return None
    if name[0].isalpha() or name[0] == "_":
        cleaned = "".join(
            ch if (ch.isalnum() or ch in {"_", "'"}) else "_" for ch in name
        )
        if cleaned and (cleaned[0].isalpha() or cleaned[0] == "_"):
            return cleaned
    return None


def _signature_from_document(
    document: _v1.SmtlibDocument,
    *,
    signature_id: str = "sig:smtlib-v2:1",
) -> LogicSignature:
    sorts: list[LogicSort] = []
    seen_sorts: set[str] = {"Bool"}
    for sort in document.sorts:
        logic_sort = _smt_sort_to_logic_sort(sort)
        if logic_sort.name not in seen_sorts:
            seen_sorts.add(logic_sort.name)
            sorts.append(logic_sort)
    # Collect range sorts from functions.
    for decl in document.functions:
        for domain_sort in decl.domain:
            logic_sort = _smt_sort_to_logic_sort(domain_sort)
            if logic_sort.name not in seen_sorts:
                seen_sorts.add(logic_sort.name)
                sorts.append(logic_sort)
        logic_sort = _smt_sort_to_logic_sort(decl.range)
        if logic_sort.name not in seen_sorts:
            seen_sorts.add(logic_sort.name)
            sorts.append(logic_sort)

    symbols: list[SymbolDeclaration] = []
    seen_symbols: set[str] = set()
    for decl in document.functions:
        safe = _safe_symbol_name(decl.name)
        if safe is None or safe in seen_symbols:
            continue
        seen_symbols.add(safe)
        range_sort = _smt_sort_to_logic_sort(decl.range)
        domain = tuple(_smt_sort_to_logic_sort(item) for item in decl.domain)
        if range_sort.is_bool:
            if not domain:
                symbols.append(declare_predicate(safe, ()))
            else:
                symbols.append(declare_predicate(safe, domain))
        elif not domain or decl.is_const:
            symbols.append(declare_constant(safe, range_sort))
        else:
            symbols.append(declare_function(safe, domain, range_sort))

    features = ["smtlib", "first_order"]
    for tag in document.feature_tags():
        features.append(tag.value.replace("-", "_").replace("/", "_"))
    # Feature ids must be lowercase dotted.
    cleaned_features = []
    for item in features:
        text = item.lower().replace(" ", "_")
        if text and text[0].isalpha():
            cleaned_features.append(text)

    return LogicSignature(
        signature_id=signature_id,
        family=SMTLIB_FAMILY_ID,
        profile=SMTLIB_PROFILE_ID,
        sorts=tuple(sorts),
        symbols=tuple(symbols),
        features=tuple(dict.fromkeys(cleaned_features)),
        metadata={
            "logic": document.logic,
            "theories": list(document.theories),
        },
    )


def _term_payload(term: SmtTerm) -> dict[str, Any]:
    return {
        "kind": term.kind.value if isinstance(term.kind, SmtTermKind) else str(term.kind),
        "render": term.render(),
        "schema_version": "smtlib.term/v1",
        "value": term.value,
    }


def _project_term(
    term: SmtTerm,
    *,
    counter: list[int],
    range: SourceRange | None = None,
) -> LogicNode:
    """Project an SMT term into a schema-governed extension node tree."""

    counter[0] += 1
    node_id = f"node:smtlib:term:{counter[0]}"
    children = tuple(
        _project_term(arg, counter=counter) for arg in term.arguments
    )
    payload: dict[str, Any] = _term_payload(term)
    if term.binders:
        payload["binders"] = [
            {
                "name": binder.name,
                "sort": binder.sort.to_dict()
                if hasattr(binder.sort, "to_dict")
                else str(binder.sort),
            }
            for binder in term.binders
        ]
    if term.sort is not None:
        payload["sort"] = term.sort.to_dict()
    return mk_extension(
        node_id,
        family=SMTLIB_FAMILY_ID,
        profile=SMTLIB_PROFILE_ID,
        features=("smtlib", "term"),
        payload_schema=SMTLIB_TERM_PAYLOAD_SCHEMA,
        payload=payload,
        children=children,
        range=range,
    )


def _project_document(
    document: _v1.SmtlibDocument,
    *,
    document_range: SourceRange,
    expression_id: str = "expr:smtlib-v2:1",
) -> tuple[LogicNode, TypedExpression, LogicSignature]:
    counter = [0]
    assertion_nodes: list[LogicNode] = []
    for index, assertion in enumerate(document.assertions, start=1):
        counter[0] += 1
        body = _project_term(assertion.formula, counter=counter)
        assertion_nodes.append(
            mk_extension(
                f"node:smtlib:assert:{index}",
                family=SMTLIB_FAMILY_ID,
                profile=SMTLIB_PROFILE_ID,
                features=("smtlib", "assertion"),
                payload_schema=SMTLIB_ASSERTION_PAYLOAD_SCHEMA,
                payload={
                    "kind": "assertion",
                    "name": assertion.name or "",
                    "schema_version": "smtlib.assertion/v1",
                    "render": assertion.formula.render(),
                },
                children=(body,),
                range=document_range,
            )
        )

    signature = _signature_from_document(document)
    semantic = document.semantic_dict()
    # Drop interface identity from nested payload to keep extension payload
    # focused on controlled script content.
    payload: dict[str, Any] = {
        "kind": "script",
        "schema_version": "smtlib.script/v1",
        "logic": document.logic,
        "theories": list(document.theories),
        "sort_names": list(document.sort_names),
        "symbol_names": list(document.symbol_names),
        "request_model": document.request_model,
        "request_unsat_core": document.request_unsat_core,
        "check_sat": document.check_sat,
        "assertions": [
            {
                "name": item.name or "",
                "render": item.formula.render(),
            }
            for item in document.assertions
        ],
        "commands": [
            {
                "kind": (
                    item.kind.value
                    if hasattr(item.kind, "value")
                    else str(item.kind)
                )
            }
            for item in document.commands
        ],
        "datatypes": [item.to_dict() for item in document.datatypes],
        "functions": [item.to_dict() for item in document.functions],
        "sorts": [item.to_dict() for item in document.sorts],
        "features": [
            tag.value if hasattr(tag, "value") else str(tag)
            for tag in document.feature_tags()
        ],
        "legacy_interface": semantic.get("interface"),
    }

    root = mk_extension(
        "node:smtlib:script",
        family=SMTLIB_FAMILY_ID,
        profile=SMTLIB_PROFILE_ID,
        features=(
            "smtlib",
            "parse",
            "elaborate",
            "theories",
            "commands",
            "binders",
            "datatypes",
            "model",
        ),
        payload_schema=SMTLIB_SCRIPT_PAYLOAD_SCHEMA,
        payload=payload,
        children=tuple(assertion_nodes),
        range=document_range,
    )
    expression = TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=SMTLIB_FAMILY_ID,
        profile=SMTLIB_PROFILE_ID,
        range=document_range,
        elaborate_on_init=False,
        metadata={
            "logic": document.logic,
            "notation_id": SMTLIB_NOTATION_ID,
            "notation_version": SMTLIB_NOTATION_VERSION,
            "profile_id": SMTLIB_PROFILE_ID,
        },
    )
    return root, expression, signature


# ---------------------------------------------------------------------------
# Parse / elaborate result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SMTLIBV2ParseResult:
    """Typed result of an SMT-LIB2 v2 parse/elaborate attempt."""

    status: ParseStatus
    document: _v1.SmtlibDocument | None = None
    forms: tuple[_v1.SExpr, ...] = ()
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    source_document: SourceDocument | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    expression: TypedExpression | None = None
    root: LogicNode | None = None
    tokens: tuple[LogicToken, ...] = ()
    source_map: SourceMap | None = None
    schema_version: str = SMTLIB_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = SMTLIB_FRONTEND_INTERFACE

    @property
    def ok(self) -> bool:
        return (
            self.status is ParseStatus.OK
            and self.document is not None
            and self.parse_artifact is not None
            and self.elaboration_artifact is not None
            and self.expression is not None
        )

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document": None if self.document is None else self.document.to_dict(),
            "elaboration_artifact": (
                None
                if self.elaboration_artifact is None
                else self.elaboration_artifact.to_dict()
            ),
            "expression": (
                None if self.expression is None else self.expression.to_dict()
            ),
            "interface": self.interface,
            "parse_artifact": (
                None if self.parse_artifact is None else self.parse_artifact.to_dict()
            ),
            "printed": self.printed,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


class SMTLIBFrontend:
    """Shared-artifact SMT-LIB2 frontend.

    Interface: ``SMTLIBFrontend@2``.
    """

    interface: ClassVar[str] = SMTLIB_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = SMTLIB_NOTATION_ID
    notation_version: ClassVar[str] = SMTLIB_NOTATION_VERSION
    profile_id: ClassVar[str] = SMTLIB_PROFILE_ID
    family_id: ClassVar[str] = SMTLIB_FAMILY_ID

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
        semantic_compiler: Any | None = None,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self._v1 = _v1.SMTLIB2Frontend(semantic_compiler=semantic_compiler)
        self.printer = self._v1.printer
        self.bridge = self._v1.bridge
        self.parser = self

    def descriptor(self) -> LogicFrontendDescriptor:
        """Return the shared frontend descriptor for this profile."""

        return build_smtlib_frontend_descriptor(limits=self.limits)

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:smtlib-v2:1",
        request_id: str = "req:smtlib-v2:1",
        expression_id: str = "expr:smtlib-v2:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> SMTLIBV2ParseResult:
        del mode  # strict-only; recovery is not offered for scripts
        document = SourceDocument.from_text(
            document_id,
            text,
            encoding="utf-8",
            language_hint="smtlib2",
            metadata={
                "interface": SMTLIB_FRONTEND_INTERFACE,
                "notation_id": SMTLIB_NOTATION_ID,
            },
        )
        return self.parse_document(
            document,
            request_id=request_id,
            expression_id=expression_id,
            limits=limits,
        )

    def parse_document(
        self,
        document: SourceDocument,
        *,
        request_id: str = "req:smtlib-v2:1",
        expression_id: str = "expr:smtlib-v2:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> SMTLIBV2ParseResult:
        del mode
        if not isinstance(document, SourceDocument):
            raise SMTLIBV2Error(
                "document must be a SourceDocument",
                code=CODE_MALFORMED_COMMAND,
            )
        bounds = limits if limits is not None else self.limits.parse_limits
        text = document.text
        forms, read_diags = _v1.read_sexprs(text, limits=bounds)
        diagnostics = _unique_diagnostics(read_diags)

        if diagnostics and any(item.is_error for item in diagnostics):
            status = (
                ParseStatus.REJECTED
                if any(item.code == CODE_INPUT_LIMIT for item in diagnostics)
                else ParseStatus.FAILED
            )
            tokens = _collect_tokens(
                forms,
                document_id=document.document_id,
                source_length=document.byte_length,
            )
            # Reader failures may leave no tokens; still emit a covering CST.
            cst = _build_covering_cst(document, tokens)
            parse_artifact = ParseArtifactV2.from_document(
                document,
                artifact_id=f"art:parse:{request_id}",
                request_id=request_id,
                status=status,
                tokens=tokens,
                cst=cst,
                surface_ast=_surface_from_forms(forms) if forms else (),
                diagnostics=diagnostics,
                metadata={
                    "interface": SMTLIB_FRONTEND_INTERFACE,
                    "notation_id": SMTLIB_NOTATION_ID,
                    "stage": "read",
                },
            )
            return SMTLIBV2ParseResult(
                status=status,
                forms=forms,
                diagnostics=diagnostics,
                source_document=document,
                parse_artifact=parse_artifact,
                tokens=tokens,
            )

        if not forms:
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty SMT-LIB input; expected at least one command",
                range=SourceRange(0, 0),
                diagnostic_id="diag:smtlib-v2:empty",
            )
            diagnostics = (diag,)
            cst = _build_covering_cst(document, ())
            parse_artifact = ParseArtifactV2.from_document(
                document,
                artifact_id=f"art:parse:{request_id}",
                request_id=request_id,
                status=ParseStatus.FAILED,
                cst=cst,
                diagnostics=diagnostics,
                metadata={
                    "interface": SMTLIB_FRONTEND_INTERFACE,
                    "notation_id": SMTLIB_NOTATION_ID,
                    "stage": "empty",
                },
            )
            return SMTLIBV2ParseResult(
                status=ParseStatus.FAILED,
                diagnostics=diagnostics,
                source_document=document,
                parse_artifact=parse_artifact,
            )

        tokens = _collect_tokens(
            forms,
            document_id=document.document_id,
            source_length=document.byte_length,
        )
        cst = _build_covering_cst(document, tokens)
        surface = _surface_from_forms(forms)
        source_map = _source_map_from_forms(
            forms, document_id=document.document_id
        )

        try:
            elaborator = _v1._Elaborator()  # noqa: SLF001 — shared elaborator
            smt_document = elaborator.elaborate(forms)
            object.__setattr__(smt_document, "source_text", text)
        except _v1.SMTLIBError as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=error.range,
                remediation=error.remediation,
                diagnostic_id="diag:smtlib-v2:elab:1",
            )
            diagnostics = diagnostics + (diag,)
            diagnostics = _unique_diagnostics(diagnostics)
            parse_artifact = ParseArtifactV2.from_document(
                document,
                artifact_id=f"art:parse:{request_id}",
                request_id=request_id,
                status=ParseStatus.FAILED,
                tokens=tokens,
                cst=cst,
                surface_ast=surface,
                source_map=source_map,
                diagnostics=diagnostics,
                metadata={
                    "interface": SMTLIB_FRONTEND_INTERFACE,
                    "notation_id": SMTLIB_NOTATION_ID,
                    "stage": "elaborate",
                },
            )
            elab_artifact = ElaborationArtifactV2(
                artifact_id=f"art:elab:{request_id}",
                parse_artifact_id=parse_artifact.artifact_id,
                document_id=document.document_id,
                source_digest=document.content_digest,
                status=ElaborationArtifactStatus.FAILED,
                parse_content_digest=parse_artifact.content_digest,
                parse_lineage_digest=parse_artifact.lineage_digest,
                diagnostics=diagnostics,
                metadata={
                    "interface": SMTLIB_FRONTEND_INTERFACE,
                    "stage": "elaborate",
                },
            )
            return SMTLIBV2ParseResult(
                status=ParseStatus.FAILED,
                forms=forms,
                diagnostics=diagnostics,
                source_document=document,
                parse_artifact=parse_artifact,
                elaboration_artifact=elab_artifact,
                tokens=tokens,
                source_map=source_map,
            )

        doc_range = document.full_range()
        root, expression, _signature = _project_document(
            smt_document,
            document_range=doc_range,
            expression_id=expression_id,
        )
        printed = self.printer.print_document(smt_document)
        parse_artifact = ParseArtifactV2.from_document(
            document,
            artifact_id=f"art:parse:{request_id}",
            request_id=request_id,
            status=ParseStatus.OK,
            tokens=tokens,
            cst=cst,
            surface_ast=surface,
            typed_roots=(root,),
            source_map=source_map,
            diagnostics=diagnostics,
            metadata={
                "interface": SMTLIB_FRONTEND_INTERFACE,
                "notation_id": SMTLIB_NOTATION_ID,
                "notation_version": SMTLIB_NOTATION_VERSION,
                "profile_id": SMTLIB_PROFILE_ID,
                "logic": smt_document.logic,
                "printed": printed,
                "stage": "ok",
            },
        )
        parse_artifact.validate_against(document)

        elab_artifact = ElaborationArtifactV2(
            artifact_id=f"art:elab:{request_id}",
            parse_artifact_id=parse_artifact.artifact_id,
            document_id=document.document_id,
            source_digest=document.content_digest,
            status=ElaborationArtifactStatus.OK,
            typed_expression=expression,
            root=root,
            normalized_root=root,
            signature=expression.signature,
            parse_content_digest=parse_artifact.content_digest,
            parse_lineage_digest=parse_artifact.lineage_digest,
            semantic_digest=expression.content_digest,
            diagnostics=(),
            metadata={
                "interface": SMTLIB_FRONTEND_INTERFACE,
                "logic": smt_document.logic,
                "theories": list(smt_document.theories),
                "sort_names": list(smt_document.sort_names),
                "symbol_names": list(smt_document.symbol_names),
            },
        )
        elab_artifact.validate_lineage(
            parse_artifact=parse_artifact, document=document
        )

        return SMTLIBV2ParseResult(
            status=ParseStatus.OK,
            document=smt_document,
            forms=forms,
            diagnostics=diagnostics,
            printed=printed,
            source_document=document,
            parse_artifact=parse_artifact,
            elaboration_artifact=elab_artifact,
            expression=expression,
            root=root,
            tokens=tokens,
            source_map=source_map,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> _v1.SmtlibDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise SMTLIBV2ParseError(
                result.errors[0].message if result.errors else "SMT-LIB parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_SEXPR,
                range=result.errors[0].range if result.errors else None,
            )
        return result.document

    def print(self, document: _v1.SmtlibDocument) -> str:
        return self.printer.print_document(document)

    def elaborate(self, text: str, **kwargs: Any) -> _v1.SmtlibDocument:
        return self.parse_text_or_raise(text, **kwargs)

    def round_trip(self, text: str, **kwargs: Any) -> SMTLIBV2ParseResult:
        """Parse → print → re-parse with semantic preservation check."""

        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:smtlib-v2:1") + ":rt",
            request_id=str(kwargs.get("request_id") or "req:smtlib-v2:1") + ":rt",
            expression_id=str(kwargs.get("expression_id") or "expr:smtlib-v2:1")
            + ":rt",
            limits=kwargs.get("limits"),
        )
        if not second.ok or second.document is None or first.document is None:
            return second
        if not _v1.documents_semantically_compatible(first.document, second.document):
            diag = _diag(
                code=CODE_TYPECHECK_FAILED,
                message="parse/print/parse does not preserve symbol/sort semantics",
                range=SourceRange(0, 0),
                diagnostic_id="diag:smtlib-v2:rt:1",
            )
            return SMTLIBV2ParseResult(
                status=ParseStatus.FAILED,
                document=second.document,
                forms=second.forms,
                diagnostics=second.diagnostics + (diag,),
                printed=printed,
                source_document=second.source_document,
                parse_artifact=second.parse_artifact,
                elaboration_artifact=second.elaboration_artifact,
                expression=second.expression,
                root=second.root,
                tokens=second.tokens,
                source_map=second.source_map,
            )
        return SMTLIBV2ParseResult(
            status=ParseStatus.OK,
            document=second.document,
            forms=second.forms,
            diagnostics=second.diagnostics,
            printed=printed,
            source_document=second.source_document,
            parse_artifact=second.parse_artifact,
            elaboration_artifact=second.elaboration_artifact,
            expression=second.expression,
            root=second.root,
            tokens=second.tokens,
            source_map=second.source_map,
        )

    def to_obligation(
        self,
        document: _v1.SmtlibDocument,
        *,
        obligation_id: str = "obl:smtlib-v2:1",
        query_mode: SmtQueryMode | str = SmtQueryMode.SATISFIABILITY,
    ):
        return self.bridge.to_obligation(
            document,
            obligation_id=obligation_id,
            query_mode=query_mode,
        )

    def compile(
        self,
        document: _v1.SmtlibDocument,
        *,
        obligation_id: str = "obl:smtlib-v2:1",
        query_mode: SmtQueryMode | str = SmtQueryMode.SATISFIABILITY,
    ):
        return self.bridge.compile(
            document,
            obligation_id=obligation_id,
            query_mode=query_mode,
        )


# Public aliases matching the interface publication name.
SMTLIBFrontendV2 = SMTLIBFrontend
SMTLIB2FrontendV2 = SMTLIBFrontend


# ---------------------------------------------------------------------------
# Descriptor / conformance
# ---------------------------------------------------------------------------


def build_smtlib_frontend_descriptor(
    *,
    limits: FrontendLimits | None = None,
    descriptor_id: str = SMTLIB_DESCRIPTOR_ID,
) -> LogicFrontendDescriptor:
    """Build the admitted ``LogicFrontendDescriptor@1`` for SMT-LIB2 v2."""

    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
        FrontendFeature.TYPECHECK.value,
    )
    fixtures = build_baseline_fixture_set(
        features=features,
        prefix="fx:smtlib-v2",
    )
    # Extra theory/command-scoped recipes (compact; no bulk goldens).
    # source_map / typecheck need at least one feature-scoped fixture each.
    extra = (
        FeatureScopedFixture(
            fixture_id="fx:smtlib-v2:theories-positive",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Core/arith/array/bv/string/datatype theories elaborate.",
        ),
        FeatureScopedFixture(
            fixture_id="fx:smtlib-v2:duplicate-decl",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.ELABORATE.value, FrontendFeature.PARSE.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Duplicate sort/symbol declarations fail with exact spans.",
        ),
        FeatureScopedFixture(
            fixture_id="fx:smtlib-v2:vendor-reject",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value,),
            expected_disposition=ExpectedDisposition.UNSUPPORTED,
            description="Vendor commands and unsupported theories reject with spans.",
        ),
        FeatureScopedFixture(
            fixture_id="fx:smtlib-v2:source-map-positive",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.SOURCE_MAP.value, FrontendFeature.PARSE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Command spans recorded in SourceMap with exact ranges.",
        ),
        FeatureScopedFixture(
            fixture_id="fx:smtlib-v2:typecheck-negative",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.TYPECHECK.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Undeclared symbols/sorts fail typecheck with exact spans.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=descriptor_id,
        key=ParserKey(
            notation_id=SMTLIB_NOTATION_ID,
            notation_version=SMTLIB_NOTATION_VERSION,
            semantic_profile_id=SMTLIB_PROFILE_ID,
        ),
        family_id=SMTLIB_FAMILY_ID,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=limits if limits is not None else DEFAULT_FRONTEND_LIMITS,
        diagnostics=_STABLE_DIAGNOSTICS,
        artifact_outputs=(
            make_parse_artifact_output(),
            make_elaboration_artifact_output(),
        ),
        fixtures=fixtures + extra,
        recovery=RecoveryPolicy.NONE,
        printer=PrinterContract(
            guarantee=PrinterGuarantee.SEMANTIC,
            features=(FrontendFeature.PRINT.value,),
            deterministic=True,
        ),
        unsupported_behavior=UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC,
        unsupported_nodes=_UNSUPPORTED_NODES,
        implementation=(
            "ipfs_datasets_py.logic.parsers.smtlib_v2:SMTLIBFrontend"
        ),
        metadata={
            "frontend_interface": SMTLIB_FRONTEND_INTERFACE,
            "goal_id": SMTLIB_V2_GOAL_ID,
            "legacy_interface": _v1.SMTLIB2_FRONTEND_INTERFACE,
            "module_version": SMTLIB_V2_MODULE_VERSION,
            "task_id": SMTLIB_V2_TASK_ID,
        },
    )


def register_smtlib_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    replace: bool = False,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    """Validate and register the SMT-LIB2 v2 descriptor."""

    reg = registry if registry is not None else SharedFrontendConformance(
        conformance_id="conformance:smtlib-v2"
    )
    descriptor = build_smtlib_frontend_descriptor()
    validate_frontend_descriptor(descriptor)
    reg.register(descriptor, replace=replace)
    return reg, descriptor


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_smtlib_v2(
    text: str,
    *,
    document_id: str = "doc:smtlib-v2:1",
    limits: ParseLimits | None = None,
) -> SMTLIBV2ParseResult:
    """Parse *text* into shared ParseArtifact@2 / ElaborationArtifact@2."""

    return SMTLIBFrontend().parse_text(
        text, document_id=document_id, limits=limits
    )


def print_smtlib_v2(document: _v1.SmtlibDocument) -> str:
    return _v1.SMTLIB2Printer().print_document(document)


def elaborate_smtlib_v2(text: str, **kwargs: Any) -> _v1.SmtlibDocument:
    return SMTLIBFrontend().parse_text_or_raise(text, **kwargs)


def parse_print_parse_smtlib_v2(text: str, **kwargs: Any) -> SMTLIBV2ParseResult:
    return SMTLIBFrontend().round_trip(text, **kwargs)


def documents_semantically_compatible(
    left: _v1.SmtlibDocument,
    right: _v1.SmtlibDocument,
) -> bool:
    return _v1.documents_semantically_compatible(left, right)


__all__ = [
    "CODE_ARITY_MISMATCH",
    "CODE_BRIDGE_FAILED",
    "CODE_DUPLICATE_SORT",
    "CODE_DUPLICATE_SYMBOL",
    "CODE_EMPTY_INPUT",
    "CODE_INPUT_LIMIT",
    "CODE_INVALID_LITERAL",
    "CODE_KIND_MISMATCH",
    "CODE_MALFORMED_COMMAND",
    "CODE_MALFORMED_SEXPR",
    "CODE_MALFORMED_SORT",
    "CODE_MALFORMED_TERM",
    "CODE_PARSE_DEPTH",
    "CODE_TOKEN_LIMIT",
    "CODE_TRAILING_INPUT",
    "CODE_TYPECHECK_FAILED",
    "CODE_UNBALANCED",
    "CODE_UNDECLARED_SORT",
    "CODE_UNDECLARED_SYMBOL",
    "CODE_UNEXPECTED_TOKEN",
    "CODE_UNKNOWN_COMMAND",
    "CODE_UNKNOWN_THEORY",
    "CODE_UNSUPPORTED_COMMAND",
    "CODE_UNSUPPORTED_FEATURE",
    "CODE_UNSUPPORTED_THEORY",
    "CODE_UNTERMINATED_QUOTE",
    "CODE_UNTERMINATED_STRING",
    "DEFAULT_FRONTEND_LIMITS",
    "DEFAULT_PARSE_LIMITS",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "SMTLIB2FrontendV2",
    "SMTLIB_DESCRIPTOR_ID",
    "SMTLIB_FAMILY_ID",
    "SMTLIB_FRONTEND_INTERFACE",
    "SMTLIB_NOTATION_ID",
    "SMTLIB_NOTATION_VERSION",
    "SMTLIB_PROFILE_ID",
    "SMTLIB_V2_GOAL_ID",
    "SMTLIB_V2_MODULE_VERSION",
    "SMTLIB_V2_TASK_ID",
    "SMTLIBFrontend",
    "SMTLIBFrontendV2",
    "SMTLIBV2Error",
    "SMTLIBV2ParseError",
    "SMTLIBV2ParseResult",
    "SUPPORTED_COMMANDS",
    "SUPPORTED_LOGICS",
    "SUPPORTED_THEORIES",
    "UNSUPPORTED_COMMANDS",
    "UNSUPPORTED_THEORIES",
    "build_smtlib_frontend_descriptor",
    "documents_semantically_compatible",
    "elaborate_smtlib_v2",
    "parse_print_parse_smtlib_v2",
    "parse_smtlib_v2",
    "print_smtlib_v2",
    "register_smtlib_frontend",
]
