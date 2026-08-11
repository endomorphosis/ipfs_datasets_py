"""Bounded, immutable source and parse contracts for the logic syntax core.

Interfaces (LFP-011):

* ``SourceDocument@1`` — exact source bytes, safe encoding, line index, digests
* ``LogicToken@1`` — kind, lexeme, trivia, and half-open source range
* ``LogicCST@1`` — lossless concrete syntax tree with complete source coverage
* ``ParseRequest@1`` — notation/profile-bound parse request with finite limits
* ``ParseArtifact@1`` — tokens, CST, surface AST refs, and diagnostics

All construction is fail-closed: invalid ranges, unsafe encodings, missing
source coverage, unbounded limits, duplicate diagnostics, and wrong
namespace/profile identities raise :class:`SyntaxContractError`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.namespaces import (
    CrossNamespaceCoercionError,
    InvalidIdentifierError,
    LogicIdentity,
    NamespaceKind,
    SchemaVersionError,
    notation_id as make_notation_id,
    profile_id as make_profile_id,
    validate_identifier,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SOURCE_DOCUMENT_INTERFACE: Final = "SourceDocument@1"
LOGIC_TOKEN_INTERFACE: Final = "LogicToken@1"
LOGIC_CST_INTERFACE: Final = "LogicCST@1"
PARSE_REQUEST_INTERFACE: Final = "ParseRequest@1"
PARSE_ARTIFACT_INTERFACE: Final = "ParseArtifact@1"

SOURCE_DOCUMENT_SCHEMA_VERSION: Final = "syntax-source-document/v1"
LOGIC_TOKEN_SCHEMA_VERSION: Final = "syntax-logic-token/v1"
LOGIC_CST_SCHEMA_VERSION: Final = "syntax-logic-cst/v1"
PARSE_REQUEST_SCHEMA_VERSION: Final = "syntax-parse-request/v1"
PARSE_ARTIFACT_SCHEMA_VERSION: Final = "syntax-parse-artifact/v1"
SOURCE_RANGE_SCHEMA_VERSION: Final = "syntax-source-range/v1"
SOURCE_MAP_SCHEMA_VERSION: Final = "syntax-source-map/v1"
DIAGNOSTIC_SCHEMA_VERSION: Final = "syntax-diagnostic/v1"
PARSE_LIMITS_SCHEMA_VERSION: Final = "syntax-parse-limits/v1"
SURFACE_AST_REF_SCHEMA_VERSION: Final = "syntax-surface-ast-ref/v1"

CONTRACTS_MODULE_VERSION: Final = "1.0.0"

# Hard resource ceilings. Callers may only tighten limits within these bounds.
MAX_SOURCE_BYTES: Final = 1_048_576
MAX_TOKENS: Final = 262_144
MAX_CST_NODES: Final = 524_288
MAX_DIAGNOSTICS: Final = 4_096
MAX_AMBIGUITIES: Final = 1_024
MAX_PARSE_DEPTH: Final = 4_096
MAX_TIME_MS: Final = 600_000
MAX_MEMORY_BYTES: Final = 268_435_456
MAX_STRING_CHARS: Final = 16_384
MAX_COLLECTION_ITEMS: Final = 65_536
MAX_LINE_INDEX_ENTRIES: Final = MAX_SOURCE_BYTES + 1

# Encodings that cannot smuggle or reinterpret untrusted bytes.
SAFE_ENCODINGS: Final[frozenset[str]] = frozenset(
    {
        "ascii",
        "utf-8",
    }
)

_UNSAFE_ENCODING_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "latin-1",
        "latin1",
        "iso-8859-1",
        "iso8859-1",
        "cp1252",
        "windows-1252",
        "utf-7",
        "utf7",
        "utf-16",
        "utf16",
        "utf-32",
        "utf32",
        "idna",
        "mbcs",
        "charmap",
        "raw-unicode-escape",
        "unicode-escape",
        "punycode",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TOKEN_KIND_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_DIAGNOSTIC_CODE_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,7}$"
)
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class SyntaxContractError(ValueError):
    """Raised when a syntax-core contract is malformed or contradictory."""


class DiagnosticSeverity(str, Enum):
    """Stable diagnostic severity ordered by operational impact."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def rank(self) -> int:
        return {
            DiagnosticSeverity.INFO: 10,
            DiagnosticSeverity.WARNING: 20,
            DiagnosticSeverity.ERROR: 30,
            DiagnosticSeverity.FATAL: 40,
        }[self]


class ParseMode(str, Enum):
    """Parser operating mode."""

    STRICT = "strict"
    RECOVERY = "recovery"


class ParseStatus(str, Enum):
    """Outcome of a parse attempt."""

    OK = "ok"
    RECOVERED = "recovered"
    FAILED = "failed"
    REJECTED = "rejected"


class CSTNodeRole(str, Enum):
    """Role of a CST node in source coverage accounting."""

    ROOT = "root"
    INNER = "inner"
    TOKEN = "token"
    TRIVIA = "trivia"
    RECOVERY = "recovery"
    ERROR = "error"
    GAP = "gap"


class TokenKind(str, Enum):
    """Closed baseline token kinds; families may use additional identifiers."""

    IDENTIFIER = "identifier"
    KEYWORD = "keyword"
    SYMBOL = "symbol"
    OPERATOR = "operator"
    NUMBER = "number"
    STRING = "string"
    COMMENT = "comment"
    WHITESPACE = "whitespace"
    NEWLINE = "newline"
    EOF = "eof"
    ERROR = "error"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SyntaxContractError(f"{field_name} must be a mapping")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise SyntaxContractError(f"{field_name} must be a sequence")
    return value


def _text(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
    maximum: int = MAX_STRING_CHARS,
) -> str:
    if type(value) is not str:
        raise SyntaxContractError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise SyntaxContractError(f"{field_name} must not be empty")
    if value != value.strip() and value:
        raise SyntaxContractError(
            f"{field_name} must not have surrounding whitespace"
        )
    if "\x00" in value:
        raise SyntaxContractError(f"{field_name} must not contain NUL bytes")
    if len(value) > maximum:
        raise SyntaxContractError(
            f"{field_name} exceeds maximum length of {maximum}"
        )
    return value


def _record_id(value: object, field_name: str) -> str:
    result = _text(value, field_name, maximum=256)
    if not _ID_RE.fullmatch(result):
        raise SyntaxContractError(f"{field_name} is not a stable record id")
    return result


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyntaxContractError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise SyntaxContractError(f"{field_name} must be a non-negative integer")
    return value


