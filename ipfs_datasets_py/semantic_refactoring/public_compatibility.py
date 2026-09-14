"""SPAR-011 public API and compatibility inventory.

Inventories every declared import/API/binding/serialization/introspection/
CLI/plugin/registration/documentation/patch obligation and dispositions each
consumer.  The original module remains a compatibility façade until every
consumer is dispositioned.

This module extends datasets formal semantic authority with
``PublicCompatibilityInventory@1``.  It reuses SPAR-004 obligation contracts
and does not create a competing task, graph, identity, VFS, proof, context,
scheduler, vector, merge, or state authority.

Unsupported required behavior is a typed terminal and is never success.
Observational metadata is excluded from identity.
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
from ipfs_datasets_py.semantic_refactoring.compatibility import (
    CompatibilityDisposition,
    CompatibilityKind,
    CompatibilityTerminal,
    CompatibilityTerminalKind,
    EvidenceClass,
    PUBLIC_COMPATIBILITY_KINDS,
    PublicCompatibilityObligation,
    SupportStatus,
    evaluate_compatibility,
    family_for_kind,
)


TASK_ID: Final[str] = "SPAR-011"
GOAL_ID: Final[str] = "SPAR-G022"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"

PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.public-compatibility-inventory@1"
)
COMPATIBILITY_CONSUMER_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.compatibility-consumer@1"
)
COMPATIBILITY_GRAPH_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.compatibility-graph-edge@1"
)
SUBJECT_FACADE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.subject-facade-record@1"
)

PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE: Final[str] = (
    "PublicCompatibilityInventory@1"
)
COMPATIBILITY_CONSUMER_INTERFACE: Final[str] = "CompatibilityConsumer@1"
COMPATIBILITY_GRAPH_EDGE_INTERFACE: Final[str] = "CompatibilityGraphEdge@1"
SUBJECT_FACADE_RECORD_INTERFACE: Final[str] = "SubjectFacadeRecord@1"

INVENTORY_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
INVENTORY_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
INVENTORY_CAN_CREATE_AUTHORITY: Final[bool] = False
INVENTORY_CAN_RETIRE_FACADE: Final[bool] = False
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

_TERMINAL_PRECEDENCE: Final[tuple[CompatibilityTerminalKind, ...]] = (
    CompatibilityTerminalKind.CONFLICT,
    CompatibilityTerminalKind.UNSUPPORTED_REQUIRED,
    CompatibilityTerminalKind.UNKNOWN_REQUIRED,
    CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
    CompatibilityTerminalKind.UNSUPPORTED_OPTIONAL,
    CompatibilityTerminalKind.ADMITTED,
)

DISPOSITIONED: Final[frozenset[str]] = frozenset(
    {
        CompatibilityDisposition.PRESERVE.value,
        CompatibilityDisposition.MIGRATE.value,
        CompatibilityDisposition.FACADE.value,
        CompatibilityDisposition.EXPLICIT_INCOMPATIBILITY.value,
        CompatibilityDisposition.UNSUPPORTED.value,
    }
)


class CompatibilityInventoryError(ValueError):
    """Fail-closed violation of a SPAR-011 public compatibility inventory."""


class ConsumerSurface(str, Enum):
    """Closed SPAR-011 public compatibility surfaces."""

    IMPORT = "import"
    API = "api"
    BINDING = "binding"
    SERIALIZATION = "serialization"
    INTROSPECTION = "introspection"
    CLI = "cli"
    PLUGIN = "plugin"
    REGISTRATION = "registration"
    DOCUMENTATION = "documentation"
    PATCH = "patch"


class ConsumerRole(str, Enum):
    """First-class consumer roles. Tests and proofs stay explicit."""

    MODULE = "module"
    TEST = "test"
    PROOF = "proof"
    CLI = "cli"
    PLUGIN = "plugin"
    DOCUMENTATION = "documentation"
    PATCH = "patch"
    EXTERNAL = "external"


DECLARED_CONSUMER_SURFACES: Final[frozenset[str]] = frozenset(
    surface.value for surface in ConsumerSurface
)

KIND_SURFACE: Final[Mapping[CompatibilityKind, ConsumerSurface]] = {
    CompatibilityKind.IMPORT_PATH: ConsumerSurface.IMPORT,
    CompatibilityKind.IMPORT_EFFECT: ConsumerSurface.IMPORT,
    CompatibilityKind.IMPORT_EAGERNESS: ConsumerSurface.IMPORT,
    CompatibilityKind.IMPORT_ORDER: ConsumerSurface.IMPORT,
    CompatibilityKind.STAR_EXPORT: ConsumerSurface.IMPORT,
    CompatibilityKind.MODULE_ATTRIBUTE: ConsumerSurface.API,
    CompatibilityKind.SIGNATURE: ConsumerSurface.API,
    CompatibilityKind.ANNOTATION: ConsumerSurface.API,
    CompatibilityKind.DEFAULT: ConsumerSurface.API,
    CompatibilityKind.EXCEPTION: ConsumerSurface.API,
    CompatibilityKind.CONFIGURATION: ConsumerSurface.API,
    CompatibilityKind.MODULE_NAME: ConsumerSurface.BINDING,
    CompatibilityKind.QUALNAME: ConsumerSurface.BINDING,
    CompatibilityKind.PICKLE: ConsumerSurface.SERIALIZATION,
    CompatibilityKind.SERIALIZATION: ConsumerSurface.SERIALIZATION,
    CompatibilityKind.INTROSPECTION: ConsumerSurface.INTROSPECTION,
    CompatibilityKind.TRACEBACK: ConsumerSurface.INTROSPECTION,
    CompatibilityKind.CLI: ConsumerSurface.CLI,
    CompatibilityKind.PLUGIN: ConsumerSurface.PLUGIN,
    CompatibilityKind.REGISTRY: ConsumerSurface.REGISTRATION,
    CompatibilityKind.DECORATOR: ConsumerSurface.REGISTRATION,
    CompatibilityKind.RESOURCE: ConsumerSurface.REGISTRATION,
    CompatibilityKind.RESOURCE_LIFETIME: ConsumerSurface.REGISTRATION,
    CompatibilityKind.DOCUMENTATION: ConsumerSurface.DOCUMENTATION,
    CompatibilityKind.PATCH_TARGET: ConsumerSurface.PATCH,
}


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise CompatibilityInventoryError(f"{name} must be a string")
    if value != value.strip():
        raise CompatibilityInventoryError(f"{name} must be trimmed text")
    if not empty and not value:
        raise CompatibilityInventoryError(f"{name} must be a nonempty string")
    if any(ord(char) < 32 for char in value):
        raise CompatibilityInventoryError(f"{name} contains control characters")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise CompatibilityInventoryError(f"{name} must be a valid CID") from exc


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise CompatibilityInventoryError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CompatibilityInventoryError(f"{name} must be a boolean")
    return value


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in text
    ):
        raise CompatibilityInventoryError(
            "tree_id must be a lowercase hex Git tree identity"
        )
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise CompatibilityInventoryError(f"{name} must be an object")
    extra = set(data) - fields
    missing = fields - set(data)
    if extra & IDENTITY_EXCLUDED_FIELDS:
        raise CompatibilityInventoryError(
            f"{name} identity excludes observational fields: "
            f"{sorted(extra & IDENTITY_EXCLUDED_FIELDS)}"
        )
    if extra:
        raise CompatibilityInventoryError(f"unknown {name} field: {sorted(extra)}")
    if missing:
        raise CompatibilityInventoryError(f"missing {name} field: {sorted(missing)}")
    return dict(data)


def _unique_sorted(values: Iterable[str], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) != len(set(ordered)):
        raise CompatibilityInventoryError(f"{name} must not contain duplicates")
    return ordered


def _sorted_set(values: Iterable[str], name: str) -> tuple[str, ...]:
    return tuple(sorted(set(_text(item, name) for item in values)))


def _reject_excluded(payload: Mapping[str, Any], name: str) -> None:
    present = IDENTITY_EXCLUDED_FIELDS & set(payload)
    if present:
        raise CompatibilityInventoryError(
            f"{name} identity excludes observational fields: {sorted(present)}"
        )


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise CompatibilityInventoryError(f"{name} does not verify")


def _coerce_obligation(
    value: PublicCompatibilityObligation | Mapping[str, Any],
) -> PublicCompatibilityObligation:
    if isinstance(value, PublicCompatibilityObligation):
        return value
    if isinstance(value, Mapping):
        try:
            return PublicCompatibilityObligation.from_dict(value)
        except CompatibilityInventoryError:
            raise
        except Exception as exc:
            raise CompatibilityInventoryError(
                "obligation must be a PublicCompatibilityObligation"
            ) from exc
    raise CompatibilityInventoryError(
        "obligation must be a PublicCompatibilityObligation"
    )


def surface_for_kind(kind: CompatibilityKind | str) -> ConsumerSurface:
    """Map one SPAR-004 compatibility kind onto a SPAR-011 consumer surface."""

    resolved = (
        kind if isinstance(kind, CompatibilityKind) else CompatibilityKind(kind)
    )
    try:
        return KIND_SURFACE[resolved]
    except KeyError as exc:
        raise CompatibilityInventoryError(
            f"kind has no consumer surface: {kind!r}"
        ) from exc


def _disposition_is_complete(disposition: str) -> bool:
    return disposition in DISPOSITIONED


@dataclass(frozen=True, slots=True)
class CompatibilityConsumer:
    """First-class consumer of one or more public compatibility obligations."""

    consumer_id: str
    module_name: str
    role: ConsumerRole | str = ConsumerRole.MODULE
    required: bool = True
    evidence_class: EvidenceClass | str = EvidenceClass.EXACT_STATIC_FACT

    interface: ClassVar[str] = COMPATIBILITY_CONSUMER_INTERFACE
    schema: ClassVar[str] = COMPATIBILITY_CONSUMER_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "consumer_id",
            "module_name",
            "role",
            "required",
            "evidence_class",
            "consumer_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "consumer_id", _text(self.consumer_id, "consumer_id")
        )
        object.__setattr__(
            self, "module_name", _text(self.module_name, "module_name")
        )
        object.__setattr__(self, "role", _enum(self.role, ConsumerRole, "role"))
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(
            self,
            "evidence_class",
            _enum(self.evidence_class, EvidenceClass, "evidence_class"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COMPATIBILITY_CONSUMER_SCHEMA,
            "interface": COMPATIBILITY_CONSUMER_INTERFACE,
            "consumer_id": self.consumer_id,
            "module_name": self.module_name,
            "role": self.role,
            "required": self.required,
            "evidence_class": self.evidence_class,
        }

    @property
    def consumer_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["consumer_cid"] = self.consumer_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompatibilityConsumer":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("consumer_cid")
        if payload.pop("schema") != COMPATIBILITY_CONSUMER_SCHEMA:
            raise CompatibilityInventoryError(
                "unsupported CompatibilityConsumer schema"
            )
        if payload.pop("interface") != COMPATIBILITY_CONSUMER_INTERFACE:
            raise CompatibilityInventoryError(
                "unsupported CompatibilityConsumer interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.consumer_cid, "CompatibilityConsumer consumer_cid")
        return result

    @classmethod
    def from_obligation(
        cls, obligation: PublicCompatibilityObligation
    ) -> "CompatibilityConsumer":
        if obligation.consumer_id is None:
            raise CompatibilityInventoryError(
                "cannot synthesize a consumer from an obligation without consumer_id"
            )
        return cls(
            consumer_id=obligation.consumer_id,
            module_name=obligation.consumer_id,
            role=_role_for_obligation(obligation),
            required=obligation.required,
            evidence_class=obligation.evidence_class,
        )


def _role_for_obligation(obligation: PublicCompatibilityObligation) -> ConsumerRole:
    kind = CompatibilityKind(obligation.kind)
    surface = surface_for_kind(kind)
    consumer_id = obligation.consumer_id or ""
    if consumer_id.startswith("test") or ".tests." in f".{consumer_id}.":
        return ConsumerRole.TEST
    if consumer_id.startswith("proof") or ".proofs." in f".{consumer_id}.":
        return ConsumerRole.PROOF
    if surface is ConsumerSurface.CLI:
        return ConsumerRole.CLI
    if surface is ConsumerSurface.PLUGIN:
        return ConsumerRole.PLUGIN
    if surface is ConsumerSurface.DOCUMENTATION:
        return ConsumerRole.DOCUMENTATION
    if surface is ConsumerSurface.PATCH:
        return ConsumerRole.PATCH
    return ConsumerRole.MODULE


def _coerce_consumer(
    value: CompatibilityConsumer | Mapping[str, Any],
) -> CompatibilityConsumer:
    if isinstance(value, CompatibilityConsumer):
        return value
    if isinstance(value, Mapping):
        if "consumer_cid" in value:
            return CompatibilityConsumer.from_dict(value)
        return CompatibilityConsumer(**dict(value))
    raise CompatibilityInventoryError("consumer must be a CompatibilityConsumer")


@dataclass(frozen=True, slots=True)
class CompatibilityGraphEdge:
    """Directed obligation-to-consumer edge in the compatibility graph."""

    obligation_id: str
    consumer_id: str
    subject_id: str
    kind: CompatibilityKind | str
    surface: ConsumerSurface | str
    disposition: CompatibilityDisposition | str
    required: bool
    family: str

    interface: ClassVar[str] = COMPATIBILITY_GRAPH_EDGE_INTERFACE
    schema: ClassVar[str] = COMPATIBILITY_GRAPH_EDGE_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "obligation_id",
            "consumer_id",
            "subject_id",
            "kind",
            "surface",
            "disposition",
            "required",
            "family",
            "edge_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "consumer_id", _text(self.consumer_id, "consumer_id")
        )
        object.__setattr__(self, "subject_id", _text(self.subject_id, "subject_id"))
        kind = _enum(self.kind, CompatibilityKind, "kind")
        object.__setattr__(self, "kind", kind)
        surface = _enum(self.surface, ConsumerSurface, "surface")
        expected = surface_for_kind(kind).value
        if surface != expected:
            raise CompatibilityInventoryError(
                f"surface {surface} does not match kind {kind}"
            )
        object.__setattr__(self, "surface", surface)
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, CompatibilityDisposition, "disposition"),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))
        family = family_for_kind(kind).value
        declared = _text(self.family, "family")
        if declared != family:
            raise CompatibilityInventoryError(
                f"family {declared} does not match kind {kind}"
            )
        object.__setattr__(self, "family", family)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COMPATIBILITY_GRAPH_EDGE_SCHEMA,
            "interface": COMPATIBILITY_GRAPH_EDGE_INTERFACE,
            "obligation_id": self.obligation_id,
            "consumer_id": self.consumer_id,
            "subject_id": self.subject_id,
            "kind": self.kind,
            "surface": self.surface,
            "disposition": self.disposition,
            "required": self.required,
            "family": self.family,
        }

    @property
    def edge_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def dispositioned(self) -> bool:
        return _disposition_is_complete(self.disposition)

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["edge_cid"] = self.edge_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompatibilityGraphEdge":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("edge_cid")
        if payload.pop("schema") != COMPATIBILITY_GRAPH_EDGE_SCHEMA:
            raise CompatibilityInventoryError(
                "unsupported CompatibilityGraphEdge schema"
            )
        if payload.pop("interface") != COMPATIBILITY_GRAPH_EDGE_INTERFACE:
            raise CompatibilityInventoryError(
                "unsupported CompatibilityGraphEdge interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.edge_cid, "CompatibilityGraphEdge edge_cid")
        return result

    @classmethod
    def from_obligation(
        cls, obligation: PublicCompatibilityObligation
    ) -> "CompatibilityGraphEdge":
        if obligation.consumer_id is None:
            raise CompatibilityInventoryError(
                "graph edges require a dispositioned consumer_id"
            )
        kind = CompatibilityKind(obligation.kind)
        return cls(
            obligation_id=obligation.obligation_id,
            consumer_id=obligation.consumer_id,
            subject_id=obligation.subject_id,
            kind=kind,
            surface=surface_for_kind(kind),
            disposition=obligation.disposition,
            required=obligation.required,
            family=family_for_kind(kind).value,
        )


@dataclass(frozen=True, slots=True)
class SubjectFacadeRecord:
    """Façade obligation for one original subject module.

    The original module remains a compatibility façade until every consumer
    of the subject is dispositioned.  Planned ``facade`` dispositions are
    not a blocking requirement once consumers are dispositioned.
    """

    subject_id: str
    subject_module: str
    facade_required: bool
    consumer_ids: Sequence[str] = ()
    undispositioned_consumer_ids: Sequence[str] = ()
    dispositions: Sequence[str] = ()

    interface: ClassVar[str] = SUBJECT_FACADE_RECORD_INTERFACE
    schema: ClassVar[str] = SUBJECT_FACADE_RECORD_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "subject_id",
            "subject_module",
            "facade_required",
            "consumer_ids",
            "undispositioned_consumer_ids",
            "dispositions",
            "facade_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _text(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "subject_module", _text(self.subject_module, "subject_module")
        )
        object.__setattr__(
            self, "facade_required", _bool(self.facade_required, "facade_required")
        )
        consumers = _unique_sorted(self.consumer_ids, "consumer_id")
        undispositioned = _unique_sorted(
            self.undispositioned_consumer_ids, "undispositioned_consumer_id"
        )
        unknown = set(undispositioned) - set(consumers)
        if unknown:
            raise CompatibilityInventoryError(
                "undispositioned consumers must be listed as consumers"
            )
        object.__setattr__(self, "consumer_ids", consumers)
        object.__setattr__(self, "undispositioned_consumer_ids", undispositioned)
        dispositions = _unique_sorted(
            (
                _enum(item, CompatibilityDisposition, "disposition")
                for item in self.dispositions
            ),
            "disposition",
        )
        object.__setattr__(self, "dispositions", dispositions)
        expected = (
            CompatibilityDisposition.UNDISPOSITIONED.value in dispositions
        )
        if self.facade_required is not expected:
            raise CompatibilityInventoryError(
                "facade_required must match undispositioned consumers"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SUBJECT_FACADE_RECORD_SCHEMA,
            "interface": SUBJECT_FACADE_RECORD_INTERFACE,
            "subject_id": self.subject_id,
            "subject_module": self.subject_module,
            "facade_required": self.facade_required,
            "consumer_ids": list(self.consumer_ids),
            "undispositioned_consumer_ids": list(self.undispositioned_consumer_ids),
            "dispositions": list(self.dispositions),
        }

    @property
    def facade_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["facade_cid"] = self.facade_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubjectFacadeRecord":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("facade_cid")
        if payload.pop("schema") != SUBJECT_FACADE_RECORD_SCHEMA:
            raise CompatibilityInventoryError(
                "unsupported SubjectFacadeRecord schema"
            )
        if payload.pop("interface") != SUBJECT_FACADE_RECORD_INTERFACE:
            raise CompatibilityInventoryError(
                "unsupported SubjectFacadeRecord interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.facade_cid, "SubjectFacadeRecord facade_cid")
        return result


def _edges_from_obligations(
    obligations: Sequence[PublicCompatibilityObligation],
) -> tuple[CompatibilityGraphEdge, ...]:
    edges = [
        CompatibilityGraphEdge.from_obligation(item)
        for item in obligations
        if item.consumer_id is not None
    ]
    edges.sort(key=lambda item: (item.obligation_id, item.consumer_id, item.kind))
    cids = [item.edge_cid for item in edges]
    if len(cids) != len(set(cids)):
        raise CompatibilityInventoryError("compatibility graph edges must be unique")
    return tuple(edges)


def _facades_from_obligations(
    obligations: Sequence[PublicCompatibilityObligation],
) -> tuple[SubjectFacadeRecord, ...]:
    grouped: dict[str, list[PublicCompatibilityObligation]] = {}
    for item in obligations:
        grouped.setdefault(item.subject_id, []).append(item)
    records: list[SubjectFacadeRecord] = []
    for subject_id in sorted(grouped):
        members = grouped[subject_id]
        modules = {item.subject_module for item in members}
        if len(modules) != 1:
            raise CompatibilityInventoryError(
                f"subject {subject_id} has conflicting subject_module values"
            )
        consumers = tuple(
            sorted(
                {
                    item.consumer_id
                    for item in members
                    if item.consumer_id is not None
                }
            )
        )
        undispositioned = tuple(
            sorted(
                {
                    item.consumer_id
                    for item in members
                    if item.consumer_id is not None
                    and item.disposition
                    == CompatibilityDisposition.UNDISPOSITIONED.value
                }
            )
        )
        dispositions = tuple(sorted({item.disposition for item in members}))
        facade_required = (
            CompatibilityDisposition.UNDISPOSITIONED.value in dispositions
        )
        records.append(
            SubjectFacadeRecord(
                subject_id=subject_id,
                subject_module=next(iter(modules)),
                facade_required=facade_required,
                consumer_ids=consumers,
                undispositioned_consumer_ids=undispositioned,
                dispositions=dispositions,
            )
        )
    return tuple(records)


def _merge_terminals(
    terminals: Sequence[CompatibilityTerminal],
) -> CompatibilityTerminal:
    if not terminals:
        raise CompatibilityInventoryError("inventory evaluation requires subjects")
    by_kind = {item.kind: item for item in terminals}
    for kind in _TERMINAL_PRECEDENCE:
        if kind.value in by_kind and kind is not CompatibilityTerminalKind.ADMITTED:
            matching = [item for item in terminals if item.kind == kind.value]
            obligation_ids = _sorted_set(
                (oid for item in matching for oid in item.obligation_ids),
                "obligation_id",
            )
            block_ids = _sorted_set(
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
    admitted = [
        item
        for item in terminals
        if item.kind == CompatibilityTerminalKind.ADMITTED.value
    ]
    return CompatibilityTerminal(
        kind=CompatibilityTerminalKind.ADMITTED,
        reason="all declared public compatibility consumers are dispositioned",
        required=any(item.required for item in admitted),
        obligation_ids=_sorted_set(
            (oid for item in admitted for oid in item.obligation_ids),
            "obligation_id",
        ),
        block_ids=_sorted_set(
            (bid for item in admitted for bid in item.block_ids),
            "block_id",
        ),
    )


@dataclass(frozen=True, slots=True)
class PublicCompatibilityInventory:
    """Closed inventory of public compatibility obligations and consumers.

    Predicted SPAR-011 symbol: ``PublicCompatibilityInventory@1``.
    """

    tree_id: str
    source_cid: str
    obligations: Sequence[PublicCompatibilityObligation] = ()
    consumers: Sequence[CompatibilityConsumer] = ()

    interface: ClassVar[str] = PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE
    schema: ClassVar[str] = PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "tree_id",
            "source_cid",
            "obligations",
            "consumers",
            "edges",
            "facades",
            "covered_kinds",
            "covered_surfaces",
            "facade_required",
            "authorizes_completion",
            "authorizes_transition",
            "authorizes_facade_retirement",
            "inventory_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        obligations = tuple(_coerce_obligation(item) for item in self.obligations)
        obligation_ids = [item.obligation_id for item in obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise CompatibilityInventoryError(
                "public compatibility obligations must have unique obligation_id"
            )
        obligations = tuple(sorted(obligations, key=lambda item: item.obligation_id))
        object.__setattr__(self, "obligations", obligations)

        consumers = tuple(_coerce_consumer(item) for item in self.consumers)
        consumer_ids = [item.consumer_id for item in consumers]
        if len(consumer_ids) != len(set(consumer_ids)):
            raise CompatibilityInventoryError(
                "compatibility consumers must have unique consumer_id"
            )
        consumers = tuple(sorted(consumers, key=lambda item: item.consumer_id))
        object.__setattr__(self, "consumers", consumers)

        referenced = {
            item.consumer_id
            for item in obligations
            if item.consumer_id is not None
        }
        declared = {item.consumer_id for item in consumers}
        missing = referenced - declared
        extra = declared - referenced
        if missing:
            raise CompatibilityInventoryError(
                f"inventory is missing consumers: {sorted(missing)}"
            )
        if extra:
            raise CompatibilityInventoryError(
                f"inventory has orphan consumers: {sorted(extra)}"
            )

        coverage: dict[tuple[str, str, str | None], str] = {}
        for item in obligations:
            key = (item.subject_id, item.kind, item.consumer_id)
            previous = coverage.get(key)
            if previous is None:
                coverage[key] = item.disposition
                continue
            if previous != item.disposition:
                raise CompatibilityInventoryError(
                    "conflicting dispositions for the same subject, kind, and consumer"
                )
            raise CompatibilityInventoryError(
                "duplicate subject/kind/consumer coverage"
            )

        for consumer in consumers:
            matching = [
                item
                for item in obligations
                if item.consumer_id == consumer.consumer_id
            ]
            if consumer.required and not any(item.required for item in matching):
                raise CompatibilityInventoryError(
                    "required consumers must have a required obligation"
                )

    @property
    def edges(self) -> tuple[CompatibilityGraphEdge, ...]:
        return _edges_from_obligations(self.obligations)

    @property
    def facades(self) -> tuple[SubjectFacadeRecord, ...]:
        return _facades_from_obligations(self.obligations)

    @property
    def covered_kinds(self) -> tuple[str, ...]:
        return _sorted_set((item.kind for item in self.obligations), "kind")

    @property
    def covered_surfaces(self) -> tuple[str, ...]:
        return _sorted_set(
            (surface_for_kind(item.kind).value for item in self.obligations),
            "surface",
        )

    @property
    def facade_required(self) -> bool:
        return any(record.facade_required for record in self.facades)

    @property
    def undispositioned_obligations(
        self,
    ) -> tuple[PublicCompatibilityObligation, ...]:
        return tuple(
            item
            for item in self.obligations
            if item.disposition == CompatibilityDisposition.UNDISPOSITIONED.value
        )

    @property
    def authorizes_completion(self) -> bool:
        return False

    @property
    def authorizes_transition(self) -> bool:
        return False

    @property
    def authorizes_facade_retirement(self) -> bool:
        return False

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA,
            "interface": PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE,
            "tree_id": self.tree_id,
            "source_cid": self.source_cid,
            "obligations": [item.identity_payload() for item in self.obligations],
            "consumers": [item.identity_payload() for item in self.consumers],
        }

    @property
    def inventory_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA,
            "interface": PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE,
            "tree_id": self.tree_id,
            "source_cid": self.source_cid,
            "obligations": [item.to_dict() for item in self.obligations],
            "consumers": [item.to_dict() for item in self.consumers],
            "edges": [item.to_dict() for item in self.edges],
            "facades": [item.to_dict() for item in self.facades],
            "covered_kinds": list(self.covered_kinds),
            "covered_surfaces": list(self.covered_surfaces),
            "facade_required": self.facade_required,
            "authorizes_completion": False,
            "authorizes_transition": False,
            "authorizes_facade_retirement": False,
            "inventory_cid": self.inventory_cid,
        }

    def obligations_for_consumer(
        self, consumer_id: str
    ) -> tuple[PublicCompatibilityObligation, ...]:
        consumer = _text(consumer_id, "consumer_id")
        return tuple(
            item for item in self.obligations if item.consumer_id == consumer
        )

    def consumers_for_subject(
        self, subject_id: str
    ) -> tuple[CompatibilityConsumer, ...]:
        subject = _text(subject_id, "subject_id")
        ids = {
            item.consumer_id
            for item in self.obligations
            if item.subject_id == subject and item.consumer_id is not None
        }
        return tuple(item for item in self.consumers if item.consumer_id in ids)

    def evaluate(self) -> CompatibilityTerminal:
        """Evaluate the inventory. Unsupported required is never success."""

        if not self.obligations:
            return CompatibilityTerminal(
                kind=CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
                reason="inventory requires declared obligations",
                required=True,
            )
        terminals = [evaluate_compatibility(obligations=self.obligations)]
        undispositioned = self.undispositioned_obligations
        if undispositioned:
            terminals.append(
                CompatibilityTerminal(
                    kind=CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
                    reason="consumer is undispositioned",
                    required=any(item.required for item in undispositioned),
                    obligation_ids=tuple(
                        item.obligation_id for item in undispositioned
                    ),
                )
            )
        if self.facade_required:
            blocking = tuple(
                record.subject_id
                for record in self.facades
                if record.facade_required
            )
            terminals.append(
                CompatibilityTerminal(
                    kind=CompatibilityTerminalKind.INCOMPLETE_CONTRACT,
                    reason=(
                        "original module remains a compatibility façade until "
                        "every consumer is dispositioned"
                    ),
                    required=True,
                    obligation_ids=tuple(
                        item.obligation_id
                        for item in self.obligations
                        if item.subject_id in set(blocking)
                        and item.disposition
                        == CompatibilityDisposition.UNDISPOSITIONED.value
                    ),
                )
            )
        return _merge_terminals(terminals)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PublicCompatibilityInventory":
        _reject_excluded(data, cls.__name__)
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("inventory_cid")
        claimed_edges = payload.pop("edges")
        claimed_facades = payload.pop("facades")
        claimed_kinds = payload.pop("covered_kinds")
        claimed_surfaces = payload.pop("covered_surfaces")
        claimed_facade_required = payload.pop("facade_required")
        claimed_completion = payload.pop("authorizes_completion")
        claimed_transition = payload.pop("authorizes_transition")
        claimed_retirement = payload.pop("authorizes_facade_retirement")
        if payload.pop("schema") != PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA:
            raise CompatibilityInventoryError(
                "unsupported PublicCompatibilityInventory schema"
            )
        if payload.pop("interface") != PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE:
            raise CompatibilityInventoryError(
                "unsupported PublicCompatibilityInventory interface"
            )
        if claimed_completion is not False:
            raise CompatibilityInventoryError(
                "PublicCompatibilityInventory cannot authorize completion"
            )
        if claimed_transition is not False:
            raise CompatibilityInventoryError(
                "PublicCompatibilityInventory cannot authorize transition"
            )
        if claimed_retirement is not False:
            raise CompatibilityInventoryError(
                "PublicCompatibilityInventory cannot retire a façade"
            )
        result = cls(
            tree_id=payload["tree_id"],
            source_cid=payload["source_cid"],
            obligations=payload["obligations"],
            consumers=payload["consumers"],
        )
        _verify_cid(
            claimed,
            result.inventory_cid,
            "PublicCompatibilityInventory inventory_cid",
        )
        if claimed_edges != [item.to_dict() for item in result.edges]:
            raise CompatibilityInventoryError("inventory edges do not match obligations")
        if claimed_facades != [item.to_dict() for item in result.facades]:
            raise CompatibilityInventoryError(
                "inventory façades do not match obligations"
            )
        if tuple(claimed_kinds) != result.covered_kinds:
            raise CompatibilityInventoryError("covered_kinds does not match obligations")
        if tuple(claimed_surfaces) != result.covered_surfaces:
            raise CompatibilityInventoryError(
                "covered_surfaces does not match obligations"
            )
        if claimed_facade_required is not result.facade_required:
            raise CompatibilityInventoryError(
                "facade_required does not match undispositioned consumers"
            )
        return result


def synthesize_consumers(
    obligations: Sequence[PublicCompatibilityObligation],
) -> tuple[CompatibilityConsumer, ...]:
    """Derive unique consumer records from obligation consumer identifiers."""

    by_id: dict[str, CompatibilityConsumer] = {}
    for item in obligations:
        if item.consumer_id is None:
            continue
        candidate = CompatibilityConsumer.from_obligation(item)
        existing = by_id.get(candidate.consumer_id)
        if existing is None:
            by_id[candidate.consumer_id] = candidate
            continue
        if existing.module_name != candidate.module_name:
            raise CompatibilityInventoryError(
                "consumer module_name conflicts across obligations"
            )
        required = existing.required or candidate.required
        role = existing.role
        if existing.role != candidate.role:
            role = ConsumerRole.MODULE.value
        by_id[candidate.consumer_id] = CompatibilityConsumer(
            consumer_id=existing.consumer_id,
            module_name=existing.module_name,
            role=role,
            required=required,
            evidence_class=existing.evidence_class,
        )
    return tuple(sorted(by_id.values(), key=lambda item: item.consumer_id))


def inventory_public_compatibility(
    obligations: Sequence[PublicCompatibilityObligation | Mapping[str, Any]],
    *,
    tree_id: str,
    source_cid: str,
    consumers: Sequence[CompatibilityConsumer | Mapping[str, Any]] | None = None,
) -> PublicCompatibilityInventory:
    """Build ``PublicCompatibilityInventory@1`` and disposition each consumer."""

    bound = tuple(_coerce_obligation(item) for item in obligations)
    if consumers is None:
        bound_consumers: Sequence[CompatibilityConsumer] = synthesize_consumers(bound)
    else:
        bound_consumers = tuple(_coerce_consumer(item) for item in consumers)
    return PublicCompatibilityInventory(
        tree_id=tree_id,
        source_cid=source_cid,
        obligations=bound,
        consumers=bound_consumers,
    )


def assert_kind_surface_coverage() -> None:
    """Refuse a kind vocabulary that cannot be inventoried."""

    missing = set(CompatibilityKind) - set(KIND_SURFACE)
    extra = set(KIND_SURFACE) - set(CompatibilityKind)
    if missing or extra:
        raise CompatibilityInventoryError(
            f"KIND_SURFACE must cover CompatibilityKind exactly; "
            f"missing={sorted(item.value for item in missing)} "
            f"extra={sorted(item.value for item in extra)}"
        )
    surfaces = {surface.value for surface in KIND_SURFACE.values()}
    if surfaces != DECLARED_CONSUMER_SURFACES:
        raise CompatibilityInventoryError(
            "KIND_SURFACE must project onto every declared consumer surface"
        )
    if set(PUBLIC_COMPATIBILITY_KINDS) != {kind.value for kind in CompatibilityKind}:
        raise CompatibilityInventoryError(
            "SPAR-004 public compatibility kinds drifted from CompatibilityKind"
        )


def assert_not_competing_capsule_family() -> None:
    """Refuse SPAR capsule-family type names; those belong to SPAR-002."""

    defined = {
        name
        for name, value in globals().items()
        if isinstance(value, type) and name in _FORBIDDEN_CAPSULE_TYPE_NAMES
    }
    if defined:
        raise CompatibilityInventoryError(
            f"public compatibility inventory must not define capsule-family types: "
            f"{sorted(defined)}"
        )


assert_not_competing_capsule_family()
assert_kind_surface_coverage()
validate_structured_value(
    {
        "schema": PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA,
        "task_id": TASK_ID,
        "authority_owner": AUTHORITY_OWNER,
    }
)

__all__ = (
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "DECLARED_CONSUMER_SURFACES",
    "DISPOSITIONED",
    "DUCKLAKE_IS_AUTHORITY",
    "IDENTITY_EXCLUDED_FIELDS",
    "INVENTORY_CAN_AUTHORIZE_COMPLETION",
    "INVENTORY_CAN_AUTHORIZE_TRANSITION",
    "INVENTORY_CAN_CREATE_AUTHORITY",
    "INVENTORY_CAN_RETIRE_FACADE",
    "KIND_SURFACE",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "PUBLIC_COMPATIBILITY_INVENTORY_INTERFACE",
    "PUBLIC_COMPATIBILITY_INVENTORY_SCHEMA",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "WORKER_SELF_APPROVAL",
    "CompatibilityConsumer",
    "CompatibilityGraphEdge",
    "CompatibilityInventoryError",
    "ConsumerRole",
    "ConsumerSurface",
    "PublicCompatibilityInventory",
    "SubjectFacadeRecord",
    "inventory_public_compatibility",
    "surface_for_kind",
    "synthesize_consumers",
)
