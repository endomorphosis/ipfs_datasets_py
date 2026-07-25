"""Immutable, declaration-only Security IR v1.

The records in this module describe a security model.  Verification attempts,
solver verdicts, runtime traces, counterexamples, and release decisions are
deliberately not fields of :class:`SecurityIR`; those are observations about a
declaration and must bind its identity from a separate result record.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ..ir_core.canonical import (
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes,
)
from ..ir_core.identity import CanonicalIdentity, canonical_identity
from ..ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json,
    freeze_json_mapping,
    thaw_json,
)


SECURITY_IR_SCHEMA_VERSION: Final = "security-ir/v1"
SECURITY_IR_V1_SCHEMA_VERSION: Final = SECURITY_IR_SCHEMA_VERSION
SECURITY_IR_IDENTITY_DOMAIN: Final = "security-ir"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SecurityIRValidationError(ValueError):
    """Raised when a Security IR declaration is malformed."""


class PolicyEffect(str, Enum):
    """The declarative effect of a security policy."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE = "require"
    AUDIT = "audit"
    UNSPECIFIED = "unspecified"


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SecurityIRValidationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise SecurityIRValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise SecurityIRValidationError(
            f"{name} must not have surrounding whitespace"
        )
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise SecurityIRValidationError(f"{name} is not a stable identifier")
    return normalized


def _ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise SecurityIRValidationError(f"{name} must be a sequence")
    result = tuple(_identifier(value, name) for value in values)
    if len(result) != len(set(result)):
        raise SecurityIRValidationError(f"{name} values must be unique")
    return result


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except ProvenanceValidationError as exc:
        raise SecurityIRValidationError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except ProvenanceValidationError as exc:
        raise SecurityIRValidationError(str(exc)) from exc


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SecurityIRValidationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SecurityIRValidationError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