def _positive_int(
    value: object,
    field_name: str,
    *,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyntaxContractError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise SyntaxContractError(
            f"{field_name} must be a positive finite bound; unbounded values "
            "are rejected"
        )
    if maximum is not None and value > maximum:
        raise SyntaxContractError(
            f"{field_name} exceeds hard ceiling of {maximum}"
        )
    return value


def _sha256_hex(value: object, field_name: str) -> str:
    result = _text(value, field_name, maximum=64)
    if not _SHA256_HEX_RE.fullmatch(result):
        raise SyntaxContractError(
            f"{field_name} must be a lowercase 64-hex sha256 digest"
        )
    return result


def _freeze_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    mapping = _require_mapping(value, field_name)
    frozen: dict[str, Any] = {}
    for key, item in mapping.items():
        if type(key) is not str or not key:
            raise SyntaxContractError(
                f"{field_name} keys must be non-empty strings"
            )
        frozen[key] = _freeze_json(item, f"{field_name}.{key}")
    return MappingProxyType(frozen)


def _freeze_json(value: object, field_name: str) -> Any:
    if value is None or type(value) in {str, bool, int}:
        if type(value) is int and abs(value) > (1 << 53) - 1:
            raise SyntaxContractError(
                f"{field_name} integer is outside the safe JSON integer range"
            )
        return value
    if type(value) is float:
        raise SyntaxContractError(f"{field_name} rejects float values")
    if isinstance(value, Mapping):
        return dict(_freeze_mapping(value, field_name))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_freeze_json(item, f"{field_name}[{index}]") for index, item in enumerate(value)]
    raise SyntaxContractError(
        f"{field_name} is not a reviewed JSON value: {type(value).__name__}"
    )


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _thaw_json(item) for key, item in value.items()}


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_json(item) for item in value]
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialize a contract payload to deterministic UTF-8 JSON bytes."""

    text = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("ascii")


def content_sha256(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of *data*."""

    if type(data) is not bytes:
        raise SyntaxContractError("content must be exact bytes")
    return hashlib.sha256(data).hexdigest()


def normalize_encoding_name(value: object, field_name: str = "encoding") -> str:
    """Normalize and admit only reviewed safe encodings."""

    if type(value) is not str or not value or value != value.strip():
        raise SyntaxContractError(f"{field_name} must be a non-empty trimmed string")
    normalized = value.strip().casefold().replace("_", "-")
    # Canonical aliases.
    if normalized in {"utf8", "utf-8"}:
        normalized = "utf-8"
    elif normalized in {"us-ascii", "ascii"}:
        normalized = "ascii"
    if normalized in _UNSAFE_ENCODING_ALIASES:
        raise SyntaxContractError(
            f"{field_name} rejects unsafe encoding {value!r}"
        )
    if normalized not in SAFE_ENCODINGS:
        raise SyntaxContractError(
            f"{field_name} must be one of {sorted(SAFE_ENCODINGS)}; got {value!r}"
        )
    return normalized


def require_namespace_identity(
    value: object,
    expected: NamespaceKind,
    field_name: str,
) -> LogicIdentity:
    """Require a typed :class:`LogicIdentity` in *expected* namespace."""

    if isinstance(value, LogicIdentity):
        identity = value
    elif isinstance(value, Mapping):
        try:
            identity = LogicIdentity.from_dict(value)
        except (InvalidIdentifierError, SchemaVersionError) as error:
            raise SyntaxContractError(
                f"{field_name} is not a valid logic identity: {error}"
            ) from error
    elif isinstance(value, str):
        # Bare strings are admitted only as the expected namespace value.
        try:
            if expected is NamespaceKind.NOTATION:
                identity = make_notation_id(value)
            elif expected is NamespaceKind.PROFILE:
                identity = make_profile_id(value)
            elif expected is NamespaceKind.FAMILY:
                from ipfs_datasets_py.logic.families.namespaces import family_id

                identity = family_id(value)
            else:
                identity = LogicIdentity(expected, validate_identifier(value, field_name))
        except (InvalidIdentifierError, ValueError) as error:
            raise SyntaxContractError(
                f"{field_name} is not a valid {expected.value} id: {error}"
            ) from error
    else:
        raise SyntaxContractError(
            f"{field_name} must be a LogicIdentity, mapping, or canonical string"
        )

    try:
        return identity.require(expected)
    except CrossNamespaceCoercionError as error:
        raise SyntaxContractError(
            f"{field_name} requires namespace {expected.value!r}; "
            f"got {identity.qualified!r}"
        ) from error


def build_line_index(text: str) -> tuple[int, ...]:
    """Return 0-based character offsets of each line start, including offset 0."""

    if type(text) is not str:
        raise SyntaxContractError("line index text must be a string")
    starts = [0]
    for index, character in enumerate(text):
        if character == "\n" and index + 1 < len(text):
            starts.append(index + 1)
        if len(starts) > MAX_LINE_INDEX_ENTRIES:
            raise SyntaxContractError("line index exceeds hard ceiling")
    return tuple(starts)


# ---------------------------------------------------------------------------
# Source range / map / document
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceRange:
    """Half-open ``[start, end)`` range over source bytes or characters.

    Byte offsets are authoritative for coverage. Character offsets are optional
    and must agree with the same half-open ordering when present.
    """

    start: int
    end: int
    start_char: int | None = None
    end_char: int | None = None
    schema_version: str = SOURCE_RANGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        start = _non_negative_int(self.start, "SourceRange.start")
        end = _non_negative_int(self.end, "SourceRange.end")
        if end < start:
            raise SyntaxContractError(
                f"invalid range: end {end} precedes start {start}"
            )
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        if self.start_char is not None or self.end_char is not None:
            if self.start_char is None or self.end_char is None:
                raise SyntaxContractError(
                    "character offsets must be supplied as a complete pair"
                )
            start_char = _non_negative_int(self.start_char, "SourceRange.start_char")
            end_char = _non_negative_int(self.end_char, "SourceRange.end_char")
            if end_char < start_char:
                raise SyntaxContractError(
                    "invalid character range: end precedes start"
                )
            object.__setattr__(self, "start_char", start_char)
            object.__setattr__(self, "end_char", end_char)
        if self.schema_version != SOURCE_RANGE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported SourceRange schema_version {self.schema_version!r}"
            )

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return self.start == self.end

    def contains(self, other: "SourceRange") -> bool:
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: "SourceRange") -> bool:
        return self.start < other.end and other.start < self.end

    def abuts(self, other: "SourceRange") -> bool:
        return self.end == other.start or other.end == self.start

    def validate_against(self, source_length: int, *, field_name: str = "range") -> None:
        if source_length < 0:
            raise SyntaxContractError("source_length must be non-negative")
        if self.end > source_length:
            raise SyntaxContractError(
                f"{field_name} end {self.end} exceeds source length {source_length}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "end": self.end,
            "schema_version": self.schema_version,
            "start": self.start,
        }
        if self.start_char is not None:
            payload["end_char"] = self.end_char
            payload["start_char"] = self.start_char
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceRange":
        payload = _require_mapping(data, "SourceRange")
        return cls(
            start=payload.get("start", 0),
            end=payload.get("end", 0),
            start_char=payload.get("start_char"),
            end_char=payload.get("end_char"),
            schema_version=str(
                payload.get("schema_version") or SOURCE_RANGE_SCHEMA_VERSION
            ),
        )


def _merge_coverage(ranges: Sequence[SourceRange]) -> list[SourceRange]:
    """Merge overlapping/adjacent ranges into a sorted disjoint cover."""

    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: (item.start, item.end))
    merged: list[SourceRange] = [ordered[0]]
    for current in ordered[1:]:
        previous = merged[-1]
        if current.start > previous.end:
            merged.append(current)
            continue
        if current.end > previous.end:
            merged[-1] = SourceRange(start=previous.start, end=current.end)
    return merged


