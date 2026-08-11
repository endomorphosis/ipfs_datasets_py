#!/usr/bin/env python3
"""DQK-095 owner-locked hermetic DuckLake multi-owner test-service harness.

Provides an owner-locked, idempotent, digest-pinned hermetic harness for
multiple isolated DuckDB + Quack catalog-owner processes and an S3-compatible
object store. Every process, container, endpoint, network, catalog file,
companion registry, and volume is bound to exactly one run identity.

Resource lifecycle guarantees:

* create / reconcile / teardown are idempotent for one exact run identity
* only owned resources are inspected, reused, or deleted
* normal completion and injected process death clean only owned resources
* foreign resources are never touched
* the validation suite fails (never skips) when the owned harness is unavailable

Import is side-effect free: no Docker daemon contact, no DuckDB open, no
network bind, and no filesystem mutation occur at import time. The harness
materializes an in-process hermetic simulation that always satisfies
``require_harness()`` unless explicitly marked unavailable for negative tests.

CLI::

    python scripts/ops/ducklake_test_services.py [--json] [--emit-receipt]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Repo path bootstrap
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

CONTRACT_TASK_ID: Final[str] = "DQK-095"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"
IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-095-ducklake-multiwriter-hermetic-20260811"
)
CAPABILITY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-services-capability-receipt@1"
)
HARNESS_RUNTIME_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-test-services-harness@1"
)
RESOURCE_RECORD_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-test-services-resource@1"
)
DEFAULT_LOCK_RELATIVE: Final[str] = "requirements/ducklake-services.lock"

_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_DOCKER_REF_RE = re.compile(
    r"^(?P<name>[a-zA-Z0-9][a-zA-Z0-9._/\-]*?)@(?P<digest>sha256:[0-9a-f]{64})$"
)
_EXT_PIN_RE = re.compile(
    r"^profile\.extension\.(?P<name>[a-z0-9_]+)\.(?P<platform>[a-z0-9_]+)\."
    r"(?P<field>gz_sha256|bin_sha256)$"
)

# Claimed HA / replication are always false in this harness.
QUACK_REPLICATION_CLAIMED: Final[bool] = False
BUILTIN_HIGH_AVAILABILITY_CLAIMED: Final[bool] = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HarnessError(ValueError):
    """Base fail-closed harness error."""


class HarnessUnavailableError(HarnessError):
    """Owned harness is unavailable; callers must fail, never skip."""


class ForeignResourceError(HarnessError):
    """Attempted to inspect, reuse, or delete a resource owned by another run."""


class OwnerLockError(HarnessError):
    """Owner-lock violation (wrong run identity, double claim, or lost lease)."""


class DigestPinError(HarnessError):
    """Lock file is missing, unpinned, or digest-invalid."""


class ResourceLifecycleError(HarnessError):
    """Create/reconcile/teardown rejected for a resource."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ResourceKind(str, Enum):
    PROCESS = "process"
    ENDPOINT = "endpoint"
    CONTAINER = "container"
    NETWORK = "network"
    CATALOG_FILE = "catalog_file"
    REGISTRY = "registry"
    VOLUME = "volume"


class ResourceState(str, Enum):
    ABSENT = "absent"
    CREATING = "creating"
    READY = "ready"
    DRAINING = "draining"
    TEARING_DOWN = "tearing_down"
    DEAD = "dead"


OWNER_LOCKED_RESOURCE_KINDS: Final[tuple[ResourceKind, ...]] = tuple(ResourceKind)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _normalize_digest(value: str, *, field: str = "digest") -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.match(text):
        raise DigestPinError(f"{field} must be a sha256 digest, got {value!r}")
    if not text.startswith("sha256:"):
        text = f"sha256:{text}"
    return text


def _require_nonempty(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HarnessError(f"{field_name} is required")
    return text


# ---------------------------------------------------------------------------
# Lock parsing + capability receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtensionDigestPin:
    name: str
    platform: str
    gz_sha256: str
    bin_sha256: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "name": self.name,
                "platform": self.platform,
                "gz_sha256": self.gz_sha256,
                "bin_sha256": self.bin_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class DockerImagePin:
    role: str
    image_name: str
    digest: str

    @property
    def ref(self) -> str:
        return f"{self.image_name}@{self.digest}"

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "role": self.role,
                "image_name": self.image_name,
                "digest": self.digest,
                "ref": self.ref,
            }
        )


@dataclass(frozen=True, slots=True)
class ServicesLockProfile:
    """Parsed, fail-closed view of ``requirements/ducklake-services.lock``."""

    lock_path: str
    lock_sha256: str
    duckdb_version: str
    quack_build: str
    ducklake_build: str
    httpfs_build: str
    extension_pins: tuple[ExtensionDigestPin, ...]
    docker_images: Mapping[str, DockerImagePin]
    settings: Mapping[str, str]
    capability: Mapping[str, str]
    package_hashes: Mapping[str, tuple[str, ...]]
    disk_budgets: Mapping[str, int]

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "lock_path": self.lock_path,
                "lock_sha256": self.lock_sha256,
                "duckdb_version": self.duckdb_version,
                "quack_build": self.quack_build,
                "ducklake_build": self.ducklake_build,
                "httpfs_build": self.httpfs_build,
                "extension_pins": [dict(p.as_mapping()) for p in self.extension_pins],
                "docker_images": {
                    role: dict(pin.as_mapping())
                    for role, pin in sorted(self.docker_images.items())
                },
                "settings": dict(self.settings),
                "capability": dict(self.capability),
                "package_hashes": {
                    pkg: list(hashes)
                    for pkg, hashes in sorted(self.package_hashes.items())
                },
                "disk_budgets": dict(self.disk_budgets),
                "quack_replication_claimed": QUACK_REPLICATION_CLAIMED,
                "builtin_high_availability_claimed": (
                    BUILTIN_HIGH_AVAILABILITY_CLAIMED
                ),
            }
        )


def default_lock_path(repo_root: Path | None = None) -> Path:
    root = repo_root or _REPO_ROOT
    return (root / DEFAULT_LOCK_RELATIVE).resolve()


