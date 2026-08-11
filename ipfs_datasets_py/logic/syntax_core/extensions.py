"""Schema-governed logic extension nodes and registry.

Interfaces (LFP2-006):

* ``ExtensionSchemaRegistry@1`` — fail-closed registration of versioned
  extension payload schemas with binder/scope/sort hooks, codecs,
  substitution/normalization/semantic-hash behavior, and explicit unsupported
  diagnostics

Unknown or malformed extension payloads never silently cross elaboration or
codec boundaries.  Registered nodes participate in algebra, elaboration,
codecs, and semantic hashing through the hooks declared on each descriptor.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    AstError,
    Binder,
    ExprCategory,
    LogicExtensionNode,
    LogicNode,
    NodeKind,
    _payload_schema,
    mk_extension,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    MAX_DIAGNOSTICS,
    DiagnosticSeverity,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
    require_namespace_identity,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSort,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

EXTENSION_SCHEMA_REGISTRY_INTERFACE: Final = "ExtensionSchemaRegistry@1"
EXTENSION_SCHEMA_DESCRIPTOR_INTERFACE: Final = "ExtensionSchemaDescriptor@1"
EXTENSION_SCHEMA_REGISTRY_SCHEMA_VERSION: Final = "syntax-extension-schema-registry/v1"
EXTENSION_SCHEMA_DESCRIPTOR_SCHEMA_VERSION: Final = (
    "syntax-extension-schema-descriptor/v1"
)
EXTENSIONS_MODULE_VERSION: Final = "1.0.0"

# Stable diagnostic codes (namespaced).
CODE_UNKNOWN_EXTENSION_SCHEMA: Final = "extension.unknown_schema"
CODE_MALFORMED_EXTENSION_PAYLOAD: Final = "extension.malformed_payload"
CODE_UNSUPPORTED_EXTENSION: Final = "extension.unsupported"
CODE_EXTENSION_CHILD_ARITY: Final = "extension.child_arity"
CODE_EXTENSION_BINDER_ARITY: Final = "extension.binder_arity"
CODE_EXTENSION_FEATURE_MISMATCH: Final = "extension.feature_mismatch"
CODE_EXTENSION_IDENTITY_MISMATCH: Final = "extension.identity_mismatch"
CODE_EXTENSION_SORT_MISMATCH: Final = "extension.sort_mismatch"
CODE_EXTENSION_DUPLICATE: Final = "extension.duplicate_schema"
CODE_EXTENSION_REQUIRED_KEY: Final = "extension.required_key"

_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_POSITION_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


class ExtensionError(SyntaxContractError):
    """Raised when extension schema registration or validation fails closed."""


class UnknownExtensionSchemaError(ExtensionError):
    """Raised when a payload schema is not registered."""


class MalformedExtensionPayloadError(ExtensionError):
    """Raised when a payload does not match its declared schema."""


class UnsupportedExtensionError(ExtensionError):
    """Raised when a consumer lacks a required extension schema."""


class DuplicateExtensionSchemaError(ExtensionError):
    """Raised when the same payload schema is registered twice."""


class ExtensionUnsupportedBehavior(str, Enum):
    """Explicit behavior when a consumer lacks the extension."""

    REJECT = "reject"
    DIAGNOSTIC = "diagnostic"


class ExtensionPositionKind(str, Enum):
    """Whether a declared position holds a child node or a binder."""

    CHILD = "child"
    BINDER = "binder"


# ---------------------------------------------------------------------------
# Position descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtensionPosition:
    """Named child-node or binder slot on an extension payload schema."""

    name: str
    kind: ExtensionPositionKind | str
    required: bool = True
    category: ExprCategory | str | None = None
    sort: LogicSort | None = None
    description: str = ""

    def __post_init__(self) -> None:
        name = _text(self.name, "ExtensionPosition.name", maximum=128)
        if not _POSITION_RE.fullmatch(name):
            raise ExtensionError(
                f"ExtensionPosition.name must be a lowercase position id; got {name!r}"
            )
        object.__setattr__(self, "name", name)
        if isinstance(self.kind, ExtensionPositionKind):
            kind = self.kind
        else:
            try:
                kind = ExtensionPositionKind(
                    _text(self.kind, "kind", maximum=32)
                )
            except ValueError as error:
                raise ExtensionError(
                    f"kind must be a ExtensionPositionKind; got {self.kind!r}"
                ) from error
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.required, bool):
            raise ExtensionError("ExtensionPosition.required must be a bool")
        category = self.category
        if category is not None:
            if isinstance(category, ExprCategory):
                pass
            else:
                try:
                    category = ExprCategory(
                        _text(category, "category", maximum=32)
                    )
                except ValueError as error:
                    raise ExtensionError(
                        f"category must be an ExprCategory; got {self.category!r}"
                    ) from error
            object.__setattr__(self, "category", category)
        if self.sort is not None and not isinstance(self.sort, LogicSort):
            object.__setattr__(
                self,
                "sort",
                LogicSort.from_dict(_require_mapping(self.sort, "sort")),
            )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", maximum=512, allow_empty=True)
            if self.description
            else "",
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value
            if isinstance(self.kind, ExtensionPositionKind)
            else self.kind,
            "name": self.name,
            "required": self.required,
        }
        if self.category is not None:
            payload["category"] = (
                self.category.value
                if isinstance(self.category, ExprCategory)
                else self.category
            )
        if self.sort is not None:
            payload["sort"] = self.sort.to_dict()
        if self.description:
            payload["description"] = self.description
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExtensionPosition":
        payload = _require_mapping(data, "ExtensionPosition")
        sort_payload = payload.get("sort")
        return cls(
            name=str(payload.get("name") or ""),
            kind=str(payload.get("kind") or ""),
            required=bool(payload.get("required", True)),
            category=payload.get("category"),
            sort=(
                None
                if sort_payload is None
                else LogicSort.from_dict(_require_mapping(sort_payload, "sort"))
            ),
            description=str(payload.get("description") or ""),
        )


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


def _feature_id(value: object, field_name: str = "feature") -> str:
    result = _text(value, field_name, maximum=128)
    if not _FEATURE_RE.fullmatch(result):
        raise ExtensionError(
            f"{field_name} must be a lowercase feature id; got {result!r}"
        )
    return result


def _features(value: object, field_name: str = "features") -> tuple[str, ...]:
    items = tuple(
        _feature_id(item, f"{field_name} item")
        for item in _require_sequence(value if value is not None else (), field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ExtensionError(f"{field_name} exceeds collection ceiling")
    if len(items) != len(set(items)):
        raise ExtensionError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items))


def _required_keys(value: object, field_name: str = "required_keys") -> tuple[str, ...]:
    items = tuple(
        _text(item, f"{field_name} item", maximum=64)
        for item in _require_sequence(value if value is not None else (), field_name)
    )
    for item in items:
        if not _KEY_RE.fullmatch(item):
            raise ExtensionError(
                f"{field_name} item must be a simple key; got {item!r}"
            )
    if len(items) != len(set(items)):
        raise ExtensionError(f"{field_name} must not contain duplicates")
    return items


PayloadValidator = Callable[[Mapping[str, Any]], None]
PayloadCodec = Callable[[Mapping[str, Any]], Mapping[str, Any]]
SemanticHashHook = Callable[[LogicExtensionNode], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ExtensionSchemaDescriptor:
    """Immutable registration record for one versioned extension schema.

    Interface: ``ExtensionSchemaDescriptor@1``.

    Every descriptor declares:

    * a versioned ``payload_schema`` id (``family.construct/vN``)
    * family/profile/features identity
    * child-node and binder positions
    * result sort/category
    * required payload keys and optional structural validators
    * translation feature requirements
    * explicit unsupported behavior when a consumer lacks the schema
    * optional codec, free/bound, substitution, normalization, and semantic-hash
      hooks (defaults preserve structured payload identity)
    """

    schema_id: str
    payload_schema: str
    family: LogicIdentity | Mapping[str, Any] | str
    profile: LogicIdentity | Mapping[str, Any] | str
    features: tuple[str, ...]
    child_positions: tuple[ExtensionPosition, ...] = ()
    binder_positions: tuple[ExtensionPosition, ...] = ()
    result_category: ExprCategory | str = ExprCategory.FORMULA
    result_sort: LogicSort | None = None
    required_keys: tuple[str, ...] = ()
    translation_features: tuple[str, ...] = ()
    unsupported_behavior: ExtensionUnsupportedBehavior | str = (
        ExtensionUnsupportedBehavior.REJECT
    )
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EXTENSION_SCHEMA_DESCRIPTOR_SCHEMA_VERSION
    # Runtime hooks (not serialized).
    payload_validator: PayloadValidator | None = field(default=None, repr=False)
    payload_encoder: PayloadCodec | None = field(default=None, repr=False)
    payload_decoder: PayloadCodec | None = field(default=None, repr=False)
    semantic_hash_hook: SemanticHashHook | None = field(default=None, repr=False)

    interface: ClassVar[str] = EXTENSION_SCHEMA_DESCRIPTOR_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_id", _record_id(self.schema_id, "schema_id")
        )
        object.__setattr__(
            self, "payload_schema", _payload_schema(self.payload_schema)
        )
        object.__setattr__(
            self,
            "family",
            require_namespace_identity(self.family, NamespaceKind.FAMILY, "family"),
        )
        object.__setattr__(
            self,
            "profile",
            require_namespace_identity(
                self.profile, NamespaceKind.PROFILE, "profile"
            ),
        )
        features = _features(self.features, "features")
        if not features:
            raise ExtensionError(
                "ExtensionSchemaDescriptor.features must be non-empty"
            )
        object.__setattr__(self, "features", features)

        child_positions = tuple(
            item
            if isinstance(item, ExtensionPosition)
            else ExtensionPosition.from_dict(
                _require_mapping(item, "child_positions item")
            )
            for item in _require_sequence(self.child_positions, "child_positions")
        )
        for position in child_positions:
            if position.kind is not ExtensionPositionKind.CHILD:
                raise ExtensionError(
                    f"child position {position.name!r} must have kind 'child'"
                )
        binder_positions = tuple(
            item
            if isinstance(item, ExtensionPosition)
            else ExtensionPosition.from_dict(
                _require_mapping(item, "binder_positions item")
            )
            for item in _require_sequence(
                self.binder_positions, "binder_positions"
            )
        )
        for position in binder_positions:
            if position.kind is not ExtensionPositionKind.BINDER:
                raise ExtensionError(
                    f"binder position {position.name!r} must have kind 'binder'"
                )
        child_names = [item.name for item in child_positions]
        binder_names = [item.name for item in binder_positions]
        if len(child_names) != len(set(child_names)):
            raise ExtensionError("child_positions names must be unique")
        if len(binder_names) != len(set(binder_names)):
            raise ExtensionError("binder_positions names must be unique")
        object.__setattr__(self, "child_positions", child_positions)
        object.__setattr__(self, "binder_positions", binder_positions)

        if isinstance(self.result_category, ExprCategory):
            category = self.result_category
        else:
            try:
                category = ExprCategory(
                    _text(self.result_category, "result_category", maximum=32)
                )
            except ValueError as error:
                raise ExtensionError(
                    f"result_category must be an ExprCategory; "
                    f"got {self.result_category!r}"
                ) from error
        object.__setattr__(self, "result_category", category)

        if self.result_sort is not None and not isinstance(
            self.result_sort, LogicSort
        ):
            object.__setattr__(
                self,
                "result_sort",
                LogicSort.from_dict(
                    _require_mapping(self.result_sort, "result_sort")
                ),
            )
        if category is ExprCategory.FORMULA:
            object.__setattr__(self, "result_sort", BOOL_SORT)
        elif self.result_sort is None:
            raise ExtensionError(
                "term extension descriptors require result_sort"
            )
        elif self.result_sort.is_bool:
            raise ExtensionError(
                "term extension result_sort must not be Bool"
            )

        object.__setattr__(
            self, "required_keys", _required_keys(self.required_keys)
        )
        object.__setattr__(
            self,
            "translation_features",
            _features(self.translation_features, "translation_features"),
        )

        if isinstance(self.unsupported_behavior, ExtensionUnsupportedBehavior):
            behavior = self.unsupported_behavior
        else:
            try:
                behavior = ExtensionUnsupportedBehavior(
                    _text(
                        self.unsupported_behavior,
                        "unsupported_behavior",
                        maximum=32,
                    )
                )
            except ValueError as error:
                raise ExtensionError(
                    f"unsupported_behavior must be an "
                    f"ExtensionUnsupportedBehavior; got "
                    f"{self.unsupported_behavior!r}"
                ) from error
        object.__setattr__(self, "unsupported_behavior", behavior)

        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", maximum=1024, allow_empty=True)
            if self.description
            else "",
        )
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != EXTENSION_SCHEMA_DESCRIPTOR_SCHEMA_VERSION:
            raise ExtensionError(
                f"unsupported ExtensionSchemaDescriptor schema_version "
                f"{self.schema_version!r}"
            )
        if self.payload_validator is not None and not callable(
            self.payload_validator
        ):
            raise ExtensionError("payload_validator must be callable or None")
        if self.payload_encoder is not None and not callable(self.payload_encoder):
            raise ExtensionError("payload_encoder must be callable or None")
        if self.payload_decoder is not None and not callable(self.payload_decoder):
            raise ExtensionError("payload_decoder must be callable or None")
        if self.semantic_hash_hook is not None and not callable(
            self.semantic_hash_hook
        ):
            raise ExtensionError("semantic_hash_hook must be callable or None")

    @property
    def min_children(self) -> int:
        return sum(1 for item in self.child_positions if item.required)

    @property
    def max_children(self) -> int:
        return len(self.child_positions)

    @property
    def min_binders(self) -> int:
        return sum(1 for item in self.binder_positions if item.required)

    @property
    def max_binders(self) -> int:
        return len(self.binder_positions)

    def encode_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Canonicalize *payload* for codecs (identity when no encoder)."""

        raw = _thaw_mapping(_freeze_mapping(payload, "payload"))
        if self.payload_encoder is not None:
            encoded = self.payload_encoder(raw)
            return _thaw_mapping(_freeze_mapping(encoded, "encoded payload"))
        return raw

    def decode_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Decode a wire payload (identity when no decoder)."""

        raw = _thaw_mapping(_freeze_mapping(payload, "payload"))
        if self.payload_decoder is not None:
            decoded = self.payload_decoder(raw)
            return _thaw_mapping(_freeze_mapping(decoded, "decoded payload"))
        return raw

    def semantic_payload(self, extension: LogicExtensionNode) -> dict[str, Any]:
        """Return the semantic-hash contribution for *extension*."""

        if self.semantic_hash_hook is not None:
            contrib = self.semantic_hash_hook(extension)
            return _thaw_mapping(
                _freeze_mapping(contrib, "semantic_hash contribution")
            )
        return {
            "features": list(extension.features),
            "payload": self.encode_payload(_thaw_mapping(extension.payload)),
            "payload_schema": extension.payload_schema,
        }

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "binder_positions": [item.to_dict() for item in self.binder_positions],
            "child_positions": [item.to_dict() for item in self.child_positions],
            "description": self.description,
            "family": self.family.to_dict()
            if isinstance(self.family, LogicIdentity)
            else self.family,
            "features": list(self.features),
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "payload_schema": self.payload_schema,
            "profile": self.profile.to_dict()
            if isinstance(self.profile, LogicIdentity)
            else self.profile,
            "required_keys": list(self.required_keys),
            "result_category": self.result_category.value
            if isinstance(self.result_category, ExprCategory)
            else self.result_category,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "translation_features": list(self.translation_features),
            "unsupported_behavior": self.unsupported_behavior.value
            if isinstance(self.unsupported_behavior, ExtensionUnsupportedBehavior)
            else self.unsupported_behavior,
        }
        if self.result_sort is not None:
            payload["result_sort"] = self.result_sort.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExtensionSchemaDescriptor":
        payload = _require_mapping(data, "ExtensionSchemaDescriptor")
        interface = payload.get("interface")
        if (
            interface is not None
            and interface != EXTENSION_SCHEMA_DESCRIPTOR_INTERFACE
        ):
            raise ExtensionError(
                f"unsupported ExtensionSchemaDescriptor interface {interface!r}"
            )
        sort_payload = payload.get("result_sort")
        return cls(
            schema_id=str(payload.get("schema_id") or ""),
            payload_schema=str(payload.get("payload_schema") or ""),
            family=payload.get("family") or "",
            profile=payload.get("profile") or "",
            features=tuple(payload.get("features") or ()),
            child_positions=tuple(
                ExtensionPosition.from_dict(
                    _require_mapping(item, "child_positions item")
                )
                for item in _require_sequence(
                    payload.get("child_positions") or (), "child_positions"
                )
            ),
            binder_positions=tuple(
                ExtensionPosition.from_dict(
                    _require_mapping(item, "binder_positions item")
                )
                for item in _require_sequence(
                    payload.get("binder_positions") or (), "binder_positions"
                )
            ),
            result_category=str(
                payload.get("result_category") or ExprCategory.FORMULA.value
            ),
            result_sort=(
                None
                if sort_payload is None
                else LogicSort.from_dict(
                    _require_mapping(sort_payload, "result_sort")
                )
            ),
            required_keys=tuple(payload.get("required_keys") or ()),
            translation_features=tuple(payload.get("translation_features") or ()),
            unsupported_behavior=str(
                payload.get("unsupported_behavior")
                or ExtensionUnsupportedBehavior.REJECT.value
            ),
            description=str(payload.get("description") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version")
                or EXTENSION_SCHEMA_DESCRIPTOR_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


def _diagnostic(
    diagnostic_id: str,
    code: str,
    message: str,
    *,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    range: SourceRange | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=diagnostic_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
    )


@dataclass(frozen=True, slots=True)
class ExtensionValidationReport:
    """Result of validating an extension node against a schema registry."""

    ok: bool
    payload_schema: str
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    descriptor: ExtensionSchemaDescriptor | None = None

    def raise_if_failed(self) -> None:
        if self.ok:
            return
        if not self.diagnostics:
            raise ExtensionError(
                f"extension validation failed for {self.payload_schema!r}"
            )
        first = self.diagnostics[0]
        code = first.code
        message = first.message
        if code == CODE_UNKNOWN_EXTENSION_SCHEMA:
            raise UnknownExtensionSchemaError(message)
        if code == CODE_MALFORMED_EXTENSION_PAYLOAD or code in {
            CODE_EXTENSION_CHILD_ARITY,
            CODE_EXTENSION_BINDER_ARITY,
            CODE_EXTENSION_FEATURE_MISMATCH,
            CODE_EXTENSION_IDENTITY_MISMATCH,
            CODE_EXTENSION_SORT_MISMATCH,
            CODE_EXTENSION_REQUIRED_KEY,
        }:
            raise MalformedExtensionPayloadError(message)
        if code == CODE_UNSUPPORTED_EXTENSION:
            raise UnsupportedExtensionError(message)
        raise ExtensionError(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptor": None
            if self.descriptor is None
            else self.descriptor.to_dict(),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "ok": self.ok,
            "payload_schema": self.payload_schema,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class ExtensionSchemaRegistry:
    """Fail-closed registry of versioned extension payload schemas.

    Interface: ``ExtensionSchemaRegistry@1``.

    Collisions are rejected.  Unknown schemas and malformed payloads produce
    stable diagnostics and never silently succeed.
    """

    registry_id: str = "registry:extension-schema"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EXTENSION_SCHEMA_REGISTRY_SCHEMA_VERSION
    _entries: dict[str, ExtensionSchemaDescriptor] = field(
        default_factory=dict, init=False, repr=False
    )

    interface: ClassVar[str] = EXTENSION_SCHEMA_REGISTRY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "registry_id", _record_id(self.registry_id, "registry_id")
        )
        object.__setattr__(
            self, "metadata", _freeze_mapping(dict(self.metadata), "metadata")
        )
        if self.schema_version != EXTENSION_SCHEMA_REGISTRY_SCHEMA_VERSION:
            raise ExtensionError(
                f"unsupported ExtensionSchemaRegistry schema_version "
                f"{self.schema_version!r}"
            )

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, payload_schema: object) -> bool:
        return isinstance(payload_schema, str) and payload_schema in self._entries

    def registered_schemas(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def descriptors(self) -> tuple[ExtensionSchemaDescriptor, ...]:
        return tuple(
            self._entries[key] for key in sorted(self._entries)
        )

    def register(
        self, descriptor: ExtensionSchemaDescriptor
    ) -> ExtensionSchemaDescriptor:
        """Register *descriptor*; reject duplicate payload schemas."""

        if not isinstance(descriptor, ExtensionSchemaDescriptor):
            if isinstance(descriptor, Mapping):
                descriptor = ExtensionSchemaDescriptor.from_dict(descriptor)
            else:
                raise ExtensionError(
                    "register requires an ExtensionSchemaDescriptor"
                )
        key = descriptor.payload_schema
        if key in self._entries:
            raise DuplicateExtensionSchemaError(
                f"extension schema {key!r} is already registered "
                f"(descriptor {self._entries[key].schema_id!r})"
            )
        self._entries[key] = descriptor
        return descriptor

    def get(self, payload_schema: str) -> ExtensionSchemaDescriptor:
        """Return the descriptor for *payload_schema* or raise."""

        schema = _payload_schema(payload_schema)
        try:
            return self._entries[schema]
        except KeyError as error:
            raise UnknownExtensionSchemaError(
                f"unknown extension payload schema {schema!r}; "
                "unregistered extension payloads are rejected"
            ) from error

    def get_or_none(
        self, payload_schema: str
    ) -> ExtensionSchemaDescriptor | None:
        schema = _payload_schema(payload_schema)
        return self._entries.get(schema)

    def require(
        self, payload_schema: str, *, consumer: str = "consumer"
    ) -> ExtensionSchemaDescriptor:
        """Resolve *payload_schema* or emit unsupported-extension failure."""

        schema = _payload_schema(payload_schema)
        descriptor = self._entries.get(schema)
        if descriptor is not None:
            return descriptor
        raise UnsupportedExtensionError(
            f"{consumer} lacks extension schema {schema!r}; "
            "unsupported extensions must not cross elaboration or translation"
        )

    def validate_payload(
        self,
        payload_schema: str,
        payload: Mapping[str, Any],
        *,
        range: SourceRange | None = None,
        diagnostic_prefix: str = "diag:ext",
    ) -> ExtensionValidationReport:
        """Validate a raw payload mapping against a registered schema."""

        diagnostics: list[SyntaxDiagnostic] = []
        seq = [0]

        def next_diag(code: str, message: str) -> None:
            seq[0] += 1
            diagnostics.append(
                _diagnostic(
                    f"{diagnostic_prefix}:{seq[0]}",
                    code,
                    message,
                    range=range,
                )
            )

        try:
            schema = _payload_schema(payload_schema)
        except AstError as error:
            next_diag(CODE_MALFORMED_EXTENSION_PAYLOAD, str(error))
            return ExtensionValidationReport(
                ok=False,
                payload_schema=str(payload_schema or ""),
                diagnostics=tuple(diagnostics),
            )

        descriptor = self._entries.get(schema)
        if descriptor is None:
            next_diag(
                CODE_UNKNOWN_EXTENSION_SCHEMA,
                f"unknown extension payload schema {schema!r}; "
                "unregistered extension payloads are rejected",
            )
            return ExtensionValidationReport(
                ok=False,
                payload_schema=schema,
                diagnostics=tuple(diagnostics),
            )

        if not isinstance(payload, Mapping):
            next_diag(
                CODE_MALFORMED_EXTENSION_PAYLOAD,
                "extension payload must be a structured mapping",
            )
            return ExtensionValidationReport(
                ok=False,
                payload_schema=schema,
                diagnostics=tuple(diagnostics),
                descriptor=descriptor,
            )

        try:
            frozen = _freeze_mapping(payload, "payload")
        except SyntaxContractError as error:
            next_diag(CODE_MALFORMED_EXTENSION_PAYLOAD, str(error))
            return ExtensionValidationReport(
                ok=False,
                payload_schema=schema,
                diagnostics=tuple(diagnostics),
                descriptor=descriptor,
            )

        if not frozen:
            next_diag(
                CODE_MALFORMED_EXTENSION_PAYLOAD,
                "extension payload must not be empty",
            )

        for key in descriptor.required_keys:
            if key not in frozen:
                next_diag(
                    CODE_EXTENSION_REQUIRED_KEY,
                    f"extension payload for {schema!r} missing required key {key!r}",
                )

        if descriptor.payload_validator is not None:
            try:
                descriptor.payload_validator(_thaw_mapping(frozen))
            except Exception as error:  # noqa: BLE001 — surface as diagnostic
                next_diag(
                    CODE_MALFORMED_EXTENSION_PAYLOAD,
                    f"extension payload for {schema!r} failed schema validator: "
                    f"{error}",
                )

        return ExtensionValidationReport(
            ok=not diagnostics,
            payload_schema=schema,
            diagnostics=tuple(diagnostics),
            descriptor=descriptor,
        )

    def validate_extension(
        self,
        extension: LogicExtensionNode | LogicNode,
        *,
        binders: Sequence[Binder] = (),
        diagnostic_prefix: str = "diag:ext",
    ) -> ExtensionValidationReport:
        """Validate a :class:`LogicExtensionNode` (or extension :class:`LogicNode`)."""

        if isinstance(extension, LogicNode):
            if extension.extension is None:
                return ExtensionValidationReport(
                    ok=False,
                    payload_schema="",
                    diagnostics=(
                        _diagnostic(
                            f"{diagnostic_prefix}:1",
                            CODE_MALFORMED_EXTENSION_PAYLOAD,
                            "extension node missing extension payload",
                            range=extension.range,
                        ),
                    ),
                )
            node_binders = binders or extension.binders
            return self.validate_extension(
                extension.extension,
                binders=node_binders,
                diagnostic_prefix=diagnostic_prefix,
            )

        if not isinstance(extension, LogicExtensionNode):
            raise ExtensionError(
                "validate_extension requires a LogicExtensionNode or LogicNode"
            )

        report = self.validate_payload(
            extension.payload_schema,
            _thaw_mapping(extension.payload),
            range=extension.range,
            diagnostic_prefix=diagnostic_prefix,
        )
        diagnostics = list(report.diagnostics)
        descriptor = report.descriptor
        seq = [len(diagnostics)]

        def next_diag(code: str, message: str) -> None:
            seq[0] += 1
            diagnostics.append(
                _diagnostic(
                    f"{diagnostic_prefix}:{seq[0]}",
                    code,
                    message,
                    range=extension.range,
                )
            )

        if descriptor is None:
            return ExtensionValidationReport(
                ok=False,
                payload_schema=report.payload_schema,
                diagnostics=tuple(diagnostics),
            )

        # Family / profile identity.
        family_value = (
            extension.family.value
            if isinstance(extension.family, LogicIdentity)
            else str(extension.family)
        )
        profile_value = (
            extension.profile.value
            if isinstance(extension.profile, LogicIdentity)
            else str(extension.profile)
        )
        desc_family = (
            descriptor.family.value
            if isinstance(descriptor.family, LogicIdentity)
            else str(descriptor.family)
        )
        desc_profile = (
            descriptor.profile.value
            if isinstance(descriptor.profile, LogicIdentity)
            else str(descriptor.profile)
        )
        if family_value != desc_family:
            next_diag(
                CODE_EXTENSION_IDENTITY_MISMATCH,
                f"extension family {family_value!r} does not match schema "
                f"family {desc_family!r}",
            )
        if profile_value != desc_profile:
            next_diag(
                CODE_EXTENSION_IDENTITY_MISMATCH,
                f"extension profile {profile_value!r} does not match schema "
                f"profile {desc_profile!r}",
            )

        # Features must cover the descriptor's declared feature set.
        ext_features = set(extension.features)
        missing = [item for item in descriptor.features if item not in ext_features]
        if missing:
            next_diag(
                CODE_EXTENSION_FEATURE_MISMATCH,
                f"extension features missing required schema features: "
                f"{', '.join(missing)}",
            )

        # Child arity / category.
        children = extension.children
        if len(children) < descriptor.min_children:
            next_diag(
                CODE_EXTENSION_CHILD_ARITY,
                f"extension {descriptor.payload_schema!r} requires at least "
                f"{descriptor.min_children} children; got {len(children)}",
            )
        if len(children) > descriptor.max_children:
            next_diag(
                CODE_EXTENSION_CHILD_ARITY,
                f"extension {descriptor.payload_schema!r} allows at most "
                f"{descriptor.max_children} children; got {len(children)}",
            )
        for index, child in enumerate(children):
            if index >= len(descriptor.child_positions):
                break
            position = descriptor.child_positions[index]
            if position.category is not None:
                expected = position.category
                if isinstance(expected, ExprCategory):
                    if child.category is not expected:
                        next_diag(
                            CODE_EXTENSION_SORT_MISMATCH,
                            f"extension child {position.name!r} expected "
                            f"category {expected.value}; got "
                            f"{child.category.value}",
                        )
            if position.sort is not None:
                try:
                    child_sort = child.result_sort
                except AstError:
                    child_sort = child.sort
                if child_sort is not None and child_sort != position.sort:
                    next_diag(
                        CODE_EXTENSION_SORT_MISMATCH,
                        f"extension child {position.name!r} expected sort "
                        f"{position.sort!s}; got {child_sort!s}",
                    )

        # Binder arity (binders may be supplied on the wrapping LogicNode).
        binder_list = tuple(binders)
        if len(binder_list) < descriptor.min_binders:
            next_diag(
                CODE_EXTENSION_BINDER_ARITY,
                f"extension {descriptor.payload_schema!r} requires at least "
                f"{descriptor.min_binders} binders; got {len(binder_list)}",
            )
        if len(binder_list) > descriptor.max_binders:
            next_diag(
                CODE_EXTENSION_BINDER_ARITY,
                f"extension {descriptor.payload_schema!r} allows at most "
                f"{descriptor.max_binders} binders; got {len(binder_list)}",
            )
        for index, binder in enumerate(binder_list):
            if index >= len(descriptor.binder_positions):
                break
            position = descriptor.binder_positions[index]
            if position.sort is not None and binder.sort != position.sort:
                next_diag(
                    CODE_EXTENSION_SORT_MISMATCH,
                    f"extension binder {position.name!r} expected sort "
                    f"{position.sort!s}; got {binder.sort!s}",
                )

        if len(diagnostics) > MAX_DIAGNOSTICS:
            diagnostics = diagnostics[:MAX_DIAGNOSTICS]

        return ExtensionValidationReport(
            ok=not diagnostics,
            payload_schema=descriptor.payload_schema,
            diagnostics=tuple(diagnostics),
            descriptor=descriptor,
        )

    def validate_extension_or_raise(
        self,
        extension: LogicExtensionNode | LogicNode,
        *,
        binders: Sequence[Binder] = (),
    ) -> ExtensionSchemaDescriptor:
        report = self.validate_extension(extension, binders=binders)
        report.raise_if_failed()
        if report.descriptor is None:
            raise ExtensionError("extension validation produced no descriptor")
        return report.descriptor

    def elaborate_extension(
        self,
        node: LogicNode,
        *,
        elaborated_children: Sequence[LogicNode] | None = None,
    ) -> LogicNode:
        """Validate *node* and return a sort-annotated extension node.

        Child elaboration is the caller's responsibility; pass already
        elaborated children via *elaborated_children* when available.
        """

        if not isinstance(node, LogicNode) or node.extension is None:
            raise ExtensionError(
                "elaborate_extension requires a LogicNode with extension payload"
            )
        descriptor = self.validate_extension_or_raise(node)
        children = (
            tuple(elaborated_children)
            if elaborated_children is not None
            else node.extension.children
        )
        # Re-check categories after elaboration.
        if elaborated_children is not None:
            recheck = LogicExtensionNode(
                node_id=node.extension.node_id,
                family=node.extension.family,
                profile=node.extension.profile,
                features=node.extension.features,
                payload_schema=node.extension.payload_schema,
                payload=_thaw_mapping(node.extension.payload),
                children=children,
                range=node.extension.range,
                metadata=_thaw_mapping(node.extension.metadata),
            )
            self.validate_extension_or_raise(
                recheck, binders=node.binders
            )

        encoded_payload = descriptor.encode_payload(
            _thaw_mapping(node.extension.payload)
        )
        extension = LogicExtensionNode(
            node_id=node.extension.node_id,
            family=node.extension.family,
            profile=node.extension.profile,
            features=node.extension.features,
            payload_schema=node.extension.payload_schema,
            payload=encoded_payload,
            children=tuple(children),
            range=node.extension.range,
            metadata=_thaw_mapping(node.extension.metadata),
        )
        result_sort = descriptor.result_sort or BOOL_SORT
        return LogicNode(
            node_id=node.node_id,
            kind=NodeKind.EXTENSION,
            extension=extension,
            binders=node.binders,
            sort=result_sort,
            range=node.range,
            metadata=_thaw_mapping(node.metadata),
        )

    def encode_extension_payload(
        self, extension: LogicExtensionNode
    ) -> dict[str, Any]:
        """Encode *extension* payload through its registered codec."""

        descriptor = self.get(extension.payload_schema)
        self.validate_extension_or_raise(extension)
        return descriptor.encode_payload(_thaw_mapping(extension.payload))

    def decode_extension_payload(
        self, payload_schema: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Decode a wire payload through the registered codec and validate."""

        descriptor = self.get(payload_schema)
        decoded = descriptor.decode_payload(payload)
        report = self.validate_payload(payload_schema, decoded)
        report.raise_if_failed()
        return decoded

    def semantic_identity_payload(
        self, extension: LogicExtensionNode
    ) -> dict[str, Any]:
        """Return the semantic-hash contribution for a registered extension."""

        descriptor = self.get(extension.payload_schema)
        base = {
            "family": extension.family.to_dict()
            if isinstance(extension.family, LogicIdentity)
            else extension.family,
            "features": list(extension.features),
            "payload_schema": extension.payload_schema,
            "profile": extension.profile.to_dict()
            if isinstance(extension.profile, LogicIdentity)
            else extension.profile,
            "semantic": descriptor.semantic_payload(extension),
        }
        return base

    def semantic_identity(self, extension: LogicExtensionNode) -> str:
        """Stable semantic digest for a registered extension payload."""

        return content_sha256(
            canonical_json_bytes(self.semantic_identity_payload(extension))
        )

    def build_node(
        self,
        node_id: str,
        payload_schema: str,
        payload: Mapping[str, Any],
        *,
        children: Sequence[LogicNode] = (),
        binders: Sequence[Binder] = (),
        features: Sequence[str] | None = None,
        family: LogicIdentity | Mapping[str, Any] | str | None = None,
        profile: LogicIdentity | Mapping[str, Any] | str | None = None,
        range: SourceRange | None = None,
    ) -> LogicNode:
        """Construct a validated extension node from a registered schema."""

        descriptor = self.get(payload_schema)
        report = self.validate_payload(payload_schema, payload, range=range)
        report.raise_if_failed()
        node = mk_extension(
            node_id,
            family=family if family is not None else descriptor.family,
            profile=profile if profile is not None else descriptor.profile,
            features=features if features is not None else descriptor.features,
            payload_schema=payload_schema,
            payload=descriptor.encode_payload(payload),
            children=children,
            range=range,
        )
        if binders:
            node = LogicNode(
                node_id=node.node_id,
                kind=NodeKind.EXTENSION,
                extension=node.extension,
                binders=tuple(binders),
                sort=descriptor.result_sort or BOOL_SORT,
                range=range,
            )
        self.validate_extension_or_raise(node)
        return node

    def freeze(self) -> "FrozenExtensionSchemaRegistry":
        return FrozenExtensionSchemaRegistry(
            registry_id=self.registry_id,
            descriptors=self.descriptors(),
            metadata=_thaw_mapping(self.metadata),
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptors": [item.to_dict() for item in self.descriptors()],
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "registry_id": self.registry_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExtensionSchemaRegistry":
        payload = _require_mapping(data, "ExtensionSchemaRegistry")
        interface = payload.get("interface")
        if (
            interface is not None
            and interface != EXTENSION_SCHEMA_REGISTRY_INTERFACE
        ):
            raise ExtensionError(
                f"unsupported ExtensionSchemaRegistry interface {interface!r}"
            )
        registry = cls(
            registry_id=str(payload.get("registry_id") or "registry:extension-schema"),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version")
                or EXTENSION_SCHEMA_REGISTRY_SCHEMA_VERSION
            ),
        )
        for item in _require_sequence(
            payload.get("descriptors") or (), "descriptors"
        ):
            registry.register(
                ExtensionSchemaDescriptor.from_dict(
                    _require_mapping(item, "descriptors item")
                )
            )
        return registry


