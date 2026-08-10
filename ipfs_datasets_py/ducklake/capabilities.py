"""Fail-closed DuckLake v1.0 capability contract (DQK-084).

Binds the DuckDB version, platform-specific ducklake and quack artifacts,
required httpfs/cloud-adapter extension artifacts and digests, DuckLake
specification and catalog version, supported maintenance functions, explicit
LOAD order, and disabled automatic install, load, and migration behavior to
the DQK-082 environment receipt.

Import is side-effect free: this module never imports ``duckdb``, never LOADs
extensions, never ATTACHes a catalog, never opens sockets, and never installs
packages. Runtime observation is optional and injected under test.

DuckLake is optional relative to the authoritative control plane: disabling
the DuckLake feature gate must not affect ``ipfs_datasets_py.duckdb_control``
CAS authority, plan generation, or task scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

__all__ = [
    "ATTACH_SAFE_OPTIONS",
    "AUTOMATIC_CATALOG_MIGRATION",
    "AUTOMATIC_EXTENSION_INSTALL",
    "AUTOMATIC_EXTENSION_LOAD",
    "CAPABILITY_PROBE_SCHEMA",
    "CONFIGURATION_LOCK_SETTINGS",
    "CatalogMismatchError",
    "CapabilityError",
    "CapabilityKind",
    "CapabilityProbeResult",
    "CapabilityRecord",
    "CapabilityStatus",
    "CapabilityUnavailableError",
    "DEFAULT_CAPABILITY_POLICY",
    "DEFAULT_OBJECT_STORE_ADAPTER",
    "DUCKLAKE_FEATURE_DISABLED_REASON",
    "DuckLakeCapabilityPolicy",
    "DuckLakeFeatureGate",
    "DuckLakeFeatureState",
    "ENVIRONMENT_RECEIPT_SCHEMA",
    "EXPLICIT_LOAD_ORDER",
    "EnvironmentReceiptBinding",
    "ExtensionArtifactPin",
    "ExtensionDigestMismatchError",
    "FeatureName",
    "LOAD_BEFORE_CONFIGURATION_LOCK",
    "MaintenanceFunction",
    "ObjectStoreAdapter",
    "ObservedCatalogState",
    "ObservedExtensionState",
    "ObservedRuntimeState",
    "PINNED_DUCKLAKE_EXTENSION_BUILD",
    "PINNED_HTTPFS_EXTENSION_BUILD",
    "PINNED_QUACK_EXTENSION_BUILD",
    "PINNED_PLATFORM_DIGESTS",
    "PreflightAttachResult",
    "ProbeRequest",
    "REQUIRED_DUCKDB_VERSION",
    "REQUIRED_DUCKDB_VERSION_TEXT",
    "REQUIRED_DUCKLAKE_CATALOG_VERSION",
    "REQUIRED_DUCKLAKE_SPECIFICATION_VERSION",
    "SUPPORTED_MAINTENANCE_FUNCTIONS",
    "SUPPORTED_PLATFORMS",
    "VersionMismatchError",
    "assert_compatible_before_attach",
    "attest_extension_digests",
    "bind_environment_receipt",
    "configuration_lock_plan",
    "evaluate_ducklake_feature_gate",
    "explicit_load_order",
    "format_version",
    "parse_version",
    "platform_extension_pins",
    "policy_pin_summary",
    "preflight_attach",
    "probe_ducklake_capabilities",
    "require_capability",
    "versions_match_exact",
]


# ---------------------------------------------------------------------------
# Schema and version pins (authoritative for DuckLake catalog owners)
# ---------------------------------------------------------------------------

CAPABILITY_PROBE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-capability-probe@1"
)
ENVIRONMENT_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-candidate-environment-receipt@1"
)
EXTENSION_PROFILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-extension-profile@1"
)

# Content-addressed implementation generation (not a wire schema field).
_CAPABILITY_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-084-ducklake-capability-contract-20260810"
)

REQUIRED_DUCKDB_VERSION: Final[tuple[int, int, int]] = (1, 5, 5)
REQUIRED_DUCKDB_VERSION_TEXT: Final[str] = "1.5.5"

# DuckLake open specification v1.0 and the matching catalog schema major.
REQUIRED_DUCKLAKE_SPECIFICATION_VERSION: Final[str] = "1.0"
REQUIRED_DUCKLAKE_CATALOG_VERSION: Final[str] = "1.0"

PINNED_QUACK_EXTENSION_NAME: Final[str] = "quack"
PINNED_QUACK_EXTENSION_VERSION: Final[tuple[int, int, int]] = (1, 5, 5)
PINNED_QUACK_EXTENSION_SOURCE: Final[str] = "core"
PINNED_QUACK_EXTENSION_BUILD: Final[str] = "quack@1.5.5+core"

PINNED_DUCKLAKE_EXTENSION_NAME: Final[str] = "ducklake"
PINNED_DUCKLAKE_EXTENSION_VERSION: Final[tuple[int, int, int]] = (1, 5, 5)
PINNED_DUCKLAKE_EXTENSION_SOURCE: Final[str] = "core"
PINNED_DUCKLAKE_EXTENSION_BUILD: Final[str] = "ducklake@1.5.5+core"

PINNED_HTTPFS_EXTENSION_NAME: Final[str] = "httpfs"
PINNED_HTTPFS_EXTENSION_VERSION: Final[tuple[int, int, int]] = (1, 5, 5)
PINNED_HTTPFS_EXTENSION_SOURCE: Final[str] = "core"
PINNED_HTTPFS_EXTENSION_BUILD: Final[str] = "httpfs@1.5.5+core"

# Explicit LOAD order before any configuration lock (matches DQK-082).
# The object-store adapter slot is the third entry and defaults to httpfs.
EXPLICIT_LOAD_ORDER: Final[tuple[str, ...]] = ("quack", "ducklake", "httpfs")
LOAD_BEFORE_CONFIGURATION_LOCK: Final[bool] = True

# Automatic install, load, and catalog migration remain off after provisioning.
AUTOMATIC_EXTENSION_INSTALL: Final[bool] = False
AUTOMATIC_EXTENSION_LOAD: Final[bool] = False
AUTOMATIC_CATALOG_MIGRATION: Final[bool] = False
ALLOW_UNSIGNED_EXTENSIONS: Final[bool] = False

CONFIGURATION_LOCK_SETTINGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
        "allow_unsigned_extensions": "false",
        "ducklake_auto_migration": "false",
    }
)

# Safe non-bootstrap / non-migration ATTACH options (see DQK-085/DQK-090).
ATTACH_SAFE_OPTIONS: Final[Mapping[str, bool]] = MappingProxyType(
    {
        "CREATE_IF_NOT_EXISTS": False,
        "OVERRIDE_DATA_PATH": False,
        "AUTOMATIC_MIGRATION": False,
    }
)

SUPPORTED_PLATFORMS: Final[frozenset[str]] = frozenset(
    {"linux_arm64", "linux_amd64"}
)

# Platform-specific gz/bin digests pinned by requirements/duckdb-quack.lock
# (DQK-082). Values are bare lowercase hex (no "sha256:" prefix).
PINNED_PLATFORM_DIGESTS: Final[Mapping[str, Mapping[str, Mapping[str, str]]]] = (
    MappingProxyType(
        {
            "quack": MappingProxyType(
                {
                    "linux_arm64": MappingProxyType(
                        {
                            "gz_sha256": (
                                "3b8857a7643a527a2ab6045e49bedf11"
                                "f24114bc52e86287e400f75a4e20fbdc"
                            ),
                            "bin_sha256": (
                                "41b2b9292bfb860c5ca8c5f818f9dd7a"
                                "2c6bc24f9c750cffbc3169286fe59f08"
                            ),
                        }
                    ),
                    "linux_amd64": MappingProxyType(
                        {
                            "gz_sha256": (
                                "7b2c417e3797c2d85673655dea420ead"
                                "9bbbb24e686ee8dbe37bef9fa8768207"
                            ),
                            "bin_sha256": (
                                "aa0155c452a882eb8912d59589626a51"
                                "56ab92a8e80952371b78e26e1cf07168"
                            ),
                        }
                    ),
                }
            ),
            "ducklake": MappingProxyType(
                {
                    "linux_arm64": MappingProxyType(
                        {
                            "gz_sha256": (
                                "1813f74b24060d6ae97187b87d221c7e"
                                "cbae67e5321929bc543bc5fdb1dc95b4"
                            ),
                            "bin_sha256": (
                                "d0b57c8e261b89a1ae367c7224f0857c"
                                "fde72ab6cf2609f188e0de9b897b1088"
                            ),
                        }
                    ),
                    "linux_amd64": MappingProxyType(
                        {
                            "gz_sha256": (
                                "733ccf19fedcfd5e0bfaf85993219145"
                                "181099cc411076cabf14933ea16ab452"
                            ),
                            "bin_sha256": (
                                "e51bf9e8d933d0e83780ae096455501b"
                                "542cf962569a2ce5613532d702c08302"
                            ),
                        }
                    ),
                }
            ),
            "httpfs": MappingProxyType(
                {
                    "linux_arm64": MappingProxyType(
                        {
                            "gz_sha256": (
                                "0820e0b5b74efaa23608c239df8e744a"
                                "68943318d530b483a529eace19cb5475"
                            ),
                            "bin_sha256": (
                                "eba6e263e395a83966090f1f11ade636"
                                "30b1b21422f0f2813858d179d42ea1e9"
                            ),
                        }
                    ),
                    "linux_amd64": MappingProxyType(
                        {
                            "gz_sha256": (
                                "7cdd52a3135388718884a9b71e3987ba"
                                "723002121e8e9de399c4ed619d824a05"
                            ),
                            "bin_sha256": (
                                "887c392b1e49128d11667c81e3698d8b"
                                "00dfdeb456771acf66d05a0f74f7b7d8"
                            ),
                        }
                    ),
                }
            ),
        }
    )
)

DUCKLAKE_FEATURE_DISABLED_REASON: Final[str] = (
    "DuckLake feature gate is off; the authoritative DuckDB control plane "
    "continues without lakehouse catalog ownership"
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CapabilityError(ValueError):
    """Invalid capability descriptor, policy field, or probe input."""


class VersionMismatchError(CapabilityError):
    """DuckDB, platform, extension, or catalog versions disagree (fail closed)."""


class CatalogMismatchError(VersionMismatchError):
    """DuckLake catalog or specification version is not admitted."""


class ExtensionDigestMismatchError(VersionMismatchError):
    """An enabled catalog-owner extension digest does not match the receipt."""


class CapabilityUnavailableError(RuntimeError):
    """Required DuckLake capability is absent, disabled, or not safely usable."""


class CapabilityKind(str, Enum):
    """Closed set of DuckLake catalog-owner capabilities."""

    DUCKDB_RUNTIME = "duckdb_runtime"
    DUCKLAKE_EXTENSION = "ducklake_extension"
    QUACK_EXTENSION = "quack_extension"
    OBJECT_STORE_ADAPTER = "object_store_adapter"
    DUCKLAKE_CATALOG = "ducklake_catalog"
    CONFIGURATION_LOCK = "configuration_lock"
    MAINTENANCE = "maintenance"
    ENVIRONMENT_RECEIPT = "environment_receipt"


class CapabilityStatus(str, Enum):
    """Availability of a probed capability.

    ``MISMATCH`` fails closed. ``DISABLED`` means the optional DuckLake gate
    is off and the control plane is unaffected. ``UNAVAILABLE`` means an
    optional runtime is missing or failed to load.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    MISMATCH = "mismatch"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class FeatureName(str, Enum):
    """Optional feature gates owned by this contract."""

    DUCKLAKE = "ducklake"