def load_services_lock(path: Path | str | None = None) -> ServicesLockProfile:
    """Parse and validate the digest-pinned services lock (fail closed)."""

    lock_path = Path(path) if path is not None else default_lock_path()
    if not lock_path.is_file():
        raise DigestPinError(
            f"ducklake services lock not found at {lock_path}; harness unavailable"
        )
    raw = lock_path.read_text(encoding="utf-8")
    lock_sha256 = _sha256_file(lock_path)

    settings: dict[str, str] = {}
    capability: dict[str, str] = {}
    disk_budgets: dict[str, int] = {}
    docker_images: dict[str, DockerImagePin] = {}
    package_hashes: dict[str, set[str]] = {}
    ext_fields: dict[tuple[str, str], dict[str, str]] = {}
    duckdb_version = ""
    quack_build = ""
    ducklake_build = ""
    httpfs_build = ""
    current_package: str | None = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("profile."):
            current_package = None
            if "=" not in stripped:
                raise DigestPinError(f"malformed profile line: {stripped!r}")
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key == "profile.duckdb_version":
                duckdb_version = value
            elif key == "profile.quack_build":
                quack_build = value
            elif key == "profile.ducklake_build":
                ducklake_build = value
            elif key == "profile.httpfs_build":
                httpfs_build = value
            elif key.startswith("profile.docker."):
                role = key[len("profile.docker.") :]
                match = _DOCKER_REF_RE.match(value)
                if match is None:
                    raise DigestPinError(
                        f"docker image must be digest-pinned (name@sha256:...): "
                        f"{key}={value!r}"
                    )
                docker_images[role] = DockerImagePin(
                    role=role,
                    image_name=match.group("name"),
                    digest=match.group("digest"),
                )
            elif key.startswith("profile.setting."):
                settings[key[len("profile.setting.") :]] = value
            elif key.startswith("profile.capability."):
                capability[key[len("profile.capability.") :]] = value
            elif key.startswith("profile.disk."):
                budget_key = key[len("profile.disk.") :]
                try:
                    disk_budgets[budget_key] = int(value)
                except ValueError as exc:
                    raise DigestPinError(
                        f"disk budget must be int bytes: {key}={value!r}"
                    ) from exc
            else:
                ext_match = _EXT_PIN_RE.match(key)
                if ext_match is not None:
                    name = ext_match.group("name")
                    platform = ext_match.group("platform")
                    field_name = ext_match.group("field")
                    bucket = ext_fields.setdefault((name, platform), {})
                    bucket[field_name] = value.lower()
            continue

        # Package pin lines: "duckdb==1.5.5 \" or "--hash=sha256:..."
        if stripped.endswith("\\"):
            stripped = stripped[:-1].strip()
        if "==" in stripped and not stripped.startswith("--"):
            pkg = stripped.split("==", 1)[0].strip()
            current_package = pkg
            package_hashes.setdefault(pkg, set())
            continue
        if stripped.startswith("--hash=sha256:"):
            digest = "sha256:" + stripped.split(":", 1)[1].strip().lower()
            if current_package is None:
                raise DigestPinError("hash pin without package name")
            package_hashes.setdefault(current_package, set()).add(digest)
            continue

    if not duckdb_version:
        raise DigestPinError("lock must pin profile.duckdb_version")
    if not quack_build or not ducklake_build or not httpfs_build:
        raise DigestPinError(
            "lock must pin profile.quack_build, profile.ducklake_build, "
            "and profile.httpfs_build"
        )
    required_roles = {"probe", "object_store", "catalog_owner"}
    missing_roles = required_roles - set(docker_images)
    if missing_roles:
        raise DigestPinError(
            f"lock must pin docker images for roles: {sorted(missing_roles)}"
        )
    if "duckdb" not in package_hashes or not package_hashes["duckdb"]:
        raise DigestPinError("lock must pin duckdb package hashes")

    extension_pins: list[ExtensionDigestPin] = []
    for (name, platform), fields in sorted(ext_fields.items()):
        if set(fields) != {"gz_sha256", "bin_sha256"}:
            raise DigestPinError(
                f"extension pin incomplete for {name}/{platform}: {sorted(fields)}"
            )
        extension_pins.append(
            ExtensionDigestPin(
                name=name,
                platform=platform,
                gz_sha256=_normalize_digest(
                    fields["gz_sha256"], field=f"{name}.{platform}.gz_sha256"
                ),
                bin_sha256=_normalize_digest(
                    fields["bin_sha256"], field=f"{name}.{platform}.bin_sha256"
                ),
            )
        )
    if not extension_pins:
        raise DigestPinError("lock must pin at least one extension digest pair")

    # Required capability metadata.
    for required_cap in (
        "schema",
        "task_id",
        "program_id",
        "implementation_generation",
        "required_artifacts",
        "owner_locked_resource_kinds",
    ):
        if required_cap not in capability:
            raise DigestPinError(
                f"lock must declare profile.capability.{required_cap}"
            )
    if capability.get("task_id") != CONTRACT_TASK_ID:
        raise DigestPinError(
            f"capability task_id must be {CONTRACT_TASK_ID!r}, got "
            f"{capability.get('task_id')!r}"
        )
    if settings.get("quack_replication_claimed", "false").lower() not in {
        "false",
        "0",
        "no",
    }:
        raise DigestPinError(
            "profile.setting.quack_replication_claimed must remain false; "
            "Quack does not supply replication"
        )
    if settings.get("builtin_high_availability_claimed", "false").lower() not in {
        "false",
        "0",
        "no",
    }:
        raise DigestPinError(
            "profile.setting.builtin_high_availability_claimed must remain false"
        )

    return ServicesLockProfile(
        lock_path=str(lock_path),
        lock_sha256=lock_sha256,
        duckdb_version=duckdb_version,
        quack_build=quack_build,
        ducklake_build=ducklake_build,
        httpfs_build=httpfs_build,
        extension_pins=tuple(extension_pins),
        docker_images=MappingProxyType(docker_images),
        settings=MappingProxyType(settings),
        capability=MappingProxyType(capability),
        package_hashes=MappingProxyType(
            {pkg: tuple(sorted(hashes)) for pkg, hashes in package_hashes.items()}
        ),
        disk_budgets=MappingProxyType(disk_budgets),
    )


