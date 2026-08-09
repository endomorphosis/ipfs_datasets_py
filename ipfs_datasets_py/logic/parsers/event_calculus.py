"""Controlled event-calculus syntax (events, fluents, time points).

Interfaces:

* ``EventCalculusSyntax@1`` — parse/print/elaborate for controlled event-calculus
  surface text with explicit profile participation in semantic identity

Owned constructs:

* events and fluents (terms)
* time points (discrete integer or variable)
* ``happens``, ``holds_at`` / ``holds``, ``initiates``, ``terminates``,
  ``releases``, ``clipped``, ``initially``, ``released_at``
* classical connectives with **right-associative** implication
* capture-safe quantifiers over typed binders (sorts never disappear)

Grammar (connective precedence, low → high)::

    formula     ::= iff
    iff         ::= implies (('iff'|↔) implies)*
    implies     ::= or (('implies'|→|=>|->) formula)?   # right-assoc
    or          ::= and (('or'|∨) and)*
    and         ::= unary (('and'|∧) unary)*
    unary       ::= quant | ('not'|¬) unary | atomic
    quant       ::= ('forall'|'exists'|∀|∃) binder (',' binder)* '.' formula
    binder      ::= IDENT (':' SORT)?
    atomic      ::= true|false | ec_pred '(' terms ')' | IDENT | '(' formula ')'
    ec_pred     ::= happens|holds_at|holds|initiates|terminates|releases
                  | clipped|initially|released_at
    terms       ::= term (',' term)*
    term        ::= NUMBER | IDENT | IDENT '(' terms ')'

Unknown characters and undeclared sorts fail closed with exact spans.
Parse/print/parse is alpha-equivalent.  Substitutions are capture-safe via
``LogicExpressionAlgebra@1``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.algebra import (
    alpha_equivalent,
    free_variables,
    substitute,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_exists,
    mk_extension,
    mk_false,
    mk_forall,
    mk_predicate,
    mk_true,
    mk_variable,
    mk_constant,
    mk_application,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseArtifact,
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import DiagnosticSink
from ipfs_datasets_py.logic.syntax_core.lexer import BoundedLexer
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    LogicSort,
    SymbolDeclaration,
    SymbolKind,
    atomic_sort,
    declare_predicate,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

EVENT_CALCULUS_SYNTAX_INTERFACE: Final = "EventCalculusSyntax@1"
EVENT_CALCULUS_PROFILE_INTERFACE: Final = "EventCalculusProfile@1"
EVENT_CALCULUS_NOTATION_ID: Final = "canonical_event_calculus"
EVENT_CALCULUS_NOTATION_VERSION: Final = "1.0.0"
EVENT_CALCULUS_FAMILY_ID: Final = "event_calculus"
EVENT_CALCULUS_MODULE_VERSION: Final = "1.0.0"
EVENT_CALCULUS_PARSE_RESULT_SCHEMA_VERSION: Final = (
    "canonical-event-calculus-parse-result/v1"
)
EVENT_CALCULUS_PROFILE_SCHEMA_VERSION: Final = "event-calculus-profile/v1"
EVENT_CALCULUS_ATOM_PAYLOAD_SCHEMA: Final = "event_calculus.atom/v1"
EVENT_CALCULUS_SOURCE_MAP_SCHEMA: Final = "event_calculus.source-map/v1"

TIME_SORT: Final = atomic_sort("Time")
EVENT_SORT: Final = atomic_sort("Event")
FLUENT_SORT: Final = atomic_sort("Fluent")
OBJECT_SORT: Final = atomic_sort("Object")

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "event_calculus.unexpected_token"
CODE_TRAILING_INPUT: Final = "event_calculus.trailing_input"
CODE_EMPTY_INPUT: Final = "event_calculus.empty_input"
CODE_PARSE_DEPTH: Final = "event_calculus.parse_depth_exceeded"
CODE_UNBALANCED: Final = "event_calculus.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "event_calculus.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "event_calculus.unknown_character"
CODE_UNKNOWN_SORT: Final = "event_calculus.unknown_sort"
CODE_ARITY_MISMATCH: Final = "event_calculus.arity_mismatch"
CODE_PROFILE_MISMATCH: Final = "event_calculus.profile_mismatch"
CODE_ROUND_TRIP: Final = "event_calculus.round_trip_failed"
CODE_CAPTURE: Final = "event_calculus.capture_violation"
CODE_REBIND: Final = "event_calculus.variable_rebind"
CODE_IMPLIES_ASSOC: Final = "event_calculus.implication_associativity"

_ALL_EC_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_UNKNOWN_CHARACTER,
        CODE_UNKNOWN_SORT,
        CODE_ARITY_MISMATCH,
        CODE_PROFILE_MISMATCH,
        CODE_ROUND_TRIP,
        CODE_CAPTURE,
        CODE_REBIND,
        CODE_IMPLIES_ASSOC,
    }
)

# Connectives.
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_OPS: Final[frozenset[str]] = frozenset({"or", "∨", "||"})
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})
_FORALL_OPS: Final[frozenset[str]] = frozenset({"forall", "∀"})
_EXISTS_OPS: Final[frozenset[str]] = frozenset({"exists", "∃"})

# Event-calculus predicate surface forms → canonical kind + arity.
_EC_PREDICATES: Final[Mapping[str, tuple[str, int]]] = {
    "happens": ("happens", 2),
    "holds_at": ("holds_at", 2),
    "holdsat": ("holds_at", 2),
    "holds": ("holds_at", 2),
    "initiates": ("initiates", 3),
    "terminates": ("terminates", 3),
    "releases": ("releases", 3),
    "clipped": ("clipped", 3),
    "initially": ("initially", 1),
    "released_at": ("released_at", 2),
    "releasedat": ("released_at", 2),
}

_KNOWN_SORTS: Final[Mapping[str, LogicSort]] = {
    "time": TIME_SORT,
    "event": EVENT_SORT,
    "fluent": FLUENT_SORT,
    "object": OBJECT_SORT,
    "agent": atomic_sort("Agent"),
    "action": atomic_sort("Action"),
}

_EC_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "forall",
    "exists",
    "happens",
    "holds_at",
    "holds",
    "initiates",
    "terminates",
    "releases",
    "clipped",
    "initially",
    "released_at",
    "time",
    "event",
    "fluent",
    "object",
    "agent",
    "action",
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class EventCalculusDialect(str, Enum):
    """Declared event-calculus dialect / fragment."""

    BASIC = "basic"
    CLASSICAL = "classical"  # CEC-style with releases/clipped
    COGNITIVE = "cognitive"  # DCEC-ready (events + fluents + agents)


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    UNARY = 60
    ATOM = 70


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventCalculusProfile:
    """Explicit event-calculus syntax / semantics profile.

    Interface: ``EventCalculusProfile@1``.
    """

    profile_id: str
    dialect: EventCalculusDialect | str = EventCalculusDialect.CLASSICAL
    admit_releases: bool = True
    admit_clipped: bool = True
    admit_initially: bool = True
    known_sorts: tuple[str, ...] = (
        "time",
        "event",
        "fluent",
        "object",
        "agent",
        "action",
    )
    default_sort: str = "object"
    implication_associativity: str = "right"
    schema_version: str = EVENT_CALCULUS_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = EVENT_CALCULUS_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError("EventCalculusProfile.profile_id is required")
        dialect = self.dialect
        if not isinstance(dialect, EventCalculusDialect):
            try:
                dialect = EventCalculusDialect(str(dialect))
            except ValueError as error:
                raise SyntaxContractError(
                    f"unknown event-calculus dialect {self.dialect!r}"
                ) from error
            object.__setattr__(self, "dialect", dialect)
        if self.implication_associativity != "right":
            raise SyntaxContractError(
                "EventCalculusProfile.implication_associativity must be 'right' "
                f"(got {self.implication_associativity!r}); left-assoc is rejected"
            )
        default = str(self.default_sort).casefold()
        sorts = tuple(str(s).casefold() for s in self.known_sorts)
        if default not in sorts and default not in _KNOWN_SORTS:
            raise SyntaxContractError(
                f"default_sort {self.default_sort!r} is not among known_sorts"
            )
        object.__setattr__(self, "default_sort", default)
        object.__setattr__(self, "known_sorts", sorts)
        if self.schema_version != EVENT_CALCULUS_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported EventCalculusProfile schema_version "
                f"{self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        return EVENT_CALCULUS_FAMILY_ID

    @property
    def semantic_identity(self) -> dict[str, Any]:
        dialect = (
            self.dialect.value
            if isinstance(self.dialect, EventCalculusDialect)
            else str(self.dialect)
        )
        return {
            "admit_clipped": self.admit_clipped,
            "admit_initially": self.admit_initially,
            "admit_releases": self.admit_releases,
            "default_sort": self.default_sort,
            "dialect": dialect,
            "implication_associativity": self.implication_associativity,
            "known_sorts": list(self.known_sorts),
            "profile_id": self.profile_id,
        }

    def resolve_sort(self, name: str) -> LogicSort | None:
        key = name.casefold()
        if key not in self.known_sorts and key not in _KNOWN_SORTS:
            return None
        if key in _KNOWN_SORTS:
            return _KNOWN_SORTS[key]
        return atomic_sort(name[0].upper() + name[1:] if name else name)

    def to_dict(self) -> dict[str, Any]:
        dialect = (
            self.dialect.value
            if isinstance(self.dialect, EventCalculusDialect)
            else str(self.dialect)
        )
        return {
            "admit_clipped": self.admit_clipped,
            "admit_initially": self.admit_initially,
            "admit_releases": self.admit_releases,
            "default_sort": self.default_sort,
            "dialect": dialect,
            "implication_associativity": self.implication_associativity,
            "interface": self.interface,
            "known_sorts": list(self.known_sorts),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EventCalculusProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("EventCalculusProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            dialect=value.get("dialect", EventCalculusDialect.CLASSICAL.value),
            admit_releases=bool(value.get("admit_releases", True)),
            admit_clipped=bool(value.get("admit_clipped", True)),
            admit_initially=bool(value.get("admit_initially", True)),
            known_sorts=tuple(value.get("known_sorts") or (
                "time",
                "event",
                "fluent",
                "object",
                "agent",
                "action",
            )),
            default_sort=str(value.get("default_sort") or "object"),
            implication_associativity=str(
                value.get("implication_associativity") or "right"
            ),
            schema_version=str(
                value.get("schema_version") or EVENT_CALCULUS_PROFILE_SCHEMA_VERSION
            ),
        )


def profile_event_calculus_basic(
    *,
    profile_id: str = "event_calculus_basic",
) -> EventCalculusProfile:
    return EventCalculusProfile(
        profile_id=profile_id,
        dialect=EventCalculusDialect.BASIC,
        admit_releases=False,
        admit_clipped=False,
        admit_initially=True,
    )


def profile_event_calculus_classical(
    *,
    profile_id: str = "event_calculus_classical",
) -> EventCalculusProfile:
    return EventCalculusProfile(
        profile_id=profile_id,
        dialect=EventCalculusDialect.CLASSICAL,
        admit_releases=True,
        admit_clipped=True,
        admit_initially=True,
    )


def profile_event_calculus_cognitive(
    *,
    profile_id: str = "event_calculus_cognitive",
) -> EventCalculusProfile:
    return EventCalculusProfile(
        profile_id=profile_id,
        dialect=EventCalculusDialect.COGNITIVE,
        admit_releases=True,
        admit_clipped=True,
        admit_initially=True,
    )


def event_calculus_semantic_identity(
    node: LogicNode,
    profile: EventCalculusProfile,
) -> dict[str, Any]:
    """Stable semantic identity fragment for an EC formula under *profile*."""

    return {
        "family": EVENT_CALCULUS_FAMILY_ID,
        "node_kind": (
            node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
        ),
        "profile": profile.semantic_identity,
    }


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventCalculusParseResult:
    """Typed result of a canonical event-calculus parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: EventCalculusProfile | None = None
    implication_associativity: str = "right"
    schema_version: str = EVENT_CALCULUS_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = EVENT_CALCULUS_SYNTAX_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)