class DuckLakeFeatureState(str, Enum):
    """Resolved state of the optional DuckLake feature gate."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    MISMATCH = "mismatch"


class ObjectStoreAdapter(str, Enum):
    """Admitted object-store adapters for catalog-owner Parquet data paths.

    Only adapters with platform digests in the DQK-082 lock (currently
    ``httpfs`` for S3-compatible storage) may be selected by default.
    """

    HTTPFS = "httpfs"
    # Reserved for future digest-pinned adapters; not admitted without pins.
    AWS = "aws"
    AZURE = "azure"
    GCS = "gcs"


DEFAULT_OBJECT_STORE_ADAPTER: Final[ObjectStoreAdapter] = ObjectStoreAdapter.HTTPFS


class MaintenanceFunction(str, Enum):
    """Supported explicit DuckLake maintenance CALL targets (never auto-run)."""

    FLUSH_INLINED_DATA = "ducklake_flush_inlined_data"
    MERGE_ADJACENT_FILES = "ducklake_merge_adjacent_files"
    EXPIRE_SNAPSHOTS = "ducklake_expire_snapshots"
    CLEANUP_OLD_FILES = "ducklake_cleanup_old_files"
    DELETE_ORPHANED_FILES = "ducklake_delete_orphaned_files"
    REWRITE_DATA_FILES = "ducklake_rewrite_data_files"


SUPPORTED_MAINTENANCE_FUNCTIONS: Final[tuple[str, ...]] = tuple(
    member.value for member in MaintenanceFunction
)


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
        raise CapabilityError(
            f"version must be a string or int sequence, got {type(value).__name__}"
        )
    text = value.strip()
    if not text:
        return ()
    parts = []
    for segment in text.split("."):
        if not segment or not segment[0].isdigit():
            break
        digits: list[str] = []
        for ch in segment:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            break
        parts.append(int("".join(digits)))
        if any(not ch.isdigit() for ch in segment):
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


def _compose_extension_build_id(
    name: str,
    version: str | Sequence[int],
    source: str = "core",
) -> str:
    if isinstance(version, Sequence) and not isinstance(version, (str, bytes)):
        version_text = format_version(version)
    else:
        version_text = format_version(parse_version(str(version)))
    return f"{name}@{version_text}+{source}"


def _normalize_digest(value: str | None) -> str | None:
    """Normalize a digest to bare lowercase hex (strip optional ``sha256:``)."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise CapabilityError(f"digest must be a string, got {type(value).__name__}")
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if any(ch not in "0123456789abcdef" for ch in text):
        raise CapabilityError(f"digest is not lowercase hex: {value!r}")
    return text


def _digest_with_prefix(hex_digest: str) -> str:
    return f"sha256:{hex_digest}"


# ---------------------------------------------------------------------------
# Policy and pin types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtensionArtifactPin:
    """Platform-specific extension artifact digests and build identity."""

    name: str
    platform: str
    gz_sha256: str
    bin_sha256: str
    build: str

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise CapabilityError("extension pin name must be a non-empty string")
        if self.platform not in SUPPORTED_PLATFORMS:
            raise CapabilityError(
                f"unsupported extension platform {self.platform!r}; "
                f"admitted={sorted(SUPPORTED_PLATFORMS)}"
            )
        gz = _normalize_digest(self.gz_sha256)
        bin_ = _normalize_digest(self.bin_sha256)
        if gz is None or bin_ is None:
            raise CapabilityError(f"extension pin {self.name!r} missing digests")
        object.__setattr__(self, "gz_sha256", gz)
        object.__setattr__(self, "bin_sha256", bin_)
        if not self.build or not isinstance(self.build, str):
            raise CapabilityError("extension pin build must be a non-empty string")

    @property
    def gz_digest(self) -> str:
        return _digest_with_prefix(self.gz_sha256)

    @property
    def bin_digest(self) -> str:
        return _digest_with_prefix(self.bin_sha256)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "name": self.name,
                "platform": self.platform,
                "gz_sha256": self.gz_digest,
                "bin_sha256": self.bin_digest,
                "build": self.build,
            }
        )


def platform_extension_pins(
    platform: str,
    *,
    object_store_adapter: ObjectStoreAdapter | str = DEFAULT_OBJECT_STORE_ADAPTER,
) -> Mapping[str, ExtensionArtifactPin]:
    """Return the DQK-082 platform pins for quack, ducklake, and the adapter."""

    if platform not in SUPPORTED_PLATFORMS:
        raise CapabilityError(
            f"unsupported platform {platform!r}; admitted={sorted(SUPPORTED_PLATFORMS)}"
        )
    adapter = (
        object_store_adapter
        if isinstance(object_store_adapter, ObjectStoreAdapter)
        else ObjectStoreAdapter(str(object_store_adapter))
    )
    if adapter is not ObjectStoreAdapter.HTTPFS:
        raise CapabilityError(
            f"object-store adapter {adapter.value!r} is not digest-pinned; "
            f"only {ObjectStoreAdapter.HTTPFS.value!r} is admitted by DQK-082"
        )

    builds = {
        "quack": PINNED_QUACK_EXTENSION_BUILD,
        "ducklake": PINNED_DUCKLAKE_EXTENSION_BUILD,
        "httpfs": PINNED_HTTPFS_EXTENSION_BUILD,
    }
    pins: dict[str, ExtensionArtifactPin] = {}
    for name in ("quack", "ducklake", adapter.value):
        digests = PINNED_PLATFORM_DIGESTS[name][platform]
        pins[name] = ExtensionArtifactPin(
            name=name,
            platform=platform,
            gz_sha256=digests["gz_sha256"],
            bin_sha256=digests["bin_sha256"],
            build=builds[name],
        )
    return MappingProxyType(pins)