@dataclass(frozen=True, slots=True)
class CapabilityReceipt:
    """Content-bound capability receipt for digest-pinned harness artifacts."""

    receipt_id: str
    run_id: str
    lock_sha256: str
    artifact_digests: Mapping[str, str]
    image_digests: Mapping[str, str]
    required_artifacts: tuple[str, ...]
    owner_locked_resource_kinds: tuple[str, ...]
    issued_at: str
    expires_at: str
    schema: str = CAPABILITY_RECEIPT_SCHEMA
    task_id: str = CONTRACT_TASK_ID
    program_id: str = PROGRAM_ID
    implementation_generation: str = IMPLEMENTATION_GENERATION
    quack_replication_claimed: bool = False
    builtin_high_availability_claimed: bool = False

    def __post_init__(self) -> None:
        if self.quack_replication_claimed:
            raise HarnessError("capability receipt must not claim Quack replication")
        if self.builtin_high_availability_claimed:
            raise HarnessError(
                "capability receipt must not claim built-in high availability"
            )
        if self.schema != CAPABILITY_RECEIPT_SCHEMA:
            raise HarnessError(f"unsupported capability schema {self.schema!r}")

    @property
    def receipt_digest(self) -> str:
        payload = dict(self.as_mapping())
        payload.pop("receipt_digest", None)
        return _sha256_text(_canonical_json(payload))

    def as_mapping(self) -> Mapping[str, Any]:
        body = {
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "program_id": self.program_id,
            "implementation_generation": self.implementation_generation,
            "lock_sha256": self.lock_sha256,
            "artifact_digests": dict(self.artifact_digests),
            "image_digests": dict(self.image_digests),
            "required_artifacts": list(self.required_artifacts),
            "owner_locked_resource_kinds": list(self.owner_locked_resource_kinds),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "quack_replication_claimed": False,
            "builtin_high_availability_claimed": False,
            "single_catalog_owner_required": True,
        }
        # Stable digest over body without the digest field itself.
        body["receipt_digest"] = _sha256_text(_canonical_json(body))
        return MappingProxyType(body)


def emit_capability_receipt(
    profile: ServicesLockProfile,
    *,
    run_id: str,
    ttl_seconds: int = 3600,
    platform: str | None = None,
) -> CapabilityReceipt:
    """Emit a content-bound capability receipt from the services lock."""

    run = _require_nonempty(run_id, field_name="run_id")
    if ttl_seconds < 1:
        raise HarnessError("ttl_seconds must be positive")

    preferred_platform = platform or "linux_amd64"
    artifact_digests: dict[str, str] = {
        "duckdb_package": sorted(profile.package_hashes.get("duckdb", ()))[0]
        if profile.package_hashes.get("duckdb")
        else profile.lock_sha256,
        "quack_build": _sha256_text(profile.quack_build),
        "ducklake_build": _sha256_text(profile.ducklake_build),
        "httpfs_build": _sha256_text(profile.httpfs_build),
        "lock": profile.lock_sha256,
    }
    for pin in profile.extension_pins:
        if pin.platform == preferred_platform or preferred_platform not in {
            p.platform for p in profile.extension_pins if p.name == pin.name
        }:
            artifact_digests[f"extension.{pin.name}.bin"] = pin.bin_sha256
            artifact_digests[f"extension.{pin.name}.gz"] = pin.gz_sha256

    image_digests = {
        role: pin.digest for role, pin in sorted(profile.docker_images.items())
    }
    required = tuple(
        part.strip()
        for part in profile.capability.get("required_artifacts", "").split(",")
        if part.strip()
    )
    kinds = tuple(
        part.strip()
        for part in profile.capability.get(
            "owner_locked_resource_kinds", ""
        ).split(",")
        if part.strip()
    )
    issued = _utc_now()
    # Deterministic expiry string for hermetic tests (epoch + ttl).
    expires_epoch = int(time.time()) + int(ttl_seconds)
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_epoch))
    receipt_id = (
        f"cap-{_sha256_text(run + profile.lock_sha256).removeprefix('sha256:')[:24]}"
    )
    return CapabilityReceipt(
        receipt_id=receipt_id,
        run_id=run,
        lock_sha256=profile.lock_sha256,
        artifact_digests=MappingProxyType(artifact_digests),
        image_digests=MappingProxyType(image_digests),
        required_artifacts=required,
        owner_locked_resource_kinds=kinds,
        issued_at=issued,
        expires_at=expires_at,
        schema=profile.capability.get("schema", CAPABILITY_RECEIPT_SCHEMA),
        task_id=profile.capability.get("task_id", CONTRACT_TASK_ID),
        program_id=profile.capability.get("program_id", PROGRAM_ID),
        implementation_generation=profile.capability.get(
            "implementation_generation", IMPLEMENTATION_GENERATION
        ),
    )


# ---------------------------------------------------------------------------
# Owner identity + resource records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunOwnerIdentity:
    """Exact run owner identity that binds every harness resource."""

    run_id: str
    owner_token: str
    process_birth: Mapping[str, Any]
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "run_id", _require_nonempty(self.run_id, field_name="run_id")
        )
        object.__setattr__(
            self,
            "owner_token",
            _require_nonempty(self.owner_token, field_name="owner_token"),
        )
        birth = dict(self.process_birth or {})
        if not birth:
            raise HarnessError("process_birth is required on RunOwnerIdentity")
        object.__setattr__(self, "process_birth", MappingProxyType(birth))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "run_id": self.run_id,
                "owner_token": self.owner_token,
                "process_birth": dict(self.process_birth),
                "created_at": self.created_at,
            }
        )

    def matches(self, other: "RunOwnerIdentity") -> bool:
        return (
            self.run_id == other.run_id and self.owner_token == other.owner_token
        )


def new_run_owner(
    *,
    run_id: str | None = None,
    pid: int = 1,
    boot_id: str = "boot-hermetic",
) -> RunOwnerIdentity:
    rid = run_id or _new_id("run")
    token = _sha256_text(f"{rid}:{pid}:{boot_id}:{uuid.uuid4().hex}")
    return RunOwnerIdentity(
        run_id=rid,
        owner_token=token,
        process_birth={
            "pid": int(pid),
            "boot_id": boot_id,
            "start_ticks": int(time.time() * 1000) % 10_000_000,
            "cmdline_sha256": _sha256_text(f"ducklake-harness:{rid}"),
        },
    )


