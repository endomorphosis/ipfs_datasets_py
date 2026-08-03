"""Immutable models for bounded inert Solidity parse results (CRYPTOIR-G730).

Records describe source-spanned declarations, relationships, control, state,
call, and effect *facts* extracted without executing or compiling corpus code.
Compiler, address, and verified-source fields are **evidence claims**, never
deployed semantics.

Importing this module performs no network I/O, secret resolution, package
installation, or ``solc`` invocation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import InvalidRequestError
from ..models import ensure_secret_safe


PARSER_SCHEMA_VERSION = "smart-contract-solidity-parser-v1"
PARSER_ID = "smart-contracts.solidity.parser"
PARSER_VERSION = "1.0.0"

# Default hard bounds (receipt-bound when overridden on a parse).
DEFAULT_MAX_SOURCE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_NODES = 50_000
DEFAULT_MAX_NESTING = 64
DEFAULT_MAX_IMPORTS = 256
DEFAULT_MAX_DIAGNOSTICS = 512
DEFAULT_MAX_DECLARATIONS = 4_096
DEFAULT_MAX_CALLS = 8_192
DEFAULT_MAX_FACTS = 16_384


class ParseStatus(StrEnum):
    """Structured parse outcome; non-success statuses fail closed for assurance."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    CANCELLED = "cancelled"
    RESOURCE_LIMIT = "resource_limit"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    INVALID_INPUT = "invalid_input"


class ContractKind(StrEnum):
    """Top-level Solidity type-definition kind."""

    CONTRACT = "contract"
    LIBRARY = "library"
    INTERFACE = "interface"
    ABSTRACT_CONTRACT = "abstract_contract"
    UNKNOWN = "unknown"


class Visibility(StrEnum):
    """Function / state-variable visibility."""

    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"
    EXTERNAL = "external"
    DEFAULT = "default"
    UNKNOWN = "unknown"


class StateMutability(StrEnum):
    """Function state mutability."""

    PURE = "pure"
    VIEW = "view"
    PAYABLE = "payable"
    NONPAYABLE = "nonpayable"
    UNKNOWN = "unknown"


class StorageAccessKind(StrEnum):
    """Read or write of a named storage location (syntactic)."""

    READ = "read"
    WRITE = "write"
    UNKNOWN = "unknown"


class CallKind(StrEnum):
    """Syntactic call form (not runtime dispatch proof)."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    SUPER = "super"
    LIBRARY = "library"
    BUILTIN = "builtin"
    LOW_LEVEL = "low_level"
    CREATE = "create"
    CREATE2 = "create2"
    DELEGATECALL = "delegatecall"
    STATICCALL = "staticcall"
    CALLCODE = "callcode"
    UNKNOWN = "unknown"


class AuthGuardKind(StrEnum):
    """Authorization / access-control guard patterns observed in source."""

    MODIFIER = "modifier"
    REQUIRE = "require"
    ASSERT_STMT = "assert"
    REVERT = "revert"
    IF_REVERT = "if_revert"
    OWNABLE = "ownable"
    ROLE = "role"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class ValueEffectKind(StrEnum):
    """Value / balance effect patterns observed in source (syntactic)."""

    TRANSFER = "transfer"
    SEND = "send"
    CALL_VALUE = "call_value"
    SELFDESTRUCT = "selfdestruct"
    PAYABLE_RECEIVE = "payable_receive"
    PAYABLE_FALLBACK = "payable_fallback"
    EMIT_VALUE = "emit_value"
    UNKNOWN = "unknown"


class DiagnosticSeverity(StrEnum):
    """Parse diagnostic severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    LIMIT = "limit"