class EventCalculusParseError(SyntaxContractError):
    """Raised by raising helpers when an event-calculus parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: EventCalculusParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Diagnostics / cursor
# ---------------------------------------------------------------------------


class _ParseFail(Exception):
    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:ec:{code.replace('.', '-')}",
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        range=range or SourceRange(0, 0),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


class _Cursor:
    def __init__(
        self,
        tokens: Sequence[LogicToken],
        document: SourceDocument,
    ) -> None:
        self.tokens = tuple(tokens)
        self.document = document
        self.index = 0
        self.depth = 0

    def current(self) -> LogicToken:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> LogicToken:
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def is_eof(self) -> bool:
        return self.current().kind == TokenKind.EOF.value

    def advance(self) -> LogicToken:
        token = self.current()
        if not self.is_eof():
            self.index += 1
        return token

    def match_any(self, lexemes: frozenset[str]) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = {item.casefold() for item in lexemes}
        if token.lexeme in lexemes or token.lexeme.casefold() in folded:
            return self.advance()
        return None

    def match_lexeme(self, *lexemes: str) -> LogicToken | None:
        return self.match_any(frozenset(lexemes))

    def expect_lexeme(self, *lexemes: str, code: str = CODE_UNEXPECTED_TOKEN) -> LogicToken:
        token = self.match_lexeme(*lexemes)
        if token is not None:
            return token
        current = self.current()
        expected = " or ".join(repr(item) for item in lexemes)
        raise _ParseFail(
            _diag(
                code=code,
                message=f"expected {expected}; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def expect_ident(self) -> LogicToken:
        token = self.current()
        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            return self.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected identifier; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def range_span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        if (
            start.start_char is not None
            and start.end_char is not None
            and end.start_char is not None
            and end.end_char is not None
        ):
            return SourceRange(
                start=start.start,
                end=end.end,
                start_char=start.start_char,
                end_char=end.end_char,
            )
        return SourceRange(start=start.start, end=end.end)


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _ECParserEngine:
    """Recursive-descent event-calculus parser with capture-safe binders."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: EventCalculusProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, document)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0
        self._scope: list[str] = []
        self._binder_sorts: dict[str, LogicSort] = {}

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"{self.expression_id}:{prefix}:{self._counter}"

    def _enter(self) -> None:
        self.cursor.depth += 1
        if self.cursor.depth > self.limits.max_depth:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"parse depth {self.cursor.depth} exceeds limit "
                        f"{self.limits.max_depth}"
                    ),
                    range=self.cursor.current().range,
                )
            )

    def _leave(self) -> None:
        self.cursor.depth = max(0, self.cursor.depth - 1)

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if not self.document.text.strip():
            return None, (
                _diag(
                    code=CODE_EMPTY_INPUT,
                    message="empty event-calculus input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_formula()
            if not self.cursor.is_eof():
                tok = self.cursor.current()
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=f"trailing input starting at {tok.lexeme!r}",
                        range=tok.range,
                        remediation="Remove trailing tokens or close open constructs",
                    )
                )
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_iff()
        finally:
            self._leave()

    def _parse_iff(self) -> LogicNode:
        left = self._parse_implies()
        while self.cursor.match_any(_IFF_OPS) is not None:
            right = self._parse_implies()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = LogicNode(
                node_id=self._nid("iff"),
                kind=NodeKind.IFF,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )
        return left

    def _parse_implies(self) -> LogicNode:
        # Right-associative: A -> B -> C ≡ A -> (B -> C).  Explicit in AST.
        left = self._parse_or()
        op = self.cursor.match_any(_IMPLIES_OPS)
        if op is None:
            return left
        right = self._parse_formula()  # recurse for right-assoc
        span = self.cursor.range_span(
            left.range or op.range,
            right.range or op.range,
        )
        return LogicNode(
            node_id=self._nid("imp"),
            kind=NodeKind.IMPLIES,
            sort=BOOL_SORT,
            arguments=(left, right),
            range=span,
            metadata={
                "associativity": "right",
                "schema_version": "event_calculus.implies/v1",
            },
        )

    def _parse_or(self) -> LogicNode:
        nodes = [self._parse_and()]
        while self.cursor.match_any(_OR_OPS) is not None:
            nodes.append(self._parse_and())
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        return LogicNode(
            node_id=self._nid("or"),
            kind=NodeKind.OR,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )

    def _parse_and(self) -> LogicNode:
        nodes = [self._parse_unary()]
        while self.cursor.match_any(_AND_OPS) is not None:
            nodes.append(self._parse_unary())
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        return LogicNode(
            node_id=self._nid("and"),
            kind=NodeKind.AND,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )

    def _parse_unary(self) -> LogicNode:
        if self.cursor.match_any(_NOT_OPS) is not None:
            body = self._parse_unary()
            return LogicNode(
                node_id=self._nid("not"),
                kind=NodeKind.NOT,
                sort=BOOL_SORT,
                arguments=(body,),
                range=body.range,
            )
        token = self.cursor.current()
        if (
            token.lexeme in _FORALL_OPS
            or token.lexeme.casefold() == "forall"
            or token.lexeme in _EXISTS_OPS
            or token.lexeme.casefold() == "exists"
        ):
            return self._parse_quantifier()
        return self._parse_atomic()

    def _parse_quantifier(self) -> LogicNode:
        token = self.cursor.advance()
        quant = (
            "forall"
            if token.lexeme in _FORALL_OPS or token.lexeme.casefold() == "forall"
            else "exists"
        )
        binders: list[Binder] = []
        binder_names: list[str] = []
        while True:
            name_tok = self._expect_binder_name()
            name = name_tok.lexeme
            if name in self._scope or name in binder_names:
                raise _ParseFail(
                    _diag(
                        code=CODE_REBIND,
                        message=(
                            f"variable {name!r} is already bound "
                            "(rebinding is capture-unsafe)"
                        ),
                        range=name_tok.range,
                        remediation="Choose a fresh variable name",
                        metadata={"variable": name, "scope": list(self._scope)},
                    )
                )
            sort = self._default_sort()
            if self.cursor.match_lexeme(":") is not None:
                sort_tok = self._expect_binder_name()
                resolved = self.profile.resolve_sort(sort_tok.lexeme)
                if resolved is None:
                    raise _ParseFail(
                        _diag(
                            code=CODE_UNKNOWN_SORT,
                            message=(
                                f"unknown sort {sort_tok.lexeme!r}; "
                                "undeclared sorts no longer disappear"
                            ),
                            range=sort_tok.range,
                            remediation=(
                                f"Declare sort in profile known_sorts "
                                f"{list(self.profile.known_sorts)!r}"
                            ),
                            metadata={
                                "sort": sort_tok.lexeme,
                                "known_sorts": list(self.profile.known_sorts),
                            },
                        )
                    )
                sort = resolved
            binders.append(Binder(name=name, sort=sort))
            binder_names.append(name)
            if self.cursor.match_lexeme(",") is None:
                break
        self.cursor.expect_lexeme(".", code=CODE_UNEXPECTED_TOKEN)
        for name, binder in zip(binder_names, binders):
            self._scope.append(name)
            self._binder_sorts[name] = binder.sort
        try:
            body = self._parse_formula()
        finally:
            for name in binder_names:
                self._scope.pop()
                self._binder_sorts.pop(name, None)
        span = self.cursor.range_span(token.range, body.range or token.range)
        node_id = self._nid(quant)
        if quant == "forall":
            built = mk_forall(node_id, binders, body)
        else:
            built = mk_exists(node_id, binders, body)
        return LogicNode(
            node_id=built.node_id,
            kind=built.kind,
            sort=BOOL_SORT,
            binders=built.binders,
            arguments=built.arguments,
            range=span,
            metadata={
                "capture_safe": True,
                "quantifier": quant,
            },
        )

    def _expect_binder_name(self) -> LogicToken:
        token = self.cursor.current()
        if token.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            return self.cursor.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected binder name; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def _default_sort(self) -> LogicSort:
        resolved = self.profile.resolve_sort(self.profile.default_sort)
        return resolved if resolved is not None else OBJECT_SORT

    def _parse_atomic(self) -> LogicNode:
        token = self.cursor.current()
        if token.lexeme in _TRUE_OPS or token.lexeme.casefold() == "true":
            self.cursor.advance()
            node = mk_true(self._nid("true"))
            return LogicNode(
                node_id=node.node_id,
                kind=node.kind,
                sort=BOOL_SORT,
                range=token.range,
            )
        if token.lexeme in _FALSE_OPS or token.lexeme.casefold() == "false":
            self.cursor.advance()
            node = mk_false(self._nid("false"))
            return LogicNode(
                node_id=node.node_id,
                kind=node.kind,
                sort=BOOL_SORT,
                range=token.range,
            )
        if token.lexeme == "(":
            self.cursor.advance()
            inner = self._parse_formula()
            self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            return inner

        # Predicate / EC atom / proposition.
        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            name = token.lexeme
            name_fold = name.casefold()
            self.cursor.advance()
            if self.cursor.current().lexeme == "(":
                self.cursor.advance()
                args = self._parse_term_list()
                end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                span = self.cursor.range_span(token.range, end.range)
                if name_fold in _EC_PREDICATES:
                    return self._build_ec_atom(name_fold, args, span)
                # Generic predicate application.
                return mk_predicate(
                    self._nid("pred"),
                    name,
                    args,
                    range=span,
                )
            # Bare proposition (nullary predicate).
            return mk_predicate(self._nid("prop"), name, (), range=token.range)

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"unexpected token {token.lexeme!r} in atomic position",
                range=token.range,
            )
        )

    def _parse_term_list(self) -> list[LogicNode]:
        if self.cursor.current().lexeme == ")":
            return []
        terms = [self._parse_term()]
        while self.cursor.match_lexeme(",") is not None:
            terms.append(self._parse_term())
        return terms

    def _parse_term(self) -> LogicNode:
        token = self.cursor.current()
        if token.kind == TokenKind.NUMBER.value:
            self.cursor.advance()
            # Symbol names cannot start with a digit; encode as n_<digits>.
            return LogicNode(
                node_id=self._nid("time"),
                kind=NodeKind.CONSTANT,
                symbol=f"n_{token.lexeme}",
                sort=TIME_SORT,
                range=token.range,
                metadata={
                    "literal": token.lexeme,
                    "literal_kind": "integer",
                    "schema_version": "event_calculus.time_literal/v1",
                },
            )
        if token.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            name = token.lexeme
            self.cursor.advance()
            if self.cursor.current().lexeme == "(":
                self.cursor.advance()
                args = self._parse_term_list()
                end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                span = self.cursor.range_span(token.range, end.range)
                return mk_application(
                    self._nid("app"),
                    name,
                    args,
                    sort=self._default_sort(),
                    range=span,
                )
            # Bound variable vs free constant.
            if name in self._scope:
                sort = self._binder_sorts.get(name, self._default_sort())
                return mk_variable(
                    self._nid("var"),
                    name,
                    sort,
                    range=token.range,
                )
            return mk_constant(
                self._nid("const"),
                name,
                self._default_sort(),
                range=token.range,
            )
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected term; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def _build_ec_atom(
        self,
        name_fold: str,
        args: Sequence[LogicNode],
        span: SourceRange,
    ) -> LogicNode:
        kind, arity = _EC_PREDICATES[name_fold]
        if kind == "releases" and not self.profile.admit_releases:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=(
                        f"releases is not admitted by profile "
                        f"{self.profile.profile_id!r}"
                    ),
                    range=span,
                    remediation="Use profile_event_calculus_classical() or cognitive",
                )
            )
        if kind == "clipped" and not self.profile.admit_clipped:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=(
                        f"clipped is not admitted by profile "
                        f"{self.profile.profile_id!r}"
                    ),
                    range=span,
                )
            )
        if kind == "initially" and not self.profile.admit_initially:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=(
                        f"initially is not admitted by profile "
                        f"{self.profile.profile_id!r}"
                    ),
                    range=span,
                )
            )
        if len(args) != arity:
            raise _ParseFail(
                _diag(
                    code=CODE_ARITY_MISMATCH,
                    message=(
                        f"{kind} expects {arity} argument(s); got {len(args)}"
                    ),
                    range=span,
                    metadata={"kind": kind, "expected": arity, "got": len(args)},
                )
            )
        payload = {
            "arity": arity,
            "kind": kind,
            "profile_id": self.profile.profile_id,
            "schema_version": EVENT_CALCULUS_ATOM_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid(kind),
            family=EVENT_CALCULUS_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(f"event_calculus.{kind}",),
            payload_schema=EVENT_CALCULUS_ATOM_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(args),
            range=span,
        )


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class EventCalculusPrinter:
    """Deterministic printer; implication parenthesization is right-assoc explicit."""

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        if style not in {PrintStyle.ASCII, PrintStyle.UNICODE}:
            raise SyntaxContractError(
                f"print style must be 'ascii' or 'unicode'; got {style!r}"
            )
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        if isinstance(node, TypedExpression):
            return self._print_node(node.root, _Prec.BOTTOM)
        if not isinstance(node, LogicNode):
            raise SyntaxContractError("print requires a LogicNode or TypedExpression")
        return self._print_node(node, _Prec.BOTTOM)

    def _op(self, ascii_form: str, unicode_form: str) -> str:
        return unicode_form if self.style == PrintStyle.UNICODE else ascii_form

    def _print_node(self, node: LogicNode, parent_prec: int) -> str:
        kind = node.kind
        if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
            return self._op("true", "⊤")
        if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
            return self._op("false", "⊥")
        if kind is NodeKind.NOT or kind == NodeKind.NOT.value:
            inner = self._print_node(node.arguments[0], _Prec.UNARY)
            text = f"{self._op('not', '¬')} {inner}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            op = f" {self._op('and', '∧')} "
            text = op.join(self._print_node(a, _Prec.AND) for a in node.arguments)
            return self._paren(text, _Prec.AND, parent_prec)
        if kind is NodeKind.OR or kind == NodeKind.OR.value:
            op = f" {self._op('or', '∨')} "
            text = op.join(self._print_node(a, _Prec.OR) for a in node.arguments)
            return self._paren(text, _Prec.OR, parent_prec)
        if kind is NodeKind.IMPLIES or kind == NodeKind.IMPLIES.value:
            # Right-assoc: parenthesize left at IMPLIES+1, right at IMPLIES.
            left = self._print_node(node.arguments[0], _Prec.IMPLIES + 1)
            right = self._print_node(node.arguments[1], _Prec.IMPLIES)
            text = f"{left} {self._op('->', '→')} {right}"
            return self._paren(text, _Prec.IMPLIES, parent_prec)
        if kind is NodeKind.IFF or kind == NodeKind.IFF.value:
            left = self._print_node(node.arguments[0], _Prec.IFF + 1)
            right = self._print_node(node.arguments[1], _Prec.IFF + 1)
            text = f"{left} {self._op('iff', '↔')} {right}"
            return self._paren(text, _Prec.IFF, parent_prec)
        if kind is NodeKind.FORALL or kind == NodeKind.FORALL.value:
            return self._print_quant("forall", "∀", node, parent_prec)
        if kind is NodeKind.EXISTS or kind == NodeKind.EXISTS.value:
            return self._print_quant("exists", "∃", node, parent_prec)
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            if not node.arguments:
                return node.symbol or ""
            args = ", ".join(self._print_term(a) for a in node.arguments)
            return f"{node.symbol}({args})"
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node)
        if kind in {
            NodeKind.CONSTANT,
            NodeKind.VARIABLE,
            NodeKind.APPLICATION,
            NodeKind.CONSTANT.value,
            NodeKind.VARIABLE.value,
            NodeKind.APPLICATION.value,
        }:
            return self._print_term(node)
        raise SyntaxContractError(f"unsupported node kind for printing: {kind!r}")

    def _print_quant(
        self,
        ascii_op: str,
        unicode_op: str,
        node: LogicNode,
        parent_prec: int,
    ) -> str:
        # Always emit sort annotations so parse/print/parse preserves sorts.
        binders = ", ".join(f"{b.name}:{b.sort.name}" for b in node.binders)
        body = self._print_node(node.arguments[0], _Prec.BOTTOM)
        text = f"{self._op(ascii_op, unicode_op)} {binders}. {body}"
        return self._paren(text, _Prec.UNARY, parent_prec)

    def _print_extension(self, node: LogicNode) -> str:
        assert node.extension is not None
        payload = dict(node.extension.payload)
        kind = str(payload.get("kind") or "")
        args = ", ".join(self._print_term(c) for c in node.extension.children)
        return f"{kind}({args})"

    def _print_term(self, node: LogicNode) -> str:
        kind = node.kind
        if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
            # Round-trip integer time literals encoded as n_<digits>.
            lit = node.metadata.get("literal") if node.metadata else None
            if lit is not None:
                return str(lit)
            symbol = node.symbol or ""
            if symbol.startswith("n_") and symbol[2:].isdigit():
                return symbol[2:]
            return symbol
        if kind is NodeKind.VARIABLE or kind == NodeKind.VARIABLE.value:
            return node.symbol or ""
        if kind is NodeKind.APPLICATION or kind == NodeKind.APPLICATION.value:
            args = ", ".join(self._print_term(a) for a in node.arguments)
            return f"{node.symbol}({args})"
        # Nested formulas printed as terms only in error paths.
        return self._print_node(node, _Prec.ATOM)

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text