@dataclass(frozen=True, slots=True)
class DuckLakeCapabilityPolicy:
    """Immutable DuckLake capability policy bound to DQK-082 pins."""

    duckdb_version: tuple[int, int, int] = REQUIRED_DUCKDB_VERSION
    ducklake_specification_version: str = REQUIRED_DUCKLAKE_SPECIFICATION_VERSION
    ducklake_catalog_version: str = REQUIRED_DUCKLAKE_CATALOG_VERSION
    quack_extension_build: str = PINNED_QUACK_EXTENSION_BUILD
    ducklake_extension_build: str = PINNED_DUCKLAKE_EXTENSION_BUILD
    httpfs_extension_build: str = PINNED_HTTPFS_EXTENSION_BUILD
    object_store_adapter: ObjectStoreAdapter = DEFAULT_OBJECT_STORE_ADAPTER
    explicit_load_order: tuple[str, ...] = EXPLICIT_LOAD_ORDER
    load_before_configuration_lock: bool = LOAD_BEFORE_CONFIGURATION_LOCK
    automatic_extension_install: bool = AUTOMATIC_EXTENSION_INSTALL
    automatic_extension_load: bool = AUTOMATIC_EXTENSION_LOAD
    automatic_catalog_migration: bool = AUTOMATIC_CATALOG_MIGRATION
    allow_unsigned_extensions: bool = ALLOW_UNSIGNED_EXTENSIONS
    configuration_lock_settings: Mapping[str, str] = field(
        default_factory=lambda: CONFIGURATION_LOCK_SETTINGS
    )
    attach_safe_options: Mapping[str, bool] = field(
        default_factory=lambda: ATTACH_SAFE_OPTIONS
    )
    supported_maintenance_functions: tuple[str, ...] = SUPPORTED_MAINTENANCE_FUNCTIONS
    supported_platforms: frozenset[str] = SUPPORTED_PLATFORMS
    environment_receipt_schema: str = ENVIRONMENT_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.object_store_adapter, ObjectStoreAdapter):
            object.__setattr__(
                self,
                "object_store_adapter",
                ObjectStoreAdapter(self.object_store_adapter),
            )
        order = tuple(self.explicit_load_order)
        if len(order) < 3:
            raise CapabilityError("explicit load order must include at least 3 entries")
        if order[0] != "quack" or order[1] != "ducklake":
            raise CapabilityError(
                "explicit load order must start with quack then ducklake "
                f"(got {order!r})"
            )
        if order[2] != self.object_store_adapter.value:
            # Keep order consistent with selected adapter.
            object.__setattr__(
                self,
                "explicit_load_order",
                ("quack", "ducklake", self.object_store_adapter.value),
            )
        else:
            object.__setattr__(self, "explicit_load_order", order)

        # Fail closed on any automatic behaviour left on in the policy itself.
        if self.automatic_extension_install:
            raise CapabilityError("policy refuses automatic extension install")
        if self.automatic_extension_load:
            raise CapabilityError("policy refuses automatic extension load")
        if self.automatic_catalog_migration:
            raise CapabilityError("policy refuses automatic catalog migration")
        if self.allow_unsigned_extensions:
            raise CapabilityError("policy refuses unsigned extensions")
        if not self.load_before_configuration_lock:
            raise CapabilityError(
                "policy requires explicit LOAD before the configuration lock"
            )
        for key, expected in CONFIGURATION_LOCK_SETTINGS.items():
            observed = str(self.configuration_lock_settings.get(key, "")).lower()
            if observed != expected:
                raise CapabilityError(
                    f"configuration lock setting {key} must be {expected!r}, "
                    f"got {observed!r}"
                )
        for key, expected in ATTACH_SAFE_OPTIONS.items():
            if bool(self.attach_safe_options.get(key)) is not expected:
                raise CapabilityError(
                    f"attach option {key} must be {expected!r} for non-bootstrap use"
                )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "duckdb_version": format_version(self.duckdb_version),
                "ducklake_specification_version": self.ducklake_specification_version,
                "ducklake_catalog_version": self.ducklake_catalog_version,
                "quack_extension_build": self.quack_extension_build,
                "ducklake_extension_build": self.ducklake_extension_build,
                "httpfs_extension_build": self.httpfs_extension_build,
                "object_store_adapter": self.object_store_adapter.value,
                "explicit_load_order": list(self.explicit_load_order),
                "load_before_configuration_lock": self.load_before_configuration_lock,
                "automatic_extension_install": self.automatic_extension_install,
                "automatic_extension_load": self.automatic_extension_load,
                "automatic_catalog_migration": self.automatic_catalog_migration,
                "allow_unsigned_extensions": self.allow_unsigned_extensions,
                "configuration_lock_settings": dict(self.configuration_lock_settings),
                "attach_safe_options": dict(self.attach_safe_options),
                "supported_maintenance_functions": list(
                    self.supported_maintenance_functions
                ),
                "supported_platforms": sorted(self.supported_platforms),
                "environment_receipt_schema": self.environment_receipt_schema,
            }
        )


DEFAULT_CAPABILITY_POLICY: Final[DuckLakeCapabilityPolicy] = DuckLakeCapabilityPolicy()


def policy_pin_summary(
    policy: DuckLakeCapabilityPolicy | None = None,
) -> Mapping[str, Any]:
    """Return a stable, JSON-friendly summary of the active DuckLake pins."""

    active = policy or DEFAULT_CAPABILITY_POLICY
    return MappingProxyType(
        {
            "duckdb": format_version(active.duckdb_version),
            "ducklake_specification": active.ducklake_specification_version,
            "ducklake_catalog": active.ducklake_catalog_version,
            "quack_build": active.quack_extension_build,
            "ducklake_build": active.ducklake_extension_build,
            "httpfs_build": active.httpfs_extension_build,
            "object_store_adapter": active.object_store_adapter.value,
            "load_order": list(active.explicit_load_order),
            "automatic_install": active.automatic_extension_install,
            "automatic_load": active.automatic_extension_load,
            "automatic_catalog_migration": active.automatic_catalog_migration,
            "generation": _CAPABILITY_IMPLEMENTATION_GENERATION,
        }
    )


def explicit_load_order(
    *,
    object_store_adapter: ObjectStoreAdapter | str = DEFAULT_OBJECT_STORE_ADAPTER,
    policy: DuckLakeCapabilityPolicy | None = None,
) -> tuple[str, ...]:
    """Return the explicit LOAD order before the configuration lock.

    Order is always ``quack``, ``ducklake``, then the selected object-store
    adapter. Callers must LOAD each entry before applying configuration-lock
    settings.
    """

    active = policy or DEFAULT_CAPABILITY_POLICY
    adapter = (
        object_store_adapter
        if isinstance(object_store_adapter, ObjectStoreAdapter)
        else ObjectStoreAdapter(str(object_store_adapter))
    )
    if adapter is not active.object_store_adapter and adapter is not ObjectStoreAdapter.HTTPFS:
        raise CapabilityError(
            f"object-store adapter {adapter.value!r} is not admitted by the policy"
        )
    return ("quack", "ducklake", adapter.value)


def configuration_lock_plan(
    *,
    object_store_adapter: ObjectStoreAdapter | str = DEFAULT_OBJECT_STORE_ADAPTER,
    policy: DuckLakeCapabilityPolicy | None = None,
) -> Mapping[str, Any]:
    """Return the ordered load + lock plan for a catalog-owner process.

    Phase 1: explicit LOAD of each artifact in ``load_order``.
    Phase 2: apply configuration-lock settings that keep automatic install,
    load, and catalog migration disabled.
    """

    active = policy or DEFAULT_CAPABILITY_POLICY
    order = explicit_load_order(
        object_store_adapter=object_store_adapter, policy=active
    )
    return MappingProxyType(
        {
            "phase": "load_then_lock",
            "load_before_configuration_lock": True,
            "load_order": list(order),
            "configuration_lock_settings": dict(active.configuration_lock_settings),
            "automatic_extension_install": False,
            "automatic_extension_load": False,
            "automatic_catalog_migration": False,
            "attach_safe_options": dict(active.attach_safe_options),
        }
    )


# ---------------------------------------------------------------------------
# Observed runtime / receipt types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservedExtensionState:
    """Observed state of one catalog-owner extension artifact."""

    name: str
    version: str | None = None
    build: str | None = None
    platform: str | None = None
    gz_sha256: str | None = None
    bin_sha256: str | None = None
    loaded: bool = False
    loaded_before_configuration_lock: bool | None = None

    def __post_init__(self) -> None:
        for attr in ("version", "build", "platform", "gz_sha256", "bin_sha256"):
            raw = getattr(self, attr)
            if raw is not None and not isinstance(raw, str):
                raise CapabilityError(f"{attr} must be a string or None")
            if isinstance(raw, str):
                stripped = raw.strip()
                if attr in {"gz_sha256", "bin_sha256"}:
                    object.__setattr__(self, attr, _normalize_digest(stripped or None))
                else:
                    object.__setattr__(self, attr, stripped or None)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "name": self.name,
                "version": self.version,
                "build": self.build,
                "platform": self.platform,
                "gz_sha256": (
                    None if self.gz_sha256 is None else _digest_with_prefix(self.gz_sha256)
                ),
                "bin_sha256": (
                    None
                    if self.bin_sha256 is None
                    else _digest_with_prefix(self.bin_sha256)
                ),
                "loaded": self.loaded,
                "loaded_before_configuration_lock": self.loaded_before_configuration_lock,
            }
        )


@dataclass(frozen=True, slots=True)
class ObservedCatalogState:
    """Observed DuckLake specification / catalog version before ATTACH."""

    specification_version: str | None = None
    catalog_version: str | None = None
    automatic_migration_enabled: bool | None = None

    def __post_init__(self) -> None:
        for attr in ("specification_version", "catalog_version"):
            raw = getattr(self, attr)
            if raw is not None and not isinstance(raw, str):
                raise CapabilityError(f"{attr} must be a string or None")
            if isinstance(raw, str):
                object.__setattr__(self, attr, raw.strip() or None)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "specification_version": self.specification_version,
                "catalog_version": self.catalog_version,
                "automatic_migration_enabled": self.automatic_migration_enabled,
            }
        )


@dataclass(frozen=True, slots=True)
class ObservedRuntimeState:
    """Observed DuckDB / extension / settings state for a catalog owner.

    Optional fields may be ``None``. Blank strings normalize to ``None``.
    """

    duckdb_version: str | None = None
    platform: str | None = None
    extensions: Mapping[str, ObservedExtensionState] = field(default_factory=dict)
    catalog: ObservedCatalogState = field(default_factory=ObservedCatalogState)
    settings: Mapping[str, Any] = field(default_factory=dict)
    load_order_observed: tuple[str, ...] = ()
    configuration_locked: bool = False

    def __post_init__(self) -> None:
        if self.duckdb_version is not None and not isinstance(self.duckdb_version, str):
            raise CapabilityError("duckdb_version must be a string or None")
        if isinstance(self.duckdb_version, str):
            object.__setattr__(
                self, "duckdb_version", self.duckdb_version.strip() or None
            )
        if self.platform is not None and not isinstance(self.platform, str):
            raise CapabilityError("platform must be a string or None")
        if isinstance(self.platform, str):
            object.__setattr__(self, "platform", self.platform.strip() or None)

        normalized_ext: dict[str, ObservedExtensionState] = {}
        for key, value in dict(self.extensions).items():
            if isinstance(value, ObservedExtensionState):
                normalized_ext[str(key)] = value
            elif isinstance(value, Mapping):
                payload = dict(value)
                payload.setdefault("name", key)
                normalized_ext[str(key)] = ObservedExtensionState(**payload)
            else:
                raise CapabilityError(
                    f"extension state for {key!r} must be ObservedExtensionState "
                    "or a mapping"
                )
        object.__setattr__(self, "extensions", MappingProxyType(normalized_ext))

        if not isinstance(self.catalog, ObservedCatalogState):
            if isinstance(self.catalog, Mapping):
                object.__setattr__(self, "catalog", ObservedCatalogState(**dict(self.catalog)))
            else:
                raise CapabilityError("catalog must be ObservedCatalogState or a mapping")

        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))
        object.__setattr__(self, "load_order_observed", tuple(self.load_order_observed))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "duckdb_version": self.duckdb_version,
                "platform": self.platform,
                "extensions": {
                    name: dict(state.as_mapping())
                    for name, state in self.extensions.items()
                },
                "catalog": dict(self.catalog.as_mapping()),
                "settings": dict(self.settings),
                "load_order_observed": list(self.load_order_observed),
                "configuration_locked": self.configuration_locked,
            }
        )


