"""SPAR-004 closed initialization and public compatibility contracts.

This module extends datasets formal semantic authority with versioned,
content-addressed records for top-level initialization blocks and public
compatibility obligations.  It does not create a competing task, graph,
identity, VFS, proof, context, scheduler, vector, merge, or state authority.

Unsupported required behavior is a typed terminal and is never success.
Observational metadata (timestamps, process IDs, local paths, model output)
is excluded from identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)

TASK_ID: Final[str] = "SPAR-004"
GOAL_ID: Final[str] = "SPAR-G013"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"

COMPATIBILITY_CONTRACTS_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.compatibility-contracts@1"
)
INITIALIZATION_BLOCK_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.initialization-block@1"
)
PUBLIC_COMPATIBILITY_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.public-compatibility-obligation@1"
)
COMPATIBILITY_TERMINAL_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.compatibility-terminal@1"
)
IMPORT_EFFECT_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.import-effect@1"
)
REGISTRY_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.registry-obligation@1"
)
DECORATOR_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.decorator-obligation@1"
)
RESOURCE_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.resource-obligation@1"
)
SERIALIZATION_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.serialization-obligation@1"
)
INTROSPECTION_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.introspection-obligation@1"
)
CLI_PLUGIN_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.cli-plugin-obligation@1"
)
PATCH_TARGET_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.patch-target-obligation@1"
)

INITIALIZATION_BLOCK_INTERFACE: Final[str] = "InitializationBlock@1"
PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE: Final[str] = (
    "PublicCompatibilityObligation@1"
)
COMPATIBILITY_TERMINAL_INTERFACE: Final[str] = "CompatibilityTerminal@1"

COMPATIBILITY_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
COMPATIBILITY_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
COMPATIBILITY_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False

IDENTITY_EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "timestamp",
        "timestamps",
        "process_id",
        "pid",
        "local_path",
        "local_paths",
        "checkout_path",
        "model_output",
        "model",
        "provider",
        "prompt",
        "lease",
        "fence",
        "generation",
        "receipt",
        "acceptance",
        "wall_clock",
        "clock",
    }
)

_FORBIDDEN_CAPSULE_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "FunctionSemanticCapsule",
        "MethodSemanticCapsule",
        "ClassSemanticCapsule",
        "TopLevelBlockCapsule",
        "ModuleSemanticCapsule",
        "PackageSemanticCapsule",
        "CallsiteSemanticCapsule",
        "StateOwnerCapsule",
        "RegistrationCapsule",
        "ResourceLifecycleCapsule",
    }
)


class CompatibilityContractError(ValueError):
    """Fail-closed violation of a SPAR-004 compatibility contract."""


class CompatibilityKind(str, Enum):
    """Closed public compatibility surfaces from SPAR-PLAN-R1."""

    IMPORT_PATH = "import_path"
    IMPORT_EFFECT = "import_effect"
    IMPORT_EAGERNESS = "import_eagerness"
    IMPORT_ORDER = "import_order"
    STAR_EXPORT = "star_export"
    MODULE_ATTRIBUTE = "module_attribute"
    SIGNATURE = "signature"
    ANNOTATION = "annotation"
    DEFAULT = "default"
    DECORATOR = "decorator"
    EXCEPTION = "exception"
    CLI = "cli"
    PLUGIN = "plugin"
    REGISTRY = "registry"
    MODULE_NAME = "module_name"
    QUALNAME = "qualname"
    PICKLE = "pickle"
    SERIALIZATION = "serialization"
    INTROSPECTION = "introspection"
    TRACEBACK = "traceback"
    DOCUMENTATION = "documentation"
    CONFIGURATION = "configuration"
    PATCH_TARGET = "patch_target"
    RESOURCE = "resource"
    RESOURCE_LIFETIME = "resource_lifetime"


class SupportStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ObligationRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class CompatibilityDisposition(str, Enum):
    PRESERVE = "preserve"
    MIGRATE = "migrate"
    FACADE = "facade"
    EXPLICIT_INCOMPATIBILITY = "explicit_incompatibility"
    UNSUPPORTED = "unsupported"
    UNDISPOSITIONED = "undispositioned"


class CompatibilityTerminalKind(str, Enum):
    ADMITTED = "admitted"
    UNSUPPORTED_REQUIRED = "unsupported_required"
    UNSUPPORTED_OPTIONAL = "unsupported_optional"
    UNKNOWN_REQUIRED = "unknown_required"
    INCOMPLETE_CONTRACT = "incomplete_contract"
    CONFLICT = "conflict"


class ImportEagerness(str, Enum):
    EAGER = "eager"
    LAZY = "lazy"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class ResourcePhase(str, Enum):
    ACQUIRE = "acquire"
    HOLD = "hold"
    RELEASE = "release"
    UNKNOWN = "unknown"


class ResourceLifetime(str, Enum):
    IMPORT_MODULE = "import_module"
    PROCESS = "process"
    CONTEXT = "context"
    UNKNOWN = "unknown"


class InitializationEffectKind(str, Enum):
    IMPORT = "import"
    REGISTRATION = "registration"
    DECORATOR = "decorator"
    RESOURCE = "resource"
    IO = "io"
    NETWORK = "network"
    STATE_MUTATION = "state_mutation"
    SIGNAL = "signal"
    ATEXIT = "atexit"
    CLI_REGISTRATION = "cli_registration"
    PLUGIN_REGISTRATION = "plugin_registration"
    UNKNOWN = "unknown"


class EvidenceClass(str, Enum):
    EXACT_STATIC_FACT = "exact_static_fact"
    CONSERVATIVE_MAY_FACT = "conservative_may_fact"
    RUNTIME_OBSERVATION = "runtime_observation"


class SerializationFormat(str, Enum):
    PICKLE = "pickle"
    JSON = "json"
    DAG_JSON = "dag_json"
    CUSTOM = "custom"


class CliPluginChannel(str, Enum):
    CLI = "cli"
    PLUGIN = "plugin"
    ENTRY_POINT = "entry_point"
    MCP = "mcp"


class IntrospectionSurface(str, Enum):
    MODULE_NAME = "module_name"
    QUALNAME = "qualname"
    SIGNATURE = "signature"
    ANNOTATION = "annotation"
    DEFAULT = "default"
    TRACEBACK = "traceback"
    DOCUMENTATION = "documentation"
    INSPECT_GETSOURCE = "inspect_getsource"
    MODULE_ATTRIBUTE = "module_attribute"
    EXCEPTION = "exception"
    CONFIGURATION = "configuration"


class ObligationFamily(str, Enum):
    IMPORT = "import"
    REGISTRY = "registry"
    DECORATOR = "decorator"
    RESOURCE = "resource"
    SERIALIZATION = "serialization"
    INTROSPECTION = "introspection"
    CLI_PLUGIN = "cli_plugin"
    PATCH_TARGET = "patch_target"


KIND_FAMILY: Final[Mapping[CompatibilityKind, ObligationFamily]] = {
    CompatibilityKind.IMPORT_PATH: ObligationFamily.IMPORT,
    CompatibilityKind.IMPORT_EFFECT: ObligationFamily.IMPORT,
    CompatibilityKind.IMPORT_EAGERNESS: ObligationFamily.IMPORT,
    CompatibilityKind.IMPORT_ORDER: ObligationFamily.IMPORT,
    CompatibilityKind.STAR_EXPORT: ObligationFamily.IMPORT,
    CompatibilityKind.REGISTRY: ObligationFamily.REGISTRY,
    CompatibilityKind.DECORATOR: ObligationFamily.DECORATOR,
    CompatibilityKind.RESOURCE: ObligationFamily.RESOURCE,
    CompatibilityKind.RESOURCE_LIFETIME: ObligationFamily.RESOURCE,
    CompatibilityKind.SERIALIZATION: ObligationFamily.SERIALIZATION,
    CompatibilityKind.PICKLE: ObligationFamily.SERIALIZATION,
    CompatibilityKind.INTROSPECTION: ObligationFamily.INTROSPECTION,
    CompatibilityKind.MODULE_NAME: ObligationFamily.INTROSPECTION,
    CompatibilityKind.QUALNAME: ObligationFamily.INTROSPECTION,
    CompatibilityKind.SIGNATURE: ObligationFamily.INTROSPECTION,
    CompatibilityKind.ANNOTATION: ObligationFamily.INTROSPECTION,
    CompatibilityKind.DEFAULT: ObligationFamily.INTROSPECTION,
    CompatibilityKind.TRACEBACK: ObligationFamily.INTROSPECTION,
    CompatibilityKind.DOCUMENTATION: ObligationFamily.INTROSPECTION,
    CompatibilityKind.MODULE_ATTRIBUTE: ObligationFamily.INTROSPECTION,
    CompatibilityKind.EXCEPTION: ObligationFamily.INTROSPECTION,
    CompatibilityKind.CONFIGURATION: ObligationFamily.INTROSPECTION,
    CompatibilityKind.CLI: ObligationFamily.CLI_PLUGIN,
    CompatibilityKind.PLUGIN: ObligationFamily.CLI_PLUGIN,
    CompatibilityKind.PATCH_TARGET: ObligationFamily.PATCH_TARGET,
}

FIRST_CLASS_OBLIGATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        CompatibilityKind.IMPORT_EFFECT.value,
        CompatibilityKind.REGISTRY.value,
        CompatibilityKind.DECORATOR.value,
        CompatibilityKind.RESOURCE.value,
        CompatibilityKind.SERIALIZATION.value,
        CompatibilityKind.INTROSPECTION.value,
        CompatibilityKind.CLI.value,
        CompatibilityKind.PLUGIN.value,
        CompatibilityKind.PATCH_TARGET.value,
    }
)

PUBLIC_COMPATIBILITY_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in CompatibilityKind
)

_TERMINAL_PRECEDENCE: Final[tuple[CompatibilityTerminalKind, ...]] = (
    CompatibilityTerminalKind.CONFLICT,
    CompatibilityTerminalKind.UNSUPPORTED_REQUIRED,
    CompatibilityTerminalKind.UNKNOWN_REQUIRED,
    CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
    CompatibilityTerminalKind.UNSUPPORTED_OPTIONAL,
    CompatibilityTerminalKind.ADMITTED,
)


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise CompatibilityContractError(f"{name} must be a string")
    if value != value.strip():
        raise CompatibilityContractError(f"{name} must be trimmed text")
    if not empty and not value:
        raise CompatibilityContractError(f"{name} must be a nonempty string")
    if any(ord(char) < 32 for char in value):
        raise CompatibilityContractError(f"{name} contains control characters")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise CompatibilityContractError(f"{name} must be a valid CID") from exc


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise CompatibilityContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CompatibilityContractError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise CompatibilityContractError(f"{name} must be a nonnegative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise CompatibilityContractError(f"{name} must be a positive integer")
    return value


def _repo_relative_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("/") or text.startswith("\\"):
        raise CompatibilityContractError(f"{name} must be repository-relative")
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise CompatibilityContractError(f"{name} is not a POSIX repository path")
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise CompatibilityContractError(f"{name} must be an object")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra & IDENTITY_EXCLUDED_FIELDS:
        raise CompatibilityContractError(
            f"{name} identity excludes observational fields: "
            f"{sorted(extra & IDENTITY_EXCLUDED_FIELDS)}"
        )
    if extra:
        raise CompatibilityContractError(f"unknown {name} field: {sorted(extra)}")
    if missing:
        raise CompatibilityContractError(f"missing {name} field: {sorted(missing)}")
    return dict(data)


def _unique_sorted(values: Iterable[str], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) != len(set(ordered)):
        raise CompatibilityContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[str], enum_type: type[Enum], name: str
) -> tuple[str, ...]:
    return _unique_sorted((_enum(item, enum_type, name) for item in values), name)


def _reject_excluded(payload: Mapping[str, Any], name: str) -> None:
    present = IDENTITY_EXCLUDED_FIELDS & set(payload)
    if present:
        raise CompatibilityContractError(
            f"{name} identity excludes observational fields: {sorted(present)}"
        )


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise CompatibilityContractError(f"{name} does not verify")


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _ordered_records(
    values: Iterable[Any], cls: type[Any], name: str
) -> tuple[Any, ...]:
    records: list[Any] = []
    for item in values:
        if isinstance(item, cls):
            records.append(item)
        elif isinstance(item, Mapping):
            records.append(cls.from_dict(item))
        else:
            raise CompatibilityContractError(f"{name} entries must be {cls.__name__}")
    cids = [item.record_cid for item in records]
    if len(cids) != len(set(cids)):
        raise CompatibilityContractError(f"{name} must not contain duplicates")
    indices = [item.order_index for item in records]
    if indices != sorted(indices):
        raise CompatibilityContractError(f"{name} order_index must be nondecreasing")
    if len(indices) != len(set(indices)):
        raise CompatibilityContractError(f"{name} order_index must be unique")
    return tuple(records)


def family_for_kind(kind: CompatibilityKind | str) -> ObligationFamily:
    resolved = CompatibilityKind(kind) if not isinstance(kind, CompatibilityKind) else kind
    try:
        return KIND_FAMILY[resolved]
    except KeyError as exc:
        raise CompatibilityContractError(f"kind has no family: {kind!r}") from exc


@dataclass(frozen=True, slots=True)
class ImportEffect:
    """First-class import-time effect and import-path obligation."""

    module_name: str
    imported_names: Sequence[str]
    eagerness: ImportEagerness | str
    order_index: int
    relative: bool
    side_effects: Sequence[str] = ()
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "module_name",
            "imported_names",
            "eagerness",
            "order_index",
            "relative",
            "side_effects",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_name", _text(self.module_name, "module_name"))
        names = tuple(_text(name, "imported_name") for name in self.imported_names)
        if not names:
            raise CompatibilityContractError("imported_names must not be empty")
        if len(names) != len(set(names)):
            raise CompatibilityContractError("imported_names must not contain duplicates")
        object.__setattr__(self, "imported_names", names)
        object.__setattr__(
            self, "eagerness", _enum(self.eagerness, ImportEagerness, "eagerness")
        )
        object.__setattr__(self, "order_index", _nonneg_int(self.order_index, "order_index"))
        object.__setattr__(self, "relative", _bool(self.relative, "relative"))
        object.__setattr__(
            self,
            "side_effects",
            _unique_sorted_enums(
                self.side_effects, InitializationEffectKind, "side_effect"
            ),
        )
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": IMPORT_EFFECT_SCHEMA,
            "module_name": self.module_name,
            "imported_names": list(self.imported_names),
            "eagerness": self.eagerness,
            "order_index": self.order_index,
            "relative": self.relative,
            "side_effects": list(self.side_effects),
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImportEffect":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != IMPORT_EFFECT_SCHEMA:
            raise CompatibilityContractError("unsupported ImportEffect schema")
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "ImportEffect record_cid")
        return result


@dataclass(frozen=True, slots=True)
class RegistryObligation:
    """First-class registry registration obligation."""

    registry_id: str
    key: str
    value_binding: str
    order_index: int
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "registry_id",
            "key",
            "value_binding",
            "order_index",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_id", _text(self.registry_id, "registry_id"))
        object.__setattr__(self, "key", _text(self.key, "key"))
        object.__setattr__(
            self, "value_binding", _text(self.value_binding, "value_binding")
        )
        object.__setattr__(self, "order_index", _nonneg_int(self.order_index, "order_index"))
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REGISTRY_OBLIGATION_SCHEMA,
            "registry_id": self.registry_id,
            "key": self.key,
            "value_binding": self.value_binding,
            "order_index": self.order_index,
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RegistryObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != REGISTRY_OBLIGATION_SCHEMA:
            raise CompatibilityContractError("unsupported RegistryObligation schema")
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "RegistryObligation record_cid")
        return result


@dataclass(frozen=True, slots=True)
class DecoratorObligation:
    """First-class decorator application and side-effect obligation."""

    decorator_name: str
    target_qualname: str
    order_index: int
    side_effects: Sequence[str] = ()
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "decorator_name",
            "target_qualname",
            "order_index",
            "side_effects",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decorator_name", _text(self.decorator_name, "decorator_name")
        )
        object.__setattr__(
            self, "target_qualname", _text(self.target_qualname, "target_qualname")
        )
        object.__setattr__(self, "order_index", _nonneg_int(self.order_index, "order_index"))
        object.__setattr__(
            self,
            "side_effects",
            _unique_sorted_enums(
                self.side_effects, InitializationEffectKind, "side_effect"
            ),
        )
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DECORATOR_OBLIGATION_SCHEMA,
            "decorator_name": self.decorator_name,
            "target_qualname": self.target_qualname,
            "order_index": self.order_index,
            "side_effects": list(self.side_effects),
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecoratorObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != DECORATOR_OBLIGATION_SCHEMA:
            raise CompatibilityContractError("unsupported DecoratorObligation schema")
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "DecoratorObligation record_cid")
        return result


@dataclass(frozen=True, slots=True)
class ResourceObligation:
    """First-class resource acquire/hold/release obligation."""

    resource_id: str
    phase: ResourcePhase | str
    owner_id: str
    lifetime: ResourceLifetime | str
    order_index: int
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "resource_id",
            "phase",
            "owner_id",
            "lifetime",
            "order_index",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _text(self.resource_id, "resource_id"))
        object.__setattr__(self, "phase", _enum(self.phase, ResourcePhase, "phase"))
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(
            self, "lifetime", _enum(self.lifetime, ResourceLifetime, "lifetime")
        )
        object.__setattr__(self, "order_index", _nonneg_int(self.order_index, "order_index"))
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RESOURCE_OBLIGATION_SCHEMA,
            "resource_id": self.resource_id,
            "phase": self.phase,
            "owner_id": self.owner_id,
            "lifetime": self.lifetime,
            "order_index": self.order_index,
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResourceObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != RESOURCE_OBLIGATION_SCHEMA:
            raise CompatibilityContractError("unsupported ResourceObligation schema")
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "ResourceObligation record_cid")
        return result


@dataclass(frozen=True, slots=True)
class SerializationObligation:
    """First-class pickle/serialization compatibility obligation."""

    format: SerializationFormat | str
    type_qualname: str
    protocol: str
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "format",
            "type_qualname",
            "protocol",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "format", _enum(self.format, SerializationFormat, "format")
        )
        object.__setattr__(
            self, "type_qualname", _text(self.type_qualname, "type_qualname")
        )
        object.__setattr__(self, "protocol", _text(self.protocol, "protocol"))
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SERIALIZATION_OBLIGATION_SCHEMA,
            "format": self.format,
            "type_qualname": self.type_qualname,
            "protocol": self.protocol,
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SerializationObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != SERIALIZATION_OBLIGATION_SCHEMA:
            raise CompatibilityContractError(
                "unsupported SerializationObligation schema"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "SerializationObligation record_cid")
        return result


@dataclass(frozen=True, slots=True)
class IntrospectionObligation:
    """First-class introspection, binding, docs, and traceback obligation."""

    surface: IntrospectionSurface | str
    expected_value: str = ""
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "surface",
            "expected_value",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "surface", _enum(self.surface, IntrospectionSurface, "surface")
        )
        object.__setattr__(
            self,
            "expected_value",
            _text(self.expected_value, "expected_value", empty=True),
        )
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": INTROSPECTION_OBLIGATION_SCHEMA,
            "surface": self.surface,
            "expected_value": self.expected_value,
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IntrospectionObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != INTROSPECTION_OBLIGATION_SCHEMA:
            raise CompatibilityContractError(
                "unsupported IntrospectionObligation schema"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "IntrospectionObligation record_cid")
        return result


@dataclass(frozen=True, slots=True)
class CliPluginObligation:
    """First-class CLI, plugin, entry-point, or MCP registration obligation."""

    channel: CliPluginChannel | str
    group: str
    name: str
    target_qualname: str
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "channel",
            "group",
            "name",
            "target_qualname",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "channel", _enum(self.channel, CliPluginChannel, "channel")
        )
        object.__setattr__(self, "group", _text(self.group, "group"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "target_qualname", _text(self.target_qualname, "target_qualname")
        )
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CLI_PLUGIN_OBLIGATION_SCHEMA,
            "channel": self.channel,
            "group": self.group,
            "name": self.name,
            "target_qualname": self.target_qualname,
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CliPluginObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != CLI_PLUGIN_OBLIGATION_SCHEMA:
            raise CompatibilityContractError("unsupported CliPluginObligation schema")
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "CliPluginObligation record_cid")
        return result


@dataclass(frozen=True, slots=True)
class PatchTargetObligation:
    """First-class monkeypatch/patch-target obligation."""

    dotted_path: str
    consumer_id: str
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "dotted_path",
            "consumer_id",
            "support_status",
            "required",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "dotted_path", _text(self.dotted_path, "dotted_path"))
        if "/" in self.dotted_path or self.dotted_path.startswith("."):
            raise CompatibilityContractError("dotted_path must be an absolute dotted name")
        object.__setattr__(self, "consumer_id", _text(self.consumer_id, "consumer_id"))
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PATCH_TARGET_OBLIGATION_SCHEMA,
            "dotted_path": self.dotted_path,
            "consumer_id": self.consumer_id,
            "support_status": self.support_status,
            "required": self.required,
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PatchTargetObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != PATCH_TARGET_OBLIGATION_SCHEMA:
            raise CompatibilityContractError("unsupported PatchTargetObligation schema")
        result = cls(**payload)
        _verify_cid(claimed, result.record_cid, "PatchTargetObligation record_cid")
        return result


def _nested_or_none(
    value: Any, cls: type[Any], name: str
) -> Any:
    if value is None:
        return None
    if isinstance(value, cls):
        return value
    if isinstance(value, Mapping):
        return cls.from_dict(value)
    raise CompatibilityContractError(f"{name} must be {cls.__name__} or null")


def _nested_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.to_dict()


@dataclass(frozen=True, slots=True)
class InitializationBlock:
    """First-class top-level initialization block contract.

    Captures import effects, registries, decorators, resources, and
    happens-before order for one content-addressed top-level region.
    """

    block_id: str
    module_path: str
    source_cid: str
    start_line: int
    end_line: int
    order_index: int
    eagerness: ImportEagerness | str
    import_effects: Sequence[ImportEffect] = ()
    registries: Sequence[RegistryObligation] = ()
    decorators: Sequence[DecoratorObligation] = ()
    resources: Sequence[ResourceObligation] = ()
    happens_before: Sequence[str] = ()
    support_status: SupportStatus | str = SupportStatus.SUPPORTED
    required: bool = True
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT

    interface: ClassVar[str] = INITIALIZATION_BLOCK_INTERFACE
    schema: ClassVar[str] = INITIALIZATION_BLOCK_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "block_id",
            "module_path",
            "source_cid",
            "start_line",
            "end_line",
            "order_index",
            "eagerness",
            "import_effects",
            "registries",
            "decorators",
            "resources",
            "happens_before",
            "support_status",
            "required",
            "evidence_class",
            "block_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "block_id", _text(self.block_id, "block_id"))
        object.__setattr__(
            self, "module_path", _repo_relative_path(self.module_path, "module_path")
        )
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        start = _positive_int(self.start_line, "start_line")
        end = _positive_int(self.end_line, "end_line")
        if end < start:
            raise CompatibilityContractError("end_line must be >= start_line")
        object.__setattr__(self, "start_line", start)
        object.__setattr__(self, "end_line", end)
        object.__setattr__(self, "order_index", _nonneg_int(self.order_index, "order_index"))
        object.__setattr__(
            self, "eagerness", _enum(self.eagerness, ImportEagerness, "eagerness")
        )
        object.__setattr__(
            self,
            "import_effects",
            _ordered_records(self.import_effects, ImportEffect, "import_effects"),
        )
        object.__setattr__(
            self,
            "registries",
            _ordered_records(self.registries, RegistryObligation, "registries"),
        )
        object.__setattr__(
            self,
            "decorators",
            _ordered_records(self.decorators, DecoratorObligation, "decorators"),
        )
        object.__setattr__(
            self,
            "resources",
            _ordered_records(self.resources, ResourceObligation, "resources"),
        )
        predecessors = _unique_sorted(self.happens_before, "happens_before")
        if self.block_id in predecessors:
            raise CompatibilityContractError("happens_before cannot include self")
        object.__setattr__(self, "happens_before", predecessors)
        object.__setattr__(
            self,
            "support_status",
            _enum(self.support_status, SupportStatus, "support_status"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(
            self,
            "evidence_class",
            _enum(self.evidence_class, EvidenceClass, "evidence_class"),
        )

    def nested_obligations(
        self,
    ) -> tuple[
        ImportEffect | RegistryObligation | DecoratorObligation | ResourceObligation,
        ...,
    ]:
        return tuple(self.import_effects) + tuple(self.registries) + tuple(
            self.decorators
        ) + tuple(self.resources)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": INITIALIZATION_BLOCK_SCHEMA,
            "interface": INITIALIZATION_BLOCK_INTERFACE,
            "block_id": self.block_id,
            "module_path": self.module_path,
            "source_cid": self.source_cid,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "order_index": self.order_index,
            "eagerness": self.eagerness,
            "import_effects": [item.identity_payload() for item in self.import_effects],
            "registries": [item.identity_payload() for item in self.registries],
            "decorators": [item.identity_payload() for item in self.decorators],
            "resources": [item.identity_payload() for item in self.resources],
            "happens_before": list(self.happens_before),
            "support_status": self.support_status,
            "required": self.required,
            "evidence_class": self.evidence_class,
        }

    @property
    def block_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": INITIALIZATION_BLOCK_SCHEMA,
            "interface": INITIALIZATION_BLOCK_INTERFACE,
            "block_id": self.block_id,
            "module_path": self.module_path,
            "source_cid": self.source_cid,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "order_index": self.order_index,
            "eagerness": self.eagerness,
            "import_effects": [item.to_dict() for item in self.import_effects],
            "registries": [item.to_dict() for item in self.registries],
            "decorators": [item.to_dict() for item in self.decorators],
            "resources": [item.to_dict() for item in self.resources],
            "happens_before": list(self.happens_before),
            "support_status": self.support_status,
            "required": self.required,
            "evidence_class": self.evidence_class,
            "block_cid": self.block_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InitializationBlock":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("block_cid")
        if payload.pop("schema") != INITIALIZATION_BLOCK_SCHEMA:
            raise CompatibilityContractError("unsupported InitializationBlock schema")
        if payload.pop("interface") != INITIALIZATION_BLOCK_INTERFACE:
            raise CompatibilityContractError(
                "unsupported InitializationBlock interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.block_cid, "InitializationBlock block_cid")
        return result


@dataclass(frozen=True, slots=True)
class PublicCompatibilityObligation:
    """First-class public compatibility obligation for one consumer surface."""

    obligation_id: str
    kind: CompatibilityKind | str
    subject_id: str
    subject_module: str
    subject_qualname: str
    required: bool
    support_status: SupportStatus | str
    disposition: CompatibilityDisposition | str
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT
    consumer_id: str | None = None
    import_effect: ImportEffect | None = None
    registry: RegistryObligation | None = None
    decorator: DecoratorObligation | None = None
    resource: ResourceObligation | None = None
    serialization: SerializationObligation | None = None
    introspection: IntrospectionObligation | None = None
    cli_plugin: CliPluginObligation | None = None
    patch_target: PatchTargetObligation | None = None

    interface: ClassVar[str] = PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE
    schema: ClassVar[str] = PUBLIC_COMPATIBILITY_OBLIGATION_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "obligation_id",
            "kind",
            "subject_id",
            "subject_module",
            "subject_qualname",
            "required",
            "support_status",
            "disposition",
            "evidence_class",
            "consumer_id",
            "import_effect",
            "registry",
            "decorator",
            "resource",
            "serialization",
            "introspection",
            "cli_plugin",
            "patch_target",
            "obligation_cid",
        }
    )

    _PAYLOAD_FIELDS: ClassVar[tuple[str, ...]] = (
        "import_effect",
        "registry",
        "decorator",
        "resource",
        "serialization",
        "introspection",
        "cli_plugin",
        "patch_target",
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        kind = _enum(self.kind, CompatibilityKind, "kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "subject_id", _text(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "subject_module", _text(self.subject_module, "subject_module")
        )
        object.__setattr__(
            self, "subject_qualname", _text(self.subject_qualname, "subject_qualname")
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))
        support = _enum(self.support_status, SupportStatus, "support_status")
        object.__setattr__(self, "support_status", support)
        disposition = _enum(
            self.disposition, CompatibilityDisposition, "disposition"
        )
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(
            self,
            "evidence_class",
            _enum(self.evidence_class, EvidenceClass, "evidence_class"),
        )
        object.__setattr__(
            self, "consumer_id", _optional_text(self.consumer_id, "consumer_id")
        )
        object.__setattr__(
            self,
            "import_effect",
            _nested_or_none(self.import_effect, ImportEffect, "import_effect"),
        )
        object.__setattr__(
            self,
            "registry",
            _nested_or_none(self.registry, RegistryObligation, "registry"),
        )
        object.__setattr__(
            self,
            "decorator",
            _nested_or_none(self.decorator, DecoratorObligation, "decorator"),
        )
        object.__setattr__(
            self,
            "resource",
            _nested_or_none(self.resource, ResourceObligation, "resource"),
        )
        object.__setattr__(
            self,
            "serialization",
            _nested_or_none(
                self.serialization, SerializationObligation, "serialization"
            ),
        )
        object.__setattr__(
            self,
            "introspection",
            _nested_or_none(
                self.introspection, IntrospectionObligation, "introspection"
            ),
        )
        object.__setattr__(
            self,
            "cli_plugin",
            _nested_or_none(self.cli_plugin, CliPluginObligation, "cli_plugin"),
        )
        object.__setattr__(
            self,
            "patch_target",
            _nested_or_none(
                self.patch_target, PatchTargetObligation, "patch_target"
            ),
        )
        self._validate_payload_family()
        self._validate_disposition()

    def _payload_map(self) -> dict[str, Any]:
        return {
            "import_effect": self.import_effect,
            "registry": self.registry,
            "decorator": self.decorator,
            "resource": self.resource,
            "serialization": self.serialization,
            "introspection": self.introspection,
            "cli_plugin": self.cli_plugin,
            "patch_target": self.patch_target,
        }

    def _validate_payload_family(self) -> None:
        family = family_for_kind(self.kind)
        expected = {
            ObligationFamily.IMPORT: "import_effect",
            ObligationFamily.REGISTRY: "registry",
            ObligationFamily.DECORATOR: "decorator",
            ObligationFamily.RESOURCE: "resource",
            ObligationFamily.SERIALIZATION: "serialization",
            ObligationFamily.INTROSPECTION: "introspection",
            ObligationFamily.CLI_PLUGIN: "cli_plugin",
            ObligationFamily.PATCH_TARGET: "patch_target",
        }[family]
        payloads = self._payload_map()
        present = [name for name, value in payloads.items() if value is not None]
        if expected not in present:
            raise CompatibilityContractError(
                f"{expected} is required for kind {self.kind}"
            )
        extra = [name for name in present if name != expected]
        if extra:
            raise CompatibilityContractError(
                f"kind {self.kind} admits only {expected}, not {extra}"
            )

    def _validate_disposition(self) -> None:
        if self.support_status == SupportStatus.UNSUPPORTED.value:
            if self.disposition not in {
                CompatibilityDisposition.UNSUPPORTED.value,
                CompatibilityDisposition.EXPLICIT_INCOMPATIBILITY.value,
            }:
                raise CompatibilityContractError(
                    "unsupported obligations must declare unsupported or "
                    "explicit_incompatibility disposition"
                )
        if self.support_status == SupportStatus.SUPPORTED.value:
            if self.disposition == CompatibilityDisposition.UNSUPPORTED.value:
                raise CompatibilityContractError(
                    "supported obligations cannot use unsupported disposition"
                )
        if self.support_status == SupportStatus.UNKNOWN.value:
            if self.disposition != CompatibilityDisposition.UNDISPOSITIONED.value:
                raise CompatibilityContractError(
                    "unknown support requires undispositioned disposition"
                )
        if (
            self.required
            and self.consumer_id is None
            and self.disposition
            not in {
                CompatibilityDisposition.UNDISPOSITIONED.value,
                CompatibilityDisposition.UNSUPPORTED.value,
            }
        ):
            raise CompatibilityContractError(
                "required obligations without a consumer must stay undispositioned "
                "or unsupported"
            )

    def nested_payload(
        self,
    ) -> (
        ImportEffect
        | RegistryObligation
        | DecoratorObligation
        | ResourceObligation
        | SerializationObligation
        | IntrospectionObligation
        | CliPluginObligation
        | PatchTargetObligation
    ):
        payloads = self._payload_map()
        present = [value for value in payloads.values() if value is not None]
        return present[0]

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PUBLIC_COMPATIBILITY_OBLIGATION_SCHEMA,
            "interface": PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "subject_module": self.subject_module,
            "subject_qualname": self.subject_qualname,
            "required": self.required,
            "support_status": self.support_status,
            "disposition": self.disposition,
            "evidence_class": self.evidence_class,
            "consumer_id": self.consumer_id,
            "import_effect": (
                None
                if self.import_effect is None
                else self.import_effect.identity_payload()
            ),
            "registry": (
                None if self.registry is None else self.registry.identity_payload()
            ),
            "decorator": (
                None if self.decorator is None else self.decorator.identity_payload()
            ),
            "resource": (
                None if self.resource is None else self.resource.identity_payload()
            ),
            "serialization": (
                None
                if self.serialization is None
                else self.serialization.identity_payload()
            ),
            "introspection": (
                None
                if self.introspection is None
                else self.introspection.identity_payload()
            ),
            "cli_plugin": (
                None
                if self.cli_plugin is None
                else self.cli_plugin.identity_payload()
            ),
            "patch_target": (
                None
                if self.patch_target is None
                else self.patch_target.identity_payload()
            ),
        }

    @property
    def obligation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PUBLIC_COMPATIBILITY_OBLIGATION_SCHEMA,
            "interface": PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "subject_module": self.subject_module,
            "subject_qualname": self.subject_qualname,
            "required": self.required,
            "support_status": self.support_status,
            "disposition": self.disposition,
            "evidence_class": self.evidence_class,
            "consumer_id": self.consumer_id,
            "import_effect": _nested_dict(self.import_effect),
            "registry": _nested_dict(self.registry),
            "decorator": _nested_dict(self.decorator),
            "resource": _nested_dict(self.resource),
            "serialization": _nested_dict(self.serialization),
            "introspection": _nested_dict(self.introspection),
            "cli_plugin": _nested_dict(self.cli_plugin),
            "patch_target": _nested_dict(self.patch_target),
            "obligation_cid": self.obligation_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PublicCompatibilityObligation":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("obligation_cid")
        if payload.pop("schema") != PUBLIC_COMPATIBILITY_OBLIGATION_SCHEMA:
            raise CompatibilityContractError(
                "unsupported PublicCompatibilityObligation schema"
            )
        if payload.pop("interface") != PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE:
            raise CompatibilityContractError(
                "unsupported PublicCompatibilityObligation interface"
            )
        result = cls(**payload)
        _verify_cid(
            claimed,
            result.obligation_cid,
            "PublicCompatibilityObligation obligation_cid",
        )
        return result


@dataclass(frozen=True, slots=True)
class CompatibilityTerminal:
    """Typed compatibility evaluation result. Never self-authorizes completion."""

    kind: CompatibilityTerminalKind | str
    reason: str
    required: bool
    obligation_ids: Sequence[str] = ()
    block_ids: Sequence[str] = ()

    interface: ClassVar[str] = COMPATIBILITY_TERMINAL_INTERFACE
    schema: ClassVar[str] = COMPATIBILITY_TERMINAL_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "kind",
            "reason",
            "required",
            "obligation_ids",
            "block_ids",
            "success",
            "authorizes_completion",
            "terminal_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, CompatibilityTerminalKind, "kind")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(
            self,
            "obligation_ids",
            _unique_sorted(self.obligation_ids, "obligation_id"),
        )
        object.__setattr__(
            self, "block_ids", _unique_sorted(self.block_ids, "block_id")
        )
        if self.kind == CompatibilityTerminalKind.ADMITTED.value:
            if not self.obligation_ids and not self.block_ids:
                raise CompatibilityContractError(
                    "admitted terminals must name at least one subject"
                )
        if self.kind == CompatibilityTerminalKind.UNSUPPORTED_REQUIRED.value:
            if not self.required:
                raise CompatibilityContractError(
                    "unsupported_required terminals must be required"
                )
        if (
            self.kind != CompatibilityTerminalKind.ADMITTED.value
            and self.success
        ):
            raise CompatibilityContractError(
                "non-admitted terminals cannot report success"
            )

    @property
    def success(self) -> bool:
        return self.kind == CompatibilityTerminalKind.ADMITTED.value

    @property
    def authorizes_completion(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COMPATIBILITY_TERMINAL_SCHEMA,
            "interface": COMPATIBILITY_TERMINAL_INTERFACE,
            "kind": self.kind,
            "reason": self.reason,
            "required": self.required,
            "obligation_ids": list(self.obligation_ids),
            "block_ids": list(self.block_ids),
        }

    @property
    def terminal_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["success"] = self.success
        payload["authorizes_completion"] = False
        payload["terminal_cid"] = self.terminal_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompatibilityTerminal":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("terminal_cid")
        claimed_success = payload.pop("success")
        claimed_completion = payload.pop("authorizes_completion")
        if payload.pop("schema") != COMPATIBILITY_TERMINAL_SCHEMA:
            raise CompatibilityContractError("unsupported CompatibilityTerminal schema")
        if payload.pop("interface") != COMPATIBILITY_TERMINAL_INTERFACE:
            raise CompatibilityContractError(
                "unsupported CompatibilityTerminal interface"
            )
        result = cls(**payload)
        if claimed_success is not result.success:
            raise CompatibilityContractError("CompatibilityTerminal success does not match kind")
        if claimed_completion is not False:
            raise CompatibilityContractError(
                "CompatibilityTerminal cannot authorize completion"
            )
        _verify_cid(claimed, result.terminal_cid, "CompatibilityTerminal terminal_cid")
        return result


def _evaluate_statuses(
    *,
    subjects: Sequence[tuple[str, bool, str]],
    obligation_ids: Sequence[str],
    block_ids: Sequence[str],
    admitted_reason: str,
) -> CompatibilityTerminal:
    required_unsupported = [
        subject_id
        for subject_id, required, status in subjects
        if required and status == SupportStatus.UNSUPPORTED.value
    ]
    required_unknown = [
        subject_id
        for subject_id, required, status in subjects
        if required and status == SupportStatus.UNKNOWN.value
    ]
    optional_unsupported = [
        subject_id
        for subject_id, required, status in subjects
        if not required and status == SupportStatus.UNSUPPORTED.value
    ]
    optional_unknown = [
        subject_id
        for subject_id, required, status in subjects
        if not required and status == SupportStatus.UNKNOWN.value
    ]
    if required_unsupported:
        return CompatibilityTerminal(
            kind=CompatibilityTerminalKind.UNSUPPORTED_REQUIRED,
            reason="required compatibility obligation is unsupported",
            required=True,
            obligation_ids=[
                item for item in obligation_ids if item in set(required_unsupported)
            ]
            or obligation_ids,
            block_ids=[item for item in block_ids if item in set(required_unsupported)]
            or (() if obligation_ids else block_ids),
        )
    if required_unknown:
        return CompatibilityTerminal(
            kind=CompatibilityTerminalKind.UNKNOWN_REQUIRED,
            reason="required compatibility obligation is unknown",
            required=True,
            obligation_ids=[
                item for item in obligation_ids if item in set(required_unknown)
            ]
            or obligation_ids,
            block_ids=[item for item in block_ids if item in set(required_unknown)]
            or (() if obligation_ids else block_ids),
        )
    if optional_unknown:
        return CompatibilityTerminal(
            kind=CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
            reason="optional compatibility obligation remains unknown",
            required=False,
            obligation_ids=[
                item for item in obligation_ids if item in set(optional_unknown)
            ]
            or obligation_ids,
            block_ids=[item for item in block_ids if item in set(optional_unknown)]
            or (() if obligation_ids else block_ids),
        )
    if optional_unsupported:
        return CompatibilityTerminal(
            kind=CompatibilityTerminalKind.UNSUPPORTED_OPTIONAL,
            reason="optional compatibility obligation is unsupported",
            required=False,
            obligation_ids=[
                item for item in obligation_ids if item in set(optional_unsupported)
            ]
            or obligation_ids,
            block_ids=[item for item in block_ids if item in set(optional_unsupported)]
            or (() if obligation_ids else block_ids),
        )
    return CompatibilityTerminal(
        kind=CompatibilityTerminalKind.ADMITTED,
        reason=admitted_reason,
        required=any(required for _, required, _ in subjects),
        obligation_ids=obligation_ids,
        block_ids=block_ids,
    )


def evaluate_initialization_block(block: InitializationBlock) -> CompatibilityTerminal:
    """Evaluate one initialization block. Unsupported required is never success."""

    subjects: list[tuple[str, bool, str]] = [
        (block.block_id, block.required, block.support_status)
    ]
    for nested in block.nested_obligations():
        nested_id = f"{block.block_id}:{nested.record_cid}"
        subjects.append((nested_id, nested.required, nested.support_status))
    return _evaluate_statuses(
        subjects=subjects,
        obligation_ids=(),
        block_ids=(block.block_id,),
        admitted_reason="initialization block obligations are supported",
    )


def evaluate_public_compatibility(
    obligation: PublicCompatibilityObligation,
) -> CompatibilityTerminal:
    """Evaluate one public compatibility obligation."""

    if (
        obligation.required
        and obligation.consumer_id is None
        and obligation.disposition == CompatibilityDisposition.UNDISPOSITIONED.value
        and obligation.support_status != SupportStatus.UNSUPPORTED.value
    ):
        return CompatibilityTerminal(
            kind=CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
            reason="required obligation has no dispositioned consumer",
            required=True,
            obligation_ids=(obligation.obligation_id,),
        )
    nested = obligation.nested_payload()
    subjects = [
        (obligation.obligation_id, obligation.required, obligation.support_status),
        (
            f"{obligation.obligation_id}:payload",
            nested.required,
            nested.support_status,
        ),
    ]
    return _evaluate_statuses(
        subjects=subjects,
        obligation_ids=(obligation.obligation_id,),
        block_ids=(),
        admitted_reason="public compatibility obligation is supported",
    )


def _merge_terminals(
    terminals: Sequence[CompatibilityTerminal],
) -> CompatibilityTerminal:
    if not terminals:
        raise CompatibilityContractError("compatibility evaluation requires subjects")
    by_kind = {item.kind: item for item in terminals}
    for kind in _TERMINAL_PRECEDENCE:
        if kind.value in by_kind and kind is not CompatibilityTerminalKind.ADMITTED:
            matching = [item for item in terminals if item.kind == kind.value]
            obligation_ids = _unique_sorted(
                (oid for item in matching for oid in item.obligation_ids),
                "obligation_id",
            )
            block_ids = _unique_sorted(
                (bid for item in matching for bid in item.block_ids),
                "block_id",
            )
            return CompatibilityTerminal(
                kind=kind,
                reason=matching[0].reason,
                required=any(item.required for item in matching),
                obligation_ids=obligation_ids,
                block_ids=block_ids,
            )
    admitted = [item for item in terminals if item.kind == CompatibilityTerminalKind.ADMITTED.value]
    return CompatibilityTerminal(
        kind=CompatibilityTerminalKind.ADMITTED,
        reason="all declared compatibility obligations are supported",
        required=any(item.required for item in admitted),
        obligation_ids=_unique_sorted(
            (oid for item in admitted for oid in item.obligation_ids),
            "obligation_id",
        ),
        block_ids=_unique_sorted(
            (bid for item in admitted for bid in item.block_ids),
            "block_id",
        ),
    )


def evaluate_compatibility(
    *,
    blocks: Sequence[InitializationBlock] = (),
    obligations: Sequence[PublicCompatibilityObligation] = (),
) -> CompatibilityTerminal:
    """Evaluate a closed set of initialization and public compatibility contracts.

    An admitted result is a contract evaluation only. It does not authorize
    completion, merge, or an accepted transition.
    """

    block_ids = [block.block_id for block in blocks]
    if len(block_ids) != len(set(block_ids)):
        raise CompatibilityContractError("initialization blocks must have unique block_id")
    obligation_ids = [item.obligation_id for item in obligations]
    if len(obligation_ids) != len(set(obligation_ids)):
        raise CompatibilityContractError(
            "public compatibility obligations must have unique obligation_id"
        )
    known_blocks = set(block_ids)
    for block in blocks:
        unknown = [item for item in block.happens_before if item not in known_blocks]
        if unknown:
            return CompatibilityTerminal(
                kind=CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
                reason="happens_before predecessor is not in the evaluated set",
                required=True,
                block_ids=tuple(unknown),
            )
    terminals = [evaluate_initialization_block(block) for block in blocks]
    terminals.extend(evaluate_public_compatibility(item) for item in obligations)
    return _merge_terminals(terminals)


def assert_not_competing_capsule_family() -> None:
    """Refuse SPAR capsule-family type names; those belong to SPAR-002."""

    defined = {
        name
        for name, value in globals().items()
        if isinstance(value, type) and name in _FORBIDDEN_CAPSULE_TYPE_NAMES
    }
    if defined:
        raise CompatibilityContractError(
            f"compatibility contracts must not define capsule-family types: {sorted(defined)}"
        )


assert_not_competing_capsule_family()
validate_structured_value(
    {
        "schema": COMPATIBILITY_CONTRACTS_SCHEMA,
        "task_id": TASK_ID,
        "authority_owner": AUTHORITY_OWNER,
    }
)

__all__ = (
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "COMPATIBILITY_CAN_AUTHORIZE_COMPLETION",
    "COMPATIBILITY_CAN_AUTHORIZE_TRANSITION",
    "COMPATIBILITY_CONTRACTS_SCHEMA",
    "CliPluginObligation",
    "CompatibilityContractError",
    "CompatibilityDisposition",
    "CompatibilityKind",
    "CompatibilityTerminal",
    "CompatibilityTerminalKind",
    "DecoratorObligation",
    "EvidenceClass",
    "FIRST_CLASS_OBLIGATION_KINDS",
    "IDENTITY_EXCLUDED_FIELDS",
    "INITIALIZATION_BLOCK_INTERFACE",
    "INITIALIZATION_BLOCK_SCHEMA",
    "ImportEffect",
    "InitializationBlock",
    "IntrospectionObligation",
    "KIND_FAMILY",
    "PUBLIC_COMPATIBILITY_KINDS",
    "PUBLIC_COMPATIBILITY_OBLIGATION_INTERFACE",
    "PUBLIC_COMPATIBILITY_OBLIGATION_SCHEMA",
    "PatchTargetObligation",
    "PublicCompatibilityObligation",
    "RegistryObligation",
    "ResourceObligation",
    "SerializationObligation",
    "SupportStatus",
    "TASK_ID",
    "evaluate_compatibility",
    "evaluate_initialization_block",
    "evaluate_public_compatibility",
    "family_for_kind",
)
