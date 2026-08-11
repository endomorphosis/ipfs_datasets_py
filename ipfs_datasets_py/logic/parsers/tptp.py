"""TPTP CNF/FOF/TFF reader/printer and TSTP candidate frontend.

Interfaces:

* ``TPTPFrontend@1`` (LFP-019) — controlled TPTP problem-file parse/print for
  CNF, FOF, and TFF annotated formulas with typed roles, symbols, formulas,
  includes, annotations, and source maps
* ``TSTPCandidateFrontend@1`` — TSTP/SZS proof-candidate normalization that
  never exceeds candidate authority (untrusted until reconstructed)

Controlled subset:

* annotated formulas ``cnf`` / ``fof`` / ``tff`` with standard formula roles
* type declarations in TFF (``$tType``, ``$o``, ``$i``, function/predicate
  signatures with ``*`` / ``>``)
* quantifiers ``!`` / ``?``, connectives ``~ & | => <=>``, equality ``=`` /
  ``!=``, truth constants ``$true`` / ``$false``
* safe relative ``include(...)`` paths only (path traversal rejected)
* well-formed optional annotations (source + useful_info)
* TSTP inference annotations and SZS status lines as **candidate** evidence

Explicitly unsupported (fail closed):

* THF / TFX / TXF higher-order dialects (deferred)
* absolute / parent-directory / URL include paths
* malformed annotations
* promotion of TSTP candidates to theorem authority
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final, Iterator

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.syntax_core.contracts import (
    DiagnosticSeverity,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

TPTP_FRONTEND_INTERFACE: Final = "TPTPFrontend@1"
TSTP_CANDIDATE_FRONTEND_INTERFACE: Final = "TSTPCandidateFrontend@1"
TPTP_NOTATION_ID: Final = "tptp"
TPTP_NOTATION_VERSION: Final = "7.0.0"
TPTP_PROFILE_ID: Final = "fof"
TPTP_FAMILY_ID: Final = "first_order"
TPTP_MODULE_VERSION: Final = "1.0.0"
TPTP_PARSE_RESULT_SCHEMA_VERSION: Final = "tptp-parse-result/v1"
TPTP_DOCUMENT_SCHEMA_VERSION: Final = "tptp-document/v1"
TSTP_CANDIDATE_SCHEMA_VERSION: Final = "tstp-candidate/v1"
TSTP_PARSE_RESULT_SCHEMA_VERSION: Final = "tstp-parse-result/v1"

# Stable namespaced diagnostic codes.
CODE_EMPTY_INPUT: Final = "tptp.empty_input"
CODE_INPUT_LIMIT: Final = "tptp.input_limit"
CODE_TOKEN_LIMIT: Final = "tptp.token_limit"
CODE_PARSE_DEPTH: Final = "tptp.parse_depth_exceeded"
CODE_UNBALANCED: Final = "tptp.unbalanced_delimiter"
CODE_UNEXPECTED_TOKEN: Final = "tptp.unexpected_token"
CODE_MALFORMED_ANNOTATED: Final = "tptp.malformed_annotated_formula"
CODE_MALFORMED_FORMULA: Final = "tptp.malformed_formula"
CODE_MALFORMED_ANNOTATION: Final = "tptp.malformed_annotation"
CODE_MALFORMED_INCLUDE: Final = "tptp.malformed_include"
CODE_UNSAFE_INCLUDE: Final = "tptp.unsafe_include"
CODE_PATH_TRAVERSAL: Final = "tptp.path_traversal"
CODE_UNSUPPORTED_LANGUAGE: Final = "tptp.unsupported_language"
CODE_UNSUPPORTED_THF: Final = "tptp.unsupported_thf"
CODE_UNKNOWN_ROLE: Final = "tptp.unknown_role"
CODE_UNSUPPORTED_ROLE: Final = "tptp.unsupported_role"
CODE_TRAILING_INPUT: Final = "tptp.trailing_input"
CODE_INVALID_LITERAL: Final = "tptp.invalid_literal"
CODE_UNTERMINATED_STRING: Final = "tptp.unterminated_string"
CODE_UNTERMINATED_COMMENT: Final = "tptp.unterminated_comment"
CODE_CANDIDATE_AUTHORITY: Final = "tptp.candidate_authority"
CODE_MALFORMED_SZS: Final = "tptp.malformed_szs"
CODE_ROUND_TRIP: Final = "tptp.round_trip_failed"

_ALL_TPTP_CODES: Final[frozenset[str]] = frozenset(
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
    }
)


# ---------------------------------------------------------------------------
# Vocabulary (declared subset)
# ---------------------------------------------------------------------------


class TPTPLanguage(StrEnum):
    """Admitted TPTP formula languages for the controlled frontend."""

    CNF = "cnf"
    FOF = "fof"
    TFF = "tff"


SUPPORTED_LANGUAGES: Final[frozenset[str]] = frozenset(
    item.value for item in TPTPLanguage
)

# Explicit higher-order / extended dialects (fail closed until implemented).
UNSUPPORTED_LANGUAGES: Final[frozenset[str]] = frozenset(
    {
        "thf",
        "tfx",
        "txf",
        "tcf",
    }
)

THF_LANGUAGES: Final[frozenset[str]] = frozenset({"thf", "tfx"})


class TPTPRole(StrEnum):
    """Standard TPTP formula roles admitted by the controlled subset."""

    AXIOM = "axiom"
    HYPOTHESIS = "hypothesis"
    DEFINITION = "definition"
    ASSUMPTION = "assumption"
    LEMMA = "lemma"
    THEOREM = "theorem"
    COROLLARY = "corollary"
    CONJECTURE = "conjecture"
    NEGATED_CONJECTURE = "negated_conjecture"
    PLAIN = "plain"
    TYPE = "type"
    FI_DOMAIN = "fi_domain"
    FI_FUNCTORS = "fi_functors"
    FI_PREDICATES = "fi_predicates"
    UNKNOWN = "unknown"


SUPPORTED_ROLES: Final[frozenset[str]] = frozenset(item.value for item in TPTPRole)

# Roles known in the TPTP standard but rejected by this controlled subset.
UNSUPPORTED_ROLES: Final[frozenset[str]] = frozenset(
    {
        "interpretation",
        "logic",
    }
)


class TPTPFormulaKind(StrEnum):
    """Structural formula / term node kinds."""

    TRUE = "true"
    FALSE = "false"
    ATOM = "atom"
    NOT = "not"
    AND = "and"
    OR = "or"
    IMPLIES = "implies"
    IFF = "iff"
    EQ = "eq"
    NEQ = "neq"
    FORALL = "forall"
    EXISTS = "exists"
    VAR = "var"
    FUN = "fun"
    TYPE_DECL = "type_decl"
    CLAUSE = "clause"


class TPTPItemKind(StrEnum):
    """Top-level document item kinds."""

    ANNOTATED = "annotated"
    INCLUDE = "include"


class SZSStatus(StrEnum):
    """Reviewed SZS statuses understood as TSTP candidate metadata."""

    THEOREM = "Theorem"
    UNSATISFIABLE = "Unsatisfiable"
    CONTRADICTORY_AXIOMS = "ContradictoryAxioms"
    SATISFIABLE = "Satisfiable"
    COUNTER_SATISFIABLE = "CounterSatisfiable"
    UNKNOWN = "Unknown"
    GAVE_UP = "GaveUp"
    TIMEOUT = "Timeout"
    RESOURCE_OUT = "ResourceOut"


SUPPORTED_SZS_STATUSES: Final[frozenset[str]] = frozenset(
    item.value for item in SZSStatus
)

# System sorts always available in TFF.
_SYSTEM_SORTS: Final[frozenset[str]] = frozenset({"$tType", "$o", "$i", "$int", "$real", "$rat"})

_IDENT_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DOLLAR_IDENT_RE: Final = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$")
_DOLLAR_DOLLAR_IDENT_RE: Final = re.compile(r"^\$\$[A-Za-z_][A-Za-z0-9_]*$")
_INTEGER_RE: Final = re.compile(r"^[+-]?\d+$")
_REAL_RE: Final = re.compile(r"^[+-]?\d+\.\d+(?:[eE][+-]?\d+)?$")
_SAFE_INCLUDE_RE: Final = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+/-]*[A-Za-z0-9]$|^[A-Za-z0-9][A-Za-z0-9._+-]*$"
)
_SZS_STATUS_RE: Final = re.compile(
    r"^[ \t]*[%#][ \t]*SZS[ \t]+status[ \t]+([A-Za-z][A-Za-z0-9_]*)"
    r"(?:[ \t]+for[ \t]+[^\r\n]+)?[ \t]*$",
    re.MULTILINE,
)
_SZS_OUTPUT_START_RE: Final = re.compile(
    r"^[ \t]*[%#][ \t]*SZS[ \t]+output[ \t]+start[ \t]+(\S+)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
_SZS_OUTPUT_END_RE: Final = re.compile(
    r"^[ \t]*[%#][ \t]*SZS[ \t]+output[ \t]+end[ \t]+(\S+)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)

_CONNECTIVES: Final[frozenset[str]] = frozenset({"&", "|", "=>", "<=>", "=", "!="})
_UNARY_OPS: Final[frozenset[str]] = frozenset({"~", "!", "?"})


# ---------------------------------------------------------------------------
# Errors / diagnostics
# ---------------------------------------------------------------------------


class TPTPError(SyntaxContractError):
    """Base class for TPTP frontend failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_MALFORMED_FORMULA,
        path: str = "",
        remediation: str = "",
        range: SourceRange | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.remediation = remediation
        self.range = range
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "remediation": self.remediation,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload


class TPTPParseError(TPTPError):
    """Raised by raising helpers when a parse fails closed."""


class TSTPError(TPTPError):
    """Raised for TSTP candidate frontend failures."""


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
    diag_id = diagnostic_id or f"diag:tptp:{code.replace('.', '-')}"
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
    DOLLAR_IDENT = "dollar_ident"
    VAR = "var"
    INTEGER = "integer"
    REAL = "real"
    STRING = "string"
    DISTINCT = "distinct"
    LPAREN = "lparen"
    RPAREN = "rparen"
    LBRACK = "lbrack"
    RBRACK = "rbrack"
    COMMA = "comma"
    COLON = "colon"
    DOT = "dot"
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


