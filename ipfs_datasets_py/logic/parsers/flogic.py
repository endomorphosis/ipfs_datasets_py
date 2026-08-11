"""Controlled F-logic and ErgoAI frontend.

Interfaces:

* ``FLogicFrontend@1`` (LFP-021) — parse/print/normalize for the declared
  frame-logic subset (frames, classes, methods, inheritance, rules, queries)
  with typed nodes instead of raw rule/query strings
* ``ErgoAIControlledSource@1`` — authority-bound controlled source view that
  never exceeds advisor/candidate authority and never executes ErgoAI

Controlled subset:

* class hierarchy ``Dog :: Animal.``
* method signatures ``Person[name => string, friends =>> Person].``
* instance membership ``rex : Dog.``
* frames ``rex[name -> "Rex", age -> 5].`` and set methods
  ``proj[member ->> {alice, bob}].``
* combined ``rex[name -> "Rex"] : Dog.``
* Horn rules ``head :- body1, body2.`` over molecules/atoms
* queries ``?- ?X : Dog.`` / ``?- ?X[name -> ?N].``
* simple atoms ``happy(rex).`` and variables ``?X``

Explicitly unsupported (retained + diagnosed, never silently dropped):

* ErgoAI module/context ``@`` operators
* transaction logic, aggregates, delay quantifiers
* defeasible ``~>``, classical ``\\neg`` / ``\\naf`` / ``\\if``
* load/export directives and absolute/URL includes
* promotion of parse results to theorem or solver authority

Execution remains lazy: this module never imports, installs, or runs ErgoAI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)
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

FLOGIC_FRONTEND_INTERFACE: Final = "FLogicFrontend@1"
ERGOAI_CONTROLLED_SOURCE_INTERFACE: Final = "ErgoAIControlledSource@1"
FLOGIC_NOTATION_ID: Final = "flogic"
FLOGIC_NOTATION_VERSION: Final = "1.0.0"
FLOGIC_PROFILE_ID: Final = "frame_core"
FLOGIC_FAMILY_ID: Final = "frame_logic"
FLOGIC_MODULE_VERSION: Final = "1.0.0"
FLOGIC_PARSE_RESULT_SCHEMA_VERSION: Final = "flogic-parse-result/v1"
FLOGIC_DOCUMENT_SCHEMA_VERSION: Final = "flogic-document/v1"
ERGOAI_SOURCE_SCHEMA_VERSION: Final = "ergoai-controlled-source/v1"
FLOGIC_PROVIDER_ID: Final = "ergoai"

# Stable namespaced diagnostic codes.
CODE_EMPTY_INPUT: Final = "flogic.empty_input"
CODE_INPUT_LIMIT: Final = "flogic.input_limit"
CODE_TOKEN_LIMIT: Final = "flogic.token_limit"
CODE_PARSE_DEPTH: Final = "flogic.parse_depth_exceeded"
CODE_UNBALANCED: Final = "flogic.unbalanced_delimiter"
CODE_UNEXPECTED_TOKEN: Final = "flogic.unexpected_token"
CODE_MALFORMED_STATEMENT: Final = "flogic.malformed_statement"
CODE_MALFORMED_MOLECULE: Final = "flogic.malformed_molecule"
CODE_MALFORMED_TERM: Final = "flogic.malformed_term"
CODE_MALFORMED_RULE: Final = "flogic.malformed_rule"
CODE_MALFORMED_QUERY: Final = "flogic.malformed_query"
CODE_TRAILING_INPUT: Final = "flogic.trailing_input"
CODE_UNTERMINATED_STRING: Final = "flogic.unterminated_string"
CODE_UNTERMINATED_COMMENT: Final = "flogic.unterminated_comment"
CODE_UNSUPPORTED_CONSTRUCT: Final = "flogic.unsupported_construct"
CODE_AUTHORITY: Final = "flogic.authority_ceiling"
CODE_ROUND_TRIP: Final = "flogic.round_trip_failed"
CODE_INVALID_LITERAL: Final = "flogic.invalid_literal"
CODE_LAZY_EXECUTION: Final = "flogic.lazy_execution"

_ALL_FLOGIC_CODES: Final[frozenset[str]] = frozenset(
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
    }
)

# ErgoAI / F-logic constructs outside the controlled subset.
UNSUPPORTED_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "@",
        "~>",
        "\\neg",
        "\\naf",
        "\\if",
        "\\unless",
        "\\while",
        "\\until",
        "avg{",
        "sum{",
        "max{",
        "min{",
        "count{",
        "setof{",
        "bagof{",
        "${",
        "%-",
        "%+",
        "#!",
    }
)

UNSUPPORTED_DIRECTIVES: Final[frozenset[str]] = frozenset(
    {
        "use_module",
        "export",
        "import",
        "include",
        "load",
        "compiler_options",
        "table",
        "index",
        "dynamic",
        "multifile",
    }
)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class FLogicTermKind(StrEnum):
    """Term node kinds in the controlled subset."""

    CONSTANT = "constant"
    VARIABLE = "variable"
    NUMBER = "number"
    STRING = "string"
    APPLICATION = "application"


class FLogicSpecKind(StrEnum):
    """Frame method specification kinds."""

    SCALAR_VALUE = "scalar_value"  # m -> v
    SET_VALUE = "set_value"  # m ->> {v1, v2}
    SCALAR_SIGNATURE = "scalar_signature"  # m => T
    SET_SIGNATURE = "set_signature"  # m =>> T


class FLogicStatementKind(StrEnum):
    """Top-level statement kinds."""

    FACT = "fact"
    RULE = "rule"
    QUERY = "query"
    UNSUPPORTED = "unsupported"


class FLogicItemRole(StrEnum):
    """Semantic role of a top-level item (evidence projection)."""

    CLASS = "class"
    FRAME = "frame"
    MEMBERSHIP = "membership"
    INHERITANCE = "inheritance"
    SIGNATURE = "signature"
    RULE = "rule"
    QUERY = "query"
    ATOM = "atom"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Errors / diagnostics
# ---------------------------------------------------------------------------


class FLogicError(SyntaxContractError):
    """Base class for F-logic frontend failures."""

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


class FLogicParseError(FLogicError):
    """Raised by raising helpers when a parse fails closed."""


class ErgoAIAuthorityError(FLogicError):
    """Raised when ErgoAI controlled source authority is violated."""


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
    diag_id = diagnostic_id or f"diag:flogic:{code.replace('.', '-')}"
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
    REAL = "real"
    STRING = "string"
    LPAREN = "lparen"
    RPAREN = "rparen"
    LBRACK = "lbrack"
    RBRACK = "rbrack"
    LBRACE = "lbrace"
    RBRACE = "rbrace"
    COMMA = "comma"
    DOT = "dot"
    COLON = "colon"
    COLON_COLON = "colon_colon"
    ARROW = "arrow"  # ->
    DOUBLE_ARROW = "double_arrow"  # ->>
    SIG_ARROW = "sig_arrow"  # =>
    SIG_DOUBLE_ARROW = "sig_double_arrow"  # =>>
    RULE_NECK = "rule_neck"  # :-
    QUERY = "query"  # ?-
    AT = "at"
    CUT = "cut"
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


def tokenize_flogic(
    text: str,
    *,
    limits: ParseLimits | None = None,
) -> tuple[tuple[Token, ...], tuple[SyntaxDiagnostic, ...]]:
    """Lex controlled F-logic / ErgoAI source into a bounded token stream.

    Line comments (``%`` … newline, ``//`` … newline) and block comments
    (``/* … */``) are discarded.  Resource limits fail closed.
    """

    bounds = limits if limits is not None else ParseLimits()
    diagnostics: list[SyntaxDiagnostic] = []
    if not isinstance(text, str):
        diagnostics.append(
            _diag(
                code=CODE_INVALID_LITERAL,
                message="F-logic input must be a string",
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
                    f"F-logic input exceeds max_input_bytes={bounds.max_input_bytes}"
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
                        f"F-logic token limit exceeded (max_tokens={bounds.max_tokens})"
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
        # Line comments: % … and // …
        if ch == "%":
            # %- / %+ are transaction markers — emit as OP so parser can retain.
            if i + 1 < n and raw[i + 1] in "-+":
                if not emit(TokenKind.OP, raw[i : i + 2], i, i + 2):
                    return (), tuple(diagnostics)
                i += 2
                continue
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

        start = i
        # Multi-character operators (longest first).
        if raw.startswith("=>>", i):
            if not emit(TokenKind.SIG_DOUBLE_ARROW, "=>>", start, i + 3):
                return (), tuple(diagnostics)
            i += 3
            continue
        if raw.startswith("->>", i):
            if not emit(TokenKind.DOUBLE_ARROW, "->>", start, i + 3):
                return (), tuple(diagnostics)
            i += 3
            continue
        if raw.startswith(":-", i):
            if not emit(TokenKind.RULE_NECK, ":-", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("?-", i):
            if not emit(TokenKind.QUERY, "?-", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("::", i):
            if not emit(TokenKind.COLON_COLON, "::", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("=>", i):
            if not emit(TokenKind.SIG_ARROW, "=>", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("->", i):
            if not emit(TokenKind.ARROW, "->", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("~>", i):
            if not emit(TokenKind.OP, "~>", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("${", i):
            if not emit(TokenKind.OP, "${", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
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
        if ch == "[":
            if not emit(TokenKind.LBRACK, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "]":
            if not emit(TokenKind.RBRACK, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "{":
            if not emit(TokenKind.LBRACE, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "}":
            if not emit(TokenKind.RBRACE, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ",":
            if not emit(TokenKind.COMMA, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ".":
            # Real number continuation handled below with digits.
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
            if not emit(TokenKind.CUT, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "\\" and i + 1 < n and raw[i + 1].isalpha():
            j = i + 1
            while j < n and (raw[j].isalnum() or raw[j] == "_"):
                j += 1
            if not emit(TokenKind.OP, raw[i:j], start, j):
                return (), tuple(diagnostics)
            i = j
            continue

        # Variable form ?Name (query ?- already handled above).
        if ch == "?" and i + 1 < n and (raw[i + 1].isalpha() or raw[i + 1] == "_"):
            j = i + 1
            while j < n and (raw[j].isalnum() or raw[j] == "_"):
                j += 1
            if not emit(TokenKind.VARIABLE, raw[i:j], start, j):
                return (), tuple(diagnostics)
            i = j
            continue

        if ch in {"?", "#", "~", "$", "+", "-", "*", "/", "=", "<", ">", "|", "&", "^"}:
            # Standalone operators retained for unsupported detection.
            if not emit(TokenKind.OP, ch, start, i + 1):
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

        if ch.isdigit() or (
            ch in "+-" and i + 1 < n and raw[i + 1].isdigit()
        ):
            j = i + 1
            while j < n and raw[j].isdigit():
                j += 1
            if j < n and raw[j] == "." and j + 1 < n and raw[j + 1].isdigit():
                j += 1
                while j < n and raw[j].isdigit():
                    j += 1
                if j < n and raw[j] in "eE":
                    k = j + 1
                    if k < n and raw[k] in "+-":
                        k += 1
                    if k < n and raw[k].isdigit():
                        j = k
                        while j < n and raw[j].isdigit():
                            j += 1
                value = raw[i:j]
                if not emit(TokenKind.REAL, value, start, j):
                    return (), tuple(diagnostics)
            else:
                value = raw[i:j]
                if not emit(TokenKind.INTEGER, value, start, j):
                    return (), tuple(diagnostics)
            i = j
            continue

        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (raw[j].isalnum() or raw[j] == "_"):
                j += 1
            value = raw[i:j]
            if not emit(TokenKind.IDENT, value, start, j):
                return (), tuple(diagnostics)
            i = j
            continue

        diagnostics.append(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"unexpected character {ch!r}",
                range=SourceRange(start, start + 1),
            )
        )
        return (), tuple(diagnostics)

    if not emit(TokenKind.EOF, "", n, n):
        return (), tuple(diagnostics)
    return tuple(tokens), tuple(diagnostics)


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FLogicTerm:
    """A term: constant, variable, number, string, or application."""

    kind: FLogicTermKind | str
    name: str = ""
    arguments: tuple["FLogicTerm", ...] = ()
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, FLogicTermKind)
            else FLogicTermKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "arguments", tuple(self.arguments))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "arguments": [item.to_dict() for item in self.arguments],
            "kind": self.kind.value,
            "name": self.name,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (
            self.kind.value,
            self.name,
            tuple(arg.structural_key() for arg in self.arguments),
        )

    def free_variables(self) -> tuple[str, ...]:
        if self.kind is FLogicTermKind.VARIABLE:
            return (self.name,)
        found: list[str] = []
        seen: set[str] = set()
        for arg in self.arguments:
            for name in arg.free_variables():
                if name not in seen:
                    seen.add(name)
                    found.append(name)
        return tuple(found)


@dataclass(frozen=True, slots=True)
class FLogicMethodSpec:
    """One method specification inside a frame molecule."""

    kind: FLogicSpecKind | str
    method: FLogicTerm
    values: tuple[FLogicTerm, ...] = ()
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, FLogicSpecKind)
            else FLogicSpecKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.method, FLogicTerm):
            raise FLogicError(
                "method specification requires an FLogicTerm method",
                code=CODE_MALFORMED_MOLECULE,
            )
        object.__setattr__(self, "values", tuple(self.values))

    @property
    def method_name(self) -> str:
        return self.method.name

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "method": self.method.to_dict(),
            "values": [item.to_dict() for item in self.values],
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (
            self.kind.value,
            self.method.structural_key(),
            tuple(v.structural_key() for v in self.values),
        )

    def normalized(self) -> "FLogicMethodSpec":
        """Deterministic method-spec form (sorted set values)."""

        if self.kind is FLogicSpecKind.SET_VALUE and len(self.values) > 1:
            ordered = tuple(
                sorted(self.values, key=lambda item: item.structural_key())
            )
            return FLogicMethodSpec(
                kind=self.kind,
                method=self.method,
                values=ordered,
                range=self.range,
            )
        return self


@dataclass(frozen=True, slots=True)
class FLogicMolecule:
    """An F-logic molecule: object with optional frame specs and inheritance.

    Covers:

    * ``object``
    * ``object : Class``
    * ``Class :: Super``
    * ``object[specs]``
    * ``object[specs] : Class``
    * ``predicate(args)`` (atom form: empty specs, no inheritance)
    """

    object: FLogicTerm
    specs: tuple[FLogicMethodSpec, ...] = ()
    isa: FLogicTerm | None = None
    subclass_of: FLogicTerm | None = None
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.object, FLogicTerm):
            raise FLogicError(
                "molecule object must be an FLogicTerm",
                code=CODE_MALFORMED_MOLECULE,
            )
        object.__setattr__(self, "specs", tuple(self.specs))
        if self.isa is not None and self.subclass_of is not None:
            raise FLogicError(
                "molecule cannot declare both : and :: inheritance",
                code=CODE_MALFORMED_MOLECULE,
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "isa": None if self.isa is None else self.isa.to_dict(),
            "object": self.object.to_dict(),
            "specs": [item.to_dict() for item in self.specs],
            "subclass_of": (
                None if self.subclass_of is None else self.subclass_of.to_dict()
            ),
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (
            self.object.structural_key(),
            tuple(spec.structural_key() for spec in self.specs),
            None if self.isa is None else self.isa.structural_key(),
            None if self.subclass_of is None else self.subclass_of.structural_key(),
        )

    def normalized(self) -> "FLogicMolecule":
        """Sort method specs by method name for deterministic identity."""

        specs = tuple(
            sorted(
                (spec.normalized() for spec in self.specs),
                key=lambda item: (item.method_name, item.kind.value, item.structural_key()),
            )
        )
        return FLogicMolecule(
            object=self.object,
            specs=specs,
            isa=self.isa,
            subclass_of=self.subclass_of,
            range=self.range,
        )

    def free_variables(self) -> tuple[str, ...]:
        found: list[str] = []
        seen: set[str] = set()

        def add(names: Sequence[str]) -> None:
            for name in names:
                if name not in seen:
                    seen.add(name)
                    found.append(name)

        add(self.object.free_variables())
        for spec in self.specs:
            add(spec.method.free_variables())
            for value in spec.values:
                add(value.free_variables())
        if self.isa is not None:
            add(self.isa.free_variables())
        if self.subclass_of is not None:
            add(self.subclass_of.free_variables())
        return tuple(found)

    def infer_role(self) -> FLogicItemRole:
        if self.subclass_of is not None:
            return FLogicItemRole.INHERITANCE
        if self.specs and all(
            spec.kind
            in {FLogicSpecKind.SCALAR_SIGNATURE, FLogicSpecKind.SET_SIGNATURE}
            for spec in self.specs
        ):
            return FLogicItemRole.SIGNATURE
        if self.specs:
            return FLogicItemRole.FRAME
        if self.isa is not None:
            return FLogicItemRole.MEMBERSHIP
        if self.object.kind is FLogicTermKind.APPLICATION:
            return FLogicItemRole.ATOM
        return FLogicItemRole.CLASS


@dataclass(frozen=True, slots=True)
class FLogicStatement:
    """One top-level F-logic statement (fact, rule, query, or unsupported)."""

    kind: FLogicStatementKind | str
    head: FLogicMolecule | None = None
    body: tuple[FLogicMolecule, ...] = ()
    role: FLogicItemRole | str = FLogicItemRole.ATOM
    raw: str = ""
    unsupported_reason: str = ""
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, FLogicStatementKind)
            else FLogicStatementKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        role = (
            self.role
            if isinstance(self.role, FLogicItemRole)
            else FLogicItemRole(str(self.role))
        )
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "body", tuple(self.body))
        object.__setattr__(self, "raw", str(self.raw or ""))
        object.__setattr__(self, "unsupported_reason", str(self.unsupported_reason or ""))
        if kind is FLogicStatementKind.UNSUPPORTED:
            if not self.raw and not self.unsupported_reason:
                raise FLogicError(
                    "unsupported statement requires raw source or reason",
                    code=CODE_UNSUPPORTED_CONSTRUCT,
                )
        elif kind is FLogicStatementKind.FACT:
            if self.head is None:
                raise FLogicError(
                    "fact statement requires a head molecule",
                    code=CODE_MALFORMED_STATEMENT,
                )
        elif kind is FLogicStatementKind.RULE:
            if self.head is None or not self.body:
                raise FLogicError(
                    "rule statement requires head and non-empty body",
                    code=CODE_MALFORMED_RULE,
                )
        elif kind is FLogicStatementKind.QUERY:
            if self.head is None and not self.body:
                raise FLogicError(
                    "query statement requires a goal",
                    code=CODE_MALFORMED_QUERY,
                )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "body": [item.to_dict() for item in self.body],
            "head": None if self.head is None else self.head.to_dict(),
            "kind": self.kind.value,
            "raw": self.raw,
            "role": self.role.value,
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
            self.unsupported_reason,
            self.raw.strip(),
        )

    def normalized(self) -> "FLogicStatement":
        head = None if self.head is None else self.head.normalized()
        body = tuple(item.normalized() for item in self.body)
        return FLogicStatement(
            kind=self.kind,
            head=head,
            body=body,
            role=self.role,
            raw=self.raw,
            unsupported_reason=self.unsupported_reason,
            range=self.range,
        )


@dataclass(frozen=True, slots=True)
class FLogicDocument:
    """Elaborated controlled F-logic program.

    Identity-relevant fields include statements (frames, classes, methods,
    inheritance, rules, queries) and retained unsupported constructs.
    Printing and normalization are deterministic for the admitted subset.
    """

    statements: tuple[FLogicStatement, ...] = ()
    profile_id: str = FLOGIC_PROFILE_ID
    notation_id: str = FLOGIC_NOTATION_ID
    notation_version: str = FLOGIC_NOTATION_VERSION
    family_id: str = FLOGIC_FAMILY_ID
    schema_version: str = FLOGIC_DOCUMENT_SCHEMA_VERSION
    source_text: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "statements", tuple(self.statements))
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise FLogicError(
                "document metadata must be immutable JSON data",
                code=CODE_MALFORMED_STATEMENT,
            ) from error
        if self.schema_version != FLOGIC_DOCUMENT_SCHEMA_VERSION:
            raise FLogicError(
                f"unsupported document schema {self.schema_version!r}",
                code=CODE_MALFORMED_STATEMENT,
            )

    @property
    def interface(self) -> str:
        return FLOGIC_FRONTEND_INTERFACE

    @property
    def facts(self) -> tuple[FLogicStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is FLogicStatementKind.FACT
        )

    @property
    def rules(self) -> tuple[FLogicStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is FLogicStatementKind.RULE
        )

    @property
    def queries(self) -> tuple[FLogicStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is FLogicStatementKind.QUERY
        )

    @property
    def unsupported(self) -> tuple[FLogicStatement, ...]:
        return tuple(
            item
            for item in self.statements
            if item.kind is FLogicStatementKind.UNSUPPORTED
        )

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(item.role.value for item in self.statements)

    @property
    def class_names(self) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()

        def add(name: str) -> None:
            if name and name not in seen and not name.startswith("?"):
                seen.add(name)
                names.append(name)

        for stmt in self.statements:
            if stmt.head is None:
                continue
            mol = stmt.head
            if mol.subclass_of is not None:
                add(mol.object.name)
                add(mol.subclass_of.name)
            if mol.isa is not None:
                add(mol.isa.name)
            if any(
                s.kind
                in {FLogicSpecKind.SCALAR_SIGNATURE, FLogicSpecKind.SET_SIGNATURE}
                for s in mol.specs
            ):
                add(mol.object.name)
        return tuple(names)

    @property
    def frame_object_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        seen: set[str] = set()
        for stmt in self.facts:
            if stmt.head is None:
                continue
            if stmt.role is FLogicItemRole.FRAME or (
                stmt.head.specs
                and any(
                    s.kind
                    in {FLogicSpecKind.SCALAR_VALUE, FLogicSpecKind.SET_VALUE}
                    for s in stmt.head.specs
                )
            ):
                name = stmt.head.object.name
                if name and name not in seen:
                    seen.add(name)
                    ids.append(name)
        return tuple(ids)

    @property
    def method_names(self) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()
        for stmt in self.statements:
            if stmt.head is None:
                continue
            for spec in stmt.head.specs:
                name = spec.method_name
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
            for body in stmt.body:
                for spec in body.specs:
                    name = spec.method_name
                    if name and name not in seen:
                        seen.add(name)
                        names.append(name)
        return tuple(names)

    @property
    def has_unsupported(self) -> bool:
        return any(item.kind is FLogicStatementKind.UNSUPPORTED for item in self.statements)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "frame_object_ids": list(self.frame_object_ids),
            "interface": FLOGIC_FRONTEND_INTERFACE,
            "method_names": list(self.method_names),
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "profile_id": self.profile_id,
            "roles": list(self.roles),
            "schema_version": self.schema_version,
            "statements": [item.to_dict() for item in self.statements],
            "unsupported_count": len(self.unsupported),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["metadata"] = self.metadata.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return tuple(item.structural_key() for item in self.statements)

    def normalized(self) -> "FLogicDocument":
        """Return a deterministically normalized document (idempotent)."""

        statements = tuple(item.normalized() for item in self.statements)
        return FLogicDocument(
            statements=statements,
            profile_id=self.profile_id,
            notation_id=self.notation_id,
            notation_version=self.notation_version,
            family_id=self.family_id,
            schema_version=self.schema_version,
            source_text=self.source_text,
            metadata=self.metadata,
        )


def documents_semantically_compatible(
    left: FLogicDocument, right: FLogicDocument
) -> bool:
    """Return True when two documents share the same structural semantics."""

    if not isinstance(left, FLogicDocument) or not isinstance(right, FLogicDocument):
        return False
    return left.normalized().structural_key() == right.normalized().structural_key()


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
        if token.kind is kind and token.value in values:
            return self.advance()
        return None

    def expect(self, *kinds: TokenKind, code: str = CODE_UNEXPECTED_TOKEN) -> Token:
        token = self.match(*kinds)
        if token is not None:
            return token
        current = self.current()
        expected = " or ".join(k.value for k in kinds)
        raise FLogicError(
            f"expected {expected}; got {current.value!r} ({current.kind.value})",
            code=code,
            range=current.range,
        )

    def enter(self) -> None:
        self.depth += 1
        if self.depth > self.limits.max_depth:
            raise FLogicError(
                f"parse depth {self.depth} exceeds limit {self.limits.max_depth}",
                code=CODE_PARSE_DEPTH,
                range=self.current().range,
            )

    def leave(self) -> None:
        self.depth = max(0, self.depth - 1)

    def span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        return SourceRange(start.start, end.end)


class _FLogicParserEngine:
    """Recursive-descent parser for the controlled F-logic subset."""

    def __init__(
        self,
        tokens: Sequence[Token],
        *,
        source_text: str = "",
        limits: ParseLimits | None = None,
    ) -> None:
        self.cursor = _TokenCursor(
            tokens, limits if limits is not None else ParseLimits()
        )
        self.source_text = source_text
        self.diagnostics: list[SyntaxDiagnostic] = []
        self.statements: list[FLogicStatement] = []

    def parse(self) -> FLogicDocument:
        if self.cursor.is_eof():
            raise FLogicError(
                "empty F-logic input; expected frame, class, rule, or query",
                code=CODE_EMPTY_INPUT,
                range=SourceRange(0, 0),
            )
        while not self.cursor.is_eof():
            stmt = self._parse_statement()
            self.statements.append(stmt)
        return FLogicDocument(
            statements=tuple(self.statements),
            source_text=self.source_text,
            metadata=FrozenMap(
                {
                    "authority_ceiling": ToolchainAuthorityCeiling.ADVISORY.value,
                    "provider_id": FLOGIC_PROVIDER_ID,
                    "role": ToolRole.ADVISOR.value,
                    "lazy": True,
                }
            ),
        )

    def _raw_slice(self, start: int, end: int) -> str:
        if not self.source_text:
            return ""
        return self.source_text[start:end]

    def _parse_statement(self) -> FLogicStatement:
        start_tok = self.cursor.current()
        start_index = start_tok.start

        # Query: ?- goals.
        if self.cursor.match(TokenKind.QUERY) is not None:
            goals = self._parse_goal_list()
            end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_QUERY)
            head = goals[0] if goals else None
            body = tuple(goals[1:]) if len(goals) > 1 else ()
            if head is None:
                raise FLogicError(
                    "query requires at least one goal",
                    code=CODE_MALFORMED_QUERY,
                    range=start_tok.range,
                )
            return FLogicStatement(
                kind=FLogicStatementKind.QUERY,
                head=head,
                body=body,
                role=FLogicItemRole.QUERY,
                range=self.cursor.span(start_tok.range, end.range),
            )

        # Detect unsupported constructs before committing to controlled parse.
        if self._lookahead_unsupported():
            return self._consume_unsupported(start_tok, start_index)

        # Head molecule, then optional rule neck.
        head = self._parse_molecule()
        if self.cursor.match(TokenKind.RULE_NECK) is not None:
            # Directive form: :- use_module(...). without a head molecule that
            # is actually empty — handled via unsupported when head is bare
            # and directive ident follows.  Here head exists so this is a rule.
            body = self._parse_goal_list()
            if not body:
                raise FLogicError(
                    "rule body must not be empty",
                    code=CODE_MALFORMED_RULE,
                    range=self.cursor.current().range,
                )
            # Body may contain unsupported markers.
            if self._body_has_unsupported(body):
                # Still accept as rule if body molecules parsed; markers
                # would have failed molecule parse.  No-op.
                pass
            end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_RULE)
            return FLogicStatement(
                kind=FLogicStatementKind.RULE,
                head=head,
                body=tuple(body),
                role=FLogicItemRole.RULE,
                range=self.cursor.span(start_tok.range, end.range),
            )

        end = self.cursor.expect(TokenKind.DOT, code=CODE_MALFORMED_STATEMENT)
        role = head.infer_role()
        return FLogicStatement(
            kind=FLogicStatementKind.FACT,
            head=head,
            role=role,
            range=self.cursor.span(start_tok.range, end.range),
        )

    def _token_is_unsupported_marker(self, tok: Token) -> bool:
        if tok.kind is TokenKind.AT:
            return True
        if tok.kind is TokenKind.CUT:
            return True
        if tok.kind is TokenKind.OP:
            if tok.value.startswith("\\"):
                return True
            if tok.value in UNSUPPORTED_MARKERS or tok.value in {
                "%-",
                "%+",
                "~>",
                "${",
                "|",  # aggregate / set-comprehension bar
            }:
                return True
        return False

    def _lookahead_unsupported(self) -> bool:
        """True when the next statement is outside the controlled subset.

        Scans through the next top-level statement (until ``.``) so mid-statement
        markers such as ``p ~> q.`` are retained rather than hard-failing.
        """

        tokens = self.cursor.tokens
        i = self.cursor.index
        if i >= len(tokens):
            return False
        first = tokens[i]
        # Headless directives are never part of the controlled subset.
        if first.kind is TokenKind.RULE_NECK:
            return True

        depth_paren = 0
        depth_brack = 0
        depth_brace = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.kind is TokenKind.EOF:
                break
            if self._token_is_unsupported_marker(tok):
                return True
            if tok.kind is TokenKind.IDENT and tok.value in {
                "avg",
                "sum",
                "max",
                "min",
                "count",
                "setof",
                "bagof",
            }:
                nxt = tokens[i + 1] if i + 1 < len(tokens) else tok
                if nxt.kind is TokenKind.LBRACE:
                    return True
            if tok.kind is TokenKind.LPAREN:
                depth_paren += 1
            elif tok.kind is TokenKind.RPAREN:
                depth_paren = max(0, depth_paren - 1)
            elif tok.kind is TokenKind.LBRACK:
                depth_brack += 1
            elif tok.kind is TokenKind.RBRACK:
                depth_brack = max(0, depth_brack - 1)
            elif tok.kind is TokenKind.LBRACE:
                depth_brace += 1
            elif tok.kind is TokenKind.RBRACE:
                depth_brace = max(0, depth_brace - 1)
            elif (
                tok.kind is TokenKind.DOT
                and depth_paren == 0
                and depth_brack == 0
                and depth_brace == 0
            ):
                break
            i += 1
        return False

    def _consume_unsupported(
        self, start_tok: Token, start_index: int
    ) -> FLogicStatement:
        """Retain an unsupported statement through its terminating '.'."""

        reason_parts: list[str] = []
        tok = self.cursor.current()
        if tok.kind is TokenKind.AT:
            reason_parts.append("ErgoAI @ context/module operator")
        elif tok.kind is TokenKind.CUT:
            reason_parts.append("Prolog cut (!)")
        elif tok.kind is TokenKind.OP:
            reason_parts.append(f"unsupported operator {tok.value!r}")
        elif tok.kind is TokenKind.RULE_NECK:
            reason_parts.append("headless directive / unsupported directive")
        elif tok.kind is TokenKind.IDENT:
            reason_parts.append(f"unsupported construct {tok.value!r}")
        else:
            reason_parts.append(f"unsupported token {tok.value!r}")

        depth_paren = 0
        depth_brack = 0
        depth_brace = 0
        end_tok = tok
        while not self.cursor.is_eof():
            cur = self.cursor.current()
            if cur.kind is TokenKind.LPAREN:
                depth_paren += 1
            elif cur.kind is TokenKind.RPAREN:
                depth_paren = max(0, depth_paren - 1)
            elif cur.kind is TokenKind.LBRACK:
                depth_brack += 1
            elif cur.kind is TokenKind.RBRACK:
                depth_brack = max(0, depth_brack - 1)
            elif cur.kind is TokenKind.LBRACE:
                depth_brace += 1
            elif cur.kind is TokenKind.RBRACE:
                depth_brace = max(0, depth_brace - 1)
            elif (
                cur.kind is TokenKind.DOT
                and depth_paren == 0
                and depth_brack == 0
                and depth_brace == 0
            ):
                end_tok = self.cursor.advance()
                break
            end_tok = self.cursor.advance()
        else:
            raise FLogicError(
                "unterminated unsupported construct; expected '.'",
                code=CODE_UNSUPPORTED_CONSTRUCT,
                range=start_tok.range,
            )

        raw = self._raw_slice(start_index, end_tok.end).strip()
        reason = "; ".join(reason_parts)
        span = self.cursor.span(start_tok.range, end_tok.range)
        self.diagnostics.append(
            _diag(
                code=CODE_UNSUPPORTED_CONSTRUCT,
                message=(
                    f"unsupported ErgoAI/F-logic construct retained: {reason}"
                ),
                range=span,
                severity=DiagnosticSeverity.WARNING,
                remediation=(
                    "Use the controlled frame/class/method/rule/query subset, "
                    "or keep this construct as retained unsupported evidence"
                ),
                metadata={
                    "raw": raw,
                    "reason": reason,
                    "retained": True,
                },
                diagnostic_id=(
                    f"diag:flogic:unsupported:{len(self.diagnostics) + 1}"
                ),
            )
        )
        return FLogicStatement(
            kind=FLogicStatementKind.UNSUPPORTED,
            role=FLogicItemRole.UNSUPPORTED,
            raw=raw,
            unsupported_reason=reason,
            range=span,
        )

    def _body_has_unsupported(self, body: Sequence[FLogicMolecule]) -> bool:
        del body
        return False

    def _parse_goal_list(self) -> list[FLogicMolecule]:
        goals: list[FLogicMolecule] = []
        goals.append(self._parse_molecule())
        while self.cursor.match(TokenKind.COMMA) is not None:
            goals.append(self._parse_molecule())
        return goals

    def _parse_molecule(self) -> FLogicMolecule:
        self.cursor.enter()
        try:
            start = self.cursor.current()
            obj = self._parse_term()

            specs: tuple[FLogicMethodSpec, ...] = ()
            if self.cursor.match(TokenKind.LBRACK) is not None:
                specs = tuple(self._parse_spec_list())
                self.cursor.expect(TokenKind.RBRACK, code=CODE_UNBALANCED)

            isa: FLogicTerm | None = None
            subclass_of: FLogicTerm | None = None
            if self.cursor.match(TokenKind.COLON_COLON) is not None:
                subclass_of = self._parse_term()
            elif self.cursor.match(TokenKind.COLON) is not None:
                isa = self._parse_term()

            # Prefer last consumed token range for the molecule span.
            if isa is not None and isa.range is not None:
                end_range = isa.range
            elif subclass_of is not None and subclass_of.range is not None:
                end_range = subclass_of.range
            elif specs and specs[-1].range is not None:
                end_range = specs[-1].range
            elif obj.range is not None:
                end_range = obj.range
            else:
                end_range = start.range
            return FLogicMolecule(
                object=obj,
                specs=specs,
                isa=isa,
                subclass_of=subclass_of,
                range=self.cursor.span(start.range, end_range),
            )
        finally:
            self.cursor.leave()

    def _parse_spec_list(self) -> list[FLogicMethodSpec]:
        if self.cursor.current().kind is TokenKind.RBRACK:
            return []
        specs = [self._parse_spec()]
        while self.cursor.match(TokenKind.COMMA) is not None:
            specs.append(self._parse_spec())
        return specs

    def _parse_spec(self) -> FLogicMethodSpec:
        start = self.cursor.current()
        method = self._parse_term()
        if self.cursor.match(TokenKind.DOUBLE_ARROW) is not None:
            values = self._parse_set_values()
            end = values[-1].range if values and values[-1].range else start.range
            return FLogicMethodSpec(
                kind=FLogicSpecKind.SET_VALUE,
                method=method,
                values=tuple(values),
                range=self.cursor.span(start.range, end),
            )
        if self.cursor.match(TokenKind.ARROW) is not None:
            value = self._parse_term()
            end = value.range or start.range
            return FLogicMethodSpec(
                kind=FLogicSpecKind.SCALAR_VALUE,
                method=method,
                values=(value,),
                range=self.cursor.span(start.range, end),
            )
        if self.cursor.match(TokenKind.SIG_DOUBLE_ARROW) is not None:
            typ = self._parse_term()
            end = typ.range or start.range
            return FLogicMethodSpec(
                kind=FLogicSpecKind.SET_SIGNATURE,
                method=method,
                values=(typ,),
                range=self.cursor.span(start.range, end),
            )
        if self.cursor.match(TokenKind.SIG_ARROW) is not None:
            typ = self._parse_term()
            end = typ.range or start.range
            return FLogicMethodSpec(
                kind=FLogicSpecKind.SCALAR_SIGNATURE,
                method=method,
                values=(typ,),
                range=self.cursor.span(start.range, end),
            )
        raise FLogicError(
            f"expected method arrow after {method.name!r}; "
            f"got {self.cursor.current().value!r}",
            code=CODE_MALFORMED_MOLECULE,
            range=self.cursor.current().range,
        )

    def _parse_set_values(self) -> list[FLogicTerm]:
        if self.cursor.match(TokenKind.LBRACE) is None:
            # Single value without braces is accepted as a one-element set.
            return [self._parse_term()]
        if self.cursor.match(TokenKind.RBRACE) is not None:
            return []
        values = [self._parse_term()]
        while self.cursor.match(TokenKind.COMMA) is not None:
            values.append(self._parse_term())
        self.cursor.expect(TokenKind.RBRACE, code=CODE_UNBALANCED)
        return values

    def _parse_term(self) -> FLogicTerm:
        self.cursor.enter()
        try:
            tok = self.cursor.current()
            if tok.kind is TokenKind.VARIABLE:
                self.cursor.advance()
                return FLogicTerm(
                    kind=FLogicTermKind.VARIABLE,
                    name=tok.value,
                    range=tok.range,
                )
            if tok.kind is TokenKind.INTEGER:
                self.cursor.advance()
                return FLogicTerm(
                    kind=FLogicTermKind.NUMBER,
                    name=tok.value,
                    range=tok.range,
                )
            if tok.kind is TokenKind.REAL:
                self.cursor.advance()
                return FLogicTerm(
                    kind=FLogicTermKind.NUMBER,
                    name=tok.value,
                    range=tok.range,
                )
            if tok.kind is TokenKind.STRING:
                self.cursor.advance()
                return FLogicTerm(
                    kind=FLogicTermKind.STRING,
                    name=tok.value,
                    range=tok.range,
                )
            if tok.kind is TokenKind.IDENT:
                self.cursor.advance()
                name = tok.value
                if self.cursor.match(TokenKind.LPAREN) is not None:
                    args: list[FLogicTerm] = []
                    if self.cursor.current().kind is not TokenKind.RPAREN:
                        args.append(self._parse_term())
                        while self.cursor.match(TokenKind.COMMA) is not None:
                            args.append(self._parse_term())
                    close = self.cursor.expect(
                        TokenKind.RPAREN, code=CODE_UNBALANCED
                    )
                    return FLogicTerm(
                        kind=FLogicTermKind.APPLICATION,
                        name=name,
                        arguments=tuple(args),
                        range=self.cursor.span(tok.range, close.range),
                    )
                return FLogicTerm(
                    kind=FLogicTermKind.CONSTANT,
                    name=name,
                    range=tok.range,
                )
            # Parenthesized term.
            if self.cursor.match(TokenKind.LPAREN) is not None:
                inner = self._parse_term()
                close = self.cursor.expect(TokenKind.RPAREN, code=CODE_UNBALANCED)
                return FLogicTerm(
                    kind=inner.kind,
                    name=inner.name,
                    arguments=inner.arguments,
                    range=self.cursor.span(tok.range, close.range),
                )
            raise FLogicError(
                f"expected term; got {tok.value!r}",
                code=CODE_MALFORMED_TERM,
                range=tok.range,
            )
        finally:
            self.cursor.leave()


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class FLogicPrinter:
    """Deterministic F-logic printer for elaborated documents."""

    def print_document(self, document: FLogicDocument) -> str:
        if not isinstance(document, FLogicDocument):
            raise FLogicError(
                "print_document requires an FLogicDocument",
                code=CODE_MALFORMED_STATEMENT,
            )
        normalized = document.normalized()
        lines: list[str] = [
            f"% F-logic frontend {FLOGIC_MODULE_VERSION}",
            f"% interface: {FLOGIC_FRONTEND_INTERFACE}",
            f"% profile: {normalized.profile_id}",
            f"% authority: advisor/candidate (never theorem)",
        ]
        for stmt in normalized.statements:
            lines.append(self.print_statement(stmt))
        return "\n".join(lines) + "\n"

    def print_statement(self, statement: FLogicStatement) -> str:
        if statement.kind is FLogicStatementKind.UNSUPPORTED:
            raw = statement.raw.strip()
            if raw:
                if not raw.endswith("."):
                    raw = raw + "."
                return raw
            return f"% unsupported: {statement.unsupported_reason}."

        if statement.kind is FLogicStatementKind.QUERY:
            goals: list[FLogicMolecule] = []
            if statement.head is not None:
                goals.append(statement.head)
            goals.extend(statement.body)
            body = ", ".join(self.print_molecule(g) for g in goals)
            return f"?- {body}."

        if statement.kind is FLogicStatementKind.RULE:
            assert statement.head is not None
            head = self.print_molecule(statement.head)
            body = ", ".join(self.print_molecule(g) for g in statement.body)
            return f"{head} :- {body}."

        assert statement.head is not None
        return f"{self.print_molecule(statement.head)}."

    def print_molecule(self, molecule: FLogicMolecule) -> str:
        mol = molecule.normalized()
        text = self.print_term(mol.object)
        if mol.specs:
            specs = ", ".join(self.print_spec(s) for s in mol.specs)
            text = f"{text}[{specs}]"
        if mol.subclass_of is not None:
            text = f"{text} :: {self.print_term(mol.subclass_of)}"
        elif mol.isa is not None:
            text = f"{text} : {self.print_term(mol.isa)}"
        return text

    def print_spec(self, spec: FLogicMethodSpec) -> str:
        method = self.print_term(spec.method)
        if spec.kind is FLogicSpecKind.SCALAR_VALUE:
            return f"{method} -> {self.print_term(spec.values[0])}"
        if spec.kind is FLogicSpecKind.SET_VALUE:
            ordered = spec.normalized().values
            inner = ", ".join(self.print_term(v) for v in ordered)
            return f"{method} ->> {{{inner}}}"
        if spec.kind is FLogicSpecKind.SCALAR_SIGNATURE:
            return f"{method} => {self.print_term(spec.values[0])}"
        if spec.kind is FLogicSpecKind.SET_SIGNATURE:
            return f"{method} =>> {self.print_term(spec.values[0])}"
        raise FLogicError(
            f"unsupported method spec kind {spec.kind!r}",
            code=CODE_MALFORMED_MOLECULE,
        )

    def print_term(self, term: FLogicTerm) -> str:
        if term.kind is FLogicTermKind.STRING:
            escaped = term.name.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if term.kind is FLogicTermKind.APPLICATION:
            args = ", ".join(self.print_term(a) for a in term.arguments)
            return f"{term.name}({args})"
        return term.name


# ---------------------------------------------------------------------------
# Parse result / public parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FLogicParseResult:
    """Typed result of an F-logic parse/elaborate attempt."""

    status: ParseStatus
    document: FLogicDocument | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    schema_version: str = FLOGIC_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = FLOGIC_FRONTEND_INTERFACE

    @property
    def ok(self) -> bool:
        # Unsupported constructs are retained as warnings; parse may still OK.
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


class FLogicParser:
    """Notation parser for controlled F-logic / ErgoAI source.

    Interface: ``FLogicFrontend@1`` (``parser:local:flogic`` implementation).

    Never imports or executes ErgoAI.
    """

    interface: ClassVar[str] = FLOGIC_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = FLOGIC_NOTATION_ID
    notation_version: ClassVar[str] = FLOGIC_NOTATION_VERSION
    profile_id: ClassVar[str] = FLOGIC_PROFILE_ID
    family_id: ClassVar[str] = FLOGIC_FAMILY_ID

    def __init__(self) -> None:
        self.printer = FLogicPrinter()

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:flogic:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> FLogicParseResult:
        del mode  # strict-only controlled subset
        del document_id
        bounds = limits if limits is not None else ParseLimits()
        tokens, lex_diags = tokenize_flogic(text, limits=bounds)
        if lex_diags and any(item.is_error for item in lex_diags):
            status = (
                ParseStatus.REJECTED
                if any(item.code == CODE_INPUT_LIMIT for item in lex_diags)
                else ParseStatus.FAILED
            )
            return FLogicParseResult(status=status, diagnostics=lex_diags)
        if len(tokens) <= 1:
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty F-logic input; expected frame, class, rule, or query",
                range=SourceRange(0, 0),
            )
            return FLogicParseResult(status=ParseStatus.FAILED, diagnostics=(diag,))
        engine = _FLogicParserEngine(tokens, source_text=text, limits=bounds)
        try:
            document = engine.parse()
            document = document.normalized()
        except FLogicError as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=error.range,
                remediation=error.remediation,
            )
            return FLogicParseResult(
                status=ParseStatus.FAILED,
                diagnostics=tuple(lex_diags) + tuple(engine.diagnostics) + (diag,),
            )
        diagnostics = tuple(lex_diags) + tuple(engine.diagnostics)
        # Presence of only warnings → OK; any error → FAILED.
        if any(item.is_error for item in diagnostics):
            return FLogicParseResult(
                status=ParseStatus.FAILED,
                document=document,
                diagnostics=diagnostics,
            )
        return FLogicParseResult(
            status=ParseStatus.OK,
            document=document,
            diagnostics=diagnostics,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> FLogicDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise FLogicParseError(
                result.errors[0].message if result.errors else "F-logic parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_STATEMENT,
            )
        return result.document


class FLogicFrontend:
    """Facade for F-logic parse / normalize / print.

    Interface: ``FLogicFrontend@1``.

    Execution remains lazy: no ErgoAI install, import, or process launch.
    """

    interface: ClassVar[str] = FLOGIC_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = FLOGIC_NOTATION_ID
    notation_version: ClassVar[str] = FLOGIC_NOTATION_VERSION
    profile_id: ClassVar[str] = FLOGIC_PROFILE_ID
    family_id: ClassVar[str] = FLOGIC_FAMILY_ID
    authority: ClassVar[ResultAuthority] = ResultAuthority.CANDIDATE
    role: ClassVar[ToolRole] = ToolRole.ADVISOR
    authority_ceiling: ClassVar[ToolchainAuthorityCeiling] = (
        ToolchainAuthorityCeiling.ADVISORY
    )

    def __init__(self) -> None:
        self.parser = FLogicParser()
        self.printer = self.parser.printer

    def parse_text(self, text: str, **kwargs: Any) -> FLogicParseResult:
        return self.parser.parse_text(text, **kwargs)

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> FLogicDocument:
        return self.parser.parse_text_or_raise(text, **kwargs)

    def print(self, document: FLogicDocument) -> str:
        return self.printer.print_document(document)

    def normalize(self, document: FLogicDocument) -> FLogicDocument:
        if not isinstance(document, FLogicDocument):
            raise FLogicError(
                "normalize requires an FLogicDocument",
                code=CODE_MALFORMED_STATEMENT,
            )
        return document.normalized()

    def elaborate(self, text: str, **kwargs: Any) -> FLogicDocument:
        return self.parse_text_or_raise(text, **kwargs)

    def as_controlled_source(self, document: FLogicDocument) -> "ErgoAIControlledSource":
        return ErgoAIControlledSource.from_document(document)

    def round_trip(self, text: str, **kwargs: Any) -> FLogicParseResult:
        """Parse → normalize → print → re-parse; requires structural preservation."""

        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:flogic:1") + ":rt",
            limits=kwargs.get("limits"),
        )
        if not second.ok or second.document is None:
            return second
        if not documents_semantically_compatible(first.document, second.document):
            diag = _diag(
                code=CODE_ROUND_TRIP,
                message="parse/print/parse does not preserve F-logic structure",
                range=SourceRange(0, 0),
            )
            return FLogicParseResult(
                status=ParseStatus.FAILED,
                document=second.document,
                diagnostics=second.diagnostics + (diag,),
                printed=printed,
            )
        return FLogicParseResult(
            status=ParseStatus.OK,
            document=second.document,
            diagnostics=second.diagnostics,
            printed=printed,
        )

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        """Hard-fail: frontend never executes ErgoAI (lazy by contract)."""

        raise FLogicError(
            "FLogicFrontend does not execute ErgoAI; execution remains lazy "
            "and authority is advisor/candidate only",
            code=CODE_LAZY_EXECUTION,
            remediation=(
                "Use a separately certified ErgoAI advisor lane for execution; "
                "parsing never launches the vendor runtime"
            ),
        )


# ---------------------------------------------------------------------------
# ErgoAI controlled source (advisor/candidate authority)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ErgoAIControlledSource:
    """Authority-bound controlled ErgoAI/F-logic source view.

    Interface: ``ErgoAIControlledSource@1``.

    Hard-wired to advisor role and advisory/candidate authority ceiling.
    Never trusted; never elevates to theorem or solver authority.  Does not
    import or run ErgoAI.
    """

    document: FLogicDocument
    authority: ResultAuthority = ResultAuthority.CANDIDATE
    status: ResultStatus = ResultStatus.CANDIDATE
    role: ToolRole = ToolRole.ADVISOR
    authority_ceiling: ToolchainAuthorityCeiling = ToolchainAuthorityCeiling.ADVISORY
    trusted: bool = False
    provider_id: str = FLOGIC_PROVIDER_ID
    schema_version: str = ERGOAI_SOURCE_SCHEMA_VERSION
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if not isinstance(self.document, FLogicDocument):
            raise ErgoAIAuthorityError(
                "ErgoAIControlledSource requires an FLogicDocument",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "trusted", False)
        authority = (
            self.authority
            if isinstance(self.authority, ResultAuthority)
            else ResultAuthority(str(self.authority))
        )
        if authority is not ResultAuthority.CANDIDATE:
            raise ErgoAIAuthorityError(
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
            raise ErgoAIAuthorityError(
                "ErgoAI controlled source must use ResultStatus.CANDIDATE; "
                f"got {status!r}",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "status", ResultStatus.CANDIDATE)
        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role is not ToolRole.ADVISOR:
            raise ErgoAIAuthorityError(
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
            raise ErgoAIAuthorityError(
                "ErgoAI authority ceiling must be advisory or candidate; "
                f"got {ceiling!r}",
                code=CODE_AUTHORITY,
            )
        object.__setattr__(self, "authority_ceiling", ceiling)
        if role_can_satisfy_certified_authority(role, ceiling):
            raise ErgoAIAuthorityError(
                "ErgoAI controlled source cannot satisfy certified authority",
                code=CODE_AUTHORITY,
            )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise ErgoAIAuthorityError(
                "controlled source metadata must be immutable JSON data",
                code=CODE_AUTHORITY,
            ) from error
        if self.schema_version != ERGOAI_SOURCE_SCHEMA_VERSION:
            raise ErgoAIAuthorityError(
                f"unsupported controlled source schema {self.schema_version!r}",
                code=CODE_AUTHORITY,
            )

    @property
    def interface(self) -> str:
        return ERGOAI_CONTROLLED_SOURCE_INTERFACE

    @property
    def is_trusted(self) -> bool:
        return False

    @property
    def can_certify(self) -> bool:
        return False

    @classmethod
    def from_document(cls, document: FLogicDocument) -> "ErgoAIControlledSource":
        return cls(
            document=document,
            metadata=FrozenMap(
                {
                    "lazy": True,
                    "provider_id": FLOGIC_PROVIDER_ID,
                    "untrusted": True,
                    "authority_ceiling": ToolchainAuthorityCeiling.ADVISORY.value,
                    "role": ToolRole.ADVISOR.value,
                }
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "authority_ceiling": self.authority_ceiling.value,
            "can_certify": False,
            "document": self.document.to_dict(),
            "interface": self.interface,
            "metadata": self.metadata.to_dict(),
            "provider_id": self.provider_id,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "trusted": False,
        }

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        """Hard-fail: controlled source never launches ErgoAI."""

        raise FLogicError(
            "ErgoAIControlledSource does not execute the ErgoAI runtime",
            code=CODE_LAZY_EXECUTION,
            remediation="Advisor execution is owned by a separate certified lane",
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_flogic(
    text: str,
    *,
    document_id: str = "doc:flogic:1",
    limits: ParseLimits | None = None,
) -> FLogicParseResult:
    """Parse controlled F-logic / ErgoAI source into a typed result."""

    return FLogicParser().parse_text(text, document_id=document_id, limits=limits)


def elaborate_flogic(text: str, **kwargs: Any) -> FLogicDocument:
    """Parse and return the elaborated document, or raise."""

    return FLogicFrontend().elaborate(text, **kwargs)


def print_flogic(document: FLogicDocument) -> str:
    """Print an elaborated F-logic document deterministically."""

    return FLogicPrinter().print_document(document)


def normalize_flogic(document: FLogicDocument) -> FLogicDocument:
    """Return the deterministic normalization of *document*."""

    return FLogicFrontend().normalize(document)


def parse_print_parse_flogic(text: str, **kwargs: Any) -> FLogicParseResult:
    """Parse → normalize → print → re-parse round trip."""

    return FLogicFrontend().round_trip(text, **kwargs)


def controlled_source_from_text(text: str, **kwargs: Any) -> ErgoAIControlledSource:
    """Parse text and wrap as an advisor/candidate controlled source."""

    document = elaborate_flogic(text, **kwargs)
    return ErgoAIControlledSource.from_document(document)


__all__ = [
    "CODE_AUTHORITY",
    "CODE_EMPTY_INPUT",
    "CODE_INPUT_LIMIT",
    "CODE_INVALID_LITERAL",
    "CODE_LAZY_EXECUTION",
    "CODE_MALFORMED_MOLECULE",
    "CODE_MALFORMED_QUERY",
    "CODE_MALFORMED_RULE",
    "CODE_MALFORMED_STATEMENT",
    "CODE_MALFORMED_TERM",
    "CODE_PARSE_DEPTH",
    "CODE_ROUND_TRIP",
    "CODE_TOKEN_LIMIT",
    "CODE_TRAILING_INPUT",
    "CODE_UNBALANCED",
    "CODE_UNEXPECTED_TOKEN",
    "CODE_UNSUPPORTED_CONSTRUCT",
    "CODE_UNTERMINATED_COMMENT",
    "CODE_UNTERMINATED_STRING",
    "ERGOAI_CONTROLLED_SOURCE_INTERFACE",
    "FLOGIC_FAMILY_ID",
    "FLOGIC_FRONTEND_INTERFACE",
    "FLOGIC_MODULE_VERSION",
    "FLOGIC_NOTATION_ID",
    "FLOGIC_NOTATION_VERSION",
    "FLOGIC_PROFILE_ID",
    "FLOGIC_PROVIDER_ID",
    "UNSUPPORTED_DIRECTIVES",
    "UNSUPPORTED_MARKERS",
    "ErgoAIAuthorityError",
    "ErgoAIControlledSource",
    "FLogicDocument",
    "FLogicError",
    "FLogicFrontend",
    "FLogicItemRole",
    "FLogicMethodSpec",
    "FLogicMolecule",
    "FLogicParseError",
    "FLogicParseResult",
    "FLogicParser",
    "FLogicPrinter",
    "FLogicSpecKind",
    "FLogicStatement",
    "FLogicStatementKind",
    "FLogicTerm",
    "FLogicTermKind",
    "Token",
    "TokenKind",
    "controlled_source_from_text",
    "documents_semantically_compatible",
    "elaborate_flogic",
    "normalize_flogic",
    "parse_flogic",
    "parse_print_parse_flogic",
    "print_flogic",
    "tokenize_flogic",
]
