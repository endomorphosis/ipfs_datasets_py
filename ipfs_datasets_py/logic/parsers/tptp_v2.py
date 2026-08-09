"""TPTP/TSTP shared typed artifact frontend (LFP2-012).

Interfaces:

* ``TPTPFrontend@2`` — controlled TPTP CNF/FOF/TFF problem parse that emits
  shared ``ParseArtifact@2`` / ``ElaborationArtifact@2`` envelopes with
  include policies, roles, source maps, and declared feature limits
* ``TSTPFrontend@1`` — controlled TSTP/SZS proof and status records that remain
  candidate-authority only (never theorem-trusted)

The v1 TPTP lexer/parser (``tptp.py``) is reused for surface syntax.  This
module converges that notation onto the Wave-2 shared artifact pipeline and
frontend descriptor contract (``LogicFrontendDescriptor@1``).

Controlled subset (Vampire/E-oriented):

* annotated formulas ``cnf`` / ``fof`` / ``tff`` with standard roles
* safe relative ``include(...)`` paths under an explicit include policy
* TSTP inference steps and SZS status lines as typed, untrusted candidates

Explicitly unsupported (fail closed / profile-scoped):

* THF / TFX / TXF higher-order dialects until a separate profile admits them
* absolute / parent-directory / URL include paths
* promotion of TSTP candidates to theorem authority
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.parsers import tptp as tptp_v1
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
    Binder,
    LogicNode,
    NodeKind,
    TypedExpression,
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
    BOOL_SORT,
    INDIVIDUAL_SORT,
    LogicSignature,
    atomic_sort,
    many_sorted_fol_signature,
    propositional_signature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

TPTP_FRONTEND_V2_INTERFACE: Final = "TPTPFrontend@2"
TSTP_FRONTEND_INTERFACE: Final = "TSTPFrontend@1"
TPTP_V2_NOTATION_ID: Final = "tptp"
TPTP_V2_NOTATION_VERSION: Final = "7.0.0"
TPTP_V2_PROFILE_ID: Final = "fof"
TPTP_V2_FAMILY_ID: Final = "first_order"
TPTP_V2_MODULE_VERSION: Final = "2.0.0"
TPTP_V2_TASK_ID: Final = "LFP2-012"
TPTP_V2_GOAL_ID: Final = FRONTEND_CONTRACT_GOAL_ID
TPTP_V2_PARSE_RESULT_SCHEMA: Final = "tptp-v2-parse-result/v1"
TSTP_V2_PARSE_RESULT_SCHEMA: Final = "tstp-v2-parse-result/v1"
TSTP_RECORD_SCHEMA_VERSION: Final = "tstp-record/v1"
INCLUDE_POLICY_SCHEMA_VERSION: Final = "tptp-include-policy/v1"
TPTP_V2_DESCRIPTOR_ID: Final = "frontend:tptp:v2:fof"
TSTP_V2_DESCRIPTOR_ID: Final = "frontend:tstp:v1:candidate"

# Re-export stable diagnostic codes from v1 (namespaced under tptp.*).
CODE_EMPTY_INPUT: Final = tptp_v1.CODE_EMPTY_INPUT
CODE_INPUT_LIMIT: Final = tptp_v1.CODE_INPUT_LIMIT
CODE_TOKEN_LIMIT: Final = tptp_v1.CODE_TOKEN_LIMIT
CODE_PARSE_DEPTH: Final = tptp_v1.CODE_PARSE_DEPTH
CODE_UNBALANCED: Final = tptp_v1.CODE_UNBALANCED
CODE_UNEXPECTED_TOKEN: Final = tptp_v1.CODE_UNEXPECTED_TOKEN
CODE_MALFORMED_ANNOTATED: Final = tptp_v1.CODE_MALFORMED_ANNOTATED
CODE_MALFORMED_FORMULA: Final = tptp_v1.CODE_MALFORMED_FORMULA
CODE_MALFORMED_ANNOTATION: Final = tptp_v1.CODE_MALFORMED_ANNOTATION
CODE_MALFORMED_INCLUDE: Final = tptp_v1.CODE_MALFORMED_INCLUDE
CODE_UNSAFE_INCLUDE: Final = tptp_v1.CODE_UNSAFE_INCLUDE
CODE_PATH_TRAVERSAL: Final = tptp_v1.CODE_PATH_TRAVERSAL
CODE_UNSUPPORTED_LANGUAGE: Final = tptp_v1.CODE_UNSUPPORTED_LANGUAGE
CODE_UNSUPPORTED_THF: Final = tptp_v1.CODE_UNSUPPORTED_THF
CODE_UNKNOWN_ROLE: Final = tptp_v1.CODE_UNKNOWN_ROLE
CODE_UNSUPPORTED_ROLE: Final = tptp_v1.CODE_UNSUPPORTED_ROLE
CODE_TRAILING_INPUT: Final = tptp_v1.CODE_TRAILING_INPUT
CODE_INVALID_LITERAL: Final = tptp_v1.CODE_INVALID_LITERAL
CODE_UNTERMINATED_STRING: Final = tptp_v1.CODE_UNTERMINATED_STRING
CODE_UNTERMINATED_COMMENT: Final = tptp_v1.CODE_UNTERMINATED_COMMENT
CODE_CANDIDATE_AUTHORITY: Final = tptp_v1.CODE_CANDIDATE_AUTHORITY
CODE_MALFORMED_SZS: Final = tptp_v1.CODE_MALFORMED_SZS
CODE_ROUND_TRIP: Final = tptp_v1.CODE_ROUND_TRIP
CODE_FEATURE_LIMIT: Final = "tptp.feature_limit"
CODE_INCLUDE_POLICY: Final = "tptp.include_policy"
CODE_PROFILE_UNSUPPORTED: Final = "tptp.profile_unsupported"
CODE_ELABORATION_FAILED: Final = "tptp.elaboration_failed"

_ALL_TPTP_V2_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_EMPTY_INPUT,
        CODE_INPUT_LIMIT,
        CODE_TOKEN_LIMIT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_UNEXPECTED_TOKEN,
        CODE_MALFORMED_ANNOTATED,
        CODE_MALFORMED_FORMULA,
        CODE_MALFORMED_ANNOTATION,
        CODE_MALFORMED_INCLUDE,
        CODE_UNSAFE_INCLUDE,
        CODE_PATH_TRAVERSAL,
        CODE_UNSUPPORTED_LANGUAGE,
        CODE_UNSUPPORTED_THF,
        CODE_UNKNOWN_ROLE,
        CODE_UNSUPPORTED_ROLE,
        CODE_TRAILING_INPUT,
        CODE_INVALID_LITERAL,
        CODE_UNTERMINATED_STRING,
        CODE_UNTERMINATED_COMMENT,
        CODE_CANDIDATE_AUTHORITY,
        CODE_MALFORMED_SZS,
        CODE_ROUND_TRIP,
        CODE_FEATURE_LIMIT,
        CODE_INCLUDE_POLICY,
        CODE_PROFILE_UNSUPPORTED,
        CODE_ELABORATION_FAILED,
    }
)

SUPPORTED_LANGUAGES: Final[frozenset[str]] = tptp_v1.SUPPORTED_LANGUAGES
UNSUPPORTED_LANGUAGES: Final[frozenset[str]] = tptp_v1.UNSUPPORTED_LANGUAGES
THF_LANGUAGES: Final[frozenset[str]] = tptp_v1.THF_LANGUAGES
SUPPORTED_ROLES: Final[frozenset[str]] = tptp_v1.SUPPORTED_ROLES
UNSUPPORTED_ROLES: Final[frozenset[str]] = tptp_v1.UNSUPPORTED_ROLES
SUPPORTED_SZS_STATUSES: Final[frozenset[str]] = tptp_v1.SUPPORTED_SZS_STATUSES

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

_TOKEN_KIND_MAP: Final[Mapping[tptp_v1.TokenKind, str]] = {
    tptp_v1.TokenKind.IDENT: CoreTokenKind.IDENTIFIER.value,
    tptp_v1.TokenKind.DOLLAR_IDENT: "dollar_ident",
    tptp_v1.TokenKind.VAR: "var",
    tptp_v1.TokenKind.INTEGER: CoreTokenKind.NUMBER.value,
    tptp_v1.TokenKind.REAL: CoreTokenKind.NUMBER.value,
    tptp_v1.TokenKind.STRING: CoreTokenKind.STRING.value,
    tptp_v1.TokenKind.DISTINCT: "distinct",
    tptp_v1.TokenKind.LPAREN: "lparen",
    tptp_v1.TokenKind.RPAREN: "rparen",
    tptp_v1.TokenKind.LBRACK: "lbrack",
    tptp_v1.TokenKind.RBRACK: "rbrack",
    tptp_v1.TokenKind.COMMA: "comma",
    tptp_v1.TokenKind.COLON: "colon",
    tptp_v1.TokenKind.DOT: "dot",
    tptp_v1.TokenKind.OP: CoreTokenKind.OPERATOR.value,
    tptp_v1.TokenKind.EOF: CoreTokenKind.EOF.value,
}

_SYMBOL_NAME_SAFE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_']{0,255}$")


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class IncludePolicy(StrEnum):
    """How include directives are admitted under feature limits."""

    REJECT = "reject"
    """Reject any include directive (standalone problem files only)."""

    RELATIVE_SAFE = "relative_safe"
    """Admit only safe relative paths (default Vampire/E problem policy)."""

    RECORD_ONLY = "record_only"
    """Record include directives without resolving external content."""


class TPTPProfileScope(StrEnum):
    """Profile-scoped dialect admission for higher-order forms."""

    FOF = "fof"
    """Default CNF/FOF/TFF controlled subset."""

    THF_DECLARED = "thf_declared"
    """THF is declared but not executable until admitted by a later profile."""


DEFAULT_INCLUDE_POLICY: Final = IncludePolicy.RELATIVE_SAFE
DEFAULT_PROFILE_SCOPE: Final = TPTPProfileScope.FOF


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TPTPFrontendV2Error(SyntaxContractError):
    """Base class for TPTPFrontend@2 failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_MALFORMED_FORMULA,
        remediation: str = "",
        range: SourceRange | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation
        self.range = range
        self.message = message


