"""SMT-LIB2 reader, elaborator, printer, and typed SMT bridge.

Interface: ``SMTLIB2Frontend@1`` (LFP-018).

Controlled SMT-LIB 2.6 subset covering:

* bounded S-expression reading with finite resource limits
* declarations (``declare-sort``, ``declare-fun``, ``declare-const``,
  ``declare-datatypes``)
* ``let`` bindings and quantifiers (``forall`` / ``exists``)
* Core, equality, arithmetic, arrays, bit-vectors, and strings theory
  fragments shared by Z3 and cvc5
* model / unsat-core request commands
* fail-closed rejection of unknown commands and theories

Elaboration reuses the typed semantic SMT compiler model
(:class:`~ipfs_datasets_py.logic.backends.smt.compiler.SmtTerm`,
:class:`~ipfs_datasets_py.logic.backends.smt.compiler.SmtObligation`)
rather than duplicating theory semantics.  The bridge lowers an elaborated
script into a compiler obligation and can re-print scripts with declared
theory/profile metadata.

Round-trip property for the Z3/cvc5 common fragment: parse → elaborate →
print → re-parse preserves symbol and sort declarations and the structural
shape of assertions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final, Iterator, Union

from ipfs_datasets_py.logic.backends.smt.compiler import (
    BOOL_SORT,
    INT_SORT,
    REAL_SORT,
    SMTLIB_VERSION,
    SmtBinder,
    SmtDatatypeConstructor,
    SmtDatatypeDecl,
    SmtFeature,
    SmtFunDecl,
    SmtNamedAssertion,
    SmtObligation,
    SmtQueryMode,
    SmtSort,
    SmtTerm,
    SmtTermKind,
    SmtTheory,
    SoftwareVerificationSMTCompiler,
    array_sort,
    term_and,
    term_apply,
    term_eq,
    term_false,
    term_implies,
    term_int,
    term_not,
    term_or,
    term_symbol,
    term_true,
)
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

SMTLIB2_FRONTEND_INTERFACE: Final = "SMTLIB2Frontend@1"
SMTLIB2_NOTATION_ID: Final = "smtlib2"
SMTLIB2_NOTATION_VERSION: Final = "2.6.0"
SMTLIB2_PROFILE_ID: Final = "smt_core"
SMTLIB2_FAMILY_ID: Final = "first_order"
SMTLIB_MODULE_VERSION: Final = "1.0.0"
SMTLIB_PARSE_RESULT_SCHEMA_VERSION: Final = "smtlib2-parse-result/v1"
SMTLIB_DOCUMENT_SCHEMA_VERSION: Final = "smtlib2-document/v1"
SMTLIB_BRIDGE_SCHEMA_VERSION: Final = "smtlib2-bridge/v1"

# Stable namespaced diagnostic codes.
CODE_EMPTY_INPUT: Final = "smtlib.empty_input"
CODE_INPUT_LIMIT: Final = "smtlib.input_limit"
CODE_TOKEN_LIMIT: Final = "smtlib.token_limit"
CODE_PARSE_DEPTH: Final = "smtlib.parse_depth_exceeded"
CODE_UNBALANCED: Final = "smtlib.unbalanced_delimiter"
CODE_UNEXPECTED_TOKEN: Final = "smtlib.unexpected_token"
CODE_MALFORMED_SEXPR: Final = "smtlib.malformed_sexpr"
CODE_UNSUPPORTED_COMMAND: Final = "smtlib.unsupported_command"
CODE_UNKNOWN_COMMAND: Final = "smtlib.unknown_command"
CODE_UNSUPPORTED_THEORY: Final = "smtlib.unsupported_theory"
CODE_UNKNOWN_THEORY: Final = "smtlib.unknown_theory"
CODE_UNDECLARED_SYMBOL: Final = "smtlib.undeclared_symbol"
CODE_UNDECLARED_SORT: Final = "smtlib.undeclared_sort"
CODE_ARITY_MISMATCH: Final = "smtlib.arity_mismatch"
CODE_KIND_MISMATCH: Final = "smtlib.kind_mismatch"
CODE_MALFORMED_COMMAND: Final = "smtlib.malformed_command"
CODE_MALFORMED_TERM: Final = "smtlib.malformed_term"
CODE_MALFORMED_SORT: Final = "smtlib.malformed_sort"
CODE_DUPLICATE_SYMBOL: Final = "smtlib.duplicate_symbol"
CODE_DUPLICATE_SORT: Final = "smtlib.duplicate_sort"
CODE_UNSUPPORTED_FEATURE: Final = "smtlib.unsupported_feature"
CODE_TYPECHECK_FAILED: Final = "smtlib.typecheck_failed"
CODE_BRIDGE_FAILED: Final = "smtlib.bridge_failed"
CODE_TRAILING_INPUT: Final = "smtlib.trailing_input"
CODE_UNTERMINATED_STRING: Final = "smtlib.unterminated_string"
CODE_UNTERMINATED_QUOTE: Final = "smtlib.unterminated_quoted_symbol"
CODE_INVALID_LITERAL: Final = "smtlib.invalid_literal"

_ALL_SMTLIB_CODES: Final[frozenset[str]] = frozenset(
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

# ---------------------------------------------------------------------------
# Supported command / theory / logic vocabulary (declared subset)
# ---------------------------------------------------------------------------


class SmtlibCommandKind(StrEnum):
    """Top-level SMT-LIB commands admitted by the controlled subset."""

    SET_LOGIC = "set-logic"
    SET_INFO = "set-info"
    SET_OPTION = "set-option"
    DECLARE_SORT = "declare-sort"
    DECLARE_FUN = "declare-fun"
    DECLARE_CONST = "declare-const"
    DECLARE_DATATYPES = "declare-datatypes"
    DEFINE_FUN = "define-fun"
    ASSERT = "assert"
    CHECK_SAT = "check-sat"
    GET_MODEL = "get-model"
    GET_UNSAT_CORE = "get-unsat-core"
    PUSH = "push"
    POP = "pop"
    RESET = "reset"
    EXIT = "exit"


SUPPORTED_COMMANDS: Final[frozenset[str]] = frozenset(
    item.value for item in SmtlibCommandKind
)

# Explicitly rejected commands (fail closed with unsupported_command).
UNSUPPORTED_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "assert-soft",
        "check-sat-assuming",
        "declare-codatatypes",
        "declare-heap",
        "declare-oracle-fun",
        "declare-rel",
        "declare-var",
        "define-const",
        "define-fun-rec",
        "define-funs-rec",
        "define-sort",
        "echo",
        "get-assertions",
        "get-assignment",
        "get-info",
        "get-option",
        "get-proof",
        "get-unsat-assumptions",
        "get-value",
        "reset-assertions",
        "simplify",
        "minimize",
        "maximize",
        "synth-fun",
        "synth-inv",
        "constraint",
        "check-synth",
        "inv-constraint",
        "set-feature",
    }
)

# Logics admitted for the Z3/cvc5 common fragment (and neutral supersets).
SUPPORTED_LOGICS: Final[frozenset[str]] = frozenset(
    {
        "ALL",
        "QF_UF",
        "UF",
        "QF_LIA",
        "LIA",
        "QF_UFLIA",
        "UFLIA",
        "QF_LRA",
        "LRA",
        "QF_UFLRA",
        "UFLRA",
        "QF_NIA",
        "NIA",
        "QF_NRA",
        "NRA",
        "QF_AUFLIA",
        "AUFLIA",
        "QF_AUFLIRA",
        "AUFLIRA",
        "QF_ABV",
        "ABV",
        "QF_BV",
        "BV",
        "QF_AUFBV",
        "AUFBV",
        "QF_S",
        "S",
        "QF_SLIA",
        "QF_UFDT",
        "UFDT",
        "HORN",
        "QF_ANIA",
        "ANIA",
    }
)

# Theory identifiers that may appear via set-logic fragments / set-info.
SUPPORTED_THEORIES: Final[frozenset[str]] = frozenset(
    {
        "Core",
        "Ints",
        "Reals",
        "Reals_Ints",
        "ArraysEx",
        "FixedSizeBitVectors",
        "FloatingPoint",
        "Strings",
        "Datatypes",
        "core",
        "equality",
        "arithmetic",
        "arrays",
        "bitvectors",
        "bv",
        "strings",
        "datatypes",
        "quantifiers",
        "horn",
    }
)

UNSUPPORTED_THEORIES: Final[frozenset[str]] = frozenset(
    {
        "FloatingPoint_full",  # reserved explicit reject for non-common FP
        "SepLogic",
        "SeparationLogic",
        "Sequences_full",
        "Bags",
        "Sets_full",
        "Transcendentals",
    }
)

# Built-in sorts always available.
_BUILTIN_SORTS: Final[frozenset[str]] = frozenset(
    {"Bool", "Int", "Real", "String", "RegLan", "RoundingMode"}
)

# Core / theory function symbols admitted without prior declare-fun.
_CORE_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        "true",
        "false",
        "not",
        "and",
        "or",
        "xor",
        "=>",
        "ite",
        "=",
        "distinct",
    }
)

_ARITH_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        "+",
        "-",
        "*",
        "/",
        "div",
        "mod",
        "abs",
        "to_real",
        "to_int",
        "is_int",
        "<",
        "<=",
        ">",
        ">=",
    }
)

_ARRAY_SYMBOLS: Final[frozenset[str]] = frozenset({"select", "store"})

_BV_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        "bvnot",
        "bvand",
        "bvor",
        "bvxor",
        "bvnand",
        "bvnor",
        "bvxnor",
        "bvneg",
        "bvadd",
        "bvsub",
        "bvmul",
        "bvudiv",
        "bvurem",
        "bvsdiv",
        "bvsrem",
        "bvsmod",
        "bvshl",
        "bvlshr",
        "bvashr",
        "bvult",
        "bvule",
        "bvugt",
        "bvuge",
        "bvslt",
        "bvsle",
        "bvsgt",
        "bvsge",
        "bvcomp",
        "concat",
        "extract",
        "repeat",
        "zero_extend",
        "sign_extend",
        "rotate_left",
        "rotate_right",
        "bv2nat",
        "nat2bv",
    }
)

_STRING_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        "str.++",
        "str.len",
        "str.at",
        "str.substr",
        "str.indexof",
        "str.replace",
        "str.contains",
        "str.prefixof",
        "str.suffixof",
        "str.to_int",
        "str.from_int",
        "str.to_re",
        "str.in_re",
        "re.++",
        "re.union",
        "re.inter",
        "re.*",
        "re.+",
        "re.opt",
        "re.range",
        "re.comp",
        "re.diff",
        "str.<",
        "str.<=",
    }
)

_BUILTIN_FUN_SYMBOLS: Final[frozenset[str]] = (
    _CORE_SYMBOLS | _ARITH_SYMBOLS | _ARRAY_SYMBOLS | _BV_SYMBOLS | _STRING_SYMBOLS
)

_KEYWORD_OPTION_MODELS: Final[frozenset[str]] = frozenset(
    {
        ":produce-models",
        ":produce-unsat-cores",
        ":produce-proofs",
        ":produce-assignments",
        ":print-success",
        ":interactive-mode",
        ":global-declarations",
        ":incremental",
    }
)

_SIMPLE_SYMBOL_RE: Final = re.compile(r"^[A-Za-z_~!@$%^&*+=<>.?/-][0-9A-Za-z_~!@$%^&*+=<>.?/-]*$")
_NUMERAL_RE: Final = re.compile(r"^[0-9]+$")
_DECIMAL_RE: Final = re.compile(r"^[0-9]+\.[0-9]+$")
_BV_BIN_RE: Final = re.compile(r"^#b[01]+$")
_BV_HEX_RE: Final = re.compile(r"^#x[0-9A-Fa-f]+$")
_BV_LITERAL_RE: Final = re.compile(r"^bv[0-9]+$")
_ATTRIBUTE_RE: Final = re.compile(r"^:[0-9A-Za-z_~!@$%^&*+=<>.?/-]+$")


# ---------------------------------------------------------------------------
# Errors / diagnostics
# ---------------------------------------------------------------------------


class SMTLIBError(SyntaxContractError):
    """Base class for SMT-LIB frontend failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_MALFORMED_SEXPR,
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


