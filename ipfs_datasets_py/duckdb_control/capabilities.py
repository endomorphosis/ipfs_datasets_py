"""DuckDB / Quack / VSS dependency policy and runtime capability probes (DQK-002).

This module is the single source of truth for:

* the pinned DuckDB client/server version (exactly 1.5.5);
* the exact Quack extension build identity expected for that pin;
* protocol compatibility between client and server;
* optional, feature-gated Quack transport and VSS/HNSW acceleration;
* fail-closed mismatch behaviour and safe local/exact-search fallbacks.

Importing this module is deliberately inert.  It never imports ``duckdb``,
never loads the ``quack`` or ``vss`` extensions, never opens sockets, and
never installs packages.  Optional runtimes are discovered only through
explicit probe entry points (or injected probe callables under test).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

__all__ = [
    "CAPABILITY_PROBE_SCHEMA",
    "CapabilityError",
    "CapabilityKind",
    "CapabilityProbeResult",
    "CapabilityRecord",
    "CapabilityStatus",
    "CapabilityUnavailableError",
    "ComponentVersions",
    "DEFAULT_VERSION_POLICY",
    "FeatureGate",
    "FeatureGateState",
    "FeatureName",
    "MINIMUM_QUACK_VERSION",
    "PINNED_QUACK_EXTENSION_BUILD",
    "PINNED_VSS_EXTENSION_BUILD",
    "QUACK_BETA",
    "QUACK_MATURITY",
    "QUACK_PRODUCTION_READY_FROM_DUCKDB",
    "QUACK_STATUS_REASON",
    "QuackMaturity",
    "REQUIRED_DUCKDB_VERSION",
    "REQUIRED_DUCKDB_VERSION_TEXT",
    "SUPPORTED_QUACK_PROTOCOL_VERSIONS",
    "TransportMode",
    "TransportResolution",
    "VersionMismatchError",
    "VersionPolicy",
    "assert_versions_compatible",
    "evaluate_feature_gate",
    "format_version",
    "parse_version",
    "ProbeRequest",
    "observe_local_duckdb_versions",
    "probe_capabilities",
    "quack_maturity_status",
    "require_capability",
    "resolve_transport",
    "versions_match_exact",
]


# ---------------------------------------------------------------------------
# Schema / pinned policy
# ---------------------------------------------------------------------------

CAPABILITY_PROBE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-capability-probe@1"
)

REQUIRED_DUCKDB_VERSION: Final[tuple[int, int, int]] = (1, 5, 5)
REQUIRED_DUCKDB_VERSION_TEXT: Final[str] = "1.5.5"

# Quack shipped as a core extension starting with DuckDB 1.5.3; this control
# plane pins the extension build to the exact admitted DuckDB platform (1.5.5).
MINIMUM_QUACK_VERSION: Final[tuple[int, int, int]] = (1, 5, 3)
PINNED_QUACK_EXTENSION_NAME: Final[str] = "quack"
PINNED_QUACK_EXTENSION_VERSION: Final[tuple[int, int, int]] = (1, 5, 5)
PINNED_QUACK_EXTENSION_SOURCE: Final[str] = "core"
PINNED_QUACK_EXTENSION_BUILD: Final[str] = "quack@1.5.5+core"

PINNED_VSS_EXTENSION_NAME: Final[str] = "vss"
PINNED_VSS_EXTENSION_VERSION: Final[tuple[int, int, int]] = (1, 5, 5)
PINNED_VSS_EXTENSION_SOURCE: Final[str] = "core"
PINNED_VSS_EXTENSION_BUILD: Final[str] = "vss@1.5.5+core"

# Protocol major versions admitted for client↔server negotiation.  Mismatches
# fail closed; later DQK-050 expands the contract suite.
SUPPORTED_QUACK_PROTOCOL_VERSIONS: Final[frozenset[int]] = frozenset({1})
DEFAULT_QUACK_PROTOCOL_VERSION: Final[int] = 1

# Quack is experimental/beta and not production-ready until DuckDB 2.0.
QUACK_PRODUCTION_READY_FROM_DUCKDB: Final[tuple[int, int, int]] = (2, 0, 0)
QUACK_BETA: Final[bool] = True
QUACK_STATUS_REASON: Final[str] = (
    "Quack is experimental/beta and not production-ready until DuckDB 2.0; "
    "keep a local transport implementation and feature gate, and require an "
    "explicit compatibility/risk receipt before any production promotion."
)


class CapabilityError(ValueError):
    """Raised when a capability descriptor, policy, or probe input is invalid."""


class VersionMismatchError(CapabilityError):
    """Raised when client, server, extension, or protocol versions disagree.

    Fail-closed: callers must not proceed with a mismatched topology.
    """


class CapabilityUnavailableError(RuntimeError):
    """Raised when a required capability is absent, disabled, or mismatched."""


class CapabilityKind(str, Enum):
    """Closed set of runtime capabilities owned by this probe."""

    DUCKDB_RUNTIME = "duckdb_runtime"
    QUACK_TRANSPORT = "quack_transport"
    VSS_INDEX = "vss_index"
    PROTOCOL = "protocol"


class CapabilityStatus(str, Enum):
    """Availability of a probed capability.

    ``MISMATCH`` is a hard fail-closed state (versions disagree).
    ``DISABLED`` means the optional feature gate is off.
    ``UNAVAILABLE`` means the optional runtime is missing or failed to load.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    MISMATCH = "mismatch"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class FeatureName(str, Enum):
    """Optional feature gates (never import-time requirements)."""

    QUACK = "quack"
    VSS = "vss"