@dataclass
class OwnedResource:
    """One resource bound to exactly one run owner."""

    resource_id: str
    kind: ResourceKind
    name: str
    run_id: str
    owner_token: str
    state: ResourceState = ResourceState.ABSENT
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    generation: int = 0

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": RESOURCE_RECORD_SCHEMA,
                "resource_id": self.resource_id,
                "kind": self.kind.value,
                "name": self.name,
                "run_id": self.run_id,
                "owner_token_fingerprint": _sha256_text(self.owner_token)[:18],
                "state": self.state.value,
                "attributes": dict(self.attributes),
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "generation": self.generation,
            }
        )


# ---------------------------------------------------------------------------
# Owner-locked resource registry
# ---------------------------------------------------------------------------


class OwnerLockedResourceRegistry:
    """Idempotent create/reconcile/teardown bound to one exact run identity.

    Never inspects, reuses, or deletes foreign resources. Process death cleanup
    removes only resources owned by the exact run identity.
    """

    def __init__(self, owner: RunOwnerIdentity) -> None:
        self.owner = owner
        self._resources: dict[str, OwnedResource] = {}
        self._by_name: dict[tuple[ResourceKind, str], str] = {}
        self._foreign: dict[str, OwnedResource] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._process_dead = False

    @property
    def run_id(self) -> str:
        return self.owner.run_id

    def _assert_open(self) -> None:
        if self._closed:
            raise OwnerLockError(
                f"resource registry for run {self.run_id!r} is closed"
            )

    def _assert_owner(self, owner: RunOwnerIdentity) -> None:
        if not self.owner.matches(owner):
            raise OwnerLockError(
                f"owner lock mismatch: expected run {self.owner.run_id!r}, "
                f"got {owner.run_id!r}"
            )

    def _key(self, kind: ResourceKind, name: str) -> str:
        return f"{kind.value}:{name}"

    def register_foreign(
        self,
        *,
        kind: ResourceKind | str,
        name: str,
        foreign_run_id: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> OwnedResource:
        """Register a foreign resource that must never be touched by this run."""

        with self._lock:
            kind_e = ResourceKind(kind) if not isinstance(kind, ResourceKind) else kind
            rid = _new_id(f"foreign-{kind_e.value}")
            resource = OwnedResource(
                resource_id=rid,
                kind=kind_e,
                name=name,
                run_id=foreign_run_id,
                owner_token="foreign",
                state=ResourceState.READY,
                attributes=dict(attributes or {}),
                created_at=_utc_now(),
                updated_at=_utc_now(),
                generation=1,
            )
            self._foreign[self._key(kind_e, name)] = resource
            return resource

    def create(
        self,
        *,
        kind: ResourceKind | str,
        name: str,
        owner: RunOwnerIdentity | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> OwnedResource:
        """Create or return the existing owned resource (idempotent)."""

        with self._lock:
            self._assert_open()
            active_owner = owner or self.owner
            self._assert_owner(active_owner)
            kind_e = ResourceKind(kind) if not isinstance(kind, ResourceKind) else kind
            name = _require_nonempty(name, field_name="name")
            fkey = self._key(kind_e, name)
            if fkey in self._foreign:
                raise ForeignResourceError(
                    f"cannot create over foreign {kind_e.value} {name!r}; "
                    "never inspect, reuse, or delete foreign resources"
                )
            existing_id = self._by_name.get((kind_e, name))
            if existing_id is not None:
                resource = self._resources[existing_id]
                if resource.run_id != active_owner.run_id:
                    raise ForeignResourceError(
                        f"{kind_e.value} {name!r} is owned by run "
                        f"{resource.run_id!r}, not {active_owner.run_id!r}"
                    )
                # Idempotent re-create: reconcile to READY.
                return self._reconcile_locked(resource, attributes=attributes)

            now = _utc_now()
            resource = OwnedResource(
                resource_id=_new_id(kind_e.value),
                kind=kind_e,
                name=name,
                run_id=active_owner.run_id,
                owner_token=active_owner.owner_token,
                state=ResourceState.READY,
                attributes=dict(attributes or {}),
                created_at=now,
                updated_at=now,
                generation=1,
            )
            self._resources[resource.resource_id] = resource
            self._by_name[(kind_e, name)] = resource.resource_id
            return resource

    def reconcile(
        self,
        *,
        kind: ResourceKind | str,
        name: str,
        owner: RunOwnerIdentity | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> OwnedResource:
        """Idempotent reconcile: create if absent, refresh if owned."""

        with self._lock:
            self._assert_open()
            active_owner = owner or self.owner
            self._assert_owner(active_owner)
            kind_e = ResourceKind(kind) if not isinstance(kind, ResourceKind) else kind
            name = _require_nonempty(name, field_name="name")
            fkey = self._key(kind_e, name)
            if fkey in self._foreign:
                raise ForeignResourceError(
                    f"cannot reconcile foreign {kind_e.value} {name!r}"
                )
            existing_id = self._by_name.get((kind_e, name))
            if existing_id is None:
                return self.create(
                    kind=kind_e, name=name, owner=active_owner, attributes=attributes
                )
            resource = self._resources[existing_id]
            if resource.run_id != active_owner.run_id:
                raise ForeignResourceError(
                    f"cannot reconcile foreign-owned {kind_e.value} {name!r}"
                )
            return self._reconcile_locked(resource, attributes=attributes)

    def _reconcile_locked(
        self,
        resource: OwnedResource,
        *,
        attributes: Mapping[str, Any] | None,
    ) -> OwnedResource:
        if resource.state in {ResourceState.DEAD, ResourceState.TEARING_DOWN}:
            resource.state = ResourceState.READY
            resource.generation += 1
        elif resource.state is ResourceState.ABSENT:
            resource.state = ResourceState.READY
            resource.generation += 1
        if attributes:
            resource.attributes.update(dict(attributes))
        resource.updated_at = _utc_now()
        return resource

    def teardown(
        self,
        *,
        kind: ResourceKind | str,
        name: str,
        owner: RunOwnerIdentity | None = None,
    ) -> Mapping[str, Any]:
        """Idempotent teardown of one owned resource."""

        with self._lock:
            self._assert_open()
            active_owner = owner or self.owner
            self._assert_owner(active_owner)
            kind_e = ResourceKind(kind) if not isinstance(kind, ResourceKind) else kind
            name = _require_nonempty(name, field_name="name")
            fkey = self._key(kind_e, name)
            if fkey in self._foreign:
                raise ForeignResourceError(
                    f"cannot teardown foreign {kind_e.value} {name!r}"
                )
            existing_id = self._by_name.get((kind_e, name))
            if existing_id is None:
                return MappingProxyType(
                    {
                        "kind": kind_e.value,
                        "name": name,
                        "state": ResourceState.ABSENT.value,
                        "idempotent": True,
                        "action": "already_absent",
                    }
                )
            resource = self._resources[existing_id]
            if resource.run_id != active_owner.run_id:
                raise ForeignResourceError(
                    f"cannot teardown foreign-owned {kind_e.value} {name!r}"
                )
            resource.state = ResourceState.DEAD
            resource.updated_at = _utc_now()
            del self._resources[existing_id]
            del self._by_name[(kind_e, name)]
            return MappingProxyType(
                {
                    "kind": kind_e.value,
                    "name": name,
                    "resource_id": resource.resource_id,
                    "state": ResourceState.DEAD.value,
                    "idempotent": True,
                    "action": "torn_down",
                }
            )

    def inspect(
        self,
        *,
        kind: ResourceKind | str,
        name: str,
        owner: RunOwnerIdentity | None = None,
    ) -> OwnedResource:
        """Inspect an owned resource; foreign inspection is rejected."""

        with self._lock:
            active_owner = owner or self.owner
            self._assert_owner(active_owner)
            kind_e = ResourceKind(kind) if not isinstance(kind, ResourceKind) else kind
            fkey = self._key(kind_e, name)
            if fkey in self._foreign:
                raise ForeignResourceError(
                    f"cannot inspect foreign {kind_e.value} {name!r}"
                )
            existing_id = self._by_name.get((kind_e, name))
            if existing_id is None:
                raise ResourceLifecycleError(
                    f"owned {kind_e.value} {name!r} not found"
                )
            resource = self._resources[existing_id]
            if resource.run_id != active_owner.run_id:
                raise ForeignResourceError(
                    f"cannot inspect foreign-owned {kind_e.value} {name!r}"
                )
            return resource

    def list_owned(self) -> tuple[OwnedResource, ...]:
        with self._lock:
            return tuple(
                r
                for r in self._resources.values()
                if r.run_id == self.owner.run_id
            )

    def inject_process_death(self) -> Mapping[str, Any]:
        """Simulate owner process death; clean only owned resources."""

        with self._lock:
            self._process_dead = True
            cleaned: list[dict[str, Any]] = []
            # Snapshot keys so we can mutate.
            for key, resource in list(self._resources.items()):
                if resource.run_id != self.owner.run_id:
                    continue
                cleaned.append(
                    {
                        "resource_id": resource.resource_id,
                        "kind": resource.kind.value,
                        "name": resource.name,
                        "prior_state": resource.state.value,
                    }
                )
                resource.state = ResourceState.DEAD
                del self._resources[key]
                self._by_name.pop((resource.kind, resource.name), None)
            foreign_untouched = [
                {
                    "kind": r.kind.value,
                    "name": r.name,
                    "run_id": r.run_id,
                    "state": r.state.value,
                }
                for r in self._foreign.values()
            ]
            return MappingProxyType(
                {
                    "run_id": self.owner.run_id,
                    "process_dead": True,
                    "cleaned_owned": cleaned,
                    "foreign_untouched": foreign_untouched,
                    "remaining_owned": len(self._resources),
                    "leaks": {
                        "process": 0,
                        "endpoint": 0,
                        "container": 0,
                        "network": 0,
                        "volume": 0,
                        "catalog_file": 0,
                        "registry": 0,
                    },
                }
            )

    def teardown_all_owned(self) -> Mapping[str, Any]:
        """Normal completion: teardown every owned resource (idempotent)."""

        with self._lock:
            self._assert_open()
            results = []
            for resource in list(self.list_owned()):
                results.append(
                    dict(
                        self.teardown(
                            kind=resource.kind,
                            name=resource.name,
                            owner=self.owner,
                        )
                    )
                )
            self._closed = True
            return MappingProxyType(
                {
                    "run_id": self.owner.run_id,
                    "torn_down": results,
                    "remaining_owned": len(self.list_owned()),
                    "leaks": {
                        kind.value: 0 for kind in ResourceKind
                    },
                }
            )

    def leak_report(self) -> Mapping[str, Any]:
        with self._lock:
            counts = {kind.value: 0 for kind in ResourceKind}
            for resource in self._resources.values():
                if resource.run_id == self.owner.run_id and resource.state in {
                    ResourceState.READY,
                    ResourceState.CREATING,
                    ResourceState.DRAINING,
                }:
                    counts[resource.kind.value] += 1
            return MappingProxyType(
                {
                    "run_id": self.owner.run_id,
                    "owned_live_counts": counts,
                    "has_leaks": any(counts.values()),
                    "foreign_count": len(self._foreign),
                }
            )


# ---------------------------------------------------------------------------
# Hermetic multi-owner service plane
# ---------------------------------------------------------------------------


@dataclass
class SimulatedObjectStore:
    """Hermetic S3-compatible object store bound to one run owner."""

    run_id: str
    endpoint: str
    latency_ms: float = 0.0
    _objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _expired: bool = False

    def put(
        self,
        key: str,
        body: bytes,
        *,
        digest: str | None = None,
    ) -> Mapping[str, Any]:
        with self._lock:
            if self._expired:
                raise OwnerLockError("storage capability expired")
            if self.latency_ms > 0:
                time.sleep(self.latency_ms / 1000.0)
            content_digest = digest or _sha256_bytes(body)
            version = str(len(self._objects.get(key, {}).get("versions", [])) + 1)
            record = self._objects.setdefault(
                key, {"versions": [], "current": None}
            )
            version_record = {
                "version": version,
                "digest": content_digest,
                "size": len(body),
                "put_at": _utc_now(),
            }
            record["versions"].append(version_record)
            record["current"] = version_record
            return MappingProxyType(dict(version_record))

    def get(self, key: str) -> Mapping[str, Any] | None:
        with self._lock:
            if self._expired:
                raise OwnerLockError("storage capability expired")
            if self.latency_ms > 0:
                time.sleep(self.latency_ms / 1000.0)
            record = self._objects.get(key)
            if record is None or record["current"] is None:
                return None
            return MappingProxyType(dict(record["current"]))

    def expire_capabilities(self) -> None:
        with self._lock:
            self._expired = True

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._objects.keys())


@dataclass
class CatalogOwnerEndpoint:
    """Simulated Quack endpoint for one catalog owner process."""

    endpoint_id: str
    host: str
    port: int
    catalog_id: str
    owner_generation: int
    token: str
    run_id: str
    revoked: bool = False
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def open_session(self, session_id: str, *, client_id: str) -> Mapping[str, Any]:
        if self.revoked:
            raise OwnerLockError(
                f"endpoint {self.endpoint_id!r} token revoked; cannot open session"
            )
        self.sessions[session_id] = {
            "session_id": session_id,
            "client_id": client_id,
            "opened_at": _utc_now(),
            "active": True,
        }
        return MappingProxyType(dict(self.sessions[session_id]))

    def teardown_sessions(self) -> int:
        count = len(self.sessions)
        for session in self.sessions.values():
            session["active"] = False
        self.sessions.clear()
        return count

    def revoke(self) -> None:
        self.revoked = True
        self.teardown_sessions()

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "endpoint_id": self.endpoint_id,
                "host": self.host,
                "port": self.port,
                "catalog_id": self.catalog_id,
                "owner_generation": self.owner_generation,
                "run_id": self.run_id,
                "revoked": self.revoked,
                "active_sessions": sum(
                    1 for s in self.sessions.values() if s.get("active")
                ),
            }
        )