class SMTLIBParseError(SMTLIBError):
    """Raised by raising helpers when a parse fails closed."""


class SMTLIBElaborationError(SMTLIBError):
    """Raised when S-expressions cannot be elaborated into typed SMT terms."""


class SMTLIBBridgeError(SMTLIBError):
    """Raised when bridging an elaborated script to a compiler obligation fails."""


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
    diag_id = diagnostic_id or f"diag:smtlib:{code.replace('.', '-')}"
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
# S-expression model
# ---------------------------------------------------------------------------

SExpr = Union["SAtom", "SList"]


@dataclass(frozen=True, slots=True)
class SAtom:
    """Atomic SMT-LIB token with source span."""

    value: str
    kind: str = "symbol"  # symbol | numeral | decimal | string | keyword | bv | quoted
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise SMTLIBError("SAtom value must be a string", code=CODE_MALFORMED_SEXPR)
        if not self.value and self.kind not in {"string"}:
            raise SMTLIBError("SAtom value must be non-empty", code=CODE_MALFORMED_SEXPR)

    @property
    def is_keyword(self) -> bool:
        return self.kind == "keyword" or self.value.startswith(":")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class SList:
    """Parenthesized S-expression list with source span."""

    items: tuple[SExpr, ...]
    range: SourceRange | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))

    def __iter__(self) -> Iterator[SExpr]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> SExpr:
        return self.items[index]

    @property
    def head(self) -> SExpr | None:
        return self.items[0] if self.items else None

    def head_symbol(self) -> str | None:
        head = self.head
        if isinstance(head, SAtom):
            return head.value
        return None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "items": [
                item.to_dict() if hasattr(item, "to_dict") else item for item in self.items
            ],
            "kind": "list",
        }
        if self.range is not None:
            payload["range"] = self.range.to_dict()
        return payload


# ---------------------------------------------------------------------------
# Bounded S-expression reader
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int

    @property
    def range(self) -> SourceRange:
        return SourceRange(start=self.start, end=self.end, start_char=self.start, end_char=self.end)


class _SExprReader:
    """Resource-bounded SMT-LIB S-expression tokenizer and parser."""

    def __init__(self, text: str, *, limits: ParseLimits) -> None:
        if not isinstance(text, str):
            raise SMTLIBError("source must be text", code=CODE_EMPTY_INPUT)
        self.text = text
        self.limits = limits
        self.pos = 0
        self.length = len(text)
        self.token_count = 0
        self.node_count = 0
        self.diagnostics: list[SyntaxDiagnostic] = []

    def read_all(self) -> tuple[tuple[SExpr, ...], tuple[SyntaxDiagnostic, ...]]:
        if self.length == 0 or not self.text.strip():
            self.diagnostics.append(
                _diag(
                    code=CODE_EMPTY_INPUT,
                    message="empty SMT-LIB input",
                    range=SourceRange(0, 0),
                )
            )
            return (), tuple(self.diagnostics)

        byte_len = len(self.text.encode("utf-8"))
        if byte_len > self.limits.max_input_bytes:
            self.diagnostics.append(
                _diag(
                    code=CODE_INPUT_LIMIT,
                    message=(
                        f"source length {byte_len} exceeds "
                        f"max_input_bytes {self.limits.max_input_bytes}"
                    ),
                    range=SourceRange(0, min(self.length, self.limits.max_input_bytes)),
                    severity=DiagnosticSeverity.FATAL,
                )
            )
            return (), tuple(self.diagnostics)

        forms: list[SExpr] = []
        try:
            while True:
                self._skip_trivia()
                if self.pos >= self.length:
                    break
                form = self._read_sexpr(depth=0)
                forms.append(form)
        except SMTLIBError as error:
            self.diagnostics.append(
                _diag(
                    code=error.code,
                    message=error.message,
                    range=error.range or SourceRange(self.pos, min(self.pos + 1, self.length)),
                    remediation=error.remediation,
                )
            )
            return (), tuple(self.diagnostics)

        return tuple(forms), tuple(self.diagnostics)

    def _skip_trivia(self) -> None:
        while self.pos < self.length:
            ch = self.text[self.pos]
            if ch.isspace():
                self.pos += 1
                continue
            if ch == ";":
                # Line comment to EOL.
                while self.pos < self.length and self.text[self.pos] not in "\n\r":
                    self.pos += 1
                continue
            break

    def _bump_token(self) -> None:
        self.token_count += 1
        if self.token_count > self.limits.max_tokens:
            raise SMTLIBError(
                f"token count exceeds max_tokens {self.limits.max_tokens}",
                code=CODE_TOKEN_LIMIT,
                range=SourceRange(self.pos, min(self.pos + 1, self.length)),
            )

    def _bump_node(self, depth: int) -> None:
        self.node_count += 1
        if depth > self.limits.max_depth:
            raise SMTLIBError(
                f"S-expression depth {depth} exceeds max_depth {self.limits.max_depth}",
                code=CODE_PARSE_DEPTH,
                range=SourceRange(self.pos, min(self.pos + 1, self.length)),
            )

    def _read_sexpr(self, *, depth: int) -> SExpr:
        self._skip_trivia()
        if self.pos >= self.length:
            raise SMTLIBError(
                "unexpected end of SMT-LIB input",
                code=CODE_UNEXPECTED_TOKEN,
                range=SourceRange(self.length, self.length),
            )
        self._bump_node(depth)
        ch = self.text[self.pos]
        if ch == "(":
            return self._read_list(depth=depth)
        if ch == ")":
            raise SMTLIBError(
                "unexpected ')'",
                code=CODE_UNBALANCED,
                range=SourceRange(self.pos, self.pos + 1),
            )
        return self._read_atom()

    def _read_list(self, *, depth: int) -> SList:
        start = self.pos
        self.pos += 1  # consume '('
        self._bump_token()
        items: list[SExpr] = []
        while True:
            self._skip_trivia()
            if self.pos >= self.length:
                raise SMTLIBError(
                    "unbalanced '(' — end of input before ')'",
                    code=CODE_UNBALANCED,
                    range=SourceRange(start, self.length),
                    remediation="Close all open parentheses",
                )
            if self.text[self.pos] == ")":
                end = self.pos + 1
                self.pos = end
                self._bump_token()
                return SList(
                    items=tuple(items),
                    range=SourceRange(start, end, start_char=start, end_char=end),
                )
            items.append(self._read_sexpr(depth=depth + 1))

    def _read_atom(self) -> SAtom:
        self._bump_token()
        ch = self.text[self.pos]
        if ch == '"':
            return self._read_string()
        if ch == "|":
            return self._read_quoted_symbol()
        if ch == "#":
            return self._read_bv_literal()
        # Simple symbol / numeral / decimal / keyword / attribute.
        start = self.pos
        while self.pos < self.length:
            c = self.text[self.pos]
            if c.isspace() or c in "();|":
                break
            if c == '"' and self.pos > start:
                break
            self.pos += 1
        if self.pos == start:
            raise SMTLIBError(
                f"unexpected character {ch!r}",
                code=CODE_UNEXPECTED_TOKEN,
                range=SourceRange(start, start + 1),
            )
        value = self.text[start : self.pos]
        span = SourceRange(start, self.pos, start_char=start, end_char=self.pos)
        kind = self._classify_atom(value)
        return SAtom(value=value, kind=kind, range=span)

    def _classify_atom(self, value: str) -> str:
        if value.startswith(":") and _ATTRIBUTE_RE.fullmatch(value):
            return "keyword"
        if _NUMERAL_RE.fullmatch(value):
            return "numeral"
        if _DECIMAL_RE.fullmatch(value):
            return "decimal"
        if _BV_BIN_RE.fullmatch(value) or _BV_HEX_RE.fullmatch(value):
            return "bv"
        return "symbol"

    def _read_string(self) -> SAtom:
        start = self.pos
        self.pos += 1  # opening "
        chars: list[str] = []
        while self.pos < self.length:
            ch = self.text[self.pos]
            if ch == '"':
                # Escaped "" inside strings.
                if self.pos + 1 < self.length and self.text[self.pos + 1] == '"':
                    chars.append('"')
                    self.pos += 2
                    continue
                self.pos += 1
                value = "".join(chars)
                span = SourceRange(start, self.pos, start_char=start, end_char=self.pos)
                return SAtom(value=value, kind="string", range=span)
            chars.append(ch)
            self.pos += 1
        raise SMTLIBError(
            "unterminated string literal",
            code=CODE_UNTERMINATED_STRING,
            range=SourceRange(start, self.length),
        )

    def _read_quoted_symbol(self) -> SAtom:
        start = self.pos
        self.pos += 1  # opening |
        while self.pos < self.length:
            if self.text[self.pos] == "|":
                self.pos += 1
                value = self.text[start + 1 : self.pos - 1]
                span = SourceRange(start, self.pos, start_char=start, end_char=self.pos)
                return SAtom(value=value, kind="quoted", range=span)
            if self.text[self.pos] == "\\":
                # SMT-LIB quoted symbols do not use backslash escapes, but
                # tolerate a literal backslash character.
                self.pos += 1
                if self.pos < self.length:
                    self.pos += 1
                continue
            self.pos += 1
        raise SMTLIBError(
            "unterminated quoted symbol",
            code=CODE_UNTERMINATED_QUOTE,
            range=SourceRange(start, self.length),
        )

    def _read_bv_literal(self) -> SAtom:
        start = self.pos
        self.pos += 1  # #
        if self.pos >= self.length:
            raise SMTLIBError(
                "incomplete bit-vector literal",
                code=CODE_INVALID_LITERAL,
                range=SourceRange(start, self.pos),
            )
        prefix = self.text[self.pos]
        self.pos += 1
        if prefix == "b":
            while self.pos < self.length and self.text[self.pos] in "01":
                self.pos += 1
        elif prefix == "x":
            while self.pos < self.length and self.text[self.pos] in "0123456789abcdefABCDEF":
                self.pos += 1
        else:
            raise SMTLIBError(
                f"invalid bit-vector literal prefix {prefix!r}",
                code=CODE_INVALID_LITERAL,
                range=SourceRange(start, self.pos),
            )
        value = self.text[start : self.pos]
        if value in {"#b", "#x"}:
            raise SMTLIBError(
                "empty bit-vector literal",
                code=CODE_INVALID_LITERAL,
                range=SourceRange(start, self.pos),
            )
        span = SourceRange(start, self.pos, start_char=start, end_char=self.pos)
        return SAtom(value=value, kind="bv", range=span)


def read_sexprs(
    text: str,
    *,
    limits: ParseLimits | None = None,
) -> tuple[tuple[SExpr, ...], tuple[SyntaxDiagnostic, ...]]:
    """Parse *text* into a sequence of top-level S-expressions (bounded)."""

    bounds = limits if limits is not None else ParseLimits()
    return _SExprReader(text, limits=bounds).read_all()


