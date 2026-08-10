"""Controlled F-logic / ErgoAI frontend on shared artifacts (LFP2-013).

Interfaces:

* ``FLogicFrontend@2`` — frame-logic subset (frames, classes, methods,
  inheritance, rules, queries) emitting shared ``ParseArtifact@2`` /
  ``ElaborationArtifact@2`` with typed frame slots instead of raw strings
* ``ErgoAIControlledSource@2`` — advisor/candidate authority-bound controlled
  source view that never executes ErgoAI

The v1 lexer/parser (``flogic.py``) is reused for surface syntax.  This module
converges that notation onto the Wave-2 shared artifact pipeline.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.parsers import flogic as flogic_v1
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
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    AstError,
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_extension,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind as CoreTokenKind,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import build_token_source_map
from ipfs_datasets_py.logic.syntax_core.registry import ParserKey
from ipfs_datasets_py.logic.syntax_core.signatures import (
    INDIVIDUAL_SORT,
    LogicSignature,
    many_sorted_fol_signature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

FLOGIC_FRONTEND_V2_INTERFACE: Final = "FLogicFrontend@2"
ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE: Final = "ErgoAIControlledSource@2"

FLOGIC_V2_NOTATION_ID: Final = flogic_v1.FLOGIC_NOTATION_ID
FLOGIC_V2_NOTATION_VERSION: Final = "2.0.0"
FLOGIC_V2_PROFILE_ID: Final = flogic_v1.FLOGIC_PROFILE_ID
FLOGIC_V2_FAMILY_ID: Final = flogic_v1.FLOGIC_FAMILY_ID
FLOGIC_V2_PROVIDER_ID: Final = flogic_v1.FLOGIC_PROVIDER_ID

FLOGIC_V2_MODULE_VERSION: Final = "2.0.0"
FLOGIC_V2_TASK_ID: Final = "LFP2-013"
FLOGIC_V2_GOAL_ID: Final = FRONTEND_CONTRACT_GOAL_ID
FLOGIC_V2_PARSE_RESULT_SCHEMA: Final = "flogic-v2-parse-result/v1"
FLOGIC_V2_DESCRIPTOR_ID: Final = "frontend:flogic:v2:frame_core"
ERGOAI_SOURCE_V2_SCHEMA: Final = "ergoai-controlled-source/v2"

FLOGIC_DOCUMENT_PAYLOAD_SCHEMA: Final = "flogic.document/v1"
FLOGIC_STATEMENT_PAYLOAD_SCHEMA: Final = "flogic.statement/v1"
FLOGIC_FRAME_PAYLOAD_SCHEMA: Final = "flogic.frame/v1"
FLOGIC_QUERY_PAYLOAD_SCHEMA: Final = "flogic.query/v1"
FLOGIC_SLOT_PAYLOAD_SCHEMA: Final = "flogic.slot/v1"

# Re-export stable diagnostic codes from v1.
CODE_EMPTY_INPUT: Final = flogic_v1.CODE_EMPTY_INPUT
CODE_INPUT_LIMIT: Final = flogic_v1.CODE_INPUT_LIMIT
CODE_TOKEN_LIMIT: Final = flogic_v1.CODE_TOKEN_LIMIT
CODE_PARSE_DEPTH: Final = flogic_v1.CODE_PARSE_DEPTH
CODE_UNBALANCED: Final = flogic_v1.CODE_UNBALANCED
CODE_UNEXPECTED_TOKEN: Final = flogic_v1.CODE_UNEXPECTED_TOKEN
CODE_MALFORMED_STATEMENT: Final = flogic_v1.CODE_MALFORMED_STATEMENT
CODE_MALFORMED_MOLECULE: Final = flogic_v1.CODE_MALFORMED_MOLECULE
CODE_MALFORMED_TERM: Final = flogic_v1.CODE_MALFORMED_TERM
CODE_MALFORMED_RULE: Final = flogic_v1.CODE_MALFORMED_RULE
CODE_MALFORMED_QUERY: Final = flogic_v1.CODE_MALFORMED_QUERY
CODE_TRAILING_INPUT: Final = flogic_v1.CODE_TRAILING_INPUT
CODE_UNTERMINATED_STRING: Final = flogic_v1.CODE_UNTERMINATED_STRING
CODE_UNTERMINATED_COMMENT: Final = flogic_v1.CODE_UNTERMINATED_COMMENT
CODE_UNSUPPORTED_CONSTRUCT: Final = flogic_v1.CODE_UNSUPPORTED_CONSTRUCT
CODE_AUTHORITY: Final = flogic_v1.CODE_AUTHORITY
CODE_ROUND_TRIP: Final = flogic_v1.CODE_ROUND_TRIP
CODE_INVALID_LITERAL: Final = flogic_v1.CODE_INVALID_LITERAL
CODE_LAZY_EXECUTION: Final = flogic_v1.CODE_LAZY_EXECUTION
CODE_ELABORATION_FAILED: Final = "flogic.elaboration_failed"
CODE_RAW_QUERY: Final = "flogic.raw_query_rejected"
CODE_AMBIGUOUS_SLOT: Final = "flogic.ambiguous_frame_slot"

_ALL_FLOGIC_V2_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_EMPTY_INPUT,
        CODE_INPUT_LIMIT,
        CODE_TOKEN_LIMIT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_UNEXPECTED_TOKEN,
        CODE_MALFORMED_STATEMENT,
        CODE_MALFORMED_MOLECULE,
        CODE_MALFORMED_TERM,
        CODE_MALFORMED_RULE,
        CODE_MALFORMED_QUERY,
        CODE_TRAILING_INPUT,
        CODE_UNTERMINATED_STRING,
        CODE_UNTERMINATED_COMMENT,
        CODE_UNSUPPORTED_CONSTRUCT,
        CODE_AUTHORITY,
        CODE_ROUND_TRIP,
        CODE_INVALID_LITERAL,
        CODE_LAZY_EXECUTION,
        CODE_ELABORATION_FAILED,
        CODE_RAW_QUERY,
        CODE_AMBIGUOUS_SLOT,
    }
)

DEFAULT_PARSE_LIMITS: Final = ParseLimits(
    max_input_bytes=262_144,
    max_tokens=65_536,
    max_depth=1_024,
    max_diagnostics=1_024,
    max_time_ms=30_000,
    max_memory_bytes=33_554_432,
)
DEFAULT_FRONTEND_LIMITS: Final = FrontendLimits(
    parse_limits=DEFAULT_PARSE_LIMITS,
    max_output_bytes=262_144,
    max_print_depth=1_024,
)

_TOKEN_KIND_MAP: Final[Mapping[flogic_v1.TokenKind, str]] = {
    flogic_v1.TokenKind.IDENT: CoreTokenKind.IDENTIFIER.value,
    flogic_v1.TokenKind.VARIABLE: "var",
    flogic_v1.TokenKind.INTEGER: CoreTokenKind.NUMBER.value,
    flogic_v1.TokenKind.REAL: CoreTokenKind.NUMBER.value,
    flogic_v1.TokenKind.STRING: CoreTokenKind.STRING.value,
    flogic_v1.TokenKind.LPAREN: "lparen",
    flogic_v1.TokenKind.RPAREN: "rparen",
    flogic_v1.TokenKind.LBRACK: "lbrack",
    flogic_v1.TokenKind.RBRACK: "rbrack",
    flogic_v1.TokenKind.LBRACE: "lbrace",
    flogic_v1.TokenKind.RBRACE: "rbrace",
    flogic_v1.TokenKind.COMMA: "comma",
    flogic_v1.TokenKind.DOT: "dot",
    flogic_v1.TokenKind.COLON: "colon",
    flogic_v1.TokenKind.COLON_COLON: "colon_colon",
    flogic_v1.TokenKind.ARROW: "arrow",
    flogic_v1.TokenKind.DOUBLE_ARROW: "double_arrow",
    flogic_v1.TokenKind.SIG_ARROW: "sig_arrow",
    flogic_v1.TokenKind.SIG_DOUBLE_ARROW: "sig_double_arrow",
    flogic_v1.TokenKind.RULE_NECK: "rule_neck",
    flogic_v1.TokenKind.QUERY: "query",
    flogic_v1.TokenKind.AT: "at",
    flogic_v1.TokenKind.CUT: "cut",
    flogic_v1.TokenKind.OP: CoreTokenKind.OPERATOR.value,
    flogic_v1.TokenKind.EOF: CoreTokenKind.EOF.value,
}

_SYMBOL_NAME_SAFE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_']{0,255}$")

# Re-export v1 vocabulary.
FLogicTermKind = flogic_v1.FLogicTermKind
FLogicSpecKind = flogic_v1.FLogicSpecKind
FLogicStatementKind = flogic_v1.FLogicStatementKind
FLogicItemRole = flogic_v1.FLogicItemRole
FLogicDocument = flogic_v1.FLogicDocument
FLogicStatement = flogic_v1.FLogicStatement
FLogicMolecule = flogic_v1.FLogicMolecule
FLogicTerm = flogic_v1.FLogicTerm
FLogicMethodSpec = flogic_v1.FLogicMethodSpec
UNSUPPORTED_MARKERS = flogic_v1.UNSUPPORTED_MARKERS
UNSUPPORTED_DIRECTIVES = flogic_v1.UNSUPPORTED_DIRECTIVES


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FLogicFrontendV2Error(SyntaxContractError):
    """Base class for FLogicFrontend@2 failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_MALFORMED_STATEMENT,
        remediation: str = "",
        range: SourceRange | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation
        self.range = range
        self.message = message


