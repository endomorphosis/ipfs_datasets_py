"""Datalog, Horn/CHC, and SecPAL rule frontends (LFP-020).

Interfaces:

* ``RuleFrontend@1`` — parse/print/elaborate for shared Datalog, Horn, and
  constrained Horn clause (CHC) surface forms with explicit closed-world and
  priority semantics, range restriction, and stratified negation
* ``SecPALFrontend@1`` — authorization-profile specialization covering
  says/can-say, speaks-for, delegation, principals, resources, actions, and
  constraints over the same typed rule AST

Controlled subset:

* facts ``pred(c1, c2).`` and ground SecPAL assertions
  ``"issuer" says pred(c1, c2).``
* Horn rules ``head :- body1, body2.`` with optional ``allow`` / ``deny``
  effects and body-only ``not`` / ``!`` negation
* queries ``?- goal.`` and authorization queries
  ``query "principal" can "action" on "resource".``
* speaks-for ``"alice" speaks-for "bob".`` / ``speaks_for(alice, bob).``
* delegation ``"root" says "alice" can "read" on "docs" with
  delegation-depth 1.``
* directives ``@world``, ``@priority``, ``@profile``, ``@trust``, ``@stratum``
* CHC surface ``chc head :- body.`` and deterministic CHC lowering

Fail-closed / explicit unsupported disposition:

* unsafe (non-range-restricted) head variables
* unstratified negation
* ambiguous principal / resource / action terms under authorization profiles
* missing world or priority semantics when negation or allow/deny is used
* open recursion without finite bounds declaration (unsupported, not silent)

Backend authorization evaluators remain in existing adapters; this module is
syntax + static semantic checks only and never executes engines.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.syntax_core.contracts import (
    DiagnosticSeverity,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

RULE_FRONTEND_INTERFACE: Final = "RuleFrontend@1"
SECPAL_FRONTEND_INTERFACE: Final = "SecPALFrontend@1"
RULE_NOTATION_ID: Final = "datalog_rules"
RULE_NOTATION_VERSION: Final = "1.0.0"
RULE_PROFILE_ID: Final = "horn"
RULE_FAMILY_ID: Final = "datalog"
SECPAL_PROFILE_ID: Final = "secpal"
SECPAL_FAMILY_ID: Final = "authorization"
RULE_MODULE_VERSION: Final = "1.0.0"
RULE_PARSE_RESULT_SCHEMA_VERSION: Final = "rules-parse-result/v1"
RULE_DOCUMENT_SCHEMA_VERSION: Final = "rules-document/v1"
CHC_LOWERING_SCHEMA_VERSION: Final = "rules-chc-lowering/v1"
SECPAL_SOURCE_SCHEMA_VERSION: Final = "secpal-controlled-source/v1"

# Stable namespaced diagnostic codes.
CODE_EMPTY_INPUT: Final = "rules.empty_input"
CODE_INPUT_LIMIT: Final = "rules.input_limit"
CODE_TOKEN_LIMIT: Final = "rules.token_limit"
CODE_PARSE_DEPTH: Final = "rules.parse_depth_exceeded"
CODE_UNBALANCED: Final = "rules.unbalanced_delimiter"
CODE_UNEXPECTED_TOKEN: Final = "rules.unexpected_token"
CODE_MALFORMED_STATEMENT: Final = "rules.malformed_statement"
CODE_MALFORMED_ATOM: Final = "rules.malformed_atom"
CODE_MALFORMED_TERM: Final = "rules.malformed_term"
CODE_MALFORMED_RULE: Final = "rules.malformed_rule"
CODE_MALFORMED_QUERY: Final = "rules.malformed_query"
CODE_MALFORMED_DIRECTIVE: Final = "rules.malformed_directive"
CODE_TRAILING_INPUT: Final = "rules.trailing_input"
CODE_UNTERMINATED_STRING: Final = "rules.unterminated_string"
CODE_UNTERMINATED_COMMENT: Final = "rules.unterminated_comment"
CODE_UNSUPPORTED_CONSTRUCT: Final = "rules.unsupported_construct"
CODE_UNSAFE_VARIABLE: Final = "rules.unsafe_variable"
CODE_UNSTRATIFIED_NEGATION: Final = "rules.unstratified_negation"
CODE_AMBIGUOUS_TERM: Final = "rules.ambiguous_principal_resource_action"
CODE_MISSING_WORLD: Final = "rules.missing_world_semantics"
CODE_MISSING_PRIORITY: Final = "rules.missing_priority_semantics"
CODE_INVALID_LITERAL: Final = "rules.invalid_literal"
CODE_ROUND_TRIP: Final = "rules.round_trip_failed"
CODE_CHC_LOWERING: Final = "rules.chc_lowering"
CODE_PROFILE: Final = "rules.invalid_profile"

_ALL_RULE_CODES: Final[frozenset[str]] = frozenset(
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
    }
)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class RuleTermKind(StrEnum):
    """Term node kinds in the controlled rule subset."""

    CONSTANT = "constant"
    VARIABLE = "variable"
    STRING = "string"
    NUMBER = "number"


class RuleAtomPolarity(StrEnum):
    """Body/head atom polarity (negation is body-only)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class RuleEffect(StrEnum):
    """Policy effect for decision-producing rule heads."""

    DERIVE = "derive"
    ALLOW = "allow"
    DENY = "deny"


class RuleStatementKind(StrEnum):
    """Top-level statement kinds."""

    FACT = "fact"
    RULE = "rule"
    QUERY = "query"
    DIRECTIVE = "directive"
    SPEAKS_FOR = "speaks_for"
    DELEGATION = "delegation"
    CONSTRAINT = "constraint"
    CHC = "chc"
    UNSUPPORTED = "unsupported"


class RuleItemRole(StrEnum):
    """Semantic role of a top-level item."""

    FACT = "fact"
    RULE = "rule"
    QUERY = "query"
    WORLD = "world"
    PRIORITY = "priority"
    PROFILE = "profile"
    TRUST = "trust"
    STRATUM = "stratum"
    SPEAKS_FOR = "speaks_for"
    DELEGATION = "delegation"
    CONSTRAINT = "constraint"
    CHC = "chc"
    SECPAL_SAYS = "secpal_says"
    UNSUPPORTED = "unsupported"


class RuleProfile(StrEnum):
    """Declared semantic profile for the document."""

    DATALOG = "datalog"
    HORN = "horn"
    CHC = "chc"
    SECPAL = "secpal"
    AUTHORIZATION = "authorization"


class WorldPolicyKind(StrEnum):
    """Open/closed-world and default-negation policy."""

    OPEN_WORLD = "open_world"
    CLOSED_WORLD = "closed_world"
    DEFAULT_NEGATION = "default_negation"


class PriorityPolicyKind(StrEnum):
    """Deny/allow conflict resolution (priority semantics)."""

    DENY_OVERRIDES = "deny_overrides"
    ALLOW_OVERRIDES = "allow_overrides"
    FIRST_APPLICABLE = "first_applicable"
    EXPLICIT_CONFLICT = "explicit_conflict"


class TermSortHint(StrEnum):
    """Optional sort annotation for principal/resource/action disambiguation."""

    ATOM = "atom"
    PRINCIPAL = "principal"
    RESOURCE = "resource"
    ACTION = "action"
    ROLE = "role"
    PREDICATE = "predicate"


# Authorization-critical predicates that require unambiguous argument roles.
_AUTHZ_PREDICATES: Final[frozenset[str]] = frozenset(
    {
        "may",
        "denied",
        "permit",
        "can",
        "authorized",
        "allow",
        "deny",
    }
)

_WORLD_ALIASES: Final[Mapping[str, WorldPolicyKind]] = {
    "closed": WorldPolicyKind.CLOSED_WORLD,
    "closed_world": WorldPolicyKind.CLOSED_WORLD,
    "open": WorldPolicyKind.OPEN_WORLD,
    "open_world": WorldPolicyKind.OPEN_WORLD,
    "default_negation": WorldPolicyKind.DEFAULT_NEGATION,
    "naf": WorldPolicyKind.DEFAULT_NEGATION,
}

_PRIORITY_ALIASES: Final[Mapping[str, PriorityPolicyKind]] = {
    "deny_overrides": PriorityPolicyKind.DENY_OVERRIDES,
    "deny-overrides": PriorityPolicyKind.DENY_OVERRIDES,
    "allow_overrides": PriorityPolicyKind.ALLOW_OVERRIDES,
    "allow-overrides": PriorityPolicyKind.ALLOW_OVERRIDES,
    "first_applicable": PriorityPolicyKind.FIRST_APPLICABLE,
    "first-applicable": PriorityPolicyKind.FIRST_APPLICABLE,
    "explicit_conflict": PriorityPolicyKind.EXPLICIT_CONFLICT,
    "explicit-conflict": PriorityPolicyKind.EXPLICIT_CONFLICT,
    "conflict": PriorityPolicyKind.EXPLICIT_CONFLICT,
}

_PROFILE_ALIASES: Final[Mapping[str, RuleProfile]] = {
    "datalog": RuleProfile.DATALOG,
    "horn": RuleProfile.HORN,
    "chc": RuleProfile.CHC,
    "horn_chc": RuleProfile.CHC,
    "secpal": RuleProfile.SECPAL,
    "authorization": RuleProfile.AUTHORIZATION,
    "authz": RuleProfile.AUTHORIZATION,
    "policy": RuleProfile.AUTHORIZATION,
}

# Constructs outside the controlled subset (retained + diagnosed).
UNSUPPORTED_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "aggregate",
        "choice",
        "soft",
        "maximize",
        "minimize",
        "#count",
        "#sum",
        "#max",
        "#min",
        "forall",
        "exists",
        "table",
        "import",
        "include",
        "load",
        "prolog",
        "cut",
        "!",
    }
)


# ---------------------------------------------------------------------------
# Errors / diagnostics
# ---------------------------------------------------------------------------


class RuleError(SyntaxContractError):
    """Base class for rule frontend failures."""

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
        self.message = message
        self.remediation = remediation
        self.range = range

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload


class RuleParseError(RuleError):
    """Raised by raising helpers when a parse fails closed."""


class SecPALError(RuleError):
    """Raised for SecPAL-profile-specific failures."""