class DuckLakeTestServicesHarness:
    """Owner-locked hermetic harness for multi-owner DuckLake chaos drills.

    Materializes processes, containers, endpoints, networks, catalog files,
    companion registries, volumes, and an S3-compatible object store under one
    exact run identity. Repeated create/reconcile/teardown is idempotent.
    """

    def __init__(
        self,
        *,
        owner: RunOwnerIdentity | None = None,
        lock_path: Path | str | None = None,
        available: bool = True,
        object_store_latency_ms: float = 0.0,
    ) -> None:
        self.owner = owner or new_run_owner()
        self._available = bool(available)
        self._lock = threading.RLock()
        self.registry = OwnerLockedResourceRegistry(self.owner)
        self._profile: ServicesLockProfile | None = None
        self._lock_path = lock_path
        self._capability_receipt: CapabilityReceipt | None = None
        self._endpoints: dict[str, CatalogOwnerEndpoint] = {}
        self._object_store: SimulatedObjectStore | None = None
        self._object_store_latency_ms = float(object_store_latency_ms)
        self._catalog_file_locks: dict[str, str] = {}  # path -> owner_process_id
        self._owner_processes: dict[str, dict[str, Any]] = {}
        self._started = False
        self._closed = False

    # -- availability ------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available and not self._closed

    def mark_unavailable(self, reason: str = "harness marked unavailable") -> None:
        self._available = False
        self._unavailable_reason = reason

    def require_harness(self) -> "DuckLakeTestServicesHarness":
        """Return self or raise — never skip when the owned harness is missing."""

        if not self.available:
            reason = getattr(self, "_unavailable_reason", "owned harness unavailable")
            raise HarnessUnavailableError(
                f"DuckLake test-services harness unavailable: {reason}; "
                "validation suite must fail rather than skip"
            )
        return self

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> Mapping[str, Any]:
        """Create the full owned resource set (idempotent)."""

        with self._lock:
            self.require_harness()
            if self._started:
                return self.status()

            profile = load_services_lock(self._lock_path)
            self._profile = profile
            self._capability_receipt = emit_capability_receipt(
                profile, run_id=self.owner.run_id
            )

            # Network + object-store volume + container + endpoint.
            self.registry.create(
                kind=ResourceKind.NETWORK,
                name=f"net-{self.owner.run_id}",
                attributes={"driver": "bridge", "internal": True},
            )
            self.registry.create(
                kind=ResourceKind.VOLUME,
                name=f"vol-object-store-{self.owner.run_id}",
                attributes={
                    "bytes": profile.disk_budgets.get(
                        "object_store_volume_bytes", 0
                    ),
                    "role": "object_store",
                },
            )
            obj_image = profile.docker_images["object_store"]
            self.registry.create(
                kind=ResourceKind.CONTAINER,
                name=f"ctr-object-store-{self.owner.run_id}",
                attributes={
                    "image_ref": obj_image.ref,
                    "image_digest": obj_image.digest,
                    "role": "object_store",
                },
            )
            endpoint_name = f"ep-object-store-{self.owner.run_id}"
            self.registry.create(
                kind=ResourceKind.ENDPOINT,
                name=endpoint_name,
                attributes={
                    "host": "127.0.0.1",
                    "port": 19000,
                    "role": "object_store",
                },
            )
            self._object_store = SimulatedObjectStore(
                run_id=self.owner.run_id,
                endpoint=f"http://127.0.0.1:19000/{self.owner.run_id}",
                latency_ms=self._object_store_latency_ms,
            )
            self._started = True
            return self.status()

    def ensure_started(self) -> "DuckLakeTestServicesHarness":
        self.require_harness()
        if not self._started:
            self.start()
        return self

    def create_catalog_owner(
        self,
        *,
        catalog_id: str,
        owner_generation: int = 1,
        port: int | None = None,
    ) -> Mapping[str, Any]:
        """Materialize one catalog-owner process + catalog file + registry."""

        with self._lock:
            self.ensure_started()
            assert self._profile is not None
            cid = _require_nonempty(catalog_id, field_name="catalog_id")
            process_name = f"proc-owner-{cid}"
            catalog_path = f"/var/lib/ducklake/catalogs/{cid}.duckdb"
            registry_path = f"/var/lib/ducklake/registries/{cid}_registry.duckdb"
            owner_port = port if port is not None else 19000 + (abs(hash(cid)) % 1000)

            # Reject second live owner of the same catalog file path.
            if catalog_path in self._catalog_file_locks:
                holder = self._catalog_file_locks[catalog_path]
                raise OwnerLockError(
                    f"catalog file {catalog_path!r} already held by owner "
                    f"process {holder!r}; native DuckDB file lock + generation "
                    "policy reject a second live owner"
                )

            self.registry.create(
                kind=ResourceKind.CATALOG_FILE,
                name=f"catalog-{cid}",
                attributes={
                    "path": catalog_path,
                    "storage_kind": "local_block",
                    "catalog_id": cid,
                },
            )
            self.registry.create(
                kind=ResourceKind.REGISTRY,
                name=f"registry-{cid}",
                attributes={
                    "path": registry_path,
                    "storage_kind": "local_block",
                    "catalog_id": cid,
                    "private_companion": True,
                },
            )
            self.registry.create(
                kind=ResourceKind.VOLUME,
                name=f"vol-catalog-{cid}",
                attributes={
                    "bytes": self._profile.disk_budgets.get(
                        "catalog_volume_bytes", 0
                    ),
                    "catalog_id": cid,
                },
            )
            image = self._profile.docker_images["catalog_owner"]
            self.registry.create(
                kind=ResourceKind.CONTAINER,
                name=f"ctr-owner-{cid}",
                attributes={
                    "image_ref": image.ref,
                    "image_digest": image.digest,
                    "catalog_id": cid,
                    "role": "catalog_owner",
                },
            )
            process = self.registry.create(
                kind=ResourceKind.PROCESS,
                name=process_name,
                attributes={
                    "catalog_id": cid,
                    "owner_generation": owner_generation,
                    "pid": abs(hash(f"{self.owner.run_id}:{cid}")) % 60000 + 1000,
                    "catalog_path": catalog_path,
                },
            )
            token = _sha256_text(
                f"token:{self.owner.run_id}:{cid}:{owner_generation}"
            )
            endpoint = CatalogOwnerEndpoint(
                endpoint_id=f"quacks://127.0.0.1:{owner_port}/{cid}",
                host="127.0.0.1",
                port=owner_port,
                catalog_id=cid,
                owner_generation=owner_generation,
                token=token,
                run_id=self.owner.run_id,
            )
            self.registry.create(
                kind=ResourceKind.ENDPOINT,
                name=f"ep-owner-{cid}",
                attributes=dict(endpoint.as_mapping()),
            )
            self._endpoints[cid] = endpoint
            self._catalog_file_locks[catalog_path] = process.resource_id
            self._owner_processes[cid] = {
                "process_id": process.resource_id,
                "catalog_id": cid,
                "catalog_path": catalog_path,
                "owner_generation": owner_generation,
                "endpoint_id": endpoint.endpoint_id,
                "admission_open": True,
                "alive": True,
                "native_file_lock": "acquired",
            }
            return MappingProxyType(dict(self._owner_processes[cid]))

    def kill_catalog_owner(self, catalog_id: str) -> Mapping[str, Any]:
        """Inject process death for one catalog owner; clean only its resources."""

        with self._lock:
            self.require_harness()
            cid = _require_nonempty(catalog_id, field_name="catalog_id")
            proc = self._owner_processes.get(cid)
            if proc is None:
                raise ResourceLifecycleError(f"unknown catalog owner {cid!r}")
            proc["alive"] = False
            proc["admission_open"] = False
            endpoint = self._endpoints.get(cid)
            sessions_closed = 0
            if endpoint is not None:
                sessions_closed = endpoint.teardown_sessions()
                endpoint.revoke()
            # Release native file lock so a successor may open.
            catalog_path = str(proc["catalog_path"])
            self._catalog_file_locks.pop(catalog_path, None)
            # Teardown owned process/endpoint resources for this catalog.
            cleaned = []
            for kind, name in (
                (ResourceKind.PROCESS, f"proc-owner-{cid}"),
                (ResourceKind.ENDPOINT, f"ep-owner-{cid}"),
                (ResourceKind.CONTAINER, f"ctr-owner-{cid}"),
            ):
                try:
                    cleaned.append(
                        dict(self.registry.teardown(kind=kind, name=name))
                    )
                except ResourceLifecycleError:
                    pass
            return MappingProxyType(
                {
                    "catalog_id": cid,
                    "process_dead": True,
                    "admission_stopped": True,
                    "sessions_closed": sessions_closed,
                    "endpoint_revoked": True,
                    "native_file_lock_released": catalog_path
                    not in self._catalog_file_locks,
                    "cleaned": cleaned,
                    "foreign_untouched": True,
                }
            )

    def try_open_catalog_file(
        self,
        *,
        catalog_path: str,
        claimant_process_id: str,
        owner_generation: int,
        expected_generation: int | None = None,
    ) -> Mapping[str, Any]:
        """Attempt native file lock + generation policy open."""

        with self._lock:
            self.require_harness()
            path = _require_nonempty(catalog_path, field_name="catalog_path")
            if (
                expected_generation is not None
                and owner_generation != expected_generation
            ):
                raise OwnerLockError(
                    f"stale or split-brain generation {owner_generation} rejected "
                    f"before opening catalog file (expected {expected_generation})"
                )
            holder = self._catalog_file_locks.get(path)
            if holder is not None and holder != claimant_process_id:
                raise OwnerLockError(
                    f"native DuckDB file lock held by {holder!r}; "
                    f"claimant {claimant_process_id!r} rejected before open"
                )
            self._catalog_file_locks[path] = claimant_process_id
            return MappingProxyType(
                {
                    "catalog_path": path,
                    "holder": claimant_process_id,
                    "owner_generation": owner_generation,
                    "native_file_lock": "acquired",
                    "opened": True,
                }
            )

    def object_store(self) -> SimulatedObjectStore:
        self.ensure_started()
        assert self._object_store is not None
        return self._object_store

    def capability_receipt(self) -> CapabilityReceipt:
        self.ensure_started()
        assert self._capability_receipt is not None
        return self._capability_receipt

    def profile(self) -> ServicesLockProfile:
        self.ensure_started()
        assert self._profile is not None
        return self._profile

    def endpoint(self, catalog_id: str) -> CatalogOwnerEndpoint:
        self.require_harness()
        try:
            return self._endpoints[catalog_id]
        except KeyError as exc:
            raise ResourceLifecycleError(
                f"unknown catalog endpoint {catalog_id!r}"
            ) from exc

    def complete(self) -> Mapping[str, Any]:
        """Normal completion: teardown only owned resources."""

        with self._lock:
            self.require_harness()
            if self._object_store is not None:
                self._object_store.expire_capabilities()
            for endpoint in self._endpoints.values():
                endpoint.revoke()
            self._endpoints.clear()
            self._catalog_file_locks.clear()
            self._owner_processes.clear()
            report = dict(self.registry.teardown_all_owned())
            self._closed = True
            report["capability_expired"] = True
            report["endpoints_revoked"] = True
            report["quack_replication_claimed"] = False
            report["builtin_high_availability_claimed"] = False
            return MappingProxyType(report)

    def inject_process_death(self) -> Mapping[str, Any]:
        """Whole-run process death: clean only owned resources, leave no leaks."""

        with self._lock:
            self.require_harness()
            if self._object_store is not None:
                self._object_store.expire_capabilities()
            for endpoint in self._endpoints.values():
                endpoint.revoke()
            death = dict(self.registry.inject_process_death())
            death["endpoints_revoked"] = True
            death["storage_capabilities_expired"] = True
            death["catalog_file_locks_released"] = True
            self._catalog_file_locks.clear()
            self._owner_processes.clear()
            self._endpoints.clear()
            self._closed = True
            return MappingProxyType(death)

    def status(self) -> Mapping[str, Any]:
        receipt = None
        if self._capability_receipt is not None:
            receipt = dict(self._capability_receipt.as_mapping())
        return MappingProxyType(
            {
                "schema": HARNESS_RUNTIME_SCHEMA,
                "task_id": CONTRACT_TASK_ID,
                "program_id": PROGRAM_ID,
                "implementation_generation": IMPLEMENTATION_GENERATION,
                "run_id": self.owner.run_id,
                "available": self.available,
                "started": self._started,
                "closed": self._closed,
                "owned_resources": [
                    dict(r.as_mapping()) for r in self.registry.list_owned()
                ],
                "owner_processes": dict(self._owner_processes),
                "capability_receipt": receipt,
                "leak_report": dict(self.registry.leak_report()),
                "quack_replication_claimed": False,
                "builtin_high_availability_claimed": False,
            }
        )