# ---------------------------------------------------------------------------
# Public parser surface
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:ec:1",
) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind,
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


def _surface_from_node(node: LogicNode) -> list[SurfaceASTRef]:
    refs: list[SurfaceASTRef] = []
    seq = [0]

    def walk(n: LogicNode) -> str:
        seq[0] += 1
        node_id = n.node_id if n.node_id else f"ast:{seq[0]}"
        child_ids: list[str] = []
        for child in n.arguments:
            child_ids.append(walk(child))
        if n.extension is not None:
            for child in n.extension.children:
                child_ids.append(walk(child))
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        safe_kind = kind.replace(" ", "_")
        span = n.range or SourceRange(0, 0)
        meta: dict[str, Any] = {}
        if n.symbol:
            meta["symbol"] = n.symbol
        if n.binders:
            meta["binders"] = [b.name for b in n.binders]
        if n.extension is not None:
            meta["payload_schema"] = n.extension.payload_schema
            meta["features"] = list(n.extension.features)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=safe_kind,
                range=span,
                child_ids=tuple(child_ids),
                metadata=meta,
            )
        )
        return node_id

    walk(node)
    return refs


def _collect_predicates(node: LogicNode) -> tuple[str, ...]:
    found: list[str] = []

    def walk(n: LogicNode) -> None:
        kind = n.kind
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            if n.symbol:
                found.append(n.symbol)
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            if n.extension is not None:
                kind_name = str(n.extension.payload.get("kind") or "")
                if kind_name:
                    found.append(kind_name)
                for child in n.extension.children:
                    walk(child)
        for child in n.arguments:
            walk(child)

    walk(node)
    return tuple(sorted(set(found)))