_DIAG_SEQ = 0


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    remediation: str = "",
    diagnostic_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    global _DIAG_SEQ
    _DIAG_SEQ += 1
    diag_id = diagnostic_id or f"diag:rules:{code.replace('.', '-')}:{_DIAG_SEQ}"
    return SyntaxDiagnostic(
        diagnostic_id=diag_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class TokenKind(StrEnum):
    IDENT = "ident"
    VARIABLE = "variable"
    INTEGER = "integer"
    STRING = "string"
    LPAREN = "lparen"
    RPAREN = "rparen"
    COMMA = "comma"
    DOT = "dot"
    COLON = "colon"
    RULE_NECK = "rule_neck"  # :- or <=
    QUERY = "query"  # ?-
    AT = "at"
    NOT = "not"
    OP = "op"
    EOF = "eof"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    value: str
    start: int
    end: int

    @property
    def range(self) -> SourceRange:
        return SourceRange(self.start, self.end)


def tokenize_rules(
    text: str,
    *,
    limits: ParseLimits | None = None,
) -> tuple[tuple[Token, ...], tuple[SyntaxDiagnostic, ...]]:
    """Lex controlled Datalog/Horn/SecPAL source into a bounded token stream."""

    bounds = limits if limits is not None else ParseLimits()
    diagnostics: list[SyntaxDiagnostic] = []
    if not isinstance(text, str):
        diagnostics.append(
            _diag(
                code=CODE_INVALID_LITERAL,
                message="rule input must be a string",
                range=SourceRange(0, 0),
            )
        )
        return (), tuple(diagnostics)

    raw = text
    if len(raw.encode("utf-8", errors="replace")) > bounds.max_input_bytes:
        diagnostics.append(
            _diag(
                code=CODE_INPUT_LIMIT,
                message=(
                    f"rule input exceeds max_input_bytes={bounds.max_input_bytes}"
                ),
                range=SourceRange(0, min(len(raw), bounds.max_input_bytes)),
                remediation="Reduce input size or raise ParseLimits.max_input_bytes",
            )
        )
        return (), tuple(diagnostics)

    tokens: list[Token] = []
    i = 0
    n = len(raw)

    def emit(kind: TokenKind, value: str, start: int, end: int) -> bool:
        if len(tokens) >= bounds.max_tokens:
            diagnostics.append(
                _diag(
                    code=CODE_TOKEN_LIMIT,
                    message=(
                        f"rule token limit exceeded (max_tokens={bounds.max_tokens})"
                    ),
                    range=SourceRange(start, end),
                )
            )
            return False
        tokens.append(Token(kind=kind, value=value, start=start, end=end))
        return True

    while i < n:
        ch = raw[i]
        if ch.isspace():
            i += 1
            continue
        # Line comments: % …, // …, # … (but not #count aggregates — those
        # start with # followed by letter and are emitted as OP markers).
        if ch == "%":
            while i < n and raw[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and raw[i + 1] == "/":
            i += 2
            while i < n and raw[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and raw[i + 1] == "*":
            start = i
            i += 2
            closed = False
            while i + 1 < n:
                if raw[i] == "*" and raw[i + 1] == "/":
                    i += 2
                    closed = True
                    break
                i += 1
            if not closed:
                diagnostics.append(
                    _diag(
                        code=CODE_UNTERMINATED_COMMENT,
                        message="unterminated block comment",
                        range=SourceRange(start, n),
                    )
                )
                return (), tuple(diagnostics)
            continue
        if ch == "#" and i + 1 < n and raw[i + 1].isalpha():
            # Aggregate-style markers (#count, #sum, …) retained as OP.
            j = i + 1
            while j < n and (raw[j].isalnum() or raw[j] == "_"):
                j += 1
            if not emit(TokenKind.OP, raw[i:j], i, j):
                return (), tuple(diagnostics)
            i = j
            continue
        if ch == "#":
            while i < n and raw[i] not in "\r\n":
                i += 1
            continue

        start = i
        if raw.startswith(":-", i) or raw.startswith("<=", i):
            lexeme = raw[i : i + 2]
            if not emit(TokenKind.RULE_NECK, lexeme, start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("?-", i):
            if not emit(TokenKind.QUERY, "?-", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("speaks-for", i) and (
            i + 10 >= n or not (raw[i + 10].isalnum() or raw[i + 10] == "_")
        ):
            if not emit(TokenKind.IDENT, "speaks-for", start, i + 10):
                return (), tuple(diagnostics)
            i += 10
            continue
        if raw.startswith("delegation-depth", i) and (
            i + 16 >= n or not (raw[i + 16].isalnum() or raw[i + 16] == "_")
        ):
            if not emit(TokenKind.IDENT, "delegation-depth", start, i + 16):
                return (), tuple(diagnostics)
            i += 16
            continue

        if ch == "(":
            if not emit(TokenKind.LPAREN, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ")":
            if not emit(TokenKind.RPAREN, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ",":
            if not emit(TokenKind.COMMA, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ".":
            if not emit(TokenKind.DOT, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ":":
            if not emit(TokenKind.COLON, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "@":
            if not emit(TokenKind.AT, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "!":
            # Standalone cut / negation bang — unsupported marker path.
            if not emit(TokenKind.OP, "!", start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue

        if ch in {'"', "'"}:
            quote = ch
            i += 1
            chars: list[str] = []
            while i < n:
                if raw[i] == "\\" and i + 1 < n:
                    chars.append(raw[i + 1])
                    i += 2
                    continue
                if raw[i] == quote:
                    i += 1
                    if not emit(TokenKind.STRING, "".join(chars), start, i):
                        return (), tuple(diagnostics)
                    break
                chars.append(raw[i])
                i += 1
            else:
                diagnostics.append(
                    _diag(
                        code=CODE_UNTERMINATED_STRING,
                        message="unterminated string literal",
                        range=SourceRange(start, n),
                    )
                )
                return (), tuple(diagnostics)
            continue

        if ch.isdigit() or (ch in "+-" and i + 1 < n and raw[i + 1].isdigit()):
            j = i + 1
            while j < n and raw[j].isdigit():
                j += 1
            if not emit(TokenKind.INTEGER, raw[i:j], start, j):
                return (), tuple(diagnostics)
            i = j
            continue

        # Variable: leading uppercase or ?Name / _var style.
        if ch == "?" and i + 1 < n and (raw[i + 1].isalpha() or raw[i + 1] == "_"):
            j = i + 1
            while j < n and (raw[j].isalnum() or raw[j] == "_"):
                j += 1
            if not emit(TokenKind.VARIABLE, raw[i:j], start, j):
                return (), tuple(diagnostics)
            i = j
            continue

        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (raw[j].isalnum() or raw[j] in "_-"):
                j += 1
            value = raw[i:j]
            folded = value.casefold()
            if folded in {"not", "naf"}:
                if not emit(TokenKind.NOT, value, start, j):
                    return (), tuple(diagnostics)
            elif value[0].isupper() or value.startswith("_"):
                if not emit(TokenKind.VARIABLE, value, start, j):
                    return (), tuple(diagnostics)
            else:
                if not emit(TokenKind.IDENT, value, start, j):
                    return (), tuple(diagnostics)
            i = j
            continue

        if ch in {"=", "<", ">", "|", "&", "*", "+", "-", "/", "~", "$", ";", "{", "}"}:
            if not emit(TokenKind.OP, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue

        diagnostics.append(
            _diag(
                code=CODE_INVALID_LITERAL,
                message=f"unexpected character {ch!r}",
                range=SourceRange(start, start + 1),
            )
        )
        return (), tuple(diagnostics)

    tokens.append(Token(kind=TokenKind.EOF, value="", start=n, end=n))
    return tuple(tokens), tuple(diagnostics)


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleTerm:
    """A constant, variable, string, or number term."""

    kind: RuleTermKind
    name: str
    sort: TermSortHint = TermSortHint.ATOM
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            self.kind if isinstance(self.kind, RuleTermKind) else RuleTermKind(self.kind),
        )
        object.__setattr__(
            self,
            "sort",
            self.sort if isinstance(self.sort, TermSortHint) else TermSortHint(self.sort),
        )
        if not isinstance(self.name, str) or not self.name:
            raise RuleError("term name must be a non-empty string", code=CODE_MALFORMED_TERM)

    @property
    def is_variable(self) -> bool:
        return self.kind is RuleTermKind.VARIABLE

    @property
    def is_ground(self) -> bool:
        return not self.is_variable

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "name": self.name,
            "sort": self.sort.value,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (self.kind.value, self.name, self.sort.value)

    def normalized(self) -> "RuleTerm":
        return self


@dataclass(frozen=True, slots=True)
class RuleAtom:
    """A positive or negative predicate application."""

    predicate: str
    arguments: tuple[RuleTerm, ...] = ()
    polarity: RuleAtomPolarity = RuleAtomPolarity.POSITIVE
    issuer: str = ""
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.predicate, str) or not self.predicate:
            raise RuleError(
                "atom predicate must be a non-empty string",
                code=CODE_MALFORMED_ATOM,
            )
        object.__setattr__(self, "arguments", tuple(self.arguments))
        object.__setattr__(
            self,
            "polarity",
            self.polarity
            if isinstance(self.polarity, RuleAtomPolarity)
            else RuleAtomPolarity(self.polarity),
        )

    @property
    def is_negative(self) -> bool:
        return self.polarity is RuleAtomPolarity.NEGATIVE

    @property
    def is_ground(self) -> bool:
        return all(arg.is_ground for arg in self.arguments)

    @property
    def variables(self) -> frozenset[str]:
        return frozenset(arg.name for arg in self.arguments if arg.is_variable)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "arguments": [item.to_dict() for item in self.arguments],
            "issuer": self.issuer,
            "polarity": self.polarity.value,
            "predicate": self.predicate,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (
            self.predicate,
            tuple(arg.structural_key() for arg in self.arguments),
            self.polarity.value,
            self.issuer,
        )

    def normalized(self) -> "RuleAtom":
        return RuleAtom(
            predicate=self.predicate,
            arguments=tuple(arg.normalized() for arg in self.arguments),
            polarity=self.polarity,
            issuer=self.issuer,
            range=self.range,
        )


@dataclass(frozen=True, slots=True)
class RuleStatement:
    """One top-level fact, rule, query, directive, or retained unsupported item."""

    kind: RuleStatementKind
    role: RuleItemRole
    head: RuleAtom | None = None
    body: tuple[RuleAtom, ...] = ()
    effect: RuleEffect = RuleEffect.DERIVE
    stratum: int = 0
    directive_name: str = ""
    directive_value: str = ""
    principal: str = ""
    subject: str = ""
    action: str = ""
    resource: str = ""
    delegation_depth: int = 0
    constraint_kind: str = ""
    raw: str = ""
    unsupported_reason: str = ""
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            self.kind if isinstance(self.kind, RuleStatementKind) else RuleStatementKind(self.kind),
        )
        object.__setattr__(
            self,
            "role",
            self.role if isinstance(self.role, RuleItemRole) else RuleItemRole(self.role),
        )
        object.__setattr__(
            self,
            "effect",
            self.effect if isinstance(self.effect, RuleEffect) else RuleEffect(self.effect),
        )
        object.__setattr__(self, "body", tuple(self.body))
        if not isinstance(self.stratum, int) or isinstance(self.stratum, bool) or self.stratum < 0:
            raise RuleError("stratum must be a non-negative integer", code=CODE_MALFORMED_RULE)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": self.action,
            "body": [item.to_dict() for item in self.body],
            "constraint_kind": self.constraint_kind,
            "delegation_depth": self.delegation_depth,
            "directive_name": self.directive_name,
            "directive_value": self.directive_value,
            "effect": self.effect.value,
            "head": None if self.head is None else self.head.to_dict(),
            "kind": self.kind.value,
            "principal": self.principal,
            "raw": self.raw,
            "resource": self.resource,
            "role": self.role.value,
            "stratum": self.stratum,
            "subject": self.subject,
            "unsupported_reason": self.unsupported_reason,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (
            self.kind.value,
            self.role.value,
            None if self.head is None else self.head.structural_key(),
            tuple(item.structural_key() for item in self.body),
            self.effect.value,
            self.stratum,
            self.directive_name,
            self.directive_value,
            self.principal,
            self.subject,
            self.action,
            self.resource,
            self.delegation_depth,
            self.constraint_kind,
            self.unsupported_reason,
            self.raw.strip(),
        )

    def normalized(self) -> "RuleStatement":
        head = None if self.head is None else self.head.normalized()
        body = tuple(item.normalized() for item in self.body)
        return RuleStatement(
            kind=self.kind,
            role=self.role,
            head=head,
            body=body,
            effect=self.effect,
            stratum=self.stratum,
            directive_name=self.directive_name,
            directive_value=self.directive_value,
            principal=self.principal,
            subject=self.subject,
            action=self.action,
            resource=self.resource,
            delegation_depth=self.delegation_depth,
            constraint_kind=self.constraint_kind,
            raw=self.raw,
            unsupported_reason=self.unsupported_reason,
            range=self.range,
        )


@dataclass(frozen=True, slots=True)
class RuleDocument:
    """Elaborated Datalog / Horn / CHC / SecPAL program.

    World and priority policies are first-class identity fields so missing
    semantics cannot be silently assumed.  Unsupported constructs are retained
    with explicit disposition rather than dropped.
    """

    statements: tuple[RuleStatement, ...] = ()
    profile: RuleProfile = RuleProfile.HORN
    world_policy: WorldPolicyKind | None = None
    priority_policy: PriorityPolicyKind | None = None
    trust_roots: tuple[str, ...] = ()
    profile_id: str = RULE_PROFILE_ID
    notation_id: str = RULE_NOTATION_ID
    notation_version: str = RULE_NOTATION_VERSION
    family_id: str = RULE_FAMILY_ID
    schema_version: str = RULE_DOCUMENT_SCHEMA_VERSION
    source_text: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "statements", tuple(self.statements))
        object.__setattr__(
            self,
            "profile",
            self.profile if isinstance(self.profile, RuleProfile) else RuleProfile(self.profile),
        )
        if self.world_policy is not None and not isinstance(
            self.world_policy, WorldPolicyKind
        ):
            object.__setattr__(
                self, "world_policy", WorldPolicyKind(self.world_policy)
            )
        if self.priority_policy is not None and not isinstance(
            self.priority_policy, PriorityPolicyKind
        ):
            object.__setattr__(
                self, "priority_policy", PriorityPolicyKind(self.priority_policy)
            )
        object.__setattr__(self, "trust_roots", tuple(self.trust_roots))
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise RuleError(
                "document metadata must be immutable JSON data",
                code=CODE_MALFORMED_STATEMENT,
            ) from error
        if self.schema_version != RULE_DOCUMENT_SCHEMA_VERSION:
            raise RuleError(
                f"unsupported document schema {self.schema_version!r}",
                code=CODE_MALFORMED_STATEMENT,
            )

    @property
    def interface(self) -> str:
        return RULE_FRONTEND_INTERFACE

    @property
    def facts(self) -> tuple[RuleStatement, ...]:
        return tuple(
            item for item in self.statements if item.kind is RuleStatementKind.FACT
        )

    @property
    def rules(self) -> tuple[RuleStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind in {RuleStatementKind.RULE, RuleStatementKind.CHC}
        )

    @property
    def queries(self) -> tuple[RuleStatement, ...]:
        return tuple(
            item for item in self.statements if item.kind is RuleStatementKind.QUERY
        )

    @property
    def delegations(self) -> tuple[RuleStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is RuleStatementKind.DELEGATION
        )

    @property
    def speaks_for(self) -> tuple[RuleStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is RuleStatementKind.SPEAKS_FOR
        )

    @property
    def constraints(self) -> tuple[RuleStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is RuleStatementKind.CONSTRAINT
        )

    @property
    def unsupported(self) -> tuple[RuleStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is RuleStatementKind.UNSUPPORTED
        )

    @property
    def has_unsupported(self) -> bool:
        return bool(self.unsupported)

    @property
    def has_negation(self) -> bool:
        for stmt in self.statements:
            for atom in stmt.body:
                if atom.is_negative:
                    return True
            if stmt.head is not None and stmt.head.is_negative:
                return True
        return False

    @property
    def has_decision_effects(self) -> bool:
        return any(
            stmt.effect in {RuleEffect.ALLOW, RuleEffect.DENY}
            for stmt in self.statements
        )

    @property
    def predicate_names(self) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()
        for stmt in self.statements:
            for atom in ((stmt.head,) if stmt.head else ()) + stmt.body:
                if atom is None:
                    continue
                if atom.predicate and atom.predicate not in seen:
                    seen.add(atom.predicate)
                    names.append(atom.predicate)
        return tuple(names)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "interface": RULE_FRONTEND_INTERFACE,
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "predicate_names": list(self.predicate_names),
            "priority_policy": (
                None if self.priority_policy is None else self.priority_policy.value
            ),
            "profile": self.profile.value,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "statements": [item.to_dict() for item in self.statements],
            "trust_roots": list(self.trust_roots),
            "unsupported_count": len(self.unsupported),
            "world_policy": (
                None if self.world_policy is None else self.world_policy.value
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["metadata"] = self.metadata.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (
            self.profile.value,
            None if self.world_policy is None else self.world_policy.value,
            None if self.priority_policy is None else self.priority_policy.value,
            self.trust_roots,
            tuple(item.structural_key() for item in self.statements),
        )

    def normalized(self) -> "RuleDocument":
        statements = tuple(item.normalized() for item in self.statements)
        return RuleDocument(
            statements=statements,
            profile=self.profile,
            world_policy=self.world_policy,
            priority_policy=self.priority_policy,
            trust_roots=self.trust_roots,
            profile_id=self.profile_id,
            notation_id=self.notation_id,
            notation_version=self.notation_version,
            family_id=self.family_id,
            schema_version=self.schema_version,
            source_text=self.source_text,
            metadata=self.metadata,
        )


def documents_semantically_compatible(
    left: RuleDocument, right: RuleDocument
) -> bool:
    """Return True when two documents share the same structural semantics."""

    if not isinstance(left, RuleDocument) or not isinstance(right, RuleDocument):
        return False
    return left.normalized().structural_key() == right.normalized().structural_key()


# ---------------------------------------------------------------------------
# Semantic checks (fail-closed)
# ---------------------------------------------------------------------------


def check_range_restriction(
    statement: RuleStatement,
) -> tuple[SyntaxDiagnostic, ...]:
    """Fail when head variables are not range-restricted by positive body atoms.

    A variable is *safe* iff it appears in at least one positive body literal.
    Facts must be ground.  Queries and directives are exempt.
    """

    if statement.kind not in {
        RuleStatementKind.RULE,
        RuleStatementKind.CHC,
        RuleStatementKind.FACT,
    }:
        return ()
    if statement.head is None:
        return ()
    head_vars = statement.head.variables
    if statement.kind is RuleStatementKind.FACT:
        if head_vars or not statement.head.is_ground:
            return (
                _diag(
                    code=CODE_UNSAFE_VARIABLE,
                    message=(
                        f"fact {statement.head.predicate!r} is not ground; "
                        f"unsafe variables {sorted(head_vars)}"
                    ),
                    range=statement.range,
                    remediation="Facts must use only constant arguments",
                ),
            )
        return ()
    positive_vars: set[str] = set()
    for atom in statement.body:
        if not atom.is_negative:
            positive_vars.update(atom.variables)
    unsafe = sorted(head_vars - positive_vars)
    if unsafe:
        return (
            _diag(
                code=CODE_UNSAFE_VARIABLE,
                message=(
                    f"rule head of {statement.head.predicate!r} has unsafe "
                    f"variables {unsafe} (not range-restricted by positive body)"
                ),
                range=statement.range,
                remediation=(
                    "Every head variable must appear in a positive body atom"
                ),
            ),
        )
    # Negative body atoms must also be range-restricted: free vars only from
    # positive body (standard Datalog safety for NAF).
    for atom in statement.body:
        if not atom.is_negative:
            continue
        free = sorted(atom.variables - positive_vars)
        if free:
            return (
                _diag(
                    code=CODE_UNSAFE_VARIABLE,
                    message=(
                        f"negative literal {atom.predicate!r} has unsafe "
                        f"variables {free}"
                    ),
                    range=atom.range or statement.range,
                    remediation=(
                        "Variables in negative literals must be bound by "
                        "positive body atoms"
                    ),
                ),
            )
    return ()


def check_stratification(
    document: RuleDocument,
) -> tuple[SyntaxDiagnostic, ...]:
    """Detect unstratified negation via positive/negative dependency graph.

    Builds a predicate dependency graph.  A negative edge from head predicate
    H to body predicate B requires stratum(B) < stratum(H).  Cycles that mix
    negative edges are unstratified.
    """

    rules = [
        stmt
        for stmt in document.statements
        if stmt.kind in {RuleStatementKind.RULE, RuleStatementKind.CHC}
        and stmt.head is not None
    ]
    if not rules:
        return ()

    # Positive and negative dependency edges: head → body predicate.
    pos_edges: dict[str, set[str]] = defaultdict(set)
    neg_edges: dict[str, set[str]] = defaultdict(set)
    defining_strata: dict[str, set[int]] = defaultdict(set)
    for rule in rules:
        assert rule.head is not None
        head_p = rule.head.predicate
        defining_strata[head_p].add(rule.stratum)
        for atom in rule.body:
            if atom.is_negative:
                neg_edges[head_p].add(atom.predicate)
            else:
                pos_edges[head_p].add(atom.predicate)

    # Explicit stratum check when strata are declared.
    diagnostics: list[SyntaxDiagnostic] = []
    for rule in rules:
        assert rule.head is not None
        for atom in rule.body:
            if not atom.is_negative:
                continue
            defined = defining_strata.get(atom.predicate, set())
            if not defined:
                continue  # EDB-only: safe
            if any(s >= rule.stratum for s in defined):
                diagnostics.append(
                    _diag(
                        code=CODE_UNSTRATIFIED_NEGATION,
                        message=(
                            f"rule for {rule.head.predicate!r} is not stratified: "
                            f"negative literal {atom.predicate!r} is defined at "
                            f"strata {sorted(defined)} which are not strictly "
                            f"below stratum {rule.stratum}"
                        ),
                        range=rule.range,
                        remediation=(
                            "Assign a strictly higher stratum to rules that "
                            "negate intensional predicates"
                        ),
                    )
                )

    # Graph-based cycle detection with negative edges (when all strata equal).
    # Collapse to SCC over undirected-style reachability treating neg edges
    # as forcing a higher stratum — if a neg edge lands inside the same SCC
    # as its source under positive+negative edges, unstratified.
    preds: set[str] = set()
    for h, deps in pos_edges.items():
        preds.add(h)
        preds.update(deps)
    for h, deps in neg_edges.items():
        preds.add(h)
        preds.update(deps)
    if not preds:
        return tuple(diagnostics)

    # Tarjan SCC on the combined graph.
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    sccs: list[set[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in pos_edges.get(v, set()) | neg_edges.get(v, set()):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            component: set[str] = set()
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.add(w)
                if w == v:
                    break
            sccs.append(component)

    for p in sorted(preds):
        if p not in indices:
            strongconnect(p)

    pred_scc = {p: i for i, comp in enumerate(sccs) for p in comp}
    for head, deps in neg_edges.items():
        for dep in deps:
            if pred_scc.get(head) == pred_scc.get(dep):
                # Same SCC with a negative edge → unstratified, unless already
                # reported via explicit stratum mismatch.
                if not any(
                    d.code == CODE_UNSTRATIFIED_NEGATION
                    and head in d.message
                    and dep in d.message
                    for d in diagnostics
                ):
                    diagnostics.append(
                        _diag(
                            code=CODE_UNSTRATIFIED_NEGATION,
                            message=(
                                f"unstratified negation: predicate {head!r} "
                                f"negatively depends on {dep!r} inside a "
                                "recursive cycle"
                            ),
                            remediation=(
                                "Break the negative cycle or stratify the "
                                "program with @stratum directives"
                            ),
                        )
                    )
    return tuple(diagnostics)


def check_world_and_priority(
    document: RuleDocument,
) -> tuple[SyntaxDiagnostic, ...]:
    """Require explicit world/priority when negation or decision effects appear."""

    diagnostics: list[SyntaxDiagnostic] = []
    if document.has_negation and document.world_policy is None:
        diagnostics.append(
            _diag(
                code=CODE_MISSING_WORLD,
                message=(
                    "document uses negation but does not declare world "
                    "semantics (@world closed_world|default_negation|open_world)"
                ),
                remediation=(
                    "Add `@world closed_world.` (or default_negation) before "
                    "rules that use `not`"
                ),
            )
        )
    if document.has_decision_effects and document.priority_policy is None:
        diagnostics.append(
            _diag(
                code=CODE_MISSING_PRIORITY,
                message=(
                    "document uses allow/deny effects but does not declare "
                    "priority semantics (@priority deny_overrides|…)"
                ),
                remediation=(
                    "Add `@priority deny_overrides.` (or another closed "
                    "priority policy) before decision-producing rules"
                ),
            )
        )
    # Open-world + default negation is unsupported disposition.
    if (
        document.world_policy is WorldPolicyKind.OPEN_WORLD
        and document.has_negation
    ):
        diagnostics.append(
            _diag(
                code=CODE_UNSUPPORTED_CONSTRUCT,
                message=(
                    "open-world policy with default negation is unsupported; "
                    "use closed_world or default_negation with explicit bounds"
                ),
                severity=DiagnosticSeverity.ERROR,
                remediation="Change `@world` to closed_world or default_negation",
            )
        )
    return tuple(diagnostics)


def check_ambiguous_authz_terms(
    document: RuleDocument,
) -> tuple[SyntaxDiagnostic, ...]:
    """Reject ambiguous principal/resource/action terms under authz profiles.

    Under ``secpal`` / ``authorization`` profiles, decision atoms
    (``may``/``can``/``denied``/…) must use three arguments with distinct
    sort hints, or explicit SecPAL surface forms that name principal,
    action, and resource.  Bare untyped three-place atoms where all arguments
    share sort ``atom`` are ambiguous.
    """

    if document.profile not in {RuleProfile.SECPAL, RuleProfile.AUTHORIZATION}:
        return ()

    diagnostics: list[SyntaxDiagnostic] = []
    for stmt in document.statements:
        atoms: list[RuleAtom] = []
        if stmt.head is not None:
            atoms.append(stmt.head)
        atoms.extend(stmt.body)
        for atom in atoms:
            pred = atom.predicate.casefold()
            if pred not in _AUTHZ_PREDICATES:
                continue
            if len(atom.arguments) != 3:
                diagnostics.append(
                    _diag(
                        code=CODE_AMBIGUOUS_TERM,
                        message=(
                            f"authorization atom {atom.predicate!r} must have "
                            "exactly three arguments (principal, action, resource)"
                        ),
                        range=atom.range or stmt.range,
                        remediation=(
                            "Use may(Principal, Action, Resource) with sort "
                            "annotations or SecPAL surface syntax"
                        ),
                    )
                )
                continue
            sorts = [arg.sort for arg in atom.arguments]
            # Explicit principal/action/resource ordering is unambiguous.
            if sorts == [
                TermSortHint.PRINCIPAL,
                TermSortHint.ACTION,
                TermSortHint.RESOURCE,
            ]:
                continue
            # All atom-sort is ambiguous under authz profile.
            if all(s is TermSortHint.ATOM for s in sorts):
                diagnostics.append(
                    _diag(
                        code=CODE_AMBIGUOUS_TERM,
                        message=(
                            f"ambiguous principal/resource/action terms in "
                            f"{atom.predicate!r}({', '.join(a.name for a in atom.arguments)}); "
                            "arguments lack sort annotations under "
                            f"profile {document.profile.value}"
                        ),
                        range=atom.range or stmt.range,
                        remediation=(
                            "Annotate terms as principal:P, action:A, "
                            "resource:R or use SecPAL query/delegation forms"
                        ),
                    )
                )
                continue
            # Mixed but wrong order / duplicate roles.
            role_set = set(sorts)
            if (
                TermSortHint.PRINCIPAL not in role_set
                or TermSortHint.ACTION not in role_set
                or TermSortHint.RESOURCE not in role_set
            ):
                diagnostics.append(
                    _diag(
                        code=CODE_AMBIGUOUS_TERM,
                        message=(
                            f"authorization atom {atom.predicate!r} arguments "
                            f"have sorts {[s.value for s in sorts]} which do "
                            "not uniquely identify principal, action, and resource"
                        ),
                        range=atom.range or stmt.range,
                    )
                )
        # Delegation / query statements must name all three roles.
        if stmt.kind is RuleStatementKind.DELEGATION:
            if not stmt.principal or not stmt.subject or not stmt.action:
                diagnostics.append(
                    _diag(
                        code=CODE_AMBIGUOUS_TERM,
                        message=(
                            "delegation statement is missing principal, subject, "
                            "or action"
                        ),
                        range=stmt.range,
                    )
                )
        if stmt.kind is RuleStatementKind.QUERY and stmt.role is RuleItemRole.QUERY:
            if stmt.principal or stmt.action or stmt.resource:
                if not (stmt.principal and stmt.action):
                    diagnostics.append(
                        _diag(
                            code=CODE_AMBIGUOUS_TERM,
                            message=(
                                "authorization query requires principal and action"
                            ),
                            range=stmt.range,
                        )
                    )
    return tuple(diagnostics)


def validate_document(
    document: RuleDocument,
    *,
    fail_on_unsupported: bool = False,
) -> tuple[SyntaxDiagnostic, ...]:
    """Run all static semantic checks; return diagnostics (errors + warnings)."""

    diagnostics: list[SyntaxDiagnostic] = []
    for stmt in document.statements:
        diagnostics.extend(check_range_restriction(stmt))
        if stmt.kind is RuleStatementKind.UNSUPPORTED:
            diagnostics.append(
                _diag(
                    code=CODE_UNSUPPORTED_CONSTRUCT,
                    message=(
                        stmt.unsupported_reason
                        or f"unsupported construct retained: {stmt.raw!r}"
                    ),
                    range=stmt.range,
                    severity=(
                        DiagnosticSeverity.ERROR
                        if fail_on_unsupported
                        else DiagnosticSeverity.WARNING
                    ),
                )
            )
    diagnostics.extend(check_stratification(document))
    diagnostics.extend(check_world_and_priority(document))
    diagnostics.extend(check_ambiguous_authz_terms(document))
    return tuple(diagnostics)


# ---------------------------------------------------------------------------
# CHC lowering
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CHCClause:
    """One constrained Horn clause ``body => head``."""

    clause_id: str
    head: RuleAtom
    body: tuple[RuleAtom, ...] = ()
    is_query: bool = False
    constraints: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": [item.to_dict() for item in self.body],
            "clause_id": self.clause_id,
            "constraints": list(self.constraints),
            "head": self.head.to_dict(),
            "is_query": self.is_query,
        }


@dataclass(frozen=True, slots=True)
class CHCLoweringResult:
    """Deterministic CHC view of a rule document with explicit loss receipts."""

    clauses: tuple[CHCClause, ...] = ()
    unsupported: tuple[str, ...] = ()
    loss_receipts: tuple[dict[str, Any], ...] = ()
    profile: str = RuleProfile.CHC.value
    schema_version: str = CHC_LOWERING_SCHEMA_VERSION
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "clauses": [item.to_dict() for item in self.clauses],
            "loss_receipts": list(self.loss_receipts),
            "ok": self.ok,
            "profile": self.profile,
            "schema_version": self.schema_version,
            "unsupported": list(self.unsupported),
        }


def lower_to_chc(document: RuleDocument) -> CHCLoweringResult:
    """Lower a rule document to constrained Horn clauses.

    Supported: positive Horn rules, facts (empty body), CHC statements, and
    queries as query clauses.  SecPAL says/delegation/speaks-for, default
    negation, and allow/deny priority resolution receive explicit unsupported
    loss receipts rather than silent omission.
    """

    if not isinstance(document, RuleDocument):
        raise RuleError(
            "lower_to_chc requires a RuleDocument",
            code=CODE_CHC_LOWERING,
        )
    clauses: list[CHCClause] = []
    unsupported: list[str] = []
    losses: list[dict[str, Any]] = []
    counter = 0

    def next_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}:{counter}"

    for stmt in document.statements:
        if stmt.kind is RuleStatementKind.UNSUPPORTED:
            unsupported.append(stmt.unsupported_reason or stmt.raw)
            losses.append(
                {
                    "kind": "unsupported_construct",
                    "reason": stmt.unsupported_reason or stmt.raw,
                    "disposition": "retained_not_lowered",
                }
            )
            continue
        if stmt.kind is RuleStatementKind.SPEAKS_FOR:
            unsupported.append("speaks_for")
            losses.append(
                {
                    "kind": "speaks_for",
                    "disposition": "unsupported_in_chc",
                    "principal": stmt.principal,
                    "subject": stmt.subject,
                }
            )
            continue
        if stmt.kind is RuleStatementKind.DELEGATION:
            unsupported.append("delegation")
            losses.append(
                {
                    "kind": "delegation",
                    "disposition": "unsupported_in_chc",
                    "principal": stmt.principal,
                    "subject": stmt.subject,
                    "action": stmt.action,
                }
            )
            continue
        if stmt.kind is RuleStatementKind.DIRECTIVE:
            continue
        if stmt.kind is RuleStatementKind.CONSTRAINT:
            # Constraints attach as named guards on subsequent clauses only when
            # referenced; record as loss if orphaned.
            losses.append(
                {
                    "kind": "constraint",
                    "disposition": "recorded_as_guard_symbol",
                    "constraint_kind": stmt.constraint_kind,
                    "value": stmt.directive_value,
                }
            )
            continue
        if stmt.head is None:
            continue
        if any(atom.is_negative for atom in stmt.body):
            unsupported.append(f"negation:{stmt.head.predicate}")
            losses.append(
                {
                    "kind": "negation",
                    "disposition": "unsupported_in_plain_chc",
                    "predicate": stmt.head.predicate,
                    "remediation": "Use stratified Datalog evaluator, not CHC lowering",
                }
            )
            continue
        if stmt.effect in {RuleEffect.ALLOW, RuleEffect.DENY}:
            losses.append(
                {
                    "kind": "priority_effect",
                    "disposition": "effect_erased_to_derive",
                    "effect": stmt.effect.value,
                    "predicate": stmt.head.predicate,
                }
            )
        if stmt.head.issuer:
            losses.append(
                {
                    "kind": "secpal_issuer",
                    "disposition": "issuer_erased",
                    "issuer": stmt.head.issuer,
                    "predicate": stmt.head.predicate,
                }
            )
        is_query = stmt.kind is RuleStatementKind.QUERY
        clauses.append(
            CHCClause(
                clause_id=next_id("chc"),
                head=stmt.head,
                body=stmt.body,
                is_query=is_query,
            )
        )

    ok = not any(
        loss.get("disposition", "").startswith("unsupported") for loss in losses
    ) or bool(clauses)
    # ok is True when we produced a usable CHC subset; losses remain explicit.
    return CHCLoweringResult(
        clauses=tuple(clauses),
        unsupported=tuple(dict.fromkeys(unsupported)),
        loss_receipts=tuple(losses),
        ok=bool(clauses) or not unsupported,
    )


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _TokenCursor:
    def __init__(self, tokens: Sequence[Token], limits: ParseLimits) -> None:
        self.tokens = tuple(tokens)
        self.limits = limits
        self.index = 0
        self.depth = 0

    def current(self) -> Token:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 0) -> Token:
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def is_eof(self) -> bool:
        return self.current().kind is TokenKind.EOF

    def advance(self) -> Token:
        token = self.current()
        if not self.is_eof():
            self.index += 1
        return token

    def match(self, *kinds: TokenKind) -> Token | None:
        token = self.current()
        if token.kind in kinds:
            return self.advance()
        return None

    def match_value(self, kind: TokenKind, *values: str) -> Token | None:
        token = self.current()
        if token.kind is kind and token.value.casefold() in {
            v.casefold() for v in values
        }:
            return self.advance()
        return None

    def expect(self, *kinds: TokenKind, code: str = CODE_UNEXPECTED_TOKEN) -> Token:
        token = self.match(*kinds)
        if token is not None:
            return token
        current = self.current()
        expected = " or ".join(k.value for k in kinds)
        raise RuleError(
            f"expected {expected}; got {current.value!r} ({current.kind.value})",
            code=code,
            range=current.range,
        )

    def enter(self) -> None:
        self.depth += 1
        if self.depth > self.limits.max_depth:
            raise RuleError(
                f"parse depth {self.depth} exceeds limit {self.limits.max_depth}",
                code=CODE_PARSE_DEPTH,
                range=self.current().range,
            )

    def leave(self) -> None:
        self.depth = max(0, self.depth - 1)

    def span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        return SourceRange(start.start, end.end)


class _RuleParserEngine:
    """Recursive-descent parser for the controlled rule subset."""

    def __init__(
        self,
        tokens: Sequence[Token],
        *,
        source_text: str = "",
        limits: ParseLimits | None = None,
        default_profile: RuleProfile = RuleProfile.HORN,
    ) -> None:
        self.cursor = _TokenCursor(
            tokens, limits if limits is not None else ParseLimits()
        )
        self.source_text = source_text
        self.diagnostics: list[SyntaxDiagnostic] = []
        self.statements: list[RuleStatement] = []
        self.profile = default_profile
        self.world_policy: WorldPolicyKind | None = None
        self.priority_policy: PriorityPolicyKind | None = None
        self.trust_roots: list[str] = []
        self.current_stratum = 0

    def parse(self) -> RuleDocument:
        if self.cursor.is_eof():
            raise RuleError(
                "empty rule input; expected fact, rule, query, or directive",
                code=CODE_EMPTY_INPUT,
                range=SourceRange(0, 0),
            )
        while not self.cursor.is_eof():
            stmt = self._parse_statement()
            self.statements.append(stmt)
        family_id = RULE_FAMILY_ID
        profile_id = RULE_PROFILE_ID
        if self.profile in {RuleProfile.SECPAL, RuleProfile.AUTHORIZATION}:
            family_id = SECPAL_FAMILY_ID
            profile_id = SECPAL_PROFILE_ID
        elif self.profile is RuleProfile.CHC:
            profile_id = "chc"
        elif self.profile is RuleProfile.DATALOG:
            profile_id = "datalog"
        return RuleDocument(
            statements=tuple(self.statements),
            profile=self.profile,
            world_policy=self.world_policy,
            priority_policy=self.priority_policy,
            trust_roots=tuple(self.trust_roots),
            profile_id=profile_id,
            family_id=family_id,
            source_text=self.source_text,
            metadata=FrozenMap(
                {
                    "module_version": RULE_MODULE_VERSION,
                    "interface": RULE_FRONTEND_INTERFACE,
                }
            ),
        )

    def _raw_slice(self, start: int, end: int) -> str:
        if not self.source_text:
            return ""
        return self.source_text[start:end]

    def _parse_statement(self) -> RuleStatement:
        start_tok = self.cursor.current()
        start_index = start_tok.start

        # Unsupported OP markers at statement start.
        if start_tok.kind is TokenKind.OP:
            return self._consume_unsupported(start_tok, start_index)

        # Query: ?- goals.
        if self.cursor.match(TokenKind.QUERY) is not None:
            goals = self._parse_atom_list()
            end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_QUERY)
            if not goals:
                raise RuleError(
                    "query requires at least one goal",
                    code=CODE_MALFORMED_QUERY,
                    range=start_tok.range,
                )
            return RuleStatement(
                kind=RuleStatementKind.QUERY,
                role=RuleItemRole.QUERY,
                head=goals[0],
                body=tuple(goals[1:]),
                range=self.cursor.span(start_tok.range, end.range),
            )

        # Directive: @name value.
        if self.cursor.match(TokenKind.AT) is not None:
            return self._parse_directive(start_tok)

        # Effect-prefixed rules: allow/deny head :- body.
        effect = RuleEffect.DERIVE
        effect_tok = self.cursor.match_value(TokenKind.IDENT, "allow", "deny")
        if effect_tok is not None:
            effect = (
                RuleEffect.ALLOW
                if effect_tok.value.casefold() == "allow"
                else RuleEffect.DENY
            )

        # CHC keyword prefix.
        is_chc = False
        if self.cursor.match_value(TokenKind.IDENT, "chc") is not None:
            is_chc = True

        # Constraint keyword.
        if self.cursor.match_value(TokenKind.IDENT, "constraint") is not None:
            return self._parse_constraint(start_tok)

        # Authorization query: query "p" can "a" on "r".
        if self.cursor.match_value(TokenKind.IDENT, "query") is not None:
            return self._parse_authz_query(start_tok)

        # SecPAL / speaks-for / delegation often start with a string.
        if self.cursor.current().kind is TokenKind.STRING:
            return self._parse_string_led_statement(start_tok, effect=effect, is_chc=is_chc)

        # Speaks_for predicate form.
        if self.cursor.match_value(TokenKind.IDENT, "speaks_for", "speaks-for") is not None:
            return self._parse_speaks_for_atom(start_tok)

        # Head atom, then optional rule neck.
        head = self._parse_atom(allow_negation=False)
        if self.cursor.match(TokenKind.RULE_NECK) is not None:
            body = self._parse_atom_list()
            end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_RULE)
            kind = RuleStatementKind.CHC if is_chc else RuleStatementKind.RULE
            role = RuleItemRole.CHC if is_chc else RuleItemRole.RULE
            if head.issuer:
                role = RuleItemRole.SECPAL_SAYS
            return RuleStatement(
                kind=kind,
                role=role,
                head=head,
                body=tuple(body),
                effect=effect,
                stratum=self.current_stratum,
                range=self.cursor.span(start_tok.range, end.range),
            )

        # Fact.
        end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_STATEMENT)
        role = RuleItemRole.SECPAL_SAYS if head.issuer else RuleItemRole.FACT
        return RuleStatement(
            kind=RuleStatementKind.FACT,
            role=role,
            head=head,
            effect=effect if effect is not RuleEffect.DERIVE else RuleEffect.DERIVE,
            stratum=self.current_stratum,
            range=self.cursor.span(start_tok.range, end.range),
        )

    def _parse_directive(self, start_tok: Token) -> RuleStatement:
        name_tok = self.cursor.expect(TokenKind.IDENT, code=CODE_MALFORMED_DIRECTIVE)
        name = name_tok.value.casefold()
        value = ""
        role = RuleItemRole.UNSUPPORTED
        if name in {"world", "world_policy"}:
            val_tok = self.cursor.expect(
                TokenKind.IDENT, TokenKind.STRING, code=CODE_MALFORMED_DIRECTIVE
            )
            value = val_tok.value
            alias = _WORLD_ALIASES.get(value.casefold())
            if alias is None:
                raise RuleError(
                    f"unknown world policy {value!r}",
                    code=CODE_MALFORMED_DIRECTIVE,
                    range=val_tok.range,
                    remediation=(
                        "Use closed_world, open_world, or default_negation"
                    ),
                )
            self.world_policy = alias
            role = RuleItemRole.WORLD
            value = alias.value
        elif name in {"priority", "precedence"}:
            val_tok = self.cursor.expect(
                TokenKind.IDENT, TokenKind.STRING, code=CODE_MALFORMED_DIRECTIVE
            )
            value = val_tok.value
            alias = _PRIORITY_ALIASES.get(value.casefold())
            if alias is None:
                raise RuleError(
                    f"unknown priority policy {value!r}",
                    code=CODE_MALFORMED_DIRECTIVE,
                    range=val_tok.range,
                )
            self.priority_policy = alias
            role = RuleItemRole.PRIORITY
            value = alias.value
        elif name == "profile":
            val_tok = self.cursor.expect(
                TokenKind.IDENT, TokenKind.STRING, code=CODE_MALFORMED_DIRECTIVE
            )
            value = val_tok.value
            alias = _PROFILE_ALIASES.get(value.casefold())
            if alias is None:
                raise RuleError(
                    f"unknown rule profile {value!r}",
                    code=CODE_PROFILE,
                    range=val_tok.range,
                )
            self.profile = alias
            role = RuleItemRole.PROFILE
            value = alias.value
        elif name == "trust":
            val_tok = self.cursor.expect(
                TokenKind.IDENT,
                TokenKind.STRING,
                TokenKind.VARIABLE,
                code=CODE_MALFORMED_DIRECTIVE,
            )
            value = val_tok.value
            self.trust_roots.append(value)
            role = RuleItemRole.TRUST
        elif name == "stratum":
            val_tok = self.cursor.expect(
                TokenKind.INTEGER, code=CODE_MALFORMED_DIRECTIVE
            )
            value = val_tok.value
            self.current_stratum = int(value)
            role = RuleItemRole.STRATUM
        else:
            # Unknown directive: retain as unsupported.
            if self.cursor.current().kind not in {TokenKind.DOT, TokenKind.EOF}:
                val_tok = self.cursor.advance()
                value = val_tok.value
            end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_DIRECTIVE)
            return RuleStatement(
                kind=RuleStatementKind.UNSUPPORTED,
                role=RuleItemRole.UNSUPPORTED,
                directive_name=name,
                directive_value=value,
                raw=self._raw_slice(start_tok.start, end.end),
                unsupported_reason=f"unknown directive @{name}",
                range=self.cursor.span(start_tok.range, end.range),
            )
        end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_DIRECTIVE)
        return RuleStatement(
            kind=RuleStatementKind.DIRECTIVE,
            role=role,
            directive_name=name,
            directive_value=value,
            stratum=self.current_stratum,
            range=self.cursor.span(start_tok.range, end.range),
        )

    def _parse_constraint(self, start_tok: Token) -> RuleStatement:
        kind_tok = self.cursor.expect(
            TokenKind.IDENT, TokenKind.STRING, code=CODE_MALFORMED_STATEMENT
        )
        value = kind_tok.value
        # Optional residual tokens until dot.
        while self.cursor.current().kind not in {TokenKind.DOT, TokenKind.EOF}:
            tok = self.cursor.advance()
            value = f"{value} {tok.value}"
        end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_STATEMENT)
        return RuleStatement(
            kind=RuleStatementKind.CONSTRAINT,
            role=RuleItemRole.CONSTRAINT,
            constraint_kind=kind_tok.value,
            directive_value=value.strip(),
            range=self.cursor.span(start_tok.range, end.range),
        )

    def _parse_authz_query(self, start_tok: Token) -> RuleStatement:
        principal = self._expect_name_or_string()
        can_tok = self.cursor.expect(TokenKind.IDENT, code=CODE_MALFORMED_QUERY)
        if can_tok.value.casefold() != "can":
            raise RuleError(
                f"expected 'can' in authorization query; got {can_tok.value!r}",
                code=CODE_MALFORMED_QUERY,
                range=can_tok.range,
            )
        action = self._expect_name_or_string()
        resource = ""
        if self.cursor.match_value(TokenKind.IDENT, "on") is not None:
            resource = self._expect_name_or_string()
        query_id = ""
        if self.cursor.match_value(TokenKind.IDENT, "id") is not None:
            if (
                self.cursor.current().kind is TokenKind.OP
                and self.cursor.current().value == "="
            ):
                self.cursor.advance()
            query_id = self._expect_name_or_string()
        end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_QUERY)
        head = RuleAtom(
            predicate="may",
            arguments=(
                RuleTerm(
                    RuleTermKind.CONSTANT, principal, sort=TermSortHint.PRINCIPAL
                ),
                RuleTerm(RuleTermKind.CONSTANT, action, sort=TermSortHint.ACTION),
                RuleTerm(
                    RuleTermKind.CONSTANT,
                    resource or "_",
                    sort=TermSortHint.RESOURCE,
                ),
            ),
            range=self.cursor.span(start_tok.range, end.range),
        )
        return RuleStatement(
            kind=RuleStatementKind.QUERY,
            role=RuleItemRole.QUERY,
            head=head,
            principal=principal,
            action=action,
            resource=resource,
            directive_value=query_id,
            range=self.cursor.span(start_tok.range, end.range),
        )

    def _parse_string_led_statement(
        self,
        start_tok: Token,
        *,
        effect: RuleEffect,
        is_chc: bool,
    ) -> RuleStatement:
        first = self.cursor.expect(TokenKind.STRING, code=CODE_MALFORMED_STATEMENT)
        # speaks-for
        if self.cursor.match_value(TokenKind.IDENT, "speaks-for", "speaks_for") is not None:
            subject = self._expect_name_or_string()
            end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_STATEMENT)
            return RuleStatement(
                kind=RuleStatementKind.SPEAKS_FOR,
                role=RuleItemRole.SPEAKS_FOR,
                principal=first.value,
                subject=subject,
                head=RuleAtom(
                    predicate="speaks_for",
                    arguments=(
                        RuleTerm(
                            RuleTermKind.STRING,
                            first.value,
                            sort=TermSortHint.PRINCIPAL,
                        ),
                        RuleTerm(
                            RuleTermKind.STRING,
                            subject,
                            sort=TermSortHint.PRINCIPAL,
                        ),
                    ),
                ),
                range=self.cursor.span(start_tok.range, end.range),
            )
        # says ...
        if self.cursor.match_value(TokenKind.IDENT, "says") is not None:
            # Delegation: "issuer" says "subject" can "action" on ...
            if self.cursor.current().kind is TokenKind.STRING and (
                self.cursor.peek(1).kind is TokenKind.IDENT
                and self.cursor.peek(1).value.casefold() == "can"
            ):
                return self._parse_delegation(start_tok, first.value)
            # Assertion / rule: "issuer" says atom [if body] [; effect=…] .
            head = self._parse_atom(allow_negation=False)
            head = RuleAtom(
                predicate=head.predicate,
                arguments=head.arguments,
                polarity=head.polarity,
                issuer=first.value,
                range=head.range,
            )
            body: tuple[RuleAtom, ...] = ()
            if self.cursor.match_value(TokenKind.IDENT, "if") is not None:
                body = tuple(self._parse_atom_list(stop_on_semi=True))
            # Optional trailing metadata: ; effect=allow; rule=id.
            rule_effect = effect
            while self.cursor.current().kind is TokenKind.OP and self.cursor.current().value == ";":
                self.cursor.advance()
                key = self.cursor.match(TokenKind.IDENT)
                if key is None:
                    break
                if self.cursor.current().kind is TokenKind.OP and self.cursor.current().value == "=":
                    self.cursor.advance()
                val = self.cursor.match(
                    TokenKind.IDENT, TokenKind.STRING, TokenKind.INTEGER
                )
                if key.value.casefold() == "effect" and val is not None:
                    try:
                        rule_effect = RuleEffect(val.value.casefold())
                    except ValueError:
                        pass
            end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_STATEMENT)
            if body:
                return RuleStatement(
                    kind=RuleStatementKind.RULE,
                    role=RuleItemRole.SECPAL_SAYS,
                    head=head,
                    body=body,
                    effect=rule_effect,
                    stratum=self.current_stratum,
                    principal=first.value,
                    range=self.cursor.span(start_tok.range, end.range),
                )
            return RuleStatement(
                kind=RuleStatementKind.FACT,
                role=RuleItemRole.SECPAL_SAYS,
                head=head,
                effect=rule_effect,
                stratum=self.current_stratum,
                principal=first.value,
                range=self.cursor.span(start_tok.range, end.range),
            )
        # Bare string as constant fact? Reject as malformed.
        raise RuleError(
            f"unexpected string-led statement starting with {first.value!r}",
            code=CODE_MALFORMED_STATEMENT,
            range=start_tok.range,
        )

    def _parse_delegation(self, start_tok: Token, issuer: str) -> RuleStatement:
        subject = self._expect_name_or_string()
        can_tok = self.cursor.expect(TokenKind.IDENT, code=CODE_MALFORMED_STATEMENT)
        if can_tok.value.casefold() != "can":
            raise RuleError(
                f"expected 'can' in delegation; got {can_tok.value!r}",
                code=CODE_MALFORMED_STATEMENT,
                range=can_tok.range,
            )
        action = self._expect_name_or_string()
        resource = ""
        if self.cursor.match_value(TokenKind.IDENT, "on") is not None:
            resource = self._expect_name_or_string()
        depth = 0
        if self.cursor.match_value(TokenKind.IDENT, "with") is not None:
            depth_key = self.cursor.expect(
                TokenKind.IDENT, code=CODE_MALFORMED_STATEMENT
            )
            if depth_key.value.casefold() not in {
                "delegation-depth",
                "delegation_depth",
                "depth",
            }:
                raise RuleError(
                    f"expected delegation-depth; got {depth_key.value!r}",
                    code=CODE_MALFORMED_STATEMENT,
                    range=depth_key.range,
                )
            depth_tok = self.cursor.expect(
                TokenKind.INTEGER, code=CODE_MALFORMED_STATEMENT
            )
            depth = int(depth_tok.value)
        # Optional id=...
        while self.cursor.current().kind is TokenKind.OP and self.cursor.current().value == ";":
            self.cursor.advance()
            while self.cursor.current().kind not in {
                TokenKind.DOT,
                TokenKind.EOF,
                TokenKind.OP,
            }:
                self.cursor.advance()
        end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_STATEMENT)
        return RuleStatement(
            kind=RuleStatementKind.DELEGATION,
            role=RuleItemRole.DELEGATION,
            principal=issuer,
            subject=subject,
            action=action,
            resource=resource,
            delegation_depth=depth,
            head=RuleAtom(
                predicate="can",
                arguments=(
                    RuleTerm(
                        RuleTermKind.CONSTANT, subject, sort=TermSortHint.PRINCIPAL
                    ),
                    RuleTerm(RuleTermKind.CONSTANT, action, sort=TermSortHint.ACTION),
                    RuleTerm(
                        RuleTermKind.CONSTANT,
                        resource or "_",
                        sort=TermSortHint.RESOURCE,
                    ),
                ),
                issuer=issuer,
            ),
            range=self.cursor.span(start_tok.range, end.range),
        )

    def _parse_speaks_for_atom(self, start_tok: Token) -> RuleStatement:
        self.cursor.expect(TokenKind.LPAREN, code=CODE_MALFORMED_ATOM)
        speaker = self._parse_term()
        self.cursor.expect(TokenKind.COMMA, code=CODE_MALFORMED_ATOM)
        subject = self._parse_term()
        self.cursor.expect(TokenKind.RPAREN, code=CODE_UNBALANCED)
        end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_STATEMENT)
        return RuleStatement(
            kind=RuleStatementKind.SPEAKS_FOR,
            role=RuleItemRole.SPEAKS_FOR,
            principal=speaker.name,
            subject=subject.name,
            head=RuleAtom(
                predicate="speaks_for",
                arguments=(
                    RuleTerm(
                        speaker.kind, speaker.name, sort=TermSortHint.PRINCIPAL
                    ),
                    RuleTerm(
                        subject.kind, subject.name, sort=TermSortHint.PRINCIPAL
                    ),
                ),
            ),
            range=self.cursor.span(start_tok.range, end.range),
        )

    def _parse_atom_list(self, *, stop_on_semi: bool = False) -> list[RuleAtom]:
        atoms: list[RuleAtom] = []
        if self.cursor.current().kind in {TokenKind.DOT, TokenKind.EOF}:
            return atoms
        if stop_on_semi and self.cursor.current().kind is TokenKind.OP and self.cursor.current().value == ";":
            return atoms
        atoms.append(self._parse_atom(allow_negation=True))
        while self.cursor.match(TokenKind.COMMA) is not None or (
            self.cursor.match_value(TokenKind.IDENT, "and") is not None
        ):
            if stop_on_semi and self.cursor.current().kind is TokenKind.OP and self.cursor.current().value == ";":
                break
            atoms.append(self._parse_atom(allow_negation=True))
        return atoms

    def _parse_atom(self, *, allow_negation: bool) -> RuleAtom:
        self.cursor.enter()
        try:
            start = self.cursor.current()
            polarity = RuleAtomPolarity.POSITIVE
            if allow_negation and self.cursor.match(TokenKind.NOT) is not None:
                polarity = RuleAtomPolarity.NEGATIVE
            pred_tok = self.cursor.expect(
                TokenKind.IDENT,
                TokenKind.STRING,
                code=CODE_MALFORMED_ATOM,
            )
            predicate = pred_tok.value
            args: list[RuleTerm] = []
            if self.cursor.match(TokenKind.LPAREN) is not None:
                if self.cursor.current().kind is not TokenKind.RPAREN:
                    args.append(self._parse_term())
                    while self.cursor.match(TokenKind.COMMA) is not None:
                        args.append(self._parse_term())
                close = self.cursor.expect(TokenKind.RPAREN, code=CODE_UNBALANCED)
                end_range = close.range
            else:
                end_range = pred_tok.range
            return RuleAtom(
                predicate=predicate,
                arguments=tuple(args),
                polarity=polarity,
                range=self.cursor.span(start.range, end_range),
            )
        finally:
            self.cursor.leave()

    def _parse_term(self) -> RuleTerm:
        self.cursor.enter()
        try:
            tok = self.cursor.current()
            sort = TermSortHint.ATOM
            sort_names = {s.value for s in TermSortHint}
            # Optional sort annotation: principal:Name or Name:principal
            if tok.kind is TokenKind.IDENT and tok.value.casefold() in sort_names:
                if self.cursor.peek(1).kind is TokenKind.COLON:
                    sort_name = tok.value.casefold()
                    self.cursor.advance()  # sort
                    self.cursor.advance()  # colon
                    sort = TermSortHint(sort_name)
                    tok = self.cursor.current()
            if tok.kind is TokenKind.VARIABLE:
                self.cursor.advance()
                kind = RuleTermKind.VARIABLE
                name = tok.value
            elif tok.kind is TokenKind.STRING:
                self.cursor.advance()
                kind = RuleTermKind.STRING
                name = tok.value
            elif tok.kind is TokenKind.INTEGER:
                self.cursor.advance()
                kind = RuleTermKind.NUMBER
                name = tok.value
            elif tok.kind is TokenKind.IDENT:
                self.cursor.advance()
                kind = RuleTermKind.CONSTANT
                name = tok.value
            else:
                raise RuleError(
                    f"expected term; got {tok.value!r}",
                    code=CODE_MALFORMED_TERM,
                    range=tok.range,
                )
            # Trailing :sort annotation (Name:principal / X:resource).
            if self.cursor.current().kind is TokenKind.COLON:
                peek = self.cursor.peek(1)
                if (
                    peek.kind is TokenKind.IDENT
                    and peek.value.casefold() in sort_names
                ):
                    self.cursor.advance()
                    sort_tok = self.cursor.advance()
                    sort = TermSortHint(sort_tok.value.casefold())
            return RuleTerm(kind, name, sort=sort, range=tok.range)
        finally:
            self.cursor.leave()

    def _expect_name_or_string(self) -> str:
        tok = self.cursor.expect(
            TokenKind.STRING,
            TokenKind.IDENT,
            TokenKind.VARIABLE,
            code=CODE_MALFORMED_STATEMENT,
        )
        return tok.value

    def _consume_unsupported(self, start_tok: Token, start_index: int) -> RuleStatement:
        # Consume until DOT or EOF.
        while self.cursor.current().kind not in {TokenKind.DOT, TokenKind.EOF}:
            self.cursor.advance()
        end = self.cursor.match(TokenKind.DOT)
        end_index = end.end if end is not None else self.cursor.current().end
        raw = self._raw_slice(start_index, end_index)
        reason = f"unsupported construct {start_tok.value!r}"
        return RuleStatement(
            kind=RuleStatementKind.UNSUPPORTED,
            role=RuleItemRole.UNSUPPORTED,
            raw=raw,
            unsupported_reason=reason,
            range=SourceRange(start_index, end_index),
        )


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class RulePrinter:
    """Deterministic rule printer for elaborated documents."""

    def print_document(self, document: RuleDocument) -> str:
        if not isinstance(document, RuleDocument):
            raise RuleError(
                "print_document requires a RuleDocument",
                code=CODE_MALFORMED_STATEMENT,
            )
        normalized = document.normalized()
        lines: list[str] = [
            f"% rules frontend {RULE_MODULE_VERSION}",
            f"% interface: {RULE_FRONTEND_INTERFACE}",
            f"% profile: {normalized.profile.value}",
        ]
        if normalized.world_policy is not None:
            lines.append(f"@world {normalized.world_policy.value}.")
        if normalized.priority_policy is not None:
            lines.append(f"@priority {normalized.priority_policy.value}.")
        lines.append(f"@profile {normalized.profile.value}.")
        for root in normalized.trust_roots:
            lines.append(f'@trust "{root}".')
        current_stratum: int | None = None
        for stmt in normalized.statements:
            if stmt.kind is RuleStatementKind.DIRECTIVE:
                # Already emitted world/priority/profile/trust from document fields.
                if stmt.role is RuleItemRole.STRATUM:
                    if current_stratum != stmt.stratum:
                        lines.append(f"@stratum {stmt.stratum}.")
                        current_stratum = stmt.stratum
                continue
            if (
                stmt.kind in {RuleStatementKind.RULE, RuleStatementKind.CHC, RuleStatementKind.FACT}
                and current_stratum != stmt.stratum
            ):
                lines.append(f"@stratum {stmt.stratum}.")
                current_stratum = stmt.stratum
            lines.append(self.print_statement(stmt))
        return "\n".join(lines) + "\n"

    def print_statement(self, statement: RuleStatement) -> str:
        if statement.kind is RuleStatementKind.UNSUPPORTED:
            raw = statement.raw.strip()
            if raw:
                if not raw.endswith("."):
                    raw = raw + "."
                return raw
            return f"% unsupported: {statement.unsupported_reason}."

        if statement.kind is RuleStatementKind.DIRECTIVE:
            return f"@{statement.directive_name} {statement.directive_value}."

        if statement.kind is RuleStatementKind.SPEAKS_FOR:
            return f'"{statement.principal}" speaks-for "{statement.subject}".'

        if statement.kind is RuleStatementKind.DELEGATION:
            resource = f' on "{statement.resource}"' if statement.resource else ""
            return (
                f'"{statement.principal}" says "{statement.subject}" can '
                f'"{statement.action}"{resource} with delegation-depth '
                f"{statement.delegation_depth}."
            )

        if statement.kind is RuleStatementKind.CONSTRAINT:
            return f"constraint {statement.directive_value}."

        if statement.kind is RuleStatementKind.QUERY:
            if statement.principal and statement.action:
                resource = (
                    f' on "{statement.resource}"' if statement.resource else ""
                )
                return (
                    f'query "{statement.principal}" can "{statement.action}"'
                    f"{resource}."
                )
            goals: list[str] = []
            if statement.head is not None:
                goals.append(self.print_atom(statement.head))
            goals.extend(self.print_atom(g) for g in statement.body)
            return f"?- {', '.join(goals)}."

        assert statement.head is not None
        prefix = ""
        if statement.effect is RuleEffect.ALLOW:
            prefix = "allow "
        elif statement.effect is RuleEffect.DENY:
            prefix = "deny "
        if statement.kind is RuleStatementKind.CHC:
            prefix = f"chc {prefix}"
        head = self.print_atom(statement.head)
        if statement.head.issuer:
            head = f'"{statement.head.issuer}" says {self.print_atom(statement.head, omit_issuer=True)}'
        if statement.kind is RuleStatementKind.FACT or not statement.body:
            if statement.head.issuer and statement.kind is RuleStatementKind.FACT:
                return f"{head}."
            return f"{prefix}{head}." if not statement.head.issuer else f"{head}."
        body = ", ".join(self.print_atom(a) for a in statement.body)
        if statement.head.issuer:
            return f"{head} if {body}."
        return f"{prefix}{head} :- {body}."

    def print_atom(self, atom: RuleAtom, *, omit_issuer: bool = False) -> str:
        del omit_issuer
        neg = "not " if atom.is_negative else ""
        if not atom.arguments:
            return f"{neg}{atom.predicate}"
        args = ", ".join(self.print_term(a) for a in atom.arguments)
        return f"{neg}{atom.predicate}({args})"

    def print_term(self, term: RuleTerm) -> str:
        if term.kind is RuleTermKind.STRING:
            escaped = term.name.replace("\\", "\\\\").replace('"', '\\"')
            base = f'"{escaped}"'
        else:
            base = term.name
        if term.sort is not TermSortHint.ATOM:
            return f"{base}:{term.sort.value}"
        return base