@dataclass(frozen=True, slots=True)
class EnvironmentReceiptBinding:
    """Validated binding of a DQK-082 candidate-environment receipt."""

    schema: str
    receipt_id: str | None
    duckdb_version: str
    platform: str
    quack_build: str
    ducklake_build: str
    httpfs_build: str
    extension_pins: Mapping[str, ExtensionArtifactPin]
    load_order: tuple[str, ...]
    automatic_extension_install_disabled: bool
    automatic_extension_load_disabled: bool
    ducklake_catalog_migration_disabled: bool
    settings: Mapping[str, str]
    raw_receipt: Mapping[str, Any] = field(repr=False, default_factory=dict)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "receipt_id": self.receipt_id,
                "duckdb_version": self.duckdb_version,
                "platform": self.platform,
                "quack_build": self.quack_build,
                "ducklake_build": self.ducklake_build,
                "httpfs_build": self.httpfs_build,
                "extension_pins": {
                    name: dict(pin.as_mapping())
                    for name, pin in self.extension_pins.items()
                },
                "load_order": list(self.load_order),
                "automatic_extension_install_disabled": (
                    self.automatic_extension_install_disabled
                ),
                "automatic_extension_load_disabled": (
                    self.automatic_extension_load_disabled
                ),
                "ducklake_catalog_migration_disabled": (
                    self.ducklake_catalog_migration_disabled
                ),
                "settings": dict(self.settings),
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
class DuckLakeFeatureGate:
    """Resolved optional DuckLake feature gate."""

    name: FeatureName
    state: DuckLakeFeatureState
    requested: bool
    capability: CapabilityRecord | None = None
    reason: str | None = None
    control_plane_affected: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, FeatureName):
            object.__setattr__(self, "name", FeatureName(self.name))
        if not isinstance(self.state, DuckLakeFeatureState):
            object.__setattr__(self, "state", DuckLakeFeatureState(self.state))

    @property
    def enabled(self) -> bool:
        return self.state is DuckLakeFeatureState.ENABLED

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "name": self.name.value,
                "state": self.state.value,
                "requested": self.requested,
                "enabled": self.enabled,
                "reason": self.reason,
                "control_plane_affected": self.control_plane_affected,
                "capability": (
                    None if self.capability is None else dict(self.capability.as_mapping())
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class PreflightAttachResult:
    """Result of fail-closed preflight before a DuckLake ATTACH."""

    allowed: bool
    attach_options: Mapping[str, bool]
    mismatches: tuple[str, ...]
    load_order: tuple[str, ...]
    configuration_lock_settings: Mapping[str, str]
    reason: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "allowed": self.allowed,
                "attach_options": dict(self.attach_options),
                "mismatches": list(self.mismatches),
                "load_order": list(self.load_order),
                "configuration_lock_settings": dict(self.configuration_lock_settings),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class CapabilityProbeResult:
    """Complete DuckLake capability probe receipt for gates and observability."""

    schema: str
    policy: DuckLakeCapabilityPolicy
    observed: ObservedRuntimeState
    capabilities: Mapping[str, CapabilityRecord]
    feature_gate: DuckLakeFeatureGate
    environment_binding: EnvironmentReceiptBinding | None
    configuration_plan: Mapping[str, Any]
    preflight: PreflightAttachResult | None
    fail_closed: bool
    mismatches: tuple[str, ...]
    ok: bool
    control_plane_independent: bool

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "policy": dict(self.policy.as_mapping()),
                "observed": dict(self.observed.as_mapping()),
                "capabilities": {
                    key: dict(record.as_mapping())
                    for key, record in self.capabilities.items()
                },
                "feature_gate": dict(self.feature_gate.as_mapping()),
                "environment_binding": (
                    None
                    if self.environment_binding is None
                    else dict(self.environment_binding.as_mapping())
                ),
                "configuration_plan": dict(self.configuration_plan),
                "preflight": (
                    None if self.preflight is None else dict(self.preflight.as_mapping())
                ),
                "fail_closed": self.fail_closed,
                "mismatches": list(self.mismatches),
                "ok": self.ok,
                "control_plane_independent": self.control_plane_independent,
                "implementation_generation": _CAPABILITY_IMPLEMENTATION_GENERATION,
            }
        )


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    """Inputs controlling which DuckLake capabilities are requested."""

    enable_ducklake: bool = False
    platform: str | None = None
    object_store_adapter: ObjectStoreAdapter | str = DEFAULT_OBJECT_STORE_ADAPTER
    require_environment_receipt: bool = False
    require_extension_digests: bool = True
    require_catalog_version: bool = True
    require_explicit_load_order: bool = True
    perform_attach_preflight: bool = True


# ---------------------------------------------------------------------------
# Environment receipt binding
# ---------------------------------------------------------------------------


def _extension_pin_from_artifact(
    name: str,
    platform: str,
    artifact: Mapping[str, Any],
    *,
    build: str,
) -> ExtensionArtifactPin:
    gz = artifact.get("gz_sha256") or artifact.get("pinned_gz_sha256")
    bin_ = artifact.get("bin_sha256") or artifact.get("pinned_bin_sha256")
    return ExtensionArtifactPin(
        name=name,
        platform=str(artifact.get("platform") or platform),
        gz_sha256=str(gz or ""),
        bin_sha256=str(bin_ or ""),
        build=str(artifact.get("build") or build),
    )


