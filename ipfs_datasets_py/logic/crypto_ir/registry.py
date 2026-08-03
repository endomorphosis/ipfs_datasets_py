"""Deterministic Crypto IR adapter and capability registry (CRYPTOIR-G030).

The registry is an in-process, side-effect-free index of
:class:`~ipfs_datasets_py.logic.crypto_ir.adapters.CryptoIRAdapter`
implementations and their :class:`~.capabilities.CapabilityDescriptor`
bindings.  Registration order does not affect identity: listings and
lookups are sorted by stable keys.  Missing or unavailable capabilities
return typed fail-closed results.

Importing this module never opens network connections or installs packages.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Iterator

from .adapters import (
    AdapterConversionResult,
    AdapterConversionStatus,
    CryptoIRAdapter,
    CryptoIRAdapterError,
    unavailable_conversion,
)
from .capabilities import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityProbeResult,
    CapabilityStatus,
    CapabilitySurface,
    fail_closed_for_unavailable,
    probe_capability,
)
from .identity import crypto_ir_identity
from .provenance import AuthorityKind
from .schema_versions import (
    CRYPTO_IR_ADAPTER_REGISTRY_SCHEMA_VERSION,
    CRYPTO_IR_KERNEL_SCHEMA_VERSION,
)
from .verdicts import VerdictFamily


CRYPTO_IR_REGISTRY_DOMAIN: Final[str] = "crypto-ir.registry"


class CryptoIRRegistryError(ValueError):
    """Raised when registry construction or lookup fails closed."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CryptoIRRegistryError(f"{name} must be a non-empty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One registered adapter plus its sealed capability descriptor."""

    adapter_id: str
    capability: CapabilityDescriptor
    adapter: CryptoIRAdapter

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", _text(self.adapter_id, "adapter_id"))
        if not isinstance(self.capability, CapabilityDescriptor):
            raise CryptoIRRegistryError("capability must be a CapabilityDescriptor")
        if not isinstance(self.adapter, CryptoIRAdapter):
            raise CryptoIRRegistryError("adapter must implement CryptoIRAdapter")
        if self.adapter.adapter_id != self.adapter_id:
            raise CryptoIRRegistryError(
                "adapter_id does not match adapter.adapter_id "
                f"({self.adapter_id!r} != {self.adapter.adapter_id!r})"
            )
        if self.adapter.capability.capability_id != self.capability.capability_id:
            raise CryptoIRRegistryError(
                "capability_id does not match adapter.capability"
            )
        # Capability identity must bind both version axes.
        adapter_cap = self.adapter.capability
        if (
            adapter_cap.implementation_version != self.capability.implementation_version
            or adapter_cap.semantic_version != self.capability.semantic_version
        ):
            raise CryptoIRRegistryError(
                "registered capability versions must match the adapter binding"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "capability": self.capability.to_dict(),
        }


@dataclass
class AdapterRegistry:
    """Mutable builder that freezes into a deterministic adapter index.

    After :meth:`freeze`, further registration raises.  Lookups never install
    packages or perform network I/O.
    """

    schema_version: str = CRYPTO_IR_ADAPTER_REGISTRY_SCHEMA_VERSION.identifier
    _entries: dict[str, RegistryEntry] = field(default_factory=dict, init=False, repr=False)
    _by_capability: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _frozen: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != CRYPTO_IR_ADAPTER_REGISTRY_SCHEMA_VERSION.identifier:
            raise CryptoIRRegistryError(
                f"unsupported adapter registry schema: {self.schema_version}"
            )

    @property
    def frozen(self) -> bool:
        return self._frozen

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[RegistryEntry]:
        for adapter_id in sorted(self._entries):
            yield self._entries[adapter_id]

    def __contains__(self, adapter_id: object) -> bool:
        return isinstance(adapter_id, str) and adapter_id in self._entries

    def register(self, adapter: CryptoIRAdapter) -> RegistryEntry:
        """Register *adapter* under its ``adapter_id`` and capability identity.

        Duplicate adapter ids or capability ids fail closed.  Registration is
        refused after :meth:`freeze`.
        """

        if self._frozen:
            raise CryptoIRRegistryError("registry is frozen; cannot register adapters")
        if not isinstance(adapter, CryptoIRAdapter):
            raise CryptoIRRegistryError("adapter must implement CryptoIRAdapter")
        adapter_id = _text(adapter.adapter_id, "adapter_id")
        capability = adapter.capability
        if not isinstance(capability, CapabilityDescriptor):
            raise CryptoIRRegistryError(
                "adapter.capability must be a CapabilityDescriptor"
            )
        if not capability.side_effect_free:
            raise CryptoIRRegistryError(
                "registered adapters must declare side_effect_free capabilities"
            )
        if adapter_id in self._entries:
            raise CryptoIRRegistryError(
                f"duplicate adapter registration: {adapter_id}"
            )
        if capability.capability_id in self._by_capability:
            raise CryptoIRRegistryError(
                f"duplicate capability registration: {capability.capability_id}"
            )
        entry = RegistryEntry(
            adapter_id=adapter_id,
            capability=capability,
            adapter=adapter,
        )
        self._entries[adapter_id] = entry
        self._by_capability[capability.capability_id] = adapter_id
        return entry

    def freeze(self) -> "AdapterRegistry":
        """Seal the registry against further mutation."""

        self._frozen = True
        return self

    def get(self, adapter_id: str) -> RegistryEntry:
        """Return the entry for *adapter_id* or fail closed."""

        key = _text(adapter_id, "adapter_id")
        try:
            return self._entries[key]
        except KeyError as exc:
            raise CryptoIRRegistryError(f"unknown adapter: {key}") from exc

    def get_by_capability(self, capability_id: str) -> RegistryEntry:
        """Return the entry bound to *capability_id* or fail closed."""

        key = _text(capability_id, "capability_id")
        try:
            adapter_id = self._by_capability[key]
        except KeyError as exc:
            raise CryptoIRRegistryError(f"unknown capability: {key}") from exc
        return self._entries[adapter_id]

    def require(
        self,
        adapter_id: str,
        *,
        required_surfaces: Sequence[CapabilitySurface | str] | None = None,
        required_features: Sequence[str] | None = None,
    ) -> RegistryEntry:
        """Return an available entry or fail closed with a typed probe reason."""

        entry = self.get(adapter_id)
        probe = probe_capability(
            entry.capability,
            required_surfaces=required_surfaces,
            required_features=required_features,
        )
        if not probe.available:
            raise CryptoIRRegistryError(
                f"adapter {adapter_id!r} unavailable: {probe.reason}"
            )
        return entry

    def probe(
        self,
        adapter_id: str,
        *,
        required_surfaces: Sequence[CapabilitySurface | str] | None = None,
        required_features: Sequence[str] | None = None,
    ) -> CapabilityProbeResult:
        """Side-effect-free availability probe for a registered adapter."""

        try:
            entry = self.get(adapter_id)
        except CryptoIRRegistryError:
            return CapabilityProbeResult(
                capability_id=adapter_id,
                status=CapabilityStatus.UNAVAILABLE,
                available=False,
                reason=f"unknown adapter: {adapter_id}",
            )
        return probe_capability(
            entry.capability,
            required_surfaces=required_surfaces,
            required_features=required_features,
        )

    def list_adapters(self) -> tuple[str, ...]:
        """Return adapter ids in deterministic sorted order."""

        return tuple(sorted(self._entries))

    def list_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        """Return capability descriptors sorted by capability_id."""

        return tuple(
            self._entries[adapter_id].capability
            for adapter_id in sorted(
                self._entries,
                key=lambda adapter_id: self._entries[adapter_id].capability.capability_id,
            )
        )

    def list_by_kind(self, kind: CapabilityKind | str) -> tuple[RegistryEntry, ...]:
        """Return entries whose capability kind matches *kind*."""

        if isinstance(kind, CapabilityKind):
            target = kind
        else:
            try:
                target = CapabilityKind(kind)
            except (TypeError, ValueError) as exc:
                raise CryptoIRRegistryError(f"unsupported capability kind: {kind!r}") from exc
        return tuple(
            entry
            for entry in self
            if entry.capability.kind is target
        )

    def list_for_chain_namespace(self, namespace: str) -> tuple[RegistryEntry, ...]:
        """Return adapters that support *namespace* (empty list is not an error)."""

        text = _text(namespace, "namespace")
        return tuple(
            entry
            for entry in self
            if entry.capability.supports_chain_namespace(text)
        )

    def list_available(
        self,
        *,
        required_surfaces: Sequence[CapabilitySurface | str] | None = None,
        required_features: Sequence[str] | None = None,
    ) -> tuple[RegistryEntry, ...]:
        """Return registered adapters whose side-effect-free probe is available.

        Deterministic sorted order matches :meth:`__iter__`.  Unavailable or
        missing-surface adapters are omitted rather than failing closed.
        """

        available: list[RegistryEntry] = []
        for entry in self:
            probe = probe_capability(
                entry.capability,
                required_surfaces=required_surfaces,
                required_features=required_features,
            )
            if probe.available:
                available.append(entry)
        return tuple(available)

    def has_available(
        self,
        adapter_id: str,
        *,
        required_surfaces: Sequence[CapabilitySurface | str] | None = None,
        required_features: Sequence[str] | None = None,
    ) -> bool:
        """Return whether *adapter_id* is registered and available."""

        return self.probe(
            adapter_id,
            required_surfaces=required_surfaces,
            required_features=required_features,
        ).available

    def convert(
        self,
        adapter_id: str,
        payload: Mapping[str, Any],
        *,
        source_provenance: Any = None,
        required_surfaces: Sequence[CapabilitySurface | str] | None = None,
    ) -> AdapterConversionResult:
        """Dispatch conversion through a registered adapter with fail-closed probe."""

        probe = self.probe(adapter_id, required_surfaces=required_surfaces)
        if not probe.available:
            return unavailable_conversion(
                conversion_id=f"registry-unavailable:{adapter_id}",
                adapter_id=adapter_id,
                capability_id=probe.capability_id,
                reason=probe.reason or "adapter unavailable",
            )
        entry = self.get(adapter_id)
        try:
            result = entry.adapter.convert(
                payload, source_provenance=source_provenance
            )
        except CryptoIRAdapterError as exc:
            return AdapterConversionResult(
                conversion_id=f"registry-error:{adapter_id}",
                adapter_id=adapter_id,
                capability_id=entry.capability.capability_id,
                status=AdapterConversionStatus.ERROR,
                source_authority=AuthorityKind.OBSERVATION,
                result_authority=AuthorityKind.OBSERVATION,
                diagnostics=(str(exc),),
            )
        if not isinstance(result, AdapterConversionResult):
            raise CryptoIRRegistryError(
                "adapter.convert must return AdapterConversionResult"
            )
        return result

    def unavailable_result(
        self,
        capability_id: str,
        *,
        family: VerdictFamily | str,
        subject_id: str,
    ):
        """Typed fail-closed result when a capability is missing or unavailable."""

        try:
            entry = self.get_by_capability(capability_id)
        except CryptoIRRegistryError:
            return fail_closed_for_unavailable(
                None,
                capability_id=capability_id,
                family=family,
                subject_id=subject_id,
                reason=f"unknown capability: {capability_id}",
            )
        probe = probe_capability(entry.capability)
        if probe.available:
            raise CryptoIRRegistryError(
                f"capability {capability_id!r} is available; refuse unavailable result"
            )
        return fail_closed_for_unavailable(
            entry.capability,
            capability_id=capability_id,
            family=family,
            subject_id=subject_id,
            reason=probe.reason,
        )

    def to_dict(self) -> dict[str, Any]:
        """Deterministic registry snapshot (adapter descriptors only)."""

        return {
            "adapters": [entry.to_dict() for entry in self],
            "registry_schema": self.schema_version,
            "schema_version": self.schema_version,
        }

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=CRYPTO_IR_REGISTRY_DOMAIN,
        )

    @classmethod
    def from_adapters(
        cls,
        adapters: Iterable[CryptoIRAdapter],
        *,
        freeze: bool = True,
    ) -> "AdapterRegistry":
        """Build a registry from *adapters* in a single pass."""

        registry = cls()
        # Sort by adapter_id for deterministic registration order when callers
        # pass unordered iterables; identity still depends only on membership.
        ordered = sorted(adapters, key=lambda item: item.adapter_id)
        for adapter in ordered:
            registry.register(adapter)
        if freeze:
            registry.freeze()
        return registry


def empty_registry(*, freeze: bool = False) -> AdapterRegistry:
    """Return an empty registry (optionally frozen)."""

    registry = AdapterRegistry()
    if freeze:
        registry.freeze()
    return registry


__all__ = [
    "CRYPTO_IR_REGISTRY_DOMAIN",
    "AdapterRegistry",
    "CryptoIRRegistryError",
    "RegistryEntry",
    "empty_registry",
]
