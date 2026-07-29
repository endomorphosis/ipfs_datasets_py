"""Immutable language-neutral AST and symbol records.

This module is the serialized shared-schema owner for DSCON-G105.  Frontends
emit lexical parsing facts into :class:`ASTRecord`; later resolver stages join
those facts by stable IDs.  In particular, references and calls intentionally
contain no resolved target or confidence claim.

All durable payloads are closed, strict DAG-JSON values.  Records reject
process-local objects, floats, booleans masquerading as integers, unsafe
cross-runtime integers, non-normalized text, duplicate JSON keys, and
language-specific escape-hatch mappings.  Content identity uses the canonical
software-contract CID profile from :mod:`.content`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final, Mapping, Sequence, TypeVar

from ipfs_datasets_py.logic.software_contracts.content import (
    SOURCE_CODEC,
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.schema_versions import (
    AST_IR_SCHEMA_VERSION,
    FRONTEND_CAPABILITY_SCHEMA_VERSION,
    SchemaVersion,
    SchemaVersionError,
)


MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
AST_IR_DESCRIPTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.ast-ir-descriptor@1"
)
_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,511}$"
)
_CAPABILITY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
)

SYMBOL_KINDS: Final[frozenset[str]] = frozenset(
    {
        "module",
        "namespace",
        "class",
        "interface",
        "protocol",
        "function",
        "method",
        "constructor",
        "property",
        "variable",
        "constant",
        "parameter",
        "type_alias",
        "enum",
        "unknown",
    }
)
SCOPE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "module",
        "namespace",
        "class",
        "interface",
        "function",
        "lambda",
        "block",
        "comprehension",
        "unknown",
    }
)
PARAMETER_KINDS: Final[frozenset[str]] = frozenset(
    {
        "positional_only",
        "positional_or_named",
        "named_only",
        "variadic_positional",
        "variadic_named",
        "receiver",
        "unknown",
    }
)
DEFAULT_KINDS: Final[frozenset[str]] = frozenset(
    {"none", "literal", "expression", "factory", "unknown"}
)
IMPORT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "module",
        "symbol",
        "namespace",
        "side_effect",
        "re_export",
        "dynamic",
        "unknown",
    }
)
REFERENCE_CONTEXTS: Final[frozenset[str]] = frozenset(
    {"read", "write", "delete", "type", "decorator", "base", "export", "call"}
)
CALL_KINDS: Final[frozenset[str]] = frozenset(
    {"direct", "method", "constructor", "super", "dynamic", "unknown"}
)
EFFECT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "filesystem",
        "subprocess",
        "network",
        "environment",
        "import",
        "database",
        "cache",
        "logging",
        "secret",
        "global_state",
        "object_state",
        "io",
        "exception",
        "await",
        "context_manager",
        "unknown",
    }
)
EFFECT_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "read",
        "write",
        "create",
        "delete",
        "mutate",
        "invoke",
        "open",
        "close",
        "raise",
        "await",
        "enter",
        "exit",
        "unknown",
    }
)
DIAGNOSTIC_SEVERITIES: Final[frozenset[str]] = frozenset(
    {"info", "warning", "error", "fatal"}
)


class ASTIRValidationError(ValueError):
    """Raised when a shared AST record is malformed or ambiguous."""


def _text(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
    no_whitespace: bool = False,
    maximum: int = 16_384,
) -> str:
    if type(value) is not str:
        raise ASTIRValidationError(f"{field_name} must be an exact string")
    if not allow_empty and not value:
        raise ASTIRValidationError(f"{field_name} must not be empty")
    if value != value.strip() and value:
        raise ASTIRValidationError(
            f"{field_name} must not contain surrounding whitespace"
        )
    if len(value) > maximum:
        raise ASTIRValidationError(f"{field_name} exceeds {maximum} characters")
    if unicodedata.normalize("NFC", value) != value:
        raise ASTIRValidationError(f"{field_name} must be NFC-normalized")
    if any(not character.isprintable() for character in value):
        raise ASTIRValidationError(f"{field_name} contains a control character")
    if no_whitespace and any(character.isspace() for character in value):
        raise ASTIRValidationError(f"{field_name} must not contain whitespace")
    return value


def _identifier(value: Any, field_name: str) -> str:
    result = _text(value, field_name, no_whitespace=True, maximum=512)
    if not _ID_RE.fullmatch(result):
        raise ASTIRValidationError(f"{field_name} is not a normalized record ID")
    return result


def _optional_identifier(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field_name)


def _integer(
    value: Any,
    field_name: str,
    *,
    minimum: int = 0,
) -> int:
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise ASTIRValidationError(
            f"{field_name} must be an integer in {minimum}..{MAX_SAFE_INTEGER}"
        )
    return value


def _boolean(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise ASTIRValidationError(f"{field_name} must be an exact bool")
    return value


def _choice(value: Any, field_name: str, allowed: frozenset[str]) -> str:
    result = _text(value, field_name, no_whitespace=True, maximum=128)
    if result not in allowed:
        raise ASTIRValidationError(
            f"{field_name} must be one of {sorted(allowed)}, got {result!r}"
        )
    return result


def _path(value: Any, field_name: str) -> str:
    result = _text(value, field_name, no_whitespace=True, maximum=4096)
    if (
        result.startswith("/")
        or "\\" in result
        or "//" in result
        or any(part in {"", ".", ".."} for part in result.split("/"))
    ):
        raise ASTIRValidationError(
            f"{field_name} must be a normalized relative POSIX path"
        )
    return result


T = TypeVar("T")


def _records(
    value: Any,
    expected_type: type[T],
    field_name: str,
    *,
    sort_key: Any | None = None,
) -> tuple[T, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping, set, frozenset)):
        raise ASTIRValidationError(f"{field_name} must be an ordered sequence")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise ASTIRValidationError(
            f"{field_name} must be an ordered sequence"
        ) from exc
    if not all(isinstance(item, expected_type) for item in result):
        raise ASTIRValidationError(
            f"{field_name} may contain only {expected_type.__name__} records"
        )
    return tuple(sorted(result, key=sort_key)) if sort_key else result


def _strings(
    value: Any,
    field_name: str,
    *,
    identifiers: bool = False,
    capabilities: bool = False,
    sorted_set: bool = False,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping, set, frozenset)):
        raise ASTIRValidationError(f"{field_name} must be an ordered sequence")
    try:
        raw = tuple(value)
    except TypeError as exc:
        raise ASTIRValidationError(
            f"{field_name} must be an ordered sequence"
        ) from exc
    result: list[str] = []
    for index, item in enumerate(raw):
        name = f"{field_name}[{index}]"
        if identifiers:
            normalized = _identifier(item, name)
        else:
            normalized = _text(item, name, no_whitespace=True, maximum=512)
        if capabilities and not _CAPABILITY_RE.fullmatch(normalized):
            raise ASTIRValidationError(f"{name} is not a capability token")
        result.append(normalized)
    if len(set(result)) != len(result):
        raise ASTIRValidationError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result)) if sorted_set else tuple(result)


def _span(value: Any, field_name: str) -> "SourceSpan":
    if not isinstance(value, SourceSpan):
        raise ASTIRValidationError(f"{field_name} must be a SourceSpan")
    return value


def _closed_mapping(
    value: Any,
    expected: frozenset[str],
    record_name: str,
) -> dict[str, Any]:
    try:
        validate_structured_value(value)
    except (TypeError, ValueError) as exc:
        raise ASTIRValidationError(
            f"{record_name} must be a strict canonical mapping"
        ) from exc
    if type(value) is not dict:
        raise ASTIRValidationError(f"{record_name} must be an exact mapping")
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ASTIRValidationError(
            f"{record_name} fields are closed (missing={missing}, extra={extra})"
        )
    return value


def _schema(value: Any, expected: SchemaVersion, field_name: str) -> SchemaVersion:
    try:
        result = (
            value
            if isinstance(value, SchemaVersion)
            else SchemaVersion.from_dict(value)
        )
    except (SchemaVersionError, TypeError, ValueError) as exc:
        raise ASTIRValidationError(f"{field_name} is invalid") from exc
    if result != expected:
        raise ASTIRValidationError(
            f"{field_name} must be exactly {expected.identifier}"
        )
    return result


class CanonicalASTRecord:
    """Common content-identity surface for all shared records."""

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstract contract
        raise NotImplementedError

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class SourceProvenance(CanonicalASTRecord):
    """Identity of the exact source blob and repository view parsed."""

    source_cid: str
    path: str
    repository_id: str
    revision: str
    repository_tree_cid: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "source_cid",
            "path",
            "repository_id",
            "revision",
            "repository_tree_cid",
        }
    )

    def __post_init__(self) -> None:
        try:
            source_cid = validate_cid(self.source_cid, codecs={SOURCE_CODEC})
            tree_cid = (
                None
                if self.repository_tree_cid is None
                else validate_cid(self.repository_tree_cid)
            )
        except (TypeError, ValueError) as exc:
            raise ASTIRValidationError("provenance contains an invalid CID") from exc
        object.__setattr__(self, "source_cid", source_cid)
        object.__setattr__(self, "path", _path(self.path, "path"))
        object.__setattr__(
            self, "repository_id", _identifier(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self,
            "revision",
            _text(self.revision, "revision", no_whitespace=True, maximum=512),
        )
        object.__setattr__(self, "repository_tree_cid", tree_cid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_cid": self.source_cid,
            "path": self.path,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "repository_tree_cid": self.repository_tree_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceProvenance":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(**data)


@dataclass(frozen=True, slots=True)
class SourceSpan(CanonicalASTRecord):
    """A half-open UTF-8 byte span with one-based lines and zero-based columns."""

    start_byte: int
    end_byte: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "start_byte",
            "end_byte",
            "start_line",
            "start_column",
            "end_line",
            "end_column",
        }
    )

    def __post_init__(self) -> None:
        for name in ("start_byte", "end_byte", "start_column", "end_column"):
            object.__setattr__(
                self, name, _integer(getattr(self, name), name, minimum=0)
            )
        for name in ("start_line", "end_line"):
            object.__setattr__(
                self, name, _integer(getattr(self, name), name, minimum=1)
            )
        if self.end_byte < self.start_byte:
            raise ASTIRValidationError("span end_byte precedes start_byte")
        if (self.end_line, self.end_column) < (
            self.start_line,
            self.start_column,
        ):
            raise ASTIRValidationError("span end position precedes start position")

    @property
    def sort_key(self) -> tuple[int, int, int]:
        return (self.start_byte, self.end_byte, self.start_line)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceSpan":
        return cls(**_closed_mapping(value, cls._FIELDS, cls.__name__))


@dataclass(frozen=True, slots=True)
class FrontendCapability(CanonicalASTRecord):
    """Pinned frontend identity and the normalized facts it can emit."""

    frontend_name: str
    frontend_version: str
    language: str
    language_version: str
    capabilities: tuple[str, ...]
    source_extensions: tuple[str, ...]
    toolchain_cid: str
    ast_schema: SchemaVersion = AST_IR_SCHEMA_VERSION
    schema_version: SchemaVersion = FRONTEND_CAPABILITY_SCHEMA_VERSION

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "frontend_name",
            "frontend_version",
            "language",
            "language_version",
            "capabilities",
            "source_extensions",
            "toolchain_cid",
            "ast_schema",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "frontend_name",
            _identifier(self.frontend_name, "frontend_name"),
        )
        for name in ("frontend_version", "language", "language_version"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), name, no_whitespace=True, maximum=256),
            )
        object.__setattr__(
            self,
            "capabilities",
            _strings(
                self.capabilities,
                "capabilities",
                capabilities=True,
                sorted_set=True,
            ),
        )
        extensions = _strings(
            self.source_extensions, "source_extensions", sorted_set=True
        )
        if any(not item.startswith(".") or item != item.lower() for item in extensions):
            raise ASTIRValidationError(
                "source_extensions must be lowercase dot-prefixed suffixes"
            )
        object.__setattr__(self, "source_extensions", extensions)
        try:
            toolchain_cid = validate_cid(self.toolchain_cid)
        except (TypeError, ValueError) as exc:
            raise ASTIRValidationError("toolchain_cid is invalid") from exc
        object.__setattr__(self, "toolchain_cid", toolchain_cid)
        object.__setattr__(
            self,
            "ast_schema",
            _schema(self.ast_schema, AST_IR_SCHEMA_VERSION, "ast_schema"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _schema(
                self.schema_version,
                FRONTEND_CAPABILITY_SCHEMA_VERSION,
                "schema_version",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_version.identifier,
            "frontend_name": self.frontend_name,
            "frontend_version": self.frontend_version,
            "language": self.language,
            "language_version": self.language_version,
            "capabilities": list(self.capabilities),
            "source_extensions": list(self.source_extensions),
            "toolchain_cid": self.toolchain_cid,
            "ast_schema": self.ast_schema.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FrontendCapability":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        if data["schema"] != FRONTEND_CAPABILITY_SCHEMA_VERSION.identifier:
            raise ASTIRValidationError("unsupported frontend capability schema")
        return cls(
            frontend_name=data["frontend_name"],
            frontend_version=data["frontend_version"],
            language=data["language"],
            language_version=data["language_version"],
            capabilities=data["capabilities"],
            source_extensions=data["source_extensions"],
            toolchain_cid=data["toolchain_cid"],
            ast_schema=data["ast_schema"],
        )


@dataclass(frozen=True, slots=True)
class ModuleDefinition(CanonicalASTRecord):
    module_id: str
    name: str
    scope_id: str
    span: SourceSpan
    export_names: tuple[str, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"module_id", "name", "scope_id", "span", "export_names"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_id", _identifier(self.module_id, "module_id"))
        object.__setattr__(
            self, "name", _text(self.name, "name", no_whitespace=True, maximum=1024)
        )
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(self, "span", _span(self.span, "span"))
        object.__setattr__(
            self,
            "export_names",
            _strings(self.export_names, "export_names", sorted_set=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "scope_id": self.scope_id,
            "span": self.span.to_dict(),
            "export_names": list(self.export_names),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleDefinition":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            module_id=data["module_id"],
            name=data["name"],
            scope_id=data["scope_id"],
            span=SourceSpan.from_dict(data["span"]),
            export_names=data["export_names"],
        )


@dataclass(frozen=True, slots=True)
class ScopeDefinition(CanonicalASTRecord):
    scope_id: str
    kind: str
    span: SourceSpan
    parent_scope_id: str | None = None
    owner_symbol_id: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"scope_id", "kind", "span", "parent_scope_id", "owner_symbol_id"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(self, "kind", _choice(self.kind, "kind", SCOPE_KINDS))
        object.__setattr__(self, "span", _span(self.span, "span"))
        object.__setattr__(
            self,
            "parent_scope_id",
            _optional_identifier(self.parent_scope_id, "parent_scope_id"),
        )
        object.__setattr__(
            self,
            "owner_symbol_id",
            _optional_identifier(self.owner_symbol_id, "owner_symbol_id"),
        )
        if self.parent_scope_id == self.scope_id:
            raise ASTIRValidationError("scope cannot be its own parent")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "kind": self.kind,
            "span": self.span.to_dict(),
            "parent_scope_id": self.parent_scope_id,
            "owner_symbol_id": self.owner_symbol_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScopeDefinition":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            scope_id=data["scope_id"],
            kind=data["kind"],
            span=SourceSpan.from_dict(data["span"]),
            parent_scope_id=data["parent_scope_id"],
            owner_symbol_id=data["owner_symbol_id"],
        )


@dataclass(frozen=True, slots=True)
class ParameterDefinition(CanonicalASTRecord):
    name: str
    kind: str
    position: int
    annotation: str = ""
    default_kind: str = "none"

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"name", "kind", "position", "annotation", "default_kind"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", _text(self.name, "name", no_whitespace=True, maximum=512)
        )
        object.__setattr__(self, "kind", _choice(self.kind, "kind", PARAMETER_KINDS))
        object.__setattr__(
            self, "position", _integer(self.position, "position", minimum=0)
        )
        object.__setattr__(
            self,
            "annotation",
            _text(self.annotation, "annotation", allow_empty=True, maximum=4096),
        )
        object.__setattr__(
            self,
            "default_kind",
            _choice(self.default_kind, "default_kind", DEFAULT_KINDS),
        )

    @property
    def has_default(self) -> bool:
        return self.default_kind != "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "position": self.position,
            "annotation": self.annotation,
            "default_kind": self.default_kind,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParameterDefinition":
        return cls(**_closed_mapping(value, cls._FIELDS, cls.__name__))


@dataclass(frozen=True, slots=True)
class SignatureDefinition(CanonicalASTRecord):
    parameters: tuple[ParameterDefinition, ...] = ()
    return_annotation: str = ""
    is_async: bool = False
    is_generator: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"parameters", "return_annotation", "is_async", "is_generator"}
    )

    def __post_init__(self) -> None:
        parameters = _records(
            self.parameters,
            ParameterDefinition,
            "parameters",
            sort_key=lambda item: item.position,
        )
        positions = [item.position for item in parameters]
        if positions != list(range(len(parameters))):
            raise ASTIRValidationError(
                "parameter positions must be unique and contiguous from zero"
            )
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(
            self,
            "return_annotation",
            _text(
                self.return_annotation,
                "return_annotation",
                allow_empty=True,
                maximum=4096,
            ),
        )
        object.__setattr__(self, "is_async", _boolean(self.is_async, "is_async"))
        object.__setattr__(
            self, "is_generator", _boolean(self.is_generator, "is_generator")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameters": [item.to_dict() for item in self.parameters],
            "return_annotation": self.return_annotation,
            "is_async": self.is_async,
            "is_generator": self.is_generator,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignatureDefinition":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            parameters=[
                ParameterDefinition.from_dict(item) for item in data["parameters"]
            ],
            return_annotation=data["return_annotation"],
            is_async=data["is_async"],
            is_generator=data["is_generator"],
        )


@dataclass(frozen=True, slots=True)
class SymbolDefinition(CanonicalASTRecord):
    symbol_id: str
    name: str
    qualified_name: str
    kind: str
    scope_id: str
    span: SourceSpan
    definition_ordinal: int = 0
    signature: SignatureDefinition | None = None
    visibility: str = "unspecified"
    decorator_names: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "symbol_id",
            "name",
            "qualified_name",
            "kind",
            "scope_id",
            "span",
            "definition_ordinal",
            "signature",
            "visibility",
            "decorator_names",
            "flags",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_id", _identifier(self.symbol_id, "symbol_id"))
        for name in ("name", "qualified_name"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), name, no_whitespace=True, maximum=2048),
            )
        object.__setattr__(self, "kind", _choice(self.kind, "kind", SYMBOL_KINDS))
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(self, "span", _span(self.span, "span"))
        object.__setattr__(
            self,
            "definition_ordinal",
            _integer(self.definition_ordinal, "definition_ordinal", minimum=0),
        )
        if self.signature is not None and not isinstance(
            self.signature, SignatureDefinition
        ):
            raise ASTIRValidationError("signature must be a SignatureDefinition")
        object.__setattr__(
            self,
            "visibility",
            _choice(
                self.visibility,
                "visibility",
                frozenset({"public", "protected", "private", "unspecified"}),
            ),
        )
        object.__setattr__(
            self,
            "decorator_names",
            _strings(self.decorator_names, "decorator_names"),
        )
        object.__setattr__(
            self,
            "flags",
            _strings(
                self.flags, "flags", capabilities=True, sorted_set=True
            ),
        )
        callable_kinds = {"function", "method", "constructor"}
        if self.signature is not None and self.kind not in callable_kinds:
            raise ASTIRValidationError(
                "only callable symbol kinds may carry a signature"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "scope_id": self.scope_id,
            "span": self.span.to_dict(),
            "definition_ordinal": self.definition_ordinal,
            "signature": None if self.signature is None else self.signature.to_dict(),
            "visibility": self.visibility,
            "decorator_names": list(self.decorator_names),
            "flags": list(self.flags),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SymbolDefinition":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            symbol_id=data["symbol_id"],
            name=data["name"],
            qualified_name=data["qualified_name"],
            kind=data["kind"],
            scope_id=data["scope_id"],
            span=SourceSpan.from_dict(data["span"]),
            definition_ordinal=data["definition_ordinal"],
            signature=(
                None
                if data["signature"] is None
                else SignatureDefinition.from_dict(data["signature"])
            ),
            visibility=data["visibility"],
            decorator_names=data["decorator_names"],
            flags=data["flags"],
        )


@dataclass(frozen=True, slots=True)
class ImportDefinition(CanonicalASTRecord):
    import_id: str
    scope_id: str
    module: str
    kind: str
    span: SourceSpan
    imported_name: str | None = None
    local_name: str | None = None
    is_type_only: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "import_id",
            "scope_id",
            "module",
            "kind",
            "span",
            "imported_name",
            "local_name",
            "is_type_only",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "import_id", _identifier(self.import_id, "import_id"))
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(
            self,
            "module",
            _text(self.module, "module", no_whitespace=True, maximum=2048),
        )
        object.__setattr__(self, "kind", _choice(self.kind, "kind", IMPORT_KINDS))
        object.__setattr__(self, "span", _span(self.span, "span"))
        for name in ("imported_name", "local_name"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _text(value, name, no_whitespace=True, maximum=1024),
                )
        object.__setattr__(
            self, "is_type_only", _boolean(self.is_type_only, "is_type_only")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "scope_id": self.scope_id,
            "module": self.module,
            "kind": self.kind,
            "span": self.span.to_dict(),
            "imported_name": self.imported_name,
            "local_name": self.local_name,
            "is_type_only": self.is_type_only,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImportDefinition":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            import_id=data["import_id"],
            scope_id=data["scope_id"],
            module=data["module"],
            kind=data["kind"],
            span=SourceSpan.from_dict(data["span"]),
            imported_name=data["imported_name"],
            local_name=data["local_name"],
            is_type_only=data["is_type_only"],
        )


@dataclass(frozen=True, slots=True)
class ReferenceRecord(CanonicalASTRecord):
    """One unresolved lexical reference."""

    reference_id: str
    name: str
    scope_id: str
    context: str
    span: SourceSpan
    is_qualified: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"reference_id", "name", "scope_id", "context", "span", "is_qualified"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reference_id", _identifier(self.reference_id, "reference_id")
        )
        object.__setattr__(
            self, "name", _text(self.name, "name", no_whitespace=True, maximum=2048)
        )
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(
            self,
            "context",
            _choice(self.context, "context", REFERENCE_CONTEXTS),
        )
        object.__setattr__(self, "span", _span(self.span, "span"))
        object.__setattr__(
            self, "is_qualified", _boolean(self.is_qualified, "is_qualified")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "name": self.name,
            "scope_id": self.scope_id,
            "context": self.context,
            "span": self.span.to_dict(),
            "is_qualified": self.is_qualified,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReferenceRecord":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            reference_id=data["reference_id"],
            name=data["name"],
            scope_id=data["scope_id"],
            context=data["context"],
            span=SourceSpan.from_dict(data["span"]),
            is_qualified=data["is_qualified"],
        )


@dataclass(frozen=True, slots=True)
class CallRecord(CanonicalASTRecord):
    """One unresolved lexical call site."""

    call_id: str
    scope_id: str
    callee_name: str
    kind: str
    argument_count: int
    span: SourceSpan
    callee_reference_id: str | None = None
    named_argument_names: tuple[str, ...] = ()
    is_awaited: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "call_id",
            "scope_id",
            "callee_name",
            "kind",
            "argument_count",
            "span",
            "callee_reference_id",
            "named_argument_names",
            "is_awaited",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_id", _identifier(self.call_id, "call_id"))
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(
            self,
            "callee_name",
            _text(
                self.callee_name,
                "callee_name",
                no_whitespace=True,
                maximum=2048,
            ),
        )
        object.__setattr__(self, "kind", _choice(self.kind, "kind", CALL_KINDS))
        object.__setattr__(
            self,
            "argument_count",
            _integer(self.argument_count, "argument_count", minimum=0),
        )
        object.__setattr__(self, "span", _span(self.span, "span"))
        object.__setattr__(
            self,
            "callee_reference_id",
            _optional_identifier(
                self.callee_reference_id, "callee_reference_id"
            ),
        )
        object.__setattr__(
            self,
            "named_argument_names",
            _strings(self.named_argument_names, "named_argument_names"),
        )
        object.__setattr__(
            self, "is_awaited", _boolean(self.is_awaited, "is_awaited")
        )
        if len(self.named_argument_names) > self.argument_count:
            raise ASTIRValidationError(
                "named_argument_names cannot exceed argument_count"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "scope_id": self.scope_id,
            "callee_name": self.callee_name,
            "kind": self.kind,
            "argument_count": self.argument_count,
            "span": self.span.to_dict(),
            "callee_reference_id": self.callee_reference_id,
            "named_argument_names": list(self.named_argument_names),
            "is_awaited": self.is_awaited,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CallRecord":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            call_id=data["call_id"],
            scope_id=data["scope_id"],
            callee_name=data["callee_name"],
            kind=data["kind"],
            argument_count=data["argument_count"],
            span=SourceSpan.from_dict(data["span"]),
            callee_reference_id=data["callee_reference_id"],
            named_argument_names=data["named_argument_names"],
            is_awaited=data["is_awaited"],
        )


@dataclass(frozen=True, slots=True)
class EffectRecord(CanonicalASTRecord):
    effect_id: str
    scope_id: str
    kind: str
    operation: str
    span: SourceSpan
    subject: str = ""

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"effect_id", "scope_id", "kind", "operation", "span", "subject"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _identifier(self.effect_id, "effect_id"))
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        object.__setattr__(self, "kind", _choice(self.kind, "kind", EFFECT_KINDS))
        object.__setattr__(
            self,
            "operation",
            _choice(self.operation, "operation", EFFECT_OPERATIONS),
        )
        object.__setattr__(self, "span", _span(self.span, "span"))
        object.__setattr__(
            self,
            "subject",
            _text(self.subject, "subject", allow_empty=True, maximum=2048),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "scope_id": self.scope_id,
            "kind": self.kind,
            "operation": self.operation,
            "span": self.span.to_dict(),
            "subject": self.subject,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EffectRecord":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            effect_id=data["effect_id"],
            scope_id=data["scope_id"],
            kind=data["kind"],
            operation=data["operation"],
            span=SourceSpan.from_dict(data["span"]),
            subject=data["subject"],
        )


@dataclass(frozen=True, slots=True)
class DiagnosticRecord(CanonicalASTRecord):
    code: str
    severity: str
    message: str
    span: SourceSpan | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"code", "severity", "message", "span"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _text(self.code, "code", no_whitespace=True, maximum=256)
        )
        object.__setattr__(
            self,
            "severity",
            _choice(self.severity, "severity", DIAGNOSTIC_SEVERITIES),
        )
        object.__setattr__(
            self, "message", _text(self.message, "message", maximum=16_384)
        )
        if self.span is not None:
            object.__setattr__(self, "span", _span(self.span, "span"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "span": None if self.span is None else self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiagnosticRecord":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            code=data["code"],
            severity=data["severity"],
            message=data["message"],
            span=None if data["span"] is None else SourceSpan.from_dict(data["span"]),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedConstruct(CanonicalASTRecord):
    unsupported_id: str
    code: str
    construct: str
    reason: str
    span: SourceSpan

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"unsupported_id", "code", "construct", "reason", "span"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "unsupported_id",
            _identifier(self.unsupported_id, "unsupported_id"),
        )
        object.__setattr__(
            self, "code", _text(self.code, "code", no_whitespace=True, maximum=256)
        )
        object.__setattr__(
            self,
            "construct",
            _text(self.construct, "construct", no_whitespace=True, maximum=512),
        )
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", maximum=4096)
        )
        object.__setattr__(self, "span", _span(self.span, "span"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "unsupported_id": self.unsupported_id,
            "code": self.code,
            "construct": self.construct,
            "reason": self.reason,
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsupportedConstruct":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        return cls(
            unsupported_id=data["unsupported_id"],
            code=data["code"],
            construct=data["construct"],
            reason=data["reason"],
            span=SourceSpan.from_dict(data["span"]),
        )


def _source_order(item: Any) -> tuple[int, int, str]:
    identity = next(
        (
            getattr(item, name)
            for name in (
                "scope_id",
                "symbol_id",
                "import_id",
                "reference_id",
                "call_id",
                "effect_id",
                "unsupported_id",
                "code",
            )
            if hasattr(item, name)
        ),
        "",
    )
    span = item.span
    if span is None:
        return (MAX_SAFE_INTEGER, MAX_SAFE_INTEGER, identity)
    return (span.start_byte, span.end_byte, identity)


@dataclass(frozen=True, slots=True)
class ASTRecord(CanonicalASTRecord):
    """One normalized, content-addressed source-blob parsing result."""

    provenance: SourceProvenance
    frontend: FrontendCapability
    module: ModuleDefinition
    scopes: tuple[ScopeDefinition, ...]
    symbols: tuple[SymbolDefinition, ...] = ()
    imports: tuple[ImportDefinition, ...] = ()
    references: tuple[ReferenceRecord, ...] = ()
    calls: tuple[CallRecord, ...] = ()
    effects: tuple[EffectRecord, ...] = ()
    diagnostics: tuple[DiagnosticRecord, ...] = ()
    unsupported: tuple[UnsupportedConstruct, ...] = ()
    schema_version: SchemaVersion = AST_IR_SCHEMA_VERSION

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "provenance",
            "frontend",
            "module",
            "scopes",
            "symbols",
            "imports",
            "references",
            "calls",
            "effects",
            "diagnostics",
            "unsupported",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, SourceProvenance):
            raise ASTIRValidationError("provenance must be SourceProvenance")
        if not isinstance(self.frontend, FrontendCapability):
            raise ASTIRValidationError("frontend must be FrontendCapability")
        if not isinstance(self.module, ModuleDefinition):
            raise ASTIRValidationError("module must be ModuleDefinition")
        object.__setattr__(
            self,
            "schema_version",
            _schema(self.schema_version, AST_IR_SCHEMA_VERSION, "schema_version"),
        )
        if self.frontend.ast_schema != self.schema_version:
            raise ASTIRValidationError("frontend ast_schema does not match AST schema")

        definitions = (
            ("scopes", ScopeDefinition),
            ("symbols", SymbolDefinition),
            ("imports", ImportDefinition),
            ("references", ReferenceRecord),
            ("calls", CallRecord),
            ("effects", EffectRecord),
            ("diagnostics", DiagnosticRecord),
            ("unsupported", UnsupportedConstruct),
        )
        for name, record_type in definitions:
            object.__setattr__(
                self,
                name,
                _records(
                    getattr(self, name),
                    record_type,
                    name,
                    sort_key=_source_order,
                ),
            )

        scope_ids = self._unique_ids(self.scopes, "scope_id")
        symbol_ids = self._unique_ids(self.symbols, "symbol_id")
        self._unique_ids(self.imports, "import_id")
        reference_ids = self._unique_ids(self.references, "reference_id")
        self._unique_ids(self.calls, "call_id")
        self._unique_ids(self.effects, "effect_id")
        self._unique_ids(self.unsupported, "unsupported_id")

        if self.module.scope_id not in scope_ids:
            raise ASTIRValidationError("module scope_id does not name a scope")
        roots = [item for item in self.scopes if item.parent_scope_id is None]
        if len(roots) != 1 or roots[0].scope_id != self.module.scope_id:
            raise ASTIRValidationError(
                "AST must have exactly one root scope matching module.scope_id"
            )
        parent_by_scope = {
            item.scope_id: item.parent_scope_id for item in self.scopes
        }
        for item in self.scopes:
            if (
                item.parent_scope_id is not None
                and item.parent_scope_id not in scope_ids
            ):
                raise ASTIRValidationError(
                    f"scope {item.scope_id} has unknown parent_scope_id"
                )
            if (
                item.owner_symbol_id is not None
                and item.owner_symbol_id not in symbol_ids
            ):
                raise ASTIRValidationError(
                    f"scope {item.scope_id} has unknown owner_symbol_id"
                )
            seen: set[str] = set()
            current: str | None = item.scope_id
            while current is not None:
                if current in seen:
                    raise ASTIRValidationError("scope parent graph contains a cycle")
                seen.add(current)
                current = parent_by_scope[current]

        for collection_name in (
            "symbols",
            "imports",
            "references",
            "calls",
            "effects",
        ):
            for item in getattr(self, collection_name):
                if item.scope_id not in scope_ids:
                    raise ASTIRValidationError(
                        f"{collection_name} record names an unknown scope_id"
                    )
        for call in self.calls:
            if (
                call.callee_reference_id is not None
                and call.callee_reference_id not in reference_ids
            ):
                raise ASTIRValidationError(
                    f"call {call.call_id} names an unknown callee_reference_id"
                )

    @staticmethod
    def _unique_ids(records: Sequence[Any], field_name: str) -> frozenset[str]:
        values = [getattr(item, field_name) for item in records]
        if len(set(values)) != len(values):
            raise ASTIRValidationError(f"duplicate {field_name} in AST")
        return frozenset(values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_version.identifier,
            "provenance": self.provenance.to_dict(),
            "frontend": self.frontend.to_dict(),
            "module": self.module.to_dict(),
            "scopes": [item.to_dict() for item in self.scopes],
            "symbols": [item.to_dict() for item in self.symbols],
            "imports": [item.to_dict() for item in self.imports],
            "references": [item.to_dict() for item in self.references],
            "calls": [item.to_dict() for item in self.calls],
            "effects": [item.to_dict() for item in self.effects],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "unsupported": [item.to_dict() for item in self.unsupported],
        }

    def to_json(self) -> str:
        return self.canonical_bytes.decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ASTRecord":
        data = _closed_mapping(value, cls._FIELDS, cls.__name__)
        if data["schema"] != AST_IR_SCHEMA_VERSION.identifier:
            raise ASTIRValidationError("unsupported AST IR schema")
        return cls(
            provenance=SourceProvenance.from_dict(data["provenance"]),
            frontend=FrontendCapability.from_dict(data["frontend"]),
            module=ModuleDefinition.from_dict(data["module"]),
            scopes=[ScopeDefinition.from_dict(item) for item in data["scopes"]],
            symbols=[SymbolDefinition.from_dict(item) for item in data["symbols"]],
            imports=[ImportDefinition.from_dict(item) for item in data["imports"]],
            references=[
                ReferenceRecord.from_dict(item) for item in data["references"]
            ],
            calls=[CallRecord.from_dict(item) for item in data["calls"]],
            effects=[EffectRecord.from_dict(item) for item in data["effects"]],
            diagnostics=[
                DiagnosticRecord.from_dict(item) for item in data["diagnostics"]
            ],
            unsupported=[
                UnsupportedConstruct.from_dict(item) for item in data["unsupported"]
            ],
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> "ASTRecord":
        if type(value) not in {str, bytes}:
            raise ASTIRValidationError("AST JSON must be exact str or bytes")

        def object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    raise ASTIRValidationError(f"duplicate JSON key: {key}")
                result[key] = item
            return result

        def reject_float(raw: str) -> Any:
            raise ASTIRValidationError(f"AST JSON rejects float value {raw}")

        try:
            decoded = json.loads(
                value,
                object_pairs_hook=object_hook,
                parse_float=reject_float,
                parse_constant=reject_float,
            )
        except ASTIRValidationError:
            raise
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ASTIRValidationError("invalid AST JSON") from exc
        return cls.from_dict(decoded)

    def verify_cid(self, claimed_cid: str) -> str:
        """Decode and recompute an AST CID on a read path."""

        return decode_and_recompute_structured(claimed_cid, self.to_dict())


# Compatibility nouns for downstream frontends.  They are aliases, not
# independent schemas, so shared serialization has exactly one owner.
Signature = SignatureDefinition
SymbolReference = ReferenceRecord
CallSite = CallRecord
Effect = EffectRecord
Diagnostic = DiagnosticRecord


def ast_ir_schema_descriptor() -> dict[str, Any]:
    """Return a deterministic machine-readable statement of the shared boundary."""

    return {
        "schema": AST_IR_DESCRIPTOR_SCHEMA,
        "owner_goal": "DSCON-G105",
        "ast_schema": AST_IR_SCHEMA_VERSION.to_dict(),
        "frontend_schema": FRONTEND_CAPABILITY_SCHEMA_VERSION.to_dict(),
        "records": [
            "ASTRecord",
            "CallRecord",
            "DiagnosticRecord",
            "EffectRecord",
            "FrontendCapability",
            "ImportDefinition",
            "ModuleDefinition",
            "ParameterDefinition",
            "ReferenceRecord",
            "ScopeDefinition",
            "SignatureDefinition",
            "SourceProvenance",
            "SourceSpan",
            "SymbolDefinition",
            "UnsupportedConstruct",
        ],
        "identity_profile": "software-contract-cid-profile-v1",
        "span_convention": {
            "byte_interval": "half-open",
            "byte_encoding": "utf-8",
            "line_base": 1,
            "column_base": 0,
        },
        "guarantees": {
            "immutable": True,
            "closed_records": True,
            "canonical_values_only": True,
            "language_specific_payloads": False,
            "parser_resolution_separated": True,
            "resolved_targets_in_ast": False,
            "unsupported_constructs_explicit": True,
        },
    }


__all__ = [
    "ASTIRValidationError",
    "ASTRecord",
    "AST_IR_DESCRIPTOR_SCHEMA",
    "CALL_KINDS",
    "CallRecord",
    "CallSite",
    "CanonicalASTRecord",
    "DEFAULT_KINDS",
    "DIAGNOSTIC_SEVERITIES",
    "Diagnostic",
    "DiagnosticRecord",
    "EFFECT_KINDS",
    "EFFECT_OPERATIONS",
    "Effect",
    "EffectRecord",
    "FrontendCapability",
    "IMPORT_KINDS",
    "ImportDefinition",
    "MAX_SAFE_INTEGER",
    "ModuleDefinition",
    "PARAMETER_KINDS",
    "ParameterDefinition",
    "REFERENCE_CONTEXTS",
    "ReferenceRecord",
    "SCOPE_KINDS",
    "SYMBOL_KINDS",
    "ScopeDefinition",
    "Signature",
    "SignatureDefinition",
    "SourceProvenance",
    "SourceSpan",
    "SymbolDefinition",
    "SymbolReference",
    "UnsupportedConstruct",
    "ast_ir_schema_descriptor",
]