class TSTPFrontendError(TPTPFrontendV2Error):
    """Raised for TSTPFrontend@1 failures."""


# ---------------------------------------------------------------------------
# Include policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IncludePolicyConfig:
    """Declared include admission policy with feature limits."""

    policy: IncludePolicy | str = DEFAULT_INCLUDE_POLICY
    max_includes: int = 256
    allow_formula_selection: bool = True
    schema_version: str = INCLUDE_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        policy = (
            self.policy
            if isinstance(self.policy, IncludePolicy)
            else IncludePolicy(str(self.policy))
        )
        object.__setattr__(self, "policy", policy)
        if (
            isinstance(self.max_includes, bool)
            or not isinstance(self.max_includes, int)
            or self.max_includes <= 0
        ):
            raise TPTPFrontendV2Error(
                "max_includes must be a positive finite bound",
                code=CODE_FEATURE_LIMIT,
            )
        if not isinstance(self.allow_formula_selection, bool):
            raise TPTPFrontendV2Error(
                "allow_formula_selection must be a bool",
                code=CODE_INCLUDE_POLICY,
            )
        if self.schema_version != INCLUDE_POLICY_SCHEMA_VERSION:
            raise TPTPFrontendV2Error(
                f"unsupported include policy schema {self.schema_version!r}",
                code=CODE_INCLUDE_POLICY,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_formula_selection": self.allow_formula_selection,
            "max_includes": self.max_includes,
            "policy": (
                self.policy.value
                if isinstance(self.policy, IncludePolicy)
                else str(self.policy)
            ),
            "schema_version": self.schema_version,
        }


def validate_include_under_policy(
    path: str,
    *,
    config: IncludePolicyConfig | None = None,
    formula_selection: Sequence[str] = (),
) -> str:
    """Validate an include path against the active include policy."""

    bounds = config if config is not None else IncludePolicyConfig()
    policy = (
        bounds.policy
        if isinstance(bounds.policy, IncludePolicy)
        else IncludePolicy(str(bounds.policy))
    )
    if policy is IncludePolicy.REJECT:
        raise TPTPFrontendV2Error(
            f"include directives are rejected by policy {policy.value!r}: {path!r}",
            code=CODE_INCLUDE_POLICY,
            remediation="Use a self-contained problem or switch include policy",
        )
    if formula_selection and not bounds.allow_formula_selection:
        raise TPTPFrontendV2Error(
            "include formula selection is disabled by include policy",
            code=CODE_INCLUDE_POLICY,
        )
    # RELATIVE_SAFE and RECORD_ONLY both require safe relative paths.
    return tptp_v1.validate_include_path(path)


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
    prefix: str = "diag:tptp-v2",
) -> tuple[SyntaxDiagnostic, ...]:
    """Re-id diagnostics so ParseArtifact@2 uniqueness constraints hold."""

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
# Token / CST / source-map projection
# ---------------------------------------------------------------------------


def _tptp_tokens_to_logic_tokens(
    tokens: Sequence[tptp_v1.Token],
    *,
    document_id: str,
) -> tuple[LogicToken, ...]:
    logic_tokens: list[LogicToken] = []
    for index, token in enumerate(tokens):
        kind = _TOKEN_KIND_MAP.get(token.kind, CoreTokenKind.UNKNOWN.value)
        logic_tokens.append(
            LogicToken(
                token_id=f"tok:tptp:{index + 1}",
                kind=kind,
                lexeme=token.value,
                range=token.range,
                document_id=document_id,
                metadata={"tptp_kind": token.kind.value},
            )
        )
    return tuple(logic_tokens)


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:tptp:1",
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
    tptp_document: tptp_v1.TPTPDocument,
    *,
    full_range: SourceRange,
) -> tuple[SurfaceASTRef, ...]:
    """Build lightweight surface AST refs for annotated formulas and includes."""

    refs: list[SurfaceASTRef] = []
    child_ids: list[str] = []
    for index, item in enumerate(tptp_document.items):
        node_id = f"ast:item:{index + 1}"
        child_ids.append(node_id)
        if item.kind is tptp_v1.TPTPItemKind.INCLUDE and item.include is not None:
            span = item.include.range or full_range
            refs.append(
                SurfaceASTRef(
                    node_id=node_id,
                    kind="include",
                    range=span,
                    metadata={
                        "path": item.include.path,
                        "formula_selection": list(item.include.formula_selection),
                    },
                )
            )
            continue
        if item.annotated is None:
            continue
        ann = item.annotated
        span = ann.range or full_range
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind="annotated_formula",
                range=span,
                metadata={
                    "language": ann.language.value,
                    "name": ann.name,
                    "role": ann.role.value,
                    "formula_kind": (
                        ann.formula.kind.value
                        if isinstance(ann.formula.kind, tptp_v1.TPTPFormulaKind)
                        else str(ann.formula.kind)
                    ),
                },
            )
        )
    refs.append(
        SurfaceASTRef(
            node_id="ast:document",
            kind="tptp_document",
            range=full_range,
            child_ids=tuple(child_ids),
            metadata={
                "languages": list(tptp_document.languages),
                "roles": list(tptp_document.roles),
                "formula_names": list(tptp_document.formula_names),
            },
        )
    )
    # Child refs must appear before parent for unique walk; order is free as
    # long as child_ids reference existing nodes.
    return tuple(refs)