class ErgoAIAuthorityV2Error(FLogicFrontendV2Error):
    """Raised when ErgoAI authority ceilings are violated."""


# ---------------------------------------------------------------------------
# Diagnostics helpers
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
    prefix: str = "diag:flogic-v2",
) -> tuple[SyntaxDiagnostic, ...]:
    out: list[SyntaxDiagnostic] = []
    for index, item in enumerate(diagnostics, start=1):
        if not isinstance(item, SyntaxDiagnostic):
            continue
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
                    "original_diagnostic_id": item.diagnostic_id,
                },
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Token / CST / surface projection
# ---------------------------------------------------------------------------


def _flogic_tokens_to_logic_tokens(
    tokens: Sequence[flogic_v1.Token],
    *,
    document_id: str,
) -> tuple[LogicToken, ...]:
    logic_tokens: list[LogicToken] = []
    for index, token in enumerate(tokens):
        kind = _TOKEN_KIND_MAP.get(token.kind, CoreTokenKind.UNKNOWN.value)
        logic_tokens.append(
            LogicToken(
                token_id=f"tok:flogic:{index + 1}",
                kind=kind,
                lexeme=token.value,
                range=token.range,
                document_id=document_id,
                metadata={"flogic_kind": token.kind.value},
            )
        )
    return tuple(logic_tokens)


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:flogic:1",
) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind if isinstance(token.kind, str) else str(token.kind),
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for token in tokens
        if (token.kind if isinstance(token.kind, str) else str(token.kind))
        != CoreTokenKind.EOF.value
    )
    covered = [
        token.range
        for token in tokens
        if (token.kind if isinstance(token.kind, str) else str(token.kind))
        != CoreTokenKind.EOF.value
    ]
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


def _surface_from_document(
    document: flogic_v1.FLogicDocument,
    *,
    full_range: SourceRange,
) -> tuple[SurfaceASTRef, ...]:
    refs: list[SurfaceASTRef] = []
    child_ids: list[str] = []
    for index, stmt in enumerate(document.statements):
        node_id = f"ast:flogic:stmt:{index + 1}"
        child_ids.append(node_id)
        span = stmt.range or full_range
        meta: dict[str, Any] = {
            "kind": stmt.kind.value,
            "role": stmt.role.value,
        }
        if stmt.head is not None:
            meta["object"] = stmt.head.object.name
            meta["slots"] = [
                {
                    "method": spec.method_name,
                    "kind": spec.kind.value,
                    "values": [v.name for v in spec.values],
                }
                for spec in stmt.head.specs
            ]
            if stmt.head.isa is not None:
                meta["isa"] = stmt.head.isa.name
            if stmt.head.subclass_of is not None:
                meta["subclass_of"] = stmt.head.subclass_of.name
        if stmt.kind is flogic_v1.FLogicStatementKind.QUERY:
            meta["query"] = {"typed": True, "raw_rejected": True}
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=stmt.kind.value,
                range=span,
                metadata=meta,
            )
        )
    refs.append(
        SurfaceASTRef(
            node_id="ast:flogic:document",
            kind="flogic_document",
            range=full_range,
            child_ids=tuple(child_ids),
            metadata={
                "class_names": list(document.class_names),
                "method_names": list(document.method_names),
                "frame_object_ids": list(document.frame_object_ids),
                "statement_count": len(document.statements),
            },
        )
    )
    return tuple(refs)