@dataclass(frozen=True, slots=True)
class SecuritySource:
    """A typed reference to source/evidence bytes outside the declaration."""

    source_id: str
    uri: str
    revision: str = ""
    content_sha256: str = ""
    review_status: str = "unreviewed"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "uri", _text(self.uri, "uri"))
        object.__setattr__(
            self, "revision", _text(self.revision, "revision", allow_empty=True)
        )
        if self.content_sha256 and not _SHA256_RE.fullmatch(self.content_sha256):
            raise SecurityIRValidationError(
                "content_sha256 must be a lowercase SHA-256 hex digest"
            )
        object.__setattr__(
            self, "review_status", _text(self.review_status, "review_status")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "content_sha256": self.content_sha256,
            "review_status": self.review_status,
            "revision": self.revision,
            "source_id": self.source_id,
            "uri": self.uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecuritySource":
        value = _as_mapping(value, "source")
        _known_fields(
            value,
            frozenset(
                {
                    "source_id",
                    "uri",
                    "revision",
                    "content_sha256",
                    "review_status",
                    "attributes",
                }
            ),
            "source",
        )
        return cls(
            source_id=value.get("source_id", ""),
            uri=value.get("uri", ""),
            revision=value.get("revision", ""),
            content_sha256=value.get("content_sha256", ""),
            review_status=value.get("review_status", "unreviewed"),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class Principal:
    """An actor that may hold roles or exercise authority."""

    principal_id: str
    kind: str = "unspecified"
    role_ids: tuple[str, ...] = ()
    trust_zone_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "principal_id", _identifier(self.principal_id, "principal_id")
        )
        object.__setattr__(self, "kind", _text(self.kind, "principal kind"))
        for name in ("role_ids", "trust_zone_ids", "source_ids"):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(
            self,
            "principal_id",
            "kind",
            "role_ids",
            "trust_zone_ids",
            "source_ids",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Principal":
        return _record_from_dict(cls, value, "principal_id")


@dataclass(frozen=True, slots=True)
class Asset:
    """A security-relevant unit of value or protected information."""

    asset_id: str
    kind: str = "unspecified"
    symbol: str = ""
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _identifier(self.asset_id, "asset_id"))
        object.__setattr__(self, "kind", _text(self.kind, "asset kind"))
        object.__setattr__(
            self, "symbol", _text(self.symbol, "asset symbol", allow_empty=True)
        )
        object.__setattr__(self, "source_ids", _ids(self.source_ids, "source_ids"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self, "asset_id", "kind", "symbol", "source_ids")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Asset":
        return _record_from_dict(cls, value, "asset_id")


@dataclass(frozen=True, slots=True)
class TrustZone:
    """A boundary inside which a declared trust posture applies."""

    trust_zone_id: str
    name: str
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trust_zone_id",
            _identifier(self.trust_zone_id, "trust_zone_id"),
        )
        object.__setattr__(self, "name", _text(self.name, "trust zone name"))
        object.__setattr__(self, "source_ids", _ids(self.source_ids, "source_ids"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self, "trust_zone_id", "name", "source_ids")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrustZone":
        return _record_from_dict(cls, value, "trust_zone_id")


@dataclass(frozen=True, slots=True)
class Channel:
    """A declared communication or data-flow channel."""

    channel_id: str
    source_node_id: str
    target_node_id: str
    protocol: str = "unspecified"
    trust_zone_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("channel_id", "source_node_id", "target_node_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "protocol", _text(self.protocol, "channel protocol"))
        object.__setattr__(
            self, "trust_zone_ids", _ids(self.trust_zone_ids, "trust_zone_ids")
        )
        object.__setattr__(self, "source_ids", _ids(self.source_ids, "source_ids"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(
            self,
            "channel_id",
            "source_node_id",
            "target_node_id",
            "protocol",
            "trust_zone_ids",
            "source_ids",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Channel":
        return _record_from_dict(
            cls, value, "channel_id", required=("source_node_id", "target_node_id")
        )


@dataclass(frozen=True, slots=True)
class Resource:
    """A protected system resource, account, wallet, service, or entity."""

    resource_id: str
    kind: str = "unspecified"
    owner_principal_ids: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    trust_zone_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_id", _identifier(self.resource_id, "resource_id")
        )
        object.__setattr__(self, "kind", _text(self.kind, "resource kind"))
        for name in (
            "owner_principal_ids",
            "asset_ids",
            "trust_zone_ids",
            "source_ids",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(
            self,
            "resource_id",
            "kind",
            "owner_principal_ids",
            "asset_ids",
            "trust_zone_ids",
            "source_ids",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Resource":
        return _record_from_dict(cls, value, "resource_id")


@dataclass(frozen=True, slots=True)
class Policy:
    """A declarative security decision rule."""

    policy_id: str
    name: str
    effect: PolicyEffect = PolicyEffect.UNSPECIFIED
    principal_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    channel_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "name", _text(self.name, "policy name"))
        try:
            effect = (
                self.effect
                if isinstance(self.effect, PolicyEffect)
                else PolicyEffect(self.effect)
            )
        except (TypeError, ValueError) as exc:
            raise SecurityIRValidationError(
                f"unsupported policy effect: {self.effect!r}"
            ) from exc
        object.__setattr__(self, "effect", effect)
        for name in ("principal_ids", "resource_ids", "channel_ids", "source_ids"):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        result = _record_dict(
            self,
            "policy_id",
            "name",
            "principal_ids",
            "resource_ids",
            "channel_ids",
            "source_ids",
        )
        result["effect"] = self.effect.value
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Policy":
        return _record_from_dict(cls, value, "policy_id", required=("name",))


@dataclass(frozen=True, slots=True)
class StateTransition:
    """One declarative transition in a state machine."""

    source_state: str
    target_state: str
    event: str
    guard: str = ""
    effect: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_state", "target_state", "event"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("guard", "effect"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "effect": self.effect,
            "event": self.event,
            "guard": self.guard,
            "source_state": self.source_state,
            "target_state": self.target_state,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateTransition":
        value = _as_mapping(value, "state transition")
        _known_fields(
            value,
            frozenset(
                {
                    "source_state",
                    "target_state",
                    "event",
                    "guard",
                    "effect",
                    "attributes",
                }
            ),
            "state transition",
        )
        return cls(
            source_state=value.get("source_state", ""),
            target_state=value.get("target_state", ""),
            event=value.get("event", ""),
            guard=value.get("guard", ""),
            effect=value.get("effect", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class StateMachine:
    """A finite-state declaration; no execution history is stored here."""

    state_machine_id: str
    states: tuple[str, ...]
    initial_state: str = ""
    transitions: tuple[StateTransition, ...] = ()
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state_machine_id",
            _identifier(self.state_machine_id, "state_machine_id"),
        )
        states = tuple(_text(value, "state") for value in self.states)
        if not states or len(states) != len(set(states)):
            raise SecurityIRValidationError(
                "state machine states must be non-empty and unique"
            )
        object.__setattr__(self, "states", states)
        initial = _text(self.initial_state, "initial_state", allow_empty=True)
        if initial and initial not in states:
            raise SecurityIRValidationError("initial_state must be one of states")
        object.__setattr__(self, "initial_state", initial)
        transitions = tuple(
            item
            if isinstance(item, StateTransition)
            else StateTransition.from_dict(_as_mapping(item, "state transition"))
            for item in self.transitions
        )
        for transition in transitions:
            if (
                transition.source_state not in states
                or transition.target_state not in states
            ):
                raise SecurityIRValidationError(
                    "state transition endpoints must be declared states"
                )
        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(self, "source_ids", _ids(self.source_ids, "source_ids"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "initial_state": self.initial_state,
            "source_ids": list(self.source_ids),
            "state_machine_id": self.state_machine_id,
            "states": list(self.states),
            "transitions": [item.to_dict() for item in self.transitions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateMachine":
        value = _as_mapping(value, "state machine")
        _known_fields(
            value,
            frozenset(
                {
                    "state_machine_id",
                    "states",
                    "initial_state",
                    "transitions",
                    "source_ids",
                    "attributes",
                }
            ),
            "state machine",
        )
        return cls(
            state_machine_id=value.get("state_machine_id", ""),
            states=tuple(value.get("states", ())),
            initial_state=value.get("initial_state", ""),
            transitions=tuple(
                StateTransition.from_dict(item)
                for item in value.get("transitions", ())
            ),
            source_ids=tuple(value.get("source_ids", ())),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class ThreatAssumption:
    """A declared premise; presence does not establish truth."""

    assumption_id: str
    statement: str
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assumption_id",
            _identifier(self.assumption_id, "assumption_id"),
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "source_ids", _ids(self.source_ids, "source_ids"))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self, "assumption_id", "statement", "source_ids")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ThreatAssumption":
        return _record_from_dict(
            cls, value, "assumption_id", required=("statement",)
        )


@dataclass(frozen=True, slots=True)
class SecurityClaim:
    """A source-grounded security property under explicit assumptions."""

    claim_id: str
    statement: str
    domain: str
    severity: str = "unspecified"
    assumption_ids: tuple[str, ...] = ()
    policy_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "domain", _identifier(self.domain, "claim domain"))
        object.__setattr__(self, "severity", _text(self.severity, "severity"))
        for name in ("assumption_ids", "policy_ids", "source_ids"):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(
            self,
            "claim_id",
            "statement",
            "domain",
            "severity",
            "assumption_ids",
            "policy_ids",
            "source_ids",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityClaim":
        return _record_from_dict(
            cls, value, "claim_id", required=("statement", "domain")
        )


@dataclass(frozen=True, slots=True)
class SecurityExtension:
    """A namespaced, versioned declaration not owned by the shared vocabulary."""

    extension_id: str
    vocabulary: str
    version: str
    payload: Any
    required: bool = False
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "extension_id", _identifier(self.extension_id, "extension_id")
        )
        object.__setattr__(
            self, "vocabulary", _identifier(self.vocabulary, "extension vocabulary")
        )
        object.__setattr__(self, "version", _text(self.version, "extension version"))
        if not isinstance(self.required, bool):
            raise SecurityIRValidationError("extension required must be a boolean")
        object.__setattr__(self, "payload", _payload(self.payload))
        object.__setattr__(self, "source_ids", _ids(self.source_ids, "source_ids"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "payload": thaw_json(self.payload),
            "required": self.required,
            "source_ids": list(self.source_ids),
            "version": self.version,
            "vocabulary": self.vocabulary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityExtension":
        value = _as_mapping(value, "extension")
        _known_fields(
            value,
            frozenset(
                {
                    "extension_id",
                    "vocabulary",
                    "version",
                    "payload",
                    "required",
                    "source_ids",
                }
            ),
            "extension",
        )
        return cls(
            extension_id=value.get("extension_id", ""),
            vocabulary=value.get("vocabulary", ""),
            version=value.get("version", ""),
            payload=value.get("payload"),
            required=value.get("required", False),
            source_ids=tuple(value.get("source_ids", ())),
        )


_RECORD_DEFAULTS: Mapping[type[Any], Mapping[str, Any]] = MappingProxyType(
    {
        Principal: {
            "kind": "unspecified",
            "role_ids": (),
            "trust_zone_ids": (),
            "source_ids": (),
        },
        Asset: {"kind": "unspecified", "symbol": "", "source_ids": ()},
        TrustZone: {"source_ids": ()},
        Channel: {
            "protocol": "unspecified",
            "trust_zone_ids": (),
            "source_ids": (),
        },
        Resource: {
            "kind": "unspecified",
            "owner_principal_ids": (),
            "asset_ids": (),
            "trust_zone_ids": (),
            "source_ids": (),
        },
        Policy: {
            "effect": PolicyEffect.UNSPECIFIED,
            "principal_ids": (),
            "resource_ids": (),
            "channel_ids": (),
            "source_ids": (),
        },
        ThreatAssumption: {"source_ids": ()},
        SecurityClaim: {
            "severity": "unspecified",
            "assumption_ids": (),
            "policy_ids": (),
            "source_ids": (),
        },
    }
)


def _record_dict(record: Any, *field_names: str) -> dict[str, Any]:
    result: dict[str, Any] = {"attributes": thaw_json(record.attributes)}
    for name in field_names:
        value = getattr(record, name)
        result[name] = list(value) if isinstance(value, tuple) else value
    return result


def _record_from_dict(
    record_type: type[Any],
    value: Mapping[str, Any],
    id_field: str,
    *,
    required: tuple[str, ...] = (),
) -> Any:
    value = _as_mapping(value, record_type.__name__)
    defaults = dict(_RECORD_DEFAULTS[record_type])
    allowed = frozenset({id_field, *defaults, *required, "attributes"})
    _known_fields(value, allowed, record_type.__name__)
    kwargs = {id_field: value.get(id_field, ""), "attributes": value.get("attributes", {})}
    for name, default in defaults.items():
        item = value.get(name, default)
        kwargs[name] = tuple(item) if isinstance(default, tuple) else item
    for name in required:
        kwargs[name] = value.get(name, "")
    return record_type(**kwargs)


SECURITY_IR_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/sources": CollectionSemantics.SET_LIKE,
        "/principals": CollectionSemantics.SET_LIKE,
        "/principals/*/role_ids": CollectionSemantics.SET_LIKE,
        "/principals/*/trust_zone_ids": CollectionSemantics.SET_LIKE,
        "/principals/*/source_ids": CollectionSemantics.SET_LIKE,
        "/assets": CollectionSemantics.SET_LIKE,
        "/assets/*/source_ids": CollectionSemantics.SET_LIKE,
        "/trust_zones": CollectionSemantics.SET_LIKE,
        "/trust_zones/*/source_ids": CollectionSemantics.SET_LIKE,
        "/channels": CollectionSemantics.SET_LIKE,
        "/channels/*/trust_zone_ids": CollectionSemantics.SET_LIKE,
        "/channels/*/source_ids": CollectionSemantics.SET_LIKE,
        "/resources": CollectionSemantics.SET_LIKE,
        "/resources/*/owner_principal_ids": CollectionSemantics.SET_LIKE,
        "/resources/*/asset_ids": CollectionSemantics.SET_LIKE,
        "/resources/*/trust_zone_ids": CollectionSemantics.SET_LIKE,
        "/resources/*/source_ids": CollectionSemantics.SET_LIKE,
        "/policies": CollectionSemantics.SET_LIKE,
        "/policies/*/principal_ids": CollectionSemantics.SET_LIKE,
        "/policies/*/resource_ids": CollectionSemantics.SET_LIKE,
        "/policies/*/channel_ids": CollectionSemantics.SET_LIKE,
        "/policies/*/source_ids": CollectionSemantics.SET_LIKE,
        "/state_machines": CollectionSemantics.SET_LIKE,
        "/state_machines/*/states": CollectionSemantics.SET_LIKE,
        "/state_machines/*/transitions": CollectionSemantics.SET_LIKE,
        "/state_machines/*/source_ids": CollectionSemantics.SET_LIKE,
        "/assumptions": CollectionSemantics.SET_LIKE,
        "/assumptions/*/source_ids": CollectionSemantics.SET_LIKE,
        "/claims": CollectionSemantics.SET_LIKE,
        "/claims/*/assumption_ids": CollectionSemantics.SET_LIKE,
        "/claims/*/policy_ids": CollectionSemantics.SET_LIKE,
        "/claims/*/source_ids": CollectionSemantics.SET_LIKE,
        "/extensions": CollectionSemantics.SET_LIKE,
        "/extensions/*/source_ids": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class SecurityIR:
    """An immutable Security IR declaration with dependency-stable identity."""

    declaration_id: str
    principals: tuple[Principal, ...] = ()
    assets: tuple[Asset, ...] = ()
    trust_zones: tuple[TrustZone, ...] = ()
    channels: tuple[Channel, ...] = ()
    resources: tuple[Resource, ...] = ()
    policies: tuple[Policy, ...] = ()
    state_machines: tuple[StateMachine, ...] = ()
    assumptions: tuple[ThreatAssumption, ...] = ()
    claims: tuple[SecurityClaim, ...] = ()
    sources: tuple[SecuritySource, ...] = ()
    extensions: tuple[SecurityExtension, ...] = ()
    schema_version: str = SECURITY_IR_SCHEMA_VERSION

    _COLLECTION_TYPES: ClassVar[Mapping[str, type[Any]]] = MappingProxyType(
        {
            "principals": Principal,
            "assets": Asset,
            "trust_zones": TrustZone,
            "channels": Channel,
            "resources": Resource,
            "policies": Policy,
            "state_machines": StateMachine,
            "assumptions": ThreatAssumption,
            "claims": SecurityClaim,
            "sources": SecuritySource,
            "extensions": SecurityExtension,
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declaration_id",
            _identifier(self.declaration_id, "declaration_id"),
        )
        if self.schema_version != SECURITY_IR_SCHEMA_VERSION:
            raise SecurityIRValidationError(
                f"unsupported Security IR schema version: {self.schema_version!r}"
            )
        for name, record_type in self._COLLECTION_TYPES.items():
            values = getattr(self, name)
            if isinstance(values, (str, bytes, bytearray)) or not isinstance(
                values, Sequence
            ):
                raise SecurityIRValidationError(f"{name} must be a sequence")
            converted = tuple(
                item
                if isinstance(item, record_type)
                else record_type.from_dict(_as_mapping(item, name))
                for item in values
            )
            object.__setattr__(self, name, converted)
        validate_security_ir(self)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-ready declaration payload."""

        return {
            "assets": [item.to_dict() for item in self.assets],
            "assumptions": [item.to_dict() for item in self.assumptions],
            "channels": [item.to_dict() for item in self.channels],
            "claims": [item.to_dict() for item in self.claims],
            "declaration_id": self.declaration_id,
            "extensions": [item.to_dict() for item in self.extensions],
            "policies": [item.to_dict() for item in self.policies],
            "principals": [item.to_dict() for item in self.principals],
            "resources": [item.to_dict() for item in self.resources],
            "schema_version": self.schema_version,
            "sources": [item.to_dict() for item in self.sources],
            "state_machines": [item.to_dict() for item in self.state_machines],
            "trust_zones": [item.to_dict() for item in self.trust_zones],
        }

    def validate(self) -> None:
        """Validate this declaration against the complete v1 contract."""

        validate_security_ir(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityIR":
        """Decode a strict Security IR v1 declaration."""

        value = _as_mapping(value, "SecurityIR")
        allowed = frozenset(
            {"declaration_id", "schema_version", *cls._COLLECTION_TYPES}
        )
        _known_fields(value, allowed, "SecurityIR")
        kwargs: dict[str, Any] = {
            "declaration_id": value.get("declaration_id", ""),
            "schema_version": value.get(
                "schema_version", SECURITY_IR_SCHEMA_VERSION
            ),
        }
        for name, record_type in cls._COLLECTION_TYPES.items():
            raw = value.get(name, ())
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(
                raw, Sequence
            ):
                raise SecurityIRValidationError(f"{name} must be a sequence")
            kwargs[name] = tuple(record_type.from_dict(item) for item in raw)
        return cls(**kwargs)

    def canonical_bytes(self) -> bytes:
        """Return canonical declaration bytes (not a verification artifact)."""

        return canonical_json_bytes(
            self.to_dict(), collection_schema=SECURITY_IR_COLLECTION_SCHEMA
        )

    def canonical_json(self) -> str:
        """Return canonical declaration JSON."""

        return self.canonical_bytes().decode("utf-8")

    @property
    def identity(self) -> CanonicalIdentity:
        """Return the shared fixed-profile identity for this declaration."""

        return canonical_identity(
            self.to_dict(),
            domain=SECURITY_IR_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
            collection_schema=SECURITY_IR_COLLECTION_SCHEMA,
        )

    @property
    def declaration_identity(self) -> CanonicalIdentity:
        """Explicit spelling emphasizing that result state is not addressed."""

        return self.identity

    @property
    def model_id(self) -> str:
        """Compatibility spelling for the declaration's stable local ID."""

        return self.declaration_id

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def cid(self) -> str:
        return self.identity.cid


def _unique(records: Sequence[Any], field_name: str, label: str) -> set[str]:
    values = [getattr(item, field_name) for item in records]
    if len(values) != len(set(values)):
        raise SecurityIRValidationError(f"duplicate {label} identifier")
    return set(values)


def _require_refs(
    values: Sequence[str], known: set[str], field_name: str
) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise SecurityIRValidationError(
            f"{field_name} contains unknown identifiers: {missing}"
        )


def validate_security_ir(declaration: SecurityIR) -> SecurityIR:
    """Validate identifiers, types, and cross-references in a declaration."""

    if not isinstance(declaration, SecurityIR):
        raise SecurityIRValidationError("declaration must be a SecurityIR")
    source_ids = _unique(declaration.sources, "source_id", "source")
    principal_ids = _unique(declaration.principals, "principal_id", "principal")
    asset_ids = _unique(declaration.assets, "asset_id", "asset")
    zone_ids = _unique(declaration.trust_zones, "trust_zone_id", "trust zone")
    channel_ids = _unique(declaration.channels, "channel_id", "channel")
    resource_ids = _unique(declaration.resources, "resource_id", "resource")
    policy_ids = _unique(declaration.policies, "policy_id", "policy")
    _unique(declaration.state_machines, "state_machine_id", "state machine")
    assumption_ids = _unique(
        declaration.assumptions, "assumption_id", "assumption"
    )
    _unique(declaration.claims, "claim_id", "claim")
    _unique(declaration.extensions, "extension_id", "extension")

    for record in (
        *declaration.principals,
        *declaration.assets,
        *declaration.trust_zones,
        *declaration.channels,
        *declaration.resources,
        *declaration.policies,
        *declaration.state_machines,
        *declaration.assumptions,
        *declaration.claims,
        *declaration.extensions,
    ):
        _require_refs(record.source_ids, source_ids, f"{type(record).__name__}.source_ids")
    for item in declaration.principals:
        _require_refs(
            item.trust_zone_ids, zone_ids, f"Principal {item.principal_id}.trust_zone_ids"
        )
    for item in declaration.channels:
        known_nodes = principal_ids | resource_ids | asset_ids | zone_ids
        _require_refs(
            (item.source_node_id, item.target_node_id),
            known_nodes,
            f"Channel {item.channel_id} endpoints",
        )
        _require_refs(
            item.trust_zone_ids, zone_ids, f"Channel {item.channel_id}.trust_zone_ids"
        )
    for item in declaration.resources:
        _require_refs(
            item.owner_principal_ids,
            principal_ids,
            f"Resource {item.resource_id}.owner_principal_ids",
        )
        _require_refs(
            item.asset_ids, asset_ids, f"Resource {item.resource_id}.asset_ids"
        )
        _require_refs(
            item.trust_zone_ids,
            zone_ids,
            f"Resource {item.resource_id}.trust_zone_ids",
        )
    for item in declaration.policies:
        _require_refs(
            item.principal_ids,
            principal_ids,
            f"Policy {item.policy_id}.principal_ids",
        )
        _require_refs(
            item.resource_ids,
            resource_ids,
            f"Policy {item.policy_id}.resource_ids",
        )
        _require_refs(
            item.channel_ids, channel_ids, f"Policy {item.policy_id}.channel_ids"
        )
    for item in declaration.claims:
        _require_refs(
            item.assumption_ids,
            assumption_ids,
            f"SecurityClaim {item.claim_id}.assumption_ids",
        )
        _require_refs(
            item.policy_ids, policy_ids, f"SecurityClaim {item.claim_id}.policy_ids"
        )
    return declaration


# Descriptive aliases for callers using the plan's plural vocabulary.
Assumption = ThreatAssumption
Claim = SecurityClaim
Source = SecuritySource
Extension = SecurityExtension
SecurityAsset = Asset
SecurityAssumption = ThreatAssumption
SecurityChannel = Channel
SecurityPolicy = Policy
SecurityPrincipal = Principal
SecurityResource = Resource
SecurityStateMachine = StateMachine
SecurityTrustZone = TrustZone
SecurityIRV1 = SecurityIR


__all__ = [
    "Asset",
    "Assumption",
    "Channel",
    "Claim",
    "Extension",
    "Policy",
    "PolicyEffect",
    "Principal",
    "Resource",
    "SECURITY_IR_COLLECTION_SCHEMA",
    "SECURITY_IR_IDENTITY_DOMAIN",
    "SECURITY_IR_SCHEMA_VERSION",
    "SECURITY_IR_V1_SCHEMA_VERSION",
    "SecurityAsset",
    "SecurityAssumption",
    "SecurityChannel",
    "SecurityClaim",
    "SecurityExtension",
    "SecurityIR",
    "SecurityIRV1",
    "SecurityIRValidationError",
    "SecurityPolicy",
    "SecurityPrincipal",
    "SecurityResource",
    "SecuritySource",
    "SecurityStateMachine",
    "SecurityTrustZone",
    "Source",
    "StateMachine",
    "StateTransition",
    "ThreatAssumption",
    "TrustZone",
    "validate_security_ir",
]
