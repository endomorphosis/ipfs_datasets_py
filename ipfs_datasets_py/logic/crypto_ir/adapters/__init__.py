"""Crypto IR adapter protocol surface (CRYPTOIR-G030).

Adapters convert wallet observations, Security IR, software-contract IR,
knowledge-graph snapshots, and prover inputs into Crypto IR without network
side effects at import time.  Chain-specific modules (``evm``, ``solana``,
…) are added by later goals; this package root only exports the shared
protocol and conversion receipt types.

Importing this module must never open sockets, install packages, or register
adapters as a side effect of discovery.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.provenance import freeze_json, thaw_json
from ..capabilities import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityStatus,
    CapabilitySurface,
    CryptoIRCapabilityError,
    probe_capability,
)
from ..identity import crypto_ir_identity
from ..provenance import (
    AuthorityKind,
    CryptoIRProvenance,
    CryptoIRProvenanceError,
    assert_authority_not_elevated,
    freeze_json_mapping,
)
from ..schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION


CRYPTO_IR_ADAPTER_DOMAIN: Final[str] = "crypto-ir.adapter"


class CryptoIRAdapterError(ValueError):
    """Raised when an adapter contract is violated."""


class AdapterConversionStatus(str, Enum):
    """Terminal status for one side-effect-free conversion attempt."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRAdapterError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRAdapterError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRAdapterError(f"{name} must not have surrounding whitespace")
    return value


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRAdapterError(f"unsupported {name}: {value!r}") from exc


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRAdapterError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRAdapterError(f"unknown {name} field(s): {', '.join(unknown)}")


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise CryptoIRAdapterError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRAdapterError(str(exc)) from exc