def bind_environment_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    policy: DuckLakeCapabilityPolicy | None = None,
) -> EnvironmentReceiptBinding:
    """Bind and validate a DQK-082 candidate-environment receipt.

    Raises:
        CapabilityError: when the receipt is missing required fields.
        VersionMismatchError: when pins disagree with the capability policy.
        ExtensionDigestMismatchError: when digests disagree with policy pins.
    """

    active = policy or DEFAULT_CAPABILITY_POLICY
    if receipt is None:
        raise CapabilityError("environment receipt is required")
    if not isinstance(receipt, Mapping):
        raise CapabilityError("environment receipt must be a mapping")

    schema = str(receipt.get("schema") or "")
    if schema != active.environment_receipt_schema:
        raise VersionMismatchError(
            f"environment receipt schema mismatch: observed={schema!r} "
            f"required={active.environment_receipt_schema!r}"
        )

    duckdb_section = dict(receipt.get("duckdb") or {})
    duckdb_version = str(
        duckdb_section.get("version")
        or duckdb_section.get("required_version")
        or ""
    ).strip()
    if not versions_match_exact(duckdb_version, active.duckdb_version):
        raise VersionMismatchError(
            f"receipt DuckDB version mismatch: observed={duckdb_version!r} "
            f"required={format_version(active.duckdb_version)!r}"
        )

    platform_section = receipt.get("platform") or {}
    extension_profile = dict(receipt.get("extension_profile") or {})
    platform_name = str(
        extension_profile.get("platform")
        or (
            platform_section.get("extension_platform")
            if isinstance(platform_section, Mapping)
            else None
        )
        or ""
    ).strip()
    if not platform_name:
        # Derive from machine if present (linux + aarch64/x86_64).
        if isinstance(platform_section, Mapping):
            machine = str(platform_section.get("machine") or "").strip().lower()
            system = str(platform_section.get("system") or "").strip().lower()
            if system == "linux" and machine in {"aarch64", "arm64"}:
                platform_name = "linux_arm64"
            elif system == "linux" and machine in {"x86_64", "amd64"}:
                platform_name = "linux_amd64"
    if platform_name not in active.supported_platforms:
        raise VersionMismatchError(
            f"receipt platform mismatch: observed={platform_name!r} "
            f"admitted={sorted(active.supported_platforms)}"
        )

    quack = dict(receipt.get("quack") or {})
    ducklake = dict(receipt.get("ducklake") or {})
    quack_build = str(quack.get("build") or "").strip()
    ducklake_build = str(ducklake.get("build") or "").strip()
    if quack_build != active.quack_extension_build:
        raise VersionMismatchError(
            f"receipt Quack build mismatch: observed={quack_build!r} "
            f"required={active.quack_extension_build!r}"
        )
    if ducklake_build != active.ducklake_extension_build:
        raise VersionMismatchError(
            f"receipt DuckLake build mismatch: observed={ducklake_build!r} "
            f"required={active.ducklake_extension_build!r}"
        )

    profile_extensions = dict(extension_profile.get("extensions") or {})
    # Artifact may also live under quack/ducklake.artifact.
    for name, section in (("quack", quack), ("ducklake", ducklake)):
        artifact = section.get("artifact")
        if isinstance(artifact, Mapping) and name not in profile_extensions:
            profile_extensions[name] = artifact

    # httpfs may only appear under extension_profile.extensions.
    expected_builds = {
        "quack": active.quack_extension_build,
        "ducklake": active.ducklake_extension_build,
        "httpfs": active.httpfs_extension_build,
    }
    policy_pins = platform_extension_pins(
        platform_name, object_store_adapter=active.object_store_adapter
    )
    bound_pins: dict[str, ExtensionArtifactPin] = {}
    for name, expected_build in expected_builds.items():
        artifact = profile_extensions.get(name)
        if not isinstance(artifact, Mapping):
            raise CapabilityError(
                f"environment receipt missing extension artifact for {name!r}"
            )
        pin = _extension_pin_from_artifact(
            name, platform_name, artifact, build=expected_build
        )
        policy_pin = policy_pins[name]
        if pin.gz_sha256 != policy_pin.gz_sha256 or pin.bin_sha256 != policy_pin.bin_sha256:
            raise ExtensionDigestMismatchError(
                f"extension {name!r} digest mismatch for platform {platform_name!r}: "
                f"receipt gz={pin.gz_digest} bin={pin.bin_digest}; "
                f"policy gz={policy_pin.gz_digest} bin={policy_pin.bin_digest}"
            )
        if pin.build != expected_build:
            raise VersionMismatchError(
                f"extension {name!r} build mismatch: observed={pin.build!r} "
                f"required={expected_build!r}"
            )
        bound_pins[name] = pin

    load_order_raw = extension_profile.get("load_order") or list(
        active.explicit_load_order
    )
    load_order = tuple(str(item) for item in load_order_raw)
    expected_order = explicit_load_order(policy=active)
    if load_order != expected_order:
        raise VersionMismatchError(
            f"receipt load order mismatch: observed={list(load_order)!r} "
            f"required={list(expected_order)!r}"
        )

    settings = {
        str(k): str(v).lower()
        for k, v in dict(
            extension_profile.get("settings")
            or receipt.get("settings_after_provisioning")
            or {}
        ).items()
    }
    for key, expected in active.configuration_lock_settings.items():
        observed = settings.get(key)
        if observed is not None and observed != expected:
            raise VersionMismatchError(
                f"receipt setting {key} must remain {expected!r}, got {observed!r}"
            )

    auto_install_disabled = bool(
        receipt.get("automatic_extension_install_disabled", True)
    ) and not _truthy(settings.get("autoinstall_known_extensions", "false"))
    auto_load_disabled = bool(
        receipt.get("automatic_extension_load_disabled", True)
    ) and not _truthy(settings.get("autoload_known_extensions", "false"))
    migration_disabled = bool(
        ducklake.get("catalog_migration_disabled", True)
    ) and not _truthy(settings.get("ducklake_auto_migration", "false"))
    if not auto_install_disabled:
        raise VersionMismatchError(
            "environment receipt does not disable automatic extension install"
        )
    if not auto_load_disabled:
        raise VersionMismatchError(
            "environment receipt does not disable automatic extension load"
        )
    if not migration_disabled:
        raise VersionMismatchError(
            "environment receipt does not disable DuckLake catalog migration"
        )

    return EnvironmentReceiptBinding(
        schema=schema,
        receipt_id=(
            str(receipt.get("receipt_id")) if receipt.get("receipt_id") is not None else None
        ),
        duckdb_version=duckdb_version,
        platform=platform_name,
        quack_build=quack_build,
        ducklake_build=ducklake_build,
        httpfs_build=active.httpfs_extension_build,
        extension_pins=MappingProxyType(bound_pins),
        load_order=load_order,
        automatic_extension_install_disabled=True,
        automatic_extension_load_disabled=True,
        ducklake_catalog_migration_disabled=True,
        settings=MappingProxyType(settings),
        raw_receipt=MappingProxyType(dict(receipt)),
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def attest_extension_digests(
    observed: Mapping[str, ObservedExtensionState] | ObservedRuntimeState,
    *,
    platform: str,
    policy: DuckLakeCapabilityPolicy | None = None,
    binding: EnvironmentReceiptBinding | None = None,
    enabled_names: Sequence[str] | None = None,
) -> Mapping[str, ExtensionArtifactPin]:
    """Attest every enabled catalog-owner extension digest (fail closed).

    Compares observed digests to the policy platform pins and, when provided,
    the DQK-082 environment receipt binding.
    """

    active = policy or DEFAULT_CAPABILITY_POLICY
    if isinstance(observed, ObservedRuntimeState):
        platform = observed.platform or platform
        extensions = observed.extensions
    else:
        extensions = observed

    if platform not in active.supported_platforms:
        raise VersionMismatchError(
            f"platform mismatch before ATTACH: observed={platform!r} "
            f"admitted={sorted(active.supported_platforms)}"
        )

    pins = (
        dict(binding.extension_pins)
        if binding is not None
        else dict(
            platform_extension_pins(
                platform, object_store_adapter=active.object_store_adapter
            )
        )
    )
    names = tuple(enabled_names) if enabled_names is not None else tuple(pins.keys())
    attested: dict[str, ExtensionArtifactPin] = {}
    for name in names:
        if name not in pins:
            raise CapabilityError(f"no pin available for enabled extension {name!r}")
        pin = pins[name]
        state = extensions.get(name)
        if state is None:
            raise ExtensionDigestMismatchError(
                f"enabled extension {name!r} is missing from observed state"
            )
        if state.gz_sha256 is None or state.bin_sha256 is None:
            raise ExtensionDigestMismatchError(
                f"enabled extension {name!r} digests are not attested"
            )
        if state.gz_sha256 != pin.gz_sha256 or state.bin_sha256 != pin.bin_sha256:
            raise ExtensionDigestMismatchError(
                f"extension {name!r} digest mismatch: "
                f"observed gz=sha256:{state.gz_sha256} bin=sha256:{state.bin_sha256}; "
                f"required gz={pin.gz_digest} bin={pin.bin_digest}"
            )
        if state.build is not None and state.build != pin.build:
            raise ExtensionDigestMismatchError(
                f"extension {name!r} build mismatch: observed={state.build!r} "
                f"required={pin.build!r}"
            )
        attested[name] = pin
    return MappingProxyType(attested)


# ---------------------------------------------------------------------------
# Fail-closed checks before ATTACH
# ---------------------------------------------------------------------------


def _setting_disabled(settings: Mapping[str, Any], key: str) -> bool:
    if key not in settings:
        # Absent means not proven disabled when required; caller decides.
        return False
    return not _truthy(settings[key])


def _enumerate_pre_attach_mismatches(
    observed: ObservedRuntimeState,
    policy: DuckLakeCapabilityPolicy,
    *,
    binding: EnvironmentReceiptBinding | None,
    require_extension_digests: bool,
    require_catalog_version: bool,
    require_explicit_load_order: bool,
) -> list[str]:
    problems: list[str] = []
    required_duckdb = format_version(policy.duckdb_version)

    if observed.duckdb_version is None:
        problems.append("DuckDB version is missing before ATTACH")
    elif not versions_match_exact(observed.duckdb_version, required_duckdb):
        problems.append(
            f"DuckDB version mismatch before ATTACH: observed={observed.duckdb_version!r} "
            f"required={required_duckdb!r}"
        )

    platform = observed.platform
    if platform is None and binding is not None:
        platform = binding.platform
    if platform is None:
        problems.append("platform is missing before ATTACH")
    elif platform not in policy.supported_platforms:
        problems.append(
            f"platform mismatch before ATTACH: observed={platform!r} "
            f"admitted={sorted(policy.supported_platforms)}"
        )

    expected_order = list(
        binding.load_order if binding is not None else policy.explicit_load_order
    )
    if require_explicit_load_order:
        if not observed.load_order_observed:
            problems.append(
                "explicit LOAD order was not observed before the configuration lock"
            )
        elif list(observed.load_order_observed) != expected_order:
            problems.append(
                f"LOAD order mismatch before ATTACH: "
                f"observed={list(observed.load_order_observed)!r} "
                f"required={expected_order!r}"
            )
        else:
            for name in expected_order:
                state = observed.extensions.get(name)
                if state is None or not state.loaded:
                    problems.append(
                        f"extension {name!r} was not explicitly loaded before "
                        "the configuration lock"
                    )
                elif state.loaded_before_configuration_lock is False:
                    problems.append(
                        f"extension {name!r} was loaded after the configuration lock"
                    )

    # Extension builds / digests.
    for name, required_build in (
        ("quack", policy.quack_extension_build),
        ("ducklake", policy.ducklake_extension_build),
        (policy.object_store_adapter.value, policy.httpfs_extension_build),
    ):
        state = observed.extensions.get(name)
        if state is None:
            problems.append(f"catalog-owner extension {name!r} is missing before ATTACH")
            continue
        if state.build is not None and state.build != required_build:
            problems.append(
                f"{name} build mismatch before ATTACH: observed={state.build!r} "
                f"required={required_build!r}"
            )

    if require_extension_digests and platform in policy.supported_platforms:
        try:
            attest_extension_digests(
                observed,
                platform=platform,
                policy=policy,
                binding=binding,
                enabled_names=expected_order,
            )
        except (ExtensionDigestMismatchError, CapabilityError, VersionMismatchError) as exc:
            problems.append(str(exc))

    if require_catalog_version:
        catalog = observed.catalog
        if catalog.specification_version is None:
            problems.append("DuckLake specification version is missing before ATTACH")
        elif catalog.specification_version != policy.ducklake_specification_version:
            problems.append(
                f"DuckLake specification mismatch before ATTACH: "
                f"observed={catalog.specification_version!r} "
                f"required={policy.ducklake_specification_version!r}"
            )
        if catalog.catalog_version is None:
            problems.append("DuckLake catalog version is missing before ATTACH")
        elif catalog.catalog_version != policy.ducklake_catalog_version:
            problems.append(
                f"DuckLake catalog version mismatch before ATTACH: "
                f"observed={catalog.catalog_version!r} "
                f"required={policy.ducklake_catalog_version!r}"
            )

    # Automatic behaviours must remain off.
    settings = dict(observed.settings)
    for key, label in (
        ("autoinstall_known_extensions", "automatic extension install"),
        ("autoload_known_extensions", "automatic extension load"),
        ("ducklake_auto_migration", "automatic catalog migration"),
        ("allow_unsigned_extensions", "unsigned extensions"),
    ):
        if key in settings and _truthy(settings[key]):
            problems.append(f"{label} remains enabled before ATTACH")
        if key in settings and not _setting_disabled(settings, key):
            # already covered by truthy check
            pass

    if observed.catalog.automatic_migration_enabled is True:
        problems.append("automatic catalog migration remains enabled before ATTACH")

    if binding is not None:
        if not binding.automatic_extension_install_disabled:
            problems.append("environment receipt allows automatic extension install")
        if not binding.automatic_extension_load_disabled:
            problems.append("environment receipt allows automatic extension load")
        if not binding.ducklake_catalog_migration_disabled:
            problems.append("environment receipt allows automatic catalog migration")
        if binding.duckdb_version and observed.duckdb_version:
            if not versions_match_exact(observed.duckdb_version, binding.duckdb_version):
                problems.append(
                    f"runtime/receipt DuckDB mismatch before ATTACH: "
                    f"runtime={observed.duckdb_version!r} "
                    f"receipt={binding.duckdb_version!r}"
                )
        if binding.platform and platform and binding.platform != platform:
            problems.append(
                f"runtime/receipt platform mismatch before ATTACH: "
                f"runtime={platform!r} receipt={binding.platform!r}"
            )

    return problems


def assert_compatible_before_attach(
    observed: ObservedRuntimeState,
    *,
    policy: DuckLakeCapabilityPolicy | None = None,
    binding: EnvironmentReceiptBinding | None = None,
    require_extension_digests: bool = True,
    require_catalog_version: bool = True,
    require_explicit_load_order: bool = True,
) -> None:
    """Fail closed when DuckDB/platform/catalog/extensions disagree before ATTACH.

    Raises:
        VersionMismatchError: on any mismatch (including digests and catalog).
        CatalogMismatchError: when only catalog/spec versions disagree (also a
            VersionMismatchError subclass).
        CapabilityError: on structurally invalid inputs.
    """

    active = policy or DEFAULT_CAPABILITY_POLICY
    problems = _enumerate_pre_attach_mismatches(
        observed,
        active,
        binding=binding,
        require_extension_digests=require_extension_digests,
        require_catalog_version=require_catalog_version,
        require_explicit_load_order=require_explicit_load_order,
    )
    if not problems:
        return

    catalog_only = all(
        "catalog" in item.lower() or "specification" in item.lower()
        for item in problems
    )
    message = "; ".join(problems)
    if catalog_only:
        raise CatalogMismatchError(message)
    raise VersionMismatchError(message)


def preflight_attach(
    observed: ObservedRuntimeState,
    *,
    policy: DuckLakeCapabilityPolicy | None = None,
    binding: EnvironmentReceiptBinding | None = None,
    require_extension_digests: bool = True,
    require_catalog_version: bool = True,
    require_explicit_load_order: bool = True,
    fail_closed: bool = True,
) -> PreflightAttachResult:
    """Return a structured preflight decision; never performs ATTACH itself."""

    active = policy or DEFAULT_CAPABILITY_POLICY
    problems = _enumerate_pre_attach_mismatches(
        observed,
        active,
        binding=binding,
        require_extension_digests=require_extension_digests,
        require_catalog_version=require_catalog_version,
        require_explicit_load_order=require_explicit_load_order,
    )
    order = tuple(
        binding.load_order if binding is not None else active.explicit_load_order
    )
    if problems:
        result = PreflightAttachResult(
            allowed=False,
            attach_options=dict(active.attach_safe_options),
            mismatches=tuple(problems),
            load_order=order,
            configuration_lock_settings=dict(active.configuration_lock_settings),
            reason="DuckDB/platform/catalog mismatch fails before ATTACH",
        )
        if fail_closed:
            raise VersionMismatchError("; ".join(problems))
        return result

    return PreflightAttachResult(
        allowed=True,
        attach_options=dict(active.attach_safe_options),
        mismatches=(),
        load_order=order,
        configuration_lock_settings=dict(active.configuration_lock_settings),
        reason=(
            "explicit LOAD order attested, digests match the environment receipt, "
            "automatic install/load/migration remain off, ATTACH options are safe"
        ),
    )


# ---------------------------------------------------------------------------
# Feature gate (DuckLake optional; control plane independent)
# ---------------------------------------------------------------------------


def evaluate_ducklake_feature_gate(
    *,
    requested: bool,
    capability: CapabilityRecord | None = None,
) -> DuckLakeFeatureGate:
    """Resolve the optional DuckLake feature gate.

    When not requested, DuckLake is ``DISABLED`` and
    ``control_plane_affected`` is always ``False`` so the authoritative
    control plane continues unchanged.
    """

    if not requested:
        return DuckLakeFeatureGate(
            name=FeatureName.DUCKLAKE,
            state=DuckLakeFeatureState.DISABLED,
            requested=False,
            capability=capability,
            reason=DUCKLAKE_FEATURE_DISABLED_REASON,
            control_plane_affected=False,
        )

    if capability is None:
        return DuckLakeFeatureGate(
            name=FeatureName.DUCKLAKE,
            state=DuckLakeFeatureState.UNAVAILABLE,
            requested=True,
            capability=None,
            reason="DuckLake capability was not probed",
            control_plane_affected=False,
        )

    if capability.status is CapabilityStatus.MISMATCH:
        return DuckLakeFeatureGate(
            name=FeatureName.DUCKLAKE,
            state=DuckLakeFeatureState.MISMATCH,
            requested=True,
            capability=capability,
            reason=capability.reason or "DuckLake version mismatch (fail closed)",
            control_plane_affected=False,
        )

    if capability.status is CapabilityStatus.AVAILABLE:
        return DuckLakeFeatureGate(
            name=FeatureName.DUCKLAKE,
            state=DuckLakeFeatureState.ENABLED,
            requested=True,
            capability=capability,
            reason=capability.reason or "DuckLake capability attested",
            control_plane_affected=False,
        )

    if capability.status is CapabilityStatus.DISABLED:
        return DuckLakeFeatureGate(
            name=FeatureName.DUCKLAKE,
            state=DuckLakeFeatureState.DISABLED,
            requested=True,
            capability=capability,
            reason=capability.reason or DUCKLAKE_FEATURE_DISABLED_REASON,
            control_plane_affected=False,
        )

    return DuckLakeFeatureGate(
        name=FeatureName.DUCKLAKE,
        state=DuckLakeFeatureState.UNAVAILABLE,
        requested=True,
        capability=capability,
        reason=capability.reason or "DuckLake unavailable",
        control_plane_affected=False,
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
# Capability record builders + main probe
# ---------------------------------------------------------------------------


def _build_duckdb_record(
    observed: ObservedRuntimeState,
    policy: DuckLakeCapabilityPolicy,
    *,
    required: bool,
) -> CapabilityRecord:
    pin = format_version(policy.duckdb_version)
    if observed.duckdb_version is None:
        return CapabilityRecord(
            kind=CapabilityKind.DUCKDB_RUNTIME,
            status=CapabilityStatus.UNAVAILABLE,
            identity={"required": pin},
            reason="DuckDB version is not observable",
            required=required,
        )
    if not versions_match_exact(observed.duckdb_version, pin):
        return CapabilityRecord(
            kind=CapabilityKind.DUCKDB_RUNTIME,
            status=CapabilityStatus.MISMATCH,
            identity={"observed": observed.duckdb_version, "required": pin},
            reason=(
                f"DuckDB version mismatch: observed={observed.duckdb_version!r} "
                f"required={pin!r}"
            ),
            required=required,
        )
    platform_ok = (
        observed.platform is None or observed.platform in policy.supported_platforms
    )
    if not platform_ok:
        return CapabilityRecord(
            kind=CapabilityKind.DUCKDB_RUNTIME,
            status=CapabilityStatus.MISMATCH,
            identity={
                "duckdb": observed.duckdb_version,
                "platform": observed.platform,
                "admitted_platforms": sorted(policy.supported_platforms),
            },
            reason=(
                f"platform mismatch: observed={observed.platform!r} "
                f"admitted={sorted(policy.supported_platforms)}"
            ),
            required=required,
        )
    return CapabilityRecord(
        kind=CapabilityKind.DUCKDB_RUNTIME,
        status=CapabilityStatus.AVAILABLE,
        identity={
            "duckdb": observed.duckdb_version,
            "platform": observed.platform,
            "required": pin,
        },
        reason="DuckDB runtime matches the pinned 1.5.5 policy",
        required=required,
    )


def _build_extension_record(
    kind: CapabilityKind,
    name: str,
    required_build: str,
    observed: ObservedRuntimeState,
    *,
    platform: str | None,
    policy: DuckLakeCapabilityPolicy,
    binding: EnvironmentReceiptBinding | None,
    required: bool,
    require_digests: bool,
) -> CapabilityRecord:
    state = observed.extensions.get(name)
    identity: dict[str, Any] = {"name": name, "required_build": required_build}
    if state is None:
        return CapabilityRecord(
            kind=kind,
            status=CapabilityStatus.UNAVAILABLE,
            identity=identity,
            reason=f"extension {name!r} is not present",
            required=required,
        )
    identity.update(
        {
            "version": state.version,
            "build": state.build,
            "loaded": state.loaded,
            "loaded_before_configuration_lock": state.loaded_before_configuration_lock,
            "gz_sha256": (
                None if state.gz_sha256 is None else _digest_with_prefix(state.gz_sha256)
            ),
            "bin_sha256": (
                None if state.bin_sha256 is None else _digest_with_prefix(state.bin_sha256)
            ),
        }
    )
    if state.build is not None and state.build != required_build:
        return CapabilityRecord(
            kind=kind,
            status=CapabilityStatus.MISMATCH,
            identity=identity,
            reason=(
                f"{name} build mismatch: observed={state.build!r} "
                f"required={required_build!r}"
            ),
            required=required,
        )
    if require_digests:
        effective_platform = platform or observed.platform
        if effective_platform is None:
            return CapabilityRecord(
                kind=kind,
                status=CapabilityStatus.MISMATCH,
                identity=identity,
                reason=f"platform required to attest {name!r} digests",
                required=required,
            )
        try:
            attest_extension_digests(
                {name: state},
                platform=effective_platform,
                policy=policy,
                binding=binding,
                enabled_names=(name,),
            )
        except (ExtensionDigestMismatchError, CapabilityError, VersionMismatchError) as exc:
            return CapabilityRecord(
                kind=kind,
                status=CapabilityStatus.MISMATCH,
                identity=identity,
                reason=str(exc),
                required=required,
            )
    if not state.loaded:
        return CapabilityRecord(
            kind=kind,
            status=CapabilityStatus.UNAVAILABLE,
            identity=identity,
            reason=f"extension {name!r} is not loaded",
            required=required,
        )
    if state.loaded_before_configuration_lock is False:
        return CapabilityRecord(
            kind=kind,
            status=CapabilityStatus.MISMATCH,
            identity=identity,
            reason=(
                f"extension {name!r} must be loaded before the configuration lock"
            ),
            required=required,
        )
    return CapabilityRecord(
        kind=kind,
        status=CapabilityStatus.AVAILABLE,
        identity=identity,
        reason=f"extension {name!r} attested and loaded before configuration lock",
        required=required,
    )


def _build_catalog_record(
    observed: ObservedRuntimeState,
    policy: DuckLakeCapabilityPolicy,
    *,
    required: bool,
) -> CapabilityRecord:
    catalog = observed.catalog
    identity = {
        "required_specification": policy.ducklake_specification_version,
        "required_catalog": policy.ducklake_catalog_version,
        "observed_specification": catalog.specification_version,
        "observed_catalog": catalog.catalog_version,
        "automatic_migration_enabled": catalog.automatic_migration_enabled,
    }
    if catalog.specification_version is None or catalog.catalog_version is None:
        return CapabilityRecord(
            kind=CapabilityKind.DUCKLAKE_CATALOG,
            status=CapabilityStatus.UNAVAILABLE,
            identity=identity,
            reason="DuckLake specification/catalog version is not observable",
            required=required,
        )
    if catalog.specification_version != policy.ducklake_specification_version:
        return CapabilityRecord(
            kind=CapabilityKind.DUCKLAKE_CATALOG,
            status=CapabilityStatus.MISMATCH,
            identity=identity,
            reason=(
                f"DuckLake specification mismatch: "
                f"observed={catalog.specification_version!r} "
                f"required={policy.ducklake_specification_version!r}"
            ),
            required=required,
        )
    if catalog.catalog_version != policy.ducklake_catalog_version:
        return CapabilityRecord(
            kind=CapabilityKind.DUCKLAKE_CATALOG,
            status=CapabilityStatus.MISMATCH,
            identity=identity,
            reason=(
                f"DuckLake catalog version mismatch: "
                f"observed={catalog.catalog_version!r} "
                f"required={policy.ducklake_catalog_version!r}"
            ),
            required=required,
        )
    if catalog.automatic_migration_enabled is True:
        return CapabilityRecord(
            kind=CapabilityKind.DUCKLAKE_CATALOG,
            status=CapabilityStatus.MISMATCH,
            identity=identity,
            reason="automatic catalog migration remains enabled",
            required=required,
        )
    return CapabilityRecord(
        kind=CapabilityKind.DUCKLAKE_CATALOG,
        status=CapabilityStatus.AVAILABLE,
        identity=identity,
        reason="DuckLake v1.0 specification and catalog version attested",
        required=required,
    )


def _build_configuration_lock_record(
    observed: ObservedRuntimeState,
    policy: DuckLakeCapabilityPolicy,
    *,
    required: bool,
) -> CapabilityRecord:
    settings = dict(observed.settings)
    identity = {
        "required_settings": dict(policy.configuration_lock_settings),
        "observed_settings": {
            key: settings.get(key) for key in policy.configuration_lock_settings
        },
        "load_order_required": list(policy.explicit_load_order),
        "load_order_observed": list(observed.load_order_observed),
        "configuration_locked": observed.configuration_locked,
    }
    for key in policy.configuration_lock_settings:
        if key in settings and _truthy(settings[key]):
            return CapabilityRecord(
                kind=CapabilityKind.CONFIGURATION_LOCK,
                status=CapabilityStatus.MISMATCH,
                identity=identity,
                reason=f"configuration lock violated: {key} is enabled",
                required=required,
            )
    if observed.load_order_observed and list(observed.load_order_observed) != list(
        policy.explicit_load_order
    ):
        return CapabilityRecord(
            kind=CapabilityKind.CONFIGURATION_LOCK,
            status=CapabilityStatus.MISMATCH,
            identity=identity,
            reason=(
                f"LOAD order mismatch: observed={list(observed.load_order_observed)!r} "
                f"required={list(policy.explicit_load_order)!r}"
            ),
            required=required,
        )
    # When settings are fully present and disabled, and load order matches, available.
    present = all(key in settings for key in policy.configuration_lock_settings)
    order_ok = (
        not observed.load_order_observed
        or list(observed.load_order_observed) == list(policy.explicit_load_order)
    )
    if present and order_ok and all(
        not _truthy(settings[key]) for key in policy.configuration_lock_settings
    ):
        return CapabilityRecord(
            kind=CapabilityKind.CONFIGURATION_LOCK,
            status=CapabilityStatus.AVAILABLE,
            identity=identity,
            reason=(
                "automatic install/load/migration remain off after explicit LOAD "
                "and configuration lock"
            ),
            required=required,
        )
    if not present:
        return CapabilityRecord(
            kind=CapabilityKind.CONFIGURATION_LOCK,
            status=CapabilityStatus.UNAVAILABLE,
            identity=identity,
            reason="configuration lock settings are not fully observable",
            required=required,
        )
    return CapabilityRecord(
        kind=CapabilityKind.CONFIGURATION_LOCK,
        status=CapabilityStatus.AVAILABLE,
        identity=identity,
        reason="configuration lock policy admits current settings",
        required=required,
    )


def _build_maintenance_record(
    policy: DuckLakeCapabilityPolicy,
    *,
    required: bool,
) -> CapabilityRecord:
    return CapabilityRecord(
        kind=CapabilityKind.MAINTENANCE,
        status=CapabilityStatus.AVAILABLE,
        identity={
            "supported_functions": list(policy.supported_maintenance_functions),
            "automatic": False,
            "bare_checkpoint_gated": True,
        },
        reason=(
            "supported maintenance functions are explicit CALL targets only; "
            "automatic maintenance and bare CHECKPOINT remain gated"
        ),
        required=required,
    )


def _build_receipt_record(
    binding: EnvironmentReceiptBinding | None,
    *,
    required: bool,
) -> CapabilityRecord:
    if binding is None:
        return CapabilityRecord(
            kind=CapabilityKind.ENVIRONMENT_RECEIPT,
            status=CapabilityStatus.UNAVAILABLE,
            identity={"required_schema": ENVIRONMENT_RECEIPT_SCHEMA},
            reason="DQK-082 environment receipt is not bound",
            required=required,
        )
    return CapabilityRecord(
        kind=CapabilityKind.ENVIRONMENT_RECEIPT,
        status=CapabilityStatus.AVAILABLE,
        identity={
            "schema": binding.schema,
            "receipt_id": binding.receipt_id,
            "platform": binding.platform,
            "duckdb_version": binding.duckdb_version,
            "load_order": list(binding.load_order),
            "automatic_extension_install_disabled": (
                binding.automatic_extension_install_disabled
            ),
            "automatic_extension_load_disabled": (
                binding.automatic_extension_load_disabled
            ),
            "ducklake_catalog_migration_disabled": (
                binding.ducklake_catalog_migration_disabled
            ),
        },
        reason="DQK-082 environment receipt digests and settings attested",
        required=required,
    )


def probe_ducklake_capabilities(
    request: ProbeRequest | None = None,
    *,
    observed: ObservedRuntimeState | None = None,
    environment_receipt: Mapping[str, Any] | None = None,
    environment_binding: EnvironmentReceiptBinding | None = None,
    policy: DuckLakeCapabilityPolicy | None = None,
    fail_closed: bool = True,
) -> CapabilityProbeResult:
    """Probe DuckLake capabilities without side effects.

    When ``enable_ducklake`` is false the feature gate is disabled, the probe
    remains ``ok``, and ``control_plane_independent`` is true so the
    authoritative control plane is unaffected.

    When DuckLake is requested, DuckDB/platform/catalog mismatches are
    recorded as ``MISMATCH`` and, if ``perform_attach_preflight`` is true,
    ATTACH is refused before any catalog open.
    """

    active = policy or DEFAULT_CAPABILITY_POLICY
    req = request or ProbeRequest()
    state = observed or ObservedRuntimeState(platform=req.platform)
    if req.platform and state.platform is None:
        state = ObservedRuntimeState(
            duckdb_version=state.duckdb_version,
            platform=req.platform,
            extensions=state.extensions,
            catalog=state.catalog,
            settings=state.settings,
            load_order_observed=state.load_order_observed,
            configuration_locked=state.configuration_locked,
        )

    adapter = (
        req.object_store_adapter
        if isinstance(req.object_store_adapter, ObjectStoreAdapter)
        else ObjectStoreAdapter(str(req.object_store_adapter))
    )
    if adapter is not active.object_store_adapter:
        # Probe against a temporary policy with the requested adapter only if
        # it is the admitted default; otherwise fail closed when enabled.
        if adapter is not ObjectStoreAdapter.HTTPFS and req.enable_ducklake:
            gate = DuckLakeFeatureGate(
                name=FeatureName.DUCKLAKE,
                state=DuckLakeFeatureState.MISMATCH,
                requested=True,
                reason=(
                    f"object-store adapter {adapter.value!r} is not digest-pinned"
                ),
                control_plane_affected=False,
            )
            return CapabilityProbeResult(
                schema=CAPABILITY_PROBE_SCHEMA,
                policy=active,
                observed=state,
                capabilities=MappingProxyType({}),
                feature_gate=gate,
                environment_binding=None,
                configuration_plan=dict(configuration_lock_plan(policy=active)),
                preflight=None,
                fail_closed=fail_closed,
                mismatches=(gate.reason or "adapter mismatch",),
                ok=False,
                control_plane_independent=True,
            )

    binding = environment_binding
    binding_error: str | None = None
    if binding is None and environment_receipt is not None:
        try:
            binding = bind_environment_receipt(environment_receipt, policy=active)
        except (CapabilityError, VersionMismatchError) as exc:
            binding_error = str(exc)
            if req.require_environment_receipt and req.enable_ducklake and fail_closed:
                # Defer raise into structured mismatches below.
                pass

    required = bool(req.enable_ducklake)
    plan = configuration_lock_plan(
        object_store_adapter=adapter, policy=active
    )

    # DuckLake disabled: control plane independent, no ATTACH path.
    if not req.enable_ducklake:
        duckdb_record = _build_duckdb_record(state, active, required=False)
        capabilities = {
            CapabilityKind.DUCKDB_RUNTIME.value: duckdb_record,
            CapabilityKind.DUCKLAKE_EXTENSION.value: CapabilityRecord(
                kind=CapabilityKind.DUCKLAKE_EXTENSION,
                status=CapabilityStatus.DISABLED,
                identity={"required_build": active.ducklake_extension_build},
                reason=DUCKLAKE_FEATURE_DISABLED_REASON,
                required=False,
            ),
            CapabilityKind.QUACK_EXTENSION.value: CapabilityRecord(
                kind=CapabilityKind.QUACK_EXTENSION,
                status=CapabilityStatus.DISABLED,
                identity={"required_build": active.quack_extension_build},
                reason="Quack catalog-owner extension not required while DuckLake is off",
                required=False,
            ),
            CapabilityKind.OBJECT_STORE_ADAPTER.value: CapabilityRecord(
                kind=CapabilityKind.OBJECT_STORE_ADAPTER,
                status=CapabilityStatus.DISABLED,
                identity={"adapter": adapter.value},
                reason="object-store adapter not required while DuckLake is off",
                required=False,
            ),
            CapabilityKind.DUCKLAKE_CATALOG.value: CapabilityRecord(
                kind=CapabilityKind.DUCKLAKE_CATALOG,
                status=CapabilityStatus.DISABLED,
                identity={
                    "required_specification": active.ducklake_specification_version,
                },
                reason=DUCKLAKE_FEATURE_DISABLED_REASON,
                required=False,
            ),
            CapabilityKind.CONFIGURATION_LOCK.value: CapabilityRecord(
                kind=CapabilityKind.CONFIGURATION_LOCK,
                status=CapabilityStatus.DISABLED,
                identity={"settings": dict(active.configuration_lock_settings)},
                reason="configuration lock not applied while DuckLake is off",
                required=False,
            ),
            CapabilityKind.MAINTENANCE.value: CapabilityRecord(
                kind=CapabilityKind.MAINTENANCE,
                status=CapabilityStatus.DISABLED,
                identity={
                    "supported_functions": list(active.supported_maintenance_functions),
                },
                reason="maintenance surface idle while DuckLake is off",
                required=False,
            ),
            CapabilityKind.ENVIRONMENT_RECEIPT.value: _build_receipt_record(
                binding, required=False
            ),
        }
        gate = evaluate_ducklake_feature_gate(requested=False)
        return CapabilityProbeResult(
            schema=CAPABILITY_PROBE_SCHEMA,
            policy=active,
            observed=state,
            capabilities=MappingProxyType(capabilities),
            feature_gate=gate,
            environment_binding=binding,
            configuration_plan=dict(plan),
            preflight=None,
            fail_closed=fail_closed,
            mismatches=(),
            ok=True,
            control_plane_independent=True,
        )

    # DuckLake requested: full attestation path.
    capabilities = {
        CapabilityKind.DUCKDB_RUNTIME.value: _build_duckdb_record(
            state, active, required=True
        ),
        CapabilityKind.DUCKLAKE_EXTENSION.value: _build_extension_record(
            CapabilityKind.DUCKLAKE_EXTENSION,
            "ducklake",
            active.ducklake_extension_build,
            state,
            platform=state.platform,
            policy=active,
            binding=binding,
            required=True,
            require_digests=req.require_extension_digests,
        ),
        CapabilityKind.QUACK_EXTENSION.value: _build_extension_record(
            CapabilityKind.QUACK_EXTENSION,
            "quack",
            active.quack_extension_build,
            state,
            platform=state.platform,
            policy=active,
            binding=binding,
            required=True,
            require_digests=req.require_extension_digests,
        ),
        CapabilityKind.OBJECT_STORE_ADAPTER.value: _build_extension_record(
            CapabilityKind.OBJECT_STORE_ADAPTER,
            adapter.value,
            active.httpfs_extension_build,
            state,
            platform=state.platform,
            policy=active,
            binding=binding,
            required=True,
            require_digests=req.require_extension_digests,
        ),
        CapabilityKind.DUCKLAKE_CATALOG.value: _build_catalog_record(
            state, active, required=req.require_catalog_version
        ),
        CapabilityKind.CONFIGURATION_LOCK.value: _build_configuration_lock_record(
            state, active, required=True
        ),
        CapabilityKind.MAINTENANCE.value: _build_maintenance_record(
            active, required=False
        ),
        CapabilityKind.ENVIRONMENT_RECEIPT.value: _build_receipt_record(
            binding, required=req.require_environment_receipt
        ),
    }
    if binding_error is not None:
        capabilities[CapabilityKind.ENVIRONMENT_RECEIPT.value] = CapabilityRecord(
            kind=CapabilityKind.ENVIRONMENT_RECEIPT,
            status=CapabilityStatus.MISMATCH,
            identity={"required_schema": ENVIRONMENT_RECEIPT_SCHEMA},
            reason=binding_error,
            required=req.require_environment_receipt,
        )

    mismatches: list[str] = []
    for record in capabilities.values():
        if record.status is CapabilityStatus.MISMATCH:
            mismatches.append(record.reason or record.kind.value)
        elif record.required and record.status is not CapabilityStatus.AVAILABLE:
            mismatches.append(record.reason or f"{record.kind.value} unavailable")

    ducklake_record = capabilities[CapabilityKind.DUCKLAKE_EXTENSION.value]
    # Surface aggregate lakehouse readiness on the feature gate via catalog record
    # when ducklake extension is available but other required pieces failed.
    gate_source = ducklake_record
    if mismatches and ducklake_record.status is CapabilityStatus.AVAILABLE:
        gate_source = CapabilityRecord(
            kind=CapabilityKind.DUCKLAKE_EXTENSION,
            status=CapabilityStatus.MISMATCH,
            identity=dict(ducklake_record.identity),
            reason="; ".join(mismatches),
            required=True,
        )
    gate = evaluate_ducklake_feature_gate(requested=True, capability=gate_source)

    preflight: PreflightAttachResult | None = None
    if req.perform_attach_preflight:
        try:
            preflight = preflight_attach(
                state,
                policy=active,
                binding=binding,
                require_extension_digests=req.require_extension_digests,
                require_catalog_version=req.require_catalog_version,
                require_explicit_load_order=req.require_explicit_load_order,
                fail_closed=False,
            )
            if not preflight.allowed:
                for item in preflight.mismatches:
                    if item not in mismatches:
                        mismatches.append(item)
        except VersionMismatchError as exc:
            mismatches.append(str(exc))
            preflight = PreflightAttachResult(
                allowed=False,
                attach_options=dict(active.attach_safe_options),
                mismatches=tuple(mismatches),
                load_order=tuple(active.explicit_load_order),
                configuration_lock_settings=dict(active.configuration_lock_settings),
                reason="DuckDB/platform/catalog mismatch fails before ATTACH",
            )

    ok = not mismatches and gate.enabled
    if fail_closed and mismatches and req.perform_attach_preflight:
        # Probe itself returns structured failure; callers that need a raise use
        # assert_compatible_before_attach / require_capability.
        pass

    return CapabilityProbeResult(
        schema=CAPABILITY_PROBE_SCHEMA,
        policy=active,
        observed=state,
        capabilities=MappingProxyType(capabilities),
        feature_gate=gate,
        environment_binding=binding,
        configuration_plan=dict(plan),
        preflight=preflight,
        fail_closed=fail_closed,
        mismatches=tuple(mismatches),
        ok=ok,
        control_plane_independent=True,
    )


# Type alias kept for callers that inject custom observers later.
RuntimeObserver = Callable[[], ObservedRuntimeState]
"""Optional observer callable returning :class:`ObservedRuntimeState`."""