def _is_var_name(name: str) -> bool:
    return bool(name) and name[0].isupper()


def tokenize_tptp(
    text: str,
    *,
    limits: ParseLimits | None = None,
) -> tuple[tuple[Token, ...], tuple[SyntaxDiagnostic, ...]]:
    """Lex TPTP/TSTP source into a bounded token stream.

    Comments (``%`` line, ``/* ... */`` block) are discarded.  Resource limits
    fail closed with stable diagnostic codes.
    """

    bounds = limits if limits is not None else ParseLimits()
    diagnostics: list[SyntaxDiagnostic] = []
    if not isinstance(text, str):
        diagnostics.append(
            _diag(
                code=CODE_INVALID_LITERAL,
                message="TPTP input must be a string",
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
                    f"TPTP input exceeds max_input_bytes={bounds.max_input_bytes}"
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
                    message=f"TPTP token limit exceeded (max_tokens={bounds.max_tokens})",
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
        if ch == "%":
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
        if ch == ",":
            if not emit(TokenKind.COMMA, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ":":
            if not emit(TokenKind.COLON, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == ".":
            if not emit(TokenKind.DOT, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "'":
            i += 1
            chars: list[str] = []
            while i < n:
                if raw[i] == "\\" and i + 1 < n:
                    chars.append(raw[i + 1])
                    i += 2
                    continue
                if raw[i] == "'":
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
                        message="unterminated single-quoted string",
                        range=SourceRange(start, n),
                    )
                )
                return (), tuple(diagnostics)
            continue
        if ch == '"':
            i += 1
            chars = []
            while i < n:
                if raw[i] == "\\" and i + 1 < n:
                    chars.append(raw[i + 1])
                    i += 2
                    continue
                if raw[i] == '"':
                    i += 1
                    if not emit(TokenKind.DISTINCT, "".join(chars), start, i):
                        return (), tuple(diagnostics)
                    break
                chars.append(raw[i])
                i += 1
            else:
                diagnostics.append(
                    _diag(
                        code=CODE_UNTERMINATED_STRING,
                        message="unterminated double-quoted distinct object",
                        range=SourceRange(start, n),
                    )
                )
                return (), tuple(diagnostics)
            continue
        # Multi-character operators first.
        if raw.startswith("<=>", i):
            if not emit(TokenKind.OP, "<=>", start, i + 3):
                return (), tuple(diagnostics)
            i += 3
            continue
        if raw.startswith("=>", i):
            if not emit(TokenKind.OP, "=>", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if raw.startswith("!=", i):
            if not emit(TokenKind.OP, "!=", start, i + 2):
                return (), tuple(diagnostics)
            i += 2
            continue
        if ch in {"~", "!", "?", "&", "|", "=", "*", ">"}:
            if not emit(TokenKind.OP, ch, start, i + 1):
                return (), tuple(diagnostics)
            i += 1
            continue
        if ch == "$":
            j = i + 1
            if j < n and raw[j] == "$":
                j += 1
            while j < n and (raw[j].isalnum() or raw[j] == "_"):
                j += 1
            value = raw[i:j]
            if not (
                _DOLLAR_IDENT_RE.fullmatch(value)
                or _DOLLAR_DOLLAR_IDENT_RE.fullmatch(value)
            ):
                diagnostics.append(
                    _diag(
                        code=CODE_INVALID_LITERAL,
                        message=f"invalid system identifier {value!r}",
                        range=SourceRange(start, j),
                    )
                )
                return (), tuple(diagnostics)
            if not emit(TokenKind.DOLLAR_IDENT, value, start, j):
                return (), tuple(diagnostics)
            i = j
            continue
        if ch.isdigit() or (ch in "+-" and i + 1 < n and raw[i + 1].isdigit()):
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
            kind = TokenKind.VAR if _is_var_name(value) else TokenKind.IDENT
            if not emit(kind, value, start, j):
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

    tokens.append(Token(kind=TokenKind.EOF, value="", start=n, end=n))
    return tuple(tokens), tuple(diagnostics)


# ---------------------------------------------------------------------------
# Formula / document model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TPTPFormula:
    """Structural TPTP formula or term node with optional source range."""

    kind: TPTPFormulaKind | str
    name: str = ""
    arguments: tuple["TPTPFormula", ...] = ()
    binders: tuple[tuple[str, str], ...] = ()  # (var, sort) for quantifiers
    type_expr: str = ""  # for type declarations: "name: signature"
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, TPTPFormulaKind)
            else TPTPFormulaKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", str(self.name or ""))
        object.__setattr__(self, "arguments", tuple(self.arguments))
        object.__setattr__(
            self,
            "binders",
            tuple((str(v), str(s)) for v, s in self.binders),
        )
        object.__setattr__(self, "type_expr", str(self.type_expr or ""))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "arguments": [item.to_dict() for item in self.arguments],
            "binders": [[v, s] for v, s in self.binders],
            "kind": self.kind.value,
            "name": self.name,
            "type_expr": self.type_expr,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return (
            self.kind.value,
            self.name,
            self.type_expr,
            tuple(self.binders),
            tuple(arg.structural_key() for arg in self.arguments),
        )


@dataclass(frozen=True, slots=True)
class TPTPAnnotation:
    """Optional trailing annotation on an annotated formula."""

    source: str = ""
    useful_info: tuple[str, ...] = ()
    raw: str = ""
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", str(self.source or ""))
        object.__setattr__(
            self,
            "useful_info",
            tuple(str(item) for item in self.useful_info),
        )
        object.__setattr__(self, "raw", str(self.raw or ""))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "raw": self.raw,
            "source": self.source,
            "useful_info": list(self.useful_info),
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class TPTPAnnotatedFormula:
    """One annotated TPTP formula with language, name, role, and body."""

    language: TPTPLanguage | str
    name: str
    role: TPTPRole | str
    formula: TPTPFormula
    annotation: TPTPAnnotation | None = None
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        language = (
            self.language
            if isinstance(self.language, TPTPLanguage)
            else TPTPLanguage(str(self.language))
        )
        role = (
            self.role
            if isinstance(self.role, TPTPRole)
            else TPTPRole(str(self.role))
        )
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "name", str(self.name))
        if not self.name:
            raise TPTPError(
                "annotated formula name must be non-empty",
                code=CODE_MALFORMED_ANNOTATED,
            )
        if not isinstance(self.formula, TPTPFormula):
            raise TPTPError(
                "annotated formula body must be a TPTPFormula",
                code=CODE_MALFORMED_FORMULA,
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "formula": self.formula.to_dict(),
            "language": self.language.value,
            "name": self.name,
            "role": self.role.value,
        }
        if self.annotation is not None:
            payload["annotation"] = self.annotation.to_dict()
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        ann_key = None
        if self.annotation is not None:
            ann_key = (
                self.annotation.source,
                self.annotation.useful_info,
                self.annotation.raw,
            )
        return (
            self.language.value,
            self.name,
            self.role.value,
            self.formula.structural_key(),
            ann_key,
        )


@dataclass(frozen=True, slots=True)
class TPTPInclude:
    """Safe relative include directive."""

    path: str
    formula_selection: tuple[str, ...] = ()
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        path = str(self.path or "")
        object.__setattr__(self, "path", path)
        object.__setattr__(
            self,
            "formula_selection",
            tuple(str(item) for item in self.formula_selection),
        )
        validate_include_path(path)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "formula_selection": list(self.formula_selection),
            "path": self.path,
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class TPTPDocumentItem:
    """Top-level document item (annotated formula or include)."""

    kind: TPTPItemKind | str
    annotated: TPTPAnnotatedFormula | None = None
    include: TPTPInclude | None = None

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, TPTPItemKind)
            else TPTPItemKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        if kind is TPTPItemKind.ANNOTATED:
            if self.annotated is None:
                raise TPTPError(
                    "annotated item requires annotated formula",
                    code=CODE_MALFORMED_ANNOTATED,
                )
        elif kind is TPTPItemKind.INCLUDE:
            if self.include is None:
                raise TPTPError(
                    "include item requires include directive",
                    code=CODE_MALFORMED_INCLUDE,
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotated": None if self.annotated is None else self.annotated.to_dict(),
            "include": None if self.include is None else self.include.to_dict(),
            "kind": self.kind.value,
        }


@dataclass(frozen=True, slots=True)
class TPTPTypeDecl:
    """Extracted TFF type declaration (symbol → signature text)."""

    name: str
    signature: str
    formula_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula_name": self.formula_name,
            "name": self.name,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class TPTPDocument:
    """Elaborated TPTP problem document.

    Identity-relevant fields include languages, roles, symbols, formulas,
    includes, and annotations.  Printing is deterministic for the admitted
    subset.
    """

    items: tuple[TPTPDocumentItem, ...] = ()
    profile_id: str = TPTP_PROFILE_ID
    notation_id: str = TPTP_NOTATION_ID
    notation_version: str = TPTP_NOTATION_VERSION
    schema_version: str = TPTP_DOCUMENT_SCHEMA_VERSION
    source_text: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise TPTPError(
                "document metadata must be immutable JSON data",
                code=CODE_MALFORMED_ANNOTATED,
            ) from error
        if self.schema_version != TPTP_DOCUMENT_SCHEMA_VERSION:
            raise TPTPError(
                f"unsupported document schema {self.schema_version!r}",
                code=CODE_MALFORMED_ANNOTATED,
            )

    @property
    def interface(self) -> str:
        return TPTP_FRONTEND_INTERFACE

    @property
    def formulas(self) -> tuple[TPTPAnnotatedFormula, ...]:
        return tuple(
            item.annotated
            for item in self.items
            if item.kind is TPTPItemKind.ANNOTATED and item.annotated is not None
        )

    @property
    def includes(self) -> tuple[TPTPInclude, ...]:
        return tuple(
            item.include
            for item in self.items
            if item.kind is TPTPItemKind.INCLUDE and item.include is not None
        )

    @property
    def languages(self) -> tuple[str, ...]:
        seen: list[str] = []
        for formula in self.formulas:
            lang = formula.language.value
            if lang not in seen:
                seen.append(lang)
        return tuple(seen)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(formula.role.value for formula in self.formulas)

    @property
    def formula_names(self) -> tuple[str, ...]:
        return tuple(formula.name for formula in self.formulas)

    @property
    def type_declarations(self) -> tuple[TPTPTypeDecl, ...]:
        decls: list[TPTPTypeDecl] = []
        for formula in self.formulas:
            if formula.role is not TPTPRole.TYPE:
                continue
            body = formula.formula
            if body.kind is TPTPFormulaKind.TYPE_DECL and body.name:
                decls.append(
                    TPTPTypeDecl(
                        name=body.name,
                        signature=body.type_expr,
                        formula_name=formula.name,
                    )
                )
        return tuple(decls)

    @property
    def symbol_names(self) -> tuple[str, ...]:
        """Function/predicate/constant symbols referenced in formulas."""

        found: list[str] = []
        seen: set[str] = set()

        def visit(node: TPTPFormula) -> None:
            if node.kind is TPTPFormulaKind.FUN and node.name:
                if node.name not in seen and not node.name.startswith("$"):
                    seen.add(node.name)
                    found.append(node.name)
            elif node.kind is TPTPFormulaKind.ATOM and node.name:
                if node.name not in seen and not node.name.startswith("$"):
                    seen.add(node.name)
                    found.append(node.name)
            elif node.kind is TPTPFormulaKind.TYPE_DECL and node.name:
                if node.name not in seen and not node.name.startswith("$"):
                    seen.add(node.name)
                    found.append(node.name)
            for arg in node.arguments:
                visit(arg)

        for formula in self.formulas:
            visit(formula.formula)
        return tuple(found)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "formula_names": list(self.formula_names),
            "formulas": [item.to_dict() for item in self.formulas],
            "includes": [item.to_dict() for item in self.includes],
            "interface": TPTP_FRONTEND_INTERFACE,
            "languages": list(self.languages),
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "profile_id": self.profile_id,
            "roles": list(self.roles),
            "schema_version": self.schema_version,
            "symbol_names": list(self.symbol_names),
            "type_declarations": [item.to_dict() for item in self.type_declarations],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["items"] = [item.to_dict() for item in self.items]
        payload["metadata"] = self.metadata.to_dict()
        return payload

    def structural_key(self) -> tuple[Any, ...]:
        return tuple(
            (
                item.kind.value,
                None
                if item.annotated is None
                else item.annotated.structural_key(),
                None
                if item.include is None
                else (item.include.path, item.include.formula_selection),
            )
            for item in self.items
        )


def documents_semantically_compatible(left: TPTPDocument, right: TPTPDocument) -> bool:
    """Return True when two documents share the same structural semantics."""

    if not isinstance(left, TPTPDocument) or not isinstance(right, TPTPDocument):
        return False
    return left.structural_key() == right.structural_key()


# ---------------------------------------------------------------------------
# Include path safety
# ---------------------------------------------------------------------------


def validate_include_path(path: str) -> str:
    """Validate a TPTP include path; reject traversal and absolute forms.

    Returns the normalized relative path on success.  Raises :class:`TPTPError`
    with :data:`CODE_PATH_TRAVERSAL` or :data:`CODE_UNSAFE_INCLUDE` on failure.
    """

    if not isinstance(path, str) or not path:
        raise TPTPError(
            "include path must be a non-empty string",
            code=CODE_UNSAFE_INCLUDE,
            remediation="Use a relative include path within the problem set",
        )
    if "\x00" in path or any(ord(ch) < 32 for ch in path):
        raise TPTPError(
            "include path contains control characters",
            code=CODE_UNSAFE_INCLUDE,
        )
    stripped = path.strip()
    if stripped != path:
        raise TPTPError(
            "include path must not have surrounding whitespace",
            code=CODE_UNSAFE_INCLUDE,
        )
    # URL / scheme forms.
    if "://" in path or path.startswith("//"):
        raise TPTPError(
            f"include path must not be a URL or scheme reference: {path!r}",
            code=CODE_UNSAFE_INCLUDE,
        )
    # Absolute POSIX / Windows.
    if path.startswith("/") or path.startswith("\\"):
        raise TPTPError(
            f"absolute include path rejected: {path!r}",
            code=CODE_PATH_TRAVERSAL,
            remediation="Use a relative path without leading separators",
        )
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        raise TPTPError(
            f"absolute Windows include path rejected: {path!r}",
            code=CODE_PATH_TRAVERSAL,
        )
    if path.startswith("~"):
        raise TPTPError(
            f"home-relative include path rejected: {path!r}",
            code=CODE_UNSAFE_INCLUDE,
        )
    # Normalize separators for segment checks without resolving on disk.
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    segments = [seg for seg in normalized.split("/") if seg not in ("", ".")]
    if not segments:
        raise TPTPError(
            "include path has no path segments",
            code=CODE_UNSAFE_INCLUDE,
        )
    if any(seg == ".." for seg in segments):
        raise TPTPError(
            f"path traversal rejected in include path: {path!r}",
            code=CODE_PATH_TRAVERSAL,
            remediation="Remove '..' segments from include paths",
        )
    rebuilt = "/".join(segments)
    if not _SAFE_INCLUDE_RE.fullmatch(rebuilt):
        raise TPTPError(
            f"include path uses disallowed characters: {path!r}",
            code=CODE_UNSAFE_INCLUDE,
            remediation="Restrict includes to relative alphanumeric path segments",
        )
    return rebuilt


# ---------------------------------------------------------------------------
# Recursive-descent formula parser
# ---------------------------------------------------------------------------


class _FormulaParser:
    """Bounded recursive-descent parser for TPTP formula / term syntax."""

    def __init__(
        self,
        tokens: Sequence[Token],
        *,
        language: TPTPLanguage,
        max_depth: int,
    ) -> None:
        self.tokens = tokens
        self.language = language
        self.max_depth = max_depth
        self.pos = 0
        self.depth = 0

    def _peek(self) -> Token:
        if self.pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self._peek()
        if tok.kind is not TokenKind.EOF:
            self.pos += 1
        return tok

    def _expect(self, kind: TokenKind, value: str | None = None) -> Token:
        tok = self._peek()
        if tok.kind is not kind or (value is not None and tok.value != value):
            expected = value if value is not None else kind.value
            raise TPTPError(
                f"expected {expected!r}, got {tok.value!r}",
                code=CODE_UNEXPECTED_TOKEN,
                range=tok.range,
            )
        return self._advance()

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > self.max_depth:
            raise TPTPError(
                f"parse depth exceeded max_depth={self.max_depth}",
                code=CODE_PARSE_DEPTH,
                range=self._peek().range,
            )

    def _leave(self) -> None:
        self.depth -= 1

    def parse_formula(self) -> TPTPFormula:
        self._enter()
        try:
            if self.language is TPTPLanguage.CNF:
                return self._parse_clause()
            return self._parse_logic()
        finally:
            self._leave()

    def parse_type_body(self) -> TPTPFormula:
        """Parse ``name: signature`` type declaration body."""

        self._enter()
        try:
            name_tok = self._peek()
            if name_tok.kind not in {
                TokenKind.IDENT,
                TokenKind.DOLLAR_IDENT,
                TokenKind.STRING,
            }:
                raise TPTPError(
                    "type declaration requires a symbol name",
                    code=CODE_MALFORMED_FORMULA,
                    range=name_tok.range,
                )
            name = self._advance().value
            self._expect(TokenKind.COLON)
            start = name_tok.start
            # Consume the remainder as a signature expression.
            parts: list[str] = []
            depth_paren = 0
            depth_brack = 0
            while self._peek().kind is not TokenKind.EOF:
                tok = self._peek()
                if tok.kind is TokenKind.LPAREN:
                    depth_paren += 1
                elif tok.kind is TokenKind.RPAREN:
                    if depth_paren == 0:
                        break
                    depth_paren -= 1
                elif tok.kind is TokenKind.LBRACK:
                    depth_brack += 1
                elif tok.kind is TokenKind.RBRACK:
                    if depth_brack == 0:
                        break
                    depth_brack -= 1
                elif tok.kind is TokenKind.COMMA and depth_paren == 0 and depth_brack == 0:
                    break
                parts.append(_token_surface(self._advance()))
            if not parts:
                raise TPTPError(
                    "type declaration missing signature",
                    code=CODE_MALFORMED_FORMULA,
                    range=name_tok.range,
                )
            signature = _join_signature_tokens(parts)
            end = self.tokens[self.pos - 1].end if self.pos > 0 else name_tok.end
            return TPTPFormula(
                kind=TPTPFormulaKind.TYPE_DECL,
                name=name,
                type_expr=signature,
                range=SourceRange(start, end),
            )
        finally:
            self._leave()

    def _parse_clause(self) -> TPTPFormula:
        """CNF clause: literal | literal | ... or $false for empty clause."""

        self._enter()
        try:
            lits: list[TPTPFormula] = []
            first = self._parse_literal()
            lits.append(first)
            while self._peek().kind is TokenKind.OP and self._peek().value == "|":
                self._advance()
                lits.append(self._parse_literal())
            if len(lits) == 1:
                return lits[0]
            start = lits[0].range.start if lits[0].range else 0
            end = lits[-1].range.end if lits[-1].range else start
            return TPTPFormula(
                kind=TPTPFormulaKind.CLAUSE,
                arguments=tuple(lits),
                range=SourceRange(start, end),
            )
        finally:
            self._leave()

    def _parse_literal(self) -> TPTPFormula:
        if self._peek().kind is TokenKind.OP and self._peek().value == "~":
            op = self._advance()
            atom = self._parse_atomic()
            end = atom.range.end if atom.range else op.end
            return TPTPFormula(
                kind=TPTPFormulaKind.NOT,
                arguments=(atom,),
                range=SourceRange(op.start, end),
            )
        return self._parse_atomic()

    def _parse_logic(self) -> TPTPFormula:
        return self._parse_iff()

    def _parse_iff(self) -> TPTPFormula:
        left = self._parse_implies()
        while self._peek().kind is TokenKind.OP and self._peek().value == "<=>":
            self._advance()
            right = self._parse_implies()
            start = left.range.start if left.range else 0
            end = right.range.end if right.range else start
            left = TPTPFormula(
                kind=TPTPFormulaKind.IFF,
                arguments=(left, right),
                range=SourceRange(start, end),
            )
        return left

    def _parse_implies(self) -> TPTPFormula:
        # Right-associative implication.
        left = self._parse_or()
        if self._peek().kind is TokenKind.OP and self._peek().value == "=>":
            self._advance()
            right = self._parse_implies()
            start = left.range.start if left.range else 0
            end = right.range.end if right.range else start
            return TPTPFormula(
                kind=TPTPFormulaKind.IMPLIES,
                arguments=(left, right),
                range=SourceRange(start, end),
            )
        return left

    def _parse_or(self) -> TPTPFormula:
        left = self._parse_and()
        while self._peek().kind is TokenKind.OP and self._peek().value == "|":
            self._advance()
            right = self._parse_and()
            start = left.range.start if left.range else 0
            end = right.range.end if right.range else start
            left = TPTPFormula(
                kind=TPTPFormulaKind.OR,
                arguments=(left, right),
                range=SourceRange(start, end),
            )
        return left

    def _parse_and(self) -> TPTPFormula:
        left = self._parse_unary()
        while self._peek().kind is TokenKind.OP and self._peek().value == "&":
            self._advance()
            right = self._parse_unary()
            start = left.range.start if left.range else 0
            end = right.range.end if right.range else start
            left = TPTPFormula(
                kind=TPTPFormulaKind.AND,
                arguments=(left, right),
                range=SourceRange(start, end),
            )
        return left

    def _parse_unary(self) -> TPTPFormula:
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.value == "~":
            op = self._advance()
            body = self._parse_unary()
            end = body.range.end if body.range else op.end
            return TPTPFormula(
                kind=TPTPFormulaKind.NOT,
                arguments=(body,),
                range=SourceRange(op.start, end),
            )
        if tok.kind is TokenKind.OP and tok.value in {"!", "?"}:
            return self._parse_quantifier()
        return self._parse_equality()

    def _parse_quantifier(self) -> TPTPFormula:
        op = self._advance()
        kind = (
            TPTPFormulaKind.FORALL if op.value == "!" else TPTPFormulaKind.EXISTS
        )
        self._expect(TokenKind.LBRACK)
        binders: list[tuple[str, str]] = []
        while True:
            var_tok = self._peek()
            if var_tok.kind not in {TokenKind.VAR, TokenKind.IDENT}:
                raise TPTPError(
                    "quantifier binder requires a variable",
                    code=CODE_MALFORMED_FORMULA,
                    range=var_tok.range,
                )
            var_name = self._advance().value
            sort = ""
            if self._peek().kind is TokenKind.COLON:
                self._advance()
                sort = self._parse_sort_token()
            binders.append((var_name, sort))
            if self._peek().kind is TokenKind.COMMA:
                self._advance()
                continue
            break
        self._expect(TokenKind.RBRACK)
        self._expect(TokenKind.COLON)
        body = self._parse_unary()
        end = body.range.end if body.range else op.end
        return TPTPFormula(
            kind=kind,
            binders=tuple(binders),
            arguments=(body,),
            range=SourceRange(op.start, end),
        )

    def _parse_sort_token(self) -> str:
        tok = self._peek()
        if tok.kind in {
            TokenKind.IDENT,
            TokenKind.DOLLAR_IDENT,
            TokenKind.STRING,
            TokenKind.VAR,
        }:
            return self._advance().value
        raise TPTPError(
            "expected sort identifier",
            code=CODE_MALFORMED_FORMULA,
            range=tok.range,
        )

    def _parse_equality(self) -> TPTPFormula:
        left = self._parse_atomic()
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.value in {"=", "!="}:
            op = self._advance()
            # Equality sides are terms, not full formulas.
            right = self._parse_term_arg()
            left_term = self._as_term(left)
            start = left_term.range.start if left_term.range else op.start
            end = right.range.end if right.range else op.end
            kind = (
                TPTPFormulaKind.EQ if op.value == "=" else TPTPFormulaKind.NEQ
            )
            return TPTPFormula(
                kind=kind,
                arguments=(left_term, right),
                range=SourceRange(start, end),
            )
        return left

    @staticmethod
    def _as_term(node: TPTPFormula) -> TPTPFormula:
        """Coerce a nullary/atomic application into term form for equality."""

        if node.kind is TPTPFormulaKind.ATOM:
            return TPTPFormula(
                kind=TPTPFormulaKind.FUN,
                name=node.name,
                arguments=node.arguments,
                range=node.range,
            )
        if node.kind is TPTPFormulaKind.VAR:
            return node
        if node.kind is TPTPFormulaKind.FUN:
            return node
        if node.kind in {TPTPFormulaKind.TRUE, TPTPFormulaKind.FALSE}:
            return TPTPFormula(
                kind=TPTPFormulaKind.FUN,
                name=node.name or (
                    "$true" if node.kind is TPTPFormulaKind.TRUE else "$false"
                ),
                range=node.range,
            )
        return node

    def _parse_atomic(self) -> TPTPFormula:
        tok = self._peek()
        if tok.kind is TokenKind.LPAREN:
            self._advance()
            if self.language is TPTPLanguage.CNF:
                inner = self._parse_clause()
            else:
                inner = self._parse_logic()
            self._expect(TokenKind.RPAREN)
            return inner
        if tok.kind is TokenKind.DOLLAR_IDENT:
            if tok.value == "$true":
                self._advance()
                return TPTPFormula(
                    kind=TPTPFormulaKind.TRUE,
                    name="$true",
                    range=tok.range,
                )
            if tok.value == "$false":
                self._advance()
                return TPTPFormula(
                    kind=TPTPFormulaKind.FALSE,
                    name="$false",
                    range=tok.range,
                )
        return self._parse_term_or_atom()

    def _parse_term_or_atom(self) -> TPTPFormula:
        tok = self._peek()
        if tok.kind is TokenKind.VAR:
            self._advance()
            # Variable application is unusual but allowed as term; as atom only
            # when not followed by '('.
            if self._peek().kind is TokenKind.LPAREN:
                return self._parse_application(tok, as_atom=False)
            return TPTPFormula(
                kind=TPTPFormulaKind.VAR,
                name=tok.value,
                range=tok.range,
            )
        if tok.kind in {
            TokenKind.IDENT,
            TokenKind.DOLLAR_IDENT,
            TokenKind.STRING,
            TokenKind.DISTINCT,
            TokenKind.INTEGER,
            TokenKind.REAL,
        }:
            self._advance()
            if self._peek().kind is TokenKind.LPAREN:
                # Applications may appear as atoms or terms.
                return self._parse_application(tok, as_atom=True)
            # Nullary: treat lowercase / system names as atoms; numbers/distinct
            # as fun/constants used in equality contexts.
            if tok.kind in {TokenKind.INTEGER, TokenKind.REAL, TokenKind.DISTINCT}:
                return TPTPFormula(
                    kind=TPTPFormulaKind.FUN,
                    name=tok.value,
                    range=tok.range,
                )
            return TPTPFormula(
                kind=TPTPFormulaKind.ATOM,
                name=tok.value,
                range=tok.range,
            )
        raise TPTPError(
            f"unexpected token {tok.value!r} in formula",
            code=CODE_UNEXPECTED_TOKEN,
            range=tok.range,
        )

    def _parse_application(self, head: Token, *, as_atom: bool) -> TPTPFormula:
        self._expect(TokenKind.LPAREN)
        args: list[TPTPFormula] = []
        if self._peek().kind is not TokenKind.RPAREN:
            while True:
                args.append(self._parse_term_arg())
                if self._peek().kind is TokenKind.COMMA:
                    self._advance()
                    continue
                break
        end_tok = self._expect(TokenKind.RPAREN)
        kind = TPTPFormulaKind.ATOM if as_atom else TPTPFormulaKind.FUN
        # Prefer FUN when head is clearly a function used inside terms, but
        # ATOM for predicate applications at formula level.  Callers that parse
        # term args use as_atom=False.
        if not as_atom:
            kind = TPTPFormulaKind.FUN
        else:
            # If this appears under equality parsing as a term, callers will
            # re-interpret; keep as ATOM for predicate context.
            kind = TPTPFormulaKind.ATOM
        return TPTPFormula(
            kind=kind,
            name=head.value,
            arguments=tuple(args),
            range=SourceRange(head.start, end_tok.end),
        )

    def _parse_term_arg(self) -> TPTPFormula:
        """Parse a term (not a full formula) in argument position."""

        tok = self._peek()
        if tok.kind is TokenKind.LPAREN:
            self._advance()
            inner = self._parse_term_arg()
            self._expect(TokenKind.RPAREN)
            return inner
        if tok.kind is TokenKind.VAR:
            self._advance()
            if self._peek().kind is TokenKind.LPAREN:
                return self._parse_application(tok, as_atom=False)
            return TPTPFormula(
                kind=TPTPFormulaKind.VAR,
                name=tok.value,
                range=tok.range,
            )
        if tok.kind in {
            TokenKind.IDENT,
            TokenKind.DOLLAR_IDENT,
            TokenKind.STRING,
            TokenKind.DISTINCT,
            TokenKind.INTEGER,
            TokenKind.REAL,
        }:
            self._advance()
            if self._peek().kind is TokenKind.LPAREN:
                return self._parse_application(tok, as_atom=False)
            return TPTPFormula(
                kind=TPTPFormulaKind.FUN if tok.kind is not TokenKind.VAR else TPTPFormulaKind.VAR,
                name=tok.value,
                range=tok.range,
            )
        raise TPTPError(
            f"unexpected token {tok.value!r} in term",
            code=CODE_UNEXPECTED_TOKEN,
            range=tok.range,
        )


def _quote_single(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _quote_double(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _token_surface(tok: Token) -> str:
    """Render a token's surface form for reprinting annotations/signatures."""

    if tok.kind is TokenKind.STRING:
        return _quote_single(tok.value)
    if tok.kind is TokenKind.DISTINCT:
        return _quote_double(tok.value)
    return tok.value


def _join_surface_parts(parts: Sequence[str]) -> str:
    """Join already-surfaced token strings with TPTP-friendly spacing."""

    if not parts:
        return ""
    out: list[str] = []
    for i, part in enumerate(parts):
        if i == 0:
            out.append(part)
            continue
        prev = out[-1]
        if part in {")", "]", ",", ":", "*", ">"}:
            out.append(part)
        elif prev in {"(", "[", ":", "*", ">"}:
            out.append(part)
        elif prev == ",":
            out.append(" ")
            out.append(part)
        elif part == "(" and (
            _IDENT_RE.fullmatch(prev)
            or prev.startswith("$")
            or prev.endswith("'")
            or prev.endswith('"')
        ):
            out.append(part)
        else:
            out.append(" ")
            out.append(part)
    return "".join(out)


def _join_signature_tokens(parts: Sequence[str]) -> str:
    """Join signature tokens with TPTP-friendly spacing."""

    return _join_surface_parts(parts)


# ---------------------------------------------------------------------------
# Annotation parsing
# ---------------------------------------------------------------------------


def _parse_annotation_tokens(
    tokens: Sequence[Token],
    start: int,
    *,
    max_depth: int,
) -> tuple[TPTPAnnotation, int]:
    """Parse optional annotation starting at ``start``; return (ann, end_pos)."""

    if start >= len(tokens) or tokens[start].kind is TokenKind.EOF:
        raise TPTPError(
            "malformed annotation: empty",
            code=CODE_MALFORMED_ANNOTATION,
            range=tokens[min(start, len(tokens) - 1)].range,
        )

    # Annotation is either a single general_term or general_term, general_list.
    # We capture a balanced comma-separated source, optional useful_info list.
    pos = start
    depth_paren = 0
    depth_brack = 0
    source_parts: list[str] = []
    source_start = tokens[pos].start
    saw_any = False

    while pos < len(tokens):
        tok = tokens[pos]
        if tok.kind is TokenKind.EOF:
            break
        if tok.kind is TokenKind.LPAREN:
            depth_paren += 1
            source_parts.append(_token_surface(tok))
            saw_any = True
            pos += 1
            continue
        if tok.kind is TokenKind.RPAREN:
            if depth_paren == 0 and depth_brack == 0:
                break
            depth_paren -= 1
            if depth_paren < 0:
                raise TPTPError(
                    "unbalanced parentheses in annotation",
                    code=CODE_MALFORMED_ANNOTATION,
                    range=tok.range,
                )
            source_parts.append(_token_surface(tok))
            pos += 1
            continue
        if tok.kind is TokenKind.LBRACK:
            depth_brack += 1
            source_parts.append(_token_surface(tok))
            saw_any = True
            pos += 1
            continue
        if tok.kind is TokenKind.RBRACK:
            if depth_brack == 0 and depth_paren == 0:
                break
            depth_brack -= 1
            if depth_brack < 0:
                raise TPTPError(
                    "unbalanced brackets in annotation",
                    code=CODE_MALFORMED_ANNOTATION,
                    range=tok.range,
                )
            source_parts.append(_token_surface(tok))
            pos += 1
            continue
        if (
            tok.kind is TokenKind.COMMA
            and depth_paren == 0
            and depth_brack == 0
        ):
            # End of source; optional useful_info follows.
            pos += 1
            break
        source_parts.append(_token_surface(tok))
        saw_any = True
        pos += 1

    if not saw_any:
        raise TPTPError(
            "malformed annotation: missing source term",
            code=CODE_MALFORMED_ANNOTATION,
            range=tokens[start].range,
        )
    if depth_paren != 0 or depth_brack != 0:
        raise TPTPError(
            "unbalanced delimiters in annotation source",
            code=CODE_MALFORMED_ANNOTATION,
            range=tokens[start].range,
        )

    source_text = _join_surface_parts(source_parts)
    # Reject empty or clearly broken forms.
    if not source_text.strip():
        raise TPTPError(
            "malformed annotation: empty source",
            code=CODE_MALFORMED_ANNOTATION,
            range=tokens[start].range,
        )
    # Bare commas / trailing incomplete inference forms.
    if source_text.rstrip().endswith(",") or source_text.lstrip().startswith(","):
        raise TPTPError(
            f"malformed annotation source: {source_text!r}",
            code=CODE_MALFORMED_ANNOTATION,
            range=tokens[start].range,
        )
    _validate_annotation_source(source_text, range=tokens[start].range)

    useful: list[str] = []
    useful_raw = ""
    if pos < len(tokens) and tokens[pos].kind is TokenKind.LBRACK:
        # Parse useful_info list as balanced [ ... ]
        list_start = pos
        depth = 0
        list_parts: list[str] = []
        while pos < len(tokens):
            tok = tokens[pos]
            if tok.kind is TokenKind.EOF:
                raise TPTPError(
                    "unterminated useful_info list in annotation",
                    code=CODE_MALFORMED_ANNOTATION,
                    range=tokens[list_start].range,
                )
            if tok.kind is TokenKind.LBRACK:
                depth += 1
                list_parts.append(_token_surface(tok))
                pos += 1
                continue
            if tok.kind is TokenKind.RBRACK:
                depth -= 1
                list_parts.append(_token_surface(tok))
                pos += 1
                if depth == 0:
                    break
                continue
            list_parts.append(_token_surface(tok))
            pos += 1
        if depth != 0:
            raise TPTPError(
                "unbalanced useful_info list",
                code=CODE_MALFORMED_ANNOTATION,
                range=tokens[list_start].range,
            )
        useful_raw = _join_surface_parts(list_parts)
        # Extract top-level items inside the brackets.
        inner = useful_raw[1:-1].strip() if useful_raw.startswith("[") else useful_raw
        if inner:
            useful = _split_top_level_items(inner)

    end_pos = pos
    end_offset = tokens[end_pos - 1].end if end_pos > start else tokens[start].end
    raw = source_text if not useful_raw else f"{source_text}, {useful_raw}"
    # Depth guard for nested annotations.
    if raw.count("(") > max_depth:
        raise TPTPError(
            "annotation nesting exceeds parse depth",
            code=CODE_PARSE_DEPTH,
            range=tokens[start].range,
        )
    return (
        TPTPAnnotation(
            source=source_text,
            useful_info=tuple(useful),
            raw=raw,
            range=SourceRange(source_start, end_offset),
        ),
        end_pos,
    )


def _split_top_level_items(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth_paren = 0
    depth_brack = 0
    in_single = False
    in_double = False
    escape = False
    for ch in text:
        if escape:
            current.append(ch)
            escape = False
            continue
        if ch == "\\" and (in_single or in_double):
            current.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            continue
        if in_single or in_double:
            current.append(ch)
            continue
        if ch == "(":
            depth_paren += 1
            current.append(ch)
            continue
        if ch == ")":
            depth_paren -= 1
            current.append(ch)
            continue
        if ch == "[":
            depth_brack += 1
            current.append(ch)
            continue
        if ch == "]":
            depth_brack -= 1
            current.append(ch)
            continue
        if ch == "," and depth_paren == 0 and depth_brack == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            continue
        current.append(ch)
    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def _validate_annotation_source(source: str, *, range: SourceRange | None) -> None:
    """Reject clearly malformed annotation source terms."""

    text = source.strip()
    if not text:
        raise TPTPError(
            "empty annotation source",
            code=CODE_MALFORMED_ANNOTATION,
            range=range,
        )
    # Unbalanced delimiters.
    if text.count("(") != text.count(")"):
        raise TPTPError(
            f"malformed annotation (unbalanced parentheses): {text!r}",
            code=CODE_MALFORMED_ANNOTATION,
            range=range,
        )
    if text.count("[") != text.count("]"):
        raise TPTPError(
            f"malformed annotation (unbalanced brackets): {text!r}",
            code=CODE_MALFORMED_ANNOTATION,
            range=range,
        )
    # Reject incomplete inference/file forms: inference(  or file(name
    if re.search(r"\b(inference|file|introduced|theory|creator)\s*\(\s*$", text):
        raise TPTPError(
            f"malformed annotation (incomplete term): {text!r}",
            code=CODE_MALFORMED_ANNOTATION,
            range=range,
        )
    if text.endswith("(") or text.endswith(","):
        raise TPTPError(
            f"malformed annotation (truncated): {text!r}",
            code=CODE_MALFORMED_ANNOTATION,
            range=range,
        )
    # Bare unknown punctuation-only sources.
    if re.fullmatch(r"[,:;]+", text):
        raise TPTPError(
            f"malformed annotation source: {text!r}",
            code=CODE_MALFORMED_ANNOTATION,
            range=range,
        )


# ---------------------------------------------------------------------------
# Document parser
# ---------------------------------------------------------------------------


def _language_from_token(tok: Token) -> TPTPLanguage:
    value = tok.value.casefold()
    if value in THF_LANGUAGES or value == "thf":
        raise TPTPError(
            f"THF dialect {tok.value!r} is not supported by TPTPFrontend@1; "
            "higher-order TPTP is deferred until separately implemented",
            code=CODE_UNSUPPORTED_THF,
            range=tok.range,
            remediation="Use cnf/fof/tff, or wait for the THF frontend",
        )
    if value in UNSUPPORTED_LANGUAGES:
        raise TPTPError(
            f"unsupported TPTP language {tok.value!r}",
            code=CODE_UNSUPPORTED_LANGUAGE,
            range=tok.range,
        )
    if value not in SUPPORTED_LANGUAGES:
        raise TPTPError(
            f"unknown TPTP language {tok.value!r}",
            code=CODE_UNSUPPORTED_LANGUAGE,
            range=tok.range,
        )
    return TPTPLanguage(value)


def _role_from_token(tok: Token) -> TPTPRole:
    value = tok.value.casefold()
    if value in UNSUPPORTED_ROLES:
        raise TPTPError(
            f"unsupported TPTP role {tok.value!r}",
            code=CODE_UNSUPPORTED_ROLE,
            range=tok.range,
        )
    if value not in SUPPORTED_ROLES:
        raise TPTPError(
            f"unknown TPTP role {tok.value!r}",
            code=CODE_UNKNOWN_ROLE,
            range=tok.range,
        )
    return TPTPRole(value)


class _DocumentParser:
    def __init__(
        self,
        tokens: Sequence[Token],
        *,
        limits: ParseLimits,
    ) -> None:
        self.tokens = tokens
        self.limits = limits
        self.pos = 0

    def _peek(self) -> Token:
        if self.pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self._peek()
        if tok.kind is not TokenKind.EOF:
            self.pos += 1
        return tok

    def _expect(self, kind: TokenKind, value: str | None = None) -> Token:
        tok = self._peek()
        if tok.kind is not kind or (value is not None and tok.value != value):
            expected = value if value is not None else kind.value
            raise TPTPError(
                f"expected {expected!r}, got {tok.value!r}",
                code=CODE_UNEXPECTED_TOKEN,
                range=tok.range,
            )
        return self._advance()

    def parse(self) -> TPTPDocument:
        items: list[TPTPDocumentItem] = []
        while self._peek().kind is not TokenKind.EOF:
            items.append(self._parse_item())
        if not items:
            raise TPTPError(
                "empty TPTP input; expected annotated formula or include",
                code=CODE_EMPTY_INPUT,
                range=SourceRange(0, 0),
            )
        return TPTPDocument(items=tuple(items))

    def _parse_item(self) -> TPTPDocumentItem:
        tok = self._peek()
        if tok.kind is TokenKind.IDENT and tok.value.casefold() == "include":
            return TPTPDocumentItem(
                kind=TPTPItemKind.INCLUDE,
                include=self._parse_include(),
            )
        if tok.kind is TokenKind.IDENT:
            return TPTPDocumentItem(
                kind=TPTPItemKind.ANNOTATED,
                annotated=self._parse_annotated(),
            )
        raise TPTPError(
            f"expected annotated formula or include, got {tok.value!r}",
            code=CODE_MALFORMED_ANNOTATED,
            range=tok.range,
        )

    def _parse_include(self) -> TPTPInclude:
        start = self._peek()
        self._expect(TokenKind.IDENT, "include")
        self._expect(TokenKind.LPAREN)
        path_tok = self._peek()
        if path_tok.kind is not TokenKind.STRING:
            raise TPTPError(
                "include path must be a single-quoted string",
                code=CODE_MALFORMED_INCLUDE,
                range=path_tok.range,
            )
        path = self._advance().value
        try:
            safe_path = validate_include_path(path)
        except TPTPError as error:
            if error.range is None:
                error.range = path_tok.range
            raise
        selection: list[str] = []
        if self._peek().kind is TokenKind.COMMA:
            self._advance()
            self._expect(TokenKind.LBRACK)
            if self._peek().kind is not TokenKind.RBRACK:
                while True:
                    name_tok = self._peek()
                    if name_tok.kind not in {
                        TokenKind.IDENT,
                        TokenKind.STRING,
                        TokenKind.DOLLAR_IDENT,
                    }:
                        raise TPTPError(
                            "include formula selection requires formula names",
                            code=CODE_MALFORMED_INCLUDE,
                            range=name_tok.range,
                        )
                    selection.append(self._advance().value)
                    if self._peek().kind is TokenKind.COMMA:
                        self._advance()
                        continue
                    break
            self._expect(TokenKind.RBRACK)
        self._expect(TokenKind.RPAREN)
        end = self._expect(TokenKind.DOT)
        return TPTPInclude(
            path=safe_path,
            formula_selection=tuple(selection),
            range=SourceRange(start.start, end.end),
        )

    def _parse_annotated(self) -> TPTPAnnotatedFormula:
        lang_tok = self._peek()
        if lang_tok.kind is not TokenKind.IDENT:
            raise TPTPError(
                "annotated formula requires a language keyword",
                code=CODE_MALFORMED_ANNOTATED,
                range=lang_tok.range,
            )
        language = _language_from_token(lang_tok)
        self._advance()
        self._expect(TokenKind.LPAREN)

        name_tok = self._peek()
        if name_tok.kind not in {
            TokenKind.IDENT,
            TokenKind.STRING,
            TokenKind.DOLLAR_IDENT,
            TokenKind.INTEGER,
        }:
            raise TPTPError(
                "annotated formula name must be an atomic word or integer",
                code=CODE_MALFORMED_ANNOTATED,
                range=name_tok.range,
            )
        name = self._advance().value
        self._expect(TokenKind.COMMA)

        role_tok = self._peek()
        if role_tok.kind is not TokenKind.IDENT:
            raise TPTPError(
                "annotated formula role must be an identifier",
                code=CODE_MALFORMED_ANNOTATED,
                range=role_tok.range,
            )
        role = _role_from_token(role_tok)
        self._advance()
        self._expect(TokenKind.COMMA)

        # Collect formula tokens until top-level comma (annotation) or ')'.
        formula_tokens, next_pos, has_annotation = self._collect_formula_tokens()
        self.pos = next_pos

        formula_parser = _FormulaParser(
            list(formula_tokens)
            + [Token(kind=TokenKind.EOF, value="", start=0, end=0)],
            language=language,
            max_depth=self.limits.max_depth,
        )
        if role is TPTPRole.TYPE and language is TPTPLanguage.TFF:
            formula = formula_parser.parse_type_body()
        else:
            formula = formula_parser.parse_formula()
        if formula_parser._peek().kind is not TokenKind.EOF:
            raise TPTPError(
                "trailing tokens in formula body",
                code=CODE_TRAILING_INPUT,
                range=formula_parser._peek().range,
            )

        annotation: TPTPAnnotation | None = None
        if has_annotation:
            annotation, ann_end = _parse_annotation_tokens(
                self.tokens,
                self.pos,
                max_depth=self.limits.max_depth,
            )
            self.pos = ann_end

        self._expect(TokenKind.RPAREN)
        end = self._expect(TokenKind.DOT)
        return TPTPAnnotatedFormula(
            language=language,
            name=name,
            role=role,
            formula=formula,
            annotation=annotation,
            range=SourceRange(lang_tok.start, end.end),
        )

    def _collect_formula_tokens(
        self,
    ) -> tuple[list[Token], int, bool]:
        """Collect tokens for the formula field; return tokens, pos, has_ann."""

        tokens: list[Token] = []
        pos = self.pos
        depth_paren = 0
        depth_brack = 0
        while pos < len(self.tokens):
            tok = self.tokens[pos]
            if tok.kind is TokenKind.EOF:
                raise TPTPError(
                    "unterminated annotated formula",
                    code=CODE_UNBALANCED,
                    range=tok.range,
                )
            if tok.kind is TokenKind.LPAREN:
                depth_paren += 1
                tokens.append(tok)
                pos += 1
                continue
            if tok.kind is TokenKind.RPAREN:
                if depth_paren == 0 and depth_brack == 0:
                    # End of formula; no annotation.
                    if not tokens:
                        raise TPTPError(
                            "empty formula body",
                            code=CODE_MALFORMED_FORMULA,
                            range=tok.range,
                        )
                    return tokens, pos, False
                depth_paren -= 1
                if depth_paren < 0:
                    raise TPTPError(
                        "unbalanced parentheses in formula",
                        code=CODE_UNBALANCED,
                        range=tok.range,
                    )
                tokens.append(tok)
                pos += 1
                continue
            if tok.kind is TokenKind.LBRACK:
                depth_brack += 1
                tokens.append(tok)
                pos += 1
                continue
            if tok.kind is TokenKind.RBRACK:
                depth_brack -= 1
                if depth_brack < 0:
                    raise TPTPError(
                        "unbalanced brackets in formula",
                        code=CODE_UNBALANCED,
                        range=tok.range,
                    )
                tokens.append(tok)
                pos += 1
                continue
            if (
                tok.kind is TokenKind.COMMA
                and depth_paren == 0
                and depth_brack == 0
            ):
                if not tokens:
                    raise TPTPError(
                        "empty formula body before annotation",
                        code=CODE_MALFORMED_FORMULA,
                        range=tok.range,
                    )
                # Annotation follows this comma.
                return tokens, pos + 1, True
            tokens.append(tok)
            pos += 1
        raise TPTPError(
            "unterminated annotated formula",
            code=CODE_UNBALANCED,
            range=self.tokens[-1].range,
        )


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class TPTPPrinter:
    """Deterministic TPTP printer for elaborated documents and formulas."""

    def print_document(self, document: TPTPDocument) -> str:
        if not isinstance(document, TPTPDocument):
            raise TPTPError(
                "print_document requires a TPTPDocument",
                code=CODE_MALFORMED_ANNOTATED,
            )
        lines: list[str] = [
            f"% TPTP frontend {TPTP_MODULE_VERSION}",
            f"% interface: {TPTP_FRONTEND_INTERFACE}",
            f"% profile: {document.profile_id}",
        ]
        for item in document.items:
            if item.kind is TPTPItemKind.INCLUDE and item.include is not None:
                lines.append(self.print_include(item.include))
            elif item.kind is TPTPItemKind.ANNOTATED and item.annotated is not None:
                lines.append(self.print_annotated(item.annotated))
        return "\n".join(lines) + "\n"

    def print_include(self, include: TPTPInclude) -> str:
        path = include.path.replace("\\", "\\\\").replace("'", "\\'")
        if include.formula_selection:
            names = ", ".join(include.formula_selection)
            return f"include('{path}', [{names}])."
        return f"include('{path}')."

    def print_annotated(self, formula: TPTPAnnotatedFormula) -> str:
        body = self.print_formula(formula.formula, language=formula.language)
        core = (
            f"{formula.language.value}({formula.name}, {formula.role.value}, {body}"
        )
        if formula.annotation is not None and formula.annotation.raw:
            core = f"{core}, {formula.annotation.raw}"
        return core + ")."

    def print_formula(
        self,
        formula: TPTPFormula,
        *,
        language: TPTPLanguage | str | None = None,
        parent_prec: int = 0,
    ) -> str:
        del language  # structural print is language-uniform for admitted ops
        kind = formula.kind
        if kind is TPTPFormulaKind.TRUE:
            return "$true"
        if kind is TPTPFormulaKind.FALSE:
            return "$false"
        if kind is TPTPFormulaKind.VAR:
            return formula.name
        if kind is TPTPFormulaKind.FUN:
            if not formula.arguments:
                return formula.name
            args = ", ".join(
                self.print_formula(arg, parent_prec=0) for arg in formula.arguments
            )
            return f"{formula.name}({args})"
        if kind is TPTPFormulaKind.ATOM:
            if not formula.arguments:
                return formula.name
            args = ", ".join(
                self.print_formula(arg, parent_prec=0) for arg in formula.arguments
            )
            return f"{formula.name}({args})"
        if kind is TPTPFormulaKind.TYPE_DECL:
            return f"{formula.name}: {formula.type_expr}"
        if kind is TPTPFormulaKind.NOT:
            # Negation applies to a unitary formula; non-unitary bodies need parens.
            body = self.print_formula(formula.arguments[0], parent_prec=5)
            if not self._is_unitary(formula.arguments[0]) and not (
                body.startswith("(") and body.endswith(")")
            ):
                body = f"({body})"
            text = f"~ {body}"
            return text if parent_prec <= 5 else f"({text})"
        if kind is TPTPFormulaKind.AND:
            return self._print_bin(formula, "&", 4, parent_prec, right_assoc=False)
        if kind is TPTPFormulaKind.OR or kind is TPTPFormulaKind.CLAUSE:
            return self._print_bin(formula, "|", 3, parent_prec, right_assoc=False)
        if kind is TPTPFormulaKind.IMPLIES:
            # Right-associative implication.
            left = self.print_formula(formula.arguments[0], parent_prec=3)
            right = self.print_formula(formula.arguments[1], parent_prec=2)
            text = f"{left} => {right}"
            return text if parent_prec <= 2 else f"({text})"
        if kind is TPTPFormulaKind.IFF:
            return self._print_bin(formula, "<=>", 1, parent_prec, right_assoc=False)
        if kind is TPTPFormulaKind.EQ:
            left = self.print_formula(formula.arguments[0], parent_prec=6)
            right = self.print_formula(formula.arguments[1], parent_prec=6)
            text = f"{left} = {right}"
            return text if parent_prec <= 6 else f"({text})"
        if kind is TPTPFormulaKind.NEQ:
            left = self.print_formula(formula.arguments[0], parent_prec=6)
            right = self.print_formula(formula.arguments[1], parent_prec=6)
            text = f"{left} != {right}"
            return text if parent_prec <= 6 else f"({text})"
        if kind is TPTPFormulaKind.FORALL:
            return self._print_quant("!", formula, parent_prec)
        if kind is TPTPFormulaKind.EXISTS:
            return self._print_quant("?", formula, parent_prec)
        raise TPTPError(
            f"cannot print formula kind {kind!r}",
            code=CODE_MALFORMED_FORMULA,
        )

    @staticmethod
    def _is_unitary(formula: TPTPFormula) -> bool:
        """Return True when *formula* is a TPTP unitary formula."""

        return formula.kind in {
            TPTPFormulaKind.TRUE,
            TPTPFormulaKind.FALSE,
            TPTPFormulaKind.ATOM,
            TPTPFormulaKind.FUN,
            TPTPFormulaKind.VAR,
            TPTPFormulaKind.NOT,
            TPTPFormulaKind.EQ,
            TPTPFormulaKind.NEQ,
            TPTPFormulaKind.FORALL,
            TPTPFormulaKind.EXISTS,
            TPTPFormulaKind.TYPE_DECL,
        }

    def _print_bin(
        self,
        formula: TPTPFormula,
        op: str,
        prec: int,
        parent_prec: int,
        *,
        right_assoc: bool,
    ) -> str:
        if formula.kind is TPTPFormulaKind.CLAUSE:
            parts = [
                self.print_formula(arg, parent_prec=prec + 1)
                for arg in formula.arguments
            ]
            text = f" {op} ".join(parts)
            return text if parent_prec <= prec else f"({text})"
        # Binary print without associative flattening so nested trees round-trip.
        left_prec = prec if right_assoc else prec
        right_prec = prec if right_assoc else prec + 1
        if right_assoc:
            left_prec = prec + 1
            right_prec = prec
        left = self.print_formula(formula.arguments[0], parent_prec=left_prec)
        right = self.print_formula(formula.arguments[1], parent_prec=right_prec)
        text = f"{left} {op} {right}"
        return text if parent_prec <= prec else f"({text})"

    def _print_quant(
        self, quant: str, formula: TPTPFormula, parent_prec: int
    ) -> str:
        binders: list[str] = []
        for var, sort in formula.binders:
            if sort:
                binders.append(f"{var}: {sort}")
            else:
                binders.append(var)
        body_node = formula.arguments[0]
        # Quantifier body is unitary in TPTP; parenthesize non-unitary bodies.
        body = self.print_formula(body_node, parent_prec=0)
        if not self._is_unitary(body_node):
            body = f"({body})"
        text = f"{quant} [{', '.join(binders)}] : {body}"
        # Quantified formulas are unitary; parenthesize when embedded under a
        # higher-precedence (or equal non-assoc) context that is not top-level.
        return text if parent_prec <= 5 else f"({text})"


# ---------------------------------------------------------------------------
# Parse result / public frontend
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TPTPParseResult:
    """Typed result of a TPTP parse/elaborate attempt."""

    status: ParseStatus
    document: TPTPDocument | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    schema_version: str = TPTP_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = TPTP_FRONTEND_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.document is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document": None if self.document is None else self.document.to_dict(),
            "interface": self.interface,
            "printed": self.printed,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


class _TPTPParserImpl:
    """Notation parser for controlled TPTP problem files.

    Interface: ``TPTPFrontend@1``.
    """

    interface: ClassVar[str] = TPTP_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = TPTP_NOTATION_ID
    notation_version: ClassVar[str] = TPTP_NOTATION_VERSION
    profile_id: ClassVar[str] = TPTP_PROFILE_ID

    def __init__(self) -> None:
        self.printer = TPTPPrinter()

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:tptp:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> TPTPParseResult:
        del mode  # strict-only subset
        del document_id
        bounds = limits if limits is not None else ParseLimits()
        tokens, lex_diags = tokenize_tptp(text, limits=bounds)
        if lex_diags and any(item.is_error for item in lex_diags):
            status = (
                ParseStatus.REJECTED
                if any(item.code == CODE_INPUT_LIMIT for item in lex_diags)
                else ParseStatus.FAILED
            )
            return TPTPParseResult(status=status, diagnostics=lex_diags)
        # Tokens always end with EOF; empty source → only EOF.
        if len(tokens) <= 1:
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty TPTP input; expected annotated formula or include",
                range=SourceRange(0, 0),
            )
            return TPTPParseResult(status=ParseStatus.FAILED, diagnostics=(diag,))
        try:
            document = _DocumentParser(tokens, limits=bounds).parse()
            object.__setattr__(document, "source_text", text)
        except TPTPError as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=error.range,
                remediation=error.remediation,
            )
            return TPTPParseResult(
                status=ParseStatus.FAILED,
                diagnostics=lex_diags + (diag,),
            )
        printed = self.printer.print_document(document)
        return TPTPParseResult(
            status=ParseStatus.OK,
            document=document,
            diagnostics=lex_diags,
            printed=printed,
        )

    def parse_document(
        self,
        document: SourceDocument,
        *,
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> TPTPParseResult:
        if not isinstance(document, SourceDocument):
            raise TPTPError(
                "document must be a SourceDocument",
                code=CODE_MALFORMED_ANNOTATED,
            )
        return self.parse_text(
            document.text,
            document_id=document.document_id,
            limits=limits,
            mode=mode,
        )


class TPTPParser(_TPTPParserImpl):
    """Public TPTP parser (``parser:local:tptp`` implementation)."""


class TPTPFrontend:
    """Facade for TPTP parse / elaborate / print.

    Interface: ``TPTPFrontend@1``.
    """

    interface: ClassVar[str] = TPTP_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = TPTP_NOTATION_ID
    notation_version: ClassVar[str] = TPTP_NOTATION_VERSION
    profile_id: ClassVar[str] = TPTP_PROFILE_ID
    family_id: ClassVar[str] = TPTP_FAMILY_ID

    def __init__(self) -> None:
        self.parser = TPTPParser()
        self.printer = self.parser.printer
        self.tstp = TSTPCandidateFrontend()

    def parse_text(self, text: str, **kwargs: Any) -> TPTPParseResult:
        return self.parser.parse_text(text, **kwargs)

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TPTPDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise TPTPParseError(
                result.errors[0].message if result.errors else "TPTP parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_FORMULA,
            )
        return result.document

    def print(self, document: TPTPDocument) -> str:
        return self.printer.print_document(document)

    def elaborate(self, text: str, **kwargs: Any) -> TPTPDocument:
        return self.parse_text_or_raise(text, **kwargs)

    def round_trip(self, text: str, **kwargs: Any) -> TPTPParseResult:
        """Parse → print → re-parse; success requires structural preservation."""

        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:tptp:1") + ":rt",
            limits=kwargs.get("limits"),
        )
        if not second.ok or second.document is None:
            return second
        if not documents_semantically_compatible(first.document, second.document):
            diag = _diag(
                code=CODE_ROUND_TRIP,
                message="parse/print/parse does not preserve TPTP structure",
                range=SourceRange(0, 0),
            )
            return TPTPParseResult(
                status=ParseStatus.FAILED,
                document=second.document,
                diagnostics=second.diagnostics + (diag,),
                printed=printed,
            )
        return TPTPParseResult(
            status=ParseStatus.OK,
            document=second.document,
            diagnostics=second.diagnostics,
            printed=printed,
        )


# ---------------------------------------------------------------------------
# TSTP candidate frontend (untrusted)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TSTPProofStep:
    """One TSTP proof step (annotated formula with optional inference)."""

    language: str
    name: str
    role: str
    formula: TPTPFormula
    annotation: TPTPAnnotation | None = None
    range: SourceRange | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "formula": self.formula.to_dict(),
            "language": self.language,
            "name": self.name,
            "role": self.role,
        }
        if self.annotation is not None:
            payload["annotation"] = self.annotation.to_dict()
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class TSTPCandidateProof:
    """Untrusted TSTP proof candidate bound to candidate authority only.

    Parsing a TSTP derivation never yields theorem authority.  Downstream
    consumers must reconstruct or kernel-check before promoting the claim.
    """

    steps: tuple[TSTPProofStep, ...] = ()
    szs_status: str = ""
    szs_output_form: str = ""
    authority: ResultAuthority = ResultAuthority.CANDIDATE
    status: ResultStatus = ResultStatus.CANDIDATE
    trusted: bool = False
    schema_version: str = TSTP_CANDIDATE_SCHEMA_VERSION
    source_text: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "szs_status", str(self.szs_status or ""))
        object.__setattr__(self, "szs_output_form", str(self.szs_output_form or ""))
        object.__setattr__(self, "trusted", False)  # always untrusted
        authority = (
            self.authority
            if isinstance(self.authority, ResultAuthority)
            else ResultAuthority(str(self.authority))
        )
        if authority is not ResultAuthority.CANDIDATE:
            raise TSTPError(
                "TSTP candidates must use ResultAuthority.CANDIDATE; "
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
            raise TSTPError(
                "TSTP candidates must use ResultStatus.CANDIDATE; "
                f"got {status!r}",
                code=CODE_CANDIDATE_AUTHORITY,
            )
        object.__setattr__(self, "status", ResultStatus.CANDIDATE)
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise TSTPError(
                "candidate metadata must be immutable JSON data",
                code=CODE_MALFORMED_ANNOTATION,
            ) from error
        if self.schema_version != TSTP_CANDIDATE_SCHEMA_VERSION:
            raise TSTPError(
                f"unsupported candidate schema {self.schema_version!r}",
                code=CODE_MALFORMED_ANNOTATED,
            )

    @property
    def interface(self) -> str:
        return TSTP_CANDIDATE_FRONTEND_INTERFACE

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
            "schema_version": self.schema_version,
            "status": self.status.value,
            "step_names": list(self.step_names),
            "steps": [item.to_dict() for item in self.steps],
            "szs_output_form": self.szs_output_form,
            "szs_status": self.szs_status,
            "trusted": False,
        }