class FeatureGateState(str, Enum):
    """Resolved state of an optional feature gate."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    MISMATCH = "mismatch"


class TransportMode(str, Enum):
    """SQL transport selected after capability probing."""

    LOCAL = "local"
    QUACK_REMOTE = "quack_remote"


class QuackMaturity(str, Enum):
    """Explicit maturity of the Quack transport for promotion gates."""

    BETA = "beta"
    PRODUCTION_CANDIDATE = "production_candidate"


QUACK_MATURITY: Final[QuackMaturity] = QuackMaturity.BETA


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def parse_version(value: str | Sequence[int] | None) -> tuple[int, ...]:
    """Parse a dotted version string (or int sequence) into an int tuple.

    Non-digit suffixes on a component are stripped (``1.5.5.dev0`` → ``(1, 5, 5)``).
    Empty / ``None`` inputs yield an empty tuple.
    """

    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        parts: list[int] = []
        for item in value:
            if not isinstance(item, int) or item < 0:
                raise CapabilityError(
                    f"version components must be non-negative ints, got {item!r}"
                )
            parts.append(item)
        return tuple(parts)
    if not isinstance(value, str):
        raise CapabilityError(f"version must be a string or int sequence, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return ()
    parts: list[int] = []
    for item in text.split("."):
        # Stop at pre-release / local segments such as "dev0", "post1", "rc1".
        if not item or not item[0].isdigit():
            break
        leading = []
        for character in item:
            if character.isdigit():
                leading.append(character)
            else:
                break
        if not leading:
            break
        parts.append(int("".join(leading)))
        # A mixed component ("5a1") ends numeric parsing after its leading digits.
        if any(not character.isdigit() for character in item):
            break
    return tuple(parts)


def format_version(version: Sequence[int]) -> str:
    """Format an int version tuple as a dotted string."""

    if not version:
        return ""
    return ".".join(str(int(part)) for part in version)


def versions_match_exact(
    observed: str | Sequence[int] | None,
    required: str | Sequence[int],
    *,
    components: int = 3,
) -> bool:
    """Return whether the first ``components`` version numbers match exactly."""

    left = parse_version(observed)[:components]
    right = parse_version(required)[:components]
    if len(left) < components or len(right) < components:
        return False
    return left == right


def _normalize_build_id(
    *,
    name: str,
    version: str | Sequence[int],
    source: str = PINNED_QUACK_EXTENSION_SOURCE,
) -> str:
    version_text = (
        format_version(version)
        if isinstance(version, Sequence) and not isinstance(version, (str, bytes))
        else format_version(parse_version(str(version)))
    )
    return f"{name}@{version_text}+{source}"


# ---------------------------------------------------------------------------
# Policy / result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionPolicy:
    """Immutable dependency/version policy for the control plane."""

    duckdb_version: tuple[int, int, int] = REQUIRED_DUCKDB_VERSION
    quack_extension_name: str = PINNED_QUACK_EXTENSION_NAME
    quack_extension_version: tuple[int, int, int] = PINNED_QUACK_EXTENSION_VERSION
    quack_extension_source: str = PINNED_QUACK_EXTENSION_SOURCE
    quack_extension_build: str = PINNED_QUACK_EXTENSION_BUILD
    minimum_quack_version: tuple[int, int, int] = MINIMUM_QUACK_VERSION
    vss_extension_name: str = PINNED_VSS_EXTENSION_NAME
    vss_extension_version: tuple[int, int, int] = PINNED_VSS_EXTENSION_VERSION
    vss_extension_source: str = PINNED_VSS_EXTENSION_SOURCE
    vss_extension_build: str = PINNED_VSS_EXTENSION_BUILD
    supported_protocol_versions: frozenset[int] = SUPPORTED_QUACK_PROTOCOL_VERSIONS
    default_protocol_version: int = DEFAULT_QUACK_PROTOCOL_VERSION
    quack_production_ready_from_duckdb: tuple[int, int, int] = (
        QUACK_PRODUCTION_READY_FROM_DUCKDB
    )
    quack_beta: bool = QUACK_BETA
    quack_status_reason: str = QUACK_STATUS_REASON

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "duckdb_version": format_version(self.duckdb_version),
                "quack_extension_name": self.quack_extension_name,
                "quack_extension_version": format_version(self.quack_extension_version),
                "quack_extension_source": self.quack_extension_source,
                "quack_extension_build": self.quack_extension_build,
                "minimum_quack_version": format_version(self.minimum_quack_version),
                "vss_extension_name": self.vss_extension_name,
                "vss_extension_version": format_version(self.vss_extension_version),
                "vss_extension_source": self.vss_extension_source,
                "vss_extension_build": self.vss_extension_build,
                "supported_protocol_versions": sorted(self.supported_protocol_versions),
                "default_protocol_version": self.default_protocol_version,
                "quack_production_ready_from_duckdb": format_version(
                    self.quack_production_ready_from_duckdb
                ),
                "quack_beta": self.quack_beta,
                "quack_status_reason": self.quack_status_reason,
            }
        )


DEFAULT_VERSION_POLICY: Final[VersionPolicy] = VersionPolicy()


@dataclass(frozen=True, slots=True)
class ComponentVersions:
    """Observed client / server / extension / protocol versions.

    Optional components may be ``None`` when not requested or not present.
    Empty strings are normalized to ``None``.
    """

    client_duckdb: str | None = None
    server_duckdb: str | None = None
    quack_extension: str | None = None
    quack_extension_build: str | None = None
    quack_extension_source: str | None = None
    vss_extension: str | None = None
    vss_extension_build: str | None = None
    client_protocol: int | None = None
    server_protocol: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "client_duckdb",
            "server_duckdb",
            "quack_extension",
            "quack_extension_build",
            "quack_extension_source",
            "vss_extension",
            "vss_extension_build",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise CapabilityError(f"{name} must be a string or None")
            if isinstance(value, str) and not value.strip():
                object.__setattr__(self, name, None)
            elif isinstance(value, str):
                object.__setattr__(self, name, value.strip())
        for name in ("client_protocol", "server_protocol"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise CapabilityError(f"{name} must be a non-negative int or None")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "client_duckdb": self.client_duckdb,
                "server_duckdb": self.server_duckdb,
                "quack_extension": self.quack_extension,
                "quack_extension_build": self.quack_extension_build,
                "quack_extension_source": self.quack_extension_source,
                "vss_extension": self.vss_extension,
                "vss_extension_build": self.vss_extension_build,
                "client_protocol": self.client_protocol,
                "server_protocol": self.server_protocol,
            }
        )


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """One probed capability with status, identity, and human reason."""

    kind: CapabilityKind
    status: CapabilityStatus
    identity: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None
    required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CapabilityKind):
            object.__setattr__(self, "kind", CapabilityKind(self.kind))
        if not isinstance(self.status, CapabilityStatus):
            object.__setattr__(self, "status", CapabilityStatus(self.status))
        if not isinstance(self.identity, Mapping):
            raise CapabilityError("identity must be a mapping")
        object.__setattr__(self, "identity", MappingProxyType(dict(self.identity)))
        if self.reason is not None and not isinstance(self.reason, str):
            raise CapabilityError("reason must be a string or None")

    @property
    def ok(self) -> bool:
        """Whether the capability is usable for its intended role."""

        if self.status is CapabilityStatus.MISMATCH:
            return False
        if self.required:
            return self.status is CapabilityStatus.AVAILABLE
        return self.status in {
            CapabilityStatus.AVAILABLE,
            CapabilityStatus.DISABLED,
            CapabilityStatus.DEGRADED,
        }

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "kind": self.kind.value,
                "status": self.status.value,
                "identity": dict(self.identity),
                "reason": self.reason,
                "required": self.required,
                "ok": self.ok,
            }
        )


@dataclass(frozen=True, slots=True)
class FeatureGate:
    """Resolved optional feature gate (Quack or VSS)."""

    name: FeatureName
    state: FeatureGateState
    requested: bool
    capability: CapabilityRecord | None = None
    fallback: str | None = None
    reason: str | None = None
    beta: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, FeatureName):
            object.__setattr__(self, "name", FeatureName(self.name))
        if not isinstance(self.state, FeatureGateState):
            object.__setattr__(self, "state", FeatureGateState(self.state))

    @property
    def enabled(self) -> bool:
        return self.state is FeatureGateState.ENABLED

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "name": self.name.value,
                "state": self.state.value,
                "requested": self.requested,
                "enabled": self.enabled,
                "fallback": self.fallback,
                "reason": self.reason,
                "beta": self.beta,
                "capability": (
                    None if self.capability is None else dict(self.capability.as_mapping())
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class TransportResolution:
    """Transport choice after probing, with explicit fallback metadata."""

    mode: TransportMode
    quack_requested: bool
    quack_available: bool
    fell_back: bool
    reason: str
    local_fallback_available: bool = True

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "mode": self.mode.value,
                "quack_requested": self.quack_requested,
                "quack_available": self.quack_available,
                "fell_back": self.fell_back,
                "reason": self.reason,
                "local_fallback_available": self.local_fallback_available,
            }
        )


@dataclass(frozen=True, slots=True)
class CapabilityProbeResult:
    """Complete capability probe receipt for gates and observability."""

    schema: str
    policy: VersionPolicy
    versions: ComponentVersions
    capabilities: Mapping[str, CapabilityRecord]
    feature_gates: Mapping[str, FeatureGate]
    transport: TransportResolution
    quack_maturity: QuackMaturity
    quack_beta: bool
    quack_status_reason: str
    fail_closed: bool
    mismatches: tuple[str, ...]
    ok: bool

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "policy": dict(self.policy.as_mapping()),
                "versions": dict(self.versions.as_mapping()),
                "capabilities": {
                    key: dict(record.as_mapping())
                    for key, record in self.capabilities.items()
                },
                "feature_gates": {
                    key: dict(gate.as_mapping())
                    for key, gate in self.feature_gates.items()
                },
                "transport": dict(self.transport.as_mapping()),
                "quack_maturity": self.quack_maturity.value,
                "quack_beta": self.quack_beta,
                "quack_status_reason": self.quack_status_reason,
                "fail_closed": self.fail_closed,
                "mismatches": list(self.mismatches),
                "ok": self.ok,
            }
        )


# ---------------------------------------------------------------------------
# Maturity / fail-closed version checks
# ---------------------------------------------------------------------------


def quack_maturity_status(
    policy: VersionPolicy | None = None,
    *,
    duckdb_version: str | Sequence[int] | None = None,
) -> QuackMaturity:
    """Return explicit Quack maturity; beta until DuckDB reaches 2.0."""

    active = policy or DEFAULT_VERSION_POLICY
    if duckdb_version is None:
        # Policy itself keeps Quack beta until the production-ready floor.
        if active.quack_beta:
            return QuackMaturity.BETA
        return QuackMaturity.PRODUCTION_CANDIDATE
    observed = parse_version(duckdb_version)
    floor = active.quack_production_ready_from_duckdb
    if len(observed) >= 3 and observed[:3] >= floor:
        return QuackMaturity.PRODUCTION_CANDIDATE
    return QuackMaturity.BETA


def assert_versions_compatible(
    versions: ComponentVersions,
    policy: VersionPolicy | None = None,
    *,
    require_server: bool = False,
    require_quack_extension: bool = False,
    require_vss_extension: bool = False,
    require_protocol: bool = False,
) -> None:
    """Fail closed when client/server/extension/protocol versions disagree.

    Raises:
        VersionMismatchError: on any required mismatch or unsupported protocol.
        CapabilityError: on structurally invalid inputs.
    """

    active = policy or DEFAULT_VERSION_POLICY
    required = format_version(active.duckdb_version)
    problems: list[str] = []

    if versions.client_duckdb is None:
        problems.append("client DuckDB version is missing")
    elif not versions_match_exact(versions.client_duckdb, required):
        problems.append(
            f"client DuckDB version mismatch: observed={versions.client_duckdb!r} "
            f"required={required!r}"
        )

    if versions.server_duckdb is None:
        if require_server:
            problems.append("server DuckDB version is missing")
    elif not versions_match_exact(versions.server_duckdb, required):
        problems.append(
            f"server DuckDB version mismatch: observed={versions.server_duckdb!r} "
            f"required={required!r}"
        )
    elif versions.client_duckdb is not None and not versions_match_exact(
        versions.server_duckdb, versions.client_duckdb
    ):
        problems.append(
            f"client/server DuckDB version mismatch: client={versions.client_duckdb!r} "
            f"server={versions.server_duckdb!r}"
        )

    if versions.quack_extension is None:
        if require_quack_extension:
            problems.append("Quack extension version is missing")
    else:
        if not versions_match_exact(
            versions.quack_extension, active.quack_extension_version
        ):
            problems.append(
                f"Quack extension version mismatch: observed={versions.quack_extension!r} "
                f"required={format_version(active.quack_extension_version)!r}"
            )
        expected_build = active.quack_extension_build
        observed_build = versions.quack_extension_build
        if observed_build is None:
            observed_build = _normalize_build_id(
                name=active.quack_extension_name,
                version=versions.quack_extension,
                source=versions.quack_extension_source
                or active.quack_extension_source,
            )
        if observed_build != expected_build:
            problems.append(
                f"Quack extension build mismatch: observed={observed_build!r} "
                f"required={expected_build!r}"
            )
        source = versions.quack_extension_source or active.quack_extension_source
        if source != active.quack_extension_source:
            problems.append(
                f"Quack extension source mismatch: observed={source!r} "
                f"required={active.quack_extension_source!r}"
            )

    if versions.vss_extension is None:
        if require_vss_extension:
            problems.append("VSS extension version is missing")
    else:
        if not versions_match_exact(
            versions.vss_extension, active.vss_extension_version
        ):
            problems.append(
                f"VSS extension version mismatch: observed={versions.vss_extension!r} "
                f"required={format_version(active.vss_extension_version)!r}"
            )
        expected_vss_build = active.vss_extension_build
        observed_vss_build = versions.vss_extension_build
        if observed_vss_build is None:
            observed_vss_build = _normalize_build_id(
                name=active.vss_extension_name,
                version=versions.vss_extension,
                source=active.vss_extension_source,
            )
        if observed_vss_build != expected_vss_build:
            problems.append(
                f"VSS extension build mismatch: observed={observed_vss_build!r} "
                f"required={expected_vss_build!r}"
            )

    client_proto = versions.client_protocol
    server_proto = versions.server_protocol
    if require_protocol or client_proto is not None or server_proto is not None:
        if client_proto is None or server_proto is None:
            if require_protocol:
                problems.append("Quack protocol version is missing on client or server")
        else:
            if client_proto not in active.supported_protocol_versions:
                problems.append(
                    f"unsupported client Quack protocol version: {client_proto}"
                )
            if server_proto not in active.supported_protocol_versions:
                problems.append(
                    f"unsupported server Quack protocol version: {server_proto}"
                )
            if client_proto != server_proto:
                problems.append(
                    f"client/server Quack protocol mismatch: client={client_proto} "
                    f"server={server_proto}"
                )

    if problems:
        raise VersionMismatchError("; ".join(problems))


# ---------------------------------------------------------------------------
# Feature gates and transport fallback
# ---------------------------------------------------------------------------


def evaluate_feature_gate(
    name: FeatureName | str,
    *,
    requested: bool,
    capability: CapabilityRecord | None,
    beta: bool | None = None,
) -> FeatureGate:
    """Resolve an optional feature gate from a capability record.

    Quack and VSS are never import-time requirements.  When the gate is not
    requested, the feature is ``DISABLED`` with a documented fallback.  When
    requested but mismatched, the gate fails closed (``MISMATCH``).
    """

    feature = FeatureName(name) if not isinstance(name, FeatureName) else name
    if feature is FeatureName.QUACK:
        fallback = TransportMode.LOCAL.value
        default_beta = True
    else:
        fallback = "exact_search"
        default_beta = False
    effective_beta = default_beta if beta is None else bool(beta)

    if not requested:
        return FeatureGate(
            name=feature,
            state=FeatureGateState.DISABLED,
            requested=False,
            capability=capability,
            fallback=fallback,
            reason=f"{feature.value} feature gate is off; using {fallback} fallback",
            beta=effective_beta if feature is FeatureName.QUACK else None,
        )

    if capability is None:
        return FeatureGate(
            name=feature,
            state=FeatureGateState.UNAVAILABLE,
            requested=True,
            capability=None,
            fallback=fallback,
            reason=f"{feature.value} capability was not probed",
            beta=effective_beta if feature is FeatureName.QUACK else None,
        )

    if capability.status is CapabilityStatus.MISMATCH:
        return FeatureGate(
            name=feature,
            state=FeatureGateState.MISMATCH,
            requested=True,
            capability=capability,
            fallback=None,
            reason=capability.reason or f"{feature.value} version mismatch (fail closed)",
            beta=effective_beta if feature is FeatureName.QUACK else None,
        )

    if capability.status is CapabilityStatus.AVAILABLE:
        reason = capability.reason
        if feature is FeatureName.QUACK and effective_beta:
            reason = reason or QUACK_STATUS_REASON
        return FeatureGate(
            name=feature,
            state=FeatureGateState.ENABLED,
            requested=True,
            capability=capability,
            fallback=None,
            reason=reason,
            beta=effective_beta if feature is FeatureName.QUACK else None,
        )

    if capability.status is CapabilityStatus.DISABLED:
        return FeatureGate(
            name=feature,
            state=FeatureGateState.DISABLED,
            requested=True,
            capability=capability,
            fallback=fallback,
            reason=capability.reason or f"{feature.value} disabled",
            beta=effective_beta if feature is FeatureName.QUACK else None,
        )

    return FeatureGate(
        name=feature,
        state=FeatureGateState.UNAVAILABLE,
        requested=True,
        capability=capability,
        fallback=fallback,
        reason=capability.reason or f"{feature.value} unavailable",
        beta=effective_beta if feature is FeatureName.QUACK else None,
    )


def resolve_transport(
    *,
    quack_gate: FeatureGate,
    duckdb_ok: bool,
) -> TransportResolution:
    """Select Quack remote transport or safe local fallback.

    A Quack version/protocol mismatch fails closed (no silent remote use).
    Missing or disabled Quack falls back to the local in-process transport.
    """

    if not duckdb_ok:
        return TransportResolution(
            mode=TransportMode.LOCAL,
            quack_requested=quack_gate.requested,
            quack_available=False,
            fell_back=False,
            reason="DuckDB runtime is not available; local transport cannot run",
            local_fallback_available=False,
        )

    if quack_gate.state is FeatureGateState.MISMATCH:
        return TransportResolution(
            mode=TransportMode.LOCAL,
            quack_requested=True,
            quack_available=False,
            fell_back=False,
            reason=(
                quack_gate.reason
                or "Quack version/protocol mismatch fails closed; remote transport refused"
            ),
            local_fallback_available=True,
        )

    if quack_gate.enabled:
        return TransportResolution(
            mode=TransportMode.QUACK_REMOTE,
            quack_requested=True,
            quack_available=True,
            fell_back=False,
            reason=quack_gate.reason or "Quack transport feature gate enabled",
            local_fallback_available=True,
        )

    if quack_gate.requested:
        return TransportResolution(
            mode=TransportMode.LOCAL,
            quack_requested=True,
            quack_available=False,
            fell_back=True,
            reason=quack_gate.reason
            or "Quack unavailable; safe local transport fallback",
            local_fallback_available=True,
        )

    return TransportResolution(
        mode=TransportMode.LOCAL,
        quack_requested=False,
        quack_available=False,
        fell_back=False,
        reason="Quack feature gate disabled; local transport is the default",
        local_fallback_available=True,
    )


def require_capability(
    result: CapabilityProbeResult,
    kind: CapabilityKind | str,
) -> CapabilityRecord:
    """Return a capability or raise if it is not safely usable."""

    key = kind.value if isinstance(kind, CapabilityKind) else str(kind)
    record = result.capabilities.get(key)
    if record is None:
        raise CapabilityUnavailableError(f"capability not present in probe: {key}")
    if record.status is CapabilityStatus.MISMATCH:
        raise VersionMismatchError(
            record.reason or f"capability {key} version mismatch (fail closed)"
        )
    if not record.ok:
        raise CapabilityUnavailableError(
            record.reason or f"capability {key} is not available ({record.status.value})"
        )
    return record


# ---------------------------------------------------------------------------
# Runtime observation helpers (never used at import time)
# ---------------------------------------------------------------------------


def _try_import_duckdb() -> Any | None:
    try:
        import duckdb  # type: ignore[import-not-found]
    except ImportError:
        return None
    return duckdb


def _query_scalar(connection: Any, sql: str) -> Any:
    result = connection.execute(sql).fetchone()
    if result is None:
        return None
    return result[0]


def _list_loaded_extensions(connection: Any) -> Mapping[str, str]:
    """Return mapping of extension name → version for loaded extensions."""

    try:
        rows = connection.execute(
            "SELECT extension_name, extension_version "
            "FROM duckdb_extensions() WHERE loaded = true"
        ).fetchall()
    except Exception:
        return {}
    loaded: dict[str, str] = {}
    for row in rows or ():
        if not row or len(row) < 2:
            continue
        name = str(row[0] or "").strip().lower()
        version = str(row[1] or "").strip()
        if name:
            loaded[name] = version
    return loaded


def observe_local_duckdb_versions(
    *,
    connection: Any | None = None,
    load_quack: bool = False,
    load_vss: bool = False,
) -> ComponentVersions:
    """Observe local DuckDB and optional extension versions via a connection.

    This is the default runtime observer.  It never auto-installs extensions.
    When ``load_quack`` / ``load_vss`` is true it only attempts ``LOAD`` of an
    already-provisioned artifact; failure leaves the extension absent.
    """

    duckdb = _try_import_duckdb()
    if duckdb is None:
        return ComponentVersions()

    owns_connection = connection is None
    conn = connection
    try:
        if conn is None:
            conn = duckdb.connect(database=":memory:")
        client_version = str(getattr(duckdb, "__version__", "") or "")
        try:
            pragma_version = _query_scalar(conn, "SELECT version()")
            if pragma_version:
                client_version = str(pragma_version)
        except Exception:
            pass

        if load_quack:
            try:
                conn.execute(f"LOAD {PINNED_QUACK_EXTENSION_NAME}")
            except Exception:
                pass
        if load_vss:
            try:
                conn.execute(f"LOAD {PINNED_VSS_EXTENSION_NAME}")
            except Exception:
                pass

        loaded = _list_loaded_extensions(conn)
        quack_version = loaded.get(PINNED_QUACK_EXTENSION_NAME)
        vss_version = loaded.get(PINNED_VSS_EXTENSION_NAME)
        quack_build = None
        if quack_version:
            quack_build = _normalize_build_id(
                name=PINNED_QUACK_EXTENSION_NAME,
                version=quack_version,
                source=PINNED_QUACK_EXTENSION_SOURCE,
            )
        vss_build = None
        if vss_version:
            vss_build = _normalize_build_id(
                name=PINNED_VSS_EXTENSION_NAME,
                version=vss_version,
                source=PINNED_VSS_EXTENSION_SOURCE,
            )
        return ComponentVersions(
            client_duckdb=client_version or None,
            server_duckdb=client_version or None,
            quack_extension=quack_version,
            quack_extension_build=quack_build,
            quack_extension_source=(
                PINNED_QUACK_EXTENSION_SOURCE if quack_version else None
            ),
            vss_extension=vss_version,
            vss_extension_build=vss_build,
            client_protocol=None,
            server_protocol=None,
        )
    finally:
        if owns_connection and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main probe
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    """Inputs controlling which optional capabilities are requested."""

    enable_quack: bool = False
    enable_vss: bool = False
    require_server: bool = False
    require_protocol: bool = False
    server_duckdb: str | None = None
    client_protocol: int | None = None
    server_protocol: int | None = None
    local_fallback: bool = True


VersionObserver = Callable[[], ComponentVersions]


def _record_duckdb_runtime(
    versions: ComponentVersions,
    policy: VersionPolicy,
) -> CapabilityRecord:
    required = format_version(policy.duckdb_version)
    if versions.client_duckdb is None:
        return CapabilityRecord(
            kind=CapabilityKind.DUCKDB_RUNTIME,
            status=CapabilityStatus.UNAVAILABLE,
            identity={"required": required},
            reason="DuckDB Python package is not installed or not observable",
            required=True,
        )
    if not versions_match_exact(versions.client_duckdb, required):
        return CapabilityRecord(
            kind=CapabilityKind.DUCKDB_RUNTIME,
            status=CapabilityStatus.MISMATCH,
            identity={
                "observed": versions.client_duckdb,
                "required": required,
            },
            reason=(
                f"DuckDB client version mismatch: observed={versions.client_duckdb!r} "
                f"required={required!r}"
            ),
            required=True,
        )
    if versions.server_duckdb is not None and not versions_match_exact(
        versions.server_duckdb, required
    ):
        return CapabilityRecord(
            kind=CapabilityKind.DUCKDB_RUNTIME,
            status=CapabilityStatus.MISMATCH,
            identity={
                "client": versions.client_duckdb,
                "server": versions.server_duckdb,
                "required": required,
            },
            reason=(
                f"DuckDB server version mismatch: observed={versions.server_duckdb!r} "
                f"required={required!r}"
            ),
            required=True,
        )
    if (
        versions.server_duckdb is not None
        and versions.client_duckdb is not None
        and not versions_match_exact(versions.client_duckdb, versions.server_duckdb)
    ):
        return CapabilityRecord(
            kind=CapabilityKind.DUCKDB_RUNTIME,
            status=CapabilityStatus.MISMATCH,
            identity={
                "client": versions.client_duckdb,
                "server": versions.server_duckdb,
            },
            reason=(
                f"client/server DuckDB version mismatch: "
                f"client={versions.client_duckdb!r} server={versions.server_duckdb!r}"
            ),
            required=True,
        )
    return CapabilityRecord(
        kind=CapabilityKind.DUCKDB_RUNTIME,
        status=CapabilityStatus.AVAILABLE,
        identity={
            "client": versions.client_duckdb,
            "server": versions.server_duckdb,
            "required": required,
        },
        reason=f"DuckDB {versions.client_duckdb} matches pin {required}",
        required=True,
    )


def _record_quack_transport(
    versions: ComponentVersions,
    policy: VersionPolicy,
    *,
    requested: bool,
) -> CapabilityRecord:
    maturity = quack_maturity_status(policy)
    beta = maturity is QuackMaturity.BETA
    identity_base: dict[str, Any] = {
        "required_build": policy.quack_extension_build,
        "required_version": format_version(policy.quack_extension_version),
        "source": policy.quack_extension_source,
        "beta": beta,
        "maturity": maturity.value,
        "status_reason": policy.quack_status_reason,
    }
    if not requested:
        return CapabilityRecord(
            kind=CapabilityKind.QUACK_TRANSPORT,
            status=CapabilityStatus.DISABLED,
            identity=identity_base,
            reason=(
                "Quack transport feature gate is off "
                f"(beta={beta}; fallback={TransportMode.LOCAL.value})"
            ),
            required=False,
        )
    if versions.quack_extension is None:
        return CapabilityRecord(
            kind=CapabilityKind.QUACK_TRANSPORT,
            status=CapabilityStatus.UNAVAILABLE,
            identity=identity_base,
            reason=(
                "Quack extension is not loaded; optional feature remains gated "
                f"with {TransportMode.LOCAL.value} fallback (beta={beta})"
            ),
            required=False,
        )
    try:
        assert_versions_compatible(
            versions,
            policy,
            require_quack_extension=True,
            require_protocol=False,
        )
    except VersionMismatchError as exc:
        return CapabilityRecord(
            kind=CapabilityKind.QUACK_TRANSPORT,
            status=CapabilityStatus.MISMATCH,
            identity={
                **identity_base,
                "observed": versions.quack_extension,
                "observed_build": versions.quack_extension_build,
            },
            reason=str(exc),
            required=False,
        )
    return CapabilityRecord(
        kind=CapabilityKind.QUACK_TRANSPORT,
        status=CapabilityStatus.AVAILABLE,
        identity={
            **identity_base,
            "observed": versions.quack_extension,
            "observed_build": versions.quack_extension_build
            or _normalize_build_id(
                name=policy.quack_extension_name,
                version=versions.quack_extension,
                source=versions.quack_extension_source or policy.quack_extension_source,
            ),
        },
        reason=(
            f"Quack extension build {policy.quack_extension_build} is available "
            f"(explicit beta={beta})"
        ),
        required=False,
    )


def _record_vss_index(
    versions: ComponentVersions,
    policy: VersionPolicy,
    *,
    requested: bool,
) -> CapabilityRecord:
    identity_base: dict[str, Any] = {
        "required_build": policy.vss_extension_build,
        "required_version": format_version(policy.vss_extension_version),
        "fallback": "exact_search",
        "identity_authority": False,
    }
    if not requested:
        return CapabilityRecord(
            kind=CapabilityKind.VSS_INDEX,
            status=CapabilityStatus.DISABLED,
            identity=identity_base,
            reason="VSS feature gate is off; exact FLOAT[N] search remains available",
            required=False,
        )
    if versions.vss_extension is None:
        return CapabilityRecord(
            kind=CapabilityKind.VSS_INDEX,
            status=CapabilityStatus.UNAVAILABLE,
            identity=identity_base,
            reason=(
                "VSS extension is not loaded; optional acceleration gated off "
                "with exact-search fallback"
            ),
            required=False,
        )
    try:
        assert_versions_compatible(
            versions,
            policy,
            require_vss_extension=True,
        )
    except VersionMismatchError as exc:
        return CapabilityRecord(
            kind=CapabilityKind.VSS_INDEX,
            status=CapabilityStatus.MISMATCH,
            identity={
                **identity_base,
                "observed": versions.vss_extension,
                "observed_build": versions.vss_extension_build,
            },
            reason=str(exc),
            required=False,
        )
    return CapabilityRecord(
        kind=CapabilityKind.VSS_INDEX,
        status=CapabilityStatus.AVAILABLE,
        identity={
            **identity_base,
            "observed": versions.vss_extension,
            "observed_build": versions.vss_extension_build
            or _normalize_build_id(
                name=policy.vss_extension_name,
                version=versions.vss_extension,
                source=policy.vss_extension_source,
            ),
        },
        reason="VSS extension is available as rebuildable derived acceleration only",
        required=False,
    )


def _record_protocol(
    versions: ComponentVersions,
    policy: VersionPolicy,
    *,
    requested: bool,
) -> CapabilityRecord:
    identity_base: dict[str, Any] = {
        "supported": sorted(policy.supported_protocol_versions),
        "default": policy.default_protocol_version,
        "client": versions.client_protocol,
        "server": versions.server_protocol,
    }
    if not requested:
        return CapabilityRecord(
            kind=CapabilityKind.PROTOCOL,
            status=CapabilityStatus.DISABLED,
            identity=identity_base,
            reason="Quack protocol negotiation not requested",
            required=False,
        )
    if versions.client_protocol is None or versions.server_protocol is None:
        return CapabilityRecord(
            kind=CapabilityKind.PROTOCOL,
            status=CapabilityStatus.UNAVAILABLE,
            identity=identity_base,
            reason="client or server Quack protocol version not provided",
            required=False,
        )
    try:
        assert_versions_compatible(
            versions,
            policy,
            require_protocol=True,
        )
    except VersionMismatchError as exc:
        return CapabilityRecord(
            kind=CapabilityKind.PROTOCOL,
            status=CapabilityStatus.MISMATCH,
            identity=identity_base,
            reason=str(exc),
            required=False,
        )
    return CapabilityRecord(
        kind=CapabilityKind.PROTOCOL,
        status=CapabilityStatus.AVAILABLE,
        identity=identity_base,
        reason=(
            f"client/server Quack protocol version {versions.client_protocol} "
            "is supported and matched"
        ),
        required=False,
    )


def probe_capabilities(
    request: ProbeRequest | None = None,
    *,
    policy: VersionPolicy | None = None,
    versions: ComponentVersions | None = None,
    observe: VersionObserver | None = None,
    fail_closed: bool = True,
) -> CapabilityProbeResult:
    """Probe DuckDB / Quack / VSS / protocol capabilities under the version policy.

    Parameters
    ----------
    request:
        Which optional features and remote components are requested.
    policy:
        Dependency pin; defaults to :data:`DEFAULT_VERSION_POLICY`.
    versions:
        Pre-observed versions (tests inject these).  When omitted, ``observe``
        or the default local DuckDB observer is used.
    observe:
        Callable returning :class:`ComponentVersions`.  Used only when
        ``versions`` is ``None``.
    fail_closed:
        When true (default), version mismatches mark the overall result not ok
        and refuse remote Quack transport.

    Notes
    -----
    Importing this module never runs this probe.  Quack and VSS remain optional
    feature gates; only the DuckDB runtime pin is required for local operation.
    """

    active_policy = policy or DEFAULT_VERSION_POLICY
    active_request = request or ProbeRequest()

    if versions is None:
        if observe is not None:
            observed = observe()
        else:
            observed = observe_local_duckdb_versions(
                load_quack=active_request.enable_quack,
                load_vss=active_request.enable_vss,
            )
        # Merge explicit server / protocol fields from the request.
        observed = ComponentVersions(
            client_duckdb=observed.client_duckdb,
            server_duckdb=active_request.server_duckdb or observed.server_duckdb,
            quack_extension=observed.quack_extension,
            quack_extension_build=observed.quack_extension_build,
            quack_extension_source=observed.quack_extension_source,
            vss_extension=observed.vss_extension,
            vss_extension_build=observed.vss_extension_build,
            client_protocol=active_request.client_protocol
            if active_request.client_protocol is not None
            else observed.client_protocol,
            server_protocol=active_request.server_protocol
            if active_request.server_protocol is not None
            else observed.server_protocol,
        )
    else:
        observed = versions
        if active_request.server_duckdb is not None and observed.server_duckdb is None:
            observed = ComponentVersions(
                client_duckdb=observed.client_duckdb,
                server_duckdb=active_request.server_duckdb,
                quack_extension=observed.quack_extension,
                quack_extension_build=observed.quack_extension_build,
                quack_extension_source=observed.quack_extension_source,
                vss_extension=observed.vss_extension,
                vss_extension_build=observed.vss_extension_build,
                client_protocol=(
                    active_request.client_protocol
                    if active_request.client_protocol is not None
                    else observed.client_protocol
                ),
                server_protocol=(
                    active_request.server_protocol
                    if active_request.server_protocol is not None
                    else observed.server_protocol
                ),
            )
        elif (
            active_request.client_protocol is not None
            or active_request.server_protocol is not None
        ):
            observed = ComponentVersions(
                client_duckdb=observed.client_duckdb,
                server_duckdb=observed.server_duckdb,
                quack_extension=observed.quack_extension,
                quack_extension_build=observed.quack_extension_build,
                quack_extension_source=observed.quack_extension_source,
                vss_extension=observed.vss_extension,
                vss_extension_build=observed.vss_extension_build,
                client_protocol=(
                    active_request.client_protocol
                    if active_request.client_protocol is not None
                    else observed.client_protocol
                ),
                server_protocol=(
                    active_request.server_protocol
                    if active_request.server_protocol is not None
                    else observed.server_protocol
                ),
            )

    protocol_requested = (
        active_request.enable_quack
        or active_request.require_protocol
        or observed.client_protocol is not None
        or observed.server_protocol is not None
    )

    duckdb_record = _record_duckdb_runtime(observed, active_policy)
    quack_record = _record_quack_transport(
        observed, active_policy, requested=active_request.enable_quack
    )
    vss_record = _record_vss_index(
        observed, active_policy, requested=active_request.enable_vss
    )
    protocol_record = _record_protocol(
        observed, active_policy, requested=protocol_requested
    )

    # When Quack is requested, a protocol mismatch also fails the transport.
    if (
        active_request.enable_quack
        and protocol_record.status is CapabilityStatus.MISMATCH
        and quack_record.status is CapabilityStatus.AVAILABLE
    ):
        quack_record = CapabilityRecord(
            kind=CapabilityKind.QUACK_TRANSPORT,
            status=CapabilityStatus.MISMATCH,
            identity=dict(quack_record.identity),
            reason=protocol_record.reason,
            required=False,
        )

    capabilities: dict[str, CapabilityRecord] = {
        CapabilityKind.DUCKDB_RUNTIME.value: duckdb_record,
        CapabilityKind.QUACK_TRANSPORT.value: quack_record,
        CapabilityKind.VSS_INDEX.value: vss_record,
        CapabilityKind.PROTOCOL.value: protocol_record,
    }

    maturity = quack_maturity_status(active_policy)
    quack_gate = evaluate_feature_gate(
        FeatureName.QUACK,
        requested=active_request.enable_quack,
        capability=quack_record,
        beta=maturity is QuackMaturity.BETA,
    )
    vss_gate = evaluate_feature_gate(
        FeatureName.VSS,
        requested=active_request.enable_vss,
        capability=vss_record,
    )

    duckdb_ok = duckdb_record.status is CapabilityStatus.AVAILABLE
    transport = resolve_transport(quack_gate=quack_gate, duckdb_ok=duckdb_ok)

    mismatches = tuple(
        record.reason or f"{key} mismatch"
        for key, record in capabilities.items()
        if record.status is CapabilityStatus.MISMATCH
    )

    # Fail closed: any mismatch, or a required DuckDB runtime that is not ok.
    hard_failure = bool(mismatches) or not duckdb_record.ok
    if fail_closed and hard_failure:
        ok = False
    else:
        ok = duckdb_record.ok and not mismatches

    # Remote transport is refused when fail-closed and mismatched.
    if fail_closed and mismatches and transport.mode is TransportMode.QUACK_REMOTE:
        transport = TransportResolution(
            mode=TransportMode.LOCAL,
            quack_requested=transport.quack_requested,
            quack_available=False,
            fell_back=False,
            reason="fail closed: refusing Quack remote transport after version mismatch",
            local_fallback_available=True,
        )

    return CapabilityProbeResult(
        schema=CAPABILITY_PROBE_SCHEMA,
        policy=active_policy,
        versions=observed,
        capabilities=MappingProxyType(capabilities),
        feature_gates=MappingProxyType(
            {
                FeatureName.QUACK.value: quack_gate,
                FeatureName.VSS.value: vss_gate,
            }
        ),
        transport=transport,
        quack_maturity=maturity,
        quack_beta=maturity is QuackMaturity.BETA,
        quack_status_reason=active_policy.quack_status_reason,
        fail_closed=fail_closed,
        mismatches=mismatches,
        ok=ok,
    )