# ---------------------------------------------------------------------------
# Typed expression projection
# ---------------------------------------------------------------------------


def _safe_symbol(name: str) -> str | None:
    if not name:
        return None
    # Variables like ?X — strip leading ?
    cleaned_name = name.lstrip("?")
    if _SYMBOL_NAME_SAFE.fullmatch(cleaned_name):
        return cleaned_name
    cleaned = "".join(
        ch if ch.isalnum() or ch in "_'" else "_" for ch in cleaned_name
    )
    if cleaned and cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    if not cleaned or not _SYMBOL_NAME_SAFE.fullmatch(cleaned):
        return None
    return cleaned


def _project_term(
    term: flogic_v1.FLogicTerm,
    *,
    counter: list[int],
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:flogic:term:{counter[0]}"
    span = term.range
    symbol = _safe_symbol(term.name) or f"t_{counter[0]}"
    if term.kind is flogic_v1.FLogicTermKind.VARIABLE:
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.VARIABLE,
            symbol=symbol,
            sort=INDIVIDUAL_SORT,
            range=span,
        )
    if term.kind is flogic_v1.FLogicTermKind.APPLICATION:
        args = tuple(_project_term(arg, counter=counter) for arg in term.arguments)
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.APPLICATION,
            symbol=symbol,
            arguments=args,
            sort=INDIVIDUAL_SORT,
            range=span,
        )
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.CONSTANT,
        symbol=symbol,
        sort=INDIVIDUAL_SORT,
        range=span,
        metadata={"term_kind": term.kind.value, "raw_name": term.name},
    )


