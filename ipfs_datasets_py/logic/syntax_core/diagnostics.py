"""Structured diagnostics and source-map helpers for the syntax-core lexer.

Interfaces:

* ``LogicDiagnostic@1`` — stable namespaced diagnostic codes and builders
* ``LogicSourceMap@1`` — deterministic token/trivia source maps
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.contracts import (
    DIAGNOSTIC_SCHEMA_VERSION,
    DiagnosticSeverity,
    LogicToken,
    SOURCE_MAP_SCHEMA_VERSION,
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)

LOGIC_DIAGNOSTIC_INTERFACE: Final = "LogicDiagnostic@1"
LOGIC_SOURCE_MAP_INTERFACE: Final = "LogicSourceMap@1"
DIAGNOSTICS_MODULE_VERSION: Final = "1.0.0"

# Stable namespaced codes (must match contracts._DIAGNOSTIC_CODE_RE).
CODE_UNKNOWN_CHARACTER: Final = "lexer.unknown_character"
CODE_TOKEN_LIMIT: Final = "lexer.token_limit_exceeded"
CODE_DIAGNOSTIC_LIMIT: Final = "lexer.diagnostic_limit_exceeded"
CODE_COMMENT_DEPTH: Final = "lexer.comment_depth_exceeded"
CODE_UNTERMINATED_STRING: Final = "lexer.unterminated_string"
CODE_UNTERMINATED_COMMENT: Final = "lexer.unterminated_comment"
CODE_MALFORMED_NUMBER: Final = "lexer.malformed_number"
CODE_NUL_CHARACTER: Final = "lexer.nul_character"
CODE_CONFUSABLE_CHARACTER: Final = "lexer.confusable_character"
CODE_INPUT_LIMIT: Final = "lexer.input_limit_exceeded"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNKNOWN_CHARACTER,
        CODE_TOKEN_LIMIT,
        CODE_DIAGNOSTIC_LIMIT,
        CODE_COMMENT_DEPTH,
        CODE_UNTERMINATED_STRING,
        CODE_UNTERMINATED_COMMENT,
        CODE_MALFORMED_NUMBER,
        CODE_NUL_CHARACTER,
        CODE_CONFUSABLE_CHARACTER,
        CODE_INPUT_LIMIT,
    }
)


@dataclass(frozen=True, slots=True)
class LogicDiagnostic:
    """Thin interface wrapper over :class:`SyntaxDiagnostic`.

    Interface: ``LogicDiagnostic@1``.
    """

    diagnostic: SyntaxDiagnostic

    interface: ClassVar[str] = LOGIC_DIAGNOSTIC_INTERFACE

    @property
    def diagnostic_id(self) -> str:
        return self.diagnostic.diagnostic_id

    @property
    def code(self) -> str:
        return self.diagnostic.code

    @property
    def message(self) -> str:
        return self.diagnostic.message

    @property
    def severity(self) -> DiagnosticSeverity:
        severity = self.diagnostic.severity
        if isinstance(severity, DiagnosticSeverity):
            return severity
        return DiagnosticSeverity(str(severity))

    @property
    def range(self) -> SourceRange | None:
        return self.diagnostic.range

    def to_syntax(self) -> SyntaxDiagnostic:
        return self.diagnostic

    def to_dict(self) -> dict[str, Any]:
        payload = self.diagnostic.to_dict()
        payload["interface"] = self.interface
        return payload

    @classmethod
    def from_syntax(cls, diagnostic: SyntaxDiagnostic) -> "LogicDiagnostic":
        if not isinstance(diagnostic, SyntaxDiagnostic):
            raise SyntaxContractError("LogicDiagnostic requires a SyntaxDiagnostic")
        return cls(diagnostic=diagnostic)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicDiagnostic":
        return cls.from_syntax(SyntaxDiagnostic.from_dict(data))


@dataclass(frozen=True, slots=True)
class LogicSourceMap:
    """Deterministic source map over lexer tokens and trivia.

    Interface: ``LogicSourceMap@1``.
    """

    source_map: SourceMap

    interface: ClassVar[str] = LOGIC_SOURCE_MAP_INTERFACE

    @property
    def map_id(self) -> str:
        return self.source_map.map_id

    @property
    def document_id(self) -> str:
        return self.source_map.document_id

    @property
    def entries(self) -> tuple[SourceMapEntry, ...]:
        return self.source_map.entries

    def to_source_map(self) -> SourceMap:
        return self.source_map

    def to_dict(self) -> dict[str, Any]:
        payload = self.source_map.to_dict()
        payload["interface"] = self.interface
        return payload

    @classmethod
    def from_source_map(cls, source_map: SourceMap) -> "LogicSourceMap":
        if not isinstance(source_map, SourceMap):
            raise SyntaxContractError("LogicSourceMap requires a SourceMap")
        return cls(source_map=source_map)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicSourceMap":
        return cls.from_source_map(SourceMap.from_dict(data))


class DiagnosticSink:
    """Bounded, deterministic diagnostic accumulator."""

    def __init__(self, *, max_diagnostics: int) -> None:
        if not isinstance(max_diagnostics, int) or isinstance(max_diagnostics, bool):
            raise SyntaxContractError("max_diagnostics must be a positive integer")
        if max_diagnostics <= 0:
            raise SyntaxContractError("max_diagnostics must be a positive integer")
        self._max = max_diagnostics
        self._items: list[SyntaxDiagnostic] = []
        self._capped = False
        self._seq = 0

    @property
    def capped(self) -> bool:
        return self._capped

    @property
    def items(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(self._items)

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"diag:{prefix}:{self._seq}"

    def add(self, diagnostic: SyntaxDiagnostic) -> bool:
        """Append *diagnostic* if capacity remains.

        Returns ``True`` when the diagnostic was stored.
        """
        if not isinstance(diagnostic, SyntaxDiagnostic):
            raise SyntaxContractError("diagnostic must be a SyntaxDiagnostic")
        if len(self._items) >= self._max:
            if not self._capped:
                self._capped = True
            return False
        # Reject duplicate ids fail-closed.
        if any(item.diagnostic_id == diagnostic.diagnostic_id for item in self._items):
            raise SyntaxContractError(
                f"duplicate diagnostic_id {diagnostic.diagnostic_id!r}"
            )
        self._items.append(diagnostic)
        if len(self._items) >= self._max:
            self._capped = True
        return True

    def emit(
        self,
        *,
        code: str,
        message: str,
        severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
        range: SourceRange | None = None,
        remediation: str = "",
        metadata: Mapping[str, Any] | None = None,
        diagnostic_id: str | None = None,
    ) -> SyntaxDiagnostic | None:
        if code not in _ALL_CODES:
            # Allow additional well-formed namespaced codes from callers.
            pass
        diag_id = diagnostic_id or self._next_id(code.replace(".", "-"))
        diagnostic = SyntaxDiagnostic(
            diagnostic_id=diag_id,
            code=code,
            message=message,
            severity=severity,
            range=range,
            remediation=remediation,
            metadata=dict(metadata or {}),
            schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        )
        if self.add(diagnostic):
            return diagnostic
        return None


def make_diagnostic(
    *,
    diagnostic_id: str,
    code: str,
    message: str,
    severity: DiagnosticSeverity | str = DiagnosticSeverity.ERROR,
    range: SourceRange | None = None,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    """Construct a validated :class:`SyntaxDiagnostic`."""

    return SyntaxDiagnostic(
        diagnostic_id=diagnostic_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


def build_token_source_map(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    map_id: str = "map:lex:1",
) -> SourceMap:
    """Build a deterministic source map covering tokens and their trivia."""

    if not isinstance(document, SourceDocument):
        raise SyntaxContractError("document must be a SourceDocument")
    entries: list[SourceMapEntry] = []
    for token in tokens:
        if not isinstance(token, LogicToken):
            raise SyntaxContractError("tokens must contain LogicToken values")
        for index, trivia in enumerate(token.leading_trivia):
            entries.append(
                SourceMapEntry(
                    entry_id=f"{token.token_id}:leading:{index}",
                    range=trivia,
                    role="trivia",
                    metadata={"side": "leading", "token_id": token.token_id},
                )
            )
        if token.kind != TokenKind.EOF.value:
            entries.append(
                SourceMapEntry(
                    entry_id=f"{token.token_id}:lexeme",
                    range=token.range,
                    role="token",
                    metadata={"kind": token.kind, "token_id": token.token_id},
                )
            )
        for index, trivia in enumerate(token.trailing_trivia):
            entries.append(
                SourceMapEntry(
                    entry_id=f"{token.token_id}:trailing:{index}",
                    range=trivia,
                    role="trivia",
                    metadata={"side": "trailing", "token_id": token.token_id},
                )
            )
    return SourceMap(
        map_id=map_id,
        document_id=document.document_id,
        entries=tuple(entries),
        schema_version=SOURCE_MAP_SCHEMA_VERSION,
    )


def build_logic_source_map(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    map_id: str = "map:lex:1",
) -> LogicSourceMap:
    return LogicSourceMap.from_source_map(
        build_token_source_map(document, tokens, map_id=map_id)
    )


def diagnostics_have_code(
    diagnostics: Iterable[SyntaxDiagnostic | LogicDiagnostic],
    code: str,
) -> bool:
    for item in diagnostics:
        actual = item.code if isinstance(item, (SyntaxDiagnostic, LogicDiagnostic)) else ""
        if actual == code:
            return True
    return False


__all__ = [
    "CODE_COMMENT_DEPTH",
    "CODE_CONFUSABLE_CHARACTER",
    "CODE_DIAGNOSTIC_LIMIT",
    "CODE_INPUT_LIMIT",
    "CODE_MALFORMED_NUMBER",
    "CODE_NUL_CHARACTER",
    "CODE_TOKEN_LIMIT",
    "CODE_UNKNOWN_CHARACTER",
    "CODE_UNTERMINATED_COMMENT",
    "CODE_UNTERMINATED_STRING",
    "DIAGNOSTICS_MODULE_VERSION",
    "DiagnosticSink",
    "LOGIC_DIAGNOSTIC_INTERFACE",
    "LOGIC_SOURCE_MAP_INTERFACE",
    "LogicDiagnostic",
    "LogicSourceMap",
    "build_logic_source_map",
    "build_token_source_map",
    "diagnostics_have_code",
    "make_diagnostic",
]