# ---------------------------------------------------------------------------
# Parse result / public parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleParseResult:
    """Typed result of a rule parse/elaborate attempt."""

    status: ParseStatus
    document: RuleDocument | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    schema_version: str = RULE_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = RULE_FRONTEND_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.document is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    @property
    def warnings(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(
            item
            for item in self.diagnostics
            if item.severity is DiagnosticSeverity.WARNING
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document": None if self.document is None else self.document.to_dict(),
            "interface": self.interface,
            "printed": self.printed,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


class RuleParser:
    """Notation parser for Datalog / Horn / CHC / SecPAL rules.

    Interface: ``RuleFrontend@1`` (``parser:local:rules`` implementation).
    """

    interface: ClassVar[str] = RULE_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = RULE_NOTATION_ID
    notation_version: ClassVar[str] = RULE_NOTATION_VERSION
    profile_id: ClassVar[str] = RULE_PROFILE_ID
    family_id: ClassVar[str] = RULE_FAMILY_ID

    def __init__(self, *, default_profile: RuleProfile | str = RuleProfile.HORN) -> None:
        self.printer = RulePrinter()
        self.default_profile = (
            default_profile
            if isinstance(default_profile, RuleProfile)
            else RuleProfile(default_profile)
        )

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:rules:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        validate: bool = True,
    ) -> RuleParseResult:
        del mode, document_id
        bounds = limits if limits is not None else ParseLimits()
        tokens, lex_diags = tokenize_rules(text, limits=bounds)
        if lex_diags and any(item.is_error for item in lex_diags):
            status = (
                ParseStatus.REJECTED
                if any(item.code == CODE_INPUT_LIMIT for item in lex_diags)
                else ParseStatus.FAILED
            )
            return RuleParseResult(status=status, diagnostics=lex_diags)
        if len(tokens) <= 1:
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty rule input; expected fact, rule, query, or directive",
                range=SourceRange(0, 0),
            )
            return RuleParseResult(status=ParseStatus.FAILED, diagnostics=(diag,))
        engine = _RuleParserEngine(
            tokens,
            source_text=text,
            limits=bounds,
            default_profile=self.default_profile,
        )
        try:
            document = engine.parse()
            document = document.normalized()
        except RuleError as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=error.range,
                remediation=error.remediation,
            )
            return RuleParseResult(
                status=ParseStatus.FAILED,
                diagnostics=tuple(lex_diags) + tuple(engine.diagnostics) + (diag,),
            )
        diagnostics = list(lex_diags) + list(engine.diagnostics)
        if validate:
            diagnostics.extend(validate_document(document))
        diagnostics_t = tuple(diagnostics)
        if any(item.is_error for item in diagnostics_t):
            return RuleParseResult(
                status=ParseStatus.FAILED,
                document=document,
                diagnostics=diagnostics_t,
            )
        return RuleParseResult(
            status=ParseStatus.OK,
            document=document,
            diagnostics=diagnostics_t,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> RuleDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise RuleParseError(
                result.errors[0].message if result.errors else "rule parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_STATEMENT,
            )
        return result.document


class RuleFrontend:
    """Facade for Datalog/Horn/CHC parse / normalize / print / CHC lowering.

    Interface: ``RuleFrontend@1``.
    """

    interface: ClassVar[str] = RULE_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = RULE_NOTATION_ID
    notation_version: ClassVar[str] = RULE_NOTATION_VERSION
    profile_id: ClassVar[str] = RULE_PROFILE_ID
    family_id: ClassVar[str] = RULE_FAMILY_ID

    def __init__(self, *, default_profile: RuleProfile | str = RuleProfile.HORN) -> None:
        self.parser = RuleParser(default_profile=default_profile)
        self.printer = self.parser.printer

    def parse_text(self, text: str, **kwargs: Any) -> RuleParseResult:
        return self.parser.parse_text(text, **kwargs)

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> RuleDocument:
        return self.parser.parse_text_or_raise(text, **kwargs)

    def print(self, document: RuleDocument) -> str:
        return self.printer.print_document(document)

    def normalize(self, document: RuleDocument) -> RuleDocument:
        if not isinstance(document, RuleDocument):
            raise RuleError(
                "normalize requires a RuleDocument",
                code=CODE_MALFORMED_STATEMENT,
            )
        return document.normalized()

    def elaborate(self, text: str, **kwargs: Any) -> RuleDocument:
        return self.parse_text_or_raise(text, **kwargs)

    def lower_to_chc(self, document: RuleDocument) -> CHCLoweringResult:
        return lower_to_chc(document)

    def round_trip(self, text: str, **kwargs: Any) -> RuleParseResult:
        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:rules:1") + ":rt",
            limits=kwargs.get("limits"),
            validate=kwargs.get("validate", True),
        )
        if not second.ok or second.document is None:
            return RuleParseResult(
                status=second.status,
                document=second.document,
                diagnostics=second.diagnostics,
                printed=printed,
            )
        if not documents_semantically_compatible(first.document, second.document):
            # Directives are re-emitted from document fields; structural
            # comparison may still succeed on rules/facts.  Soft-check predicates.
            if first.document.predicate_names != second.document.predicate_names:
                diag = _diag(
                    code=CODE_ROUND_TRIP,
                    message="parse/print/parse does not preserve rule structure",
                    range=SourceRange(0, 0),
                )
                return RuleParseResult(
                    status=ParseStatus.FAILED,
                    document=second.document,
                    diagnostics=second.diagnostics + (diag,),
                    printed=printed,
                )
        return RuleParseResult(
            status=ParseStatus.OK,
            document=second.document,
            diagnostics=second.diagnostics,
            printed=printed,
        )