class ClaimKind(StrEnum):
    """Evidence claim kinds that must not be treated as deployed semantics."""

    COMPILER = "compiler"
    ADDRESS = "address"
    VERIFIED_SOURCE = "verified_source"
    LICENSE = "license"
    SOURCE_PATH = "source_path"
    OTHER = "other"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _optional_text(value: str | None) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise InvalidRequestError("text field must be a string")
    if value != value.strip():
        raise InvalidRequestError("text field must not have surrounding whitespace")
    return value


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Exact half-open byte offsets and 1-based line/column coordinates.

    Offsets are UTF-8 byte offsets into the source unit bytes.  Line and column
    are 1-based; column is a Unicode code-point offset within the line.
    """

    start_offset: int
    end_offset: int
    start_line: int = 1
    start_column: int = 1
    end_line: int = 1
    end_column: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "start_offset", _non_negative(self.start_offset, "start_offset")
        )
        object.__setattr__(
            self, "end_offset", _non_negative(self.end_offset, "end_offset")
        )
        if self.end_offset < self.start_offset:
            raise InvalidRequestError("end_offset must be >= start_offset")
        object.__setattr__(
            self, "start_line", _positive(self.start_line, "start_line")
        )
        object.__setattr__(
            self, "start_column", _positive(self.start_column, "start_column")
        )
        object.__setattr__(self, "end_line", _positive(self.end_line, "end_line"))
        object.__setattr__(
            self, "end_column", _positive(self.end_column, "end_column")
        )

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset

    def to_dict(self) -> dict[str, Any]:
        return {
            "end_column": self.end_column,
            "end_line": self.end_line,
            "end_offset": self.end_offset,
            "start_column": self.start_column,
            "start_line": self.start_line,
            "start_offset": self.start_offset,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceSpan":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SourceSpan must be a mapping")
        return cls(
            start_offset=int(value.get("start_offset", 0)),
            end_offset=int(value.get("end_offset", 0)),
            start_line=int(value.get("start_line", 1)),
            start_column=int(value.get("start_column", 1)),
            end_line=int(value.get("end_line", 1)),
            end_column=int(value.get("end_column", 1)),
        )


@dataclass(frozen=True, slots=True)
class ParserBounds:
    """Hard parse budgets; receipt-bound on every result."""

    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_nodes: int = DEFAULT_MAX_NODES
    max_nesting: int = DEFAULT_MAX_NESTING
    max_imports: int = DEFAULT_MAX_IMPORTS
    max_diagnostics: int = DEFAULT_MAX_DIAGNOSTICS
    max_declarations: int = DEFAULT_MAX_DECLARATIONS
    max_calls: int = DEFAULT_MAX_CALLS
    max_facts: int = DEFAULT_MAX_FACTS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_source_bytes",
            _positive(self.max_source_bytes, "max_source_bytes"),
        )
        object.__setattr__(self, "max_nodes", _positive(self.max_nodes, "max_nodes"))
        object.__setattr__(
            self, "max_nesting", _positive(self.max_nesting, "max_nesting")
        )
        object.__setattr__(
            self, "max_imports", _positive(self.max_imports, "max_imports")
        )
        object.__setattr__(
            self,
            "max_diagnostics",
            _positive(self.max_diagnostics, "max_diagnostics"),
        )
        object.__setattr__(
            self,
            "max_declarations",
            _positive(self.max_declarations, "max_declarations"),
        )
        object.__setattr__(self, "max_calls", _positive(self.max_calls, "max_calls"))
        object.__setattr__(self, "max_facts", _positive(self.max_facts, "max_facts"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "max_declarations": self.max_declarations,
            "max_diagnostics": self.max_diagnostics,
            "max_facts": self.max_facts,
            "max_imports": self.max_imports,
            "max_nesting": self.max_nesting,
            "max_nodes": self.max_nodes,
            "max_source_bytes": self.max_source_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParserBounds":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ParserBounds must be a mapping")
        return cls(
            max_source_bytes=int(
                value.get("max_source_bytes", DEFAULT_MAX_SOURCE_BYTES)
            ),
            max_nodes=int(value.get("max_nodes", DEFAULT_MAX_NODES)),
            max_nesting=int(value.get("max_nesting", DEFAULT_MAX_NESTING)),
            max_imports=int(value.get("max_imports", DEFAULT_MAX_IMPORTS)),
            max_diagnostics=int(
                value.get("max_diagnostics", DEFAULT_MAX_DIAGNOSTICS)
            ),
            max_declarations=int(
                value.get("max_declarations", DEFAULT_MAX_DECLARATIONS)
            ),
            max_calls=int(value.get("max_calls", DEFAULT_MAX_CALLS)),
            max_facts=int(value.get("max_facts", DEFAULT_MAX_FACTS)),
        )


@dataclass(frozen=True, slots=True)
class ParserConfig:
    """Parser configuration bound into every parse receipt.

    ``backend`` is the extraction engine identity.  The default ``"inert"``
    backend is pure Python and never requires ``solc``.  Optional backends may
    be injected; when unavailable the parser returns a typed UNSUPPORTED result
    rather than installing or shelling out at import time.
    """

    backend: str = "inert"
    preserve_comments: bool = False
    extract_calls: bool = True
    extract_storage: bool = True
    extract_auth_guards: bool = True
    extract_value_effects: bool = True
    extract_assembly: bool = True
    resolve_imports: bool = False  # always offline; never network
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "backend", _required_text(self.backend, "backend")
        )
        if self.resolve_imports:
            raise InvalidRequestError(
                "resolve_imports must be false; imports never resolve over the network"
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "backend": self.backend,
            "extract_assembly": self.extract_assembly,
            "extract_auth_guards": self.extract_auth_guards,
            "extract_calls": self.extract_calls,
            "extract_storage": self.extract_storage,
            "extract_value_effects": self.extract_value_effects,
            "preserve_comments": self.preserve_comments,
            "resolve_imports": self.resolve_imports,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParserConfig":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ParserConfig must be a mapping")
        return cls(
            backend=str(value.get("backend", "inert")),
            preserve_comments=bool(value.get("preserve_comments", False)),
            extract_calls=bool(value.get("extract_calls", True)),
            extract_storage=bool(value.get("extract_storage", True)),
            extract_auth_guards=bool(value.get("extract_auth_guards", True)),
            extract_value_effects=bool(value.get("extract_value_effects", True)),
            extract_assembly=bool(value.get("extract_assembly", True)),
            resolve_imports=bool(value.get("resolve_imports", False)),
            attributes=value.get("attributes", {}),
        )

    @property
    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ParserIdentity:
    """Receipt-bound parser identity and version."""

    parser_id: str = PARSER_ID
    parser_version: str = PARSER_VERSION
    schema_version: str = PARSER_SCHEMA_VERSION
    config_digest: str = ""
    bounds_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "parser_id", _required_text(self.parser_id, "parser_id")
        )
        object.__setattr__(
            self,
            "parser_version",
            _required_text(self.parser_version, "parser_version"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "config_digest", _optional_text(self.config_digest)
        )
        object.__setattr__(
            self, "bounds_digest", _optional_text(self.bounds_digest)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds_digest": self.bounds_digest,
            "config_digest": self.config_digest,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParserIdentity":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ParserIdentity must be a mapping")
        return cls(
            parser_id=str(value.get("parser_id", PARSER_ID)),
            parser_version=str(value.get("parser_version", PARSER_VERSION)),
            schema_version=str(value.get("schema_version", PARSER_SCHEMA_VERSION)),
            config_digest=str(value.get("config_digest", "")),
            bounds_digest=str(value.get("bounds_digest", "")),
        )


@dataclass(frozen=True, slots=True)
class ParseDiagnostic:
    """One bounded diagnostic attached to a parse result."""

    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO
    span: SourceSpan | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "code"))
        object.__setattr__(
            self, "message", _required_text(self.message, "message")
        )
        if not isinstance(self.severity, DiagnosticSeverity):
            object.__setattr__(
                self, "severity", DiagnosticSeverity(str(self.severity))
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "span": self.span.to_dict() if self.span is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParseDiagnostic":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ParseDiagnostic must be a mapping")
        span_raw = value.get("span")
        return cls(
            code=str(value.get("code", "")),
            message=str(value.get("message", "")),
            severity=DiagnosticSeverity(str(value.get("severity", "info"))),
            span=SourceSpan.from_dict(span_raw) if span_raw else None,
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """Unverified metadata claim (compiler/address/path); never deployed truth."""

    kind: ClaimKind
    value: str
    span: SourceSpan | None = None
    source_field: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ClaimKind):
            object.__setattr__(self, "kind", ClaimKind(str(self.kind)))
        object.__setattr__(self, "value", _optional_text(self.value) if self.value else "")
        object.__setattr__(
            self, "source_field", _optional_text(self.source_field)
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "kind": self.kind.value,
            "source_field": self.source_field,
            "span": self.span.to_dict() if self.span is not None else None,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceClaim":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("EvidenceClaim must be a mapping")
        span_raw = value.get("span")
        return cls(
            kind=ClaimKind(str(value.get("kind", "other"))),
            value=str(value.get("value", "")),
            span=SourceSpan.from_dict(span_raw) if span_raw else None,
            source_field=str(value.get("source_field", "")),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class SolidityImport:
    """Import directive; path is preserved but never network-resolved."""

    path: str
    span: SourceSpan
    symbols: tuple[str, ...] = ()
    alias: str = ""
    is_star: bool = False
    resolved: bool = False  # always False under inert offline policy
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _required_text(self.path, "path"))
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "alias", _optional_text(self.alias))
        if self.resolved:
            raise InvalidRequestError(
                "imports never resolve over the network; resolved must be false"
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "attributes": thaw_json(self.attributes),
            "is_star": self.is_star,
            "path": self.path,
            "resolved": self.resolved,
            "span": self.span.to_dict(),
            "symbols": list(self.symbols),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityImport":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SolidityImport must be a mapping")
        return cls(
            path=str(value.get("path", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            symbols=tuple(value.get("symbols", ()) or ()),
            alias=str(value.get("alias", "")),
            is_star=bool(value.get("is_star", False)),
            resolved=bool(value.get("resolved", False)),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class SolidityPragma:
    """``pragma`` directive (e.g. solidity version)."""

    name: str
    value: str
    span: SourceSpan

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "value", _optional_text(self.value) if self.value else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "span": self.span.to_dict(),
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityPragma":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SolidityPragma must be a mapping")
        return cls(
            name=str(value.get("name", "")),
            value=str(value.get("value", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
        )


@dataclass(frozen=True, slots=True)
class InheritanceRef:
    """Base type reference on a contract/library/interface header."""

    name: str
    span: SourceSpan
    arguments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "arguments", tuple(self.arguments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": list(self.arguments),
            "name": self.name,
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InheritanceRef":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("InheritanceRef must be a mapping")
        return cls(
            name=str(value.get("name", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            arguments=tuple(value.get("arguments", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class ParameterFact:
    """Function / event / error / modifier parameter."""

    name: str
    type_name: str
    span: SourceSpan
    indexed: bool = False
    storage_location: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _optional_text(self.name))
        object.__setattr__(
            self, "type_name", _required_text(self.type_name, "type_name")
        )
        object.__setattr__(
            self, "storage_location", _optional_text(self.storage_location)
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "indexed": self.indexed,
            "name": self.name,
            "span": self.span.to_dict(),
            "storage_location": self.storage_location,
            "type_name": self.type_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParameterFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ParameterFact must be a mapping")
        return cls(
            name=str(value.get("name", "")),
            type_name=str(value.get("type_name", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            indexed=bool(value.get("indexed", False)),
            storage_location=str(value.get("storage_location", "")),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class FunctionFact:
    """Function, constructor, receive, or fallback declaration."""

    name: str
    span: SourceSpan
    kind: str = "function"  # function|constructor|receive|fallback|modifier
    visibility: Visibility = Visibility.DEFAULT
    state_mutability: StateMutability = StateMutability.UNKNOWN
    parameters: tuple[ParameterFact, ...] = ()
    returns: tuple[ParameterFact, ...] = ()
    modifiers: tuple[str, ...] = ()
    is_virtual: bool = False
    is_override: bool = False
    body_span: SourceSpan | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _optional_text(self.name))
        object.__setattr__(self, "kind", _required_text(self.kind, "kind"))
        if not isinstance(self.visibility, Visibility):
            object.__setattr__(
                self, "visibility", Visibility(str(self.visibility))
            )
        if not isinstance(self.state_mutability, StateMutability):
            object.__setattr__(
                self,
                "state_mutability",
                StateMutability(str(self.state_mutability)),
            )
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "returns", tuple(self.returns))
        object.__setattr__(self, "modifiers", tuple(self.modifiers))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "body_span": self.body_span.to_dict() if self.body_span else None,
            "is_override": self.is_override,
            "is_virtual": self.is_virtual,
            "kind": self.kind,
            "modifiers": list(self.modifiers),
            "name": self.name,
            "parameters": [p.to_dict() for p in self.parameters],
            "returns": [p.to_dict() for p in self.returns],
            "span": self.span.to_dict(),
            "state_mutability": self.state_mutability.value,
            "visibility": self.visibility.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FunctionFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("FunctionFact must be a mapping")
        body = value.get("body_span")
        return cls(
            name=str(value.get("name", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            kind=str(value.get("kind", "function")),
            visibility=Visibility(str(value.get("visibility", "default"))),
            state_mutability=StateMutability(
                str(value.get("state_mutability", "unknown"))
            ),
            parameters=tuple(
                ParameterFact.from_dict(p)
                for p in (value.get("parameters") or ())
            ),
            returns=tuple(
                ParameterFact.from_dict(p) for p in (value.get("returns") or ())
            ),
            modifiers=tuple(value.get("modifiers", ()) or ()),
            is_virtual=bool(value.get("is_virtual", False)),
            is_override=bool(value.get("is_override", False)),
            body_span=SourceSpan.from_dict(body) if body else None,
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class StateVariableFact:
    """Contract state variable declaration."""

    name: str
    type_name: str
    span: SourceSpan
    visibility: Visibility = Visibility.DEFAULT
    is_constant: bool = False
    is_immutable: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(
            self, "type_name", _required_text(self.type_name, "type_name")
        )
        if not isinstance(self.visibility, Visibility):
            object.__setattr__(
                self, "visibility", Visibility(str(self.visibility))
            )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "is_constant": self.is_constant,
            "is_immutable": self.is_immutable,
            "name": self.name,
            "span": self.span.to_dict(),
            "type_name": self.type_name,
            "visibility": self.visibility.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateVariableFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("StateVariableFact must be a mapping")
        return cls(
            name=str(value.get("name", "")),
            type_name=str(value.get("type_name", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            visibility=Visibility(str(value.get("visibility", "default"))),
            is_constant=bool(value.get("is_constant", False)),
            is_immutable=bool(value.get("is_immutable", False)),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class EventFact:
    """Event declaration."""

    name: str
    span: SourceSpan
    parameters: tuple[ParameterFact, ...] = ()
    is_anonymous: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "parameters", tuple(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_anonymous": self.is_anonymous,
            "name": self.name,
            "parameters": [p.to_dict() for p in self.parameters],
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EventFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("EventFact must be a mapping")
        return cls(
            name=str(value.get("name", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            parameters=tuple(
                ParameterFact.from_dict(p)
                for p in (value.get("parameters") or ())
            ),
            is_anonymous=bool(value.get("is_anonymous", False)),
        )


@dataclass(frozen=True, slots=True)
class ErrorFact:
    """Custom error declaration."""

    name: str
    span: SourceSpan
    parameters: tuple[ParameterFact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "parameters", tuple(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": [p.to_dict() for p in self.parameters],
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ErrorFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ErrorFact must be a mapping")
        return cls(
            name=str(value.get("name", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            parameters=tuple(
                ParameterFact.from_dict(p)
                for p in (value.get("parameters") or ())
            ),
        )


@dataclass(frozen=True, slots=True)
class CallFact:
    """Syntactic call / create / low-level call observation."""

    kind: CallKind
    callee: str
    span: SourceSpan
    enclosing: str = ""
    value_expression: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CallKind):
            object.__setattr__(self, "kind", CallKind(str(self.kind)))
        object.__setattr__(self, "callee", _required_text(self.callee, "callee"))
        object.__setattr__(self, "enclosing", _optional_text(self.enclosing))
        object.__setattr__(
            self, "value_expression", _optional_text(self.value_expression)
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "callee": self.callee,
            "enclosing": self.enclosing,
            "kind": self.kind.value,
            "span": self.span.to_dict(),
            "value_expression": self.value_expression,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CallFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("CallFact must be a mapping")
        return cls(
            kind=CallKind(str(value.get("kind", "unknown"))),
            callee=str(value.get("callee", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            enclosing=str(value.get("enclosing", "")),
            value_expression=str(value.get("value_expression", "")),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class StorageAccessFact:
    """Syntactic storage read/write observation."""

    kind: StorageAccessKind
    target: str
    span: SourceSpan
    enclosing: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StorageAccessKind):
            object.__setattr__(
                self, "kind", StorageAccessKind(str(self.kind))
            )
        object.__setattr__(self, "target", _required_text(self.target, "target"))
        object.__setattr__(self, "enclosing", _optional_text(self.enclosing))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enclosing": self.enclosing,
            "kind": self.kind.value,
            "span": self.span.to_dict(),
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StorageAccessFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("StorageAccessFact must be a mapping")
        return cls(
            kind=StorageAccessKind(str(value.get("kind", "unknown"))),
            target=str(value.get("target", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            enclosing=str(value.get("enclosing", "")),
        )


@dataclass(frozen=True, slots=True)
class AuthGuardFact:
    """Authorization guard observation (modifier, require, role, ...)."""

    kind: AuthGuardKind
    expression: str
    span: SourceSpan
    enclosing: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AuthGuardKind):
            object.__setattr__(self, "kind", AuthGuardKind(str(self.kind)))
        object.__setattr__(
            self, "expression", _required_text(self.expression, "expression")
        )
        object.__setattr__(self, "enclosing", _optional_text(self.enclosing))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enclosing": self.enclosing,
            "expression": self.expression,
            "kind": self.kind.value,
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthGuardFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("AuthGuardFact must be a mapping")
        return cls(
            kind=AuthGuardKind(str(value.get("kind", "unknown"))),
            expression=str(value.get("expression", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            enclosing=str(value.get("enclosing", "")),
        )


@dataclass(frozen=True, slots=True)
class ValueEffectFact:
    """Value / balance effect observation."""

    kind: ValueEffectKind
    expression: str
    span: SourceSpan
    enclosing: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ValueEffectKind):
            object.__setattr__(
                self, "kind", ValueEffectKind(str(self.kind))
            )
        object.__setattr__(
            self, "expression", _required_text(self.expression, "expression")
        )
        object.__setattr__(self, "enclosing", _optional_text(self.enclosing))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enclosing": self.enclosing,
            "expression": self.expression,
            "kind": self.kind.value,
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValueEffectFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ValueEffectFact must be a mapping")
        return cls(
            kind=ValueEffectKind(str(value.get("kind", "unknown"))),
            expression=str(value.get("expression", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            enclosing=str(value.get("enclosing", "")),
        )


@dataclass(frozen=True, slots=True)
class AssemblyBlockFact:
    """Inline assembly / Yul block (body not executed)."""

    span: SourceSpan
    dialect: str = "assembly"
    enclosing: str = ""
    body_preview: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "dialect", _required_text(self.dialect, "dialect"))
        object.__setattr__(self, "enclosing", _optional_text(self.enclosing))
        # Bound body preview length to keep records finite.
        preview = self.body_preview if isinstance(self.body_preview, str) else ""
        if len(preview) > 256:
            preview = preview[:256]
        object.__setattr__(self, "body_preview", preview)

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_preview": self.body_preview,
            "dialect": self.dialect,
            "enclosing": self.enclosing,
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssemblyBlockFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("AssemblyBlockFact must be a mapping")
        return cls(
            span=SourceSpan.from_dict(value.get("span", {})),
            dialect=str(value.get("dialect", "assembly")),
            enclosing=str(value.get("enclosing", "")),
            body_preview=str(value.get("body_preview", "")),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedSyntaxFact:
    """Explicit unsupported or incomplete syntax region."""

    reason: str
    span: SourceSpan
    construct: str = ""
    disposition: str = "preserve_opaque"

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _required_text(self.reason, "reason"))
        object.__setattr__(self, "construct", _optional_text(self.construct))
        object.__setattr__(
            self, "disposition", _required_text(self.disposition, "disposition")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "construct": self.construct,
            "disposition": self.disposition,
            "reason": self.reason,
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsupportedSyntaxFact":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("UnsupportedSyntaxFact must be a mapping")
        return cls(
            reason=str(value.get("reason", "")),
            span=SourceSpan.from_dict(value.get("span", {})),
            construct=str(value.get("construct", "")),
            disposition=str(value.get("disposition", "preserve_opaque")),
        )


@dataclass(frozen=True, slots=True)
class SolidityTypeDefinition:
    """Contract, library, or interface definition with members and facts."""

    name: str
    kind: ContractKind
    span: SourceSpan
    inheritance: tuple[InheritanceRef, ...] = ()
    functions: tuple[FunctionFact, ...] = ()
    modifiers: tuple[FunctionFact, ...] = ()
    state_variables: tuple[StateVariableFact, ...] = ()
    events: tuple[EventFact, ...] = ()
    errors: tuple[ErrorFact, ...] = ()
    calls: tuple[CallFact, ...] = ()
    storage_accesses: tuple[StorageAccessFact, ...] = ()
    auth_guards: tuple[AuthGuardFact, ...] = ()
    value_effects: tuple[ValueEffectFact, ...] = ()
    assembly_blocks: tuple[AssemblyBlockFact, ...] = ()
    unsupported: tuple[UnsupportedSyntaxFact, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        if not isinstance(self.kind, ContractKind):
            object.__setattr__(self, "kind", ContractKind(str(self.kind)))
        object.__setattr__(self, "inheritance", tuple(self.inheritance))
        object.__setattr__(self, "functions", tuple(self.functions))
        object.__setattr__(self, "modifiers", tuple(self.modifiers))
        object.__setattr__(self, "state_variables", tuple(self.state_variables))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "calls", tuple(self.calls))
        object.__setattr__(self, "storage_accesses", tuple(self.storage_accesses))
        object.__setattr__(self, "auth_guards", tuple(self.auth_guards))
        object.__setattr__(self, "value_effects", tuple(self.value_effects))
        object.__setattr__(self, "assembly_blocks", tuple(self.assembly_blocks))
        object.__setattr__(self, "unsupported", tuple(self.unsupported))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assembly_blocks": [a.to_dict() for a in self.assembly_blocks],
            "attributes": thaw_json(self.attributes),
            "auth_guards": [a.to_dict() for a in self.auth_guards],
            "calls": [c.to_dict() for c in self.calls],
            "errors": [e.to_dict() for e in self.errors],
            "events": [e.to_dict() for e in self.events],
            "functions": [f.to_dict() for f in self.functions],
            "inheritance": [i.to_dict() for i in self.inheritance],
            "kind": self.kind.value,
            "modifiers": [m.to_dict() for m in self.modifiers],
            "name": self.name,
            "span": self.span.to_dict(),
            "state_variables": [s.to_dict() for s in self.state_variables],
            "storage_accesses": [s.to_dict() for s in self.storage_accesses],
            "unsupported": [u.to_dict() for u in self.unsupported],
            "value_effects": [v.to_dict() for v in self.value_effects],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityTypeDefinition":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SolidityTypeDefinition must be a mapping")
        return cls(
            name=str(value.get("name", "")),
            kind=ContractKind(str(value.get("kind", "unknown"))),
            span=SourceSpan.from_dict(value.get("span", {})),
            inheritance=tuple(
                InheritanceRef.from_dict(i)
                for i in (value.get("inheritance") or ())
            ),
            functions=tuple(
                FunctionFact.from_dict(f)
                for f in (value.get("functions") or ())
            ),
            modifiers=tuple(
                FunctionFact.from_dict(m)
                for m in (value.get("modifiers") or ())
            ),
            state_variables=tuple(
                StateVariableFact.from_dict(s)
                for s in (value.get("state_variables") or ())
            ),
            events=tuple(
                EventFact.from_dict(e) for e in (value.get("events") or ())
            ),
            errors=tuple(
                ErrorFact.from_dict(e) for e in (value.get("errors") or ())
            ),
            calls=tuple(
                CallFact.from_dict(c) for c in (value.get("calls") or ())
            ),
            storage_accesses=tuple(
                StorageAccessFact.from_dict(s)
                for s in (value.get("storage_accesses") or ())
            ),
            auth_guards=tuple(
                AuthGuardFact.from_dict(a)
                for a in (value.get("auth_guards") or ())
            ),
            value_effects=tuple(
                ValueEffectFact.from_dict(v)
                for v in (value.get("value_effects") or ())
            ),
            assembly_blocks=tuple(
                AssemblyBlockFact.from_dict(a)
                for a in (value.get("assembly_blocks") or ())
            ),
            unsupported=tuple(
                UnsupportedSyntaxFact.from_dict(u)
                for u in (value.get("unsupported") or ())
            ),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class SoliditySourceUnit:
    """Normalized source unit: pragmas, imports, type definitions, claims."""

    source_digest: str
    path: str = ""
    byte_length: int = 0
    pragmas: tuple[SolidityPragma, ...] = ()
    imports: tuple[SolidityImport, ...] = ()
    type_definitions: tuple[SolidityTypeDefinition, ...] = ()
    evidence_claims: tuple[EvidenceClaim, ...] = ()
    unsupported: tuple[UnsupportedSyntaxFact, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PARSER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        digest = _required_text(self.source_digest, "source_digest")
        if not digest.startswith("sha256:"):
            raise InvalidRequestError("source_digest must be a tagged sha256 digest")
        object.__setattr__(self, "source_digest", digest)
        object.__setattr__(self, "path", _optional_text(self.path))
        object.__setattr__(
            self, "byte_length", _non_negative(self.byte_length, "byte_length")
        )
        object.__setattr__(self, "pragmas", tuple(self.pragmas))
        object.__setattr__(self, "imports", tuple(self.imports))
        object.__setattr__(self, "type_definitions", tuple(self.type_definitions))
        object.__setattr__(self, "evidence_claims", tuple(self.evidence_claims))
        object.__setattr__(self, "unsupported", tuple(self.unsupported))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "evidence_claims": [c.to_dict() for c in self.evidence_claims],
            "imports": [i.to_dict() for i in self.imports],
            "path": self.path,
            "pragmas": [p.to_dict() for p in self.pragmas],
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "type_definitions": [t.to_dict() for t in self.type_definitions],
            "unsupported": [u.to_dict() for u in self.unsupported],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SoliditySourceUnit":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SoliditySourceUnit must be a mapping")
        return cls(
            source_digest=str(value.get("source_digest", "")),
            path=str(value.get("path", "")),
            byte_length=int(value.get("byte_length", 0)),
            pragmas=tuple(
                SolidityPragma.from_dict(p)
                for p in (value.get("pragmas") or ())
            ),
            imports=tuple(
                SolidityImport.from_dict(i)
                for i in (value.get("imports") or ())
            ),
            type_definitions=tuple(
                SolidityTypeDefinition.from_dict(t)
                for t in (value.get("type_definitions") or ())
            ),
            evidence_claims=tuple(
                EvidenceClaim.from_dict(c)
                for c in (value.get("evidence_claims") or ())
            ),
            unsupported=tuple(
                UnsupportedSyntaxFact.from_dict(u)
                for u in (value.get("unsupported") or ())
            ),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", PARSER_SCHEMA_VERSION)
            ),
        )

    @property
    def content_digest(self) -> str:
        return content_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ParseUsage:
    """Observed resource usage against receipt-bound budgets."""

    source_bytes: int = 0
    nodes: int = 0
    max_nesting_seen: int = 0
    imports: int = 0
    diagnostics: int = 0
    declarations: int = 0
    calls: int = 0
    facts: int = 0
    elapsed_ms: int = 0

    def __post_init__(self) -> None:
        for name in (
            "source_bytes",
            "nodes",
            "max_nesting_seen",
            "imports",
            "diagnostics",
            "declarations",
            "calls",
            "facts",
            "elapsed_ms",
        ):
            object.__setattr__(
                self, name, _non_negative(getattr(self, name), name)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "declarations": self.declarations,
            "diagnostics": self.diagnostics,
            "elapsed_ms": self.elapsed_ms,
            "facts": self.facts,
            "imports": self.imports,
            "max_nesting_seen": self.max_nesting_seen,
            "nodes": self.nodes,
            "source_bytes": self.source_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParseUsage":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ParseUsage must be a mapping")
        return cls(
            source_bytes=int(value.get("source_bytes", 0)),
            nodes=int(value.get("nodes", 0)),
            max_nesting_seen=int(value.get("max_nesting_seen", 0)),
            imports=int(value.get("imports", 0)),
            diagnostics=int(value.get("diagnostics", 0)),
            declarations=int(value.get("declarations", 0)),
            calls=int(value.get("calls", 0)),
            facts=int(value.get("facts", 0)),
            elapsed_ms=int(value.get("elapsed_ms", 0)),
        )


@dataclass(frozen=True, slots=True)
class SolidityParseResult:
    """Full parse receipt: status, unit, identity, bounds, usage, diagnostics."""

    status: ParseStatus
    identity: ParserIdentity
    bounds: ParserBounds
    config: ParserConfig
    usage: ParseUsage = field(default_factory=ParseUsage)
    source_unit: SoliditySourceUnit | None = None
    diagnostics: tuple[ParseDiagnostic, ...] = ()
    partial: bool = False
    notes: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PARSER_SCHEMA_VERSION

    SCHEMA_VERSION: ClassVar[str] = PARSER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, ParseStatus):
            object.__setattr__(self, "status", ParseStatus(str(self.status)))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "notes", tuple(self.notes))
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        # Consistency: partial flag when status is partial or coverage incomplete.
        if self.status is ParseStatus.PARTIAL:
            object.__setattr__(self, "partial", True)

    @property
    def is_success(self) -> bool:
        return self.status in (ParseStatus.OK, ParseStatus.PARTIAL)

    @property
    def is_unsupported(self) -> bool:
        return self.status is ParseStatus.UNSUPPORTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "bounds": self.bounds.to_dict(),
            "config": self.config.to_dict(),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "identity": self.identity.to_dict(),
            "notes": list(self.notes),
            "partial": self.partial,
            "schema_version": self.schema_version,
            "source_unit": (
                self.source_unit.to_dict() if self.source_unit is not None else None
            ),
            "status": self.status.value,
            "usage": self.usage.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityParseResult":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("SolidityParseResult must be a mapping")
        unit_raw = value.get("source_unit")
        return cls(
            status=ParseStatus(str(value.get("status", "failed"))),
            identity=ParserIdentity.from_dict(value.get("identity", {})),
            bounds=ParserBounds.from_dict(value.get("bounds", {})),
            config=ParserConfig.from_dict(value.get("config", {})),
            usage=ParseUsage.from_dict(value.get("usage", {})),
            source_unit=(
                SoliditySourceUnit.from_dict(unit_raw) if unit_raw else None
            ),
            diagnostics=tuple(
                ParseDiagnostic.from_dict(d)
                for d in (value.get("diagnostics") or ())
            ),
            partial=bool(value.get("partial", False)),
            notes=tuple(value.get("notes", ()) or ()),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", PARSER_SCHEMA_VERSION)
            ),
        )

    @property
    def content_digest(self) -> str:
        return content_digest(self.to_dict())


__all__ = [
    "DEFAULT_MAX_CALLS",
    "DEFAULT_MAX_DECLARATIONS",
    "DEFAULT_MAX_DIAGNOSTICS",
    "DEFAULT_MAX_FACTS",
    "DEFAULT_MAX_IMPORTS",
    "DEFAULT_MAX_NESTING",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_SOURCE_BYTES",
    "PARSER_ID",
    "PARSER_SCHEMA_VERSION",
    "PARSER_VERSION",
    "AssemblyBlockFact",
    "AuthGuardFact",
    "AuthGuardKind",
    "CallFact",
    "CallKind",
    "ClaimKind",
    "ContractKind",
    "DiagnosticSeverity",
    "ErrorFact",
    "EventFact",
    "EvidenceClaim",
    "FunctionFact",
    "InheritanceRef",
    "ParameterFact",
    "ParseDiagnostic",
    "ParseStatus",
    "ParseUsage",
    "ParserBounds",
    "ParserConfig",
    "ParserIdentity",
    "SolidityImport",
    "SolidityParseResult",
    "SolidityPragma",
    "SoliditySourceUnit",
    "SolidityTypeDefinition",
    "SourceSpan",
    "StateMutability",
    "StateVariableFact",
    "StorageAccessFact",
    "StorageAccessKind",
    "UnsupportedSyntaxFact",
    "ValueEffectFact",
    "ValueEffectKind",
    "Visibility",
]
