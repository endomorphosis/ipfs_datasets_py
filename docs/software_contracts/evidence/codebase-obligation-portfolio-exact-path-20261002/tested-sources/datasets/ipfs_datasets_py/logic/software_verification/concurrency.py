"""Concurrency, rely-guarantee, session, and linearizability semantics.

``ConcurrencyIR@1`` represents threads/processes, environment versus component
steps, interference, atomic regions, rely/guarantee contracts, channels,
session protocols, and linearizability points.  The document is deliberately
free of TLA+, SMT-LIB, and model-checker syntax: it describes concurrent
semantics that later backends may project into.

Construction fails closed when environment and component steps are conflated,
when interference or fairness is left implicit, when session duality does not
validate, or when a bounded schedule claims unbounded refinement authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

CONCURRENCY_IR_INTERFACE: Final = "ConcurrencyIR@1"
CONCURRENCY_IR_SCHEMA_VERSION: Final = "concurrency-ir/v1"
CONCURRENCY_IR_IDENTITY_DOMAIN: Final = "logic.software-verification.concurrency"

COMPONENT_SCHEMA_VERSION: Final = "concurrent-component/v1"
STEP_SCHEMA_VERSION: Final = "concurrent-step/v1"
ATOMIC_REGION_SCHEMA_VERSION: Final = "atomic-region/v1"
INTERFERENCE_SCHEMA_VERSION: Final = "interference-assumption/v1"
FAIRNESS_SCHEMA_VERSION: Final = "concurrency-fairness/v1"
RELY_GUARANTEE_SCHEMA_VERSION: Final = "rely-guarantee-contract/v1"
CHANNEL_SCHEMA_VERSION: Final = "concurrent-channel/v1"
SESSION_ACTION_SCHEMA_VERSION: Final = "session-action/v1"
SESSION_PROTOCOL_SCHEMA_VERSION: Final = "session-protocol/v1"
LINEARIZABILITY_SCHEMA_VERSION: Final = "linearizability-point/v1"
BOUNDED_SCHEDULE_SCHEMA_VERSION: Final = "bounded-schedule/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class ConcurrencyValidationError(ValueError):
    """Raised when concurrent semantics are malformed or ambiguous."""


class ComponentKind(StrEnum):
    """How a concurrent component is scheduled."""

    THREAD = "thread"
    PROCESS = "process"


class StepOwner(StrEnum):
    """Who performs a step.

    Environment and component steps are distinct and never interchangeable.
    An environment step models interference from the rest of the system; a
    component step is performed by a declared thread or process.
    """

    COMPONENT = "component"
    ENVIRONMENT = "environment"


class InterferenceKind(StrEnum):
    """How the environment or another component may interfere."""

    READ = "read"
    WRITE = "write"
    BOTH = "both"
    INTERNAL = "internal"


class AtomicityKind(StrEnum):
    """Atomicity strength of a region."""

    NONE = "none"
    ATOMIC = "atomic"
    LOCKED = "locked"


class FairnessKind(StrEnum):
    """Fairness strength assumed over concurrent steps or components."""

    WEAK = "weak"
    STRONG = "strong"
    UNCONDITIONAL = "unconditional"


class ChannelMode(StrEnum):
    """Communication discipline of a concurrent channel."""

    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    BUFFERED = "buffered"


class SessionPolarity(StrEnum):
    """Local polarity of a session-protocol action."""

    SEND = "send"
    RECEIVE = "receive"
    INTERNAL = "internal"
    END = "end"


class SessionRole(StrEnum):
    """Endpoint role used for duality pairing."""

    CLIENT = "client"
    SERVER = "server"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise ConcurrencyValidationError(
            f"{label} must be a non-empty trimmed string without NUL bytes"
        )
    return value


def _optional_text(value: object, label: str) -> str:
    if value == "" or value is None:
        return ""
    return _text(value, label)


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise ConcurrencyValidationError(f"{label} must be a stable identifier")
    return result


def _ids(
    values: Sequence[str] | object,
    label: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ConcurrencyValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise ConcurrencyValidationError(f"{label} must not contain duplicates")
    return result if preserve_order else tuple(sorted(result))


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise ConcurrencyValidationError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConcurrencyValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise ConcurrencyValidationError(
            f"{label} must contain immutable JSON-compatible data: {error}"
        ) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConcurrencyValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConcurrencyValidationError(f"{label} must be a boolean")
    return value


def _non_bool_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConcurrencyValidationError(f"{label} must be an integer")
    return value


def _known(values: Sequence[str], known: set[str], label: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise ConcurrencyValidationError(f"{label} references unknown ids {missing}")


def _coerce_records(
    values: Sequence[object],
    cls: type[Any],
    label: str,
    id_field: str,
) -> tuple[Any, ...]:
    records = tuple(
        item if isinstance(item, cls) else cls.from_dict(_mapping(item, label))
        for item in values
    )
    return tuple(sorted(records, key=lambda item: getattr(item, id_field)))


def dual_polarity(polarity: SessionPolarity | str) -> SessionPolarity:
    """Return the dual polarity of a session action."""

    value = polarity if isinstance(polarity, SessionPolarity) else SessionPolarity(polarity)
    if value is SessionPolarity.SEND:
        return SessionPolarity.RECEIVE
    if value is SessionPolarity.RECEIVE:
        return SessionPolarity.SEND
    if value is SessionPolarity.INTERNAL:
        return SessionPolarity.INTERNAL
    if value is SessionPolarity.END:
        return SessionPolarity.END
    raise ConcurrencyValidationError(f"unsupported session polarity {value!r}")


def dual_role(role: SessionRole | str) -> SessionRole:
    """Return the dual endpoint role."""

    value = role if isinstance(role, SessionRole) else SessionRole(role)
    if value is SessionRole.CLIENT:
        return SessionRole.SERVER
    if value is SessionRole.SERVER:
        return SessionRole.CLIENT
    raise ConcurrencyValidationError(f"unsupported session role {value!r}")


@dataclass(frozen=True, slots=True)
class ConcurrentComponent:
    """A thread or process participating in concurrent composition."""

    component_id: str
    kind: ComponentKind | str
    name: str
    local_variable_ids: tuple[str, ...] = ()
    step_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = COMPONENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "component_id", _identifier(self.component_id, "component_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, ComponentKind, "kind"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self,
            "local_variable_ids",
            _ids(self.local_variable_ids, "local_variable_ids"),
        )
        object.__setattr__(self, "step_ids", _ids(self.step_ids, "step_ids"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != COMPONENT_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported component schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "component_id": self.component_id,
            "kind": self.kind.value,
            "local_variable_ids": list(self.local_variable_ids),
            "name": self.name,
            "schema_version": self.schema_version,
            "step_ids": list(self.step_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ConcurrentComponent:
        value = _mapping(value, "component")
        _reject_unknown(
            value,
            frozenset(
                {
                    "component_id",
                    "kind",
                    "name",
                    "local_variable_ids",
                    "step_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "component",
        )
        return cls(
            component_id=value.get("component_id", ""),
            kind=value.get("kind", ""),
            name=value.get("name", ""),
            local_variable_ids=tuple(value.get("local_variable_ids", ())),
            step_ids=tuple(value.get("step_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", COMPONENT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ConcurrentStep:
    """One atomic or non-atomic step owned by a component or the environment.

    Environment steps must set ``owner`` to :attr:`StepOwner.ENVIRONMENT` and
    leave ``component_id`` empty.  Component steps require a declared
    ``component_id``.  The two owners are never interchangeable.
    """

    step_id: str
    owner: StepOwner | str
    label: str
    guard_statement: str = "true"
    effect_statement: str = "skip"
    component_id: str = ""
    atomic_region_id: str = ""
    read_variable_ids: tuple[str, ...] = ()
    write_variable_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = STEP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _identifier(self.step_id, "step_id"))
        owner = _enum(self.owner, StepOwner, "owner")
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "label", _text(self.label, "label"))
        object.__setattr__(
            self, "guard_statement", _text(self.guard_statement, "guard_statement")
        )
        object.__setattr__(
            self, "effect_statement", _text(self.effect_statement, "effect_statement")
        )
        component_id = _optional_text(self.component_id, "component_id")
        if component_id:
            component_id = _identifier(component_id, "component_id")
        atomic_region_id = _optional_text(self.atomic_region_id, "atomic_region_id")
        if atomic_region_id:
            atomic_region_id = _identifier(atomic_region_id, "atomic_region_id")
        object.__setattr__(self, "component_id", component_id)
        object.__setattr__(self, "atomic_region_id", atomic_region_id)
        object.__setattr__(
            self, "read_variable_ids", _ids(self.read_variable_ids, "read_variable_ids")
        )
        object.__setattr__(
            self,
            "write_variable_ids",
            _ids(self.write_variable_ids, "write_variable_ids"),
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != STEP_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported step schema_version {self.schema_version!r}"
            )
        if owner is StepOwner.COMPONENT:
            if not component_id:
                raise ConcurrencyValidationError(
                    "component steps require a component_id; environment and "
                    "component steps are distinct"
                )
        elif owner is StepOwner.ENVIRONMENT:
            if component_id:
                raise ConcurrencyValidationError(
                    "environment steps must not claim a component_id; environment "
                    "and component steps are distinct"
                )
        else:  # pragma: no cover - enum exhaustiveness
            raise ConcurrencyValidationError(f"unsupported step owner {owner!r}")

    def is_environment(self) -> bool:
        return self.owner is StepOwner.ENVIRONMENT

    def is_component(self) -> bool:
        return self.owner is StepOwner.COMPONENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "atomic_region_id": self.atomic_region_id,
            "attributes": self.attributes.to_dict(),
            "component_id": self.component_id,
            "effect_statement": self.effect_statement,
            "guard_statement": self.guard_statement,
            "label": self.label,
            "owner": self.owner.value,
            "read_variable_ids": list(self.read_variable_ids),
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "write_variable_ids": list(self.write_variable_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ConcurrentStep:
        value = _mapping(value, "step")
        _reject_unknown(
            value,
            frozenset(
                {
                    "step_id",
                    "owner",
                    "label",
                    "guard_statement",
                    "effect_statement",
                    "component_id",
                    "atomic_region_id",
                    "read_variable_ids",
                    "write_variable_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "step",
        )
        return cls(
            step_id=value.get("step_id", ""),
            owner=value.get("owner", ""),
            label=value.get("label", ""),
            guard_statement=value.get("guard_statement", "true"),
            effect_statement=value.get("effect_statement", "skip"),
            component_id=value.get("component_id", ""),
            atomic_region_id=value.get("atomic_region_id", ""),
            read_variable_ids=tuple(value.get("read_variable_ids", ())),
            write_variable_ids=tuple(value.get("write_variable_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", STEP_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class AtomicRegion:
    """A region of component steps that execute without external interference."""

    region_id: str
    component_id: str
    step_ids: tuple[str, ...]
    atomicity: AtomicityKind | str = AtomicityKind.ATOMIC
    statement: str = "atomic"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = ATOMIC_REGION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_id", _identifier(self.region_id, "region_id"))
        object.__setattr__(
            self, "component_id", _identifier(self.component_id, "component_id")
        )
        step_ids = _ids(self.step_ids, "step_ids", preserve_order=True)
        if not step_ids:
            raise ConcurrencyValidationError("atomic region requires at least one step")
        object.__setattr__(self, "step_ids", step_ids)
        object.__setattr__(
            self, "atomicity", _enum(self.atomicity, AtomicityKind, "atomicity")
        )
        if self.atomicity is AtomicityKind.NONE:
            raise ConcurrencyValidationError(
                "atomic region atomicity must not be 'none'; use non-atomic steps"
            )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != ATOMIC_REGION_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported atomic-region schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "atomicity": self.atomicity.value,
            "attributes": self.attributes.to_dict(),
            "component_id": self.component_id,
            "region_id": self.region_id,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "step_ids": list(self.step_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AtomicRegion:
        value = _mapping(value, "atomic region")
        _reject_unknown(
            value,
            frozenset(
                {
                    "region_id",
                    "component_id",
                    "step_ids",
                    "atomicity",
                    "statement",
                    "attributes",
                    "schema_version",
                }
            ),
            "atomic region",
        )
        return cls(
            region_id=value.get("region_id", ""),
            component_id=value.get("component_id", ""),
            step_ids=tuple(value.get("step_ids", ())),
            atomicity=value.get("atomicity", AtomicityKind.ATOMIC),
            statement=value.get("statement", "atomic"),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", ATOMIC_REGION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class InterferenceAssumption:
    """An explicit assumption about how components or the environment interfere.

    Interference is never implicit: every concurrent composition that admits
    external mutation of shared state must declare at least one assumption.
    """

    interference_id: str
    kind: InterferenceKind | str
    statement: str
    subject_component_id: str
    interferer_component_id: str = ""
    interferer_is_environment: bool = False
    shared_variable_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = INTERFERENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "interference_id",
            _identifier(self.interference_id, "interference_id"),
        )
        object.__setattr__(self, "kind", _enum(self.kind, InterferenceKind, "kind"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self,
            "subject_component_id",
            _identifier(self.subject_component_id, "subject_component_id"),
        )
        interferer_is_environment = _bool(
            self.interferer_is_environment, "interferer_is_environment"
        )
        interferer_component_id = _optional_text(
            self.interferer_component_id, "interferer_component_id"
        )
        if interferer_component_id:
            interferer_component_id = _identifier(
                interferer_component_id, "interferer_component_id"
            )
        if interferer_is_environment and interferer_component_id:
            raise ConcurrencyValidationError(
                "environment interference must not name a component interferer"
            )
        if not interferer_is_environment and not interferer_component_id:
            raise ConcurrencyValidationError(
                "interference requires an interferer component or environment flag"
            )
        if (
            not interferer_is_environment
            and interferer_component_id == self.subject_component_id
        ):
            raise ConcurrencyValidationError(
                "interference interferer must differ from the subject component"
            )
        object.__setattr__(self, "interferer_is_environment", interferer_is_environment)
        object.__setattr__(self, "interferer_component_id", interferer_component_id)
        object.__setattr__(
            self,
            "shared_variable_ids",
            _ids(self.shared_variable_ids, "shared_variable_ids"),
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != INTERFERENCE_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported interference schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "interference_id": self.interference_id,
            "interferer_component_id": self.interferer_component_id,
            "interferer_is_environment": self.interferer_is_environment,
            "kind": self.kind.value,
            "schema_version": self.schema_version,
            "shared_variable_ids": list(self.shared_variable_ids),
            "statement": self.statement,
            "subject_component_id": self.subject_component_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> InterferenceAssumption:
        value = _mapping(value, "interference")
        _reject_unknown(
            value,
            frozenset(
                {
                    "interference_id",
                    "kind",
                    "statement",
                    "subject_component_id",
                    "interferer_component_id",
                    "interferer_is_environment",
                    "shared_variable_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "interference",
        )
        return cls(
            interference_id=value.get("interference_id", ""),
            kind=value.get("kind", ""),
            statement=value.get("statement", ""),
            subject_component_id=value.get("subject_component_id", ""),
            interferer_component_id=value.get("interferer_component_id", ""),
            interferer_is_environment=value.get("interferer_is_environment", False),
            shared_variable_ids=tuple(value.get("shared_variable_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", INTERFERENCE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ConcurrencyFairness:
    """An explicit fairness assumption over concurrent steps or components."""

    fairness_id: str
    kind: FairnessKind | str
    statement: str
    step_ids: tuple[str, ...] = ()
    component_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FAIRNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fairness_id", _identifier(self.fairness_id, "fairness_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, FairnessKind, "kind"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        step_ids = _ids(self.step_ids, "step_ids")
        component_ids = _ids(self.component_ids, "component_ids")
        if not step_ids and not component_ids:
            raise ConcurrencyValidationError(
                "fairness assumptions require step_ids or component_ids; "
                "fairness is never implicit"
            )
        object.__setattr__(self, "step_ids", step_ids)
        object.__setattr__(self, "component_ids", component_ids)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != FAIRNESS_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported fairness schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "component_ids": list(self.component_ids),
            "fairness_id": self.fairness_id,
            "kind": self.kind.value,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "step_ids": list(self.step_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ConcurrencyFairness:
        value = _mapping(value, "fairness")
        _reject_unknown(
            value,
            frozenset(
                {
                    "fairness_id",
                    "kind",
                    "statement",
                    "step_ids",
                    "component_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "fairness",
        )
        return cls(
            fairness_id=value.get("fairness_id", ""),
            kind=value.get("kind", ""),
            statement=value.get("statement", ""),
            step_ids=tuple(value.get("step_ids", ())),
            component_ids=tuple(value.get("component_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", FAIRNESS_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RelyGuaranteeContract:
    """A rely/guarantee contract for one concurrent component.

    ``rely`` describes permitted environment interference; ``guarantee``
    describes the component's own interference commitments to others.
    """

    contract_id: str
    component_id: str
    rely_statement: str
    guarantee_statement: str
    shared_variable_ids: tuple[str, ...] = ()
    interference_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = RELY_GUARANTEE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contract_id", _identifier(self.contract_id, "contract_id")
        )
        object.__setattr__(
            self, "component_id", _identifier(self.component_id, "component_id")
        )
        object.__setattr__(
            self, "rely_statement", _text(self.rely_statement, "rely_statement")
        )
        object.__setattr__(
            self,
            "guarantee_statement",
            _text(self.guarantee_statement, "guarantee_statement"),
        )
        object.__setattr__(
            self,
            "shared_variable_ids",
            _ids(self.shared_variable_ids, "shared_variable_ids"),
        )
        object.__setattr__(
            self, "interference_ids", _ids(self.interference_ids, "interference_ids")
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != RELY_GUARANTEE_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported rely-guarantee schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "component_id": self.component_id,
            "contract_id": self.contract_id,
            "guarantee_statement": self.guarantee_statement,
            "interference_ids": list(self.interference_ids),
            "rely_statement": self.rely_statement,
            "schema_version": self.schema_version,
            "shared_variable_ids": list(self.shared_variable_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RelyGuaranteeContract:
        value = _mapping(value, "rely-guarantee contract")
        _reject_unknown(
            value,
            frozenset(
                {
                    "contract_id",
                    "component_id",
                    "rely_statement",
                    "guarantee_statement",
                    "shared_variable_ids",
                    "interference_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "rely-guarantee contract",
        )
        return cls(
            contract_id=value.get("contract_id", ""),
            component_id=value.get("component_id", ""),
            rely_statement=value.get("rely_statement", ""),
            guarantee_statement=value.get("guarantee_statement", ""),
            shared_variable_ids=tuple(value.get("shared_variable_ids", ())),
            interference_ids=tuple(value.get("interference_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", RELY_GUARANTEE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ConcurrentChannel:
    """A communication channel between concurrent components."""

    channel_id: str
    name: str
    mode: ChannelMode | str
    endpoint_component_ids: tuple[str, ...]
    payload_sort: str = "message"
    capacity: int | None = None
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = CHANNEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "channel_id", _identifier(self.channel_id, "channel_id")
        )
        object.__setattr__(self, "name", _text(self.name, "name"))
        mode = _enum(self.mode, ChannelMode, "mode")
        object.__setattr__(self, "mode", mode)
        endpoints = _ids(
            self.endpoint_component_ids, "endpoint_component_ids", preserve_order=True
        )
        if len(endpoints) < 2:
            raise ConcurrencyValidationError(
                "channel requires at least two endpoint components"
            )
        object.__setattr__(self, "endpoint_component_ids", endpoints)
        object.__setattr__(
            self, "payload_sort", _text(self.payload_sort, "payload_sort")
        )
        capacity = self.capacity
        if capacity is not None:
            capacity = _non_bool_int(capacity, "capacity")
            if capacity < 0:
                raise ConcurrencyValidationError("channel capacity must be non-negative")
        if mode is ChannelMode.BUFFERED and capacity is None:
            raise ConcurrencyValidationError(
                "buffered channels require an explicit capacity"
            )
        if mode is not ChannelMode.BUFFERED and capacity is not None:
            raise ConcurrencyValidationError(
                "capacity is only valid for buffered channels"
            )
        if mode is ChannelMode.SYNCHRONOUS and capacity not in (None, 0):
            raise ConcurrencyValidationError(
                "synchronous channels do not admit positive capacity"
            )
        object.__setattr__(self, "capacity", capacity)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != CHANNEL_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported channel schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "capacity": self.capacity,
            "channel_id": self.channel_id,
            "endpoint_component_ids": list(self.endpoint_component_ids),
            "mode": self.mode.value,
            "name": self.name,
            "payload_sort": self.payload_sort,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ConcurrentChannel:
        value = _mapping(value, "channel")
        _reject_unknown(
            value,
            frozenset(
                {
                    "channel_id",
                    "name",
                    "mode",
                    "endpoint_component_ids",
                    "payload_sort",
                    "capacity",
                    "attributes",
                    "schema_version",
                }
            ),
            "channel",
        )
        return cls(
            channel_id=value.get("channel_id", ""),
            name=value.get("name", ""),
            mode=value.get("mode", ""),
            endpoint_component_ids=tuple(value.get("endpoint_component_ids", ())),
            payload_sort=value.get("payload_sort", "message"),
            capacity=value.get("capacity"),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", CHANNEL_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SessionAction:
    """One action in a session protocol."""

    action_id: str
    polarity: SessionPolarity | str
    label: str
    payload_sort: str = ""
    continuation_action_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SESSION_ACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        polarity = _enum(self.polarity, SessionPolarity, "polarity")
        object.__setattr__(self, "polarity", polarity)
        object.__setattr__(self, "label", _text(self.label, "label"))
        payload_sort = _optional_text(self.payload_sort, "payload_sort")
        if polarity in (SessionPolarity.SEND, SessionPolarity.RECEIVE) and not payload_sort:
            raise ConcurrencyValidationError(
                "send/receive session actions require payload_sort"
            )
        if polarity in (SessionPolarity.INTERNAL, SessionPolarity.END) and payload_sort:
            raise ConcurrencyValidationError(
                "internal/end session actions must not declare payload_sort"
            )
        object.__setattr__(self, "payload_sort", payload_sort)
        object.__setattr__(
            self,
            "continuation_action_ids",
            _ids(self.continuation_action_ids, "continuation_action_ids"),
        )
        if polarity is SessionPolarity.END and self.continuation_action_ids:
            raise ConcurrencyValidationError(
                "end session actions must not have continuations"
            )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != SESSION_ACTION_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported session-action schema_version {self.schema_version!r}"
            )

    def dual(self) -> SessionAction:
        """Return the dual action (send/receive flipped, structure preserved)."""

        return SessionAction(
            action_id=self.action_id,
            polarity=dual_polarity(self.polarity),
            label=self.label,
            payload_sort=self.payload_sort,
            continuation_action_ids=self.continuation_action_ids,
            attributes=self.attributes,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "attributes": self.attributes.to_dict(),
            "continuation_action_ids": list(self.continuation_action_ids),
            "label": self.label,
            "payload_sort": self.payload_sort,
            "polarity": self.polarity.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SessionAction:
        value = _mapping(value, "session action")
        _reject_unknown(
            value,
            frozenset(
                {
                    "action_id",
                    "polarity",
                    "label",
                    "payload_sort",
                    "continuation_action_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "session action",
        )
        return cls(
            action_id=value.get("action_id", ""),
            polarity=value.get("polarity", ""),
            label=value.get("label", ""),
            payload_sort=value.get("payload_sort", ""),
            continuation_action_ids=tuple(value.get("continuation_action_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", SESSION_ACTION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SessionProtocol:
    """A session protocol with an optional dual endpoint.

    Duality validates that the dual protocol flips send/receive polarities
    while preserving action identifiers, labels, payload sorts, and
    continuation structure.  Applying dual twice yields the original
    polarities.
    """

    protocol_id: str
    name: str
    role: SessionRole | str
    actions: tuple[SessionAction, ...]
    entry_action_id: str
    dual_protocol_id: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SESSION_PROTOCOL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "protocol_id", _identifier(self.protocol_id, "protocol_id")
        )
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "role", _enum(self.role, SessionRole, "role"))
        actions = tuple(
            item
            if isinstance(item, SessionAction)
            else SessionAction.from_dict(_mapping(item, "session action"))
            for item in self.actions
        )
        if not actions:
            raise ConcurrencyValidationError("session protocol requires at least one action")
        action_ids = [item.action_id for item in actions]
        if len(action_ids) != len(set(action_ids)):
            raise ConcurrencyValidationError("session action identifiers must be unique")
        known = set(action_ids)
        entry = _identifier(self.entry_action_id, "entry_action_id")
        if entry not in known:
            raise ConcurrencyValidationError(
                f"entry_action_id {entry} is not a declared session action"
            )
        for action in actions:
            _known(
                action.continuation_action_ids,
                known,
                f"session action {action.action_id}.continuation_action_ids",
            )
        dual_protocol_id = _optional_text(self.dual_protocol_id, "dual_protocol_id")
        if dual_protocol_id:
            dual_protocol_id = _identifier(dual_protocol_id, "dual_protocol_id")
            if dual_protocol_id == self.protocol_id:
                raise ConcurrencyValidationError(
                    "session protocol cannot be dual of itself"
                )
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "entry_action_id", entry)
        object.__setattr__(self, "dual_protocol_id", dual_protocol_id)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != SESSION_PROTOCOL_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported session-protocol schema_version {self.schema_version!r}"
            )

    def dual(self, *, protocol_id: str | None = None, name: str | None = None) -> SessionProtocol:
        """Construct the dual protocol with flipped polarities and role."""

        dual_id = protocol_id or (
            self.dual_protocol_id if self.dual_protocol_id else f"{self.protocol_id}:dual"
        )
        return SessionProtocol(
            protocol_id=dual_id,
            name=name or f"dual({self.name})",
            role=dual_role(self.role),
            actions=tuple(action.dual() for action in self.actions),
            entry_action_id=self.entry_action_id,
            dual_protocol_id=self.protocol_id,
            attributes=self.attributes,
            schema_version=self.schema_version,
        )

    def is_dual_of(self, other: SessionProtocol) -> bool:
        """Return True when ``other`` is the structural dual of this protocol."""

        if self.entry_action_id != other.entry_action_id:
            return False
        if dual_role(self.role) is not other.role:
            return False
        if len(self.actions) != len(other.actions):
            return False
        by_id = {item.action_id: item for item in other.actions}
        for action in self.actions:
            dual_action = by_id.get(action.action_id)
            if dual_action is None:
                return False
            if dual_polarity(action.polarity) is not dual_action.polarity:
                return False
            if action.label != dual_action.label:
                return False
            if action.payload_sort != dual_action.payload_sort:
                return False
            if set(action.continuation_action_ids) != set(
                dual_action.continuation_action_ids
            ):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [item.to_dict() for item in self.actions],
            "attributes": self.attributes.to_dict(),
            "dual_protocol_id": self.dual_protocol_id,
            "entry_action_id": self.entry_action_id,
            "name": self.name,
            "protocol_id": self.protocol_id,
            "role": self.role.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SessionProtocol:
        value = _mapping(value, "session protocol")
        _reject_unknown(
            value,
            frozenset(
                {
                    "protocol_id",
                    "name",
                    "role",
                    "actions",
                    "entry_action_id",
                    "dual_protocol_id",
                    "attributes",
                    "schema_version",
                }
            ),
            "session protocol",
        )
        return cls(
            protocol_id=value.get("protocol_id", ""),
            name=value.get("name", ""),
            role=value.get("role", ""),
            actions=tuple(
                SessionAction.from_dict(_mapping(item, "session action"))
                for item in value.get("actions", ())
            ),
            entry_action_id=value.get("entry_action_id", ""),
            dual_protocol_id=value.get("dual_protocol_id", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", SESSION_PROTOCOL_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class LinearizabilityPoint:
    """A linearization point tying a concrete step to an abstract operation."""

    point_id: str
    step_id: str
    abstract_operation: str
    statement: str
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LINEARIZABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "point_id", _identifier(self.point_id, "point_id"))
        object.__setattr__(self, "step_id", _identifier(self.step_id, "step_id"))
        object.__setattr__(
            self,
            "abstract_operation",
            _text(self.abstract_operation, "abstract_operation"),
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != LINEARIZABILITY_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported linearizability schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract_operation": self.abstract_operation,
            "attributes": self.attributes.to_dict(),
            "point_id": self.point_id,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "step_id": self.step_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LinearizabilityPoint:
        value = _mapping(value, "linearizability point")
        _reject_unknown(
            value,
            frozenset(
                {
                    "point_id",
                    "step_id",
                    "abstract_operation",
                    "statement",
                    "attributes",
                    "schema_version",
                }
            ),
            "linearizability point",
        )
        return cls(
            point_id=value.get("point_id", ""),
            step_id=value.get("step_id", ""),
            abstract_operation=value.get("abstract_operation", ""),
            statement=value.get("statement", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", LINEARIZABILITY_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class BoundedSchedule:
    """An explicit schedule bound for concurrent exploration.

    Bounded schedules must never claim unbounded refinement.  When
    ``max_steps`` is set, ``claims_unbounded_refinement`` must be false.
    """

    schedule_id: str
    max_steps: int
    component_ids: tuple[str, ...] = ()
    step_ids: tuple[str, ...] = ()
    claims_unbounded_refinement: bool = False
    statement: str = "bounded schedule"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BOUNDED_SCHEDULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schedule_id", _identifier(self.schedule_id, "schedule_id")
        )
        max_steps = _non_bool_int(self.max_steps, "max_steps")
        if max_steps < 1:
            raise ConcurrencyValidationError("max_steps must be a positive integer")
        object.__setattr__(self, "max_steps", max_steps)
        object.__setattr__(
            self, "component_ids", _ids(self.component_ids, "component_ids")
        )
        object.__setattr__(self, "step_ids", _ids(self.step_ids, "step_ids"))
        claims = _bool(self.claims_unbounded_refinement, "claims_unbounded_refinement")
        if claims:
            raise ConcurrencyValidationError(
                "bounded schedules never claim unbounded refinement"
            )
        object.__setattr__(self, "claims_unbounded_refinement", claims)
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != BOUNDED_SCHEDULE_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported bounded-schedule schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "claims_unbounded_refinement": self.claims_unbounded_refinement,
            "component_ids": list(self.component_ids),
            "max_steps": self.max_steps,
            "schedule_id": self.schedule_id,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "step_ids": list(self.step_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BoundedSchedule:
        value = _mapping(value, "bounded schedule")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schedule_id",
                    "max_steps",
                    "component_ids",
                    "step_ids",
                    "claims_unbounded_refinement",
                    "statement",
                    "attributes",
                    "schema_version",
                }
            ),
            "bounded schedule",
        )
        return cls(
            schedule_id=value.get("schedule_id", ""),
            max_steps=value.get("max_steps", 0),
            component_ids=tuple(value.get("component_ids", ())),
            step_ids=tuple(value.get("step_ids", ())),
            claims_unbounded_refinement=value.get("claims_unbounded_refinement", False),
            statement=value.get("statement", "bounded schedule"),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", BOUNDED_SCHEDULE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ConcurrencyIR:
    """Canonical concurrent-composition document (``ConcurrencyIR@1``).

    Construction validates that:

    * environment and component steps are distinct;
    * interference and fairness assumptions are explicit when required;
    * atomic regions, channels, rely/guarantee contracts, and linearizability
      points resolve closed-world against declared identifiers;
    * paired session protocols validate duality; and
    * bounded schedules never claim unbounded refinement.
    """

    components: tuple[ConcurrentComponent, ...]
    steps: tuple[ConcurrentStep, ...]
    shared_variable_ids: tuple[str, ...] = ()
    atomic_regions: tuple[AtomicRegion, ...] = ()
    interference: tuple[InterferenceAssumption, ...] = ()
    fairness: tuple[ConcurrencyFairness, ...] = ()
    rely_guarantee: tuple[RelyGuaranteeContract, ...] = ()
    channels: tuple[ConcurrentChannel, ...] = ()
    sessions: tuple[SessionProtocol, ...] = ()
    linearizability_points: tuple[LinearizabilityPoint, ...] = ()
    schedules: tuple[BoundedSchedule, ...] = ()
    require_interference: bool = True
    require_fairness: bool = False
    metadata: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = CONCURRENCY_IR_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = CONCURRENCY_IR_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "components",
            _coerce_records(
                self.components, ConcurrentComponent, "component", "component_id"
            ),
        )
        object.__setattr__(
            self,
            "steps",
            _coerce_records(self.steps, ConcurrentStep, "step", "step_id"),
        )
        object.__setattr__(
            self,
            "shared_variable_ids",
            _ids(self.shared_variable_ids, "shared_variable_ids"),
        )
        object.__setattr__(
            self,
            "atomic_regions",
            _coerce_records(
                self.atomic_regions, AtomicRegion, "atomic region", "region_id"
            ),
        )
        object.__setattr__(
            self,
            "interference",
            _coerce_records(
                self.interference,
                InterferenceAssumption,
                "interference",
                "interference_id",
            ),
        )
        object.__setattr__(
            self,
            "fairness",
            _coerce_records(
                self.fairness, ConcurrencyFairness, "fairness", "fairness_id"
            ),
        )
        object.__setattr__(
            self,
            "rely_guarantee",
            _coerce_records(
                self.rely_guarantee,
                RelyGuaranteeContract,
                "rely-guarantee",
                "contract_id",
            ),
        )
        object.__setattr__(
            self,
            "channels",
            _coerce_records(self.channels, ConcurrentChannel, "channel", "channel_id"),
        )
        sessions = tuple(
            item
            if isinstance(item, SessionProtocol)
            else SessionProtocol.from_dict(_mapping(item, "session"))
            for item in self.sessions
        )
        object.__setattr__(
            self,
            "sessions",
            tuple(sorted(sessions, key=lambda item: item.protocol_id)),
        )
        object.__setattr__(
            self,
            "linearizability_points",
            _coerce_records(
                self.linearizability_points,
                LinearizabilityPoint,
                "linearizability point",
                "point_id",
            ),
        )
        object.__setattr__(
            self,
            "schedules",
            _coerce_records(
                self.schedules, BoundedSchedule, "schedule", "schedule_id"
            ),
        )
        object.__setattr__(
            self, "require_interference", _bool(self.require_interference, "require_interference")
        )
        object.__setattr__(
            self, "require_fairness", _bool(self.require_fairness, "require_fairness")
        )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != CONCURRENCY_IR_SCHEMA_VERSION:
            raise ConcurrencyValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        self.validate()
        identity = self._compute_identity()
        if self.document_id and self.document_id != identity.cid:
            raise ConcurrencyValidationError(
                "document_id does not match canonical concurrency semantics"
            )
        object.__setattr__(self, "document_id", identity.cid)

    @property
    def interface(self) -> str:
        return CONCURRENCY_IR_INTERFACE

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.document_id

    def component_steps(self, component_id: str) -> tuple[ConcurrentStep, ...]:
        component_id = _identifier(component_id, "component_id")
        return tuple(
            step
            for step in self.steps
            if step.owner is StepOwner.COMPONENT and step.component_id == component_id
        )

    def environment_steps(self) -> tuple[ConcurrentStep, ...]:
        return tuple(step for step in self.steps if step.owner is StepOwner.ENVIRONMENT)

    def validate(self) -> None:
        def unique(values: Sequence[object], attr: str, label: str) -> set[str]:
            ids = [getattr(item, attr) for item in values]
            if len(ids) != len(set(ids)):
                raise ConcurrencyValidationError(f"duplicate {label} identifiers")
            return set(ids)

        if not self.components:
            raise ConcurrencyValidationError(
                "ConcurrencyIR requires at least one concurrent component"
            )
        if not self.steps:
            raise ConcurrencyValidationError(
                "ConcurrencyIR requires at least one concurrent step"
            )

        component_ids = unique(self.components, "component_id", "component")
        step_ids = unique(self.steps, "step_id", "step")
        region_ids = unique(self.atomic_regions, "region_id", "atomic region")
        interference_ids = unique(self.interference, "interference_id", "interference")
        fairness_ids = unique(self.fairness, "fairness_id", "fairness")
        contract_ids = unique(self.rely_guarantee, "contract_id", "rely-guarantee")
        channel_ids = unique(self.channels, "channel_id", "channel")
        session_ids = unique(self.sessions, "protocol_id", "session")
        point_ids = unique(self.linearizability_points, "point_id", "linearizability")
        schedule_ids = unique(self.schedules, "schedule_id", "schedule")
        del fairness_ids, contract_ids, channel_ids, point_ids, schedule_ids

        component_names = [item.name for item in self.components]
        if len(component_names) != len(set(component_names)):
            raise ConcurrencyValidationError("component names must be unique")

        shared = set(self.shared_variable_ids)
        steps_by_id = {item.step_id: item for item in self.steps}
        components_by_id = {item.component_id: item for item in self.components}

        # Component membership of steps must be closed and consistent.
        for component in self.components:
            _known(
                component.step_ids,
                step_ids,
                f"component {component.component_id}.step_ids",
            )
            for step_id in component.step_ids:
                step = steps_by_id[step_id]
                if step.owner is not StepOwner.COMPONENT:
                    raise ConcurrencyValidationError(
                        f"component {component.component_id} lists environment step "
                        f"{step_id}; environment and component steps are distinct"
                    )
                if step.component_id != component.component_id:
                    raise ConcurrencyValidationError(
                        f"component {component.component_id} lists step {step_id} "
                        f"owned by {step.component_id!r}"
                    )
            for variable_id in component.local_variable_ids:
                if variable_id in shared:
                    raise ConcurrencyValidationError(
                        f"component {component.component_id} local variable "
                        f"{variable_id} must not also be shared"
                    )

        for step in self.steps:
            if step.owner is StepOwner.COMPONENT:
                if step.component_id not in component_ids:
                    raise ConcurrencyValidationError(
                        f"step {step.step_id} references unknown component "
                        f"{step.component_id}"
                    )
                owner = components_by_id[step.component_id]
                if step.step_id not in owner.step_ids:
                    raise ConcurrencyValidationError(
                        f"component step {step.step_id} must be listed on component "
                        f"{step.component_id}"
                    )
            if step.atomic_region_id:
                _known(
                    (step.atomic_region_id,),
                    region_ids,
                    f"step {step.step_id}.atomic_region_id",
                )

        for region in self.atomic_regions:
            if region.component_id not in component_ids:
                raise ConcurrencyValidationError(
                    f"atomic region {region.region_id} references unknown component "
                    f"{region.component_id}"
                )
            _known(region.step_ids, step_ids, f"atomic region {region.region_id}.step_ids")
            for step_id in region.step_ids:
                step = steps_by_id[step_id]
                if step.owner is not StepOwner.COMPONENT:
                    raise ConcurrencyValidationError(
                        f"atomic region {region.region_id} cannot include environment "
                        f"step {step_id}"
                    )
                if step.component_id != region.component_id:
                    raise ConcurrencyValidationError(
                        f"atomic region {region.region_id} step {step_id} belongs to "
                        f"another component"
                    )
                if step.atomic_region_id and step.atomic_region_id != region.region_id:
                    raise ConcurrencyValidationError(
                        f"step {step_id} atomic_region_id mismatch with region "
                        f"{region.region_id}"
                    )

        # Interference must be explicit when required and multi-component.
        if self.require_interference and len(self.components) > 1 and not self.interference:
            raise ConcurrencyValidationError(
                "multi-component concurrency requires explicit interference "
                "assumptions; interference is never implicit"
            )
        for assumption in self.interference:
            if assumption.subject_component_id not in component_ids:
                raise ConcurrencyValidationError(
                    f"interference {assumption.interference_id} subject unknown"
                )
            if (
                not assumption.interferer_is_environment
                and assumption.interferer_component_id not in component_ids
            ):
                raise ConcurrencyValidationError(
                    f"interference {assumption.interference_id} interferer unknown"
                )
            if shared:
                _known(
                    assumption.shared_variable_ids,
                    shared,
                    f"interference {assumption.interference_id}.shared_variable_ids",
                )

        if self.require_fairness and not self.fairness:
            raise ConcurrencyValidationError(
                "fairness assumptions are required and must be explicit"
            )
        for constraint in self.fairness:
            _known(
                constraint.step_ids,
                step_ids,
                f"fairness {constraint.fairness_id}.step_ids",
            )
            _known(
                constraint.component_ids,
                component_ids,
                f"fairness {constraint.fairness_id}.component_ids",
            )

        for contract in self.rely_guarantee:
            if contract.component_id not in component_ids:
                raise ConcurrencyValidationError(
                    f"rely/guarantee {contract.contract_id} references unknown component"
                )
            _known(
                contract.interference_ids,
                interference_ids,
                f"rely/guarantee {contract.contract_id}.interference_ids",
            )
            if shared:
                _known(
                    contract.shared_variable_ids,
                    shared,
                    f"rely/guarantee {contract.contract_id}.shared_variable_ids",
                )

        for channel in self.channels:
            _known(
                channel.endpoint_component_ids,
                component_ids,
                f"channel {channel.channel_id}.endpoint_component_ids",
            )

        sessions_by_id = {item.protocol_id: item for item in self.sessions}
        for session in self.sessions:
            if session.dual_protocol_id:
                if session.dual_protocol_id not in session_ids:
                    raise ConcurrencyValidationError(
                        f"session {session.protocol_id} dual_protocol_id "
                        f"{session.dual_protocol_id} is unknown"
                    )
                dual = sessions_by_id[session.dual_protocol_id]
                if not session.is_dual_of(dual):
                    raise ConcurrencyValidationError(
                        f"session {session.protocol_id} is not dual of "
                        f"{session.dual_protocol_id}; session duality must validate"
                    )
                if dual.dual_protocol_id and dual.dual_protocol_id != session.protocol_id:
                    raise ConcurrencyValidationError(
                        f"session duality must be symmetric between "
                        f"{session.protocol_id} and {dual.protocol_id}"
                    )

        for point in self.linearizability_points:
            if point.step_id not in step_ids:
                raise ConcurrencyValidationError(
                    f"linearizability point {point.point_id} references unknown step"
                )
            step = steps_by_id[point.step_id]
            if step.owner is not StepOwner.COMPONENT:
                raise ConcurrencyValidationError(
                    f"linearizability point {point.point_id} must attach to a "
                    "component step"
                )

        for schedule in self.schedules:
            _known(
                schedule.component_ids,
                component_ids,
                f"schedule {schedule.schedule_id}.component_ids",
            )
            _known(
                schedule.step_ids,
                step_ids,
                f"schedule {schedule.schedule_id}.step_ids",
            )
            if schedule.claims_unbounded_refinement:
                raise ConcurrencyValidationError(
                    "bounded schedules never claim unbounded refinement"
                )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "atomic_regions": [item.to_dict() for item in self.atomic_regions],
            "channels": [item.to_dict() for item in self.channels],
            "components": [item.to_dict() for item in self.components],
            "fairness": [item.to_dict() for item in self.fairness],
            "interference": [item.to_dict() for item in self.interference],
            "interface": CONCURRENCY_IR_INTERFACE,
            "linearizability_points": [
                item.to_dict() for item in self.linearizability_points
            ],
            "metadata": self.metadata.to_dict(),
            "rely_guarantee": [item.to_dict() for item in self.rely_guarantee],
            "require_fairness": self.require_fairness,
            "require_interference": self.require_interference,
            "schedules": [item.to_dict() for item in self.schedules],
            "schema_version": self.schema_version,
            "sessions": [item.to_dict() for item in self.sessions],
            "shared_variable_ids": list(self.shared_variable_ids),
            "steps": [item.to_dict() for item in self.steps],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["document_id"] = self.document_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def semantic_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=CONCURRENCY_IR_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ConcurrencyIR:
        value = _mapping(value, "concurrency ir")
        _reject_unknown(
            value,
            frozenset(
                {
                    "components",
                    "steps",
                    "shared_variable_ids",
                    "atomic_regions",
                    "interference",
                    "fairness",
                    "rely_guarantee",
                    "channels",
                    "sessions",
                    "linearizability_points",
                    "schedules",
                    "require_interference",
                    "require_fairness",
                    "metadata",
                    "document_id",
                    "schema_version",
                    "interface",
                }
            ),
            "concurrency ir",
        )
        return cls(
            components=tuple(
                ConcurrentComponent.from_dict(_mapping(item, "component"))
                for item in value.get("components", ())
            ),
            steps=tuple(
                ConcurrentStep.from_dict(_mapping(item, "step"))
                for item in value.get("steps", ())
            ),
            shared_variable_ids=tuple(value.get("shared_variable_ids", ())),
            atomic_regions=tuple(
                AtomicRegion.from_dict(_mapping(item, "atomic region"))
                for item in value.get("atomic_regions", ())
            ),
            interference=tuple(
                InterferenceAssumption.from_dict(_mapping(item, "interference"))
                for item in value.get("interference", ())
            ),
            fairness=tuple(
                ConcurrencyFairness.from_dict(_mapping(item, "fairness"))
                for item in value.get("fairness", ())
            ),
            rely_guarantee=tuple(
                RelyGuaranteeContract.from_dict(_mapping(item, "rely-guarantee"))
                for item in value.get("rely_guarantee", ())
            ),
            channels=tuple(
                ConcurrentChannel.from_dict(_mapping(item, "channel"))
                for item in value.get("channels", ())
            ),
            sessions=tuple(
                SessionProtocol.from_dict(_mapping(item, "session"))
                for item in value.get("sessions", ())
            ),
            linearizability_points=tuple(
                LinearizabilityPoint.from_dict(_mapping(item, "linearizability"))
                for item in value.get("linearizability_points", ())
            ),
            schedules=tuple(
                BoundedSchedule.from_dict(_mapping(item, "schedule"))
                for item in value.get("schedules", ())
            ),
            require_interference=value.get("require_interference", True),
            require_fairness=value.get("require_fairness", False),
            metadata=_frozen(
                _mapping(value.get("metadata", {}), "metadata"), "metadata"
            ),
            document_id=value.get("document_id", ""),
            schema_version=value.get("schema_version", CONCURRENCY_IR_SCHEMA_VERSION),
        )


__all__ = [
    "ATOMIC_REGION_SCHEMA_VERSION",
    "BOUNDED_SCHEDULE_SCHEMA_VERSION",
    "CHANNEL_SCHEMA_VERSION",
    "COMPONENT_SCHEMA_VERSION",
    "CONCURRENCY_IR_IDENTITY_DOMAIN",
    "CONCURRENCY_IR_INTERFACE",
    "CONCURRENCY_IR_SCHEMA_VERSION",
    "FAIRNESS_SCHEMA_VERSION",
    "INTERFERENCE_SCHEMA_VERSION",
    "LINEARIZABILITY_SCHEMA_VERSION",
    "RELY_GUARANTEE_SCHEMA_VERSION",
    "SESSION_ACTION_SCHEMA_VERSION",
    "SESSION_PROTOCOL_SCHEMA_VERSION",
    "STEP_SCHEMA_VERSION",
    "AtomicRegion",
    "AtomicityKind",
    "BoundedSchedule",
    "ChannelMode",
    "ComponentKind",
    "ConcurrencyFairness",
    "ConcurrencyIR",
    "ConcurrencyValidationError",
    "ConcurrentChannel",
    "ConcurrentComponent",
    "ConcurrentStep",
    "FairnessKind",
    "InterferenceAssumption",
    "InterferenceKind",
    "LinearizabilityPoint",
    "RelyGuaranteeContract",
    "SessionAction",
    "SessionPolarity",
    "SessionProtocol",
    "SessionRole",
    "StepOwner",
    "dual_polarity",
    "dual_role",
]