def assert_complete_coverage(
    ranges: Sequence[SourceRange],
    source_length: int,
    *,
    field_name: str = "coverage",
) -> None:
    """Fail closed when *ranges* do not cover ``[0, source_length)`` exactly."""

    if source_length == 0:
        if ranges and any(not item.is_empty for item in ranges):
            raise SyntaxContractError(
                f"{field_name} must be empty for a zero-length source"
            )
        return
    merged = _merge_coverage(tuple(item for item in ranges if not item.is_empty))
    if not merged:
        raise SyntaxContractError(
            f"{field_name} is missing; source coverage is incomplete"
        )
    if merged[0].start != 0:
        raise SyntaxContractError(
            f"{field_name} leaves a hole at the start of the source "
            f"(first covered byte is {merged[0].start})"
        )
    if merged[-1].end != source_length:
        raise SyntaxContractError(
            f"{field_name} leaves a hole at the end of the source "
            f"(last covered byte is {merged[-1].end}, expected {source_length})"
        )
    for left, right in zip(merged, merged[1:]):
        if left.end != right.start:
            raise SyntaxContractError(
                f"{field_name} leaves an uncovered hole [{left.end}, {right.start})"
            )


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    """One named span contribution to a source map."""

    entry_id: str
    range: SourceRange
    role: str = "span"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _record_id(self.entry_id, "entry_id"))
        if not isinstance(self.range, SourceRange):
            object.__setattr__(
                self, "range", SourceRange.from_dict(_require_mapping(self.range, "range"))
            )
        object.__setattr__(self, "role", _text(self.role, "role", maximum=64))
        if not _TOKEN_KIND_RE.fullmatch(self.role):
            raise SyntaxContractError(f"role is not a canonical token: {self.role!r}")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "metadata": _thaw_mapping(self.metadata),
            "range": self.range.to_dict(),
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceMapEntry":
        payload = _require_mapping(data, "SourceMapEntry")
        return cls(
            entry_id=str(payload.get("entry_id") or ""),
            range=SourceRange.from_dict(_require_mapping(payload.get("range"), "range")),
            role=str(payload.get("role") or "span"),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
        )