@dataclass(frozen=True, slots=True)
class FrozenExtensionSchemaRegistry:
    """Immutable snapshot of an :class:`ExtensionSchemaRegistry`."""

    registry_id: str
    descriptors: tuple[ExtensionSchemaDescriptor, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EXTENSION_SCHEMA_REGISTRY_SCHEMA_VERSION

    interface: ClassVar[str] = EXTENSION_SCHEMA_REGISTRY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "registry_id", _record_id(self.registry_id, "registry_id")
        )
        descriptors = tuple(
            item
            if isinstance(item, ExtensionSchemaDescriptor)
            else ExtensionSchemaDescriptor.from_dict(
                _require_mapping(item, "descriptors item")
            )
            for item in _require_sequence(self.descriptors, "descriptors")
        )
        keys = [item.payload_schema for item in descriptors]
        if len(keys) != len(set(keys)):
            raise ExtensionError(
                "FrozenExtensionSchemaRegistry descriptors must have unique "
                "payload_schema values"
            )
        object.__setattr__(self, "descriptors", descriptors)
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != EXTENSION_SCHEMA_REGISTRY_SCHEMA_VERSION:
            raise ExtensionError(
                f"unsupported FrozenExtensionSchemaRegistry schema_version "
                f"{self.schema_version!r}"
            )

    def thaw(self) -> ExtensionSchemaRegistry:
        registry = ExtensionSchemaRegistry(
            registry_id=self.registry_id,
            metadata=_thaw_mapping(self.metadata),
            schema_version=self.schema_version,
        )
        for descriptor in self.descriptors:
            registry.register(descriptor)
        return registry

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptors": [item.to_dict() for item in self.descriptors],
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "registry_id": self.registry_id,
            "schema_version": self.schema_version,
        }