# ---------------------------------------------------------------------------
# Formula projection → LogicNode / signature
# ---------------------------------------------------------------------------


def _safe_symbol(name: str) -> str | None:
    if not name:
        return None
    if name.startswith("$"):
        # System identifiers: map $true/$false specially; sanitize others.
        if name in {"$true", "$false"}:
            return None
        cleaned = "sys_" + name.lstrip("$").replace("$", "_")
        return cleaned if _SYMBOL_NAME_SAFE.fullmatch(cleaned) else None
    if _SYMBOL_NAME_SAFE.fullmatch(name):
        return name
    cleaned = "".join(ch if ch.isalnum() or ch in "_'" else "_" for ch in name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    if not cleaned or not _SYMBOL_NAME_SAFE.fullmatch(cleaned):
        return None
    return cleaned


def _sort_from_name(name: str) -> Any:
    if name in {"$o", "Bool", "bool"}:
        return BOOL_SORT
    if name in {"$i", "Individual", ""}:
        return INDIVIDUAL_SORT
    cleaned = _safe_symbol(name) or "Individual"
    if cleaned == "Bool":
        return BOOL_SORT
    return atomic_sort(cleaned)


def _project_formula(
    formula: tptp_v1.TPTPFormula,
    *,
    counter: list[int],
    under_term: bool = False,
) -> LogicNode:
    counter[0] += 1
    node_id = f"node:tptp:{counter[0]}"
    kind = (
        formula.kind
        if isinstance(formula.kind, tptp_v1.TPTPFormulaKind)
        else tptp_v1.TPTPFormulaKind(str(formula.kind))
    )
    span = formula.range

    if kind is tptp_v1.TPTPFormulaKind.TRUE:
        return LogicNode(node_id=node_id, kind=NodeKind.TRUE, range=span)
    if kind is tptp_v1.TPTPFormulaKind.FALSE:
        return LogicNode(node_id=node_id, kind=NodeKind.FALSE, range=span)

    if kind is tptp_v1.TPTPFormulaKind.VAR:
        symbol = _safe_symbol(formula.name) or "X"
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.VARIABLE,
            symbol=symbol,
            sort=INDIVIDUAL_SORT,
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.FUN:
        symbol = _safe_symbol(formula.name) or "f"
        args = tuple(
            _project_formula(arg, counter=counter, under_term=True)
            for arg in formula.arguments
        )
        if not args:
            return LogicNode(
                node_id=node_id,
                kind=NodeKind.CONSTANT,
                symbol=symbol,
                sort=INDIVIDUAL_SORT,
                range=span,
            )
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.APPLICATION,
            symbol=symbol,
            arguments=args,
            sort=INDIVIDUAL_SORT,
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.ATOM:
        if formula.name in {"$true"}:
            return LogicNode(node_id=node_id, kind=NodeKind.TRUE, range=span)
        if formula.name in {"$false"}:
            return LogicNode(node_id=node_id, kind=NodeKind.FALSE, range=span)
        symbol = _safe_symbol(formula.name) or "p"
        args = tuple(
            _project_formula(arg, counter=counter, under_term=True)
            for arg in formula.arguments
        )
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.PREDICATE,
            symbol=symbol,
            arguments=args,
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.NOT:
        body = _project_formula(formula.arguments[0], counter=counter)
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.NOT,
            arguments=(body,),
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.AND:
        args = tuple(_project_formula(a, counter=counter) for a in formula.arguments)
        if len(args) == 1:
            return args[0]
        if not args:
            return LogicNode(node_id=node_id, kind=NodeKind.TRUE, range=span)
        return LogicNode(node_id=node_id, kind=NodeKind.AND, arguments=args, range=span)

    if kind is tptp_v1.TPTPFormulaKind.OR or kind is tptp_v1.TPTPFormulaKind.CLAUSE:
        args = tuple(_project_formula(a, counter=counter) for a in formula.arguments)
        if len(args) == 1:
            return args[0]
        if not args:
            return LogicNode(node_id=node_id, kind=NodeKind.FALSE, range=span)
        return LogicNode(node_id=node_id, kind=NodeKind.OR, arguments=args, range=span)

    if kind is tptp_v1.TPTPFormulaKind.IMPLIES:
        left = _project_formula(formula.arguments[0], counter=counter)
        right = _project_formula(formula.arguments[1], counter=counter)
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.IMPLIES,
            arguments=(left, right),
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.IFF:
        left = _project_formula(formula.arguments[0], counter=counter)
        right = _project_formula(formula.arguments[1], counter=counter)
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.IFF,
            arguments=(left, right),
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.EQ:
        left = _project_formula(formula.arguments[0], counter=counter, under_term=True)
        right = _project_formula(formula.arguments[1], counter=counter, under_term=True)
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.EQUALITY,
            arguments=(left, right),
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.NEQ:
        left = _project_formula(formula.arguments[0], counter=counter, under_term=True)
        right = _project_formula(formula.arguments[1], counter=counter, under_term=True)
        eq = LogicNode(
            node_id=f"{node_id}:eq",
            kind=NodeKind.EQUALITY,
            arguments=(left, right),
            range=span,
        )
        return LogicNode(
            node_id=node_id,
            kind=NodeKind.NOT,
            arguments=(eq,),
            range=span,
        )

    if kind is tptp_v1.TPTPFormulaKind.FORALL or kind is tptp_v1.TPTPFormulaKind.EXISTS:
        binders: list[Binder] = []
        for var, sort_name in formula.binders:
            symbol = _safe_symbol(var) or "X"
            binders.append(Binder(name=symbol, sort=_sort_from_name(sort_name)))
        body = _project_formula(formula.arguments[0], counter=counter)
        return LogicNode(
            node_id=node_id,
            kind=(
                NodeKind.FORALL
                if kind is tptp_v1.TPTPFormulaKind.FORALL
                else NodeKind.EXISTS
            ),
            binders=tuple(binders),
            arguments=(body,),
            range=span,
        )

    # TYPE_DECL and unknown kinds: propositional placeholder.
    del under_term
    return LogicNode(node_id=node_id, kind=NodeKind.TRUE, range=span)


def _collect_signature_from_node(
    node: LogicNode,
    *,
    constants: dict[str, Any],
    functions: dict[str, tuple[int, Any]],
    predicates: dict[str, int],
    sorts: dict[str, Any],
) -> None:
    kind = node.kind
    if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
        if node.symbol:
            constants[node.symbol] = node.sort or INDIVIDUAL_SORT
    elif kind is NodeKind.APPLICATION or kind == NodeKind.APPLICATION.value:
        if node.symbol:
            functions[node.symbol] = (len(node.arguments), node.sort or INDIVIDUAL_SORT)
    elif kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
        if node.symbol:
            predicates[node.symbol] = len(node.arguments)
    elif kind is NodeKind.VARIABLE or kind == NodeKind.VARIABLE.value:
        pass
    for binder in node.binders:
        if binder.sort.name not in {"Bool"}:
            sorts[binder.sort.name] = binder.sort
    for child in node.arguments:
        _collect_signature_from_node(
            child,
            constants=constants,
            functions=functions,
            predicates=predicates,
            sorts=sorts,
        )


def _build_signature_for_roots(
    roots: Sequence[LogicNode],
    *,
    signature_id: str = "sig:tptp:v2",
) -> LogicSignature:
    constants: dict[str, Any] = {}
    functions: dict[str, tuple[int, Any]] = {}
    predicates: dict[str, int] = {}
    sorts: dict[str, Any] = {INDIVIDUAL_SORT.name: INDIVIDUAL_SORT}
    for root in roots:
        _collect_signature_from_node(
            root,
            constants=constants,
            functions=functions,
            predicates=predicates,
            sorts=sorts,
        )
    # Drop symbols that collide across kinds (prefer predicates).
    for name in list(constants):
        if name in predicates or name in functions:
            constants.pop(name, None)
    for name in list(functions):
        if name in predicates:
            functions.pop(name, None)

    const_decls = [(name, sort) for name, sort in sorted(constants.items())]
    fun_decls = [
        (name, tuple(INDIVIDUAL_SORT for _ in range(arity)), range_sort)
        for name, (arity, range_sort) in sorted(functions.items())
        if arity > 0
    ]
    # Nullary functions become constants.
    for name, (arity, range_sort) in sorted(functions.items()):
        if arity == 0:
            const_decls.append((name, range_sort))
    pred_decls = [
        (name, tuple(INDIVIDUAL_SORT for _ in range(arity)))
        for name, arity in sorted(predicates.items())
    ]
    sort_tuple = tuple(
        sort
        for name, sort in sorted(sorts.items())
        if name not in {BOOL_SORT.name, INDIVIDUAL_SORT.name}
    )
    if not const_decls and not fun_decls and not pred_decls:
        return LogicSignature(
            signature_id=signature_id,
            family=TPTP_V2_FAMILY_ID,
            profile=TPTP_V2_PROFILE_ID,
            sorts=(INDIVIDUAL_SORT,),
            symbols=(),
            features=("tptp", "first_order"),
        )
    return many_sorted_fol_signature(
        signature_id,
        sorts=(INDIVIDUAL_SORT, *sort_tuple),
        constants=const_decls,
        functions=fun_decls,
        predicates=pred_decls,
        family=TPTP_V2_FAMILY_ID,
        profile=TPTP_V2_PROFILE_ID,
        features=("tptp", "first_order", "many_sorted"),
    )


def _document_to_typed_expression(
    tptp_document: tptp_v1.TPTPDocument,
    *,
    expression_id: str = "expr:tptp:v2:1",
    full_range: SourceRange | None = None,
) -> tuple[TypedExpression, LogicSignature]:
    """Project a TPTP document into a TypedExpression (shared artifact root)."""

    counter = [0]
    formula_nodes: list[LogicNode] = []
    for ann in tptp_document.formulas:
        try:
            formula_nodes.append(_project_formula(ann.formula, counter=counter))
        except (AstError, SyntaxContractError, ValueError, TypeError):
            # Fall back per-formula to a named nullary predicate.
            symbol = _safe_symbol(ann.name) or f"formula_{len(formula_nodes) + 1}"
            counter[0] += 1
            formula_nodes.append(
                LogicNode(
                    node_id=f"node:tptp:fallback:{counter[0]}",
                    kind=NodeKind.PREDICATE,
                    symbol=symbol,
                    range=ann.range,
                )
            )

    if not formula_nodes:
        root = LogicNode(
            node_id="node:tptp:empty",
            kind=NodeKind.TRUE,
            range=full_range,
        )
        signature = LogicSignature(
            signature_id="sig:tptp:v2:empty",
            family=TPTP_V2_FAMILY_ID,
            profile=TPTP_V2_PROFILE_ID,
            sorts=(INDIVIDUAL_SORT,),
            symbols=(),
            features=("tptp",),
        )
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=TPTP_V2_FAMILY_ID,
            profile=TPTP_V2_PROFILE_ID,
            range=full_range,
            elaborate_on_init=False,
            metadata={"tptp_empty": True, "includes": list(
                inc.path for inc in tptp_document.includes
            )},
        )
        return expression, signature

    if len(formula_nodes) == 1:
        root = formula_nodes[0]
    else:
        root = LogicNode(
            node_id="node:tptp:document",
            kind=NodeKind.AND,
            arguments=tuple(formula_nodes),
            range=full_range,
        )

    try:
        signature = _build_signature_for_roots((root,), signature_id="sig:tptp:v2")
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=TPTP_V2_FAMILY_ID,
            profile=TPTP_V2_PROFILE_ID,
            range=full_range or root.range,
            elaborate_on_init=False,
            metadata={
                "languages": list(tptp_document.languages),
                "roles": list(tptp_document.roles),
                "formula_names": list(tptp_document.formula_names),
            },
        )
        return expression, signature
    except (AstError, SyntaxContractError, ValueError, TypeError):
        # Ultimate fallback: propositional abstraction over formula names.
        names: list[str] = []
        for ann in tptp_document.formulas:
            symbol = _safe_symbol(ann.name)
            if symbol:
                names.append(symbol)
        if not names:
            names = ["goal"]
        # Unique preserve order.
        seen: set[str] = set()
        unique: list[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        signature = propositional_signature(
            "sig:tptp:v2:prop",
            unique,
            family=TPTP_V2_FAMILY_ID,
            profile=TPTP_V2_PROFILE_ID,
        )
        preds = [
            LogicNode(
                node_id=f"node:tptp:prop:{index + 1}",
                kind=NodeKind.PREDICATE,
                symbol=name,
            )
            for index, name in enumerate(unique)
        ]
        root = (
            preds[0]
            if len(preds) == 1
            else LogicNode(
                node_id="node:tptp:prop:and",
                kind=NodeKind.AND,
                arguments=tuple(preds),
            )
        )
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=TPTP_V2_FAMILY_ID,
            profile=TPTP_V2_PROFILE_ID,
            range=full_range,
            elaborate_on_init=False,
            metadata={"projection": "propositional_fallback"},
        )
        return expression, signature


