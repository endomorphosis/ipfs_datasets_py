"""Crypto IR provenance bindings that reuse ``ir_core`` contracts.

This module does not clone :mod:`ipfs_datasets_py.logic.ir_core.provenance`.
It adds chain-neutral acquisition and observation bindings and an explicit
authority lattice so conversion cannot elevate declarations, observations,
assumptions, results, or authorization.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ..ir_core.canonical import CollectionSchema, CollectionSemantics, canonical_json_bytes
from ..ir_core.identity import CanonicalIdentity, canonical_identity
from ..ir_core.provenance import (
    IR_PROVENANCE_SCHEMA_VERSION,
    ConfigBinding,
    ConfigurationBinding,
    IRProvenance,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    ProvenanceValidationError,
    SourceRef,
    SourceReference,
    SourceReviewStatus,
    SourceSpan,
    freeze_json,
    freeze_json_mapping,
    provenance_sha256,
    thaw_json,
    validate_provenance,
)
from .schema_versions import (
    CRYPTO_IR_KERNEL_SCHEMA_VERSION,
    CRYPTO_IR_PROVENANCE_SCHEMA_VERSION,
)


CRYPTO_IR_PROVENANCE_DOMAIN: Final[str] = "crypto-ir.provenance"
CRYPTO_IR_PROVENANCE_SCHEMA_ID: Final[str] = CRYPTO_IR_PROVENANCE_SCHEMA_VERSION.identifier


class CryptoIRProvenanceError(ValueError):
    """Raised when Crypto IR provenance is malformed or elevates authority."""


class AuthorityKind(str, Enum):
    """Non-interchangeable authority kinds for Crypto IR records.

    These kinds form a lattice, not a scalar score.  Conversion and adaptation
    must preserve the kind; a lower or different kind must never be relabeled
    as a higher or different kind.
    """

    DECLARATION = "declaration"
    OBSERVATION = "observation"
    ASSUMPTION = "assumption"
    EVIDENCE = "evidence"
    RESULT = "result"
    AUTHORIZATION = "authorization"


# Conversion may only preserve or narrow authority.  Explicit promotions are
# forbidden; authorization may never be manufactured from other kinds.
_AUTHORITY_RANK: Final[Mapping[AuthorityKind, int]] = MappingProxyType(
    {
        AuthorityKind.DECLARATION: 0,
        AuthorityKind.OBSERVATION: 1,
        AuthorityKind.ASSUMPTION: 1,
        AuthorityKind.EVIDENCE: 2,
        AuthorityKind.RESULT: 3,
        AuthorityKind.AUTHORIZATION: 4,
    }
)


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRProvenanceError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRProvenanceError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRProvenanceError(f"{name} must not have surrounding whitespace")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRProvenanceError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRProvenanceError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except ProvenanceValidationError as exc:
        raise CryptoIRProvenanceError(str(exc)) from exc


def coerce_authority_kind(value: AuthorityKind | str) -> AuthorityKind:
    """Return a closed :class:`AuthorityKind` or fail closed."""

    if isinstance(value, AuthorityKind):
        return value
    try:
        return AuthorityKind(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRProvenanceError(
            f"unknown authority kind: {value!r}"
        ) from exc


def assert_authority_not_elevated(
    source: AuthorityKind | str,
    target: AuthorityKind | str,
    *,
    context: str = "conversion",
) -> None:
    """Fail closed when *target* would elevate authority relative to *source*.

    Authorization may never be produced by conversion.  Distinct sibling kinds
    at the same rank (observation vs assumption) also cannot rewrite into each
    other.
    """

    source_kind = coerce_authority_kind(source)
    target_kind = coerce_authority_kind(target)
    if source_kind == target_kind:
        return
    if target_kind is AuthorityKind.AUTHORIZATION:
        raise CryptoIRProvenanceError(
            f"{context} cannot elevate {source_kind.value} to authorization"
        )
    if _AUTHORITY_RANK[target_kind] > _AUTHORITY_RANK[source_kind]:
        raise CryptoIRProvenanceError(
            f"{context} cannot elevate {source_kind.value} to {target_kind.value}"
        )
    if source_kind != target_kind:
        # Same rank or demotion across distinct kinds still requires an explicit
        # re-authoring step outside conversion.
        raise CryptoIRProvenanceError(
            f"{context} cannot rewrite {source_kind.value} as {target_kind.value}"
        )


@dataclass(frozen=True, slots=True)
class AuthorityBinding:
    """Explicit authority classification bound into a record's provenance."""

    kind: AuthorityKind
    policy_id: str = ""
    notes: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", coerce_authority_kind(self.kind))
        object.__setattr__(
            self, "policy_id", _text(self.policy_id, "policy_id", allow_empty=True)
        )
        object.__setattr__(self, "notes", _text(self.notes, "notes", allow_empty=True))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "kind": self.kind.value,
            "notes": self.notes,
            "policy_id": self.policy_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityBinding":
        value = _as_mapping(value, "AuthorityBinding")
        _known_fields(
            value,
            frozenset({"kind", "policy_id", "notes", "attributes"}),
            "AuthorityBinding",
        )
        return cls(
            kind=value.get("kind", ""),
            policy_id=value.get("policy_id", ""),
            notes=value.get("notes", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class AcquisitionProvenance:
    """Request/response binding for read-only artifact acquisition."""

    provider_id: str
    transport: str
    request_digest: str = ""
    response_digest: str = ""
    endpoint_id: str = ""
    observed_at: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _text(self.provider_id, "provider_id")
        )
        object.__setattr__(self, "transport", _text(self.transport, "transport"))
        for name in (
            "request_digest",
            "response_digest",
            "endpoint_id",
            "observed_at",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "endpoint_id": self.endpoint_id,
            "observed_at": self.observed_at,
            "provider_id": self.provider_id,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "transport": self.transport,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AcquisitionProvenance":
        value = _as_mapping(value, "AcquisitionProvenance")
        _known_fields(
            value,
            frozenset(
                {
                    "provider_id",
                    "transport",
                    "request_digest",
                    "response_digest",
                    "endpoint_id",
                    "observed_at",
                    "attributes",
                }
            ),
            "AcquisitionProvenance",
        )
        return cls(
            provider_id=value.get("provider_id", ""),
            transport=value.get("transport", ""),
            request_digest=value.get("request_digest", ""),
            response_digest=value.get("response_digest", ""),
            endpoint_id=value.get("endpoint_id", ""),
            observed_at=value.get("observed_at", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    """Time, finality, validity, and retraction bindings for observations."""

    observed_at: str
    finality: str
    validity_start: str = ""
    validity_end: str = ""
    retraction_status: str = "not_retracted"
    reorg_depth: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _text(self.observed_at, "observed_at"))
        object.__setattr__(self, "finality", _text(self.finality, "finality"))
        object.__setattr__(
            self,
            "validity_start",
            _text(self.validity_start, "validity_start", allow_empty=True),
        )
        object.__setattr__(
            self,
            "validity_end",
            _text(self.validity_end, "validity_end", allow_empty=True),
        )
        object.__setattr__(
            self,
            "retraction_status",
            _text(self.retraction_status, "retraction_status"),
        )
        if self.reorg_depth is not None:
            if type(self.reorg_depth) is not int or isinstance(self.reorg_depth, bool):
                raise CryptoIRProvenanceError("reorg_depth must be an integer")
            if self.reorg_depth < 0:
                raise CryptoIRProvenanceError("reorg_depth must be non-negative")
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "finality": self.finality,
            "observed_at": self.observed_at,
            "reorg_depth": self.reorg_depth,
            "retraction_status": self.retraction_status,
            "validity_end": self.validity_end,
            "validity_start": self.validity_start,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObservationProvenance":
        value = _as_mapping(value, "ObservationProvenance")
        _known_fields(
            value,
            frozenset(
                {
                    "observed_at",
                    "finality",
                    "validity_start",
                    "validity_end",
                    "retraction_status",
                    "reorg_depth",
                    "attributes",
                }
            ),
            "ObservationProvenance",
        )
        return cls(
            observed_at=value.get("observed_at", ""),
            finality=value.get("finality", ""),
            validity_start=value.get("validity_start", ""),
            validity_end=value.get("validity_end", ""),
            retraction_status=value.get("retraction_status", "not_retracted"),
            reorg_depth=value.get("reorg_depth"),
            attributes=value.get("attributes", {}),
        )


CRYPTO_IR_PROVENANCE_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/source_refs": CollectionSemantics.SET_LIKE,
        "/producer_ids": CollectionSemantics.SET_LIKE,
        "/config_ids": CollectionSemantics.SET_LIKE,
    }
)


@dataclass(frozen=True, slots=True)
class CryptoIRProvenance:
    """Chain-neutral provenance envelope for Crypto IR records.

    Embeds optional shared :class:`IRProvenance` material by reference ids and
    digests rather than cloning source bodies.
    """

    authority: AuthorityBinding
    producer_id: str
    schema_version: str = CRYPTO_IR_KERNEL_SCHEMA_VERSION
    acquisition: AcquisitionProvenance | None = None
    observation: ObservationProvenance | None = None
    source_refs: tuple[str, ...] = ()
    producer_ids: tuple[str, ...] = ()
    config_ids: tuple[str, ...] = ()
    ir_provenance_digest: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.authority, AuthorityBinding):
            if isinstance(self.authority, Mapping):
                object.__setattr__(
                    self, "authority", AuthorityBinding.from_dict(self.authority)
                )
            else:
                raise CryptoIRProvenanceError("authority must be an AuthorityBinding")
        object.__setattr__(self, "producer_id", _text(self.producer_id, "producer_id"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.acquisition is not None and not isinstance(
            self.acquisition, AcquisitionProvenance
        ):
            object.__setattr__(
                self,
                "acquisition",
                AcquisitionProvenance.from_dict(
                    _as_mapping(self.acquisition, "acquisition")
                ),
            )
        if self.observation is not None and not isinstance(
            self.observation, ObservationProvenance
        ):
            object.__setattr__(
                self,
                "observation",
                ObservationProvenance.from_dict(
                    _as_mapping(self.observation, "observation")
                ),
            )
        for name in ("source_refs", "producer_ids", "config_ids"):
            raw = getattr(self, name)
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(
                raw, Sequence
            ):
                raise CryptoIRProvenanceError(f"{name} must be a sequence of strings")
            values = tuple(_text(item, name) for item in raw)
            if len(values) != len(set(values)):
                raise CryptoIRProvenanceError(f"{name} values must be unique")
            object.__setattr__(self, name, values)
        object.__setattr__(
            self,
            "ir_provenance_digest",
            _text(self.ir_provenance_digest, "ir_provenance_digest", allow_empty=True),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        if (
            self.authority.kind is AuthorityKind.OBSERVATION
            and self.observation is None
        ):
            raise CryptoIRProvenanceError(
                "observation authority requires ObservationProvenance"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition": None
            if self.acquisition is None
            else self.acquisition.to_dict(),
            "attributes": thaw_json(self.attributes),
            "authority": self.authority.to_dict(),
            "config_ids": list(self.config_ids),
            "ir_provenance_digest": self.ir_provenance_digest,
            "observation": None
            if self.observation is None
            else self.observation.to_dict(),
            "producer_id": self.producer_id,
            "producer_ids": list(self.producer_ids),
            "schema_version": self.schema_version,
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CryptoIRProvenance":
        value = _as_mapping(value, "CryptoIRProvenance")
        _known_fields(
            value,
            frozenset(
                {
                    "authority",
                    "producer_id",
                    "schema_version",
                    "acquisition",
                    "observation",
                    "source_refs",
                    "producer_ids",
                    "config_ids",
                    "ir_provenance_digest",
                    "attributes",
                }
            ),
            "CryptoIRProvenance",
        )
        acquisition_raw = value.get("acquisition")
        observation_raw = value.get("observation")
        return cls(
            authority=AuthorityBinding.from_dict(
                _as_mapping(value.get("authority", {}), "authority")
            ),
            producer_id=value.get("producer_id", ""),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_KERNEL_SCHEMA_VERSION
            ),
            acquisition=None
            if acquisition_raw is None
            else AcquisitionProvenance.from_dict(
                _as_mapping(acquisition_raw, "acquisition")
            ),
            observation=None
            if observation_raw is None
            else ObservationProvenance.from_dict(
                _as_mapping(observation_raw, "observation")
            ),
            source_refs=tuple(value.get("source_refs", ())),
            producer_ids=tuple(value.get("producer_ids", ())),
            config_ids=tuple(value.get("config_ids", ())),
            ir_provenance_digest=value.get("ir_provenance_digest", ""),
            attributes=value.get("attributes", {}),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            self.to_dict(),
            collection_schema=CRYPTO_IR_PROVENANCE_COLLECTION_SCHEMA,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=CRYPTO_IR_PROVENANCE_DOMAIN,
            schema_version=self.schema_version,
            collection_schema=CRYPTO_IR_PROVENANCE_COLLECTION_SCHEMA,
        )


def bind_shared_provenance(provenance: IRProvenance | Provenance) -> str:
    """Return the digest of a shared IR provenance record for embedding."""

    if not isinstance(provenance, Provenance):
        raise CryptoIRProvenanceError("provenance must be an IR provenance record")
    try:
        validate_provenance(provenance)
    except ProvenanceValidationError as exc:
        raise CryptoIRProvenanceError(str(exc)) from exc
    return f"sha256:{provenance_sha256(provenance)}"


__all__ = [
    "CRYPTO_IR_PROVENANCE_COLLECTION_SCHEMA",
    "CRYPTO_IR_PROVENANCE_DOMAIN",
    "CRYPTO_IR_PROVENANCE_SCHEMA_ID",
    "IR_PROVENANCE_SCHEMA_VERSION",
    "AcquisitionProvenance",
    "AuthorityBinding",
    "AuthorityKind",
    "ConfigBinding",
    "ConfigurationBinding",
    "CryptoIRProvenance",
    "CryptoIRProvenanceError",
    "IRProvenance",
    "ObservationProvenance",
    "ProducerBinding",
    "Provenance",
    "ProvenanceBinding",
    "ProvenanceValidationError",
    "SourceRef",
    "SourceReference",
    "SourceReviewStatus",
    "SourceSpan",
    "assert_authority_not_elevated",
    "bind_shared_provenance",
    "coerce_authority_kind",
    "freeze_json",
    "freeze_json_mapping",
    "provenance_sha256",
    "thaw_json",
    "validate_provenance",
]