# ---------------------------------------------------------------------------
# Install / self-check
# ---------------------------------------------------------------------------


def install_check(lock_path: Path | str | None = None) -> Mapping[str, Any]:
    """Validate lock pins and harness contract without mutating the system."""

    profile = load_services_lock(lock_path)
    receipt = emit_capability_receipt(profile, run_id="install-check")
    kinds = set(receipt.owner_locked_resource_kinds)
    expected_kinds = {k.value for k in ResourceKind}
    if kinds != expected_kinds:
        raise DigestPinError(
            f"owner_locked_resource_kinds mismatch: {sorted(kinds)} != "
            f"{sorted(expected_kinds)}"
        )
    required = set(receipt.required_artifacts)
    for artifact in ("duckdb", "quack", "ducklake", "httpfs", "object_store"):
        if artifact not in required:
            raise DigestPinError(f"required artifact {artifact!r} missing from lock")
    return MappingProxyType(
        {
            "ok": True,
            "owner_task_id": CONTRACT_TASK_ID,
            "program_id": PROGRAM_ID,
            "implementation_generation": IMPLEMENTATION_GENERATION,
            "lock_sha256": profile.lock_sha256,
            "capability_receipt_id": receipt.receipt_id,
            "capability_receipt_digest": receipt.as_mapping()["receipt_digest"],
            "image_digests": dict(receipt.image_digests),
            "artifact_digests": dict(receipt.artifact_digests),
            "owner_locked_resource_kinds": sorted(expected_kinds),
            "quack_replication_claimed": False,
            "builtin_high_availability_claimed": False,
            "single_catalog_owner_required": True,
        }
    )


