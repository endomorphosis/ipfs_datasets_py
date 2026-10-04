"""Side-effect-free Crypto IR capability descriptors (CRYPTOIR-G030).

Capability identities bind both *implementation* and *semantic* versions so a
binary swap or silent semantic drift cannot masquerade as the same capability.
Discovery is pure: importing this module never installs packages, opens
sockets, or probes networks.  Unavailable required capabilities return typed
fail-closed results rather than empty success.

Adapters for wallet records, Security IR, software-contract IR, knowledge
graphs, and prover backends declare capabilities here; chain-specific parsing
lives in later adapter modules.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ..ir_core.provenance import freeze_json, thaw_json
from .identity import crypto_ir_identity
from .provenance import CryptoIRProvenanceError, freeze_json_mapping
from .schema_versions import (
    CRYPTO_IR_CAPABILITY_SCHEMA_VERSION,
    CRYPTO_IR_KERNEL_SCHEMA_VERSION,
)
from .verdicts import (
    AnalysisVerdict,
    PolicyVerdict,
    ReadinessOutcome,
    TypedFamilyVerdict,
    VerdictFamily,
    unavailable_analysis_verdict,
    unavailable_policy_verdict,
)


CRYPTO_IR_CAPABILITY_DOMAIN: Final[str] = "crypto-ir.capability"
_SEMVER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_CAPABILITY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
)


class CryptoIRCapabilityError(ValueError):
    """Raised when a capability descriptor or probe is invalid."""


class CapabilityKind(str, Enum):
    """Closed capability families adapters may declare."""

    WALLET_RECORDS = "wallet_records"
    SECURITY_IR = "security_ir"
    SOFTWARE_CONTRACT_IR = "software_contract_ir"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    PROVER_BACKEND = "prover_backend"
    CHAIN_ADAPTER = "chain_adapter"
    SANCTIONS = "sanctions"
    COMPLIANCE_POLICY = "compliance_policy"
    SIMULATION = "simulation"
    ARTIFACT_ACQUISITION = "artifact_acquisition"


class CapabilityStatus(str, Enum):
    """Availability of a declared capability without probing the network."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"


class CapabilitySurface(str, Enum):
    """Which result authority a capability is permitted to emit."""

    OBSERVATION = "observation"
    EVIDENCE = "evidence"
    ANALYSIS = "analysis"
    SATISFIABILITY = "satisfiability"
    MONITOR = "monitor"
    READINESS = "readiness"
    HEURISTIC = "heuristic"
    SANCTIONS = "sanctions"
    POLICY = "policy"
    # Authorization is intentionally omitted from generic capability surfaces;
    # only dedicated guard services may emit transaction authorization.


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRCapabilityError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRCapabilityError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRCapabilityError(f"{name} must not have surrounding whitespace")
    return value


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRCapabilityError(f"unsupported {name}: {value!r}") from exc


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRCapabilityError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRCapabilityError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise CryptoIRCapabilityError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRCapabilityError(str(exc)) from exc