def _unique_texts(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRAdapterError(f"{name} must be a sequence")
    result = tuple(_text(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRAdapterError(f"{name} values must be unique")
    return result


@dataclass(frozen=True, slots=True)
class UnsupportedField:
    """An input field the adapter could not normalize without inventing facts."""

    path: str
    reason: str
    raw_digest: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _text(self.path, "path"))
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self, "raw_digest", _text(self.raw_digest, "raw_digest", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "path": self.path,
            "raw_digest": self.raw_digest,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsupportedField":
        value = _as_mapping(value, "UnsupportedField")
        _known_fields(
            value,
            frozenset({"attributes", "path", "raw_digest", "reason"}),
            "UnsupportedField",
        )
        return cls(
            path=value.get("path", ""),
            reason=value.get("reason", ""),
            raw_digest=value.get("raw_digest", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class AdapterConversionResult:
    """Immutable receipt for one adapter conversion.

    Provenance of the source record is preserved.  Unsupported fields remain
    explicit rather than being dropped or invented.  Conversion never elevates
    authority (observations cannot become proof or authorization).
    """

    conversion_id: str
    adapter_id: str
    capability_id: str
    status: AdapterConversionStatus
    source_authority: AuthorityKind
    result_authority: AuthorityKind
    source_digest: str = ""
    result_digest: str = ""
    result_payload: Any = field(default_factory=dict)
    unsupported_fields: tuple[UnsupportedField, ...] = ()
    preserved_provenance: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "ipfs-datasets.crypto-ir.adapter-conversion@1.0.0"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "conversion_id", _text(self.conversion_id, "conversion_id")
        )
        object.__setattr__(self, "adapter_id", _text(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self, "capability_id", _text(self.capability_id, "capability_id")
        )
        object.__setattr__(
            self, "status", _enum(AdapterConversionStatus, self.status, "status")
        )
        if not isinstance(self.source_authority, AuthorityKind):
            try:
                object.__setattr__(
                    self,
                    "source_authority",
                    AuthorityKind(self.source_authority),
                )
            except (TypeError, ValueError) as exc:
                raise CryptoIRAdapterError(
                    f"unsupported source_authority: {self.source_authority!r}"
                ) from exc
        if not isinstance(self.result_authority, AuthorityKind):
            try:
                object.__setattr__(
                    self,
                    "result_authority",
                    AuthorityKind(self.result_authority),
                )
            except (TypeError, ValueError) as exc:
                raise CryptoIRAdapterError(
                    f"unsupported result_authority: {self.result_authority!r}"
                ) from exc
        # Fail closed on authority elevation.
        try:
            assert_authority_not_elevated(
                self.source_authority,
                self.result_authority,
                context="adapter conversion",
            )
        except CryptoIRProvenanceError as exc:
            raise CryptoIRAdapterError(str(exc)) from exc
        for name in ("source_digest", "result_digest"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "result_payload", _payload(self.result_payload))
        if isinstance(self.unsupported_fields, (str, bytes, bytearray)) or not isinstance(
            self.unsupported_fields, Sequence
        ):
            raise CryptoIRAdapterError("unsupported_fields must be a sequence")
        normalized_fields: list[UnsupportedField] = []
        for item in self.unsupported_fields:
            if isinstance(item, UnsupportedField):
                normalized_fields.append(item)
            elif isinstance(item, Mapping):
                normalized_fields.append(UnsupportedField.from_dict(item))
            else:
                raise CryptoIRAdapterError(
                    "unsupported_fields items must be UnsupportedField or mappings"
                )
        object.__setattr__(self, "unsupported_fields", tuple(normalized_fields))
        object.__setattr__(
            self, "preserved_provenance", _attributes(self.preserved_provenance)
        )
        object.__setattr__(
            self, "diagnostics", _unique_texts(self.diagnostics, "diagnostics")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=CRYPTO_IR_ADAPTER_DOMAIN,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "attributes": thaw_json(self.attributes),
            "capability_id": self.capability_id,
            "conversion_id": self.conversion_id,
            "diagnostics": list(self.diagnostics),
            "preserved_provenance": thaw_json(self.preserved_provenance),
            "result_authority": self.result_authority.value,
            "result_digest": self.result_digest,
            "result_payload": thaw_json(self.result_payload),
            "schema_version": self.schema_version,
            "source_authority": self.source_authority.value,
            "source_digest": self.source_digest,
            "status": self.status.value,
            "unsupported_fields": [item.to_dict() for item in self.unsupported_fields],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdapterConversionResult":
        value = _as_mapping(value, "AdapterConversionResult")
        _known_fields(
            value,
            frozenset(
                {
                    "adapter_id",
                    "attributes",
                    "capability_id",
                    "conversion_id",
                    "diagnostics",
                    "preserved_provenance",
                    "result_authority",
                    "result_digest",
                    "result_payload",
                    "schema_version",
                    "source_authority",
                    "source_digest",
                    "status",
                    "unsupported_fields",
                }
            ),
            "AdapterConversionResult",
        )
        return cls(
            conversion_id=value.get("conversion_id", ""),
            adapter_id=value.get("adapter_id", ""),
            capability_id=value.get("capability_id", ""),
            status=value.get("status", ""),
            source_authority=value.get("source_authority", ""),
            result_authority=value.get("result_authority", ""),
            source_digest=value.get("source_digest", ""),
            result_digest=value.get("result_digest", ""),
            result_payload=value.get("result_payload", {}),
            unsupported_fields=tuple(value.get("unsupported_fields", ())),
            preserved_provenance=value.get("preserved_provenance", {}),
            diagnostics=tuple(value.get("diagnostics", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                "ipfs-datasets.crypto-ir.adapter-conversion@1.0.0",
            ),
        )


@runtime_checkable
class CryptoIRAdapter(Protocol):
    """Side-effect-free protocol for Crypto IR adapters.

    Implementations must:

    * expose a stable ``adapter_id`` and :class:`CapabilityDescriptor`;
    * preserve provenance and unsupported fields on conversion;
    * never elevate authority during conversion; and
    * avoid import-time network I/O or package installation.
    """

    @property
    def adapter_id(self) -> str:
        """Stable adapter identifier."""

    @property
    def capability(self) -> CapabilityDescriptor:
        """Capability binding implementation and semantic versions."""

    def supports_chain_namespace(self, namespace: str) -> bool:
        """Return whether this adapter handles *namespace*."""

    def convert(
        self,
        payload: Mapping[str, Any],
        *,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    ) -> AdapterConversionResult:
        """Convert *payload* into Crypto IR without elevating authority."""


def adapter_is_available(adapter: CryptoIRAdapter) -> bool:
    """Return True when the adapter's declared capability is available."""

    capability = adapter.capability
    if not isinstance(capability, CapabilityDescriptor):
        raise CryptoIRAdapterError("adapter.capability must be a CapabilityDescriptor")
    probe = probe_capability(capability)
    return probe.available


def adapter_capability_identity(
    adapter: CryptoIRAdapter,
) -> tuple[str, str, str]:
    """Return (capability_id, implementation_version, semantic_version).

    Capability identity binds both version axes so a binary swap or silent
    semantic drift cannot masquerade as the same adapter capability.
    """

    capability = adapter.capability
    if not isinstance(capability, CapabilityDescriptor):
        raise CryptoIRAdapterError("adapter.capability must be a CapabilityDescriptor")
    return (
        capability.capability_id,
        capability.implementation_version,
        capability.semantic_version,
    )


def conversion_elevates_authority(result: AdapterConversionResult) -> bool:
    """Return True when *result* would elevate authority (should never happen).

    :class:`AdapterConversionResult` construction already fails closed on
    elevation; this helper is for audit/inspection of sealed receipts.
    """

    if not isinstance(result, AdapterConversionResult):
        raise CryptoIRAdapterError("result must be an AdapterConversionResult")
    source = result.source_authority
    target = result.result_authority
    if source is target:
        return False
    # Authorization may never be manufactured from any other kind.
    if target is AuthorityKind.AUTHORIZATION:
        return True
    # Rank order mirrors provenance.assert_authority_not_elevated.
    rank = {
        AuthorityKind.DECLARATION: 0,
        AuthorityKind.OBSERVATION: 1,
        AuthorityKind.ASSUMPTION: 1,
        AuthorityKind.EVIDENCE: 2,
        AuthorityKind.RESULT: 3,
        AuthorityKind.AUTHORIZATION: 4,
    }
    return rank[target] > rank[source]


def unavailable_conversion(
    *,
    conversion_id: str,
    adapter_id: str,
    capability_id: str,
    source_authority: AuthorityKind | str = AuthorityKind.OBSERVATION,
    reason: str,
) -> AdapterConversionResult:
    """Build a typed fail-closed conversion result for unavailable adapters."""

    source = (
        source_authority
        if isinstance(source_authority, AuthorityKind)
        else AuthorityKind(source_authority)
    )
    return AdapterConversionResult(
        conversion_id=conversion_id,
        adapter_id=adapter_id,
        capability_id=capability_id,
        status=AdapterConversionStatus.UNAVAILABLE,
        source_authority=source,
        result_authority=source,
        diagnostics=(reason,),
        attributes={"unavailable": True},
    )


class NullCryptoIRAdapter:
    """Reference in-process adapter that records unsupported conversion.

    Useful for registry and import-side-effect tests.  Performs no network I/O.
    """

    def __init__(
        self,
        *,
        adapter_id: str = "crypto-ir.null",
        capability: CapabilityDescriptor | None = None,
    ) -> None:
        self._adapter_id = _text(adapter_id, "adapter_id")
        if capability is None:
            capability = CapabilityDescriptor(
                capability_id="crypto-ir.null",
                kind=CapabilityKind.CHAIN_ADAPTER,
                implementation_version="1.0.0",
                semantic_version="1.0.0",
                status=CapabilityStatus.AVAILABLE,
                surfaces=(CapabilitySurface.OBSERVATION,),
                features=("null",),
                summary="Null reference adapter",
            )
        if not isinstance(capability, CapabilityDescriptor):
            raise CryptoIRAdapterError("capability must be a CapabilityDescriptor")
        self._capability = capability

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def capability(self) -> CapabilityDescriptor:
        return self._capability

    def supports_chain_namespace(self, namespace: str) -> bool:
        return self._capability.supports_chain_namespace(namespace)

    def convert(
        self,
        payload: Mapping[str, Any],
        *,
        source_provenance: CryptoIRProvenance | Mapping[str, Any] | None = None,
    ) -> AdapterConversionResult:
        if not isinstance(payload, Mapping):
            raise CryptoIRAdapterError("payload must be a mapping")
        provenance_dict: dict[str, Any] = {}
        source_authority = AuthorityKind.OBSERVATION
        if isinstance(source_provenance, CryptoIRProvenance):
            provenance_dict = source_provenance.to_dict()
            source_authority = source_provenance.authority.kind
        elif isinstance(source_provenance, Mapping):
            provenance_dict = dict(source_provenance)
            authority = provenance_dict.get("authority", {})
            if isinstance(authority, Mapping) and "kind" in authority:
                source_authority = AuthorityKind(authority["kind"])
        unsupported = tuple(
            UnsupportedField(path=str(key), reason="null adapter does not normalize")
            for key in sorted(payload)
        )
        return AdapterConversionResult(
            conversion_id=f"null:{self._adapter_id}",
            adapter_id=self._adapter_id,
            capability_id=self._capability.capability_id,
            status=AdapterConversionStatus.UNSUPPORTED,
            source_authority=source_authority,
            result_authority=source_authority,
            result_payload={},
            unsupported_fields=unsupported,
            preserved_provenance=provenance_dict,
            diagnostics=("null adapter preserves unsupported fields only",),
        )


__all__ = [
    "CRYPTO_IR_ADAPTER_DOMAIN",
    "AdapterConversionResult",
    "AdapterConversionStatus",
    "CryptoIRAdapter",
    "CryptoIRAdapterError",
    "NullCryptoIRAdapter",
    "UnsupportedField",
    "adapter_capability_identity",
    "adapter_is_available",
    "conversion_elevates_authority",
    "unavailable_conversion",
    # Re-exports useful to adapter implementers.
    "CapabilityDescriptor",
    "CapabilityKind",
    "CapabilityStatus",
    "CapabilitySurface",
    "CryptoIRCapabilityError",
]