def print_sexpr(node: SExpr) -> str:
    """Deterministic printer for S-expression trees."""

    if isinstance(node, SAtom):
        return _print_atom(node)
    if isinstance(node, SList):
        if not node.items:
            return "()"
        return "(" + " ".join(print_sexpr(item) for item in node.items) + ")"
    raise SMTLIBError(f"unknown S-expression node {type(node)!r}", code=CODE_MALFORMED_SEXPR)


def _print_atom(atom: SAtom) -> str:
    if atom.kind == "string":
        escaped = atom.value.replace('"', '""')
        return f'"{escaped}"'
    if atom.kind == "quoted":
        return f"|{atom.value}|"
    return atom.value


# ---------------------------------------------------------------------------
# Elaborated document model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmtlibSymbolDecl:
    """User-declared function / constant symbol."""

    name: str
    domain: tuple[SmtSort, ...]
    range: SmtSort
    is_const: bool = False

    def to_fun_decl(self) -> SmtFunDecl:
        return SmtFunDecl(
            name=self.name,
            domain=self.domain,
            range=self.range,
            is_const=self.is_const or not self.domain,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": [item.to_dict() for item in self.domain],
            "is_const": self.is_const,
            "name": self.name,
            "range": self.range.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SmtlibCommand:
    """One elaborated top-level command."""

    kind: SmtlibCommandKind | str
    arguments: tuple[Any, ...] = ()
    raw: SExpr | None = None
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, SmtlibCommandKind)
            else SmtlibCommandKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "arguments", tuple(self.arguments))
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise SMTLIBError(
                "command metadata must be immutable JSON data",
                code=CODE_MALFORMED_COMMAND,
            ) from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": list(self.arguments),
            "kind": self.kind.value,
            "metadata": self.metadata.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SmtlibDocument:
    """Elaborated SMT-LIB script with symbol/sort tables and assertions.

    Identity-relevant fields include logic, theories, declarations, and the
    structured assertions.  Printing is deterministic for the admitted subset.
    """

    logic: str = ""
    theories: tuple[str, ...] = ()
    sorts: tuple[SmtSort, ...] = ()
    functions: tuple[SmtlibSymbolDecl, ...] = ()
    datatypes: tuple[SmtDatatypeDecl, ...] = ()
    assertions: tuple[SmtNamedAssertion, ...] = ()
    commands: tuple[SmtlibCommand, ...] = ()
    request_model: bool = False
    request_unsat_core: bool = False
    check_sat: bool = False
    options: FrozenMap = field(default_factory=FrozenMap)
    info: FrozenMap = field(default_factory=FrozenMap)
    profile_id: str = SMTLIB2_PROFILE_ID
    notation_id: str = SMTLIB2_NOTATION_ID
    notation_version: str = SMTLIB2_NOTATION_VERSION
    schema_version: str = SMTLIB_DOCUMENT_SCHEMA_VERSION
    source_text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "logic", str(self.logic or ""))
        object.__setattr__(
            self,
            "theories",
            tuple(str(item) for item in self.theories),
        )
        object.__setattr__(self, "sorts", tuple(self.sorts))
        object.__setattr__(self, "functions", tuple(self.functions))
        object.__setattr__(self, "datatypes", tuple(self.datatypes))
        object.__setattr__(self, "assertions", tuple(self.assertions))
        object.__setattr__(self, "commands", tuple(self.commands))
        object.__setattr__(self, "request_model", bool(self.request_model))
        object.__setattr__(self, "request_unsat_core", bool(self.request_unsat_core))
        object.__setattr__(self, "check_sat", bool(self.check_sat))
        try:
            object.__setattr__(self, "options", FrozenMap(self.options))
            object.__setattr__(self, "info", FrozenMap(self.info))
        except (TypeError, ValueError) as error:
            raise SMTLIBError(
                "options/info must be immutable JSON maps",
                code=CODE_MALFORMED_COMMAND,
            ) from error
        if self.schema_version != SMTLIB_DOCUMENT_SCHEMA_VERSION:
            raise SMTLIBError(
                f"unsupported document schema {self.schema_version!r}",
                code=CODE_MALFORMED_COMMAND,
            )

    @property
    def interface(self) -> str:
        return SMTLIB2_FRONTEND_INTERFACE

    @property
    def sort_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.sorts)

    @property
    def symbol_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.functions)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "assertions": [item.to_dict() for item in self.assertions],
            "check_sat": self.check_sat,
            "datatypes": [item.to_dict() for item in self.datatypes],
            "functions": [item.to_dict() for item in self.functions],
            "info": self.info.to_dict(),
            "interface": SMTLIB2_FRONTEND_INTERFACE,
            "logic": self.logic,
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "options": self.options.to_dict(),
            "profile_id": self.profile_id,
            "request_model": self.request_model,
            "request_unsat_core": self.request_unsat_core,
            "schema_version": self.schema_version,
            "sorts": [item.to_dict() for item in self.sorts],
            "theories": list(self.theories),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["commands"] = [item.to_dict() for item in self.commands]
        return payload

    def feature_tags(self) -> tuple[SmtFeature, ...]:
        """Infer semantic-compiler feature tags from the elaborated document."""

        features: set[SmtFeature] = {SmtFeature.EQUALITY}
        theory_set = {item.casefold() for item in self.theories}
        logic = self.logic.upper()
        if any(tag in theory_set for tag in {"arithmetic", "ints", "reals", "reals_ints"}):
            features.add(SmtFeature.ARITHMETIC)
        if "LIA" in logic or "LRA" in logic or "NIA" in logic or "NRA" in logic:
            features.add(SmtFeature.ARITHMETIC)
        if any(tag in theory_set for tag in {"arrays", "arraysex"}):
            features.add(SmtFeature.ARRAYS)
        if "A" in logic.replace("ALL", ""):
            # Heuristic: AUFLIA etc.
            if "AUFL" in logic or logic.startswith("QF_A") or "ABV" in logic:
                features.add(SmtFeature.ARRAYS)
        if any(tag in theory_set for tag in {"datatypes"}):
            features.add(SmtFeature.DATATYPES)
        if "DT" in logic:
            features.add(SmtFeature.DATATYPES)
        if self.datatypes:
            features.add(SmtFeature.DATATYPES)
        # Quantifiers: presence of forall/exists in assertions.
        if any(_term_has_quantifier(item.formula) for item in self.assertions):
            features.add(SmtFeature.QUANTIFIERS)
        if not logic.startswith("QF_") and logic not in {"", "ALL", "HORN"} and "QF" not in logic:
            if logic not in {"QF_UF"}:
                features.add(SmtFeature.QUANTIFIERS)
        if logic == "HORN" or "horn" in theory_set:
            features.add(SmtFeature.HORN_CHC)
        if any(
            _term_uses_symbols(item.formula, _ARRAY_SYMBOLS) for item in self.assertions
        ):
            features.add(SmtFeature.ARRAYS)
        if any(
            _term_uses_symbols(item.formula, _ARITH_SYMBOLS) for item in self.assertions
        ):
            features.add(SmtFeature.ARITHMETIC)
        return tuple(sorted(features, key=lambda item: item.value))

    def theory_tags(self) -> tuple[SmtTheory, ...]:
        theories: set[SmtTheory] = {SmtTheory.CORE, SmtTheory.EQUALITY}
        for feature in self.feature_tags():
            if feature is SmtFeature.ARITHMETIC:
                theories.add(SmtTheory.ARITHMETIC)
            elif feature is SmtFeature.ARRAYS:
                theories.add(SmtTheory.ARRAYS)
            elif feature is SmtFeature.DATATYPES:
                theories.add(SmtTheory.DATATYPES)
            elif feature is SmtFeature.QUANTIFIERS:
                theories.add(SmtTheory.QUANTIFIERS)
            elif feature is SmtFeature.HORN_CHC:
                theories.add(SmtTheory.HORN)
        return tuple(sorted(theories, key=lambda item: item.value))


def _term_has_quantifier(term: SmtTerm) -> bool:
    if term.kind in {SmtTermKind.FORALL, SmtTermKind.EXISTS}:
        return True
    return any(_term_has_quantifier(arg) for arg in term.arguments)


def _term_uses_symbols(term: SmtTerm, symbols: frozenset[str]) -> bool:
    if term.kind is SmtTermKind.APPLY and term.value in symbols:
        return True
    if term.kind is SmtTermKind.SYMBOL and term.value in symbols:
        return True
    if term.kind in {
        SmtTermKind.ADD,
        SmtTermKind.SUB,
        SmtTermKind.MUL,
        SmtTermKind.DIV,
        SmtTermKind.MOD,
        SmtTermKind.NEG,
        SmtTermKind.LT,
        SmtTermKind.LE,
        SmtTermKind.GT,
        SmtTermKind.GE,
        SmtTermKind.SELECT,
        SmtTermKind.STORE,
    }:
        return True
    return any(_term_uses_symbols(arg, symbols) for arg in term.arguments)


# ---------------------------------------------------------------------------
# Elaborator
# ---------------------------------------------------------------------------