class SecPALFrontend(RuleFrontend):
    """SecPAL / authorization profile specialization of the rule frontend.

    Interface: ``SecPALFrontend@1``.
    """

    interface: ClassVar[str] = SECPAL_FRONTEND_INTERFACE
    profile_id: ClassVar[str] = SECPAL_PROFILE_ID
    family_id: ClassVar[str] = SECPAL_FAMILY_ID

    def __init__(self) -> None:
        super().__init__(default_profile=RuleProfile.SECPAL)

    def parse_text(self, text: str, **kwargs: Any) -> RuleParseResult:
        # Ensure profile defaults to secpal when not declared in source.
        result = super().parse_text(text, **kwargs)
        if result.document is not None and result.document.profile is RuleProfile.HORN:
            # Inject secpal profile when source omitted @profile.
            if not any(
                s.role is RuleItemRole.PROFILE for s in result.document.statements
            ):
                doc = RuleDocument(
                    statements=result.document.statements,
                    profile=RuleProfile.SECPAL,
                    world_policy=result.document.world_policy,
                    priority_policy=result.document.priority_policy,
                    trust_roots=result.document.trust_roots,
                    profile_id=SECPAL_PROFILE_ID,
                    family_id=SECPAL_FAMILY_ID,
                    source_text=result.document.source_text,
                    metadata=result.document.metadata,
                )
                diagnostics = list(result.diagnostics)
                if kwargs.get("validate", True):
                    # Re-run authz-sensitive checks under secpal profile.
                    diagnostics = [
                        d
                        for d in diagnostics
                        if d.code != CODE_AMBIGUOUS_TERM
                    ]
                    diagnostics.extend(check_ambiguous_authz_terms(doc))
                    diagnostics.extend(check_world_and_priority(doc))
                diagnostics_t = tuple(diagnostics)
                if any(item.is_error for item in diagnostics_t):
                    return RuleParseResult(
                        status=ParseStatus.FAILED,
                        document=doc,
                        diagnostics=diagnostics_t,
                        printed=result.printed,
                    )
                return RuleParseResult(
                    status=ParseStatus.OK,
                    document=doc,
                    diagnostics=diagnostics_t,
                    printed=result.printed,
                )
        return result


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_rules(
    text: str,
    *,
    document_id: str = "doc:rules:1",
    limits: ParseLimits | None = None,
    validate: bool = True,
    profile: RuleProfile | str = RuleProfile.HORN,
) -> RuleParseResult:
    """Parse Datalog/Horn/CHC/SecPAL source into a typed result."""

    return RuleParser(default_profile=profile).parse_text(
        text, document_id=document_id, limits=limits, validate=validate
    )


