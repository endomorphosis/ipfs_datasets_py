"""Datalog, Horn/CHC, and SecPAL rule frontends on shared artifacts (LFP2-013).

Interfaces:

* ``RuleFrontend@2`` — controlled Datalog/Horn/CHC surface with typed variables,
  safety (range restriction), stratification, world/priority policies, and
  shared ``ParseArtifact@2`` / ``ElaborationArtifact@2`` envelopes
* ``SecPALFrontend@2`` — authorization specialization (says/can-say, speaks-for,
  delegation, principal/resource/action typing)
* ``RuleFrameFrontend@2`` — joint rules/frame convergence facade that never
  admits raw query strings or unsafe rules into an executable path without
  typed artifacts and exact diagnostics

The v1 lexer/parser (``rules.py``) is reused for surface syntax.  This module
converges that notation onto the Wave-2 shared artifact pipeline and
``LogicFrontendDescriptor@1`` contract.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.parsers import rules as rules_v1
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

RULE_FRONTEND_V2_INTERFACE: Final = "RuleFrontend@2"
SECPAL_FRONTEND_V2_INTERFACE: Final = "SecPALFrontend@2"
RULE_FRAME_FRONTEND_INTERFACE: Final = "RuleFrameFrontend@2"

RULE_V2_NOTATION_ID: Final = rules_v1.RULE_NOTATION_ID
RULE_V2_NOTATION_VERSION: Final = "2.0.0"
RULE_V2_PROFILE_ID: Final = rules_v1.RULE_PROFILE_ID
RULE_V2_FAMILY_ID: Final = rules_v1.RULE_FAMILY_ID
SECPAL_V2_PROFILE_ID: Final = rules_v1.SECPAL_PROFILE_ID
SECPAL_V2_FAMILY_ID: Final = rules_v1.SECPAL_FAMILY_ID

RULE_V2_MODULE_VERSION: Final = "2.0.0"
RULE_V2_TASK_ID: Final = "LFP2-013"
RULE_V2_GOAL_ID: Final = FRONTEND_CONTRACT_GOAL_ID
RULE_V2_PARSE_RESULT_SCHEMA: Final = "rules-v2-parse-result/v1"
RULE_V2_DESCRIPTOR_ID: Final = "frontend:datalog_rules:v2:horn"
SECPAL_V2_DESCRIPTOR_ID: Final = "frontend:datalog_rules:v2:secpal"
RULE_FRAME_DESCRIPTOR_ID: Final = "frontend:rule_frame:v2:joint"

RULE_PROGRAM_PAYLOAD_SCHEMA: Final = "rules.program/v1"
RULE_STATEMENT_PAYLOAD_SCHEMA: Final = "rules.statement/v1"
RULE_QUERY_PAYLOAD_SCHEMA: Final = "rules.query/v1"
RULE_ATOM_PAYLOAD_SCHEMA: Final = "rules.atom/v1"

# Re-export stable diagnostic codes from v1.
CODE_EMPTY_INPUT: Final = rules_v1.CODE_EMPTY_INPUT
CODE_INPUT_LIMIT: Final = rules_v1.CODE_INPUT_LIMIT
CODE_TOKEN_LIMIT: Final = rules_v1.CODE_TOKEN_LIMIT
CODE_PARSE_DEPTH: Final = rules_v1.CODE_PARSE_DEPTH
CODE_UNBALANCED: Final = rules_v1.CODE_UNBALANCED
CODE_UNEXPECTED_TOKEN: Final = rules_v1.CODE_UNEXPECTED_TOKEN
CODE_MALFORMED_STATEMENT: Final = rules_v1.CODE_MALFORMED_STATEMENT
CODE_MALFORMED_ATOM: Final = rules_v1.CODE_MALFORMED_ATOM
CODE_MALFORMED_TERM: Final = rules_v1.CODE_MALFORMED_TERM
CODE_MALFORMED_RULE: Final = rules_v1.CODE_MALFORMED_RULE
CODE_MALFORMED_QUERY: Final = rules_v1.CODE_MALFORMED_QUERY
CODE_MALFORMED_DIRECTIVE: Final = rules_v1.CODE_MALFORMED_DIRECTIVE
CODE_TRAILING_INPUT: Final = rules_v1.CODE_TRAILING_INPUT
CODE_UNTERMINATED_STRING: Final = rules_v1.CODE_UNTERMINATED_STRING
CODE_UNTERMINATED_COMMENT: Final = rules_v1.CODE_UNTERMINATED_COMMENT
CODE_UNSUPPORTED_CONSTRUCT: Final = rules_v1.CODE_UNSUPPORTED_CONSTRUCT
CODE_UNSAFE_VARIABLE: Final = rules_v1.CODE_UNSAFE_VARIABLE
CODE_UNSTRATIFIED_NEGATION: Final = rules_v1.CODE_UNSTRATIFIED_NEGATION
CODE_AMBIGUOUS_TERM: Final = rules_v1.CODE_AMBIGUOUS_TERM
CODE_MISSING_WORLD: Final = rules_v1.CODE_MISSING_WORLD
CODE_MISSING_PRIORITY: Final = rules_v1.CODE_MISSING_PRIORITY
CODE_INVALID_LITERAL: Final = rules_v1.CODE_INVALID_LITERAL
CODE_ROUND_TRIP: Final = rules_v1.CODE_ROUND_TRIP
CODE_CHC_LOWERING: Final = rules_v1.CODE_CHC_LOWERING
CODE_PROFILE: Final = rules_v1.CODE_PROFILE
CODE_ELABORATION_FAILED: Final = "rules.elaboration_failed"
CODE_RAW_QUERY: Final = "rules.raw_query_rejected"
CODE_EXECUTION_BLOCKED: Final = "rules.execution_blocked"

_ALL_RULE_V2_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_EMPTY_INPUT,
        CODE_INPUT_LIMIT,
        CODE_TOKEN_LIMIT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_UNEXPECTED_TOKEN,
        CODE_MALFORMED_STATEMENT,
        CODE_MALFORMED_ATOM,
        CODE_MALFORMED_TERM,
        CODE_MALFORMED_RULE,
        CODE_MALFORMED_QUERY,
        CODE_MALFORMED_DIRECTIVE,
        CODE_TRAILING_INPUT,
        CODE_UNTERMINATED_STRING,
        CODE_UNTERMINATED_COMMENT,
        CODE_UNSUPPORTED_CONSTRUCT,
        CODE_UNSAFE_VARIABLE,
        CODE_UNSTRATIFIED_NEGATION,
        CODE_AMBIGUOUS_TERM,
        CODE_MISSING_WORLD,
        CODE_MISSING_PRIORITY,
        CODE_INVALID_LITERAL,
        CODE_ROUND_TRIP,
        CODE_CHC_LOWERING,
        CODE_PROFILE,
        CODE_ELABORATION_FAILED,
        CODE_RAW_QUERY,
        CODE_EXECUTION_BLOCKED,
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

_TOKEN_KIND_MAP: Final[Mapping[rules_v1.TokenKind, str]] = {
    rules_v1.TokenKind.IDENT: CoreTokenKind.IDENTIFIER.value,
    rules_v1.TokenKind.VARIABLE: "var",
    rules_v1.TokenKind.INTEGER: CoreTokenKind.NUMBER.value,
    rules_v1.TokenKind.STRING: CoreTokenKind.STRING.value,
    rules_v1.TokenKind.LPAREN: "lparen",
    rules_v1.TokenKind.RPAREN: "rparen",
    rules_v1.TokenKind.COMMA: "comma",
    rules_v1.TokenKind.DOT: "dot",
    rules_v1.TokenKind.COLON: "colon",
    rules_v1.TokenKind.RULE_NECK: "rule_neck",
    rules_v1.TokenKind.QUERY: "query",
    rules_v1.TokenKind.AT: "at",
    rules_v1.TokenKind.NOT: "not",
    rules_v1.TokenKind.OP: CoreTokenKind.OPERATOR.value,
    rules_v1.TokenKind.EOF: CoreTokenKind.EOF.value,
}

_SYMBOL_NAME_SAFE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_']{0,255}$")

# Re-export commonly used v1 vocabulary for callers.
RuleProfile = rules_v1.RuleProfile
RuleEffect = rules_v1.RuleEffect
RuleStatementKind = rules_v1.RuleStatementKind
RuleItemRole = rules_v1.RuleItemRole
RuleTermKind = rules_v1.RuleTermKind
RuleAtomPolarity = rules_v1.RuleAtomPolarity
WorldPolicyKind = rules_v1.WorldPolicyKind
PriorityPolicyKind = rules_v1.PriorityPolicyKind
TermSortHint = rules_v1.TermSortHint
RuleDocument = rules_v1.RuleDocument
RuleStatement = rules_v1.RuleStatement
RuleAtom = rules_v1.RuleAtom
RuleTerm = rules_v1.RuleTerm
CHCLoweringResult = rules_v1.CHCLoweringResult


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RuleFrontendV2Error(SyntaxContractError):
    """Base class for RuleFrontend@2 / RuleFrameFrontend@2 failures."""

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


class SecPALFrontendV2Error(RuleFrontendV2Error):
    """Raised for SecPALFrontend@2 failures."""


class RuleExecutionBlockedError(RuleFrontendV2Error):
    """Raised when execution is requested without typed artifacts."""


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
    prefix: str = "diag:rules-v2",
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


def _rules_tokens_to_logic_tokens(
    tokens: Sequence[rules_v1.Token],
    *,
    document_id: str,
) -> tuple[LogicToken, ...]:
    logic_tokens: list[LogicToken] = []
    for index, token in enumerate(tokens):
        kind = _TOKEN_KIND_MAP.get(token.kind, CoreTokenKind.UNKNOWN.value)
        logic_tokens.append(
            LogicToken(
                token_id=f"tok:rules:{index + 1}",
                kind=kind,
                lexeme=token.value,
                range=token.range,
                document_id=document_id,
                metadata={"rules_kind": token.kind.value},
            )
        )
    return tuple(logic_tokens)


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:rules:1",
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
    document: rules_v1.RuleDocument,
    *,
    full_range: SourceRange,
) -> tuple[SurfaceASTRef, ...]:
    refs: list[SurfaceASTRef] = []
    child_ids: list[str] = []
    for index, stmt in enumerate(document.statements):
        node_id = f"ast:stmt:{index + 1}"
        child_ids.append(node_id)
        span = stmt.range or full_range
        meta: dict[str, Any] = {
            "kind": stmt.kind.value,
            "role": stmt.role.value,
            "effect": stmt.effect.value,
            "stratum": stmt.stratum,
        }
        if stmt.head is not None:
            meta["predicate"] = stmt.head.predicate
            meta["polarity"] = stmt.head.polarity.value
            meta["arguments"] = [
                {
                    "kind": arg.kind.value,
                    "name": arg.name,
                    "sort": arg.sort.value,
                }
                for arg in stmt.head.arguments
            ]
        if stmt.kind is rules_v1.RuleStatementKind.QUERY:
            meta["query"] = {
                "principal": stmt.principal,
                "action": stmt.action,
                "resource": stmt.resource,
                "typed": True,
            }
        if stmt.principal:
            meta["principal"] = stmt.principal
        if stmt.subject:
            meta["subject"] = stmt.subject
        if stmt.action:
            meta["action"] = stmt.action
        if stmt.resource:
            meta["resource"] = stmt.resource
        if stmt.delegation_depth:
            meta["delegation_depth"] = stmt.delegation_depth
        if stmt.directive_name:
            meta["directive_name"] = stmt.directive_name
            meta["directive_value"] = stmt.directive_value
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
            node_id="ast:document",
            kind="rule_document",
            range=full_range,
            child_ids=tuple(child_ids),
            metadata={
                "profile": document.profile.value,
                "world_policy": (
                    None
                    if document.world_policy is None
                    else document.world_policy.value
                ),
                "priority_policy": (
                    None
                    if document.priority_policy is None
                    else document.priority_policy.value
                ),
                "predicate_names": list(document.predicate_names),
                "trust_roots": list(document.trust_roots),
                "query_count": len(document.queries),
                "rule_count": len(document.rules),
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
    if _SYMBOL_NAME_SAFE.fullmatch(name):
        return name
    cleaned = "".join(ch if ch.isalnum() or ch in "_'" else "_" for ch in name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    if not cleaned or not _SYMBOL_NAME_SAFE.fullmatch(cleaned):
        return None
    return cleaned


def _project_term(
    term: rules_v1.RuleTerm,
    *,
    counter: list[int],
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:rules:term:{counter[0]}"
    span = term.range
    symbol = _safe_symbol(term.name) or f"t_{counter[0]}"
    if term.kind is rules_v1.RuleTermKind.VARIABLE:
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.VARIABLE,
            symbol=symbol,
            sort=INDIVIDUAL_SORT,
            range=span,
            metadata={"sort_hint": term.sort.value},
        )
    return LogicNode(
        node_id=node_id,
        kind=NodeKind.CONSTANT,
        symbol=symbol,
        sort=INDIVIDUAL_SORT,
        range=span,
        metadata={
            "term_kind": term.kind.value,
            "sort_hint": term.sort.value,
            "raw_name": term.name,
        },
    )


def _project_atom(
    atom: rules_v1.RuleAtom,
    *,
    counter: list[int],
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:rules:atom:{counter[0]}"
    args = tuple(_project_term(arg, counter=counter) for arg in atom.arguments)
    symbol = _safe_symbol(atom.predicate) or f"p_{counter[0]}"
    pred = LogicNode(
        node_id=node_id,
        kind=NodeKind.PREDICATE,
        symbol=symbol,
        arguments=args,
        range=atom.range,
        metadata={
            "issuer": atom.issuer,
            "polarity": atom.polarity.value,
            "payload_schema": RULE_ATOM_PAYLOAD_SCHEMA,
        },
    )
    if atom.is_negative:
        counter[0] += 1
        return LogicNode(
            node_id=f"node:rules:not:{counter[0]}",
            kind=NodeKind.NOT,
            arguments=(pred,),
            range=atom.range,
        )
    return pred


def _project_statement(
    stmt: rules_v1.RuleStatement,
    *,
    counter: list[int],
    family: str,
    profile: str,
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:rules:stmt:{counter[0]}"
    span = stmt.range

    if stmt.kind is rules_v1.RuleStatementKind.QUERY:
        children: list[LogicNode] = []
        if stmt.head is not None:
            children.append(_project_atom(stmt.head, counter=counter))
        for atom in stmt.body:
            children.append(_project_atom(atom, counter=counter))
        payload: dict[str, Any] = {
            "kind": "query",
            "schema_version": "rules.query/v1",
            "typed": True,
            "raw_rejected": True,
            "principal": stmt.principal,
            "action": stmt.action,
            "resource": stmt.resource,
            "role": stmt.role.value,
        }
        if stmt.head is not None:
            payload["goal_predicate"] = stmt.head.predicate
            payload["goal_arguments"] = [
                {"kind": a.kind.value, "name": a.name, "sort": a.sort.value}
                for a in stmt.head.arguments
            ]
        return mk_extension(
            node_id,
            family=family,
            profile=profile,
            features=("rules", "query", "typed"),
            payload_schema=RULE_QUERY_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(children),
            range=span,
        )

    if stmt.kind is rules_v1.RuleStatementKind.SPEAKS_FOR:
        return mk_extension(
            node_id,
            family=family,
            profile=profile,
            features=("rules", "speaks_for", "authorization"),
            payload_schema=RULE_STATEMENT_PAYLOAD_SCHEMA,
            payload={
                "kind": "speaks_for",
                "schema_version": "rules.statement/v1",
                "principal": stmt.principal,
                "subject": stmt.subject,
            },
            range=span,
        )

    if stmt.kind is rules_v1.RuleStatementKind.DELEGATION:
        return mk_extension(
            node_id,
            family=family,
            profile=profile,
            features=("rules", "delegation", "authorization"),
            payload_schema=RULE_STATEMENT_PAYLOAD_SCHEMA,
            payload={
                "kind": "delegation",
                "schema_version": "rules.statement/v1",
                "principal": stmt.principal,
                "subject": stmt.subject,
                "action": stmt.action,
                "resource": stmt.resource,
                "delegation_depth": stmt.delegation_depth,
            },
            range=span,
        )

    if stmt.kind is rules_v1.RuleStatementKind.DIRECTIVE:
        return mk_extension(
            node_id,
            family=family,
            profile=profile,
            features=("rules", "directive", f"role_{stmt.role.value}"),
            payload_schema=RULE_STATEMENT_PAYLOAD_SCHEMA,
            payload={
                "kind": "directive",
                "schema_version": "rules.statement/v1",
                "name": stmt.directive_name,
                "value": stmt.directive_value,
                "role": stmt.role.value,
            },
            range=span,
        )

    # Fact / rule / CHC / constraint / unsupported
    children_list: list[LogicNode] = []
    if stmt.head is not None:
        head_node = _project_atom(stmt.head, counter=counter)
        if stmt.body:
            body_nodes = tuple(
                _project_atom(atom, counter=counter) for atom in stmt.body
            )
            if len(body_nodes) == 1:
                body = body_nodes[0]
            else:
                counter[0] += 1
                body = LogicNode(
                    node_id=f"node:rules:body:{counter[0]}",
                    kind=NodeKind.AND,
                    arguments=body_nodes,
                    range=span,
                )
            counter[0] += 1
            formula = LogicNode(
                node_id=f"node:rules:rule:{counter[0]}",
                kind=NodeKind.IMPLIES,
                arguments=(body, head_node),
                range=span,
            )
            children_list.append(formula)
        else:
            children_list.append(head_node)

    feature_set = {
        "rules",
        f"kind_{stmt.kind.value}",
        f"effect_{stmt.effect.value}",
        f"stratum_{stmt.stratum}",
        f"role_{stmt.role.value}",
    }
    return mk_extension(
        node_id,
        family=family,
        profile=profile,
        features=tuple(sorted(feature_set)),
        payload_schema=RULE_STATEMENT_PAYLOAD_SCHEMA,
        payload={
            "kind": stmt.kind.value,
            "schema_version": "rules.statement/v1",
            "role": stmt.role.value,
            "effect": stmt.effect.value,
            "stratum": stmt.stratum,
            "issuer": stmt.head.issuer if stmt.head is not None else "",
            "principal": stmt.principal,
            "unsupported_reason": stmt.unsupported_reason,
            "typed": True,
        },
        children=tuple(children_list),
        range=span,
    )


def _collect_signature(
    document: rules_v1.RuleDocument,
    *,
    signature_id: str,
    family: str,
    profile: str,
) -> LogicSignature:
    predicates: dict[str, int] = {}
    constants: dict[str, Any] = {}
    for stmt in document.statements:
        for atom in ((stmt.head,) if stmt.head else ()) + stmt.body:
            if atom is None:
                continue
            symbol = _safe_symbol(atom.predicate)
            if symbol:
                predicates[symbol] = max(
                    predicates.get(symbol, 0), len(atom.arguments)
                )
            for arg in atom.arguments:
                if arg.kind is not rules_v1.RuleTermKind.VARIABLE:
                    csym = _safe_symbol(arg.name)
                    if csym:
                        constants[csym] = INDIVIDUAL_SORT
    const_decls = [(name, sort) for name, sort in sorted(constants.items())]
    pred_decls = [
        (name, tuple(INDIVIDUAL_SORT for _ in range(arity)))
        for name, arity in sorted(predicates.items())
    ]
    if not const_decls and not pred_decls:
        return LogicSignature(
            signature_id=signature_id,
            family=family,
            profile=profile,
            sorts=(INDIVIDUAL_SORT,),
            symbols=(),
            features=("rules", "datalog"),
        )
    return many_sorted_fol_signature(
        signature_id,
        sorts=(INDIVIDUAL_SORT,),
        constants=const_decls,
        functions=(),
        predicates=pred_decls,
        family=family,
        profile=profile,
        features=("rules", "datalog", "horn"),
    )


def _document_to_typed_expression(
    document: rules_v1.RuleDocument,
    *,
    expression_id: str,
    full_range: SourceRange | None = None,
    family: str | None = None,
    profile: str | None = None,
) -> tuple[TypedExpression, LogicSignature]:
    family_id = family or document.family_id or RULE_V2_FAMILY_ID
    profile_id = profile or document.profile_id or RULE_V2_PROFILE_ID
    counter = [0]
    children = tuple(
        _project_statement(
            stmt, counter=counter, family=family_id, profile=profile_id
        )
        for stmt in document.statements
    )
    # Typed query inventory — never raw strings.
    typed_queries = [
        {
            "principal": q.principal,
            "action": q.action,
            "resource": q.resource,
            "predicate": q.head.predicate if q.head is not None else "",
            "arguments": (
                [
                    {"kind": a.kind.value, "name": a.name, "sort": a.sort.value}
                    for a in q.head.arguments
                ]
                if q.head is not None
                else []
            ),
            "typed": True,
        }
        for q in document.queries
    ]
    payload: dict[str, Any] = {
        "kind": "rule_program",
        "schema_version": "rules.program/v1",
        "profile": document.profile.value,
        "world_policy": (
            None if document.world_policy is None else document.world_policy.value
        ),
        "priority_policy": (
            None
            if document.priority_policy is None
            else document.priority_policy.value
        ),
        "trust_roots": list(document.trust_roots),
        "predicate_names": list(document.predicate_names),
        "statement_count": len(document.statements),
        "rule_count": len(document.rules),
        "query_count": len(document.queries),
        "queries": typed_queries,
        "has_negation": document.has_negation,
        "has_decision_effects": document.has_decision_effects,
        "raw_query_strings_admitted": False,
    }
    root = mk_extension(
        "node:rules:program",
        family=family_id,
        profile=profile_id,
        features=(
            "rules",
            "parse",
            "elaborate",
            "safety",
            "stratification",
            "priority",
            "query",
        ),
        payload_schema=RULE_PROGRAM_PAYLOAD_SCHEMA,
        payload=payload,
        children=children,
        range=full_range,
    )
    signature = _collect_signature(
        document,
        signature_id=f"sig:rules:{expression_id}",
        family=family_id,
        profile=profile_id,
    )
    expression = TypedExpression(
        expression_id=expression_id,
        root=root,
        signature=signature,
        family=family_id,
        profile=profile_id,
        range=full_range,
        elaborate_on_init=False,
        metadata={
            "notation_id": RULE_V2_NOTATION_ID,
            "notation_version": RULE_V2_NOTATION_VERSION,
            "profile": document.profile.value,
            "queries_typed": True,
            "raw_query_strings_admitted": False,
        },
    )
    return expression, signature


# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleFrontendV2Result:
    """Typed result of a RuleFrontend@2 parse/elaborate attempt."""

    status: ParseStatus
    document: rules_v1.RuleDocument | None = None
    source_document: SourceDocument | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    typed_expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    chc_lowering: rules_v1.CHCLoweringResult | None = None
    schema_version: str = RULE_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = RULE_FRONTEND_V2_INTERFACE

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
        """True when every query is a typed statement (never a raw string)."""

        if self.document is None:
            return False
        for query in self.document.queries:
            # Authz queries carry principal/action/resource; goal queries carry head.
            if query.head is None and not (
                query.principal or query.action or query.resource
            ):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "chc_lowering": (
                None if self.chc_lowering is None else self.chc_lowering.to_dict()
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
# Descriptor builders
# ---------------------------------------------------------------------------


def build_rules_v2_descriptor(
    *,
    limits: FrontendLimits | None = None,
    descriptor_id: str = RULE_V2_DESCRIPTOR_ID,
    profile_id: str = RULE_V2_PROFILE_ID,
    family_id: str = RULE_V2_FAMILY_ID,
) -> LogicFrontendDescriptor:
    """Build the shared frontend descriptor for RuleFrontend@2."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
        FrontendFeature.TYPECHECK.value,
    )
    fixtures = build_baseline_fixture_set(features=features, prefix="rules-v2")
    extra = (
        FeatureScopedFixture(
            fixture_id="fixture:rules-v2:safety-unsafe",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.TYPECHECK.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Unsafe head variables reject with exact diagnostics.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:rules-v2:stratification",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.TYPECHECK.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Unstratified negation rejects with exact diagnostics.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:rules-v2:typed-query",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Queries elaborate as typed artifacts, not raw strings.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:rules-v2:priority-world",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="World and priority policies are first-class typed fields.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=descriptor_id,
        key=ParserKey(
            notation_id=RULE_V2_NOTATION_ID,
            notation_version=RULE_V2_NOTATION_VERSION,
            semantic_profile_id=profile_id,
        ),
        family_id=family_id,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_RULE_V2_CODES)),
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
            "open_recursion_unbounded",
            "aggregates",
            "disjunctive_heads",
            "raw_query_string",
            "unstratified_negation",
            "unsafe_variable",
        ),
        implementation="ipfs_datasets_py.logic.parsers.rules_v2:RuleFrontendV2",
        metadata={
            "task_id": RULE_V2_TASK_ID,
            "goal_id": RULE_V2_GOAL_ID,
            "interfaces": {
                "rule": RULE_FRONTEND_V2_INTERFACE,
                "secpal": SECPAL_FRONTEND_V2_INTERFACE,
                "rule_frame": RULE_FRAME_FRONTEND_INTERFACE,
                "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
            },
        },
    )