@dataclass(frozen=True, slots=True)
class TSTPParseResult:
    """Typed result of a TSTP candidate parse."""

    status: ParseStatus
    candidate: TSTPCandidateProof | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    schema_version: str = TSTP_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = TSTP_CANDIDATE_FRONTEND_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.candidate is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "interface": self.interface,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


def parse_szs_status(text: str) -> str | None:
    """Extract one SZS status token from TSTP/prover output, if present."""

    if not isinstance(text, str) or not text:
        return None
    matches = _SZS_STATUS_RE.findall(text)
    if not matches:
        return None
    # Prefer the last status line (common in multi-stage output).
    return matches[-1]


class TSTPCandidateFrontend:
    """Parse TSTP derivations as untrusted proof candidates.

    Interface: ``TSTPCandidateFrontend@1``.

    Authority is hard-wired to :attr:`ResultAuthority.CANDIDATE`.  The
    frontend never claims theorem or reconstruction authority.
    """

    interface: ClassVar[str] = TSTP_CANDIDATE_FRONTEND_INTERFACE
    authority: ClassVar[ResultAuthority] = ResultAuthority.CANDIDATE

    def __init__(self) -> None:
        self._problem_parser = TPTPParser()

    def parse_text(
        self,
        text: str,
        *,
        limits: ParseLimits | None = None,
    ) -> TSTPParseResult:
        if not isinstance(text, str) or not text.strip():
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty TSTP input",
                range=SourceRange(0, 0),
            )
            return TSTPParseResult(status=ParseStatus.FAILED, diagnostics=(diag,))

        bounds = limits if limits is not None else ParseLimits()
        if len(text.encode("utf-8", errors="replace")) > bounds.max_input_bytes:
            diag = _diag(
                code=CODE_INPUT_LIMIT,
                message=f"TSTP input exceeds max_input_bytes={bounds.max_input_bytes}",
                range=SourceRange(0, min(len(text), bounds.max_input_bytes)),
            )
            return TSTPParseResult(status=ParseStatus.REJECTED, diagnostics=(diag,))

        szs_status = parse_szs_status(text) or ""
        if szs_status and szs_status not in SUPPORTED_SZS_STATUSES:
            # Unknown SZS token is recorded but does not hard-fail the
            # candidate parse; still never trusted.
            pass

        szs_form = ""
        start_match = _SZS_OUTPUT_START_RE.search(text)
        if start_match:
            szs_form = start_match.group(1)

        # Parse formula steps by stripping pure SZS comment noise is already
        # handled by the lexer (line comments).  Reuse TPTP document parse.
        problem_result = self._problem_parser.parse_text(text, limits=bounds)
        if not problem_result.ok or problem_result.document is None:
            # If only SZS lines were present without formulas, fail closed.
            return TSTPParseResult(
                status=problem_result.status,
                diagnostics=problem_result.diagnostics,
            )

        steps: list[TSTPProofStep] = []
        for formula in problem_result.document.formulas:
            steps.append(
                TSTPProofStep(
                    language=formula.language.value,
                    name=formula.name,
                    role=formula.role.value,
                    formula=formula.formula,
                    annotation=formula.annotation,
                    range=formula.range,
                )
            )

        if not steps:
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="TSTP candidate has no proof steps",
                range=SourceRange(0, 0),
            )
            return TSTPParseResult(status=ParseStatus.FAILED, diagnostics=(diag,))

        try:
            candidate = TSTPCandidateProof(
                steps=tuple(steps),
                szs_status=szs_status,
                szs_output_form=szs_form,
                authority=ResultAuthority.CANDIDATE,
                status=ResultStatus.CANDIDATE,
                trusted=False,
                source_text=text,
                metadata=FrozenMap(
                    {
                        "untrusted": True,
                        "authority_ceiling": ResultAuthority.CANDIDATE.value,
                    }
                ),
            )
        except TSTPError as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=error.range,
                remediation=error.remediation,
            )
            return TSTPParseResult(status=ParseStatus.FAILED, diagnostics=(diag,))

        return TSTPParseResult(
            status=ParseStatus.OK,
            candidate=candidate,
            diagnostics=problem_result.diagnostics,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TSTPCandidateProof:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.candidate is None:
            raise TSTPError(
                result.errors[0].message if result.errors else "TSTP parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_FORMULA,
            )
        return result.candidate


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_tptp(
    text: str,
    *,
    document_id: str = "doc:tptp:1",
    limits: ParseLimits | None = None,
) -> TPTPParseResult:
    """Parse controlled TPTP problem text into a typed result."""

    return TPTPParser().parse_text(text, document_id=document_id, limits=limits)


def elaborate_tptp(text: str, **kwargs: Any) -> TPTPDocument:
    """Parse and return the elaborated document, or raise."""

    return TPTPFrontend().elaborate(text, **kwargs)


def print_tptp(document: TPTPDocument) -> str:
    """Print an elaborated TPTP document deterministically."""

    return TPTPPrinter().print_document(document)


def parse_print_parse_tptp(text: str, **kwargs: Any) -> TPTPParseResult:
    """Parse → print → re-parse round trip."""

    return TPTPFrontend().round_trip(text, **kwargs)


def parse_tstp_candidate(
    text: str,
    *,
    limits: ParseLimits | None = None,
) -> TSTPParseResult:
    """Parse TSTP output as an untrusted proof candidate."""

    return TSTPCandidateFrontend().parse_text(text, limits=limits)


__all__ = [
    "CODE_CANDIDATE_AUTHORITY",
    "CODE_EMPTY_INPUT",
    "CODE_INPUT_LIMIT",
    "CODE_MALFORMED_ANNOTATION",
    "CODE_MALFORMED_ANNOTATED",
    "CODE_MALFORMED_FORMULA",
    "CODE_MALFORMED_INCLUDE",
    "CODE_PATH_TRAVERSAL",
    "CODE_PARSE_DEPTH",
    "CODE_ROUND_TRIP",
    "CODE_TOKEN_LIMIT",
    "CODE_UNBALANCED",
    "CODE_UNEXPECTED_TOKEN",
    "CODE_UNKNOWN_ROLE",
    "CODE_UNSAFE_INCLUDE",
    "CODE_UNSUPPORTED_LANGUAGE",
    "CODE_UNSUPPORTED_ROLE",
    "CODE_UNSUPPORTED_THF",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_ROLES",
    "SUPPORTED_SZS_STATUSES",
    "SZSStatus",
    "THF_LANGUAGES",
    "TPTP_FRONTEND_INTERFACE",
    "TPTP_MODULE_VERSION",
    "TPTP_NOTATION_ID",
    "TPTP_NOTATION_VERSION",
    "TPTP_PROFILE_ID",
    "TPTPAnnotatedFormula",
    "TPTPAnnotation",
    "TPTPDocument",
    "TPTPDocumentItem",
    "TPTPError",
    "TPTPFormula",
    "TPTPFormulaKind",
    "TPTPFrontend",
    "TPTPInclude",
    "TPTPItemKind",
    "TPTPLanguage",
    "TPTPParseError",
    "TPTPParseResult",
    "TPTPParser",
    "TPTPPrinter",
    "TPTPRole",
    "TPTPTypeDecl",
    "TSTP_CANDIDATE_FRONTEND_INTERFACE",
    "TSTPCandidateFrontend",
    "TSTPCandidateProof",
    "TSTPError",
    "TSTPParseResult",
    "TSTPProofStep",
    "Token",
    "TokenKind",
    "UNSUPPORTED_LANGUAGES",
    "UNSUPPORTED_ROLES",
    "documents_semantically_compatible",
    "elaborate_tptp",
    "parse_print_parse_tptp",
    "parse_szs_status",
    "parse_tptp",
    "parse_tstp_candidate",
    "print_tptp",
    "tokenize_tptp",
    "validate_include_path",
]