def _signature_for_formula(
    root: LogicNode,
    profile: EventCalculusProfile,
) -> LogicSignature:
    preds = _collect_predicates(root)
    symbols = tuple(declare_predicate(name) for name in preds) if preds else ()
    sorts = tuple(
        s
        for s in (
            TIME_SORT,
            EVENT_SORT,
            FLUENT_SORT,
            OBJECT_SORT,
        )
    )
    return LogicSignature(
        signature_id=f"sig:event_calculus:{profile.profile_id}",
        family=EVENT_CALCULUS_FAMILY_ID,
        profile=profile.profile_id,
        sorts=sorts,
        symbols=symbols,
        features=("event_calculus", "classical"),
    )


def _extract_profile(value: object) -> EventCalculusProfile | None:
    if value is None:
        return None
    if isinstance(value, EventCalculusProfile):
        return value
    if isinstance(value, Mapping):
        return EventCalculusProfile.from_dict(value)
    return None


class EventCalculusParser:
    """Notation parser for controlled event-calculus syntax.

    Interface: ``EventCalculusSyntax@1``.
    """

    interface: ClassVar[str] = EVENT_CALCULUS_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = EVENT_CALCULUS_NOTATION_ID
    notation_version: ClassVar[str] = EVENT_CALCULUS_NOTATION_VERSION

    def __init__(
        self,
        profile: EventCalculusProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(profile, EventCalculusProfile):
            raise SyntaxContractError("profile must be an EventCalculusProfile")
        self.profile = profile
        self.printer = EventCalculusPrinter(style=print_style)
        self._lexer = BoundedLexer(keywords=_EC_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("event_calculus_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:ec:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: EventCalculusProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:ec:1",
        expression_id: str = "expr:ec:1",
    ) -> EventCalculusParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message="event-calculus parse requires an EventCalculusProfile",
                range=document.full_range(),
                remediation="Pass profile=profile_event_calculus_classical()",
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": EVENT_CALCULUS_SYNTAX_INTERFACE},
            )
            return EventCalculusParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        # Promote unknown-character / lexer errors so they never disappear.
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:ec:lex:{index + 1}",
                    code=(
                        CODE_UNKNOWN_CHARACTER
                        if "unknown" in item.code
                        else (
                            CODE_LEXER_ERROR
                            if item.code.startswith("lexer.")
                            else item.code
                        )
                    ),
                    message=item.message,
                    severity=item.severity,
                    range=item.range,
                    remediation=item.remediation
                    or "Unknown characters no longer disappear; fix or remove them",
                    metadata={"lexer_code": item.code},
                )
                for index, item in enumerate(lex_result.diagnostics)
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=promoted,
                metadata={"interface": EVENT_CALCULUS_SYNTAX_INTERFACE},
            )
            return EventCalculusParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _ECParserEngine(
            document=document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
        )
        root, diagnostics = engine.parse()
        all_diags = tuple(lex_result.diagnostics) + tuple(diagnostics)

        if root is None or any(item.is_error for item in all_diags):
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": EVENT_CALCULUS_SYNTAX_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return EventCalculusParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        printed = self.printer.print(root)
        signature = _signature_for_formula(root, prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=EVENT_CALCULUS_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            cst=cst,
            surface_ast=surface,
            diagnostics=all_diags,
            metadata={
                "interface": EVENT_CALCULUS_SYNTAX_INTERFACE,
                "profile": prof.to_dict(),
                "implication_associativity": "right",
                "printed": printed,
            },
        )
        return EventCalculusParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            implication_associativity="right",
        )