@dataclass(frozen=True, slots=True)
class SourceMap:
    """Named collection of source ranges bound to one document."""

    map_id: str
    document_id: str
    entries: tuple[SourceMapEntry, ...] = ()
    schema_version: str = SOURCE_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "map_id", _record_id(self.map_id, "map_id"))
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        entries = tuple(
            item
            if isinstance(item, SourceMapEntry)
            else SourceMapEntry.from_dict(_require_mapping(item, "entries item"))
            for item in _require_sequence(self.entries, "entries")
        )
        if len(entries) > MAX_COLLECTION_ITEMS:
            raise SyntaxContractError("SourceMap.entries exceeds collection ceiling")
        ids = [item.entry_id for item in entries]
        if len(ids) != len(set(ids)):
            raise SyntaxContractError("SourceMap.entries must have unique entry_id values")
        object.__setattr__(self, "entries", entries)
        if self.schema_version != SOURCE_MAP_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported SourceMap schema_version {self.schema_version!r}"
            )

    def ranges(self) -> tuple[SourceRange, ...]:
        return tuple(item.range for item in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "entries": [item.to_dict() for item in self.entries],
            "map_id": self.map_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceMap":
        payload = _require_mapping(data, "SourceMap")
        return cls(
            map_id=str(payload.get("map_id") or ""),
            document_id=str(payload.get("document_id") or ""),
            entries=tuple(
                SourceMapEntry.from_dict(_require_mapping(item, "entries item"))
                for item in _require_sequence(payload.get("entries") or (), "entries")
            ),
            schema_version=str(
                payload.get("schema_version") or SOURCE_MAP_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Exact source bytes with a reviewed encoding and derived line index.

    Interface: ``SourceDocument@1``.
    """

    document_id: str
    content: bytes
    encoding: str = "utf-8"
    uri: str = ""
    language_hint: str = ""
    line_index: tuple[int, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SOURCE_DOCUMENT_SCHEMA_VERSION

    interface: ClassVar[str] = SOURCE_DOCUMENT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        content = self.content
        if isinstance(content, bytearray):
            content = bytes(content)
        if type(content) is not bytes:
            raise SyntaxContractError("SourceDocument.content must be exact bytes")
        if len(content) > MAX_SOURCE_BYTES:
            raise SyntaxContractError(
                f"SourceDocument.content exceeds hard ceiling of {MAX_SOURCE_BYTES} bytes"
            )
        encoding = normalize_encoding_name(self.encoding, "encoding")
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError as error:
            raise SyntaxContractError(
                f"SourceDocument.content is not valid {encoding}: {error}"
            ) from error
        # Reject embedded NUL even when the codec admits it (ascii/utf-8).
        if "\x00" in text:
            raise SyntaxContractError(
                "SourceDocument.content must not contain NUL code points"
            )
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "encoding", encoding)

        digest = content_sha256(content)
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != digest:
                raise SyntaxContractError(
                    "content_digest does not match SourceDocument.content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", digest)

        if self.line_index:
            index = tuple(
                _non_negative_int(item, "line_index item")
                for item in _require_sequence(self.line_index, "line_index")
            )
            expected = build_line_index(text)
            if index != expected:
                raise SyntaxContractError(
                    "line_index does not match decoded source text"
                )
            object.__setattr__(self, "line_index", index)
        else:
            object.__setattr__(self, "line_index", build_line_index(text))

        if self.uri:
            object.__setattr__(self, "uri", _text(self.uri, "uri", maximum=2048))
        else:
            object.__setattr__(self, "uri", "")
        if self.language_hint:
            object.__setattr__(
                self,
                "language_hint",
                _text(self.language_hint, "language_hint", maximum=128),
            )
        else:
            object.__setattr__(self, "language_hint", "")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        if self.schema_version != SOURCE_DOCUMENT_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported SourceDocument schema_version {self.schema_version!r}"
            )

    @property
    def byte_length(self) -> int:
        return len(self.content)

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding)

    def full_range(self) -> SourceRange:
        text = self.text
        return SourceRange(
            start=0,
            end=self.byte_length,
            start_char=0,
            end_char=len(text),
        )

    def slice(self, source_range: SourceRange) -> bytes:
        if not isinstance(source_range, SourceRange):
            raise SyntaxContractError("slice requires a SourceRange")
        source_range.validate_against(self.byte_length, field_name="slice range")
        return self.content[source_range.start : source_range.end]

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "content_digest": self.content_digest,
            "content_hex": self.content.hex(),
            "encoding": self.encoding,
            "document_id": self.document_id,
            "interface": self.interface,
            "language_hint": self.language_hint,
            "line_index": list(self.line_index),
            "metadata": _thaw_mapping(self.metadata),
            "schema_version": self.schema_version,
            "uri": self.uri,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceDocument":
        payload = _require_mapping(data, "SourceDocument")
        interface = payload.get("interface")
        if interface is not None and interface != SOURCE_DOCUMENT_INTERFACE:
            raise SyntaxContractError(
                f"unsupported SourceDocument interface {interface!r}"
            )
        content_hex = payload.get("content_hex")
        if content_hex is None:
            raise SyntaxContractError("SourceDocument requires content_hex")
        try:
            content = bytes.fromhex(str(content_hex))
        except ValueError as error:
            raise SyntaxContractError(
                "SourceDocument.content_hex is not valid hex"
            ) from error
        return cls(
            document_id=str(payload.get("document_id") or ""),
            content=content,
            encoding=str(payload.get("encoding") or "utf-8"),
            uri=str(payload.get("uri") or ""),
            language_hint=str(payload.get("language_hint") or ""),
            line_index=tuple(payload.get("line_index") or ()),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or SOURCE_DOCUMENT_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_text(
        cls,
        document_id: str,
        text: str,
        *,
        encoding: str = "utf-8",
        uri: str = "",
        language_hint: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> "SourceDocument":
        """Build a document from Unicode text under a safe encoding."""

        if type(text) is not str:
            raise SyntaxContractError("from_text requires a string")
        encoding_name = normalize_encoding_name(encoding, "encoding")
        try:
            content = text.encode(encoding_name)
        except UnicodeEncodeError as error:
            raise SyntaxContractError(
                f"text is not encodable as {encoding_name}: {error}"
            ) from error
        return cls(
            document_id=document_id,
            content=content,
            encoding=encoding_name,
            uri=uri,
            language_hint=language_hint,
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# Tokens, CST, surface AST refs, diagnostics
# ---------------------------------------------------------------------------


def _token_kind(value: object, field_name: str = "kind") -> str:
    if isinstance(value, TokenKind):
        return value.value
    result = _text(value, field_name, maximum=128)
    if not _TOKEN_KIND_RE.fullmatch(result):
        raise SyntaxContractError(
            f"{field_name} must be a lowercase canonical token kind"
        )
    return result


@dataclass(frozen=True, slots=True)
class LogicToken:
    """One lexer token with optional leading/trailing trivia.

    Interface: ``LogicToken@1``.
    """

    token_id: str
    kind: str | TokenKind
    lexeme: str
    range: SourceRange
    leading_trivia: tuple[SourceRange, ...] = ()
    trailing_trivia: tuple[SourceRange, ...] = ()
    document_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_TOKEN_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_TOKEN_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_id", _record_id(self.token_id, "token_id"))
        object.__setattr__(self, "kind", _token_kind(self.kind))
        object.__setattr__(
            self, "lexeme", _text(self.lexeme, "lexeme", allow_empty=True, maximum=MAX_STRING_CHARS)
        )
        if not isinstance(self.range, SourceRange):
            object.__setattr__(
                self,
                "range",
                SourceRange.from_dict(_require_mapping(self.range, "range")),
            )
        leading = tuple(
            item
            if isinstance(item, SourceRange)
            else SourceRange.from_dict(_require_mapping(item, "leading_trivia item"))
            for item in _require_sequence(self.leading_trivia, "leading_trivia")
        )
        trailing = tuple(
            item
            if isinstance(item, SourceRange)
            else SourceRange.from_dict(_require_mapping(item, "trailing_trivia item"))
            for item in _require_sequence(self.trailing_trivia, "trailing_trivia")
        )
        if len(leading) + len(trailing) > MAX_COLLECTION_ITEMS:
            raise SyntaxContractError("token trivia exceeds collection ceiling")
        object.__setattr__(self, "leading_trivia", leading)
        object.__setattr__(self, "trailing_trivia", trailing)
        if self.document_id:
            object.__setattr__(
                self, "document_id", _record_id(self.document_id, "document_id")
            )
        else:
            object.__setattr__(self, "document_id", "")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        if self.schema_version != LOGIC_TOKEN_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported LogicToken schema_version {self.schema_version!r}"
            )

    def coverage_ranges(self) -> tuple[SourceRange, ...]:
        return (*self.leading_trivia, self.range, *self.trailing_trivia)

    def validate_against(self, document: SourceDocument) -> None:
        if self.document_id and self.document_id != document.document_id:
            raise SyntaxContractError(
                f"token {self.token_id} document_id does not match source document"
            )
        for item in self.coverage_ranges():
            item.validate_against(document.byte_length, field_name=f"token {self.token_id}")
        # Lexeme length is measured in characters for text tokens; empty is ok.
        if self.kind != TokenKind.EOF.value and self.range.is_empty and self.lexeme:
            raise SyntaxContractError(
                f"token {self.token_id} has a non-empty lexeme over an empty range"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "interface": self.interface,
            "kind": self.kind,
            "leading_trivia": [item.to_dict() for item in self.leading_trivia],
            "lexeme": self.lexeme,
            "metadata": _thaw_mapping(self.metadata),
            "range": self.range.to_dict(),
            "schema_version": self.schema_version,
            "token_id": self.token_id,
            "trailing_trivia": [item.to_dict() for item in self.trailing_trivia],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicToken":
        payload = _require_mapping(data, "LogicToken")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_TOKEN_INTERFACE:
            raise SyntaxContractError(
                f"unsupported LogicToken interface {interface!r}"
            )
        return cls(
            token_id=str(payload.get("token_id") or ""),
            kind=str(payload.get("kind") or ""),
            lexeme=str(payload.get("lexeme") or ""),
            range=SourceRange.from_dict(_require_mapping(payload.get("range"), "range")),
            leading_trivia=tuple(
                SourceRange.from_dict(_require_mapping(item, "leading_trivia item"))
                for item in _require_sequence(
                    payload.get("leading_trivia") or (), "leading_trivia"
                )
            ),
            trailing_trivia=tuple(
                SourceRange.from_dict(_require_mapping(item, "trailing_trivia item"))
                for item in _require_sequence(
                    payload.get("trailing_trivia") or (), "trailing_trivia"
                )
            ),
            document_id=str(payload.get("document_id") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or LOGIC_TOKEN_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class LogicCSTNode:
    """One immutable concrete-syntax node."""

    node_id: str
    kind: str
    range: SourceRange
    role: CSTNodeRole | str = CSTNodeRole.INNER
    token_id: str = ""
    children: tuple["LogicCSTNode", ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _record_id(self.node_id, "node_id"))
        object.__setattr__(self, "kind", _token_kind(self.kind, "kind"))
        if not isinstance(self.range, SourceRange):
            object.__setattr__(
                self,
                "range",
                SourceRange.from_dict(_require_mapping(self.range, "range")),
            )
        if isinstance(self.role, CSTNodeRole):
            role = self.role
        else:
            try:
                role = CSTNodeRole(_text(self.role, "role", maximum=32))
            except ValueError as error:
                raise SyntaxContractError(
                    f"role must be a CSTNodeRole value; got {self.role!r}"
                ) from error
        object.__setattr__(self, "role", role)
        if self.token_id:
            object.__setattr__(self, "token_id", _record_id(self.token_id, "token_id"))
        else:
            object.__setattr__(self, "token_id", "")
        children = tuple(
            item
            if isinstance(item, LogicCSTNode)
            else LogicCSTNode.from_dict(_require_mapping(item, "children item"))
            for item in _require_sequence(self.children, "children")
        )
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        if self.role is CSTNodeRole.TOKEN and not self.token_id:
            raise SyntaxContractError(
                f"token-role CST node {self.node_id} requires token_id"
            )
        if self.role is CSTNodeRole.TOKEN and self.children:
            raise SyntaxContractError(
                f"token-role CST node {self.node_id} must be a leaf"
            )
        for child in children:
            if not self.range.contains(child.range):
                raise SyntaxContractError(
                    f"child {child.node_id} range is outside parent {self.node_id}"
                )

    def walk(self) -> Iterable["LogicCSTNode"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def leaf_coverage_ranges(self) -> tuple[SourceRange, ...]:
        if not self.children:
            return (self.range,)
        ranges: list[SourceRange] = []
        for child in self.children:
            ranges.extend(child.leaf_coverage_ranges())
        return tuple(ranges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "children": [child.to_dict() for child in self.children],
            "kind": self.kind,
            "metadata": _thaw_mapping(self.metadata),
            "node_id": self.node_id,
            "range": self.range.to_dict(),
            "role": self.role.value,
            "token_id": self.token_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicCSTNode":
        payload = _require_mapping(data, "LogicCSTNode")
        return cls(
            node_id=str(payload.get("node_id") or ""),
            kind=str(payload.get("kind") or ""),
            range=SourceRange.from_dict(_require_mapping(payload.get("range"), "range")),
            role=str(payload.get("role") or CSTNodeRole.INNER.value),
            token_id=str(payload.get("token_id") or ""),
            children=tuple(
                LogicCSTNode.from_dict(_require_mapping(item, "children item"))
                for item in _require_sequence(payload.get("children") or (), "children")
            ),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
        )


@dataclass(frozen=True, slots=True)
class LogicCST:
    """Lossless concrete syntax tree with complete source coverage.

    Interface: ``LogicCST@1``.
    """

    cst_id: str
    document_id: str
    root: LogicCSTNode
    source_length: int
    require_complete_coverage: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_CST_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_CST_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "cst_id", _record_id(self.cst_id, "cst_id"))
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        if not isinstance(self.root, LogicCSTNode):
            object.__setattr__(
                self,
                "root",
                LogicCSTNode.from_dict(_require_mapping(self.root, "root")),
            )
        source_length = _non_negative_int(self.source_length, "source_length")
        if source_length > MAX_SOURCE_BYTES:
            raise SyntaxContractError("LogicCST.source_length exceeds hard ceiling")
        object.__setattr__(self, "source_length", source_length)
        if not isinstance(self.require_complete_coverage, bool):
            raise SyntaxContractError(
                "require_complete_coverage must be a boolean"
            )
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != LOGIC_CST_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported LogicCST schema_version {self.schema_version!r}"
            )

        nodes = tuple(self.root.walk())
        if len(nodes) > MAX_CST_NODES:
            raise SyntaxContractError("LogicCST exceeds hard node ceiling")
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise SyntaxContractError("LogicCST node_id values must be unique")
        self.root.range.validate_against(
            source_length, field_name=f"CST root {self.root.node_id}"
        )
        if self.root.range.start != 0 or self.root.range.end != source_length:
            raise SyntaxContractError(
                "LogicCST root range must span the entire source"
            )
        if self.require_complete_coverage:
            assert_complete_coverage(
                self.root.leaf_coverage_ranges(),
                source_length,
                field_name="LogicCST source coverage",
            )

    def nodes(self) -> tuple[LogicCSTNode, ...]:
        return tuple(self.root.walk())

    def to_dict(self) -> dict[str, Any]:
        return {
            "cst_id": self.cst_id,
            "document_id": self.document_id,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "require_complete_coverage": self.require_complete_coverage,
            "root": self.root.to_dict(),
            "schema_version": self.schema_version,
            "source_length": self.source_length,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicCST":
        payload = _require_mapping(data, "LogicCST")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_CST_INTERFACE:
            raise SyntaxContractError(
                f"unsupported LogicCST interface {interface!r}"
            )
        return cls(
            cst_id=str(payload.get("cst_id") or ""),
            document_id=str(payload.get("document_id") or ""),
            root=LogicCSTNode.from_dict(_require_mapping(payload.get("root"), "root")),
            source_length=int(payload.get("source_length") or 0),
            require_complete_coverage=bool(
                payload.get("require_complete_coverage", True)
            ),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or LOGIC_CST_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SurfaceASTRef:
    """Lightweight surface-AST node reference carried by parse artifacts.

    Full typed AST construction is owned by later syntax-core tasks.  This
    envelope only records identity, kind, source range, and child refs.
    """

    node_id: str
    kind: str
    range: SourceRange
    child_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SURFACE_AST_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _record_id(self.node_id, "node_id"))
        object.__setattr__(self, "kind", _token_kind(self.kind, "kind"))
        if not isinstance(self.range, SourceRange):
            object.__setattr__(
                self,
                "range",
                SourceRange.from_dict(_require_mapping(self.range, "range")),
            )
        child_ids = tuple(
            _record_id(item, "child_ids item")
            for item in _require_sequence(self.child_ids, "child_ids")
        )
        if len(child_ids) != len(set(child_ids)):
            raise SyntaxContractError("SurfaceASTRef.child_ids must be unique")
        object.__setattr__(self, "child_ids", child_ids)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        if self.schema_version != SURFACE_AST_REF_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported SurfaceASTRef schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "child_ids": list(self.child_ids),
            "kind": self.kind,
            "metadata": _thaw_mapping(self.metadata),
            "node_id": self.node_id,
            "range": self.range.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SurfaceASTRef":
        payload = _require_mapping(data, "SurfaceASTRef")
        return cls(
            node_id=str(payload.get("node_id") or ""),
            kind=str(payload.get("kind") or ""),
            range=SourceRange.from_dict(_require_mapping(payload.get("range"), "range")),
            child_ids=tuple(payload.get("child_ids") or ()),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or SURFACE_AST_REF_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SyntaxDiagnostic:
    """One structured parse/lexer diagnostic with a unique identity."""

    diagnostic_id: str
    code: str
    message: str
    severity: DiagnosticSeverity | str = DiagnosticSeverity.ERROR
    range: SourceRange | None = None
    related_ranges: tuple[SourceRange, ...] = ()
    related_diagnostic_ids: tuple[str, ...] = ()
    remediation: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = DIAGNOSTIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "diagnostic_id", _record_id(self.diagnostic_id, "diagnostic_id")
        )
        code = _text(self.code, "code", maximum=128)
        if not _DIAGNOSTIC_CODE_RE.fullmatch(code):
            raise SyntaxContractError(
                "diagnostic code must be a stable lowercase namespaced code"
            )
        object.__setattr__(self, "code", code)
        object.__setattr__(
            self, "message", _text(self.message, "message", maximum=MAX_STRING_CHARS)
        )
        if isinstance(self.severity, DiagnosticSeverity):
            severity = self.severity
        else:
            try:
                severity = DiagnosticSeverity(_text(self.severity, "severity", maximum=16))
            except ValueError as error:
                raise SyntaxContractError(
                    f"severity must be a DiagnosticSeverity value; got {self.severity!r}"
                ) from error
        object.__setattr__(self, "severity", severity)
        if self.range is not None:
            if not isinstance(self.range, SourceRange):
                object.__setattr__(
                    self,
                    "range",
                    SourceRange.from_dict(_require_mapping(self.range, "range")),
                )
        related = tuple(
            item
            if isinstance(item, SourceRange)
            else SourceRange.from_dict(_require_mapping(item, "related_ranges item"))
            for item in _require_sequence(self.related_ranges, "related_ranges")
        )
        object.__setattr__(self, "related_ranges", related)
        related_ids = tuple(
            _record_id(item, "related_diagnostic_ids item")
            for item in _require_sequence(
                self.related_diagnostic_ids, "related_diagnostic_ids"
            )
        )
        if len(related_ids) != len(set(related_ids)):
            raise SyntaxContractError(
                "related_diagnostic_ids must not contain duplicates"
            )
        if self.diagnostic_id in related_ids:
            raise SyntaxContractError(
                "related_diagnostic_ids must not include the diagnostic itself"
            )
        object.__setattr__(self, "related_diagnostic_ids", related_ids)
        if self.remediation:
            object.__setattr__(
                self,
                "remediation",
                _text(self.remediation, "remediation", maximum=MAX_STRING_CHARS),
            )
        else:
            object.__setattr__(self, "remediation", "")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        if self.schema_version != DIAGNOSTIC_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported SyntaxDiagnostic schema_version {self.schema_version!r}"
            )

    @property
    def is_error(self) -> bool:
        return self.severity in {
            DiagnosticSeverity.ERROR,
            DiagnosticSeverity.FATAL,
        }

    def validate_against(self, document: SourceDocument) -> None:
        if self.range is not None:
            self.range.validate_against(
                document.byte_length, field_name=f"diagnostic {self.diagnostic_id}"
            )
        for item in self.related_ranges:
            item.validate_against(
                document.byte_length,
                field_name=f"diagnostic {self.diagnostic_id} related range",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "diagnostic_id": self.diagnostic_id,
            "message": self.message,
            "metadata": _thaw_mapping(self.metadata),
            "range": None if self.range is None else self.range.to_dict(),
            "related_diagnostic_ids": list(self.related_diagnostic_ids),
            "related_ranges": [item.to_dict() for item in self.related_ranges],
            "remediation": self.remediation,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SyntaxDiagnostic":
        payload = _require_mapping(data, "SyntaxDiagnostic")
        range_payload = payload.get("range")
        return cls(
            diagnostic_id=str(payload.get("diagnostic_id") or ""),
            code=str(payload.get("code") or ""),
            message=str(payload.get("message") or ""),
            severity=str(payload.get("severity") or DiagnosticSeverity.ERROR.value),
            range=(
                None
                if range_payload is None
                else SourceRange.from_dict(_require_mapping(range_payload, "range"))
            ),
            related_ranges=tuple(
                SourceRange.from_dict(_require_mapping(item, "related_ranges item"))
                for item in _require_sequence(
                    payload.get("related_ranges") or (), "related_ranges"
                )
            ),
            related_diagnostic_ids=tuple(
                payload.get("related_diagnostic_ids") or ()
            ),
            remediation=str(payload.get("remediation") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or DIAGNOSTIC_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Parse limits, request, artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParseLimits:
    """Finite resource bounds for one parse request.

    Every field is a positive finite integer.  ``None``, zero, negative values,
    and values above hard ceilings fail closed.
    """

    max_input_bytes: int = MAX_SOURCE_BYTES
    max_tokens: int = MAX_TOKENS
    max_depth: int = MAX_PARSE_DEPTH
    max_diagnostics: int = MAX_DIAGNOSTICS
    max_ambiguities: int = MAX_AMBIGUITIES
    max_time_ms: int = MAX_TIME_MS
    max_memory_bytes: int = MAX_MEMORY_BYTES
    schema_version: str = PARSE_LIMITS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_input_bytes",
            _positive_int(
                self.max_input_bytes, "max_input_bytes", maximum=MAX_SOURCE_BYTES
            ),
        )
        object.__setattr__(
            self,
            "max_tokens",
            _positive_int(self.max_tokens, "max_tokens", maximum=MAX_TOKENS),
        )
        object.__setattr__(
            self,
            "max_depth",
            _positive_int(self.max_depth, "max_depth", maximum=MAX_PARSE_DEPTH),
        )
        object.__setattr__(
            self,
            "max_diagnostics",
            _positive_int(
                self.max_diagnostics, "max_diagnostics", maximum=MAX_DIAGNOSTICS
            ),
        )
        object.__setattr__(
            self,
            "max_ambiguities",
            _positive_int(
                self.max_ambiguities, "max_ambiguities", maximum=MAX_AMBIGUITIES
            ),
        )
        object.__setattr__(
            self,
            "max_time_ms",
            _positive_int(self.max_time_ms, "max_time_ms", maximum=MAX_TIME_MS),
        )
        object.__setattr__(
            self,
            "max_memory_bytes",
            _positive_int(
                self.max_memory_bytes, "max_memory_bytes", maximum=MAX_MEMORY_BYTES
            ),
        )
        if self.schema_version != PARSE_LIMITS_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported ParseLimits schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_ambiguities": self.max_ambiguities,
            "max_depth": self.max_depth,
            "max_diagnostics": self.max_diagnostics,
            "max_input_bytes": self.max_input_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "max_time_ms": self.max_time_ms,
            "max_tokens": self.max_tokens,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParseLimits":
        payload = _require_mapping(data, "ParseLimits")
        return cls(
            max_input_bytes=payload.get("max_input_bytes", MAX_SOURCE_BYTES),
            max_tokens=payload.get("max_tokens", MAX_TOKENS),
            max_depth=payload.get("max_depth", MAX_PARSE_DEPTH),
            max_diagnostics=payload.get("max_diagnostics", MAX_DIAGNOSTICS),
            max_ambiguities=payload.get("max_ambiguities", MAX_AMBIGUITIES),
            max_time_ms=payload.get("max_time_ms", MAX_TIME_MS),
            max_memory_bytes=payload.get("max_memory_bytes", MAX_MEMORY_BYTES),
            schema_version=str(
                payload.get("schema_version") or PARSE_LIMITS_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ParseRequest:
    """Bounded parse request bound to notation and semantic profile identities.

    Interface: ``ParseRequest@1``.
    """

    request_id: str
    document: SourceDocument
    notation_id: LogicIdentity | Mapping[str, Any] | str
    profile_id: LogicIdentity | Mapping[str, Any] | str
    family_id: LogicIdentity | Mapping[str, Any] | str | None = None
    mode: ParseMode | str = ParseMode.STRICT
    limits: ParseLimits = field(default_factory=ParseLimits)
    source_map: SourceMap | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PARSE_REQUEST_SCHEMA_VERSION

    interface: ClassVar[str] = PARSE_REQUEST_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        if not isinstance(self.document, SourceDocument):
            object.__setattr__(
                self,
                "document",
                SourceDocument.from_dict(_require_mapping(self.document, "document")),
            )
        object.__setattr__(
            self,
            "notation_id",
            require_namespace_identity(
                self.notation_id, NamespaceKind.NOTATION, "notation_id"
            ),
        )
        object.__setattr__(
            self,
            "profile_id",
            require_namespace_identity(
                self.profile_id, NamespaceKind.PROFILE, "profile_id"
            ),
        )
        if self.family_id is not None:
            object.__setattr__(
                self,
                "family_id",
                require_namespace_identity(
                    self.family_id, NamespaceKind.FAMILY, "family_id"
                ),
            )
        if isinstance(self.mode, ParseMode):
            mode = self.mode
        else:
            try:
                mode = ParseMode(_text(self.mode, "mode", maximum=32))
            except ValueError as error:
                raise SyntaxContractError(
                    f"mode must be a ParseMode value; got {self.mode!r}"
                ) from error
        object.__setattr__(self, "mode", mode)
        if not isinstance(self.limits, ParseLimits):
            object.__setattr__(
                self,
                "limits",
                ParseLimits.from_dict(_require_mapping(self.limits, "limits")),
            )
        if self.document.byte_length > self.limits.max_input_bytes:
            raise SyntaxContractError(
                "SourceDocument exceeds ParseRequest.limits.max_input_bytes"
            )
        if self.source_map is not None:
            if not isinstance(self.source_map, SourceMap):
                object.__setattr__(
                    self,
                    "source_map",
                    SourceMap.from_dict(_require_mapping(self.source_map, "source_map")),
                )
            if self.source_map.document_id != self.document.document_id:
                raise SyntaxContractError(
                    "source_map.document_id must match document.document_id"
                )
            for entry in self.source_map.entries:
                entry.range.validate_against(
                    self.document.byte_length,
                    field_name=f"source_map entry {entry.entry_id}",
                )
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        if self.schema_version != PARSE_REQUEST_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported ParseRequest schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document.to_dict(),
            "family_id": None if self.family_id is None else self.family_id.to_dict(),
            "interface": self.interface,
            "limits": self.limits.to_dict(),
            "metadata": _thaw_mapping(self.metadata),
            "mode": self.mode.value,
            "notation_id": self.notation_id.to_dict(),
            "profile_id": self.profile_id.to_dict(),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_map": None if self.source_map is None else self.source_map.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParseRequest":
        payload = _require_mapping(data, "ParseRequest")
        interface = payload.get("interface")
        if interface is not None and interface != PARSE_REQUEST_INTERFACE:
            raise SyntaxContractError(
                f"unsupported ParseRequest interface {interface!r}"
            )
        source_map_payload = payload.get("source_map")
        return cls(
            request_id=str(payload.get("request_id") or ""),
            document=SourceDocument.from_dict(
                _require_mapping(payload.get("document"), "document")
            ),
            notation_id=payload.get("notation_id") or "",
            profile_id=payload.get("profile_id") or "",
            family_id=payload.get("family_id"),
            mode=str(payload.get("mode") or ParseMode.STRICT.value),
            limits=ParseLimits.from_dict(
                _require_mapping(payload.get("limits") or {}, "limits")
            ),
            source_map=(
                None
                if source_map_payload is None
                else SourceMap.from_dict(
                    _require_mapping(source_map_payload, "source_map")
                )
            ),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or PARSE_REQUEST_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ParseArtifact:
    """Immutable parse result envelope.

    Interface: ``ParseArtifact@1``.
    """

    artifact_id: str
    request_id: str
    document_id: str
    status: ParseStatus | str
    tokens: tuple[LogicToken, ...] = ()
    cst: LogicCST | None = None
    surface_ast: tuple[SurfaceASTRef, ...] = ()
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    ambiguity_count: int = 0
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PARSE_ARTIFACT_SCHEMA_VERSION

    interface: ClassVar[str] = PARSE_ARTIFACT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _record_id(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        if isinstance(self.status, ParseStatus):
            status = self.status
        else:
            try:
                status = ParseStatus(_text(self.status, "status", maximum=32))
            except ValueError as error:
                raise SyntaxContractError(
                    f"status must be a ParseStatus value; got {self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        tokens = tuple(
            item
            if isinstance(item, LogicToken)
            else LogicToken.from_dict(_require_mapping(item, "tokens item"))
            for item in _require_sequence(self.tokens, "tokens")
        )
        if len(tokens) > MAX_TOKENS:
            raise SyntaxContractError("ParseArtifact.tokens exceeds hard ceiling")
        token_ids = [item.token_id for item in tokens]
        if len(token_ids) != len(set(token_ids)):
            raise SyntaxContractError("ParseArtifact.tokens must have unique token_id values")
        for token in tokens:
            if token.document_id and token.document_id != self.document_id:
                raise SyntaxContractError(
                    f"token {token.token_id} document_id does not match artifact"
                )
        object.__setattr__(self, "tokens", tokens)

        if self.cst is not None:
            if not isinstance(self.cst, LogicCST):
                object.__setattr__(
                    self,
                    "cst",
                    LogicCST.from_dict(_require_mapping(self.cst, "cst")),
                )
            if self.cst.document_id != self.document_id:
                raise SyntaxContractError(
                    "LogicCST.document_id must match ParseArtifact.document_id"
                )

        surface_ast = tuple(
            item
            if isinstance(item, SurfaceASTRef)
            else SurfaceASTRef.from_dict(_require_mapping(item, "surface_ast item"))
            for item in _require_sequence(self.surface_ast, "surface_ast")
        )
        if len(surface_ast) > MAX_CST_NODES:
            raise SyntaxContractError("surface_ast exceeds hard ceiling")
        ast_ids = [item.node_id for item in surface_ast]
        if len(ast_ids) != len(set(ast_ids)):
            raise SyntaxContractError(
                "surface_ast node_id values must be unique"
            )
        known_ast = set(ast_ids)
        for node in surface_ast:
            unknown = [child for child in node.child_ids if child not in known_ast]
            if unknown:
                raise SyntaxContractError(
                    f"surface AST node {node.node_id} references unknown child ids: "
                    f"{', '.join(unknown)}"
                )
        object.__setattr__(self, "surface_ast", surface_ast)

        diagnostics = tuple(
            item
            if isinstance(item, SyntaxDiagnostic)
            else SyntaxDiagnostic.from_dict(
                _require_mapping(item, "diagnostics item")
            )
            for item in _require_sequence(self.diagnostics, "diagnostics")
        )
        if len(diagnostics) > MAX_DIAGNOSTICS:
            raise SyntaxContractError(
                "ParseArtifact.diagnostics exceeds hard ceiling"
            )
        diagnostic_ids = [item.diagnostic_id for item in diagnostics]
        if len(diagnostic_ids) != len(set(diagnostic_ids)):
            raise SyntaxContractError(
                "duplicate diagnostics are rejected; diagnostic_id values must be unique"
            )
        known_diagnostics = set(diagnostic_ids)
        for item in diagnostics:
            dangling = [
                related
                for related in item.related_diagnostic_ids
                if related not in known_diagnostics
            ]
            if dangling:
                raise SyntaxContractError(
                    f"diagnostic {item.diagnostic_id} references unknown "
                    f"related diagnostics: {', '.join(dangling)}"
                )
        object.__setattr__(self, "diagnostics", diagnostics)

        ambiguity_count = _non_negative_int(self.ambiguity_count, "ambiguity_count")
        if ambiguity_count > MAX_AMBIGUITIES:
            raise SyntaxContractError("ambiguity_count exceeds hard ceiling")
        object.__setattr__(self, "ambiguity_count", ambiguity_count)

        if self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )
        else:
            identity = {
                "artifact_id": self.artifact_id,
                "cst": None if self.cst is None else self.cst.to_dict(),
                "diagnostics": [item.to_dict() for item in diagnostics],
                "document_id": self.document_id,
                "request_id": self.request_id,
                "status": status.value,
                "surface_ast": [item.to_dict() for item in surface_ast],
                "tokens": [item.to_dict() for item in tokens],
            }
            object.__setattr__(
                self,
                "content_digest",
                hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
            )

        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
        if self.schema_version != PARSE_ARTIFACT_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported ParseArtifact schema_version {self.schema_version!r}"
            )

        # Status-specific structural requirements.
        if status is ParseStatus.OK and any(item.is_error for item in diagnostics):
            raise SyntaxContractError(
                "ParseArtifact status ok cannot carry error/fatal diagnostics"
            )
        if status is ParseStatus.OK and self.cst is None:
            raise SyntaxContractError(
                "ParseArtifact status ok requires a LogicCST"
            )
        if status is ParseStatus.RECOVERED and self.cst is None:
            raise SyntaxContractError(
                "ParseArtifact status recovered requires a LogicCST"
            )

    def validate_against(
        self,
        document: SourceDocument,
        *,
        limits: ParseLimits | None = None,
    ) -> None:
        """Cross-check tokens, CST, diagnostics, and optional request limits."""

        if document.document_id != self.document_id:
            raise SyntaxContractError(
                "document_id does not match the supplied SourceDocument"
            )
        if limits is not None:
            if len(self.tokens) > limits.max_tokens:
                raise SyntaxContractError(
                    "token count exceeds ParseLimits.max_tokens"
                )
            if len(self.diagnostics) > limits.max_diagnostics:
                raise SyntaxContractError(
                    "diagnostic count exceeds ParseLimits.max_diagnostics"
                )
            if self.ambiguity_count > limits.max_ambiguities:
                raise SyntaxContractError(
                    "ambiguity_count exceeds ParseLimits.max_ambiguities"
                )
            if document.byte_length > limits.max_input_bytes:
                raise SyntaxContractError(
                    "source exceeds ParseLimits.max_input_bytes"
                )
        for token in self.tokens:
            token.validate_against(document)
        if self.cst is not None:
            if self.cst.source_length != document.byte_length:
                raise SyntaxContractError(
                    "LogicCST.source_length must equal SourceDocument.byte_length"
                )
            # Re-check coverage against the live document.
            if self.cst.require_complete_coverage:
                assert_complete_coverage(
                    self.cst.root.leaf_coverage_ranges(),
                    document.byte_length,
                    field_name="ParseArtifact CST coverage",
                )
        for node in self.surface_ast:
            node.range.validate_against(
                document.byte_length, field_name=f"surface AST {node.node_id}"
            )
        for diagnostic in self.diagnostics:
            diagnostic.validate_against(document)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_count": self.ambiguity_count,
            "artifact_id": self.artifact_id,
            "content_digest": self.content_digest,
            "cst": None if self.cst is None else self.cst.to_dict(),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document_id": self.document_id,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "surface_ast": [item.to_dict() for item in self.surface_ast],
            "tokens": [item.to_dict() for item in self.tokens],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParseArtifact":
        payload = _require_mapping(data, "ParseArtifact")
        interface = payload.get("interface")
        if interface is not None and interface != PARSE_ARTIFACT_INTERFACE:
            raise SyntaxContractError(
                f"unsupported ParseArtifact interface {interface!r}"
            )
        cst_payload = payload.get("cst")
        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            document_id=str(payload.get("document_id") or ""),
            status=str(payload.get("status") or ParseStatus.FAILED.value),
            tokens=tuple(
                LogicToken.from_dict(_require_mapping(item, "tokens item"))
                for item in _require_sequence(payload.get("tokens") or (), "tokens")
            ),
            cst=(
                None
                if cst_payload is None
                else LogicCST.from_dict(_require_mapping(cst_payload, "cst"))
            ),
            surface_ast=tuple(
                SurfaceASTRef.from_dict(_require_mapping(item, "surface_ast item"))
                for item in _require_sequence(
                    payload.get("surface_ast") or (), "surface_ast"
                )
            ),
            diagnostics=tuple(
                SyntaxDiagnostic.from_dict(
                    _require_mapping(item, "diagnostics item")
                )
                for item in _require_sequence(
                    payload.get("diagnostics") or (), "diagnostics"
                )
            ),
            ambiguity_count=int(payload.get("ambiguity_count") or 0),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or PARSE_ARTIFACT_SCHEMA_VERSION
            ),
        )


__all__ = [
    "CONTRACTS_MODULE_VERSION",
    "CSTNodeRole",
    "DIAGNOSTIC_SCHEMA_VERSION",
    "DiagnosticSeverity",
    "LOGIC_CST_INTERFACE",
    "LOGIC_CST_SCHEMA_VERSION",
    "LOGIC_TOKEN_INTERFACE",
    "LOGIC_TOKEN_SCHEMA_VERSION",
    "LogicCST",
    "LogicCSTNode",
    "LogicToken",
    "MAX_AMBIGUITIES",
    "MAX_CST_NODES",
    "MAX_DIAGNOSTICS",
    "MAX_MEMORY_BYTES",
    "MAX_PARSE_DEPTH",
    "MAX_SOURCE_BYTES",
    "MAX_TIME_MS",
    "MAX_TOKENS",
    "PARSE_ARTIFACT_INTERFACE",
    "PARSE_ARTIFACT_SCHEMA_VERSION",
    "PARSE_LIMITS_SCHEMA_VERSION",
    "PARSE_REQUEST_INTERFACE",
    "PARSE_REQUEST_SCHEMA_VERSION",
    "ParseArtifact",
    "ParseLimits",
    "ParseMode",
    "ParseRequest",
    "ParseStatus",
    "SAFE_ENCODINGS",
    "SOURCE_DOCUMENT_INTERFACE",
    "SOURCE_DOCUMENT_SCHEMA_VERSION",
    "SOURCE_MAP_SCHEMA_VERSION",
    "SOURCE_RANGE_SCHEMA_VERSION",
    "SURFACE_AST_REF_SCHEMA_VERSION",
    "SourceDocument",
    "SourceMap",
    "SourceMapEntry",
    "SourceRange",
    "SurfaceASTRef",
    "SyntaxContractError",
    "SyntaxDiagnostic",
    "TokenKind",
    "assert_complete_coverage",
    "build_line_index",
    "canonical_json_bytes",
    "content_sha256",
    "normalize_encoding_name",
    "require_namespace_identity",
]