def parse_secpal(
    text: str,
    *,
    document_id: str = "doc:secpal:1",
    limits: ParseLimits | None = None,
    validate: bool = True,
) -> RuleParseResult:
    """Parse SecPAL/authorization profile source."""

    return SecPALFrontend().parse_text(
        text, document_id=document_id, limits=limits, validate=validate
    )


def elaborate_rules(text: str, **kwargs: Any) -> RuleDocument:
    """Parse and return the elaborated document, or raise."""

    return RuleFrontend(
        default_profile=kwargs.pop("profile", RuleProfile.HORN)
    ).elaborate(text, **kwargs)


def print_rules(document: RuleDocument) -> str:
    """Print an elaborated rule document deterministically."""

    return RulePrinter().print_document(document)


def normalize_rules(document: RuleDocument) -> RuleDocument:
    """Return the deterministic normalization of *document*."""

    return RuleFrontend().normalize(document)


def parse_print_parse_rules(text: str, **kwargs: Any) -> RuleParseResult:
    """Parse → normalize → print → re-parse round trip."""

    return RuleFrontend(
        default_profile=kwargs.pop("profile", RuleProfile.HORN)
    ).round_trip(text, **kwargs)


__all__ = [
    "CHCClause",
    "CHCLoweringResult",
    "CODE_AMBIGUOUS_TERM",
    "CODE_CHC_LOWERING",
    "CODE_EMPTY_INPUT",
    "CODE_INPUT_LIMIT",
    "CODE_MISSING_PRIORITY",
    "CODE_MISSING_WORLD",
    "CODE_TOKEN_LIMIT",
    "CODE_UNSAFE_VARIABLE",
    "CODE_UNSTRATIFIED_NEGATION",
    "CODE_UNSUPPORTED_CONSTRUCT",
    "PriorityPolicyKind",
    "RULE_FAMILY_ID",
    "RULE_FRONTEND_INTERFACE",
    "RULE_MODULE_VERSION",
    "RULE_NOTATION_ID",
    "RULE_NOTATION_VERSION",
    "RULE_PROFILE_ID",
    "RuleAtom",
    "RuleAtomPolarity",
    "RuleDocument",
    "RuleEffect",
    "RuleError",
    "RuleFrontend",
    "RuleItemRole",
    "RuleParseError",
    "RuleParseResult",
    "RuleParser",
    "RulePrinter",
    "RuleProfile",
    "RuleStatement",
    "RuleStatementKind",
    "RuleTerm",
    "RuleTermKind",
    "SECPAL_FAMILY_ID",
    "SECPAL_FRONTEND_INTERFACE",
    "SECPAL_PROFILE_ID",
    "SecPALFrontend",
    "TermSortHint",
    "Token",
    "TokenKind",
    "UNSUPPORTED_MARKERS",
    "WorldPolicyKind",
    "check_ambiguous_authz_terms",
    "check_range_restriction",
    "check_stratification",
    "check_world_and_priority",
    "documents_semantically_compatible",
    "elaborate_rules",
    "lower_to_chc",
    "normalize_rules",
    "parse_print_parse_rules",
    "parse_rules",
    "parse_secpal",
    "print_rules",
    "tokenize_rules",
    "validate_document",
]