# ---------------------------------------------------------------------------
# Parse / elaborate result envelopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TPTPFrontendV2Result:
    """Typed result of a TPTPFrontend@2 parse/elaborate attempt."""

    status: ParseStatus
    document: tptp_v1.TPTPDocument | None = None
    source_document: SourceDocument | None = None
    parse_artifact: ParseArtifactV2 | None = None
    elaboration_artifact: ElaborationArtifactV2 | None = None
    typed_expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    schema_version: str = TPTP_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = TPTP_FRONTEND_V2_INTERFACE

    @property
    def ok(self) -> bool:
        return (
            self.status is ParseStatus.OK
            and self.document is not None
            and self.parse_artifact is not None
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
            "interface": self.interface,
            "parse_artifact": (
                None if self.parse_artifact is None else self.parse_artifact.to_dict()
            ),
            "printed": self.printed,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class TSTPProofRecord:
    """Controlled typed TSTP proof/status record (candidate authority only).

    Interface payload under ``TSTPFrontend@1``.  Never claims theorem trust.
    """

    steps: tuple[tptp_v1.TSTPProofStep, ...] = ()
    szs_status: str = ""
    szs_output_form: str = ""
    authority: ResultAuthority = ResultAuthority.CANDIDATE
    status: ResultStatus = ResultStatus.CANDIDATE
    trusted: bool = False
    parse_artifact: ParseArtifactV2 | None = None
    source_text: str = ""
    schema_version: str = TSTP_RECORD_SCHEMA_VERSION
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "szs_status", str(self.szs_status or ""))
        object.__setattr__(self, "szs_output_form", str(self.szs_output_form or ""))
        object.__setattr__(self, "trusted", False)
        authority = (
            self.authority
            if isinstance(self.authority, ResultAuthority)
            else ResultAuthority(str(self.authority))
        )
        if authority is not ResultAuthority.CANDIDATE:
            raise TSTPFrontendError(
                "TSTP records must use ResultAuthority.CANDIDATE; "
                f"got {authority!r}",
                code=CODE_CANDIDATE_AUTHORITY,
                remediation="Do not promote TSTP output to theorem authority",
            )
        object.__setattr__(self, "authority", ResultAuthority.CANDIDATE)
        status = (
            self.status
            if isinstance(self.status, ResultStatus)
            else ResultStatus(str(self.status))
        )
        if status is not ResultStatus.CANDIDATE:
            raise TSTPFrontendError(
                "TSTP records must use ResultStatus.CANDIDATE; "
                f"got {status!r}",
                code=CODE_CANDIDATE_AUTHORITY,
            )
        object.__setattr__(self, "status", ResultStatus.CANDIDATE)
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise TSTPFrontendError(
                "record metadata must be immutable JSON data",
                code=CODE_MALFORMED_ANNOTATION,
            ) from error
        if self.schema_version != TSTP_RECORD_SCHEMA_VERSION:
            raise TSTPFrontendError(
                f"unsupported TSTP record schema {self.schema_version!r}",
                code=CODE_MALFORMED_ANNOTATED,
            )

    @property
    def interface(self) -> str:
        return TSTP_FRONTEND_INTERFACE

    @property
    def is_trusted(self) -> bool:
        return False

    @property
    def step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "interface": self.interface,
            "metadata": self.metadata.to_dict(),
            "parse_artifact": (
                None if self.parse_artifact is None else self.parse_artifact.to_dict()
            ),
            "schema_version": self.schema_version,
            "status": self.status.value,
            "step_names": list(self.step_names),
            "steps": [item.to_dict() for item in self.steps],
            "szs_output_form": self.szs_output_form,
            "szs_status": self.szs_status,
            "trusted": False,
        }