def empty_extension_registry(
    registry_id: str = "registry:extension-schema",
) -> ExtensionSchemaRegistry:
    """Return an empty mutable extension schema registry."""

    return ExtensionSchemaRegistry(registry_id=registry_id)


def modal_box_descriptor() -> ExtensionSchemaDescriptor:
    """Built-in sample descriptor for ``modal.box/v1`` (tests and demos)."""

    return ExtensionSchemaDescriptor(
        schema_id="ext:modal.box/v1",
        payload_schema="modal.box/v1",
        family="modal",
        profile="s5",
        features=("modal.box", "modal.kripke"),
        child_positions=(
            ExtensionPosition(
                name="body",
                kind=ExtensionPositionKind.CHILD,
                required=True,
                category=ExprCategory.FORMULA,
            ),
        ),
        required_keys=("kind",),
        translation_features=("modal.box",),
        description="Alethic/epistemic box modality over one formula child",
        payload_validator=_validate_modal_box_payload,
    )


def _validate_modal_box_payload(payload: Mapping[str, Any]) -> None:
    kind = payload.get("kind")
    if kind != "box":
        raise MalformedExtensionPayloadError(
            f"modal.box/v1 payload.kind must be 'box'; got {kind!r}"
        )


DEFAULT_EXTENSION_REGISTRY: Final = empty_extension_registry(
    "registry:extension-schema:default"
)
DEFAULT_EXTENSION_REGISTRY.register(modal_box_descriptor())