def build_secpal_v2_descriptor(
    *,
    limits: FrontendLimits | None = None,
) -> LogicFrontendDescriptor:
    """Build the shared frontend descriptor for SecPALFrontend@2."""

    return build_rules_v2_descriptor(
        limits=limits,
        descriptor_id=SECPAL_V2_DESCRIPTOR_ID,
        profile_id=SECPAL_V2_PROFILE_ID,
        family_id=SECPAL_V2_FAMILY_ID,
    )


def build_rule_frame_descriptor(
    *,
    limits: FrontendLimits | None = None,
) -> LogicFrontendDescriptor:
    """Build the joint RuleFrameFrontend@2 descriptor."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    base = build_rules_v2_descriptor(limits=bounds)
    features = base.features
    fixtures = tuple(base.fixtures) + (
        FeatureScopedFixture(
            fixture_id="fixture:rule-frame:joint-artifacts",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.ELABORATE.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description=(
                "Joint rules/frame path emits ParseArtifact@2 and "
                "ElaborationArtifact@2; raw queries never execute."
            ),
        ),
        FeatureScopedFixture(
            fixture_id="fixture:rule-frame:ambiguous-authz",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.TYPECHECK.value),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Ambiguous principal/resource/action terms reject closed.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=RULE_FRAME_DESCRIPTOR_ID,
        key=ParserKey(
            notation_id=RULE_V2_NOTATION_ID,
            notation_version=RULE_V2_NOTATION_VERSION,
            semantic_profile_id="rule_frame_joint",
        ),
        family_id=RULE_V2_FAMILY_ID,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_RULE_V2_CODES)),
        artifact_outputs=(
            make_parse_artifact_output(),
            make_elaboration_artifact_output(),
        ),
        fixtures=fixtures,
        recovery=RecoveryPolicy.NONE,
        printer=PrinterContract(
            guarantee=PrinterGuarantee.SEMANTIC,
            features=(FrontendFeature.PRINT.value,),
            deterministic=True,
        ),
        unsupported_behavior=UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC,
        unsupported_nodes=base.unsupported_nodes
        + (
            "frame_raw_query",
            "ergoai_execution",
        ),
        implementation="ipfs_datasets_py.logic.parsers.rules_v2:RuleFrameFrontend",
        metadata={
            "task_id": RULE_V2_TASK_ID,
            "goal_id": RULE_V2_GOAL_ID,
            "interfaces": {
                "rule_frame": RULE_FRAME_FRONTEND_INTERFACE,
                "rule": RULE_FRONTEND_V2_INTERFACE,
                "secpal": SECPAL_FRONTEND_V2_INTERFACE,
            },
            "evidence_subset": [
                "datalog",
                "horn",
                "chc",
                "secpal",
                "flogic",
                "ergoai",
                "rule",
                "frame",
            ],
        },
    )


def register_rules_v2_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_rules_v2_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


def register_secpal_v2_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_secpal_v2_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


def register_rule_frame_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    descriptor = build_rule_frame_descriptor(limits=limits)
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


# ---------------------------------------------------------------------------
# Frontends
# ---------------------------------------------------------------------------


class RuleFrontendV2:
    """Shared-artifact Datalog/Horn/CHC frontend.

    Interface: ``RuleFrontend@2``.
    """

    interface: ClassVar[str] = RULE_FRONTEND_V2_INTERFACE
    notation_id: ClassVar[str] = RULE_V2_NOTATION_ID
    notation_version: ClassVar[str] = RULE_V2_NOTATION_VERSION
    profile_id: ClassVar[str] = RULE_V2_PROFILE_ID
    family_id: ClassVar[str] = RULE_V2_FAMILY_ID
    module_version: ClassVar[str] = RULE_V2_MODULE_VERSION

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
        default_profile: rules_v1.RuleProfile | str = rules_v1.RuleProfile.HORN,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self.default_profile = (
            default_profile
            if isinstance(default_profile, rules_v1.RuleProfile)
            else rules_v1.RuleProfile(default_profile)
        )
        self._v1 = rules_v1.RuleFrontend(default_profile=self.default_profile)
        self.printer = self._v1.printer
        self.parser = self
        self._descriptor = build_rules_v2_descriptor(limits=self.limits)

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    def parse_limits(self) -> ParseLimits:
        return self.limits.parse_limits

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:rules:v2:1",
        request_id: str = "req:rules:v2:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        validate: bool = True,
        elaborate: bool = True,
        lower_chc: bool = False,
    ) -> RuleFrontendV2Result:
        del mode
        bounds = limits if limits is not None else self.parse_limits()

        if not isinstance(text, str):
            diag = _diag(
                code=CODE_INVALID_LITERAL,
                message="rule input must be a string",
                range=SourceRange(0, 0),
                diagnostic_id="diag:rules-v2:type",
            )
            return RuleFrontendV2Result(status=ParseStatus.FAILED, diagnostics=(diag,))

        try:
            source = SourceDocument.from_text(
                document_id,
                text,
                encoding="utf-8",
                language_hint="datalog_rules",
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
                diagnostic_id="diag:rules-v2:source",
            )
            return RuleFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )

        v1_result = self._v1.parse_text(
            text,
            document_id=document_id,
            limits=bounds,
            validate=validate,
        )
        diagnostics = _unique_diagnostics(v1_result.diagnostics)

        raw_tokens, lex_diags = rules_v1.tokenize_rules(text, limits=bounds)
        logic_tokens = _rules_tokens_to_logic_tokens(
            raw_tokens, document_id=document_id
        )
        if lex_diags and not diagnostics:
            diagnostics = _unique_diagnostics(lex_diags)

        if not v1_result.ok or v1_result.document is None:
            status = v1_result.status
            cst = _build_covering_cst(
                source, logic_tokens, cst_id=f"cst:rules:{request_id}"
            )
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:rules:parse:{request_id}",
                request_id=request_id,
                status=status,
                tokens=logic_tokens,
                cst=cst,
                surface_ast=(),
                diagnostics=diagnostics,
                metadata={
                    "interface": self.interface,
                    "stage": "parse_failed",
                    "raw_query_strings_admitted": False,
                    "execution_admitted": False,
                },
            )
            # Fail-closed: still emit a failed elaboration envelope so callers
            # cannot confuse a missing artifact with an executable path.
            elab = ElaborationArtifactV2(
                artifact_id=f"art:rules:elab:{request_id}",
                parse_artifact_id=artifact.artifact_id,
                document_id=source.document_id,
                source_digest=source.content_digest,
                status=ElaborationArtifactStatus.FAILED,
                parse_content_digest=artifact.content_digest,
                parse_lineage_digest=artifact.lineage_digest,
                diagnostics=diagnostics,
                metadata={
                    "interface": self.interface,
                    "execution_admitted": False,
                    "raw_query_strings_admitted": False,
                },
            )
            return RuleFrontendV2Result(
                status=status,
                document=v1_result.document,
                source_document=source,
                parse_artifact=artifact,
                elaboration_artifact=elab,
                diagnostics=diagnostics,
            )

        document = v1_result.document
        cst = _build_covering_cst(
            source, logic_tokens, cst_id=f"cst:rules:{request_id}"
        )
        surface = _surface_from_document(document, full_range=source.full_range())
        source_map = build_token_source_map(
            source, logic_tokens, map_id=f"map:rules:{request_id}"
        )
        printed = self.printer.print_document(document)

        # Reject any residual raw-query disposition (defensive fail-closed).
        raw_query_errors: list[SyntaxDiagnostic] = []
        for index, query in enumerate(document.queries):
            if query.raw and query.head is None and not (
                query.principal or query.action or query.resource
            ):
                raw_query_errors.append(
                    _diag(
                        code=CODE_RAW_QUERY,
                        message=(
                            "raw query string cannot reach execution; "
                            "queries must be typed RuleStatement artifacts"
                        ),
                        range=query.range or source.full_range(),
                        diagnostic_id=f"diag:rules-v2:raw-query:{index + 1}",
                        remediation=(
                            "Use ?- goal(...). or SecPAL query principal/action/"
                            "resource form"
                        ),
                    )
                )
        if raw_query_errors:
            diagnostics = _unique_diagnostics(
                tuple(diagnostics) + tuple(raw_query_errors)
            )
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:rules:parse:{request_id}",
                request_id=request_id,
                status=ParseStatus.FAILED,
                tokens=logic_tokens,
                cst=cst,
                surface_ast=surface,
                source_map=source_map,
                diagnostics=diagnostics,
                metadata={
                    "interface": self.interface,
                    "execution_admitted": False,
                    "raw_query_strings_admitted": False,
                },
            )
            elab = ElaborationArtifactV2(
                artifact_id=f"art:rules:elab:{request_id}",
                parse_artifact_id=artifact.artifact_id,
                document_id=source.document_id,
                source_digest=source.content_digest,
                status=ElaborationArtifactStatus.FAILED,
                parse_content_digest=artifact.content_digest,
                parse_lineage_digest=artifact.lineage_digest,
                diagnostics=diagnostics,
                metadata={"interface": self.interface, "execution_admitted": False},
            )
            return RuleFrontendV2Result(
                status=ParseStatus.FAILED,
                document=document,
                source_document=source,
                parse_artifact=artifact,
                elaboration_artifact=elab,
                diagnostics=diagnostics,
                printed=printed,
            )

        parse_artifact = ParseArtifactV2.from_document(
            source,
            artifact_id=f"art:rules:parse:{request_id}",
            request_id=request_id,
            status=ParseStatus.OK,
            tokens=logic_tokens,
            cst=cst,
            surface_ast=surface,
            source_map=source_map,
            diagnostics=diagnostics,
            metadata={
                "interface": self.interface,
                "notation_id": self.notation_id,
                "notation_version": self.notation_version,
                "profile_id": document.profile_id,
                "family_id": document.family_id,
                "profile": document.profile.value,
                "world_policy": (
                    None
                    if document.world_policy is None
                    else document.world_policy.value
                ),
                "priority_policy": (
                    None
                    if document.priority_policy is None
                    else document.priority_policy.value
                ),
                "predicate_names": list(document.predicate_names),
                "query_count": len(document.queries),
                "printed": printed,
                "raw_query_strings_admitted": False,
                "execution_admitted": False,
            },
        )
        parse_artifact.validate_against(source)

        elaboration_artifact: ElaborationArtifactV2 | None = None
        typed_expression: TypedExpression | None = None
        if elaborate:
            try:
                typed_expression, signature = _document_to_typed_expression(
                    document,
                    expression_id=f"expr:rules:{request_id}",
                    full_range=source.full_range(),
                    family=document.family_id,
                    profile=document.profile_id,
                )
                # Attach typed roots to parse artifact lineage.
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
                    diagnostics=diagnostics,
                    metadata=dict(parse_artifact.metadata),
                )
                parse_artifact.validate_against(source)
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:rules:elab:{request_id}",
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
                        "profile": document.profile.value,
                        "world_policy": (
                            None
                            if document.world_policy is None
                            else document.world_policy.value
                        ),
                        "priority_policy": (
                            None
                            if document.priority_policy is None
                            else document.priority_policy.value
                        ),
                        "queries_typed": True,
                        "raw_query_strings_admitted": False,
                        "execution_admitted": False,
                        "predicate_names": list(document.predicate_names),
                    },
                )
                elaboration_artifact.validate_lineage(
                    parse_artifact=parse_artifact, document=source
                )
            except (AstError, SyntaxContractError, ValueError, TypeError) as error:
                diag = _diag(
                    code=CODE_ELABORATION_FAILED,
                    message=f"rule elaboration failed: {error}",
                    range=source.full_range(),
                    diagnostic_id="diag:rules-v2:elab",
                )
                diagnostics = _unique_diagnostics(tuple(diagnostics) + (diag,))
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:rules:elab:{request_id}",
                    parse_artifact_id=parse_artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.FAILED,
                    parse_content_digest=parse_artifact.content_digest,
                    parse_lineage_digest=parse_artifact.lineage_digest,
                    diagnostics=diagnostics,
                    metadata={
                        "interface": self.interface,
                        "execution_admitted": False,
                    },
                )
                return RuleFrontendV2Result(
                    status=ParseStatus.FAILED,
                    document=document,
                    source_document=source,
                    parse_artifact=parse_artifact,
                    elaboration_artifact=elaboration_artifact,
                    diagnostics=diagnostics,
                    printed=printed,
                )

        chc: rules_v1.CHCLoweringResult | None = None
        if lower_chc:
            chc = rules_v1.lower_to_chc(document)

        return RuleFrontendV2Result(
            status=ParseStatus.OK,
            document=document,
            source_document=source,
            parse_artifact=parse_artifact,
            elaboration_artifact=elaboration_artifact,
            typed_expression=typed_expression,
            diagnostics=diagnostics,
            printed=printed,
            chc_lowering=chc,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> rules_v1.RuleDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise RuleFrontendV2Error(
                result.errors[0].message if result.errors else "rule parse failed",
                code=(
                    result.errors[0].code
                    if result.errors
                    else CODE_MALFORMED_STATEMENT
                ),
            )
        return result.document

    def print(self, document: rules_v1.RuleDocument) -> str:
        return self.printer.print_document(document)

    def normalize(self, document: rules_v1.RuleDocument) -> rules_v1.RuleDocument:
        return document.normalized()

    def elaborate(self, text: str, **kwargs: Any) -> RuleFrontendV2Result:
        kwargs = dict(kwargs)
        kwargs["elaborate"] = True
        return self.parse_text(text, **kwargs)

    def lower_to_chc(
        self, document: rules_v1.RuleDocument
    ) -> rules_v1.CHCLoweringResult:
        return rules_v1.lower_to_chc(document)

    def round_trip(self, text: str, **kwargs: Any) -> RuleFrontendV2Result:
        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:rules:v2:1") + ":rt",
            request_id=str(kwargs.get("request_id") or "req:rules:v2:1") + ":rt",
            limits=kwargs.get("limits"),
            validate=kwargs.get("validate", True),
            elaborate=kwargs.get("elaborate", True),
        )
        if not second.ok or second.document is None:
            return second
        if not rules_v1.documents_semantically_compatible(
            first.document, second.document
        ):
            if first.document.predicate_names != second.document.predicate_names:
                diag = _diag(
                    code=CODE_ROUND_TRIP,
                    message="parse/print/parse does not preserve rule structure",
                    range=SourceRange(0, 0),
                    diagnostic_id="diag:rules-v2:rt",
                )
                return RuleFrontendV2Result(
                    status=ParseStatus.FAILED,
                    document=second.document,
                    source_document=second.source_document,
                    parse_artifact=second.parse_artifact,
                    elaboration_artifact=second.elaboration_artifact,
                    typed_expression=second.typed_expression,
                    diagnostics=second.diagnostics + (diag,),
                    printed=printed,
                )
        return RuleFrontendV2Result(
            status=ParseStatus.OK,
            document=second.document,
            source_document=second.source_document,
            parse_artifact=second.parse_artifact,
            elaboration_artifact=second.elaboration_artifact,
            typed_expression=second.typed_expression,
            diagnostics=second.diagnostics,
            printed=printed,
        )

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        """Hard-fail: frontend never executes engines without typed artifacts."""

        raise RuleExecutionBlockedError(
            "RuleFrontend@2 does not execute rule engines; only typed "
            "ParseArtifact@2 / ElaborationArtifact@2 are produced",
            code=CODE_EXECUTION_BLOCKED,
            remediation=(
                "Pass typed artifacts to a separately admitted evaluation lane"
            ),
        )


class SecPALFrontendV2(RuleFrontendV2):
    """SecPAL / authorization profile specialization.

    Interface: ``SecPALFrontend@2``.
    """

    interface: ClassVar[str] = SECPAL_FRONTEND_V2_INTERFACE
    profile_id: ClassVar[str] = SECPAL_V2_PROFILE_ID
    family_id: ClassVar[str] = SECPAL_V2_FAMILY_ID

    def __init__(self, *, limits: FrontendLimits | ParseLimits | None = None) -> None:
        super().__init__(
            limits=limits, default_profile=rules_v1.RuleProfile.SECPAL
        )
        self._descriptor = build_secpal_v2_descriptor(
            limits=self.limits if isinstance(self.limits, FrontendLimits) else None
        )
        self._v1 = rules_v1.SecPALFrontend()
        self.printer = self._v1.printer


class RuleFrameFrontend:
    """Joint rules + frame convergence facade.

    Interface: ``RuleFrameFrontend@2``.

    Owns the fail-closed contract that unsafe/ambiguous rules and raw query
    strings cannot reach execution without typed artifacts and exact
    diagnostics.  Frame/F-logic work is delegated to ``flogic_v2`` when present.
    """

    interface: ClassVar[str] = RULE_FRAME_FRONTEND_INTERFACE
    module_version: ClassVar[str] = RULE_V2_MODULE_VERSION
    task_id: ClassVar[str] = RULE_V2_TASK_ID
    goal_id: ClassVar[str] = RULE_V2_GOAL_ID

    def __init__(
        self,
        *,
        limits: FrontendLimits | ParseLimits | None = None,
    ) -> None:
        if isinstance(limits, FrontendLimits):
            self.limits = limits
        elif isinstance(limits, ParseLimits):
            self.limits = FrontendLimits(parse_limits=limits)
        else:
            self.limits = DEFAULT_FRONTEND_LIMITS
        self.rules = RuleFrontendV2(limits=self.limits)
        self.secpal = SecPALFrontendV2(limits=self.limits)
        self._flogic: Any | None = None
        self._descriptor = build_rule_frame_descriptor(limits=self.limits)

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    @property
    def flogic(self) -> Any:
        """Lazy F-logic v2 frontend (avoids circular import at module load)."""

        if self._flogic is None:
            from ipfs_datasets_py.logic.parsers import flogic_v2 as _flogic_v2

            self._flogic = _flogic_v2.FLogicFrontendV2(limits=self.limits)
        return self._flogic

    def parse_rules(self, text: str, **kwargs: Any) -> RuleFrontendV2Result:
        return self.rules.parse_text(text, **kwargs)

    def parse_secpal(self, text: str, **kwargs: Any) -> RuleFrontendV2Result:
        return self.secpal.parse_text(text, **kwargs)

    def parse_flogic(self, text: str, **kwargs: Any) -> Any:
        return self.flogic.parse_text(text, **kwargs)

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuleExecutionBlockedError(
            "RuleFrameFrontend@2 never executes engines or ErgoAI; "
            "typed artifacts and exact diagnostics are required first",
            code=CODE_EXECUTION_BLOCKED,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_rules_v2(text: str, **kwargs: Any) -> RuleFrontendV2Result:
    """Parse Datalog/Horn/CHC source into shared typed artifacts."""

    return RuleFrontendV2().parse_text(text, **kwargs)


def parse_secpal_v2(text: str, **kwargs: Any) -> RuleFrontendV2Result:
    """Parse SecPAL/authorization source into shared typed artifacts."""

    return SecPALFrontendV2().parse_text(text, **kwargs)


def elaborate_rules_v2(text: str, **kwargs: Any) -> RuleFrontendV2Result:
    """Parse and elaborate into ParseArtifact@2 / ElaborationArtifact@2."""

    return RuleFrontendV2().elaborate(text, **kwargs)


def print_rules_v2(document: rules_v1.RuleDocument) -> str:
    return RuleFrontendV2().print(document)


def parse_print_parse_rules_v2(text: str, **kwargs: Any) -> RuleFrontendV2Result:
    return RuleFrontendV2().round_trip(text, **kwargs)


def documents_semantically_compatible(
    left: rules_v1.RuleDocument,
    right: rules_v1.RuleDocument,
) -> bool:
    return rules_v1.documents_semantically_compatible(left, right)


def lower_to_chc(document: rules_v1.RuleDocument) -> rules_v1.CHCLoweringResult:
    return rules_v1.lower_to_chc(document)


__all__ = [
    "CHCLoweringResult",
    "CODE_AMBIGUOUS_TERM",
    "CODE_ELABORATION_FAILED",
    "CODE_EMPTY_INPUT",
    "CODE_EXECUTION_BLOCKED",
    "CODE_INPUT_LIMIT",
    "CODE_MISSING_PRIORITY",
    "CODE_MISSING_WORLD",
    "CODE_RAW_QUERY",
    "CODE_ROUND_TRIP",
    "CODE_TOKEN_LIMIT",
    "CODE_UNSAFE_VARIABLE",
    "CODE_UNSTRATIFIED_NEGATION",
    "CODE_UNSUPPORTED_CONSTRUCT",
    "DEFAULT_FRONTEND_LIMITS",
    "DEFAULT_PARSE_LIMITS",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "PriorityPolicyKind",
    "RULE_FRAME_DESCRIPTOR_ID",
    "RULE_FRAME_FRONTEND_INTERFACE",
    "RULE_FRONTEND_V2_INTERFACE",
    "RULE_V2_DESCRIPTOR_ID",
    "RULE_V2_FAMILY_ID",
    "RULE_V2_GOAL_ID",
    "RULE_V2_MODULE_VERSION",
    "RULE_V2_NOTATION_ID",
    "RULE_V2_PROFILE_ID",
    "RULE_V2_TASK_ID",
    "RuleDocument",
    "RuleEffect",
    "RuleExecutionBlockedError",
    "RuleFrameFrontend",
    "RuleFrontendV2",
    "RuleFrontendV2Error",
    "RuleFrontendV2Result",
    "RuleItemRole",
    "RuleProfile",
    "RuleStatementKind",
    "SECPAL_FRONTEND_V2_INTERFACE",
    "SECPAL_V2_DESCRIPTOR_ID",
    "SECPAL_V2_FAMILY_ID",
    "SECPAL_V2_PROFILE_ID",
    "SecPALFrontendV2",
    "SecPALFrontendV2Error",
    "WorldPolicyKind",
    "build_rule_frame_descriptor",
    "build_rules_v2_descriptor",
    "build_secpal_v2_descriptor",
    "documents_semantically_compatible",
    "elaborate_rules_v2",
    "lower_to_chc",
    "parse_print_parse_rules_v2",
    "parse_rules_v2",
    "parse_secpal_v2",
    "print_rules_v2",
    "register_rule_frame_frontend",
    "register_rules_v2_frontend",
    "register_secpal_v2_frontend",
]