def _semver(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _SEMVER_RE.fullmatch(text):
        raise CryptoIRCapabilityError(
            f"{name} must be a semantic version (major.minor.patch)"
        )
    return text


def _unique_texts(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRCapabilityError(f"{name} must be a sequence")
    result = tuple(_text(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRCapabilityError(f"{name} values must be unique")
    return result


def _unique_enums(
    values: Sequence[Any] | None,
    enum_type: type[Enum],
    name: str,
) -> tuple[Enum, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRCapabilityError(f"{name} must be a sequence")
    result = tuple(_enum(enum_type, item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRCapabilityError(f"{name} values must be unique")
    return result


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Immutable identity of one Crypto IR capability implementation.

    ``capability_id`` alone is insufficient: the content identity binds both
    ``implementation_version`` (binary/build) and ``semantic_version``
    (contract surface).  Changing either yields a distinct identity.
    """

    capability_id: str
    kind: CapabilityKind
    implementation_version: str
    semantic_version: str
    status: CapabilityStatus = CapabilityStatus.AVAILABLE
    surfaces: tuple[CapabilitySurface, ...] = ()
    chain_namespaces: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    deterministic: bool = True
    side_effect_free: bool = True
    provider_id: str = ""
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_CAPABILITY_SCHEMA_VERSION.identifier

    def __post_init__(self) -> None:
        capability_id = _text(self.capability_id, "capability_id")
        if not _CAPABILITY_ID_RE.fullmatch(capability_id):
            raise CryptoIRCapabilityError(
                "capability_id must be a lowercase dotted/dashed identifier"
            )
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "kind", _enum(CapabilityKind, self.kind, "kind"))
        object.__setattr__(
            self,
            "implementation_version",
            _semver(self.implementation_version, "implementation_version"),
        )
        object.__setattr__(
            self,
            "semantic_version",
            _semver(self.semantic_version, "semantic_version"),
        )
        object.__setattr__(
            self, "status", _enum(CapabilityStatus, self.status, "status")
        )
        object.__setattr__(
            self,
            "surfaces",
            _unique_enums(self.surfaces, CapabilitySurface, "surfaces"),
        )
        object.__setattr__(
            self,
            "chain_namespaces",
            _unique_texts(self.chain_namespaces, "chain_namespaces"),
        )
        object.__setattr__(
            self, "features", _unique_texts(self.features, "features")
        )
        if not isinstance(self.deterministic, bool):
            raise CryptoIRCapabilityError("deterministic must be a boolean")
        if not isinstance(self.side_effect_free, bool):
            raise CryptoIRCapabilityError("side_effect_free must be a boolean")
        if not self.side_effect_free:
            raise CryptoIRCapabilityError(
                "Crypto IR capability descriptors must be side-effect-free"
            )
        object.__setattr__(
            self, "provider_id", _text(self.provider_id, "provider_id", allow_empty=True)
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != CRYPTO_IR_CAPABILITY_SCHEMA_VERSION.identifier:
            raise CryptoIRCapabilityError(
                f"unsupported capability schema: {self.schema_version}"
            )

    @property
    def available(self) -> bool:
        return self.status is CapabilityStatus.AVAILABLE

    @property
    def identity(self):
        """Content identity binding id + implementation + semantic versions."""

        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=CRYPTO_IR_CAPABILITY_DOMAIN,
        )

    def supports_surface(self, surface: CapabilitySurface | str) -> bool:
        target = _enum(CapabilitySurface, surface, "surface")
        return target in self.surfaces

    def supports_chain_namespace(self, namespace: str) -> bool:
        text = _text(namespace, "namespace")
        if not self.chain_namespaces:
            return True
        return text in self.chain_namespaces

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "capability_id": self.capability_id,
            "chain_namespaces": list(self.chain_namespaces),
            "deterministic": self.deterministic,
            "features": list(self.features),
            "implementation_version": self.implementation_version,
            "kind": self.kind.value,
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
            "semantic_version": self.semantic_version,
            "side_effect_free": self.side_effect_free,
            "status": self.status.value,
            "summary": self.summary,
            "surfaces": [item.value for item in self.surfaces],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityDescriptor":
        value = _as_mapping(value, "CapabilityDescriptor")
        _known_fields(
            value,
            frozenset(
                {
                    "attributes",
                    "capability_id",
                    "chain_namespaces",
                    "deterministic",
                    "features",
                    "implementation_version",
                    "kind",
                    "provider_id",
                    "schema_version",
                    "semantic_version",
                    "side_effect_free",
                    "status",
                    "summary",
                    "surfaces",
                }
            ),
            "CapabilityDescriptor",
        )
        return cls(
            capability_id=value.get("capability_id", ""),
            kind=value.get("kind", ""),
            implementation_version=value.get("implementation_version", ""),
            semantic_version=value.get("semantic_version", ""),
            status=value.get("status", CapabilityStatus.AVAILABLE),
            surfaces=tuple(value.get("surfaces", ())),
            chain_namespaces=tuple(value.get("chain_namespaces", ())),
            features=tuple(value.get("features", ())),
            deterministic=value.get("deterministic", True),
            side_effect_free=value.get("side_effect_free", True),
            provider_id=value.get("provider_id", ""),
            summary=value.get("summary", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                CRYPTO_IR_CAPABILITY_SCHEMA_VERSION.identifier,
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityProbeResult:
    """Typed outcome of a side-effect-free capability availability check.

    Probes never perform network I/O.  They re-evaluate declared status and
    required surfaces/features only.
    """

    capability_id: str
    status: CapabilityStatus
    available: bool
    reason: str = ""
    missing_surfaces: tuple[str, ...] = ()
    missing_features: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capability_id", _text(self.capability_id, "capability_id")
        )
        object.__setattr__(
            self, "status", _enum(CapabilityStatus, self.status, "status")
        )
        if not isinstance(self.available, bool):
            raise CryptoIRCapabilityError("available must be a boolean")
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", allow_empty=True)
        )
        object.__setattr__(
            self,
            "missing_surfaces",
            _unique_texts(self.missing_surfaces, "missing_surfaces"),
        )
        object.__setattr__(
            self,
            "missing_features",
            _unique_texts(self.missing_features, "missing_features"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "available": self.available,
            "capability_id": self.capability_id,
            "missing_features": list(self.missing_features),
            "missing_surfaces": list(self.missing_surfaces),
            "reason": self.reason,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityProbeResult":
        value = _as_mapping(value, "CapabilityProbeResult")
        _known_fields(
            value,
            frozenset(
                {
                    "attributes",
                    "available",
                    "capability_id",
                    "missing_features",
                    "missing_surfaces",
                    "reason",
                    "status",
                }
            ),
            "CapabilityProbeResult",
        )
        return cls(
            capability_id=value.get("capability_id", ""),
            status=value.get("status", ""),
            available=value.get("available", False),
            reason=value.get("reason", ""),
            missing_surfaces=tuple(value.get("missing_surfaces", ())),
            missing_features=tuple(value.get("missing_features", ())),
            attributes=value.get("attributes", {}),
        )


def probe_capability(
    descriptor: CapabilityDescriptor,
    *,
    required_surfaces: Sequence[CapabilitySurface | str] | None = None,
    required_features: Sequence[str] | None = None,
) -> CapabilityProbeResult:
    """Evaluate availability without network or installation side effects."""

    if not isinstance(descriptor, CapabilityDescriptor):
        raise CryptoIRCapabilityError("descriptor must be a CapabilityDescriptor")

    required_surface_values = _unique_enums(
        required_surfaces, CapabilitySurface, "required_surfaces"
    )
    required_feature_values = _unique_texts(required_features, "required_features")

    missing_surfaces = tuple(
        surface.value
        for surface in required_surface_values
        if surface not in descriptor.surfaces
    )
    missing_features = tuple(
        feature
        for feature in required_feature_values
        if feature not in descriptor.features
    )

    if descriptor.status is not CapabilityStatus.AVAILABLE:
        return CapabilityProbeResult(
            capability_id=descriptor.capability_id,
            status=descriptor.status,
            available=False,
            reason=f"capability status is {descriptor.status.value}",
            missing_surfaces=missing_surfaces,
            missing_features=missing_features,
        )
    if missing_surfaces or missing_features:
        reasons: list[str] = []
        if missing_surfaces:
            reasons.append(f"missing surfaces: {', '.join(missing_surfaces)}")
        if missing_features:
            reasons.append(f"missing features: {', '.join(missing_features)}")
        return CapabilityProbeResult(
            capability_id=descriptor.capability_id,
            status=CapabilityStatus.UNSUPPORTED,
            available=False,
            reason="; ".join(reasons),
            missing_surfaces=missing_surfaces,
            missing_features=missing_features,
        )
    return CapabilityProbeResult(
        capability_id=descriptor.capability_id,
        status=CapabilityStatus.AVAILABLE,
        available=True,
        reason="available",
    )


def fail_closed_for_unavailable(
    descriptor: CapabilityDescriptor | None,
    *,
    capability_id: str,
    family: VerdictFamily | str,
    subject_id: str,
    reason: str = "",
) -> AnalysisVerdict | PolicyVerdict | TypedFamilyVerdict:
    """Return a typed fail-closed verdict for an unavailable capability.

    The family selects the result type.  Authorization is never fabricated.
    """

    family_value = (
        family if isinstance(family, VerdictFamily) else VerdictFamily(family)
    )
    resolved_id = (
        descriptor.capability_id if descriptor is not None else capability_id
    )
    message = reason or f"capability {resolved_id!r} is unavailable"
    if family_value is VerdictFamily.ANALYSIS:
        return unavailable_analysis_verdict(
            verdict_id=f"unavailable:{resolved_id}:{subject_id}",
            obligation_id=subject_id,
            reason=message,
            backend_id=resolved_id,
        )
    if family_value is VerdictFamily.POLICY:
        return unavailable_policy_verdict(
            verdict_id=f"unavailable:{resolved_id}:{subject_id}",
            policy_id=subject_id,
            policy_revision="unavailable",
            reason=message,
        )
    if family_value is VerdictFamily.AUTHORIZATION:
        raise CryptoIRCapabilityError(
            "unavailable capabilities cannot fabricate authorization verdicts"
        )
    if family_value is VerdictFamily.READINESS:
        outcome = ReadinessOutcome.NOT_READY.value
    elif family_value is VerdictFamily.SATISFIABILITY:
        outcome = "error"
    elif family_value is VerdictFamily.MONITOR:
        outcome = "error"
    elif family_value is VerdictFamily.HEURISTIC:
        outcome = "error"
    elif family_value is VerdictFamily.SANCTIONS:
        outcome = "error"
    else:
        raise CryptoIRCapabilityError(f"unsupported fail-closed family: {family_value}")

    return TypedFamilyVerdict(
        verdict_id=f"unavailable:{resolved_id}:{subject_id}",
        family=family_value,
        outcome=outcome,
        subject_id=subject_id,
        summary=message,
        payload={"unavailable": True, "capability_id": resolved_id},
    )


def capability_identity_tuple(
    descriptor: CapabilityDescriptor,
) -> tuple[str, str, str]:
    """Return the (id, implementation_version, semantic_version) binding."""

    return (
        descriptor.capability_id,
        descriptor.implementation_version,
        descriptor.semantic_version,
    )


# Convenience constructors for common kernel capability shapes.  These do not
# register adapters; they only produce descriptors for callers/tests.


def wallet_records_capability(
    *,
    capability_id: str,
    implementation_version: str,
    semantic_version: str,
    chain_namespaces: Sequence[str] = (),
    status: CapabilityStatus = CapabilityStatus.AVAILABLE,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        kind=CapabilityKind.WALLET_RECORDS,
        implementation_version=implementation_version,
        semantic_version=semantic_version,
        status=status,
        surfaces=(CapabilitySurface.OBSERVATION, CapabilitySurface.EVIDENCE),
        chain_namespaces=tuple(chain_namespaces),
        features=("wallet_records",),
        summary="Wallet record normalization into Crypto IR",
    )


def prover_backend_capability(
    *,
    capability_id: str,
    implementation_version: str,
    semantic_version: str,
    features: Sequence[str] = (),
    status: CapabilityStatus = CapabilityStatus.AVAILABLE,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        kind=CapabilityKind.PROVER_BACKEND,
        implementation_version=implementation_version,
        semantic_version=semantic_version,
        status=status,
        surfaces=(
            CapabilitySurface.ANALYSIS,
            CapabilitySurface.SATISFIABILITY,
            CapabilitySurface.READINESS,
        ),
        features=tuple(features) or ("theorem_proof",),
        summary="Prover backend for named obligations",
    )


def security_ir_capability(
    *,
    capability_id: str,
    implementation_version: str,
    semantic_version: str,
    chain_namespaces: Sequence[str] = (),
    status: CapabilityStatus = CapabilityStatus.AVAILABLE,
) -> CapabilityDescriptor:
    """Descriptor for Security IR → Crypto IR adapters (observation/evidence)."""

    return CapabilityDescriptor(
        capability_id=capability_id,
        kind=CapabilityKind.SECURITY_IR,
        implementation_version=implementation_version,
        semantic_version=semantic_version,
        status=status,
        surfaces=(CapabilitySurface.OBSERVATION, CapabilitySurface.EVIDENCE),
        chain_namespaces=tuple(chain_namespaces),
        features=("security_ir",),
        summary="Security IR normalization into Crypto IR",
    )


def software_contract_ir_capability(
    *,
    capability_id: str,
    implementation_version: str,
    semantic_version: str,
    features: Sequence[str] = (),
    status: CapabilityStatus = CapabilityStatus.AVAILABLE,
) -> CapabilityDescriptor:
    """Descriptor for software-contract IR adapters (analysis/readiness)."""

    return CapabilityDescriptor(
        capability_id=capability_id,
        kind=CapabilityKind.SOFTWARE_CONTRACT_IR,
        implementation_version=implementation_version,
        semantic_version=semantic_version,
        status=status,
        surfaces=(
            CapabilitySurface.OBSERVATION,
            CapabilitySurface.EVIDENCE,
            CapabilitySurface.ANALYSIS,
            CapabilitySurface.READINESS,
        ),
        features=tuple(features) or ("software_contract_ir",),
        summary="Software-contract IR binding into Crypto IR",
    )


def same_capability_identity(
    left: CapabilityDescriptor,
    right: CapabilityDescriptor,
) -> bool:
    """Return True when both descriptors bind the same id and version axes."""

    return capability_identity_tuple(left) == capability_identity_tuple(right)


__all__ = [
    "CRYPTO_IR_CAPABILITY_DOMAIN",
    "CapabilityDescriptor",
    "CapabilityKind",
    "CapabilityProbeResult",
    "CapabilityStatus",
    "CapabilitySurface",
    "CryptoIRCapabilityError",
    "capability_identity_tuple",
    "fail_closed_for_unavailable",
    "probe_capability",
    "prover_backend_capability",
    "same_capability_identity",
    "security_ir_capability",
    "software_contract_ir_capability",
    "wallet_records_capability",
    "AnalysisVerdict",
    "PolicyVerdict",
]