@dataclass(frozen=True, slots=True)
class TSTPFrontendResult:
    """Typed result of a TSTPFrontend@1 parse."""

    status: ParseStatus
    record: TSTPProofRecord | None = None
    parse_artifact: ParseArtifactV2 | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    schema_version: str = TSTP_V2_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = TSTP_FRONTEND_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.record is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "interface": self.interface,
            "parse_artifact": (
                None if self.parse_artifact is None else self.parse_artifact.to_dict()
            ),
            "record": None if self.record is None else self.record.to_dict(),
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


# ---------------------------------------------------------------------------
# Descriptor / feature limits
# ---------------------------------------------------------------------------


def build_tptp_v2_descriptor(
    *,
    limits: FrontendLimits | None = None,
    include_policy: IncludePolicyConfig | None = None,
) -> LogicFrontendDescriptor:
    """Build the shared frontend descriptor for TPTPFrontend@2."""

    bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
    policy = include_policy if include_policy is not None else IncludePolicyConfig()
    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
        FrontendFeature.TYPECHECK.value,
    )
    fixtures = build_baseline_fixture_set(
        features=features,
        prefix="tptp-v2",
    )
    # Extra evidence-scoped fixtures for include policy / THF / TSTP.
    extra = (
        FeatureScopedFixture(
            fixture_id="fixture:tptp-v2:include-safe",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value,),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Safe relative include admitted under relative_safe policy.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:tptp-v2:include-traversal",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value,),
            expected_disposition=ExpectedDisposition.REJECT,
            description="Path traversal include rejected with span.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:tptp-v2:thf-unsupported",
            kind=FixtureKind.NEGATIVE,
            features=(FrontendFeature.PARSE.value,),
            expected_disposition=ExpectedDisposition.UNSUPPORTED,
            description="THF remains profile-scoped unsupported until admitted.",
        ),
        FeatureScopedFixture(
            fixture_id="fixture:tptp-v2:tstp-candidate",
            kind=FixtureKind.POSITIVE,
            features=(FrontendFeature.PARSE.value, FrontendFeature.SOURCE_MAP.value),
            expected_disposition=ExpectedDisposition.ACCEPT,
            description="Controlled TSTP/SZS record typed at candidate authority.",
        ),
    )
    return LogicFrontendDescriptor(
        descriptor_id=TPTP_V2_DESCRIPTOR_ID,
        key=ParserKey(
            notation_id=TPTP_V2_NOTATION_ID,
            notation_version=TPTP_V2_NOTATION_VERSION,
            semantic_profile_id=TPTP_V2_PROFILE_ID,
        ),
        family_id=TPTP_V2_FAMILY_ID,
        features=features,
        parse_modes=(ParseMode.STRICT,),
        limits=bounds,
        diagnostics=tuple(sorted(_ALL_TPTP_V2_CODES)),
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
            "thf",
            "tfx",
            "txf",
            "tcf",
            "absolute_include",
            "url_include",
        ),
        implementation=(
            "ipfs_datasets_py.logic.parsers.tptp_v2:TPTPFrontendV2"
        ),
        metadata={
            "task_id": TPTP_V2_TASK_ID,
            "goal_id": TPTP_V2_GOAL_ID,
            "include_policy": policy.to_dict(),
            "profile_scope": DEFAULT_PROFILE_SCOPE.value,
            "interfaces": {
                "tptp": TPTP_FRONTEND_V2_INTERFACE,
                "tstp": TSTP_FRONTEND_INTERFACE,
                "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
            },
            "supported_languages": sorted(SUPPORTED_LANGUAGES),
            "supported_roles": sorted(SUPPORTED_ROLES),
        },
    )


