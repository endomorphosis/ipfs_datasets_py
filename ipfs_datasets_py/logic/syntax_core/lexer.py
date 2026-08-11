"""Bounded, deterministic lexer for the logic syntax core.

Interface: ``BoundedLexer@1``.

Whitespace and newlines are never placed into token lexemes (the
``LogicToken`` contract rejects surrounding whitespace).  They are recorded
as leading trivia ranges on the following token (or trailing trivia on EOF).

Unknown input is never logged-and-skipped: strict mode rejects with an error
diagnostic; recovery mode emits an explicit ``error`` token and continues.
All configured resource bounds terminate deterministically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.contracts import (
    DiagnosticSeverity,
    LogicToken,
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SourceMap,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import (
    CODE_COMMENT_DEPTH,
    CODE_CONFUSABLE_CHARACTER,
    CODE_DIAGNOSTIC_LIMIT,
    CODE_INPUT_LIMIT,
    CODE_MALFORMED_NUMBER,
    CODE_TOKEN_LIMIT,
    CODE_UNKNOWN_CHARACTER,
    CODE_UNTERMINATED_COMMENT,
    CODE_UNTERMINATED_STRING,
    DiagnosticSink,
    build_token_source_map,
)

BOUNDED_LEXER_INTERFACE: Final = "BoundedLexer@1"
LEXER_MODULE_VERSION: Final = "1.0.0"

# Longest-first multi-character ASCII operators.
_MULTI_CHAR_OPERATORS: Final[tuple[str, ...]] = (
    "<=>",
    "<->",
    "==>",
    "=>",
    "->",
    "<-",
    "<=",
    ">=",
    "!=",
    "==",
    "/=",
    "&&",
    "||",
    "**",
    "..",
    "::",
)

_SINGLE_CHAR_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "&",
        "|",
        "!",
        "~",
        "+",
        "-",
        "*",
        "/",
        "%",
        "^",
        "<",
        ">",
        "=",
        "?",
        "@",
        "$",
        "\\",
    }
)

_SINGLE_CHAR_SYMBOLS: Final[frozenset[str]] = frozenset(
    {
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
        ",",
        ".",
        ":",
        ";",
    }
)

# Unicode logical operators and quantifiers.
_UNICODE_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "∧",
        "∨",
        "¬",
        "→",
        "⇒",
        "↔",
        "⇔",
        "⊕",
        "⊗",
        "∀",
        "∃",
        "⊤",
        "⊥",
        "⊨",
        "⊢",
        "∈",
        "∉",
        "⊆",
        "⊂",
        "∪",
        "∩",
        "≠",
        "≤",
        "≥",
        "□",
        "◇",
        "◊",
        "○",
        "●",
    }
)

_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "or",
        "not",
        "implies",
        "iff",
        "xor",
        "forall",
        "exists",
        "true",
        "false",
        "if",
        "then",
        "else",
        "let",
        "in",
        "where",
    }
)

# Homoglyph / confusable forms of ASCII operators or letters commonly abused
# in adversarial inputs. Mapped character -> confusable label.
_CONFUSABLES: Final[Mapping[str, str]] = {
    "\u2010": "hyphen",  # ‐
    "\u2011": "hyphen",
    "\u2012": "hyphen",
    "\u2013": "hyphen",  # –
    "\u2014": "hyphen",  # —
    "\u2212": "minus",  # −
    "\uff01": "exclamation",  # ！
    "\uff06": "ampersand",  # ＆
    "\uff5c": "pipe",  # ｜
    "\u00a0": "nbsp",  # non-breaking space treated as confusable whitespace
    "\u200b": "zero-width-space",
    "\u200c": "zero-width-non-joiner",
    "\u200d": "zero-width-joiner",
    "\ufeff": "bom",
}


@dataclass(frozen=True, slots=True)
class LexResult:
    """Immutable result of one bounded lex pass."""

    tokens: tuple[LogicToken, ...]
    diagnostics: tuple[SyntaxDiagnostic, ...]
    source_map: SourceMap
    status: ParseStatus
    mode: ParseMode = ParseMode.STRICT
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK

    @property
    def has_errors(self) -> bool:
        return any(
            item.severity in {DiagnosticSeverity.ERROR, DiagnosticSeverity.FATAL}
            for item in self.diagnostics
        )


class BoundedLexer:
    """Deterministic, resource-bounded lexer.

    Interface: ``BoundedLexer@1``.
    """

    interface: ClassVar[str] = BOUNDED_LEXER_INTERFACE

    def __init__(
        self,
        *,
        keywords: Sequence[str] | None = None,
        multi_char_operators: Sequence[str] | None = None,
    ) -> None:
        self._keywords = frozenset(
            item.casefold() for item in (keywords if keywords is not None else _KEYWORDS)
        )
        ops = tuple(
            multi_char_operators
            if multi_char_operators is not None
            else _MULTI_CHAR_OPERATORS
        )
        # Longest match first; stable within equal length.
        self._multi_ops = tuple(sorted(ops, key=lambda item: (-len(item), item)))

    def lex(
        self,
        document: SourceDocument,
        *,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
    ) -> LexResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("lex requires a SourceDocument")
        if isinstance(mode, ParseMode):
            parse_mode = mode
        else:
            try:
                parse_mode = ParseMode(str(mode))
            except ValueError as error:
                raise SyntaxContractError(
                    f"mode must be a ParseMode value; got {mode!r}"
                ) from error
        bounds = limits if limits is not None else ParseLimits()
        if not isinstance(bounds, ParseLimits):
            raise SyntaxContractError("limits must be a ParseLimits instance")

        if document.byte_length > bounds.max_input_bytes:
            sink = DiagnosticSink(max_diagnostics=bounds.max_diagnostics)
            sink.emit(
                code=CODE_INPUT_LIMIT,
                message=(
                    f"source length {document.byte_length} exceeds "
                    f"max_input_bytes {bounds.max_input_bytes}"
                ),
                severity=DiagnosticSeverity.FATAL,
                range=SourceRange(start=0, end=min(document.byte_length, bounds.max_input_bytes)),
            )
            eof = _eof_token(document, char_pos=0, byte_pos=0, token_index=1)
            source_map = build_token_source_map(document, (eof,))
            return LexResult(
                tokens=(eof,),
                diagnostics=sink.items,
                source_map=source_map,
                status=ParseStatus.REJECTED,
                mode=parse_mode,
            )

        engine = _LexerEngine(
            document=document,
            mode=parse_mode,
            limits=bounds,
            keywords=self._keywords,
            multi_ops=self._multi_ops,
        )
        return engine.run()


def lex_document(
    document: SourceDocument,
    *,
    mode: ParseMode | str = ParseMode.STRICT,
    limits: ParseLimits | None = None,
    keywords: Sequence[str] | None = None,
    multi_char_operators: Sequence[str] | None = None,
) -> LexResult:
    """Convenience entry point matching :class:`BoundedLexer.lex`."""

    return BoundedLexer(
        keywords=keywords,
        multi_char_operators=multi_char_operators,
    ).lex(document, mode=mode, limits=limits)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class _LexerEngine:
    def __init__(
        self,
        *,
        document: SourceDocument,
        mode: ParseMode,
        limits: ParseLimits,
        keywords: frozenset[str],
        multi_ops: tuple[str, ...],
    ) -> None:
        self.document = document
        self.mode = mode
        self.limits = limits
        self.keywords = keywords
        self.multi_ops = multi_ops
        self.text = document.text
        self.encoding = document.encoding
        self.length = len(self.text)
        self.pos = 0  # character offset
        self.tokens: list[LogicToken] = []
        self.sink = DiagnosticSink(max_diagnostics=limits.max_diagnostics)
        self.token_seq = 0
        self.stopped = False
        self.had_error = False
        self.pending_leading: list[SourceRange] = []

    def run(self) -> LexResult:
        # Reserve one slot for the mandatory EOF token so total length never
        # exceeds ParseLimits.max_tokens (see ParseArtifact.validate_against).
        while self.pos < self.length and not self.stopped:
            if not self._can_emit_non_eof():
                self._token_limit()
                break
            self._lex_one()

        # Remaining whitespace becomes leading trivia on EOF.
        if not self.stopped:
            self._consume_whitespace_as_pending()

        eof_leading = tuple(self.pending_leading)
        self.pending_leading = []
        eof = self._make_token(
            kind=TokenKind.EOF,
            lexeme="",
            char_start=self.pos,
            char_end=self.pos,
            leading=eof_leading,
            trailing=(),
        )
        self.tokens.append(eof)

        if self.sink.capped and not any(
            item.code == CODE_DIAGNOSTIC_LIMIT for item in self.sink.items
        ):
            # Best-effort note when we hit the diagnostic ceiling mid-stream.
            # Only emitted if capacity remains (otherwise already full).
            pass

        status = self._status()
        source_map = build_token_source_map(self.document, self.tokens)
        return LexResult(
            tokens=tuple(self.tokens),
            diagnostics=self.sink.items,
            source_map=source_map,
            status=status,
            mode=self.mode,
            metadata={
                "token_count": len(self.tokens),
                "diagnostic_count": len(self.sink.items),
            },
        )

    def _status(self) -> ParseStatus:
        if any(
            item.severity == DiagnosticSeverity.FATAL for item in self.sink.items
        ):
            return (
                ParseStatus.REJECTED
                if self.mode == ParseMode.STRICT
                else ParseStatus.FAILED
            )
        if self.had_error or self.sink.items:
            if self.mode == ParseMode.STRICT:
                return ParseStatus.FAILED
            return ParseStatus.RECOVERED
        return ParseStatus.OK

    def _max_non_eof(self) -> int:
        return max(0, self.limits.max_tokens - 1)

    def _can_emit_non_eof(self) -> bool:
        return len(self.tokens) < self._max_non_eof()

    def _token_limit(self) -> None:
        if self.stopped and any(
            item.code == CODE_TOKEN_LIMIT for item in self.sink.items
        ):
            return
        self.had_error = True
        start_byte, start_char = self._byte_char_at(self.pos)
        self.sink.emit(
            code=CODE_TOKEN_LIMIT,
            message=(
                f"token limit of {self.limits.max_tokens} exceeded; "
                "lexing terminated deterministically"
            ),
            severity=DiagnosticSeverity.FATAL,
            range=SourceRange(
                start=start_byte,
                end=start_byte,
                start_char=start_char,
                end_char=start_char,
            ),
            remediation="Increase ParseLimits.max_tokens or reduce input size",
        )
        self.stopped = True

    def _lex_one(self) -> None:
        # Collect leading whitespace/newlines as trivia (never lexeme content).
        self._consume_whitespace_as_pending()
        if self.pos >= self.length or self.stopped:
            return

        if not self._can_emit_non_eof():
            self._token_limit()
            return

        ch = self.text[self.pos]

        if ch == "\x00":
            self._error_char(
                code=CODE_UNKNOWN_CHARACTER,
                message="NUL character is not permitted in source",
                severity=DiagnosticSeverity.FATAL,
            )
            return

        if ch in _CONFUSABLES:
            label = _CONFUSABLES[ch]
            self._error_char(
                code=CODE_CONFUSABLE_CHARACTER,
                message=f"confusable character {ch!r} ({label}) is not permitted",
                severity=DiagnosticSeverity.ERROR,
            )
            return

        if ch in {"'", '"'}:
            self._lex_string(ch)
            return

        if ch == "/" and self._peek(1) == "/":
            self._lex_line_comment()
            return

        if ch == "/" and self._peek(1) == "*":
            self._lex_block_comment()
            return

        if ch == "#":
            # Line comment starting with `#` (common in logic DSLs).
            self._lex_hash_comment()
            return

        if ch.isdigit() or (ch == "." and (self._peek(1) or "").isdigit()):
            self._lex_number()
            return

        if ch.isalpha() or ch == "_":
            self._lex_identifier_or_keyword()
            return

        # Multi-char ASCII operators (longest first).
        for op in self.multi_ops:
            if self.text.startswith(op, self.pos):
                self._emit_operator(op)
                return

        if ch in _UNICODE_OPERATORS:
            self._emit_operator(ch)
            return

        if ch in _SINGLE_CHAR_OPERATORS:
            self._emit_operator(ch)
            return

        if ch in _SINGLE_CHAR_SYMBOLS:
            self._emit_symbol(ch)
            return

        # Unknown character.
        self._error_char(
            code=CODE_UNKNOWN_CHARACTER,
            message=f"unknown character {ch!r}",
            severity=DiagnosticSeverity.ERROR,
        )

    def _consume_whitespace_as_pending(self) -> None:
        start = self.pos
        while self.pos < self.length and self.text[self.pos].isspace():
            self.pos += 1
        if self.pos > start:
            self.pending_leading.append(self._range(start, self.pos))

    def _lex_identifier_or_keyword(self) -> None:
        start = self.pos
        self.pos += 1
        while self.pos < self.length:
            ch = self.text[self.pos]
            if ch.isalnum() or ch == "_":
                self.pos += 1
                continue
            break
        lexeme = self.text[start : self.pos]
        # Lexeme is identifier text only — never includes surrounding whitespace.
        kind = (
            TokenKind.KEYWORD
            if lexeme.casefold() in self.keywords
            else TokenKind.IDENTIFIER
        )
        self._emit(kind=kind, lexeme=lexeme, char_start=start, char_end=self.pos)

    def _lex_number(self) -> None:
        start = self.pos
        # Integer / decimal; optional leading dot already checked by caller.
        if self.text[self.pos] == ".":
            self.pos += 1
        while self.pos < self.length and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos < self.length and self.text[self.pos] == ".":
            # Fractional part.
            nxt = self._peek(1)
            if nxt is not None and nxt.isdigit():
                self.pos += 1
                while self.pos < self.length and self.text[self.pos].isdigit():
                    self.pos += 1
            elif self.text[start] != ".":
                # Trailing lone dot is not part of the number.
                pass
        # Exponent.
        if self.pos < self.length and self.text[self.pos] in {"e", "E"}:
            exp_pos = self.pos
            self.pos += 1
            if self.pos < self.length and self.text[self.pos] in {"+", "-"}:
                self.pos += 1
            if self.pos < self.length and self.text[self.pos].isdigit():
                while self.pos < self.length and self.text[self.pos].isdigit():
                    self.pos += 1
            else:
                # Roll back incomplete exponent; report malformed.
                self.pos = exp_pos
                lexeme = self.text[start : self.pos]
                if not lexeme:
                    lexeme = self.text[start : start + 1]
                    self.pos = start + 1
                self.had_error = True
                self.sink.emit(
                    code=CODE_MALFORMED_NUMBER,
                    message=f"malformed numeric literal near {lexeme!r}",
                    severity=DiagnosticSeverity.ERROR,
                    range=self._range(start, self.pos),
                )
                if self.mode is ParseMode.STRICT:
                    self.stopped = True
                    return
                self._emit(
                    kind=TokenKind.ERROR,
                    lexeme=lexeme,
                    char_start=start,
                    char_end=self.pos,
                )
                return

        lexeme = self.text[start : self.pos]
        if not lexeme or lexeme == ".":
            self._error_char(
                code=CODE_MALFORMED_NUMBER,
                message="malformed numeric literal",
                severity=DiagnosticSeverity.ERROR,
            )
            return
        self._emit(
            kind=TokenKind.NUMBER,
            lexeme=lexeme,
            char_start=start,
            char_end=self.pos,
        )

    def _lex_string(self, quote: str) -> None:
        start = self.pos
        self.pos += 1  # opening quote
        closed = False
        while self.pos < self.length:
            ch = self.text[self.pos]
            if ch == "\\":
                # Accept a single escaped character when present.
                self.pos += 1
                if self.pos < self.length:
                    self.pos += 1
                continue
            if ch == quote:
                self.pos += 1
                closed = True
                break
            if ch == "\x00":
                break
            self.pos += 1
        lexeme = self.text[start : self.pos]
        if not closed:
            self.had_error = True
            self.sink.emit(
                code=CODE_UNTERMINATED_STRING,
                message="unterminated string literal",
                severity=DiagnosticSeverity.ERROR,
                range=self._range(start, self.pos),
                remediation=f"Close the string with {quote}",
            )
            if self.mode is ParseMode.STRICT:
                self.stopped = True
            self._emit(
                kind=TokenKind.ERROR,
                lexeme=_safe_lexeme(lexeme, fallback=quote),
                char_start=start,
                char_end=self.pos,
            )
            return
        # String lexeme includes quotes; internal whitespace is fine.
        # Quotes guarantee the value does not have surrounding whitespace.
        self._emit(
            kind=TokenKind.STRING,
            lexeme=lexeme,
            char_start=start,
            char_end=self.pos,
        )

    def _lex_line_comment(self) -> None:
        start = self.pos
        self.pos += 2  # //
        while self.pos < self.length and self.text[self.pos] not in {"\n", "\r"}:
            self.pos += 1
        lexeme = self.text[start : self.pos]
        self._emit(
            kind=TokenKind.COMMENT,
            lexeme=lexeme,
            char_start=start,
            char_end=self.pos,
        )

    def _lex_hash_comment(self) -> None:
        start = self.pos
        self.pos += 1  # #
        while self.pos < self.length and self.text[self.pos] not in {"\n", "\r"}:
            self.pos += 1
        lexeme = self.text[start : self.pos]
        self._emit(
            kind=TokenKind.COMMENT,
            lexeme=lexeme,
            char_start=start,
            char_end=self.pos,
        )

    def _lex_block_comment(self) -> None:
        start = self.pos
        self.pos += 2  # /*
        depth = 1
        max_depth = self.limits.max_depth
        while self.pos < self.length and depth > 0:
            if (
                self.text[self.pos] == "/"
                and self._peek(1) == "*"
            ):
                depth += 1
                if depth > max_depth:
                    self.had_error = True
                    self.sink.emit(
                        code=CODE_COMMENT_DEPTH,
                        message=(
                            f"block comment nesting depth exceeds max_depth "
                            f"{max_depth}"
                        ),
                        severity=DiagnosticSeverity.FATAL,
                        range=self._range(self.pos, min(self.pos + 2, self.length)),
                    )
                    # Consume the rest of the input as part of the error span
                    # but terminate deterministically.
                    self.pos = self.length
                    self.stopped = True
                    lexeme = self.text[start : self.pos]
                    # Strip only if surrounding whitespace slipped in (should not).
                    safe = _safe_lexeme(lexeme, fallback="/*")
                    self._emit(
                        kind=TokenKind.ERROR,
                        lexeme=safe,
                        char_start=start,
                        char_end=self.pos,
                    )
                    return
                self.pos += 2
                continue
            if (
                self.text[self.pos] == "*"
                and self._peek(1) == "/"
            ):
                depth -= 1
                self.pos += 2
                continue
            self.pos += 1

        lexeme = self.text[start : self.pos]
        if depth != 0:
            self.had_error = True
            self.sink.emit(
                code=CODE_UNTERMINATED_COMMENT,
                message="unterminated block comment",
                severity=DiagnosticSeverity.ERROR,
                range=self._range(start, self.pos),
                remediation="Close the block comment with */",
            )
            if self.mode is ParseMode.STRICT:
                self.stopped = True
            safe = _safe_lexeme(lexeme, fallback="/*")
            self._emit(
                kind=TokenKind.ERROR,
                lexeme=safe,
                char_start=start,
                char_end=self.pos,
            )
            return
        self._emit(
            kind=TokenKind.COMMENT,
            lexeme=lexeme,
            char_start=start,
            char_end=self.pos,
        )

    def _emit_operator(self, op: str) -> None:
        start = self.pos
        self.pos += len(op)
        self._emit(
            kind=TokenKind.OPERATOR,
            lexeme=op,
            char_start=start,
            char_end=self.pos,
        )

    def _emit_symbol(self, sym: str) -> None:
        start = self.pos
        self.pos += len(sym)
        self._emit(
            kind=TokenKind.SYMBOL,
            lexeme=sym,
            char_start=start,
            char_end=self.pos,
        )

    def _error_char(
        self,
        *,
        code: str,
        message: str,
        severity: DiagnosticSeverity,
    ) -> None:
        start = self.pos
        ch = self.text[self.pos]
        self.pos += 1
        self.had_error = True
        self.sink.emit(
            code=code,
            message=message,
            severity=severity,
            range=self._range(start, self.pos),
        )
        # Always preserve an explicit error node. Lexeme must satisfy the
        # no-surrounding-whitespace contract (pure whitespace becomes "error").
        lexeme = _safe_lexeme(ch, fallback="error") or "error"
        self._emit(
            kind=TokenKind.ERROR,
            lexeme=lexeme,
            char_start=start,
            char_end=self.pos,
        )
        if self.mode is ParseMode.STRICT or severity is DiagnosticSeverity.FATAL:
            self.stopped = True

    def _emit(
        self,
        *,
        kind: TokenKind | str,
        lexeme: str,
        char_start: int,
        char_end: int,
        trailing: tuple[SourceRange, ...] = (),
    ) -> None:
        if not self._can_emit_non_eof():
            self._token_limit()
            return
        leading = tuple(self.pending_leading)
        self.pending_leading = []
        safe = _safe_lexeme(lexeme, fallback="error")
        token = self._make_token(
            kind=kind,
            lexeme=safe,
            char_start=char_start,
            char_end=char_end,
            leading=leading,
            trailing=trailing,
        )
        self.tokens.append(token)

    def _make_token(
        self,
        *,
        kind: TokenKind | str,
        lexeme: str,
        char_start: int,
        char_end: int,
        leading: tuple[SourceRange, ...] | list[SourceRange],
        trailing: tuple[SourceRange, ...] | list[SourceRange],
    ) -> LogicToken:
        self.token_seq += 1
        kind_value = kind.value if isinstance(kind, TokenKind) else str(kind)
        byte_start = self._byte_at(char_start)
        byte_end = self._byte_at(char_end)
        return LogicToken(
            token_id=f"tok:{self.token_seq}",
            kind=kind_value,
            lexeme=lexeme,
            range=SourceRange(
                start=byte_start,
                end=byte_end,
                start_char=char_start,
                end_char=char_end,
            ),
            leading_trivia=tuple(leading),
            trailing_trivia=tuple(trailing),
            document_id=self.document.document_id,
        )

    def _range(self, char_start: int, char_end: int) -> SourceRange:
        return SourceRange(
            start=self._byte_at(char_start),
            end=self._byte_at(char_end),
            start_char=char_start,
            end_char=char_end,
        )

    def _byte_at(self, char_pos: int) -> int:
        if char_pos <= 0:
            return 0
        if char_pos >= self.length:
            return self.document.byte_length
        return len(self.text[:char_pos].encode(self.encoding))

    def _byte_char_at(self, char_pos: int) -> tuple[int, int]:
        return self._byte_at(char_pos), char_pos

    def _peek(self, offset: int = 1) -> str | None:
        index = self.pos + offset
        if 0 <= index < self.length:
            return self.text[index]
        return None


def _safe_lexeme(lexeme: str, *, fallback: str = "error") -> str:
    """Ensure *lexeme* satisfies the LogicToken whitespace contract.

    The contract rejects any non-empty value that differs from ``value.strip()``.
    Pure-whitespace values are therefore rewritten to *fallback*.
    """
    if not isinstance(lexeme, str):
        return fallback
    if not lexeme:
        return ""
    if lexeme != lexeme.strip():
        stripped = lexeme.strip()
        return stripped if stripped else fallback
    return lexeme


def _eof_token(
    document: SourceDocument,
    *,
    char_pos: int,
    byte_pos: int,
    token_index: int,
) -> LogicToken:
    return LogicToken(
        token_id=f"tok:{token_index}",
        kind=TokenKind.EOF,
        lexeme="",
        range=SourceRange(
            start=byte_pos,
            end=byte_pos,
            start_char=char_pos,
            end_char=char_pos,
        ),
        document_id=document.document_id,
    )


__all__ = [
    "BOUNDED_LEXER_INTERFACE",
    "BoundedLexer",
    "LEXER_MODULE_VERSION",
    "LexResult",
    "lex_document",
]