class _Elaborator:
    """Elaborate top-level S-expressions into a typed :class:`SmtlibDocument`."""

    def __init__(self) -> None:
        self.sorts: dict[str, SmtSort] = {
            "Bool": BOOL_SORT,
            "Int": INT_SORT,
            "Real": REAL_SORT,
            "String": SmtSort("String"),
        }
        self.user_sorts: list[SmtSort] = []
        self.functions: dict[str, SmtlibSymbolDecl] = {}
        self.function_order: list[str] = []
        self.datatypes: list[SmtDatatypeDecl] = []
        self.assertions: list[SmtNamedAssertion] = []
        self.commands: list[SmtlibCommand] = []
        self.logic = ""
        self.theories: list[str] = []
        self.request_model = False
        self.request_unsat_core = False
        self.check_sat = False
        self.options: dict[str, Any] = {}
        self.info: dict[str, Any] = {}
        self._locals: list[dict[str, SmtSort]] = [{}]
        self._define_bodies: dict[str, SmtTerm] = {}

    def elaborate(self, forms: Sequence[SExpr]) -> SmtlibDocument:
        if not forms:
            raise SMTLIBElaborationError(
                "no SMT-LIB commands to elaborate",
                code=CODE_EMPTY_INPUT,
            )
        for form in forms:
            self._elaborate_command(form)
        return SmtlibDocument(
            logic=self.logic,
            theories=tuple(self.theories),
            sorts=tuple(self.user_sorts),
            functions=tuple(self.functions[name] for name in self.function_order),
            datatypes=tuple(self.datatypes),
            assertions=tuple(self.assertions),
            commands=tuple(self.commands),
            request_model=self.request_model,
            request_unsat_core=self.request_unsat_core,
            check_sat=self.check_sat,
            options=self.options,
            info=self.info,
        )

    def _elaborate_command(self, form: SExpr) -> None:
        if not isinstance(form, SList) or not form.items:
            raise SMTLIBElaborationError(
                "top-level SMT-LIB form must be a non-empty list",
                code=CODE_MALFORMED_COMMAND,
                range=getattr(form, "range", None),
            )
        head = form.head_symbol()
        if head is None:
            raise SMTLIBElaborationError(
                "command head must be a symbol",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        if head in UNSUPPORTED_COMMANDS:
            raise SMTLIBElaborationError(
                f"unsupported SMT-LIB command {head!r}",
                code=CODE_UNSUPPORTED_COMMAND,
                range=form.range,
                remediation=(
                    "Use only the controlled command subset: "
                    + ", ".join(sorted(SUPPORTED_COMMANDS))
                ),
            )
        if head not in SUPPORTED_COMMANDS:
            raise SMTLIBElaborationError(
                f"unknown SMT-LIB command {head!r}",
                code=CODE_UNKNOWN_COMMAND,
                range=form.range,
                remediation=(
                    "Admit a supported command or omit it; unsupported closed set includes: "
                    + ", ".join(sorted(UNSUPPORTED_COMMANDS))
                ),
            )
        kind = SmtlibCommandKind(head)
        handler = {
            SmtlibCommandKind.SET_LOGIC: self._cmd_set_logic,
            SmtlibCommandKind.SET_INFO: self._cmd_set_info,
            SmtlibCommandKind.SET_OPTION: self._cmd_set_option,
            SmtlibCommandKind.DECLARE_SORT: self._cmd_declare_sort,
            SmtlibCommandKind.DECLARE_FUN: self._cmd_declare_fun,
            SmtlibCommandKind.DECLARE_CONST: self._cmd_declare_const,
            SmtlibCommandKind.DECLARE_DATATYPES: self._cmd_declare_datatypes,
            SmtlibCommandKind.DEFINE_FUN: self._cmd_define_fun,
            SmtlibCommandKind.ASSERT: self._cmd_assert,
            SmtlibCommandKind.CHECK_SAT: self._cmd_check_sat,
            SmtlibCommandKind.GET_MODEL: self._cmd_get_model,
            SmtlibCommandKind.GET_UNSAT_CORE: self._cmd_get_unsat_core,
            SmtlibCommandKind.PUSH: self._cmd_push_pop,
            SmtlibCommandKind.POP: self._cmd_push_pop,
            SmtlibCommandKind.RESET: self._cmd_reset,
            SmtlibCommandKind.EXIT: self._cmd_exit,
        }[kind]
        handler(form, kind)

    def _cmd_set_logic(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 2 or not isinstance(form[1], SAtom):
            raise SMTLIBElaborationError(
                "set-logic requires a single logic symbol",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        logic = form[1].value
        if logic in UNSUPPORTED_THEORIES:
            raise SMTLIBElaborationError(
                f"unsupported SMT-LIB theory/logic {logic!r}",
                code=CODE_UNSUPPORTED_THEORY,
                range=form[1].range,
            )
        if logic not in SUPPORTED_LOGICS:
            raise SMTLIBElaborationError(
                f"unknown or unsupported SMT-LIB logic {logic!r}",
                code=CODE_UNKNOWN_THEORY,
                range=form[1].range,
                remediation="Use a Z3/cvc5 common-fragment logic from the admitted set",
            )
        self.logic = logic
        self.theories = list(_theories_from_logic(logic))
        self.commands.append(SmtlibCommand(kind=kind, arguments=(logic,), raw=form))

    def _cmd_set_info(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) < 2:
            raise SMTLIBElaborationError(
                "set-info requires a keyword",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        key_node = form[1]
        if not isinstance(key_node, SAtom):
            raise SMTLIBElaborationError(
                "set-info key must be a keyword/symbol",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        key = key_node.value
        value: Any = True
        if len(form) >= 3:
            value = _atom_or_print(form[2])
        # Theory annotations via set-info :theory ...
        if key in {":theory", "theory"} and isinstance(value, str):
            if value in UNSUPPORTED_THEORIES:
                raise SMTLIBElaborationError(
                    f"unsupported SMT-LIB theory {value!r}",
                    code=CODE_UNSUPPORTED_THEORY,
                    range=getattr(form[2], "range", form.range),
                )
            if value not in SUPPORTED_THEORIES:
                raise SMTLIBElaborationError(
                    f"unknown SMT-LIB theory {value!r}",
                    code=CODE_UNKNOWN_THEORY,
                    range=getattr(form[2], "range", form.range),
                )
            if value not in self.theories:
                self.theories.append(value)
        self.info[key] = value
        self.commands.append(
            SmtlibCommand(kind=kind, arguments=(key, value), raw=form)
        )

    def _cmd_set_option(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 3 or not isinstance(form[1], SAtom):
            raise SMTLIBElaborationError(
                "set-option requires a keyword and value",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        option = form[1].value
        value = _atom_or_print(form[2])
        if option not in _KEYWORD_OPTION_MODELS and not option.startswith(":"):
            raise SMTLIBElaborationError(
                f"unknown SMT-LIB option {option!r}",
                code=CODE_UNSUPPORTED_FEATURE,
                range=form[1].range,
            )
        self.options[option] = value
        if option == ":produce-models" and _truthy(value):
            self.request_model = True
        if option == ":produce-unsat-cores" and _truthy(value):
            self.request_unsat_core = True
        self.commands.append(
            SmtlibCommand(kind=kind, arguments=(option, value), raw=form)
        )

    def _cmd_declare_sort(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 3:
            raise SMTLIBElaborationError(
                "declare-sort requires name and arity",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        name = _require_symbol(form[1], "sort name")
        arity_atom = form[2]
        if not isinstance(arity_atom, SAtom) or not _NUMERAL_RE.fullmatch(arity_atom.value):
            raise SMTLIBElaborationError(
                "declare-sort arity must be a numeral",
                code=CODE_MALFORMED_COMMAND,
                range=getattr(arity_atom, "range", form.range),
            )
        arity = int(arity_atom.value)
        if name in self.sorts and name not in _BUILTIN_SORTS:
            raise SMTLIBElaborationError(
                f"duplicate sort declaration {name!r}",
                code=CODE_DUPLICATE_SORT,
                range=form[1].range if isinstance(form[1], SAtom) else form.range,
            )
        sort = SmtSort(name, arity=arity)
        self.sorts[name] = sort
        if name not in _BUILTIN_SORTS:
            self.user_sorts.append(sort)
        self.commands.append(
            SmtlibCommand(kind=kind, arguments=(name, arity), raw=form)
        )

    def _cmd_declare_fun(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 4:
            raise SMTLIBElaborationError(
                "declare-fun requires name, domain, and range",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        name = _require_symbol(form[1], "function name")
        if name in self.functions:
            raise SMTLIBElaborationError(
                f"duplicate function declaration {name!r}",
                code=CODE_DUPLICATE_SYMBOL,
                range=form[1].range if isinstance(form[1], SAtom) else form.range,
            )
        domain = self._parse_sort_list(form[2])
        range_sort = self._parse_sort(form[3])
        decl = SmtlibSymbolDecl(
            name=name,
            domain=domain,
            range=range_sort,
            is_const=not domain,
        )
        self.functions[name] = decl
        self.function_order.append(name)
        self.commands.append(
            SmtlibCommand(
                kind=kind,
                arguments=(name, [s.to_dict() for s in domain], range_sort.to_dict()),
                raw=form,
            )
        )

    def _cmd_declare_const(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 3:
            raise SMTLIBElaborationError(
                "declare-const requires name and sort",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        name = _require_symbol(form[1], "constant name")
        if name in self.functions:
            raise SMTLIBElaborationError(
                f"duplicate constant declaration {name!r}",
                code=CODE_DUPLICATE_SYMBOL,
                range=form[1].range if isinstance(form[1], SAtom) else form.range,
            )
        range_sort = self._parse_sort(form[2])
        decl = SmtlibSymbolDecl(name=name, domain=(), range=range_sort, is_const=True)
        self.functions[name] = decl
        self.function_order.append(name)
        self.commands.append(
            SmtlibCommand(
                kind=kind,
                arguments=(name, range_sort.to_dict()),
                raw=form,
            )
        )

    def _cmd_declare_datatypes(self, form: SList, kind: SmtlibCommandKind) -> None:
        # (declare-datatypes () ((Name (cons (sel Sort) ...) ...)))
        if len(form) != 3:
            raise SMTLIBElaborationError(
                "declare-datatypes requires params and declaration list",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        params = form[1]
        decls = form[2]
        if not isinstance(params, SList) or params.items:
            raise SMTLIBElaborationError(
                "parametric datatypes are not in the controlled subset; use ()",
                code=CODE_UNSUPPORTED_FEATURE,
                range=getattr(params, "range", form.range),
            )
        if not isinstance(decls, SList) or not decls.items:
            raise SMTLIBElaborationError(
                "declare-datatypes requires at least one datatype",
                code=CODE_MALFORMED_COMMAND,
                range=getattr(decls, "range", form.range),
            )
        # Pre-register datatype names so recursive selectors can resolve.
        pending_names: list[str] = []
        for decl_form in decls.items:
            if not isinstance(decl_form, SList) or not decl_form.items:
                raise SMTLIBElaborationError(
                    "datatype declaration must be (Name constructor...)",
                    code=CODE_MALFORMED_COMMAND,
                    range=getattr(decl_form, "range", form.range),
                )
            name = _require_symbol(decl_form[0], "datatype name")
            if name in self.sorts and name not in _BUILTIN_SORTS:
                raise SMTLIBElaborationError(
                    f"duplicate datatype/sort {name!r}",
                    code=CODE_DUPLICATE_SORT,
                    range=getattr(decl_form[0], "range", form.range),
                )
            if name in pending_names:
                raise SMTLIBElaborationError(
                    f"duplicate datatype name {name!r} in declaration block",
                    code=CODE_DUPLICATE_SORT,
                    range=getattr(decl_form[0], "range", form.range),
                )
            pending_names.append(name)
            self.sorts[name] = SmtSort(name)
        for decl_form in decls.items:
            datatype = self._parse_datatype_decl(decl_form)
            self.user_sorts.append(SmtSort(datatype.name))
            self.datatypes.append(datatype)
            # Register constructors / selectors as function symbols.
            for constructor in datatype.constructors:
                domain = tuple(sort for _, sort in constructor.selectors)
                self.functions[constructor.name] = SmtlibSymbolDecl(
                    name=constructor.name,
                    domain=domain,
                    range=SmtSort(datatype.name),
                    is_const=not domain,
                )
                self.function_order.append(constructor.name)
                for selector_name, selector_sort in constructor.selectors:
                    self.functions[selector_name] = SmtlibSymbolDecl(
                        name=selector_name,
                        domain=(SmtSort(datatype.name),),
                        range=selector_sort,
                    )
                    self.function_order.append(selector_name)
        self.commands.append(
            SmtlibCommand(
                kind=kind,
                arguments=tuple(item.to_dict() for item in self.datatypes[-len(decls.items) :]),
                raw=form,
            )
        )

    def _parse_datatype_decl(self, form: SExpr) -> SmtDatatypeDecl:
        if not isinstance(form, SList) or len(form) < 2:
            raise SMTLIBElaborationError(
                "datatype declaration must be (Name constructor...)",
                code=CODE_MALFORMED_COMMAND,
                range=getattr(form, "range", None),
            )
        name = _require_symbol(form[0], "datatype name")
        constructors: list[SmtDatatypeConstructor] = []
        for ctor_form in form.items[1:]:
            if not isinstance(ctor_form, SList) or not ctor_form.items:
                raise SMTLIBElaborationError(
                    "constructor must be a non-empty list",
                    code=CODE_MALFORMED_COMMAND,
                    range=getattr(ctor_form, "range", None),
                )
            ctor_name = _require_symbol(ctor_form[0], "constructor name")
            selectors: list[tuple[str, SmtSort]] = []
            for sel in ctor_form.items[1:]:
                if not isinstance(sel, SList) or len(sel) != 2:
                    raise SMTLIBElaborationError(
                        "selector must be (name sort)",
                        code=CODE_MALFORMED_COMMAND,
                        range=getattr(sel, "range", None),
                    )
                sel_name = _require_symbol(sel[0], "selector name")
                sel_sort = self._parse_sort(sel[1])
                selectors.append((sel_name, sel_sort))
            constructors.append(
                SmtDatatypeConstructor(name=ctor_name, selectors=tuple(selectors))
            )
        return SmtDatatypeDecl(name=name, constructors=tuple(constructors))

    def _cmd_define_fun(self, form: SList, kind: SmtlibCommandKind) -> None:
        # (define-fun name ((x Sort) ...) Range body)
        if len(form) != 5:
            raise SMTLIBElaborationError(
                "define-fun requires name, binders, range, and body",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        name = _require_symbol(form[1], "define-fun name")
        if name in self.functions:
            raise SMTLIBElaborationError(
                f"duplicate function definition {name!r}",
                code=CODE_DUPLICATE_SYMBOL,
                range=form[1].range if isinstance(form[1], SAtom) else form.range,
            )
        binders = self._parse_sorted_var_list(form[2])
        range_sort = self._parse_sort(form[3])
        self._push_locals({binder.name: binder.sort for binder in binders})
        try:
            body = self._elaborate_term(form[4])
        finally:
            self._pop_locals()
        domain = tuple(binder.sort for binder in binders)
        decl = SmtlibSymbolDecl(
            name=name, domain=domain, range=range_sort, is_const=not domain
        )
        self.functions[name] = decl
        self.function_order.append(name)
        self._define_bodies[name] = body
        self.commands.append(
            SmtlibCommand(
                kind=kind,
                arguments=(
                    name,
                    [b.to_dict() for b in binders],
                    range_sort.to_dict(),
                    body.to_dict(),
                ),
                raw=form,
            )
        )

    def _cmd_assert(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 2:
            raise SMTLIBElaborationError(
                "assert requires exactly one formula",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        formula_node = form[1]
        name = ""
        # Named assertion: (! formula :named name)
        if (
            isinstance(formula_node, SList)
            and formula_node.head_symbol() == "!"
            and len(formula_node) >= 4
        ):
            formula_node, name = self._unwrap_named(formula_node)
        term = self._elaborate_term(formula_node)
        assertion = SmtNamedAssertion(formula=term, name=name)
        self.assertions.append(assertion)
        self.commands.append(
            SmtlibCommand(
                kind=kind,
                arguments=(assertion.to_dict(),),
                raw=form,
            )
        )

    def _unwrap_named(self, form: SList) -> tuple[SExpr, str]:
        # (! term :named name ...)
        if len(form) < 4:
            raise SMTLIBElaborationError(
                "named term requires (! term :named name)",
                code=CODE_MALFORMED_TERM,
                range=form.range,
            )
        body = form[1]
        name = ""
        index = 2
        while index < len(form):
            key = form[index]
            if not isinstance(key, SAtom):
                raise SMTLIBElaborationError(
                    "attribute key must be a keyword",
                    code=CODE_MALFORMED_TERM,
                    range=form.range,
                )
            if key.value == ":named":
                if index + 1 >= len(form):
                    raise SMTLIBElaborationError(
                        ":named requires a value",
                        code=CODE_MALFORMED_TERM,
                        range=key.range,
                    )
                name = _require_symbol(form[index + 1], "assertion name")
                index += 2
            else:
                # Skip unknown attributes with optional value.
                index += 1
                if index < len(form) and not (
                    isinstance(form[index], SAtom) and form[index].value.startswith(":")
                ):
                    index += 1
        return body, name

    def _cmd_check_sat(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 1:
            raise SMTLIBElaborationError(
                "check-sat takes no arguments",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        self.check_sat = True
        self.commands.append(SmtlibCommand(kind=kind, raw=form))

    def _cmd_get_model(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 1:
            raise SMTLIBElaborationError(
                "get-model takes no arguments",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        self.request_model = True
        self.commands.append(SmtlibCommand(kind=kind, raw=form))

    def _cmd_get_unsat_core(self, form: SList, kind: SmtlibCommandKind) -> None:
        if len(form) != 1:
            raise SMTLIBElaborationError(
                "get-unsat-core takes no arguments",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        self.request_unsat_core = True
        self.commands.append(SmtlibCommand(kind=kind, raw=form))

    def _cmd_push_pop(self, form: SList, kind: SmtlibCommandKind) -> None:
        # Record but do not mutate tables (controlled scripts are flat).
        level = 1
        if len(form) == 2 and isinstance(form[1], SAtom) and _NUMERAL_RE.fullmatch(form[1].value):
            level = int(form[1].value)
        elif len(form) > 2:
            raise SMTLIBElaborationError(
                f"{kind.value} accepts at most one numeral",
                code=CODE_MALFORMED_COMMAND,
                range=form.range,
            )
        self.commands.append(SmtlibCommand(kind=kind, arguments=(level,), raw=form))

    def _cmd_reset(self, form: SList, kind: SmtlibCommandKind) -> None:
        self.sorts = {
            "Bool": BOOL_SORT,
            "Int": INT_SORT,
            "Real": REAL_SORT,
            "String": SmtSort("String"),
        }
        self.user_sorts = []
        self.functions = {}
        self.function_order = []
        self.datatypes = []
        self.assertions = []
        self.logic = ""
        self.theories = []
        self.request_model = False
        self.request_unsat_core = False
        self.check_sat = False
        self.options = {}
        self.info = {}
        self._define_bodies = {}
        self.commands.append(SmtlibCommand(kind=kind, raw=form))

    def _cmd_exit(self, form: SList, kind: SmtlibCommandKind) -> None:
        self.commands.append(SmtlibCommand(kind=kind, raw=form))

    # -- sorts -------------------------------------------------------------

    def _parse_sort_list(self, node: SExpr) -> tuple[SmtSort, ...]:
        if not isinstance(node, SList):
            raise SMTLIBElaborationError(
                "sort list must be a parenthesized list",
                code=CODE_MALFORMED_SORT,
                range=getattr(node, "range", None),
            )
        return tuple(self._parse_sort(item) for item in node.items)

    def _parse_sort(self, node: SExpr) -> SmtSort:
        if isinstance(node, SAtom):
            name = node.value
            if name in self.sorts:
                return self.sorts[name]
            if name in _BUILTIN_SORTS:
                sort = SmtSort(name)
                self.sorts[name] = sort
                return sort
            raise SMTLIBElaborationError(
                f"undeclared sort {name!r}",
                code=CODE_UNDECLARED_SORT,
                range=node.range,
            )
        if not isinstance(node, SList) or not node.items:
            raise SMTLIBElaborationError(
                "malformed sort expression",
                code=CODE_MALFORMED_SORT,
                range=getattr(node, "range", None),
            )
        head = node.head
        # Indexed sort: (_ BitVec n) or (_ FloatingPoint eb sb)
        if isinstance(head, SAtom) and head.value == "_":
            return self._parse_indexed_sort(node)
        if isinstance(head, SAtom) and head.value == "Array":
            if len(node) != 3:
                raise SMTLIBElaborationError(
                    "Array sort requires index and element sorts",
                    code=CODE_MALFORMED_SORT,
                    range=node.range,
                )
            index = self._parse_sort(node[1])
            element = self._parse_sort(node[2])
            return array_sort(index, element)
        if isinstance(head, SAtom):
            name = head.value
            if name not in self.sorts and name not in _BUILTIN_SORTS:
                raise SMTLIBElaborationError(
                    f"undeclared sort constructor {name!r}",
                    code=CODE_UNDECLARED_SORT,
                    range=head.range,
                )
            params = tuple(_sort_param_token(self._parse_sort(item)) for item in node.items[1:])
            return SmtSort(name, arity=len(params), parameters=params)
        raise SMTLIBElaborationError(
            "malformed sort expression",
            code=CODE_MALFORMED_SORT,
            range=node.range,
        )

    def _parse_indexed_sort(self, node: SList) -> SmtSort:
        if len(node) < 3 or not isinstance(node[1], SAtom):
            raise SMTLIBElaborationError(
                "indexed sort requires (_ name index...)",
                code=CODE_MALFORMED_SORT,
                range=node.range,
            )
        name = node[1].value
        indices = []
        for item in node.items[2:]:
            if not isinstance(item, SAtom):
                raise SMTLIBElaborationError(
                    "sort indices must be atoms",
                    code=CODE_MALFORMED_SORT,
                    range=node.range,
                )
            indices.append(item.value)
        if name == "BitVec":
            if len(indices) != 1 or not _NUMERAL_RE.fullmatch(indices[0]):
                raise SMTLIBElaborationError(
                    "BitVec requires a single numeral width",
                    code=CODE_MALFORMED_SORT,
                    range=node.range,
                )
            # Encode as parametric sort; printer rewrites to (_ BitVec n).
            return SmtSort("BitVec", arity=1, parameters=(indices[0],))
        if name == "FloatingPoint":
            if len(indices) != 2:
                raise SMTLIBElaborationError(
                    "FloatingPoint requires eb and sb indices",
                    code=CODE_MALFORMED_SORT,
                    range=node.range,
                )
            return SmtSort("FloatingPoint", arity=2, parameters=tuple(indices))
        raise SMTLIBElaborationError(
            f"unsupported indexed sort {name!r}",
            code=CODE_UNSUPPORTED_FEATURE,
            range=node.range,
        )

    def _parse_sorted_var_list(self, node: SExpr) -> tuple[SmtBinder, ...]:
        if not isinstance(node, SList):
            raise SMTLIBElaborationError(
                "binder list must be parenthesized",
                code=CODE_MALFORMED_TERM,
                range=getattr(node, "range", None),
            )
        binders: list[SmtBinder] = []
        for item in node.items:
            if not isinstance(item, SList) or len(item) != 2:
                raise SMTLIBElaborationError(
                    "binder must be (name sort)",
                    code=CODE_MALFORMED_TERM,
                    range=getattr(item, "range", None),
                )
            name = _require_symbol(item[0], "binder name")
            sort = self._parse_sort(item[1])
            binders.append(SmtBinder(name=name, sort=sort))
        return tuple(binders)

    # -- terms -------------------------------------------------------------

    def _push_locals(self, mapping: Mapping[str, SmtSort]) -> None:
        self._locals.append(dict(mapping))

    def _pop_locals(self) -> None:
        if len(self._locals) > 1:
            self._locals.pop()

    def _lookup_local(self, name: str) -> SmtSort | None:
        for frame in reversed(self._locals):
            if name in frame:
                return frame[name]
        return None

    def _elaborate_term(self, node: SExpr) -> SmtTerm:
        if isinstance(node, SAtom):
            return self._elaborate_atom(node)
        if not isinstance(node, SList) or not node.items:
            raise SMTLIBElaborationError(
                "malformed term",
                code=CODE_MALFORMED_TERM,
                range=getattr(node, "range", None),
            )
        head = node.head
        # Indexed operator: ((_ extract i j) x) or ((_ zero_extend n) x)
        if isinstance(head, SList) and head.head_symbol() == "_":
            return self._elaborate_indexed_app(node)
        if not isinstance(head, SAtom):
            raise SMTLIBElaborationError(
                "application head must be a symbol",
                code=CODE_MALFORMED_TERM,
                range=node.range,
            )
        op = head.value
        if op == "true":
            return term_true()
        if op == "false":
            return term_false()
        if op == "not":
            if len(node) != 2:
                raise SMTLIBElaborationError(
                    "not requires exactly one argument",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return term_not(self._elaborate_term(node[1]))
        if op == "and":
            if len(node) < 3:
                raise SMTLIBElaborationError(
                    "and requires at least two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return term_and(*[self._elaborate_term(item) for item in node.items[1:]])
        if op == "or":
            if len(node) < 3:
                raise SMTLIBElaborationError(
                    "or requires at least two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return term_or(*[self._elaborate_term(item) for item in node.items[1:]])
        if op == "xor":
            if len(node) != 3:
                raise SMTLIBElaborationError(
                    "xor requires exactly two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            left = self._elaborate_term(node[1])
            right = self._elaborate_term(node[2])
            # a xor b ≡ (or (and a (not b)) (and (not a) b))
            return term_or(
                term_and(left, term_not(right)),
                term_and(term_not(left), right),
            )
        if op == "=>":
            if len(node) != 3:
                raise SMTLIBElaborationError(
                    "=> requires exactly two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return term_implies(
                self._elaborate_term(node[1]),
                self._elaborate_term(node[2]),
            )
        if op == "ite":
            if len(node) != 4:
                raise SMTLIBElaborationError(
                    "ite requires exactly three arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return SmtTerm(
                SmtTermKind.ITE,
                arguments=tuple(self._elaborate_term(item) for item in node.items[1:]),
            )
        if op == "=":
            if len(node) != 3:
                raise SMTLIBElaborationError(
                    "= requires exactly two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return term_eq(
                self._elaborate_term(node[1]),
                self._elaborate_term(node[2]),
            )
        if op == "distinct":
            if len(node) < 3:
                raise SMTLIBElaborationError(
                    "distinct requires at least two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return SmtTerm(
                SmtTermKind.DISTINCT,
                arguments=tuple(self._elaborate_term(item) for item in node.items[1:]),
            )
        if op in {"forall", "exists"}:
            return self._elaborate_quantifier(node, op)
        if op == "let":
            return self._elaborate_let(node)
        if op == "!":
            body, _name = self._unwrap_named(node)
            return self._elaborate_term(body)
        if op == "as":
            # (as term sort) — ignore annotation, keep term.
            if len(node) != 3:
                raise SMTLIBElaborationError(
                    "as requires term and sort",
                    code=CODE_MALFORMED_TERM,
                    range=node.range,
                )
            return self._elaborate_term(node[1])
        if op == "+":
            args = tuple(self._elaborate_term(item) for item in node.items[1:])
            if len(args) < 2:
                raise SMTLIBElaborationError(
                    "+ requires at least two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return SmtTerm(SmtTermKind.ADD, arguments=args)
        if op == "-":
            args = tuple(self._elaborate_term(item) for item in node.items[1:])
            if len(args) == 1:
                return SmtTerm(SmtTermKind.NEG, arguments=args)
            if len(args) == 2:
                return SmtTerm(SmtTermKind.SUB, arguments=args)
            raise SMTLIBElaborationError(
                "- requires one or two arguments",
                code=CODE_ARITY_MISMATCH,
                range=node.range,
            )
        if op == "*":
            args = tuple(self._elaborate_term(item) for item in node.items[1:])
            if len(args) < 2:
                raise SMTLIBElaborationError(
                    "* requires at least two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return SmtTerm(SmtTermKind.MUL, arguments=args)
        if op in {"div", "/"}:
            if len(node) != 3:
                raise SMTLIBElaborationError(
                    f"{op} requires exactly two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return SmtTerm(
                SmtTermKind.DIV,
                arguments=(
                    self._elaborate_term(node[1]),
                    self._elaborate_term(node[2]),
                ),
            )
        if op == "mod":
            if len(node) != 3:
                raise SMTLIBElaborationError(
                    "mod requires exactly two arguments",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return SmtTerm(
                SmtTermKind.MOD,
                arguments=(
                    self._elaborate_term(node[1]),
                    self._elaborate_term(node[2]),
                ),
            )
        if op == "<":
            return self._bin(SmtTermKind.LT, node)
        if op == "<=":
            return self._bin(SmtTermKind.LE, node)
        if op == ">":
            return self._bin(SmtTermKind.GT, node)
        if op == ">=":
            return self._bin(SmtTermKind.GE, node)
        if op == "select":
            return self._bin(SmtTermKind.SELECT, node)
        if op == "store":
            if len(node) != 4:
                raise SMTLIBElaborationError(
                    "store requires array, index, and value",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            return SmtTerm(
                SmtTermKind.STORE,
                arguments=tuple(self._elaborate_term(item) for item in node.items[1:]),
            )
        # General application: declared fun, define-fun, or theory symbol.
        if op in self._define_bodies and not node.items[1:]:
            return self._define_bodies[op]
        if (
            op not in self.functions
            and op not in _BUILTIN_FUN_SYMBOLS
            and self._lookup_local(op) is None
            and op not in self._define_bodies
        ):
            raise SMTLIBElaborationError(
                f"undeclared symbol {op!r}",
                code=CODE_UNDECLARED_SYMBOL,
                range=head.range,
            )
        if op in self.functions:
            decl = self.functions[op]
            args = tuple(self._elaborate_term(item) for item in node.items[1:])
            if decl.domain and len(args) != len(decl.domain):
                raise SMTLIBElaborationError(
                    f"symbol {op!r} has arity {len(decl.domain)}; got {len(args)}",
                    code=CODE_ARITY_MISMATCH,
                    range=node.range,
                )
            if not args:
                return term_symbol(op)
            return term_apply(op, *args)
        args = tuple(self._elaborate_term(item) for item in node.items[1:])
        if not args:
            return term_symbol(op)
        return term_apply(op, *args)

    def _bin(self, kind: SmtTermKind, node: SList) -> SmtTerm:
        if len(node) != 3:
            raise SMTLIBElaborationError(
                f"{kind.value} requires exactly two arguments",
                code=CODE_ARITY_MISMATCH,
                range=node.range,
            )
        return SmtTerm(
            kind,
            arguments=(
                self._elaborate_term(node[1]),
                self._elaborate_term(node[2]),
            ),
        )

    def _elaborate_atom(self, atom: SAtom) -> SmtTerm:
        value = atom.value
        if atom.kind == "numeral" or _NUMERAL_RE.fullmatch(value):
            return term_int(int(value))
        if atom.kind == "decimal" or _DECIMAL_RE.fullmatch(value):
            return SmtTerm(SmtTermKind.REAL, value=value)
        if atom.kind == "bv" or _BV_BIN_RE.fullmatch(value) or _BV_HEX_RE.fullmatch(value):
            return SmtTerm(SmtTermKind.SYMBOL, value=value)
        if atom.kind == "string":
            # Represent string literals as raw SMT-LIB text fragments.
            escaped = value.replace('"', '""')
            return SmtTerm(SmtTermKind.RAW, value=f'"{escaped}"')
        if value == "true":
            return term_true()
        if value == "false":
            return term_false()
        if self._lookup_local(value) is not None:
            return term_symbol(value)
        if value in self.functions:
            return term_symbol(value)
        if value in _BUILTIN_FUN_SYMBOLS:
            return term_symbol(value)
        if value in self._define_bodies:
            return self._define_bodies[value]
        # Indexed bv numeral form is handled as (_ bvN w); bare bvN is a symbol.
        if _BV_LITERAL_RE.fullmatch(value):
            return term_symbol(value)
        raise SMTLIBElaborationError(
            f"undeclared symbol {value!r}",
            code=CODE_UNDECLARED_SYMBOL,
            range=atom.range,
        )

    def _elaborate_quantifier(self, node: SList, op: str) -> SmtTerm:
        if len(node) != 3:
            raise SMTLIBElaborationError(
                f"{op} requires binders and body",
                code=CODE_MALFORMED_TERM,
                range=node.range,
            )
        binders = self._parse_sorted_var_list(node[1])
        if not binders:
            raise SMTLIBElaborationError(
                f"{op} requires at least one binder",
                code=CODE_MALFORMED_TERM,
                range=node.range,
            )
        self._push_locals({binder.name: binder.sort for binder in binders})
        try:
            body = self._elaborate_term(node[2])
        finally:
            self._pop_locals()
        kind = SmtTermKind.FORALL if op == "forall" else SmtTermKind.EXISTS
        return SmtTerm(kind, arguments=(body,), binders=binders)

    def _elaborate_let(self, node: SList) -> SmtTerm:
        # (let ((x t) ...) body)
        if len(node) != 3:
            raise SMTLIBElaborationError(
                "let requires bindings and body",
                code=CODE_MALFORMED_TERM,
                range=node.range,
            )
        bindings_node = node[1]
        if not isinstance(bindings_node, SList) or not bindings_node.items:
            raise SMTLIBElaborationError(
                "let bindings must be a non-empty list",
                code=CODE_MALFORMED_TERM,
                range=getattr(bindings_node, "range", node.range),
            )
        # Parallel bindings: elaborate values in outer scope, then bind.
        pairs: list[tuple[str, SmtTerm, SmtSort]] = []
        for binding in bindings_node.items:
            if not isinstance(binding, SList) or len(binding) != 2:
                raise SMTLIBElaborationError(
                    "let binding must be (name term)",
                    code=CODE_MALFORMED_TERM,
                    range=getattr(binding, "range", node.range),
                )
            name = _require_symbol(binding[0], "let variable")
            value = self._elaborate_term(binding[1])
            # Sort is not always known; use Bool as a placeholder when absent.
            sort = value.sort if value.sort is not None else BOOL_SORT
            pairs.append((name, value, sort))
        # Nested let encoding: fold from the outside for multi-binders.
        # SmtTerm LET is not a dedicated kind; expand as sequential substitution
        # via a synthetic quantifier-free representation using apply of a local
        # symbol is incorrect.  Represent multi-let as nested single-lets via
        # RAW only when needed — prefer sequential binder expansion using
        # exists-style local symbols: we encode let as the body with symbols
        # bound in a local frame and *inline* the value by substituting at
        # print time via a dedicated SmtTerm APPLY of a reserved encoding.
        #
        # Practical choice: encode (let ((x t)) body) as body with x registered
        # as a local symbol; for round-trip printing we reconstruct via a
        # synthetic RAW only when the structured term cannot carry let.
        # Use SmtTerm with kind APPLY value="let" is invalid.  The semantic
        # compiler has no LET kind.  We expand let by substitution of the
        # bound term for free occurrences of the variable.
        body_node = node[2]
        # Register locals so free references resolve, then substitute.
        substituted = body_node
        # First elaborate body with locals in scope, then rewrite symbols.
        local_map = {name: value for name, value, _ in pairs}
        self._push_locals({name: sort for name, _, sort in pairs})
        try:
            body = self._elaborate_term(body_node)
        finally:
            self._pop_locals()
        return _substitute_symbols(body, local_map)

    def _elaborate_indexed_app(self, node: SList) -> SmtTerm:
        # ((_ extract i j) x) or ((_ bvN w)) or ((_ zero_extend n) x)
        head = node[0]
        assert isinstance(head, SList)
        if len(head) < 2 or not isinstance(head[1], SAtom):
            raise SMTLIBElaborationError(
                "indexed operator requires (_ name ...)",
                code=CODE_MALFORMED_TERM,
                range=node.range,
            )
        name = head[1].value
        indices = []
        for item in head.items[2:]:
            if not isinstance(item, SAtom):
                raise SMTLIBElaborationError(
                    "operator indices must be atoms",
                    code=CODE_MALFORMED_TERM,
                    range=node.range,
                )
            indices.append(item.value)
        # Indexed bit-vector numeral: (_ bv13 32)
        if name.startswith("bv") and _BV_LITERAL_RE.fullmatch(name) and not node.items[1:]:
            if len(indices) != 1:
                raise SMTLIBElaborationError(
                    "indexed bv numeral requires a width",
                    code=CODE_MALFORMED_TERM,
                    range=node.range,
                )
            rendered = f"(_ {name} {indices[0]})"
            return SmtTerm(SmtTermKind.RAW, value=rendered)
        args = tuple(self._elaborate_term(item) for item in node.items[1:])
        # Represent indexed ops as RAW applications for round-trip fidelity.
        index_text = " ".join(indices)
        op_text = f"(_ {name} {index_text})" if index_text else f"(_ {name})"
        if not args:
            return SmtTerm(SmtTermKind.RAW, value=op_text)
        arg_text = " ".join(arg.render() for arg in args)
        return SmtTerm(SmtTermKind.RAW, value=f"({op_text} {arg_text})")


def _substitute_symbols(term: SmtTerm, mapping: Mapping[str, SmtTerm]) -> SmtTerm:
    """Capture-avoiding substitution of free symbols by term mapping."""

    if term.kind is SmtTermKind.SYMBOL and term.value in mapping:
        return mapping[term.value]
    if term.kind in {SmtTermKind.FORALL, SmtTermKind.EXISTS}:
        bound = {binder.name for binder in term.binders}
        inner_map = {key: value for key, value in mapping.items() if key not in bound}
        body = _substitute_symbols(term.arguments[0], inner_map) if inner_map else term.arguments[0]
        if body is term.arguments[0]:
            return term
        return SmtTerm(term.kind, arguments=(body,), binders=term.binders, value=term.value)
    if not term.arguments:
        return term
    new_args = tuple(_substitute_symbols(arg, mapping) for arg in term.arguments)
    if new_args == term.arguments:
        return term
    return SmtTerm(
        term.kind,
        value=term.value,
        arguments=new_args,
        binders=term.binders,
        sort=term.sort,
    )


def _theories_from_logic(logic: str) -> tuple[str, ...]:
    theories: list[str] = ["Core"]
    upper = logic.upper()
    if upper == "ALL":
        return ("Core", "Ints", "Reals", "ArraysEx", "FixedSizeBitVectors", "Strings", "Datatypes")
    if upper == "HORN":
        return ("Core", "horn")
    if "UF" in upper or upper in {"QF_UF", "UF"}:
        theories.append("equality")
    if "LIA" in upper or "NIA" in upper or "LRA" in upper or "NRA" in upper:
        theories.append("Ints" if "LIA" in upper or "NIA" in upper else "Reals")
        theories.append("arithmetic")
    if "BV" in upper:
        theories.append("FixedSizeBitVectors")
        theories.append("bitvectors")
    if upper.startswith("QF_A") or "AUFL" in upper or "ABV" in upper or "ANIA" in upper:
        theories.append("ArraysEx")
        theories.append("arrays")
    if "DT" in upper:
        theories.append("Datatypes")
        theories.append("datatypes")
    if upper in {"QF_S", "S", "QF_SLIA"} or upper.endswith("_S"):
        theories.append("Strings")
        theories.append("strings")
    if not upper.startswith("QF_") and upper not in {"ALL", "HORN"}:
        theories.append("quantifiers")
    # Deduplicate preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in theories:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _require_symbol(node: SExpr, label: str) -> str:
    if not isinstance(node, SAtom):
        raise SMTLIBElaborationError(
            f"{label} must be a symbol",
            code=CODE_MALFORMED_COMMAND,
            range=getattr(node, "range", None),
        )
    if node.kind in {"numeral", "decimal", "string", "keyword"}:
        raise SMTLIBElaborationError(
            f"{label} must be a symbol, got {node.kind}",
            code=CODE_MALFORMED_COMMAND,
            range=node.range,
        )
    return node.value


def _atom_or_print(node: SExpr) -> Any:
    if isinstance(node, SAtom):
        if node.kind == "numeral":
            return int(node.value)
        if node.kind == "decimal":
            return node.value
        if node.value in {"true", "false"}:
            return node.value == "true"
        return node.value
    return print_sexpr(node)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.casefold() in {"true", "1", "yes"}
    return bool(value)


def _sort_param_token(sort: SmtSort) -> str:
    if sort.parameters:
        return sort.render()
    return sort.name


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class SMTLIB2Printer:
    """Deterministic SMT-LIB2 printer for elaborated documents and terms."""

    def print_document(self, document: SmtlibDocument) -> str:
        if not isinstance(document, SmtlibDocument):
            raise SMTLIBError(
                "print_document requires an SmtlibDocument",
                code=CODE_MALFORMED_COMMAND,
            )
        lines: list[str] = [
            f"; SMT-LIB2 frontend {SMTLIB_MODULE_VERSION}",
            f"; interface: {SMTLIB2_FRONTEND_INTERFACE}",
            f"; profile: {document.profile_id}",
            f"(set-info :smt-lib-version {SMTLIB_VERSION})",
        ]
        if document.logic:
            lines.append(f"(set-logic {document.logic})")
        for key, value in sorted(document.options.to_dict().items()):
            lines.append(f"(set-option {key} {_print_option_value(value)})")
        datatype_names = {item.name for item in document.datatypes}
        for sort in document.sorts:
            if sort.name in _BUILTIN_SORTS or sort.parameters:
                continue
            # Datatype sorts are introduced by declare-datatypes, not declare-sort.
            if sort.name in datatype_names:
                continue
            lines.append(f"(declare-sort {sort.name} {sort.arity})")
        for datatype in document.datatypes:
            lines.append(datatype.render())
        for function in document.functions:
            # Skip constructors/selectors already emitted via datatypes.
            if any(
                function.name == ctor.name
                or any(function.name == sel for sel, _ in ctor.selectors)
                for dt in document.datatypes
                for ctor in dt.constructors
            ):
                continue
            lines.append(_render_fun_decl(function))
        for assertion in document.assertions:
            lines.append(assertion.render())
        if document.check_sat:
            lines.append("(check-sat)")
        if document.request_model:
            lines.append("(get-model)")
        if document.request_unsat_core:
            lines.append("(get-unsat-core)")
        return "\n".join(lines) + "\n"

    def print_term(self, term: SmtTerm) -> str:
        if not isinstance(term, SmtTerm):
            raise SMTLIBError("print_term requires an SmtTerm", code=CODE_MALFORMED_TERM)
        return term.render()

    def print_sort(self, sort: SmtSort) -> str:
        if not isinstance(sort, SmtSort):
            raise SMTLIBError("print_sort requires an SmtSort", code=CODE_MALFORMED_SORT)
        if sort.name == "BitVec" and len(sort.parameters) == 1:
            return f"(_ BitVec {sort.parameters[0]})"
        if sort.name == "FloatingPoint" and len(sort.parameters) == 2:
            return f"(_ FloatingPoint {sort.parameters[0]} {sort.parameters[1]})"
        if sort.name == "Array" and len(sort.parameters) == 2:
            return f"(Array {sort.parameters[0]} {sort.parameters[1]})"
        return sort.render()


def _print_option_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if value in {"true", "false"} or _NUMERAL_RE.fullmatch(value):
            return value
        if _SIMPLE_SYMBOL_RE.fullmatch(value):
            return value
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    return str(value)


def _render_fun_decl(decl: SmtlibSymbolDecl) -> str:
    range_text = _print_sort_static(decl.range)
    if decl.is_const or not decl.domain:
        return f"(declare-const {decl.name} {range_text})"
    domain = " ".join(_print_sort_static(item) for item in decl.domain)
    return f"(declare-fun {decl.name} ({domain}) {range_text})"


def _print_sort_static(sort: SmtSort) -> str:
    if sort.name == "BitVec" and len(sort.parameters) == 1:
        return f"(_ BitVec {sort.parameters[0]})"
    if sort.name == "Array" and len(sort.parameters) == 2:
        return f"(Array {sort.parameters[0]} {sort.parameters[1]})"
    return sort.render()


# ---------------------------------------------------------------------------
# Parse result / public frontend
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SMTLIBParseResult:
    """Typed result of an SMT-LIB2 parse/elaborate attempt."""

    status: ParseStatus
    document: SmtlibDocument | None = None
    forms: tuple[SExpr, ...] = ()
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    printed: str = ""
    schema_version: str = SMTLIB_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = SMTLIB2_FRONTEND_INTERFACE

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


class _SMTLIB2ParserImpl:
    """Notation parser for controlled SMT-LIB2 scripts.

    Interface: ``SMTLIB2Frontend@1``.
    """

    interface: ClassVar[str] = SMTLIB2_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = SMTLIB2_NOTATION_ID
    notation_version: ClassVar[str] = SMTLIB2_NOTATION_VERSION
    profile_id: ClassVar[str] = SMTLIB2_PROFILE_ID

    def __init__(self) -> None:
        self.printer = SMTLIB2Printer()

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:smtlib:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> SMTLIBParseResult:
        del mode  # strict-only subset; recovery is not offered for scripts
        del document_id
        bounds = limits if limits is not None else ParseLimits()
        forms, read_diags = read_sexprs(text, limits=bounds)
        if read_diags and any(item.is_error for item in read_diags):
            status = (
                ParseStatus.REJECTED
                if any(item.code == CODE_INPUT_LIMIT for item in read_diags)
                else ParseStatus.FAILED
            )
            return SMTLIBParseResult(
                status=status,
                forms=forms,
                diagnostics=read_diags,
            )
        if not forms:
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty SMT-LIB input; expected at least one command",
                range=SourceRange(0, 0),
            )
            return SMTLIBParseResult(
                status=ParseStatus.FAILED,
                diagnostics=(diag,),
            )
        try:
            elaborator = _Elaborator()
            document = elaborator.elaborate(forms)
            object.__setattr__(document, "source_text", text)
        except SMTLIBError as error:
            diag = _diag(
                code=error.code,
                message=error.message,
                range=error.range,
                remediation=error.remediation,
            )
            return SMTLIBParseResult(
                status=ParseStatus.FAILED,
                forms=forms,
                diagnostics=read_diags + (diag,),
            )
        printed = self.printer.print_document(document)
        return SMTLIBParseResult(
            status=ParseStatus.OK,
            document=document,
            forms=forms,
            diagnostics=read_diags,
            printed=printed,
        )

    def parse_document(
        self,
        document: SourceDocument,
        *,
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> SMTLIBParseResult:
        if not isinstance(document, SourceDocument):
            raise SMTLIBError(
                "document must be a SourceDocument",
                code=CODE_MALFORMED_COMMAND,
            )
        return self.parse_text(
            document.text,
            document_id=document.document_id,
            limits=limits,
            mode=mode,
        )


# Public class name matching the lazy publication descriptor.
class SMTLIB2Parser(_SMTLIB2ParserImpl):
    """Public SMT-LIB2 parser (``parser:local:smtlib2`` implementation)."""


class SMTLIB2Frontend:
    """Facade for SMT-LIB2 parse / elaborate / print / bridge.

    Interface: ``SMTLIB2Frontend@1``.
    """

    interface: ClassVar[str] = SMTLIB2_FRONTEND_INTERFACE
    notation_id: ClassVar[str] = SMTLIB2_NOTATION_ID
    notation_version: ClassVar[str] = SMTLIB2_NOTATION_VERSION
    profile_id: ClassVar[str] = SMTLIB2_PROFILE_ID
    family_id: ClassVar[str] = SMTLIB2_FAMILY_ID

    def __init__(
        self,
        *,
        semantic_compiler: SoftwareVerificationSMTCompiler | None = None,
    ) -> None:
        self.parser = SMTLIB2Parser()
        self.printer = self.parser.printer
        self.bridge = SMTBridge(semantic_compiler=semantic_compiler)

    def parse_text(self, text: str, **kwargs: Any) -> SMTLIBParseResult:
        return self.parser.parse_text(text, **kwargs)

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> SmtlibDocument:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.document is None:
            raise SMTLIBParseError(
                result.errors[0].message if result.errors else "SMT-LIB parse failed",
                code=result.errors[0].code if result.errors else CODE_MALFORMED_SEXPR,
            )
        return result.document

    def print(self, document: SmtlibDocument) -> str:
        return self.printer.print_document(document)

    def elaborate(self, text: str, **kwargs: Any) -> SmtlibDocument:
        return self.parse_text_or_raise(text, **kwargs)

    def round_trip(self, text: str, **kwargs: Any) -> SMTLIBParseResult:
        """Parse → print → re-parse; success requires symbol/sort preservation."""

        first = self.parse_text(text, **kwargs)
        if not first.ok or first.document is None:
            return first
        printed = self.print(first.document)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:smtlib:1") + ":rt",
            limits=kwargs.get("limits"),
        )
        if not second.ok or second.document is None or first.document is None:
            return second
        if not documents_semantically_compatible(first.document, second.document):
            diag = _diag(
                code=CODE_TYPECHECK_FAILED,
                message="parse/print/parse does not preserve symbol/sort semantics",
                range=SourceRange(0, 0),
            )
            return SMTLIBParseResult(
                status=ParseStatus.FAILED,
                document=second.document,
                forms=second.forms,
                diagnostics=second.diagnostics + (diag,),
                printed=printed,
            )
        return SMTLIBParseResult(
            status=ParseStatus.OK,
            document=second.document,
            forms=second.forms,
            diagnostics=second.diagnostics,
            printed=printed,
        )

    def to_obligation(
        self,
        document: SmtlibDocument,
        *,
        obligation_id: str = "obl:smtlib:1",
        query_mode: SmtQueryMode | str = SmtQueryMode.SATISFIABILITY,
    ) -> SmtObligation:
        return self.bridge.to_obligation(
            document,
            obligation_id=obligation_id,
            query_mode=query_mode,
        )

    def compile(
        self,
        document: SmtlibDocument,
        *,
        obligation_id: str = "obl:smtlib:1",
        query_mode: SmtQueryMode | str = SmtQueryMode.SATISFIABILITY,
    ):
        return self.bridge.compile(
            document,
            obligation_id=obligation_id,
            query_mode=query_mode,
        )


def documents_semantically_compatible(
    left: SmtlibDocument,
    right: SmtlibDocument,
) -> bool:
    """Return True when symbol/sort tables and assertion shapes match."""

    if left.logic != right.logic:
        return False
    if left.sort_names != right.sort_names:
        return False
    if left.symbol_names != right.symbol_names:
        return False
    if len(left.assertions) != len(right.assertions):
        return False
    if left.request_model != right.request_model:
        return False
    if left.request_unsat_core != right.request_unsat_core:
        return False
    for l_decl, r_decl in zip(left.functions, right.functions):
        if l_decl.name != r_decl.name:
            return False
        if _sort_key(l_decl.range) != _sort_key(r_decl.range):
            return False
        if len(l_decl.domain) != len(r_decl.domain):
            return False
        for ls, rs in zip(l_decl.domain, r_decl.domain):
            if _sort_key(ls) != _sort_key(rs):
                return False
    for l_assert, r_assert in zip(left.assertions, right.assertions):
        if l_assert.name != r_assert.name:
            return False
        if l_assert.formula.render() != r_assert.formula.render():
            return False
    return True


def _sort_key(sort: SmtSort) -> tuple[Any, ...]:
    return (sort.name, sort.arity, sort.parameters)


def _datatype_member_names(datatypes: Sequence[SmtDatatypeDecl]) -> frozenset[str]:
    names: set[str] = set()
    for datatype in datatypes:
        for constructor in datatype.constructors:
            names.add(constructor.name)
            for selector_name, _sort in constructor.selectors:
                names.add(selector_name)
    return frozenset(names)


# ---------------------------------------------------------------------------
# SMT bridge (typed semantic compiler)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SMTBridgeResult:
    """Bridge output: obligation (+ optional compilation)."""

    obligation: SmtObligation
    compilation: Any | None = None
    document: SmtlibDocument | None = None
    schema_version: str = SMTLIB_BRIDGE_SCHEMA_VERSION

    interface: ClassVar[str] = SMTLIB2_FRONTEND_INTERFACE

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "interface": self.interface,
            "obligation": self.obligation.to_dict(),
            "schema_version": self.schema_version,
        }
        if self.compilation is not None and hasattr(self.compilation, "to_dict"):
            payload["compilation"] = self.compilation.to_dict()
        if self.document is not None:
            payload["document"] = self.document.to_dict()
        return payload


class SMTBridge:
    """Lower elaborated SMT-LIB documents into typed SMT obligations.

    Reuses :class:`SoftwareVerificationSMTCompiler` for theory-aware script
    emission rather than re-implementing theory semantics.
    """

    interface: ClassVar[str] = SMTLIB2_FRONTEND_INTERFACE

    def __init__(
        self,
        *,
        semantic_compiler: SoftwareVerificationSMTCompiler | None = None,
    ) -> None:
        self._compiler = semantic_compiler or SoftwareVerificationSMTCompiler()

    def to_obligation(
        self,
        document: SmtlibDocument,
        *,
        obligation_id: str = "obl:smtlib:1",
        query_mode: SmtQueryMode | str = SmtQueryMode.SATISFIABILITY,
    ) -> SmtObligation:
        if not isinstance(document, SmtlibDocument):
            raise SMTLIBBridgeError(
                "bridge requires an SmtlibDocument",
                code=CODE_BRIDGE_FAILED,
            )
        mode = (
            query_mode
            if isinstance(query_mode, SmtQueryMode)
            else SmtQueryMode(str(query_mode))
        )
        features = document.feature_tags() or (SmtFeature.EQUALITY,)
        theories = document.theory_tags()
        datatype_members = _datatype_member_names(document.datatypes)
        functions = tuple(
            item.to_fun_decl()
            for item in document.functions
            if item.name not in datatype_members
        )
        # Datatype constructors/selectors are emitted via declare-datatypes.
        if not document.assertions and mode is not SmtQueryMode.FIXED_POINT:
            goal = term_true()
            assumptions: tuple[SmtNamedAssertion, ...] = ()
        elif len(document.assertions) == 1 and not document.assertions[0].name:
            goal = document.assertions[0].formula
            assumptions = ()
        elif document.assertions:
            # Last assertion is the goal; preceding ones are assumptions.
            if len(document.assertions) == 1:
                goal = document.assertions[0].formula
                assumptions = ()
            else:
                assumptions = tuple(document.assertions[:-1])
                goal = document.assertions[-1].formula
        else:
            goal = term_true()
            assumptions = ()

        try:
            return SmtObligation(
                obligation_id=obligation_id,
                query_mode=mode,
                features=features,
                goal=goal,
                assumptions=assumptions,
                sorts=document.sorts,
                functions=functions,
                datatypes=document.datatypes,
                theories=theories,
                request_model=document.request_model,
                request_unsat_core=document.request_unsat_core,
                logic=document.logic,
                attributes={
                    "notation_id": document.notation_id,
                    "notation_version": document.notation_version,
                    "profile_id": document.profile_id,
                    "source_interface": SMTLIB2_FRONTEND_INTERFACE,
                },
            )
        except Exception as error:  # noqa: BLE001 - bridge fail-closed
            raise SMTLIBBridgeError(
                f"failed to lower SMT-LIB document to obligation: {error}",
                code=CODE_BRIDGE_FAILED,
            ) from error

    def compile(
        self,
        document: SmtlibDocument,
        *,
        obligation_id: str = "obl:smtlib:1",
        query_mode: SmtQueryMode | str = SmtQueryMode.SATISFIABILITY,
    ) -> SMTBridgeResult:
        obligation = self.to_obligation(
            document,
            obligation_id=obligation_id,
            query_mode=query_mode,
        )
        compilation = self._compiler.compile(obligation)
        return SMTBridgeResult(
            obligation=obligation,
            compilation=compilation,
            document=document,
        )

    def from_obligation(self, obligation: SmtObligation) -> SmtlibDocument:
        """Lift a typed obligation back into an SMT-LIB document (lossy inverse)."""

        if not isinstance(obligation, SmtObligation):
            raise SMTLIBBridgeError(
                "from_obligation requires an SmtObligation",
                code=CODE_BRIDGE_FAILED,
            )
        functions = tuple(
            SmtlibSymbolDecl(
                name=item.name,
                domain=item.domain,
                range=item.range,
                is_const=item.is_const,
            )
            for item in obligation.functions
        )
        assertions: list[SmtNamedAssertion] = list(obligation.assumptions)
        if obligation.goal is not None:
            if obligation.query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
                assertions.append(
                    SmtNamedAssertion(formula=term_not(obligation.goal), name="goal_neg")
                )
            else:
                assertions.append(SmtNamedAssertion(formula=obligation.goal, name="goal"))
        return SmtlibDocument(
            logic=obligation.logic,
            theories=tuple(item.value for item in obligation.theories),
            sorts=obligation.sorts,
            functions=functions,
            datatypes=obligation.datatypes,
            assertions=tuple(assertions),
            request_model=obligation.request_model,
            request_unsat_core=obligation.request_unsat_core,
            check_sat=True,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_smtlib2(
    text: str,
    *,
    document_id: str = "doc:smtlib:1",
    limits: ParseLimits | None = None,
) -> SMTLIBParseResult:
    """Parse *text* as controlled SMT-LIB2 and elaborate into a document."""

    return SMTLIB2Frontend().parse_text(
        text, document_id=document_id, limits=limits
    )


def print_smtlib2(document: SmtlibDocument) -> str:
    """Print an elaborated SMT-LIB document."""

    return SMTLIB2Printer().print_document(document)


def elaborate_smtlib2(text: str, **kwargs: Any) -> SmtlibDocument:
    """Parse and elaborate, raising on failure."""

    return SMTLIB2Frontend().parse_text_or_raise(text, **kwargs)


def parse_print_parse_smtlib2(text: str, **kwargs: Any) -> SMTLIBParseResult:
    """Parse/print/parse with symbol/sort preservation check."""

    return SMTLIB2Frontend().round_trip(text, **kwargs)


def bridge_smtlib2_to_obligation(
    text: str,
    *,
    obligation_id: str = "obl:smtlib:1",
    query_mode: SmtQueryMode | str = SmtQueryMode.SATISFIABILITY,
) -> SmtObligation:
    """Parse SMT-LIB text and lower it to a typed SMT obligation."""

    frontend = SMTLIB2Frontend()
    document = frontend.parse_text_or_raise(text)
    return frontend.to_obligation(
        document, obligation_id=obligation_id, query_mode=query_mode
    )


__all__ = [
    "SMTLIB2_FAMILY_ID",
    "SMTLIB2_FRONTEND_INTERFACE",
    "SMTLIB2_NOTATION_ID",
    "SMTLIB2_NOTATION_VERSION",
    "SMTLIB2_PROFILE_ID",
    "SMTLIB_MODULE_VERSION",
    "SMTLIB_PARSE_RESULT_SCHEMA_VERSION",
    "SUPPORTED_COMMANDS",
    "SUPPORTED_LOGICS",
    "SUPPORTED_THEORIES",
    "UNSUPPORTED_COMMANDS",
    "UNSUPPORTED_THEORIES",
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
    "SAtom",
    "SList",
    "SExpr",
    "SMTLIB2Frontend",
    "SMTLIB2Parser",
    "SMTLIB2Printer",
    "SMTLIBBridgeError",
    "SMTLIBElaborationError",
    "SMTLIBError",
    "SMTLIBParseError",
    "SMTLIBParseResult",
    "SMTBridge",
    "SMTBridgeResult",
    "SmtlibCommand",
    "SmtlibCommandKind",
    "SmtlibDocument",
    "SmtlibSymbolDecl",
    "bridge_smtlib2_to_obligation",
    "documents_semantically_compatible",
    "elaborate_smtlib2",
    "parse_print_parse_smtlib2",
    "parse_smtlib2",
    "print_sexpr",
    "print_smtlib2",
    "read_sexprs",
]