def register_tptp_v2_frontend(
    registry: SharedFrontendConformance | None = None,
    *,
    limits: FrontendLimits | None = None,
    include_policy: IncludePolicyConfig | None = None,
) -> tuple[SharedFrontendConformance, LogicFrontendDescriptor]:
    """Validate and register the TPTPFrontend@2 descriptor."""

    descriptor = build_tptp_v2_descriptor(
        limits=limits, include_policy=include_policy
    )
    validate_frontend_descriptor(descriptor)
    target = registry if registry is not None else SharedFrontendConformance()
    admitted = target.register(descriptor)
    return target, admitted


# ---------------------------------------------------------------------------
# TPTPFrontend@2
# ---------------------------------------------------------------------------


class TPTPFrontendV2:
    """Shared-artifact TPTP frontend.

    Interface: ``TPTPFrontend@2``.
    """

    interface: ClassVar[str] = TPTP_FRONTEND_V2_INTERFACE
    notation_id: ClassVar[str] = TPTP_V2_NOTATION_ID
    notation_version: ClassVar[str] = TPTP_V2_NOTATION_VERSION
    profile_id: ClassVar[str] = TPTP_V2_PROFILE_ID
    family_id: ClassVar[str] = TPTP_V2_FAMILY_ID
    module_version: ClassVar[str] = TPTP_V2_MODULE_VERSION

    def __init__(
        self,
        *,
        limits: FrontendLimits | None = None,
        include_policy: IncludePolicyConfig | None = None,
        profile_scope: TPTPProfileScope | str = DEFAULT_PROFILE_SCOPE,
    ) -> None:
        self.limits = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
        self.include_policy = (
            include_policy if include_policy is not None else IncludePolicyConfig()
        )
        self.profile_scope = (
            profile_scope
            if isinstance(profile_scope, TPTPProfileScope)
            else TPTPProfileScope(str(profile_scope))
        )
        self._v1 = tptp_v1.TPTPFrontend()
        self.printer = self._v1.printer
        self.tstp = TSTPFrontend(
            limits=self.limits,
            include_policy=self.include_policy,
        )
        self._descriptor = build_tptp_v2_descriptor(
            limits=self.limits, include_policy=self.include_policy
        )

    @property
    def descriptor(self) -> LogicFrontendDescriptor:
        return self._descriptor

    def parse_limits(self) -> ParseLimits:
        return self.limits.parse_limits

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:tptp:v2:1",
        request_id: str = "req:tptp:v2:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        elaborate: bool = True,
    ) -> TPTPFrontendV2Result:
        del mode  # strict-only controlled subset
        bounds = limits if limits is not None else self.parse_limits()

        if not isinstance(text, str):
            diag = _diag(
                code=CODE_INVALID_LITERAL,
                message="TPTP input must be a string",
                range=SourceRange(0, 0),
                diagnostic_id="diag:tptp-v2:type",
            )
            return TPTPFrontendV2Result(
                status=ParseStatus.FAILED, diagnostics=(diag,)
            )

        try:
            source = SourceDocument.from_text(
                document_id, text, encoding="utf-8", language_hint="tptp"
            )
        except SyntaxContractError as error:
            diag = _diag(
                code=CODE_INPUT_LIMIT,
                message=str(error),
                range=SourceRange(0, 0),
                diagnostic_id="diag:tptp-v2:source",
            )
            return TPTPFrontendV2Result(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )

        # Profile-scoped THF: still rejected under the default fof profile.
        if self.profile_scope is TPTPProfileScope.FOF:
            # v1 already rejects THF; keep explicit profile metadata.
            pass

        v1_result = self._v1.parse_text(
            text, document_id=document_id, limits=bounds
        )
        diagnostics = _unique_diagnostics(v1_result.diagnostics)

        # Tokenize for shared artifacts (even on failure when possible).
        raw_tokens, lex_diags = tptp_v1.tokenize_tptp(text, limits=bounds)
        logic_tokens = _tptp_tokens_to_logic_tokens(
            raw_tokens, document_id=document_id
        )
        if lex_diags and not diagnostics:
            diagnostics = _unique_diagnostics(lex_diags)

        if not v1_result.ok or v1_result.document is None:
            status = v1_result.status
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:tptp:parse:{request_id}",
                request_id=request_id,
                status=status,
                tokens=logic_tokens,
                cst=None,
                surface_ast=(),
                diagnostics=diagnostics,
                metadata={
                    "interface": TPTP_FRONTEND_V2_INTERFACE,
                    "profile_scope": self.profile_scope.value,
                    "include_policy": self.include_policy.to_dict(),
                },
            )
            return TPTPFrontendV2Result(
                status=status,
                source_document=source,
                parse_artifact=artifact,
                diagnostics=diagnostics,
            )

        document = v1_result.document

        # Enforce include policy feature limits on successful parses.
        include_errors: list[SyntaxDiagnostic] = []
        if len(document.includes) > self.include_policy.max_includes:
            include_errors.append(
                _diag(
                    code=CODE_FEATURE_LIMIT,
                    message=(
                        f"include count {len(document.includes)} exceeds "
                        f"max_includes={self.include_policy.max_includes}"
                    ),
                    range=source.full_range(),
                    diagnostic_id="diag:tptp-v2:include-limit",
                )
            )
        for include in document.includes:
            try:
                validate_include_under_policy(
                    include.path,
                    config=self.include_policy,
                    formula_selection=include.formula_selection,
                )
            except (TPTPFrontendV2Error, tptp_v1.TPTPError) as error:
                code = getattr(error, "code", CODE_INCLUDE_POLICY)
                include_errors.append(
                    _diag(
                        code=code,
                        message=str(error),
                        range=include.range or source.full_range(),
                        diagnostic_id=(
                            f"diag:tptp-v2:include:{len(include_errors) + 1}"
                        ),
                        remediation=getattr(error, "remediation", ""),
                    )
                )
        if include_errors:
            diagnostics = _unique_diagnostics(
                tuple(diagnostics) + tuple(include_errors)
            )
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:tptp:parse:{request_id}",
                request_id=request_id,
                status=ParseStatus.FAILED,
                tokens=logic_tokens,
                diagnostics=diagnostics,
                metadata={
                    "interface": TPTP_FRONTEND_V2_INTERFACE,
                    "include_policy": self.include_policy.to_dict(),
                },
            )
            return TPTPFrontendV2Result(
                status=ParseStatus.FAILED,
                document=document,
                source_document=source,
                parse_artifact=artifact,
                diagnostics=diagnostics,
            )

        cst = _build_covering_cst(
            source, logic_tokens, cst_id=f"cst:tptp:{request_id}"
        )
        surface = _surface_from_document(document, full_range=source.full_range())
        source_map = build_token_source_map(
            source, logic_tokens, map_id=f"map:tptp:{request_id}"
        )
        printed = self.printer.print_document(document)

        parse_artifact = ParseArtifactV2.from_document(
            source,
            artifact_id=f"art:tptp:parse:{request_id}",
            request_id=request_id,
            status=ParseStatus.OK,
            tokens=logic_tokens,
            cst=cst,
            surface_ast=surface,
            source_map=source_map,
            diagnostics=diagnostics,
            metadata={
                "interface": TPTP_FRONTEND_V2_INTERFACE,
                "notation_id": TPTP_V2_NOTATION_ID,
                "notation_version": TPTP_V2_NOTATION_VERSION,
                "profile_id": TPTP_V2_PROFILE_ID,
                "profile_scope": self.profile_scope.value,
                "include_policy": self.include_policy.to_dict(),
                "languages": list(document.languages),
                "roles": list(document.roles),
                "formula_names": list(document.formula_names),
                "include_paths": [item.path for item in document.includes],
                "printed": printed,
                "document": document.to_dict(),
            },
        )
        parse_artifact.validate_against(source)

        elaboration_artifact: ElaborationArtifactV2 | None = None
        typed_expression: TypedExpression | None = None
        if elaborate:
            try:
                typed_expression, signature = _document_to_typed_expression(
                    document,
                    expression_id=f"expr:tptp:{request_id}",
                    full_range=source.full_range(),
                )
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:tptp:elab:{request_id}",
                    parse_artifact_id=parse_artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.OK,
                    typed_expression=typed_expression,
                    root=typed_expression.root,
                    signature=signature,
                    parse_content_digest=parse_artifact.content_digest,
                    parse_lineage_digest=parse_artifact.lineage_digest,
                    diagnostics=(),
                    metadata={
                        "interface": TPTP_FRONTEND_V2_INTERFACE,
                        "roles": list(document.roles),
                        "languages": list(document.languages),
                    },
                )
            except (AstError, SyntaxContractError, ValueError, TypeError) as error:
                diag = _diag(
                    code=CODE_ELABORATION_FAILED,
                    message=f"TPTP elaboration failed: {error}",
                    range=source.full_range(),
                    diagnostic_id="diag:tptp-v2:elab",
                )
                diagnostics = _unique_diagnostics(tuple(diagnostics) + (diag,))
                elaboration_artifact = ElaborationArtifactV2(
                    artifact_id=f"art:tptp:elab:{request_id}",
                    parse_artifact_id=parse_artifact.artifact_id,
                    document_id=source.document_id,
                    source_digest=source.content_digest,
                    status=ElaborationArtifactStatus.FAILED,
                    parse_content_digest=parse_artifact.content_digest,
                    parse_lineage_digest=parse_artifact.lineage_digest,
                    diagnostics=diagnostics,
                    metadata={"interface": TPTP_FRONTEND_V2_INTERFACE},
                )

        return TPTPFrontendV2Result(
            status=ParseStatus.OK,
            document=document,
            source_document=source,
            parse_artifact=parse_artifact,
            elaboration_artifact=elaboration_artifact,
            typed_expression=typed_expression,
            diagnostics=diagnostics,
            printed=printed,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> tptp_v1.TPTPDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise TPTPFrontendV2Error(
                result.errors[0].message if result.errors else "TPTP parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_FORMULA,
            )
        return result.document

    def print(self, document: tptp_v1.TPTPDocument) -> str:
        return self.printer.print_document(document)

    def elaborate(self, text: str, **kwargs: Any) -> TPTPFrontendV2Result:
        kwargs = dict(kwargs)
        kwargs["elaborate"] = True
        return self.parse_text(text, **kwargs)

    def round_trip(self, text: str, **kwargs: Any) -> TPTPFrontendV2Result:
        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:tptp:v2:1") + ":rt",
            request_id=str(kwargs.get("request_id") or "req:tptp:v2:1") + ":rt",
            limits=kwargs.get("limits"),
            elaborate=kwargs.get("elaborate", True),
        )
        if not second.ok or second.document is None:
            return second
        if not tptp_v1.documents_semantically_compatible(
            first.document, second.document
        ):
            diag = _diag(
                code=CODE_ROUND_TRIP,
                message="parse/print/parse does not preserve TPTP structure",
                range=SourceRange(0, 0),
                diagnostic_id="diag:tptp-v2:round-trip",
            )
            return TPTPFrontendV2Result(
                status=ParseStatus.FAILED,
                document=second.document,
                source_document=second.source_document,
                parse_artifact=second.parse_artifact,
                elaboration_artifact=second.elaboration_artifact,
                typed_expression=second.typed_expression,
                diagnostics=second.diagnostics + (diag,),
                printed=printed,
            )
        return TPTPFrontendV2Result(
            status=ParseStatus.OK,
            document=second.document,
            source_document=second.source_document,
            parse_artifact=second.parse_artifact,
            elaboration_artifact=second.elaboration_artifact,
            typed_expression=second.typed_expression,
            diagnostics=second.diagnostics,
            printed=printed,
        )