def _project_slot(
    spec: flogic_v1.FLogicMethodSpec,
    *,
    counter: list[int],
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:flogic:slot:{counter[0]}"
    method_node = _project_term(spec.method, counter=counter)
    value_nodes = tuple(_project_term(v, counter=counter) for v in spec.values)
    return mk_extension(
        node_id,
        family=FLOGIC_V2_FAMILY_ID,
        profile=FLOGIC_V2_PROFILE_ID,
        features=("flogic", "frame_slot", spec.kind.value),
        payload_schema=FLOGIC_SLOT_PAYLOAD_SCHEMA,
        payload={
            "kind": "frame_slot",
            "schema_version": "flogic.slot/v1",
            "method": spec.method_name,
            "spec_kind": spec.kind.value,
            "typed": True,
            "value_count": len(spec.values),
        },
        children=(method_node, *value_nodes),
        range=spec.range,
    )


def _project_molecule(
    molecule: flogic_v1.FLogicMolecule,
    *,
    counter: list[int],
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:flogic:mol:{counter[0]}"
    obj = _project_term(molecule.object, counter=counter)
    slots = tuple(_project_slot(spec, counter=counter) for spec in molecule.specs)
    extras: list[LogicNode] = []
    if molecule.isa is not None:
        extras.append(_project_term(molecule.isa, counter=counter))
    if molecule.subclass_of is not None:
        extras.append(_project_term(molecule.subclass_of, counter=counter))
    role = molecule.infer_role()
    return mk_extension(
        node_id,
        family=FLOGIC_V2_FAMILY_ID,
        profile=FLOGIC_V2_PROFILE_ID,
        features=("flogic", "molecule", f"role_{role.value}"),
        payload_schema=FLOGIC_FRAME_PAYLOAD_SCHEMA,
        payload={
            "kind": "molecule",
            "schema_version": "flogic.frame/v1",
            "role": role.value,
            "object": molecule.object.name,
            "slot_count": len(molecule.specs),
            "slots": [
                {
                    "method": s.method_name,
                    "kind": s.kind.value,
                    "values": [v.name for v in s.values],
                }
                for s in molecule.specs
            ],
            "isa": None if molecule.isa is None else molecule.isa.name,
            "subclass_of": (
                None if molecule.subclass_of is None else molecule.subclass_of.name
            ),
            "typed": True,
        },
        children=(obj, *slots, *extras),
        range=molecule.range,
    )


def _project_statement(
    stmt: flogic_v1.FLogicStatement,
    *,
    counter: list[int],
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:flogic:stmt:{counter[0]}"
    span = stmt.range

    if stmt.kind is flogic_v1.FLogicStatementKind.QUERY:
        children: list[LogicNode] = []
        if stmt.head is not None:
            children.append(_project_molecule(stmt.head, counter=counter))
        for mol in stmt.body:
            children.append(_project_molecule(mol, counter=counter))
        return mk_extension(
            node_id,
            family=FLOGIC_V2_FAMILY_ID,
            profile=FLOGIC_V2_PROFILE_ID,
            features=("flogic", "query", "typed"),
            payload_schema=FLOGIC_QUERY_PAYLOAD_SCHEMA,
            payload={
                "kind": "query",
                "schema_version": "flogic.query/v1",
                "typed": True,
                "raw_rejected": True,
                "role": stmt.role.value,
                "free_variables": list(
                    (stmt.head.free_variables() if stmt.head is not None else ())
                ),
            },
            children=tuple(children),
            range=span,
        )

    children_list: list[LogicNode] = []
    if stmt.head is not None:
        head_node = _project_molecule(stmt.head, counter=counter)
        if stmt.body:
            body_nodes = tuple(
                _project_molecule(mol, counter=counter) for mol in stmt.body
            )
            if len(body_nodes) == 1:
                body = body_nodes[0]
            else:
                counter[0] += 1
                body = LogicNode(
                    node_id=f"node:flogic:body:{counter[0]}",
                    kind=NodeKind.AND,
                    arguments=body_nodes,
                    range=span,
                )
            counter[0] += 1
            formula = LogicNode(
                node_id=f"node:flogic:rule:{counter[0]}",
                kind=NodeKind.IMPLIES,
                arguments=(body, head_node),
                range=span,
            )
            children_list.append(formula)
        else:
            children_list.append(head_node)

    feature_set = {"flogic", f"kind_{stmt.kind.value}", f"role_{stmt.role.value}"}
    return mk_extension(
        node_id,
        family=FLOGIC_V2_FAMILY_ID,
        profile=FLOGIC_V2_PROFILE_ID,
        features=tuple(sorted(feature_set)),
        payload_schema=FLOGIC_STATEMENT_PAYLOAD_SCHEMA,
        payload={
            "kind": stmt.kind.value,
            "schema_version": "flogic.statement/v1",
            "role": stmt.role.value,
            "unsupported_reason": getattr(stmt, "unsupported_reason", "") or "",
            "typed": True,
        },
        children=tuple(children_list),
        range=span,
    )


def _collect_signature(
    document: flogic_v1.FLogicDocument,
    *,
    signature_id: str,
) -> LogicSignature:
    constants: dict[str, Any] = {}
    predicates: dict[str, int] = {}
    for name in document.class_names:
        symbol = _safe_symbol(name)
        if symbol:
            constants[symbol] = INDIVIDUAL_SORT
    for name in document.frame_object_ids:
        symbol = _safe_symbol(name)
        if symbol:
            constants[symbol] = INDIVIDUAL_SORT
    for name in document.method_names:
        symbol = _safe_symbol(name)
        if symbol:
            # Methods as binary predicates object-method-value abstracted.
            predicates[symbol] = max(predicates.get(symbol, 0), 2)
    const_decls = [(n, s) for n, s in sorted(constants.items())]
    pred_decls = [
        (n, tuple(INDIVIDUAL_SORT for _ in range(arity)))
        for n, arity in sorted(predicates.items())
    ]
    if not const_decls and not pred_decls:
        return LogicSignature(
            signature_id=signature_id,
            family=FLOGIC_V2_FAMILY_ID,
            profile=FLOGIC_V2_PROFILE_ID,
            sorts=(INDIVIDUAL_SORT,),
            symbols=(),
            features=("flogic", "frame"),
        )
    return many_sorted_fol_signature(
        signature_id,
        sorts=(INDIVIDUAL_SORT,),
        constants=const_decls,
        functions=(),
        predicates=pred_decls,
        family=FLOGIC_V2_FAMILY_ID,
        profile=FLOGIC_V2_PROFILE_ID,
        features=("flogic", "frame", "inheritance"),
    )


def _document_to_typed_expression(
    document: flogic_v1.FLogicDocument,
    *,
    expression_id: str,
    full_range: SourceRange | None = None,
) -> tuple[TypedExpression, LogicSignature]:
    counter = [0]
    children = tuple(
        _project_statement(stmt, counter=counter) for stmt in document.statements
    )
    typed_slots: list[dict[str, Any]] = []
    for stmt in document.statements:
        if stmt.head is None:
            continue
        for spec in stmt.head.specs:
            typed_slots.append(
                {
                    "object": stmt.head.object.name,
                    "method": spec.method_name,
                    "kind": spec.kind.value,
                    "values": [v.name for v in spec.values],
                    "typed": True,
                }
            )
    queries = [
        {
            "role": stmt.role.value,
            "typed": True,
            "object": stmt.head.object.name if stmt.head is not None else "",
        }
        for stmt in document.statements
        if stmt.kind is flogic_v1.FLogicStatementKind.QUERY
    ]
    payload: dict[str, Any] = {
        "kind": "flogic_document",
        "schema_version": "flogic.document/v1",
        "class_names": list(document.class_names),
        "method_names": list(document.method_names),
        "frame_object_ids": list(document.frame_object_ids),
        "statement_count": len(document.statements),
        "frame_slots": typed_slots,
        "queries": queries,
        "raw_query_strings_admitted": False,
        "authority": ResultAuthority.CANDIDATE.value,
        "lazy_execution": True,
    }
    root = mk_extension(
        "node:flogic:document",
        family=FLOGIC_V2_FAMILY_ID,
        profile=FLOGIC_V2_PROFILE_ID,
        features=(
            "flogic",
            "parse",
            "elaborate",
            "frame_slots",
            "inheritance",
            "query",
        ),
        payload_schema=FLOGIC_DOCUMENT_PAYLOAD_SCHEMA,
        payload=payload,
        children=children,
        range=full_range,
    )
    signature = _collect_signature(
        document, signature_id=f"sig:flogic:{expression_id}"
    )
    expression = TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=FLOGIC_V2_FAMILY_ID,
        profile=FLOGIC_V2_PROFILE_ID,
        range=full_range,
        elaborate_on_init=False,
        metadata={
            "notation_id": FLOGIC_V2_NOTATION_ID,
            "notation_version": FLOGIC_V2_NOTATION_VERSION,
            "queries_typed": True,
            "raw_query_strings_admitted": False,
            "authority": ResultAuthority.CANDIDATE.value,
        },
    )
    return expression, signature


def check_ambiguous_frame_slots(
    document: flogic_v1.FLogicDocument,
) -> tuple[SyntaxDiagnostic, ...]:
    """Diagnose conflicting scalar slot assignments on the same object/method."""

    diagnostics: list[SyntaxDiagnostic] = []
    # object+method → list of scalar values seen on facts
    seen: dict[tuple[str, str], list[str]] = {}
    for stmt in document.statements:
        if stmt.kind is not flogic_v1.FLogicStatementKind.FACT:
            continue
        if stmt.head is None:
            continue
        obj = stmt.head.object.name
        for spec in stmt.head.specs:
            if spec.kind is not flogic_v1.FLogicSpecKind.SCALAR_VALUE:
                continue
            key = (obj, spec.method_name)
            values = [v.name for v in spec.values]
            seen.setdefault(key, []).extend(values)
    for (obj, method), values in seen.items():
        unique = sorted(set(values))
        if len(unique) > 1:
            diagnostics.append(
                _diag(
                    code=CODE_AMBIGUOUS_SLOT,
                    message=(
                        f"ambiguous scalar frame slot {obj}[{method}]; "
                        f"conflicting values {unique}"
                    ),
                    range=SourceRange(0, 0),
                    diagnostic_id=f"diag:flogic-v2:slot:{obj}:{method}",
                    remediation=(
                        "Use a single scalar value or a set-valued slot (->>)"
                    ),
                )
            )
    return tuple(diagnostics)


# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FLogicFrontendV2Result:
    """Typed result of an FLogicFrontend@2 parse/elaborate attempt."""

    status: ParseStatus
    document: flogic_v1.FLogicDocument | None = None
    source_document: SourceDocument | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    typed_expression: TypedExpression | None = None
    controlled_source: "ErgoAIControlledSourceV2 | None" = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    schema_version: str = FLOGIC_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = FLOGIC_FRONTEND_V2_INTERFACE

    @property
    def ok(self) -> bool:
        return (
            self.status is ParseStatus.OK
            and self.document is not None
            and self.parse_artifact is not None
            and self.elaboration_artifact is not None
            and self.typed_expression is not None
        )

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    @property
    def queries_typed(self) -> bool:
        if self.document is None:
            return False
        return all(
            stmt.head is not None or stmt.body
            for stmt in self.document.statements
            if stmt.kind is flogic_v1.FLogicStatementKind.QUERY
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "controlled_source": (
                None
                if self.controlled_source is None
                else self.controlled_source.to_dict()
            ),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document": None if self.document is None else self.document.to_dict(),
            "elaboration_artifact": (
                None
                if self.elaboration_artifact is None
                else self.elaboration_artifact.to_dict()
            ),
            "interface": self.interface,
            "parse_artifact": (
                None if self.parse_artifact is None else self.parse_artifact.to_dict()
            ),
            "printed": self.printed,
            "queries_typed": self.queries_typed,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
        }


# ---------------------------------------------------------------------------
# ErgoAI controlled source v2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ErgoAIControlledSourceV2:
    """Authority-bound controlled ErgoAI/F-logic source (v2).

    Interface: ``ErgoAIControlledSource@2``.

    Hard-wired to advisor role and candidate authority.  Never executes ErgoAI.
    Requires a typed document (not a raw query string).
    """

    document: flogic_v1.FLogicDocument
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    typed_expression: TypedExpression | None = None
    authority: ResultAuthority = ResultAuthority.CANDIDATE
    status: ResultStatus = ResultStatus.CANDIDATE
    role: ToolRole = ToolRole.ADVISOR
    authority_ceiling: ToolchainAuthorityCeiling = ToolchainAuthorityCeiling.ADVISORY
    trusted: bool = False
    provider_id: str = FLOGIC_V2_PROVIDER_ID
    schema_version: str = ERGOAI_SOURCE_V2_SCHEMA
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if not isinstance(self.document, flogic_v1.FLogicDocument):
            raise ErgoAIAuthorityV2Error(
                "ErgoAIControlledSource@2 requires an FLogicDocument",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "trusted", False)
        authority = (
            self.authority
            if isinstance(self.authority, ResultAuthority)
            else ResultAuthority(str(self.authority))
        )
        if authority is not ResultAuthority.CANDIDATE:
            raise ErgoAIAuthorityV2Error(
                "ErgoAI controlled source must use ResultAuthority.CANDIDATE; "
                f"got {authority!r}",
                code=CODE_AUTHORITY,
                remediation="Do not promote ErgoAI parse output to theorem authority",
            )
        object.__setattr__(self, "authority", ResultAuthority.CANDIDATE)
        status = (
            self.status
            if isinstance(self.status, ResultStatus)
            else ResultStatus(str(self.status))
        )
        if status is not ResultStatus.CANDIDATE:
            raise ErgoAIAuthorityV2Error(
                "ErgoAI controlled source must use ResultStatus.CANDIDATE; "
                f"got {status!r}",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "status", ResultStatus.CANDIDATE)
        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role is not ToolRole.ADVISOR:
            raise ErgoAIAuthorityV2Error(
                f"ErgoAI controlled source role must be advisor; got {role!r}",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "role", ToolRole.ADVISOR)
        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling not in {
            ToolchainAuthorityCeiling.ADVISORY,
            ToolchainAuthorityCeiling.CANDIDATE,
        }:
            raise ErgoAIAuthorityV2Error(
                "ErgoAI authority ceiling must be advisory or candidate; "
                f"got {ceiling!r}",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "authority_ceiling", ceiling)
        if role_can_satisfy_certified_authority(role, ceiling):
            raise ErgoAIAuthorityV2Error(
                "ErgoAI controlled source cannot satisfy certified authority",
                code=CODE_AUTHORITY,
            )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise ErgoAIAuthorityV2Error(
                "controlled source metadata must be immutable JSON data",
                code=CODE_AUTHORITY,
            ) from error
        if self.schema_version != ERGOAI_SOURCE_V2_SCHEMA:
            raise ErgoAIAuthorityV2Error(
                f"unsupported controlled source schema {self.schema_version!r}",
                code=CODE_AUTHORITY,
            )

    @property
    def interface(self) -> str:
        return ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE

    @property
    def is_trusted(self) -> bool:
        return False

    @property
    def can_certify(self) -> bool:
        return False

    @property
    def has_typed_artifacts(self) -> bool:
        return (
            self.parse_artifact is not None
            and self.elaboration_artifact is not None
            and self.typed_expression is not None
        )

    @classmethod
    def from_result(cls, result: FLogicFrontendV2Result) -> "ErgoAIControlledSourceV2":
        if result.document is None:
            raise ErgoAIAuthorityV2Error(
                "controlled source requires a typed FLogicDocument",
                code=CODE_AUTHORITY,
            )
        return cls(
            document=result.document,
            parse_artifact=result.parse_artifact,
            elaboration_artifact=result.elaboration_artifact,
            typed_expression=result.typed_expression,
            metadata=FrozenMap(
                {
                    "lazy": True,
                    "provider_id": FLOGIC_V2_PROVIDER_ID,
                    "untrusted": True,
                    "authority_ceiling": ToolchainAuthorityCeiling.ADVISORY.value,
                    "role": ToolRole.ADVISOR.value,
                    "has_typed_artifacts": (
                        result.parse_artifact is not None
                        and result.elaboration_artifact is not None
                    ),
                    "raw_query_strings_admitted": False,
                }
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "authority_ceiling": self.authority_ceiling.value,
            "can_certify": False,
            "document": self.document.to_dict(),
            "elaboration_artifact": (
                None
                if self.elaboration_artifact is None
                else self.elaboration_artifact.to_dict()
            ),
            "has_typed_artifacts": self.has_typed_artifacts,
            "interface": self.interface,
            "metadata": self.metadata.to_dict(),
            "parse_artifact": (
                None if self.parse_artifact is None else self.parse_artifact.to_dict()
            ),
            "provider_id": self.provider_id,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "trusted": False,
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
        }

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise FLogicFrontendV2Error(
            "ErgoAIControlledSource@2 does not execute the ErgoAI runtime",
            code=CODE_LAZY_EXECUTION,
            remediation="Advisor execution is owned by a separate certified lane",
        )


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


def build_flogic_v2_descriptor(
    *,
    limits: FrontendLimits | None = None,
) -> LogicFrontendDescriptor:
    """Build the shared frontend descriptor for FLogicFrontend@2."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
        FrontendFeature.TYPECHECK.value,
    )
    fixtures = build_baseline_fixture_set(features=features, prefix="flogic-v2")
    extra = (
        FeatureScopedFixture(
            fixture_id="fixture:flogic-v2:frame-slots",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Frame slots elaborate as typed artifacts.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:flogic-v2:unsupported-ergoai",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value,),
            expected_disposition=ExpectedDisposition.UNSUPPORTED,
            description="Unsupported ErgoAI constructs diagnosed, never silent.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:flogic-v2:typed-query",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Queries are typed molecules, not raw strings.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:flogic-v2:ambiguous-slot",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.TYPECHECK.value, FrontendFeature.PARSE.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Ambiguous scalar frame slots reject with diagnostics.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=FLOGIC_V2_DESCRIPTOR_ID,
        key=ParserKey(
            notation_id=FLOGIC_V2_NOTATION_ID,
            notation_version=FLOGIC_V2_NOTATION_VERSION,
            semantic_profile_id=FLOGIC_V2_PROFILE_ID,
        ),
        family_id=FLOGIC_V2_FAMILY_ID,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_FLOGIC_V2_CODES)),
        artifact_outputs=(
            make_parse_artifact_output(),
            make_elaboration_artifact_output(),
        ),
        fixtures=tuple(fixtures) + extra,
        recovery=RecoveryPolicy.NONE,
        printer=PrinterContract(
            guarantee=PrinterGuarantee.SEMANTIC,
            features=(FrontendFeature.PRINT.value,),
            deterministic=True,
        ),
        unsupported_behavior=UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC,
        unsupported_nodes=(
            "ergoai_module_context",
            "transaction_logic",
            "aggregates",
            "defeasible_rules",
            "classical_negation",
            "load_export_directives",
            "raw_query_string",
            "ergoai_execution",
        ),
        implementation="ipfs_datasets_py.logic.parsers.flogic_v2:FLogicFrontendV2",
        metadata={
            "task_id": FLOGIC_V2_TASK_ID,
            "goal_id": FLOGIC_V2_GOAL_ID,
            "provider_id": FLOGIC_V2_PROVIDER_ID,
            "authority": ResultAuthority.CANDIDATE.value,
            "role": ToolRole.ADVISOR.value,
            "interfaces": {
                "flogic": FLOGIC_FRONTEND_V2_INTERFACE,
                "ergoai_source": ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE,
                "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
            },
        },
    )


def register_flogic_v2_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_flogic_v2_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


class FLogicFrontendV2:
    """Shared-artifact F-logic / frame frontend.

    Interface: ``FLogicFrontend@2``.

    Execution remains lazy: no ErgoAI install, import, or process launch.
    """

    interface: ClassVar[str] = FLOGIC_FRONTEND_V2_INTERFACE
    notation_id: ClassVar[str] = FLOGIC_V2_NOTATION_ID
    notation_version: ClassVar[str] = FLOGIC_V2_NOTATION_VERSION
    profile_id: ClassVar[str] = FLOGIC_V2_PROFILE_ID
    family_id: ClassVar[str] = FLOGIC_V2_FAMILY_ID
    module_version: ClassVar[str] = FLOGIC_V2_MODULE_VERSION
    authority: ClassVar[ResultAuthority] = ResultAuthority.CANDIDATE
    role: ClassVar[ToolRole] = ToolRole.ADVISOR
    authority_ceiling: ClassVar[ToolchainAuthorityCeiling] = (
        ToolchainAuthorityCeiling.ADVISORY
    )

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
        check_slots: bool = True,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self.check_slots = check_slots
        self._v1 = flogic_v1.FLogicFrontend()
        self.printer = self._v1.printer
        self.parser = self
        self._descriptor = build_flogic_v2_descriptor(limits=self.limits)

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    def parse_limits(self) -> ParseLimits:
        return self.limits.parse_limits

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:flogic:v2:1",
        request_id: str = "req:flogic:v2:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        elaborate: bool = True,
        as_controlled_source: bool = True,
    ) -> FLogicFrontendV2Result:
        del mode
        bounds = limits if limits is not None else self.parse_limits()

        if not isinstance(text, str):
            diag = _diag(
                code=CODE_INVALID_LITERAL,
                message="F-logic input must be a string",
                range=SourceRange(0, 0),
                diagnostic_id="diag:flogic-v2:type",
            )
            return FLogicFrontendV2Result(
                status=ParseStatus.FAILED, diagnostics=(diag,)
            )

        try:
            source = SourceDocument.from_text(
                document_id,
                text,
                encoding="utf-8",
                language_hint="flogic",
                metadata={
                    "interface": self.interface,
                    "notation_id": self.notation_id,
                },
            )
        except SyntaxContractError as error:
            diag = _diag(
                code=CODE_INPUT_LIMIT,
                message=str(error),
                range=SourceRange(0, 0),
                diagnostic_id="diag:flogic-v2:source",
            )
            return FLogicFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )

        v1_result = self._v1.parse_text(
            text, document_id=document_id, limits=bounds
        )
        diagnostics = list(_unique_diagnostics(v1_result.diagnostics))

        raw_tokens, lex_diags = flogic_v1.tokenize_flogic(text, limits=bounds)
        logic_tokens = _flogic_tokens_to_logic_tokens(
            raw_tokens, document_id=document_id
        )
        if lex_diags and not diagnostics:
            diagnostics = list(_unique_diagnostics(lex_diags))

        if not v1_result.ok or v1_result.document is None:
            status = v1_result.status
            cst = _build_covering_cst(
                source, logic_tokens, cst_id=f"cst:flogic:{request_id}"
            )
            diags = tuple(diagnostics)
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:flogic:parse:{request_id}",
                request_id=request_id,
                status=status,
                tokens=logic_tokens,
                cst=cst,
                surface_ast=(),
                diagnostics=diags,
                metadata={
                    "interface": self.interface,
                    "stage": "parse_failed",
                    "raw_query_strings_admitted": False,
                    "execution_admitted": False,
                    "authority": ResultAuthority.CANDIDATE.value,
                },
            )
            elab = ElaborationArtifactV2(
                artifact_id=f"art:flogic:elab:{request_id}",
                parse_artifact_id=artifact.artifact_id,
                document_id=source.document_id,
                source_digest=source.content_digest,
                status=ElaborationArtifactStatus.FAILED,
                parse_content_digest=artifact.content_digest,
                parse_lineage_digest=artifact.lineage_digest,
                diagnostics=diags,
                metadata={
                    "interface": self.interface,
                    "execution_admitted": False,
                    "authority": ResultAuthority.CANDIDATE.value,
                },
            )
            return FLogicFrontendV2Result(
                status=status,
                document=v1_result.document,
                source_document=source,
                parse_artifact=artifact,
                elaboration_artifact=elab,
                diagnostics=diags,
            )

        document = v1_result.document

        if self.check_slots:
            slot_diags = check_ambiguous_frame_slots(document)
            if slot_diags:
                diagnostics.extend(_unique_diagnostics(slot_diags, prefix="diag:slot"))

        # Fail closed on ambiguous slots (errors).
        if any(item.is_error for item in diagnostics):
            diags = _unique_diagnostics(diagnostics)
            cst = _build_covering_cst(
                source, logic_tokens, cst_id=f"cst:flogic:{request_id}"
            )
            surface = _surface_from_document(
                document, full_range=source.full_range()
            )
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:flogic:parse:{request_id}",
                request_id=request_id,
                status=ParseStatus.FAILED,
                tokens=logic_tokens,
                cst=cst,
                surface_ast=surface,
                diagnostics=diags,
                metadata={
                    "interface": self.interface,
                    "execution_admitted": False,
                    "raw_query_strings_admitted": False,
                },
            )
            elab = ElaborationArtifactV2(
                artifact_id=f"art:flogic:elab:{request_id}",
                parse_artifact_id=artifact.artifact_id,
                document_id=source.document_id,
                source_digest=source.content_digest,
                status=ElaborationArtifactStatus.FAILED,
                parse_content_digest=artifact.content_digest,
                parse_lineage_digest=artifact.lineage_digest,
                diagnostics=diags,
                metadata={"interface": self.interface, "execution_admitted": False},
            )
            return FLogicFrontendV2Result(
                status=ParseStatus.FAILED,
                document=document,
                source_document=source,
                parse_artifact=artifact,
                elaboration_artifact=elab,
                diagnostics=diags,
            )

        diags = _unique_diagnostics(diagnostics)
        cst = _build_covering_cst(
            source, logic_tokens, cst_id=f"cst:flogic:{request_id}"
        )
        surface = _surface_from_document(document, full_range=source.full_range())
        source_map = build_token_source_map(
            source, logic_tokens, map_id=f"map:flogic:{request_id}"
        )
        printed = self.printer.print_document(document)

        parse_artifact = ParseArtifactV2.from_document(
            source,
            artifact_id=f"art:flogic:parse:{request_id}",
            request_id=request_id,
            status=ParseStatus.OK,
            tokens=logic_tokens,
            cst=cst,
            surface_ast=surface,
            source_map=source_map,
            diagnostics=diags,
            metadata={
                "interface": self.interface,
                "notation_id": self.notation_id,
                "notation_version": self.notation_version,
                "profile_id": self.profile_id,
                "family_id": self.family_id,
                "class_names": list(document.class_names),
                "method_names": list(document.method_names),
                "frame_object_ids": list(document.frame_object_ids),
                "printed": printed,
                "raw_query_strings_admitted": False,
                "execution_admitted": False,
                "authority": ResultAuthority.CANDIDATE.value,
            },
        )
        parse_artifact.validate_against(source)

        elaboration_artifact: ElaborationArtifactV2 | None = None
        typed_expression: TypedExpression | None = None
        if elaborate:
            try:
                typed_expression, signature = _document_to_typed_expression(
                    document,
                    expression_id=f"expr:flogic:{request_id}",
                    full_range=source.full_range(),
                )
                parse_artifact = ParseArtifactV2.from_document(
                    source,
                    artifact_id=parse_artifact.artifact_id,
                    request_id=request_id,
                    status=ParseStatus.OK,
                    tokens=logic_tokens,
                    cst=cst,
                    surface_ast=surface,
                    typed_roots=(typed_expression.root,),
                    source_map=source_map,
                    diagnostics=diags,
                    metadata=dict(parse_artifact.metadata),
                )
                parse_artifact.validate_against(source)
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:flogic:elab:{request_id}",
                    parse_artifact_id=parse_artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.OK,
                    typed_expression=typed_expression,
                    root=typed_expression.root,
                    normalized_root=typed_expression.root,
                    signature=signature,
                    parse_content_digest=parse_artifact.content_digest,
                    parse_lineage_digest=parse_artifact.lineage_digest,
                    semantic_digest=typed_expression.content_digest,
                    diagnostics=(),
                    metadata={
                        "interface": self.interface,
                        "class_names": list(document.class_names),
                        "method_names": list(document.method_names),
                        "queries_typed": True,
                        "raw_query_strings_admitted": False,
                        "execution_admitted": False,
                        "authority": ResultAuthority.CANDIDATE.value,
                    },
                )
                elaboration_artifact.validate_lineage(
                    parse_artifact=parse_artifact, document=source
                )
            except (AstError, SyntaxContractError, ValueError, TypeError) as error:
                diag = _diag(
                    code=CODE_ELABORATION_FAILED,
                    message=f"F-logic elaboration failed: {error}",
                    range=source.full_range(),
                    diagnostic_id="diag:flogic-v2:elab",
                )
                diags = _unique_diagnostics(tuple(diags) + (diag,))
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:flogic:elab:{request_id}",
                    parse_artifact_id=parse_artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.FAILED,
                    parse_content_digest=parse_artifact.content_digest,
                    parse_lineage_digest=parse_artifact.lineage_digest,
                    diagnostics=diags,
                    metadata={
                        "interface": self.interface,
                        "execution_admitted": False,
                    },
                )
                return FLogicFrontendV2Result(
                    status=ParseStatus.FAILED,
                    document=document,
                    source_document=source,
                    parse_artifact=parse_artifact,
                    elaboration_artifact=elaboration_artifact,
                    diagnostics=diags,
                    printed=printed,
                )

        result = FLogicFrontendV2Result(
            status=ParseStatus.OK,
            document=document,
            source_document=source,
            parse_artifact=parse_artifact,
            elaboration_artifact=elaboration_artifact,
            typed_expression=typed_expression,
            diagnostics=diags,
            printed=printed,
        )
        if as_controlled_source and result.ok:
            result = FLogicFrontendV2Result(
                status=result.status,
                document=result.document,
                source_document=result.source_document,
                parse_artifact=result.parse_artifact,
                elaboration_artifact=result.elaboration_artifact,
                typed_expression=result.typed_expression,
                controlled_source=ErgoAIControlledSourceV2.from_result(result),
                diagnostics=result.diagnostics,
                printed=result.printed,
            )
        return result

    def parse_text_or_raise(
        self, text: str, **kwargs: Any
    ) -> flogic_v1.FLogicDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise FLogicFrontendV2Error(
                result.errors[0].message if result.errors else "F-logic parse failed",
                code=(
                    result.errors[0].code
                    if result.errors
                    else CODE_MALFORMED_STATEMENT
                ),
            )
        return result.document

    def print(self, document: flogic_v1.FLogicDocument) -> str:
        return self.printer.print_document(document)

    def normalize(
        self, document: flogic_v1.FLogicDocument
    ) -> flogic_v1.FLogicDocument:
        return document.normalized()

    def elaborate(self, text: str, **kwargs: Any) -> FLogicFrontendV2Result:
        kwargs = dict(kwargs)
        kwargs["elaborate"] = True
        return self.parse_text(text, **kwargs)

    def as_controlled_source(
        self, result: FLogicFrontendV2Result
    ) -> ErgoAIControlledSourceV2:
        return ErgoAIControlledSourceV2.from_result(result)

    def round_trip(self, text: str, **kwargs: Any) -> FLogicFrontendV2Result:
        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:flogic:v2:1") + ":rt",
            request_id=str(kwargs.get("request_id") or "req:flogic:v2:1") + ":rt",
            limits=kwargs.get("limits"),
            elaborate=kwargs.get("elaborate", True),
            as_controlled_source=kwargs.get("as_controlled_source", True),
        )
        if not second.ok or second.document is None:
            return second
        if not flogic_v1.documents_semantically_compatible(
            first.document, second.document
        ):
            diag = _diag(
                code=CODE_ROUND_TRIP,
                message="parse/print/parse does not preserve F-logic structure",
                range=SourceRange(0, 0),
                diagnostic_id="diag:flogic-v2:rt",
            )
            return FLogicFrontendV2Result(
                status=ParseStatus.FAILED,
                document=second.document,
                source_document=second.source_document,
                parse_artifact=second.parse_artifact,
                elaboration_artifact=second.elaboration_artifact,
                typed_expression=second.typed_expression,
                controlled_source=second.controlled_source,
                diagnostics=second.diagnostics + (diag,),
                printed=printed,
            )
        return FLogicFrontendV2Result(
            status=ParseStatus.OK,
            document=second.document,
            source_document=second.source_document,
            parse_artifact=second.parse_artifact,
            elaboration_artifact=second.elaboration_artifact,
            typed_expression=second.typed_expression,
            controlled_source=second.controlled_source,
            diagnostics=second.diagnostics,
            printed=printed,
        )

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise FLogicFrontendV2Error(
            "FLogicFrontend@2 does not execute ErgoAI; execution remains lazy "
            "and authority is advisor/candidate only",
            code=CODE_LAZY_EXECUTION,
            remediation=(
                "Use a separately certified ErgoAI advisor lane for execution; "
                "parsing never launches the vendor runtime"
            ),
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_flogic_v2(text: str, **kwargs: Any) -> FLogicFrontendV2Result:
    return FLogicFrontendV2().parse_text(text, **kwargs)


def elaborate_flogic_v2(text: str, **kwargs: Any) -> FLogicFrontendV2Result:
    return FLogicFrontendV2().elaborate(text, **kwargs)


def print_flogic_v2(document: flogic_v1.FLogicDocument) -> str:
    return FLogicFrontendV2().print(document)


def parse_print_parse_flogic_v2(text: str, **kwargs: Any) -> FLogicFrontendV2Result:
    return FLogicFrontendV2().round_trip(text, **kwargs)


def controlled_source_from_text_v2(
    text: str, **kwargs: Any
) -> ErgoAIControlledSourceV2:
    result = FLogicFrontendV2().parse_text(text, **kwargs)
    if not result.ok or result.document is None:
        raise FLogicFrontendV2Error(
            result.errors[0].message if result.errors else "F-logic parse failed",
            code=result.errors[0].code if result.errors else CODE_MALFORMED_STATEMENT,
        )
    if result.controlled_source is not None:
        return result.controlled_source
    return ErgoAIControlledSourceV2.from_result(result)


def documents_semantically_compatible(
    left: flogic_v1.FLogicDocument,
    right: flogic_v1.FLogicDocument,
) -> bool:
    return flogic_v1.documents_semantically_compatible(left, right)


__all__ = [
    "CODE_AMBIGUOUS_SLOT",
    "CODE_AUTHORITY",
    "CODE_ELABORATION_FAILED",
    "CODE_EMPTY_INPUT",
    "CODE_INPUT_LIMIT",
    "CODE_LAZY_EXECUTION",
    "CODE_RAW_QUERY",
    "CODE_ROUND_TRIP",
    "CODE_TOKEN_LIMIT",
    "CODE_UNSUPPORTED_CONSTRUCT",
    "DEFAULT_FRONTEND_LIMITS",
    "DEFAULT_PARSE_LIMITS",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE",
    "ErgoAIAuthorityV2Error",
    "ErgoAIControlledSourceV2",
    "FLOGIC_FRONTEND_V2_INTERFACE",
    "FLOGIC_V2_DESCRIPTOR_ID",
    "FLOGIC_V2_FAMILY_ID",
    "FLOGIC_V2_GOAL_ID",
    "FLOGIC_V2_MODULE_VERSION",
    "FLOGIC_V2_NOTATION_ID",
    "FLOGIC_V2_PROFILE_ID",
    "FLOGIC_V2_PROVIDER_ID",
    "FLOGIC_V2_TASK_ID",
    "FLogicDocument",
    "FLogicFrontendV2",
    "FLogicFrontendV2Error",
    "FLogicFrontendV2Result",
    "FLogicItemRole",
    "FLogicSpecKind",
    "FLogicStatementKind",
    "FLogicTermKind",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "UNSUPPORTED_DIRECTIVES",
    "UNSUPPORTED_MARKERS",
    "build_flogic_v2_descriptor",
    "check_ambiguous_frame_slots",
    "controlled_source_from_text_v2",
    "documents_semantically_compatible",
    "elaborate_flogic_v2",
    "parse_flogic_v2",
    "parse_print_parse_flogic_v2",
    "print_flogic_v2",
    "register_flogic_v2_frontend",
]