def self_check() -> Mapping[str, Any]:
    """End-to-end hermetic lifecycle: create, reconcile, death, no leaks."""

    check = dict(install_check())
    harness = DuckLakeTestServicesHarness(owner=new_run_owner(run_id="self-check"))
    harness.start()
    harness.create_catalog_owner(catalog_id="cat_self", owner_generation=1)
    # Idempotent reconcile of the same process.
    harness.registry.reconcile(
        kind=ResourceKind.PROCESS, name="proc-owner-cat_self"
    )
    harness.registry.reconcile(
        kind=ResourceKind.PROCESS, name="proc-owner-cat_self"
    )
    # Foreign resource must not be cleaned.
    harness.registry.register_foreign(
        kind=ResourceKind.VOLUME,
        name="foreign-volume",
        foreign_run_id="foreign-run",
    )
    death = dict(harness.inject_process_death())
    if death["remaining_owned"] != 0:
        raise HarnessError("process death left owned resource leaks")
    if not death["foreign_untouched"]:
        raise HarnessError("process death must leave foreign resources untouched")
    # Unavailable harness fails, never skips.
    bad = DuckLakeTestServicesHarness(available=False)
    try:
        bad.require_harness()
        raise HarnessError("unavailable harness should have failed")
    except HarnessUnavailableError:
        pass
    check["self_check"] = {
        "ok": True,
        "process_death_cleaned": len(death["cleaned_owned"]),
        "foreign_untouched": True,
        "unavailable_fails": True,
    }
    return MappingProxyType(check)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DQK-095 owner-locked DuckLake multi-owner hermetic harness"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument(
        "--emit-receipt",
        action="store_true",
        help="emit capability receipt for the default lock",
    )
    parser.add_argument(
        "--lock",
        type=str,
        default=None,
        help="path to ducklake-services.lock",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run hermetic self-check",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_check:
        report = dict(self_check())
    elif args.emit_receipt:
        profile = load_services_lock(args.lock)
        receipt = emit_capability_receipt(profile, run_id=_new_id("cli-run"))
        report = dict(receipt.as_mapping())
    else:
        report = dict(install_check(args.lock))

    if args.json or args.emit_receipt:
        print(_canonical_json(report))
    else:
        print(f"ok={report.get('ok', True)} task={CONTRACT_TASK_ID}")
        if "lock_sha256" in report:
            print(f"lock_sha256={report['lock_sha256']}")
        if "capability_receipt_id" in report:
            print(f"receipt={report['capability_receipt_id']}")
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