__all__ = [
    "CODE_EXTENSION_BINDER_ARITY",
    "CODE_EXTENSION_CHILD_ARITY",
    "CODE_EXTENSION_DUPLICATE",
    "CODE_EXTENSION_FEATURE_MISMATCH",
    "CODE_EXTENSION_IDENTITY_MISMATCH",
    "CODE_EXTENSION_REQUIRED_KEY",
    "CODE_EXTENSION_SORT_MISMATCH",
    "CODE_MALFORMED_EXTENSION_PAYLOAD",
    "CODE_UNKNOWN_EXTENSION_SCHEMA",
    "CODE_UNSUPPORTED_EXTENSION",
    "DEFAULT_EXTENSION_REGISTRY",
    "EXTENSIONS_MODULE_VERSION",
    "EXTENSION_SCHEMA_DESCRIPTOR_INTERFACE",
    "EXTENSION_SCHEMA_DESCRIPTOR_SCHEMA_VERSION",
    "EXTENSION_SCHEMA_REGISTRY_INTERFACE",
    "EXTENSION_SCHEMA_REGISTRY_SCHEMA_VERSION",
    "DuplicateExtensionSchemaError",
    "ExtensionError",
    "ExtensionPosition",
    "ExtensionPositionKind",
    "ExtensionSchemaDescriptor",
    "ExtensionSchemaRegistry",
    "ExtensionUnsupportedBehavior",
    "ExtensionValidationReport",
    "FrozenExtensionSchemaRegistry",
    "MalformedExtensionPayloadError",
    "UnknownExtensionSchemaError",
    "UnsupportedExtensionError",
    "empty_extension_registry",
    "modal_box_descriptor",
]