# ---------------------------------------------------------------------------
# TSTPFrontend@1
# ---------------------------------------------------------------------------


class TSTPFrontend:
    """Controlled TSTP/SZS proof and status record frontend.

    Interface: ``TSTPFrontend@1``.

    Authority is hard-wired to :attr:`ResultAuthority.CANDIDATE`.  Records are
    typed shared artifacts but never theorem-trusted.
    """

    interface: ClassVar[str] = TSTP_FRONTEND_INTERFACE
    authority: ClassVar[ResultAuthority] = ResultAuthority.CANDIDATE

    def __init__(
        self,
        *,
        limits: FrontendLimits | None = None,
        include_policy: IncludePolicyConfig | None = None,
    ) -> None:
        self.limits = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
        self.include_policy = (
            include_policy if include_policy is not None else IncludePolicyConfig()
        )
        self._candidate = tptp_v1.TSTPCandidateFrontend()

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:tstp:1",
        request_id: str = "req:tstp:1",
        limits: ParseLimits | None = None,
    ) -> TSTPFrontendResult:
        bounds = limits if limits is not None else self.limits.parse_limits
        if not isinstance(text, str) or not text.strip():
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty TSTP input",
                range=SourceRange(0, 0),
                diagnostic_id="diag:tstp:empty",
            )
            return TSTPFrontendResult(status=ParseStatus.FAILED, diagnostics=(diag,))

        try:
            source = SourceDocument.from_text(
                document_id, text, encoding="utf-8", language_hint="tstp"
            )
        except SyntaxContractError as error:
            diag = _diag(
                code=CODE_INPUT_LIMIT,
                message=str(error),
                range=SourceRange(0, 0),
                diagnostic_id="diag:tstp:source",
            )
            return TSTPFrontendResult(
                status=ParseStatus.REJECTED, diagnostics=(diag,)
            )

        candidate_result = self._candidate.parse_text(text, limits=bounds)
        diagnostics = _unique_diagnostics(
            candidate_result.diagnostics, prefix="diag:tstp"
        )
        raw_tokens, _ = tptp_v1.tokenize_tptp(text, limits=bounds)
        logic_tokens = _tptp_tokens_to_logic_tokens(
            raw_tokens, document_id=document_id
        )

        if not candidate_result.ok or candidate_result.candidate is None:
            artifact = ParseArtifactV2.from_document(
                source,
                artifact_id=f"art:tstp:parse:{request_id}",
                request_id=request_id,
                status=candidate_result.status,
                tokens=logic_tokens,
                diagnostics=diagnostics,
                metadata={
                    "interface": TSTP_FRONTEND_INTERFACE,
                    "authority": ResultAuthority.CANDIDATE.value,
                    "trusted": False,
                },
            )
            return TSTPFrontendResult(
                status=candidate_result.status,
                parse_artifact=artifact,
                diagnostics=diagnostics,
            )

        candidate = candidate_result.candidate
        cst = _build_covering_cst(
            source, logic_tokens, cst_id=f"cst:tstp:{request_id}"
        )
        source_map = build_token_source_map(
            source, logic_tokens, map_id=f"map:tstp:{request_id}"
        )
        surface = tuple(
            SurfaceASTRef(
                node_id=f"ast:step:{index + 1}",
                kind="tstp_step",
                range=step.range or source.full_range(),
                metadata={
                    "name": step.name,
                    "role": step.role,
                    "language": step.language,
                },
            )
            for index, step in enumerate(candidate.steps)
        )
        parse_artifact = ParseArtifactV2.from_document(
            source,
            artifact_id=f"art:tstp:parse:{request_id}",
            request_id=request_id,
            status=ParseStatus.OK,
            tokens=logic_tokens,
            cst=cst,
            surface_ast=surface,
            source_map=source_map,
            diagnostics=diagnostics,
            metadata={
                "interface": TSTP_FRONTEND_INTERFACE,
                "authority": ResultAuthority.CANDIDATE.value,
                "trusted": False,
                "szs_status": candidate.szs_status,
                "szs_output_form": candidate.szs_output_form,
                "step_names": list(candidate.step_names),
            },
        )
        parse_artifact.validate_against(source)

        try:
            record = TSTPProofRecord(
                steps=candidate.steps,
                szs_status=candidate.szs_status,
                szs_output_form=candidate.szs_output_form,
                authority=ResultAuthority.CANDIDATE,
                status=ResultStatus.CANDIDATE,
                trusted=False,
                parse_artifact=parse_artifact,
                source_text=text,
                metadata=FrozenMap(
                    {
                        "untrusted": True,
                        "authority_ceiling": ResultAuthority.CANDIDATE.value,
                        "interface": TSTP_FRONTEND_INTERFACE,
                    }
                ),
            )
        except TSTPFrontendError as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=error.range,
                diagnostic_id="diag:tstp:record",
                remediation=error.remediation,
            )
            return TSTPFrontendResult(
                status=ParseStatus.FAILED,
                parse_artifact=parse_artifact,
                diagnostics=diagnostics + (diag,),
            )

        return TSTPFrontendResult(
            status=ParseStatus.OK,
            record=record,
            parse_artifact=parse_artifact,
            diagnostics=diagnostics,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TSTPProofRecord:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.record is None:
            raise TSTPFrontendError(
                result.errors[0].message if result.errors else "TSTP parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_FORMULA,
            )
        return result.record


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_tptp_v2(
    text: str,
    *,
    document_id: str = "doc:tptp:v2:1",
    request_id: str = "req:tptp:v2:1",
    limits: ParseLimits | None = None,
    elaborate: bool = True,
) -> TPTPFrontendV2Result:
    """Parse controlled TPTP problem text into shared typed artifacts."""

    return TPTPFrontendV2().parse_text(
        text,
        document_id=document_id,
        request_id=request_id,
        limits=limits,
        elaborate=elaborate,
    )


def elaborate_tptp_v2(text: str, **kwargs: Any) -> TPTPFrontendV2Result:
    """Parse and elaborate TPTP text to shared artifacts."""

    return TPTPFrontendV2().elaborate(text, **kwargs)


def print_tptp_v2(document: tptp_v1.TPTPDocument) -> str:
    """Print an elaborated TPTP document deterministically."""

    return tptp_v1.TPTPPrinter().print_document(document)


def parse_print_parse_tptp_v2(text: str, **kwargs: Any) -> TPTPFrontendV2Result:
    """Parse → print → re-parse round trip under TPTPFrontend@2."""

    return TPTPFrontendV2().round_trip(text, **kwargs)


def parse_tstp_v2(
    text: str,
    *,
    document_id: str = "doc:tstp:1",
    request_id: str = "req:tstp:1",
    limits: ParseLimits | None = None,
) -> TSTPFrontendResult:
    """Parse TSTP output as a typed untrusted proof/status record."""

    return TSTPFrontend().parse_text(
        text,
        document_id=document_id,
        request_id=request_id,
        limits=limits,
    )


def parse_szs_status(text: str) -> str | None:
    """Extract one SZS status token from TSTP/prover output, if present."""

    return tptp_v1.parse_szs_status(text)


# Stable aliases used by tests and downstream importers.
TPTPLanguage = tptp_v1.TPTPLanguage
TPTPRole = tptp_v1.TPTPRole
TPTPFormulaKind = tptp_v1.TPTPFormulaKind
TPTPDocument = tptp_v1.TPTPDocument
TPTPAnnotatedFormula = tptp_v1.TPTPAnnotatedFormula
documents_semantically_compatible = tptp_v1.documents_semantically_compatible
validate_include_path = tptp_v1.validate_include_path


__all__ = [
    "CODE_CANDIDATE_AUTHORITY",
    "CODE_ELABORATION_FAILED",
    "CODE_EMPTY_INPUT",
    "CODE_FEATURE_LIMIT",
    "CODE_INCLUDE_POLICY",
    "CODE_INPUT_LIMIT",
    "CODE_MALFORMED_ANNOTATION",
    "CODE_PATH_TRAVERSAL",
    "CODE_PROFILE_UNSUPPORTED",
    "CODE_ROUND_TRIP",
    "CODE_TOKEN_LIMIT",
    "CODE_UNSAFE_INCLUDE",
    "CODE_UNSUPPORTED_LANGUAGE",
    "CODE_UNSUPPORTED_THF",
    "CODE_UNKNOWN_ROLE",
    "DEFAULT_FRONTEND_LIMITS",
    "DEFAULT_INCLUDE_POLICY",
    "DEFAULT_PARSE_LIMITS",
    "DEFAULT_PROFILE_SCOPE",
    "IncludePolicy",
    "IncludePolicyConfig",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_ROLES",
    "SUPPORTED_SZS_STATUSES",
    "THF_LANGUAGES",
    "TPTPAnnotatedFormula",
    "TPTPDocument",
    "TPTPFormulaKind",
    "TPTPFrontendV2",
    "TPTPFrontendV2Error",
    "TPTPFrontendV2Result",
    "TPTPLanguage",
    "TPTPProfileScope",
    "TPTPRole",
    "TPTP_FRONTEND_V2_INTERFACE",
    "TPTP_V2_DESCRIPTOR_ID",
    "TPTP_V2_FAMILY_ID",
    "TPTP_V2_GOAL_ID",
    "TPTP_V2_MODULE_VERSION",
    "TPTP_V2_NOTATION_ID",
    "TPTP_V2_NOTATION_VERSION",
    "TPTP_V2_PROFILE_ID",
    "TPTP_V2_TASK_ID",
    "TSTPFrontend",
    "TSTPFrontendError",
    "TSTPFrontendResult",
    "TSTPProofRecord",
    "TSTP_FRONTEND_INTERFACE",
    "TSTP_V2_DESCRIPTOR_ID",
    "UNSUPPORTED_LANGUAGES",
    "build_tptp_v2_descriptor",
    "documents_semantically_compatible",
    "elaborate_tptp_v2",
    "parse_print_parse_tptp_v2",
    "parse_szs_status",
    "parse_tptp_v2",
    "parse_tstp_v2",
    "print_tptp_v2",
    "register_tptp_v2_frontend",
    "validate_include_path",
    "validate_include_under_policy",
]