class EventCalculusSyntax:
    """Facade for ``EventCalculusSyntax@1``."""

    interface: ClassVar[str] = EVENT_CALCULUS_SYNTAX_INTERFACE

    def __init__(
        self,
        profile: EventCalculusProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_event_calculus_classical()
        self.parser = EventCalculusParser(self.profile, print_style=print_style)
        self.printer = EventCalculusPrinter(style=print_style)

    def parse_text(self, text: str, **kwargs: Any) -> EventCalculusParseResult:
        document_id = str(kwargs.pop("document_id", "doc:ec:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:ec:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:ec:1"))
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            request_id=request_id,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise EventCalculusParseError(
                "event-calculus parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def substitute_capture_safe(
        self,
        node: LogicNode,
        var: str,
        replacement: LogicNode,
    ) -> LogicNode:
        """Capture-avoiding substitution via ``LogicExpressionAlgebra@1``."""

        return substitute(node, var, replacement)


def parse_event_calculus(
    text: str,
    profile: EventCalculusProfile | None = None,
    **kwargs: Any,
) -> EventCalculusParseResult:
    """Parse event-calculus *text* under *profile*."""

    syntax = EventCalculusSyntax(profile or profile_event_calculus_classical())
    return syntax.parse_text(text, **kwargs)


def print_event_calculus(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return EventCalculusPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: EventCalculusProfile | None = None,
) -> tuple[EventCalculusParseResult, EventCalculusParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_event_calculus_classical()
    first = parse_event_calculus(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_event_calculus(first.root)
    second = parse_event_calculus(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


def capture_safe_substitute(
    node: LogicNode,
    var: str,
    replacement: LogicNode,
) -> LogicNode:
    """Public capture-avoiding substitution for event-calculus ASTs."""

    return substitute(node, var, replacement)


__all__ = [
    "EVENT_CALCULUS_SYNTAX_INTERFACE",
    "EVENT_CALCULUS_PROFILE_INTERFACE",
    "EVENT_CALCULUS_NOTATION_ID",
    "EVENT_CALCULUS_NOTATION_VERSION",
    "EVENT_CALCULUS_FAMILY_ID",
    "EVENT_CALCULUS_MODULE_VERSION",
    "TIME_SORT",
    "EVENT_SORT",
    "FLUENT_SORT",
    "OBJECT_SORT",
    "CODE_UNEXPECTED_TOKEN",
    "CODE_TRAILING_INPUT",
    "CODE_EMPTY_INPUT",
    "CODE_UNKNOWN_CHARACTER",
    "CODE_UNKNOWN_SORT",
    "CODE_ARITY_MISMATCH",
    "CODE_PROFILE_MISMATCH",
    "CODE_CAPTURE",
    "CODE_REBIND",
    "CODE_IMPLIES_ASSOC",
    "PrintStyle",
    "EventCalculusDialect",
    "EventCalculusProfile",
    "EventCalculusParseError",
    "EventCalculusParseResult",
    "EventCalculusPrinter",
    "EventCalculusParser",
    "EventCalculusSyntax",
    "profile_event_calculus_basic",
    "profile_event_calculus_classical",
    "profile_event_calculus_cognitive",
    "event_calculus_semantic_identity",
    "parse_event_calculus",
    "print_event_calculus",
    "parse_print_parse",
    "capture_safe_substitute",
    "free_variables",
]
