"""Typed DuckDB + Quack catalog-shard profiles and owner binding (DQK-085).

Binds each logical catalog shard to:

* exactly one DuckDB metadata file on local/attached block storage;
* exactly one identity-bound DuckDB + Quack owner process and generation;
* exactly one canonical Quack endpoint;
* exactly one lifecycle-managed Parquet namespace;

and enforces:

* remote clients never open, mount, copy, or mutate the live catalog file;
* same-shard requests serialize through the fenced owner while independent
  shards may run concurrently;
* active/passive takeover only after a durable owner-generation receipt,
  proof the prior process stopped admission and is dead/fenced, endpoint/token
  revocation, expired storage capabilities, closed handles, exact catalog
  digest/generation, and successful native DuckDB file-lock acquisition;
* DuckLake supplies no role or authorization layer — a trusted owner broker
  independently authorizes every privileged call and injects a one-use Quack
  capability only into an identity-bound trusted worker;
* every non-bootstrap / non-migration ATTACH sets CREATE_IF_NOT_EXISTS=false,
  OVERRIDE_DATA_PATH=false, and AUTOMATIC_MIGRATION=false.

Import is side-effect free: never imports ``duckdb``, never ATTACHes, never
opens sockets, and never resolves secrets.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

from ipfs_datasets_py.ducklake.capabilities import ATTACH_SAFE_OPTIONS
from ipfs_datasets_py.ducklake.config import (
    CatalogConfigError,
    IdentityCapabilityProfile,
    IdentityRole,
    ObjectDeleteIAMCapability,
    SecretProfile,
    StorageProfile,
    assert_no_secret_material,
    build_identity_profiles,
    build_object_delete_capability,
    project_safe_config,
)

__all__ = [
    "ATTACH_OPTION_KEYS",
    "ATTACH_SAFE_OPTIONS",
    "AttachAuthorization",
    "AttachAuthorizationError",
    "AttachMode",
    "AttachOptions",
    "CATALOG_SHARD_PROFILE_SCHEMA",
    "CatalogOwnershipError",
    "CatalogShardError",
    "CatalogShardPlane",
    "CatalogShardProfile",
    "DUCKLAKE_HAS_AUTHORIZATION_LAYER",
    "NativeFileLockEvidence",
    "OneUseQuackCapability",
    "OwnerGenerationReceipt",
    "OwnerProcessIdentity",
    "PrivilegedOperation",
    "QuackEndpointIdentity",
    "RemoteCatalogAccessError",
    "TakeoverEvidence",
    "TakeoverError",
    "TrustedOwnerBroker",
    "assert_remote_cannot_open_catalog",
    "build_attach_options",
    "build_catalog_shard_profile",
    "build_owner_generation_receipt",
    "build_owner_process_identity",
    "build_quack_endpoint",
    "evaluate_takeover",
    "inspect_attach_options",
    "project_shard_profile",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATALOG_SHARD_PROFILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-shard-profile@1"
)
_CATALOG_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-085-catalog-shard-profiles-20260810"
)

# DuckLake itself supplies no role or authorization layer (DQK-085 / DQK-097).
DUCKLAKE_HAS_AUTHORIZATION_LAYER: Final[bool] = False

ATTACH_OPTION_KEYS: Final[tuple[str, ...]] = (
    "CREATE_IF_NOT_EXISTS",
    "OVERRIDE_DATA_PATH",
    "AUTOMATIC_MIGRATION",
)

# Re-export the capability-module safe defaults for a single import surface.
assert dict(ATTACH_SAFE_OPTIONS) == {
    "CREATE_IF_NOT_EXISTS": False,
    "OVERRIDE_DATA_PATH": False,
    "AUTOMATIC_MIGRATION": False,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CatalogShardError(CatalogConfigError):
    """Invalid catalog-shard profile, owner binding, or attach policy."""


class CatalogOwnershipError(CatalogShardError):
    """Ownership, fencing, or single-owner invariant violated."""


class TakeoverError(CatalogOwnershipError):
    """Active/passive takeover preconditions are not fully satisfied."""


class RemoteCatalogAccessError(CatalogOwnershipError):
    """Remote client attempted to open, mount, or mutate a catalog file."""


class AttachAuthorizationError(CatalogShardError):
    """Bootstrap/migration ATTACH options used without separate authorization."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AttachMode(str, Enum):
    """DuckLake ATTACH operating mode."""

    RUNTIME = "runtime"
    """Ordinary owner ATTACH: all three safety flags forced false."""

    BOOTSTRAP = "bootstrap"
    """Separately authorized first-time catalog creation."""

    MIGRATION = "migration"
    """Separately authorized catalog migration."""


class PrivilegedOperation(str, Enum):
    """Privileged operations that require trusted-broker authorization."""

    CATALOG_MUTATE = "catalog_mutate"
    INGEST_REGISTER = "ingest_register"
    MAINTENANCE_DRY_RUN = "maintenance_dry_run"
    MAINTENANCE_EXECUTE = "maintenance_execute"
    OBJECT_DELETE = "object_delete"
    SNAPSHOT_READ = "snapshot_read"
    BOOTSTRAP_ATTACH = "bootstrap_attach"
    MIGRATION_ATTACH = "migration_attach"
    OWNER_TAKEOVER = "owner_takeover"
    INJECT_QUACK_CAPABILITY = "inject_quack_capability"


# ---------------------------------------------------------------------------
# Owner, endpoint, and generation identities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnerProcessIdentity:
    """Identity-bound owner process birth for fencing and lease binding."""

    process_id: str
    pid: int
    boot_id: str
    start_ticks: int
    cmdline_sha256: str
    principal: str

    def __post_init__(self) -> None:
        if not self.process_id or not self.principal:
            raise CatalogShardError("owner process_id and principal are required")
        if self.pid <= 0:
            raise CatalogShardError("owner pid must be positive")
        if not self.boot_id:
            raise CatalogShardError("owner boot_id is required")
        if self.start_ticks < 0:
            raise CatalogShardError("owner start_ticks must be non-negative")
        digest = self.cmdline_sha256
        if digest.startswith("sha256:"):
            digest = digest[7:]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CatalogShardError("cmdline_sha256 must be a sha256 hex digest")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "process_id": self.process_id,
                "pid": self.pid,
                "boot_id": self.boot_id,
                "start_ticks": self.start_ticks,
                "cmdline_sha256": (
                    self.cmdline_sha256
                    if self.cmdline_sha256.startswith("sha256:")
                    else f"sha256:{self.cmdline_sha256}"
                ),
                "principal": self.principal,
            }
        )


def build_owner_process_identity(
    *,
    principal: str,
    pid: int,
    boot_id: str,
    start_ticks: int,
    cmdline_sha256: str,
    process_id: str | None = None,
) -> OwnerProcessIdentity:
    """Build an owner process identity from explicit birth facts (no live /proc)."""

    digest = cmdline_sha256 if cmdline_sha256.startswith("sha256:") else f"sha256:{cmdline_sha256}"
    hex_part = digest[7:]
    pid_value = int(pid)
    boot = str(boot_id)
    ticks = int(start_ticks)
    generated = process_id or (
        "ownerproc:"
        + hashlib.sha256(
            f"{principal}|{pid_value}|{boot}|{ticks}|{hex_part}".encode()
        ).hexdigest()[:24]
    )
    return OwnerProcessIdentity(
        process_id=generated,
        pid=pid_value,
        boot_id=boot,
        start_ticks=ticks,
        cmdline_sha256=digest,
        principal=principal,
    )


@dataclass(frozen=True, slots=True)
class QuackEndpointIdentity:
    """Canonical Quack endpoint for one catalog shard (token never embedded)."""

    endpoint_id: str
    bind_address: str
    port: int
    tls_required: bool = True
    loopback_only: bool = True
    token_reference_id: str | None = None

    def __post_init__(self) -> None:
        if not self.endpoint_id:
            raise CatalogShardError("quack endpoint_id is required")
        if not self.bind_address:
            raise CatalogShardError("quack bind_address is required")
        if not (0 < self.port < 65536):
            raise CatalogShardError("quack port must be in 1..65535")
        if self.loopback_only:
            allowed = {
                "127.0.0.1",
                "localhost",
                "::1",
                "0:0:0:0:0:0:0:1",
            }
            host = self.bind_address.lower().strip("[]")
            if host not in allowed and not host.startswith("127."):
                raise CatalogShardError(
                    "catalog-owner Quack endpoints must be loopback-only by default"
                )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "endpoint_id": self.endpoint_id,
                "bind_address": self.bind_address,
                "port": self.port,
                "tls_required": self.tls_required,
                "loopback_only": self.loopback_only,
                "token_reference_id": self.token_reference_id,
            }
        )


def build_quack_endpoint(
    *,
    endpoint_id: str,
    bind_address: str = "127.0.0.1",
    port: int,
    tls_required: bool = True,
    loopback_only: bool = True,
    token_reference_id: str | None = None,
) -> QuackEndpointIdentity:
    return QuackEndpointIdentity(
        endpoint_id=endpoint_id,
        bind_address=bind_address,
        port=port,
        tls_required=tls_required,
        loopback_only=loopback_only,
        token_reference_id=token_reference_id,
    )


@dataclass(frozen=True, slots=True)
class OwnerGenerationReceipt:
    """Durable owner-generation lease receipt for one catalog shard."""

    receipt_id: str
    catalog_id: str
    shard_id: str
    generation: int
    fencing_epoch: int
    owner: OwnerProcessIdentity
    endpoint: QuackEndpointIdentity
    catalog_digest: str
    lease_expires_at_unix: int
    admission_open: bool
    issued_at_unix: int

    def __post_init__(self) -> None:
        if self.generation <= 0:
            raise CatalogShardError("owner generation must be positive")
        if self.fencing_epoch < 0:
            raise CatalogShardError("fencing_epoch must be non-negative")
        if not self.catalog_id or not self.shard_id:
            raise CatalogShardError("catalog_id and shard_id are required")
        digest = self.catalog_digest
        if digest.startswith("sha256:"):
            hex_part = digest[7:]
        else:
            hex_part = digest
            object.__setattr__(self, "catalog_digest", f"sha256:{digest}")
        if len(hex_part) != 64 or any(c not in "0123456789abcdef" for c in hex_part):
            raise CatalogShardError("catalog_digest must be sha256 hex")
        if self.lease_expires_at_unix < self.issued_at_unix:
            raise CatalogShardError("lease expiry must not precede issued_at")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "receipt_id": self.receipt_id,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "generation": self.generation,
                "fencing_epoch": self.fencing_epoch,
                "owner": dict(self.owner.as_mapping()),
                "endpoint": dict(self.endpoint.as_mapping()),
                "catalog_digest": self.catalog_digest,
                "lease_expires_at_unix": self.lease_expires_at_unix,
                "admission_open": self.admission_open,
                "issued_at_unix": self.issued_at_unix,
            }
        )


def build_owner_generation_receipt(
    *,
    catalog_id: str,
    shard_id: str,
    generation: int,
    fencing_epoch: int,
    owner: OwnerProcessIdentity,
    endpoint: QuackEndpointIdentity,
    catalog_digest: str,
    lease_ttl_seconds: int = 3600,
    admission_open: bool = True,
    issued_at_unix: int | None = None,
) -> OwnerGenerationReceipt:
    """Build a durable owner-generation receipt (no I/O)."""

    issued = int(issued_at_unix if issued_at_unix is not None else time.time())
    if lease_ttl_seconds <= 0:
        raise CatalogShardError("lease_ttl_seconds must be positive")
    digest = (
        catalog_digest
        if catalog_digest.startswith("sha256:")
        else f"sha256:{catalog_digest}"
    )
    receipt_id = "ogen:" + hashlib.sha256(
        f"{catalog_id}|{shard_id}|{generation}|{fencing_epoch}|{digest}|{owner.process_id}".encode()
    ).hexdigest()[:28]
    return OwnerGenerationReceipt(
        receipt_id=receipt_id,
        catalog_id=catalog_id,
        shard_id=shard_id,
        generation=int(generation),
        fencing_epoch=int(fencing_epoch),
        owner=owner,
        endpoint=endpoint,
        catalog_digest=digest,
        lease_expires_at_unix=issued + int(lease_ttl_seconds),
        admission_open=bool(admission_open),
        issued_at_unix=issued,
    )


# ---------------------------------------------------------------------------
# ATTACH options
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttachAuthorization:
    """Separate authorization required for bootstrap or migration ATTACH modes."""

    operation: PrivilegedOperation
    authorization_id: str
    catalog_id: str
    shard_id: str
    owner_generation: int
    caller_principal: str
    nonce: str
    expires_at_unix: int
    issued_by_broker: str

    def __post_init__(self) -> None:
        if self.operation not in {
            PrivilegedOperation.BOOTSTRAP_ATTACH,
            PrivilegedOperation.MIGRATION_ATTACH,
        }:
            raise CatalogShardError(
                "attach authorization operation must be bootstrap_attach or migration_attach"
            )
        if not self.authorization_id or not self.issued_by_broker:
            raise CatalogShardError("authorization_id and issued_by_broker are required")
        if not self.caller_principal or not self.nonce:
            raise CatalogShardError("caller_principal and nonce are required")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "operation": self.operation.value,
                "authorization_id": self.authorization_id,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "owner_generation": self.owner_generation,
                "caller_principal": self.caller_principal,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "issued_by_broker": self.issued_by_broker,
            }
        )


@dataclass(frozen=True, slots=True)
class AttachOptions:
    """Resolved DuckLake ATTACH option set with mode and authorization evidence."""

    mode: AttachMode
    create_if_not_exists: bool
    override_data_path: bool
    automatic_migration: bool
    authorization: AttachAuthorization | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, AttachMode):
            object.__setattr__(self, "mode", AttachMode(self.mode))
        if self.mode is AttachMode.RUNTIME:
            if self.create_if_not_exists or self.override_data_path or self.automatic_migration:
                raise CatalogShardError(
                    "runtime ATTACH must set CREATE_IF_NOT_EXISTS=false, "
                    "OVERRIDE_DATA_PATH=false, and AUTOMATIC_MIGRATION=false"
                )
            if self.authorization is not None:
                raise CatalogShardError(
                    "runtime ATTACH must not carry bootstrap/migration authorization"
                )
        else:
            if self.authorization is None:
                raise AttachAuthorizationError(
                    f"{self.mode.value} ATTACH requires a separate broker authorization"
                )
            expected = (
                PrivilegedOperation.BOOTSTRAP_ATTACH
                if self.mode is AttachMode.BOOTSTRAP
                else PrivilegedOperation.MIGRATION_ATTACH
            )
            if self.authorization.operation is not expected:
                raise AttachAuthorizationError(
                    f"{self.mode.value} ATTACH authorization operation mismatch"
                )

    @property
    def as_duckdb_options(self) -> Mapping[str, bool]:
        return MappingProxyType(
            {
                "CREATE_IF_NOT_EXISTS": self.create_if_not_exists,
                "OVERRIDE_DATA_PATH": self.override_data_path,
                "AUTOMATIC_MIGRATION": self.automatic_migration,
            }
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "mode": self.mode.value,
                "CREATE_IF_NOT_EXISTS": self.create_if_not_exists,
                "OVERRIDE_DATA_PATH": self.override_data_path,
                "AUTOMATIC_MIGRATION": self.automatic_migration,
                "authorization": (
                    None
                    if self.authorization is None
                    else dict(self.authorization.as_mapping())
                ),
            }
        )


def build_attach_options(
    mode: AttachMode | str = AttachMode.RUNTIME,
    *,
    create_if_not_exists: bool | None = None,
    override_data_path: bool | None = None,
    automatic_migration: bool | None = None,
    authorization: AttachAuthorization | None = None,
    now_unix: int | None = None,
) -> AttachOptions:
    """Build ATTACH options; runtime mode always forces the three safe flags.

    Bootstrap and migration modes may request non-safe flags only when a
    separately issued :class:`AttachAuthorization` is supplied and unexpired.
    """

    mode_value = AttachMode(mode) if not isinstance(mode, AttachMode) else mode
    if mode_value is AttachMode.RUNTIME:
        return AttachOptions(
            mode=AttachMode.RUNTIME,
            create_if_not_exists=False,
            override_data_path=False,
            automatic_migration=False,
            authorization=None,
        )

    if authorization is None:
        raise AttachAuthorizationError(
            f"{mode_value.value} ATTACH requires separate broker authorization"
        )
    clock = int(now_unix if now_unix is not None else time.time())
    if authorization.expires_at_unix <= clock:
        raise AttachAuthorizationError(
            f"{mode_value.value} ATTACH authorization has expired"
        )

    # Defaults for authorized bootstrap/migration still prefer safe values
    # unless the caller explicitly opts into non-safe flags.
    cif = False if create_if_not_exists is None else bool(create_if_not_exists)
    odp = False if override_data_path is None else bool(override_data_path)
    am = False if automatic_migration is None else bool(automatic_migration)

    if mode_value is AttachMode.BOOTSTRAP and not cif:
        # Bootstrap without CREATE is legal but unusual; allow as explicit.
        pass

    return AttachOptions(
        mode=mode_value,
        create_if_not_exists=cif,
        override_data_path=odp,
        automatic_migration=am,
        authorization=authorization,
    )


def inspect_attach_options(
    options: AttachOptions | Mapping[str, Any],
    *,
    require_runtime_safe: bool = True,
) -> Mapping[str, Any]:
    """Inspect ATTACH options and prove the non-bootstrap safety contract.

    When ``require_runtime_safe`` is true (default), any options that are not
    an authorized bootstrap/migration with explicit non-safe flags must show:

    * CREATE_IF_NOT_EXISTS = false
    * OVERRIDE_DATA_PATH = false
    * AUTOMATIC_MIGRATION = false
    """

    if isinstance(options, AttachOptions):
        mapping = dict(options.as_mapping())
        mode = options.mode
        cif = options.create_if_not_exists
        odp = options.override_data_path
        am = options.automatic_migration
        authorized = options.authorization is not None
    else:
        mapping = dict(options)
        mode_raw = mapping.get("mode", AttachMode.RUNTIME.value)
        mode = AttachMode(mode_raw) if not isinstance(mode_raw, AttachMode) else mode_raw
        cif = bool(mapping.get("CREATE_IF_NOT_EXISTS", True))
        odp = bool(mapping.get("OVERRIDE_DATA_PATH", True))
        am = bool(mapping.get("AUTOMATIC_MIGRATION", True))
        authorized = mapping.get("authorization") is not None

    is_safe = (cif is False) and (odp is False) and (am is False)
    is_privileged_mode = mode in {AttachMode.BOOTSTRAP, AttachMode.MIGRATION}

    if require_runtime_safe:
        if not is_safe and not (is_privileged_mode and authorized):
            raise CatalogShardError(
                "non-bootstrap/non-migration ATTACH must set "
                "CREATE_IF_NOT_EXISTS=false, OVERRIDE_DATA_PATH=false, "
                "and AUTOMATIC_MIGRATION=false"
            )
        if is_privileged_mode and not authorized:
            raise AttachAuthorizationError(
                f"{mode.value} ATTACH inspected without separate authorization"
            )

    return MappingProxyType(
        {
            "mode": mode.value if isinstance(mode, AttachMode) else str(mode),
            "CREATE_IF_NOT_EXISTS": cif,
            "OVERRIDE_DATA_PATH": odp,
            "AUTOMATIC_MIGRATION": am,
            "is_safe": is_safe,
            "authorized_privileged": bool(is_privileged_mode and authorized),
            "options": mapping,
        }
    )


# ---------------------------------------------------------------------------
# Takeover evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NativeFileLockEvidence:
    """Proof that DuckDB's native file lock was acquired before open."""

    path: str
    acquired: bool
    locker_process_id: str
    acquisition_unix: int

    def __post_init__(self) -> None:
        if not self.path or not self.locker_process_id:
            raise CatalogShardError("file-lock path and locker_process_id are required")
        if not self.acquired:
            raise TakeoverError("native DuckDB file lock was not acquired")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "path": self.path,
                "acquired": self.acquired,
                "locker_process_id": self.locker_process_id,
                "acquisition_unix": self.acquisition_unix,
            }
        )


@dataclass(frozen=True, slots=True)
class TakeoverEvidence:
    """Complete active/passive takeover evidence package (all fields required)."""

    prior_generation_receipt: OwnerGenerationReceipt
    successor_generation_receipt: OwnerGenerationReceipt
    prior_stopped_admission: bool
    prior_process_dead_or_fenced: bool
    endpoint_token_revoked: bool
    storage_capabilities_expired: bool
    all_handles_closed: bool
    catalog_digest_matches: bool
    catalog_generation_matches: bool
    native_file_lock: NativeFileLockEvidence

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "prior_generation_receipt": dict(
                    self.prior_generation_receipt.as_mapping()
                ),
                "successor_generation_receipt": dict(
                    self.successor_generation_receipt.as_mapping()
                ),
                "prior_stopped_admission": self.prior_stopped_admission,
                "prior_process_dead_or_fenced": self.prior_process_dead_or_fenced,
                "endpoint_token_revoked": self.endpoint_token_revoked,
                "storage_capabilities_expired": self.storage_capabilities_expired,
                "all_handles_closed": self.all_handles_closed,
                "catalog_digest_matches": self.catalog_digest_matches,
                "catalog_generation_matches": self.catalog_generation_matches,
                "native_file_lock": dict(self.native_file_lock.as_mapping()),
            }
        )


def evaluate_takeover(evidence: TakeoverEvidence) -> Mapping[str, Any]:
    """Validate active/passive takeover; fail closed on any missing precondition.

    Required:

    1. durable prior and successor owner-generation receipts
    2. prior stopped admission
    3. prior process dead or fenced
    4. endpoint/token revoked
    5. storage capabilities expired
    6. all handles closed
    7. exact catalog digest match
    8. successor generation is prior + 1 (monotonic)
    9. native DuckDB file lock acquired by successor before open
    """

    prior = evidence.prior_generation_receipt
    succ = evidence.successor_generation_receipt
    problems: list[str] = []

    if prior.catalog_id != succ.catalog_id or prior.shard_id != succ.shard_id:
        problems.append("successor receipt catalog/shard identity mismatch")
    if succ.generation != prior.generation + 1:
        problems.append(
            f"successor generation {succ.generation} must be prior {prior.generation} + 1"
        )
    if succ.fencing_epoch <= prior.fencing_epoch:
        problems.append("successor fencing_epoch must advance")
    if prior.owner.process_id == succ.owner.process_id:
        problems.append("successor must be a distinct owner process identity")
    if not evidence.prior_stopped_admission:
        problems.append("prior owner must stop admission before takeover")
    if prior.admission_open:
        problems.append("prior generation receipt still shows admission_open")
    if not evidence.prior_process_dead_or_fenced:
        problems.append("prior process must be proven dead or fenced")
    if not evidence.endpoint_token_revoked:
        problems.append("prior endpoint/token must be revoked")
    if not evidence.storage_capabilities_expired:
        problems.append("prior storage capabilities must be expired")
    if not evidence.all_handles_closed:
        problems.append("all prior catalog and registry handles must be closed")
    if not evidence.catalog_digest_matches:
        problems.append("exact catalog digest must match the receipted generation")
    if prior.catalog_digest != succ.catalog_digest:
        problems.append("prior and successor catalog digests disagree")
    if not evidence.catalog_generation_matches:
        problems.append("exact catalog generation must match before open")
    if not evidence.native_file_lock.acquired:
        problems.append("native DuckDB file lock must be acquired before open")
    if evidence.native_file_lock.locker_process_id != succ.owner.process_id:
        problems.append("file lock must be held by the successor owner process")

    if problems:
        raise TakeoverError("; ".join(problems))

    return MappingProxyType(
        {
            "allowed": True,
            "prior_generation": prior.generation,
            "successor_generation": succ.generation,
            "catalog_id": succ.catalog_id,
            "shard_id": succ.shard_id,
            "catalog_digest": succ.catalog_digest,
            "reason": "all active/passive takeover preconditions satisfied",
        }
    )


# ---------------------------------------------------------------------------
# Remote access policy
# ---------------------------------------------------------------------------


def assert_remote_cannot_open_catalog(
    *,
    caller_role: IdentityRole | str,
    action: str,
    identities: Mapping[IdentityRole, IdentityCapabilityProfile] | None = None,
) -> None:
    """Fail closed when a non-owner identity tries to open/mount/mutate the file.

    Remote clients (reader, writer, maintainer, untrusted agents) must submit
    typed remote requests to the single owner and must never open, copy into
    place, or network-mount the live catalog file.
    """

    role = IdentityRole(caller_role) if not isinstance(caller_role, IdentityRole) else caller_role
    forbidden_actions = {
        "open",
        "open_catalog",
        "mount",
        "network_mount",
        "copy_into_place",
        "mutate_file",
        "direct_attach",
        "replace_file",
    }
    action_key = action.strip().lower()
    if action_key not in forbidden_actions:
        # Non-file actions are not in scope for this guard.
        return

    if identities is not None and role in identities:
        profile = identities[role]
        if not profile.may_open_catalog_file:
            raise RemoteCatalogAccessError(
                f"{role.value} cannot {action_key} the live catalog file; "
                "submit typed remote requests to the fenced owner"
            )
        return

    if role is not IdentityRole.OWNER_BROKER:
        raise RemoteCatalogAccessError(
            f"{role.value} cannot {action_key} the live catalog file; "
            "only the identity-bound owner process may open it"
        )


# ---------------------------------------------------------------------------
# One-use Quack capability and trusted owner broker
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OneUseQuackCapability:
    """One-use Quack transport capability injected only into a trusted worker.

    The capability material is held privately and never appears in
    :meth:`as_mapping` projections. Untrusted agents never receive it.
    """

    capability_id: str
    endpoint_id: str
    owner_generation: int
    worker_principal: str
    worker_process_id: str
    operation: PrivilegedOperation
    nonce: str
    expires_at_unix: int
    _material: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self._material:
            raise CatalogShardError("one-use Quack capability material is required")
        if not self.worker_principal or not self.worker_process_id:
            raise CatalogShardError("worker principal and process_id are required")
        if self.expires_at_unix <= 0:
            raise CatalogShardError("capability expiry must be positive")

    @property
    def consumed(self) -> bool:
        # Immutable snapshot; consumption is tracked by the broker.
        return False

    def as_mapping(self) -> Mapping[str, Any]:
        """Safe projection — never includes the capability material."""

        return MappingProxyType(
            {
                "kind": "one_use_quack_capability",
                "capability_id": self.capability_id,
                "endpoint_id": self.endpoint_id,
                "owner_generation": self.owner_generation,
                "worker_principal": self.worker_principal,
                "worker_process_id": self.worker_process_id,
                "operation": self.operation.value,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                # material intentionally omitted
            }
        )


@dataclass
class TrustedOwnerBroker:
    """Trusted owner broker: independent authorization outside DuckLake.

    DuckLake supplies no role or authorization layer
    (:data:`DUCKLAKE_HAS_AUTHORIZATION_LAYER` is false). This broker:

    * independently authorizes every privileged call;
    * retains reusable Quack tokens;
    * injects a one-use Quack capability only into an identity-bound trusted
      worker;
    * mints short-lived object-delete IAM only for authorized deletions.
    """

    broker_principal: str
    shard_id: str
    catalog_id: str
    owner_generation: int
    endpoint: QuackEndpointIdentity
    identities: Mapping[IdentityRole, IdentityCapabilityProfile]
    _consumed_capabilities: set[str] = field(default_factory=set, repr=False)
    _retained_token_ref: str | None = field(default=None, repr=False)
    _authorized_nonces: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if DUCKLAKE_HAS_AUTHORIZATION_LAYER:
            raise CatalogShardError(
                "invariant broken: DuckLake must not supply an authorization layer"
            )
        if not self.broker_principal:
            raise CatalogShardError("broker_principal is required")
        owner = self.identities.get(IdentityRole.OWNER_BROKER)
        if owner is None:
            raise CatalogShardError("identities must include owner_broker")
        if not owner.may_open_catalog_file:
            raise CatalogShardError("owner_broker must be allowed to open the catalog file")

    @property
    def ducklake_authorization_layer(self) -> bool:
        return DUCKLAKE_HAS_AUTHORIZATION_LAYER

    def authorize(
        self,
        *,
        operation: PrivilegedOperation | str,
        caller_role: IdentityRole | str,
        caller_principal: str,
        caller_process_id: str,
        resource: str,
        nonce: str,
        now_unix: int | None = None,
        ttl_seconds: int = 300,
    ) -> Mapping[str, Any]:
        """Independently authorize a privileged operation (not DuckLake roles)."""

        if DUCKLAKE_HAS_AUTHORIZATION_LAYER:
            raise CatalogShardError("DuckLake must not authorize operations")

        op = (
            PrivilegedOperation(operation)
            if not isinstance(operation, PrivilegedOperation)
            else operation
        )
        role = (
            IdentityRole(caller_role)
            if not isinstance(caller_role, IdentityRole)
            else caller_role
        )
        if nonce in self._authorized_nonces:
            raise CatalogShardError(f"authorization nonce {nonce!r} already used")
        if role not in self.identities:
            raise CatalogShardError(f"unknown caller role {role.value}")
        profile = self.identities[role]

        # Quack token alone is never sufficient — presence of a role profile
        # and broker decision is required. Readers may only snapshot_read.
        allowed: dict[IdentityRole, frozenset[PrivilegedOperation]] = {
            IdentityRole.READER: frozenset({PrivilegedOperation.SNAPSHOT_READ}),
            IdentityRole.WRITER: frozenset(
                {
                    PrivilegedOperation.SNAPSHOT_READ,
                    PrivilegedOperation.INGEST_REGISTER,
                }
            ),
            IdentityRole.MAINTAINER: frozenset(
                {
                    PrivilegedOperation.SNAPSHOT_READ,
                    PrivilegedOperation.MAINTENANCE_DRY_RUN,
                    PrivilegedOperation.MAINTENANCE_EXECUTE,
                    PrivilegedOperation.OBJECT_DELETE,
                }
            ),
            IdentityRole.OWNER_BROKER: frozenset(PrivilegedOperation),
        }
        if op not in allowed[role]:
            raise CatalogShardError(
                f"{role.value} is not authorized for {op.value}"
            )
        if op is PrivilegedOperation.OBJECT_DELETE and not profile.may_receive_object_delete_iam:
            raise CatalogShardError(
                f"{role.value} cannot receive object-delete IAM"
            )

        clock = int(now_unix if now_unix is not None else time.time())
        self._authorized_nonces.add(nonce)
        authorization_id = "authz:" + hashlib.sha256(
            f"{self.broker_principal}|{op.value}|{caller_principal}|{nonce}|{resource}".encode()
        ).hexdigest()[:24]
        return MappingProxyType(
            {
                "authorization_id": authorization_id,
                "operation": op.value,
                "caller_role": role.value,
                "caller_principal": caller_principal,
                "caller_process_id": caller_process_id,
                "resource": resource,
                "nonce": nonce,
                "issued_by_broker": self.broker_principal,
                "owner_generation": self.owner_generation,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "expires_at_unix": clock + int(ttl_seconds),
                "ducklake_authorized": False,
                "broker_authorized": True,
            }
        )

    def inject_one_use_quack_capability(
        self,
        *,
        worker_principal: str,
        worker_process_id: str,
        worker_role: IdentityRole | str,
        operation: PrivilegedOperation | str,
        authorization: Mapping[str, Any],
        now_unix: int | None = None,
        ttl_seconds: int = 60,
    ) -> OneUseQuackCapability:
        """Inject a one-use Quack capability into an identity-bound trusted worker.

        Untrusted agents and roles that may not receive transport capabilities
        fail closed. The reusable endpoint token remains inside the broker.
        """

        role = (
            IdentityRole(worker_role)
            if not isinstance(worker_role, IdentityRole)
            else worker_role
        )
        op = (
            PrivilegedOperation(operation)
            if not isinstance(operation, PrivilegedOperation)
            else operation
        )
        if role is IdentityRole.READER and op not in {
            PrivilegedOperation.SNAPSHOT_READ,
            PrivilegedOperation.INJECT_QUACK_CAPABILITY,
        }:
            pass  # further checks below

        # Only identity-bound workers with an authorization for the same
        # principal may receive the capability.
        if authorization.get("caller_principal") != worker_principal:
            raise CatalogShardError(
                "Quack capability principal must match the authorization principal"
            )
        if authorization.get("broker_authorized") is not True:
            raise CatalogShardError(
                "Quack capability requires broker authorization; "
                "a Quack token alone cannot authorize"
            )
        if authorization.get("ducklake_authorized") is True:
            raise CatalogShardError(
                "DuckLake must not appear as the authorization source"
            )
        if role not in self.identities:
            raise CatalogShardError(f"unknown worker role {role.value}")
        profile = self.identities[role]
        if profile.may_receive_reusable_quack_token:
            raise CatalogShardError(
                "workers must not receive reusable Quack tokens; one-use only"
            )

        clock = int(now_unix if now_unix is not None else time.time())
        expires = authorization.get("expires_at_unix")
        if expires is not None and int(expires) <= clock:
            raise CatalogShardError("authorization expired; cannot inject capability")

        nonce = secrets.token_hex(8)
        material = secrets.token_urlsafe(32)
        capability_id = "q1:" + hashlib.sha256(
            f"{self.endpoint.endpoint_id}|{worker_process_id}|{nonce}|{op.value}".encode()
        ).hexdigest()[:24]
        return OneUseQuackCapability(
            capability_id=capability_id,
            endpoint_id=self.endpoint.endpoint_id,
            owner_generation=self.owner_generation,
            worker_principal=worker_principal,
            worker_process_id=worker_process_id,
            operation=op,
            nonce=nonce,
            expires_at_unix=clock + int(ttl_seconds),
            _material=material,
        )

    def consume_quack_capability(
        self,
        capability: OneUseQuackCapability,
        *,
        now_unix: int | None = None,
    ) -> str:
        """Consume a one-use capability and return its material exactly once."""

        if capability.capability_id in self._consumed_capabilities:
            raise CatalogShardError(
                f"Quack capability {capability.capability_id} already consumed"
            )
        clock = int(now_unix if now_unix is not None else time.time())
        if capability.expires_at_unix <= clock:
            raise CatalogShardError("Quack capability expired")
        self._consumed_capabilities.add(capability.capability_id)
        return capability._material

    def mint_object_delete_iam(
        self,
        *,
        caller_role: IdentityRole | str,
        authorization: Mapping[str, Any],
        resource_prefix: str,
        ttl_seconds: int = 300,
    ) -> ObjectDeleteIAMCapability:
        """Mint short-lived object-delete IAM for an authorized deletion only."""

        role = (
            IdentityRole(caller_role)
            if not isinstance(caller_role, IdentityRole)
            else caller_role
        )
        if role in {IdentityRole.READER, IdentityRole.WRITER}:
            raise CatalogConfigError(
                f"{role.value} must not receive object-delete IAM"
            )
        if authorization.get("operation") != PrivilegedOperation.OBJECT_DELETE.value:
            raise CatalogShardError(
                "object-delete IAM requires an object_delete authorization"
            )
        if authorization.get("broker_authorized") is not True:
            raise CatalogShardError("object-delete IAM requires broker authorization")
        profile = self.identities[role]
        if not profile.may_receive_object_delete_iam:
            raise CatalogConfigError(
                f"{role.value} is not eligible for object-delete IAM"
            )
        return build_object_delete_capability(
            principal=str(authorization["caller_principal"]),
            resource_prefix=resource_prefix,
            issued_for_operation=str(authorization["authorization_id"]),
            ttl_seconds=ttl_seconds,
            nonce=str(authorization["nonce"]),
        )

    def issue_attach_authorization(
        self,
        *,
        mode: AttachMode | str,
        caller_principal: str,
        nonce: str,
        now_unix: int | None = None,
        ttl_seconds: int = 600,
    ) -> AttachAuthorization:
        """Issue separate bootstrap/migration ATTACH authorization."""

        mode_value = AttachMode(mode) if not isinstance(mode, AttachMode) else mode
        if mode_value is AttachMode.RUNTIME:
            raise CatalogShardError("runtime ATTACH does not use attach authorization")
        op = (
            PrivilegedOperation.BOOTSTRAP_ATTACH
            if mode_value is AttachMode.BOOTSTRAP
            else PrivilegedOperation.MIGRATION_ATTACH
        )
        clock = int(now_unix if now_unix is not None else time.time())
        authorization_id = "attach-authz:" + hashlib.sha256(
            f"{self.broker_principal}|{op.value}|{caller_principal}|{nonce}".encode()
        ).hexdigest()[:24]
        return AttachAuthorization(
            operation=op,
            authorization_id=authorization_id,
            catalog_id=self.catalog_id,
            shard_id=self.shard_id,
            owner_generation=self.owner_generation,
            caller_principal=caller_principal,
            nonce=nonce,
            expires_at_unix=clock + int(ttl_seconds),
            issued_by_broker=self.broker_principal,
        )


# ---------------------------------------------------------------------------
# Catalog shard profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogShardProfile:
    """Typed binding of one logical catalog shard to its sole owner and storage."""

    schema: str
    catalog_id: str
    shard_id: str
    storage: StorageProfile
    secrets: SecretProfile
    identities: Mapping[IdentityRole, IdentityCapabilityProfile]
    owner_generation: OwnerGenerationReceipt
    quack_endpoint: QuackEndpointIdentity
    single_owner: bool = True
    remote_clients_open_catalog_file: bool = False
    same_shard_serialized: bool = True
    independent_shards_concurrent: bool = True
    ducklake_authorization_layer: bool = False

    def __post_init__(self) -> None:
        if self.schema != CATALOG_SHARD_PROFILE_SCHEMA:
            raise CatalogShardError(
                f"catalog shard profile schema must be {CATALOG_SHARD_PROFILE_SCHEMA!r}"
            )
        if not self.catalog_id or not self.shard_id:
            raise CatalogShardError("catalog_id and shard_id are required")
        if not self.single_owner:
            raise CatalogOwnershipError(
                "each catalog shard must have exactly one identity-bound owner"
            )
        if self.remote_clients_open_catalog_file:
            raise RemoteCatalogAccessError(
                "remote clients must not open the live catalog file"
            )
        if not self.same_shard_serialized:
            raise CatalogShardError(
                "same-shard requests must be serialized through the fenced owner"
            )
        if not self.independent_shards_concurrent:
            raise CatalogShardError(
                "independent shards must be allowed to run concurrently"
            )
        if self.ducklake_authorization_layer or DUCKLAKE_HAS_AUTHORIZATION_LAYER:
            raise CatalogShardError(
                "DuckLake supplies no role or authorization layer"
            )
        if self.owner_generation.catalog_id != self.catalog_id:
            raise CatalogShardError("owner generation catalog_id mismatch")
        if self.owner_generation.shard_id != self.shard_id:
            raise CatalogShardError("owner generation shard_id mismatch")
        if self.owner_generation.endpoint.endpoint_id != self.quack_endpoint.endpoint_id:
            raise CatalogShardError("owner generation endpoint mismatch")
        if IdentityRole.OWNER_BROKER not in self.identities:
            raise CatalogShardError("identities must include owner_broker")
        owner_identity = self.identities[IdentityRole.OWNER_BROKER]
        if not owner_identity.may_open_catalog_file:
            raise CatalogOwnershipError(
                "owner_broker is the sole identity permitted to open the catalog file"
            )
        if self.owner_generation.owner.principal != owner_identity.principal:
            # Allow process principal to match broker principal or be a
            # dedicated owner process under the broker identity family.
            if not self.owner_generation.owner.principal.startswith("owner"):
                raise CatalogOwnershipError(
                    "owner process principal must be the owner-broker identity family"
                )
        frozen = {
            (k if isinstance(k, IdentityRole) else IdentityRole(k)): v
            for k, v in dict(self.identities).items()
        }
        object.__setattr__(self, "identities", MappingProxyType(frozen))

    @property
    def catalog_metadata_path(self) -> str:
        return self.storage.catalog_metadata.path

    @property
    def companion_registry_path(self) -> str:
        return self.storage.companion_registry.path

    @property
    def parquet_data_path(self) -> str:
        return self.storage.parquet_namespace.data_path.path

    def runtime_attach_options(self) -> AttachOptions:
        """Return the mandatory safe ATTACH options for non-bootstrap use."""

        return build_attach_options(AttachMode.RUNTIME)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "storage": dict(self.storage.as_mapping()),
                "secrets": dict(self.secrets.as_mapping()),
                "identities": {
                    role.value: dict(profile.as_mapping())
                    for role, profile in self.identities.items()
                },
                "owner_generation": dict(self.owner_generation.as_mapping()),
                "quack_endpoint": dict(self.quack_endpoint.as_mapping()),
                "single_owner": self.single_owner,
                "remote_clients_open_catalog_file": self.remote_clients_open_catalog_file,
                "same_shard_serialized": self.same_shard_serialized,
                "independent_shards_concurrent": self.independent_shards_concurrent,
                "ducklake_authorization_layer": self.ducklake_authorization_layer,
                "implementation_generation": _CATALOG_IMPLEMENTATION_GENERATION,
            }
        )

    def make_broker(self) -> TrustedOwnerBroker:
        """Construct a trusted owner broker bound to this shard profile."""

        return TrustedOwnerBroker(
            broker_principal=self.identities[IdentityRole.OWNER_BROKER].principal,
            shard_id=self.shard_id,
            catalog_id=self.catalog_id,
            owner_generation=self.owner_generation.generation,
            endpoint=self.quack_endpoint,
            identities=self.identities,
            _retained_token_ref=self.quack_endpoint.token_reference_id,
        )


def build_catalog_shard_profile(
    *,
    catalog_id: str,
    shard_id: str,
    storage: StorageProfile,
    secrets: SecretProfile,
    owner: OwnerProcessIdentity,
    endpoint: QuackEndpointIdentity,
    catalog_digest: str,
    generation: int = 1,
    fencing_epoch: int = 1,
    identities: Mapping[IdentityRole, IdentityCapabilityProfile] | None = None,
    lease_ttl_seconds: int = 3600,
    issued_at_unix: int | None = None,
) -> CatalogShardProfile:
    """Build a complete catalog-shard profile from typed sub-profiles."""

    id_map = identities or build_identity_profiles(
        shard_id=shard_id,
        object_prefix=storage.parquet_namespace.data_path.path,
    )
    receipt = build_owner_generation_receipt(
        catalog_id=catalog_id,
        shard_id=shard_id,
        generation=generation,
        fencing_epoch=fencing_epoch,
        owner=owner,
        endpoint=endpoint,
        catalog_digest=catalog_digest,
        lease_ttl_seconds=lease_ttl_seconds,
        admission_open=True,
        issued_at_unix=issued_at_unix,
    )
    return CatalogShardProfile(
        schema=CATALOG_SHARD_PROFILE_SCHEMA,
        catalog_id=catalog_id,
        shard_id=shard_id,
        storage=storage,
        secrets=secrets,
        identities=id_map,
        owner_generation=receipt,
        quack_endpoint=endpoint,
    )


def project_shard_profile(profile: CatalogShardProfile) -> Mapping[str, Any]:
    """Project a shard profile safe for untrusted agents and logs."""

    projection = project_safe_config(
        storage=profile.storage,
        secrets=profile.secrets,
        identities=profile.identities,
        extra={
            "catalog_id": profile.catalog_id,
            "shard_id": profile.shard_id,
            "owner_generation": {
                "generation": profile.owner_generation.generation,
                "fencing_epoch": profile.owner_generation.fencing_epoch,
                "receipt_id": profile.owner_generation.receipt_id,
                "catalog_digest": profile.owner_generation.catalog_digest,
                "admission_open": profile.owner_generation.admission_open,
                "owner_process_id": profile.owner_generation.owner.process_id,
                "endpoint_id": profile.quack_endpoint.endpoint_id,
            },
            "quack_endpoint": dict(profile.quack_endpoint.as_mapping()),
            "single_owner": profile.single_owner,
            "remote_clients_open_catalog_file": profile.remote_clients_open_catalog_file,
            "ducklake_authorization_layer": profile.ducklake_authorization_layer,
            "runtime_attach_options": dict(
                profile.runtime_attach_options().as_duckdb_options
            ),
        },
    )
    assert_no_secret_material(projection)
    return projection


# ---------------------------------------------------------------------------
# Multi-shard plane: serialize same-shard, concurrent cross-shard
# ---------------------------------------------------------------------------


class CatalogShardPlane:
    """In-process plane tracking independent shards and same-shard serialization.

    This is a pure coordination helper for tests and owner-side code. It does
    not open DuckDB files. Independent shards may hold locks concurrently;
    same-shard requests are serialized through a per-shard mutex.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, CatalogShardProfile] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._owners: dict[str, str] = {}
        self._gate = threading.RLock()

    def register(self, profile: CatalogShardProfile) -> None:
        with self._gate:
            key = self._key(profile.catalog_id, profile.shard_id)
            if key in self._profiles:
                existing = self._profiles[key]
                if existing.owner_generation.owner.process_id != (
                    profile.owner_generation.owner.process_id
                ):
                    raise CatalogOwnershipError(
                        f"shard {key} already has owner "
                        f"{existing.owner_generation.owner.process_id}; "
                        "refusing second owner without takeover"
                    )
            self._profiles[key] = profile
            self._locks.setdefault(key, threading.RLock())
            self._owners[key] = profile.owner_generation.owner.process_id

    def get(self, catalog_id: str, shard_id: str) -> CatalogShardProfile:
        key = self._key(catalog_id, shard_id)
        try:
            return self._profiles[key]
        except KeyError as exc:
            raise CatalogShardError(f"unknown catalog shard {key}") from exc

    def owner_process_id(self, catalog_id: str, shard_id: str) -> str:
        return self._owners[self._key(catalog_id, shard_id)]

    def serialize_same_shard(
        self,
        catalog_id: str,
        shard_id: str,
        fn: Callable[[], Any],
        *,
        caller_process_id: str | None = None,
    ) -> Any:
        """Run *fn* under the per-shard lock (same-shard serialization)."""

        key = self._key(catalog_id, shard_id)
        if key not in self._locks:
            raise CatalogShardError(f"unknown catalog shard {key}")
        if caller_process_id is not None and caller_process_id != self._owners[key]:
            raise CatalogOwnershipError(
                f"caller {caller_process_id} is not the fenced owner of {key}"
            )
        with self._locks[key]:
            return fn()

    def transfer_ownership(
        self,
        evidence: TakeoverEvidence,
    ) -> CatalogShardProfile:
        """Apply a validated takeover: replace the profile's owner generation."""

        evaluate_takeover(evidence)
        succ = evidence.successor_generation_receipt
        key = self._key(succ.catalog_id, succ.shard_id)
        with self._gate:
            if key not in self._profiles:
                raise CatalogShardError(f"unknown catalog shard {key}")
            prior_profile = self._profiles[key]
            if (
                prior_profile.owner_generation.generation
                != evidence.prior_generation_receipt.generation
            ):
                raise TakeoverError("plane prior generation does not match evidence")
            updated = CatalogShardProfile(
                schema=prior_profile.schema,
                catalog_id=prior_profile.catalog_id,
                shard_id=prior_profile.shard_id,
                storage=prior_profile.storage,
                secrets=prior_profile.secrets,
                identities=prior_profile.identities,
                owner_generation=succ,
                quack_endpoint=succ.endpoint,
            )
            self._profiles[key] = updated
            self._owners[key] = succ.owner.process_id
            return updated

    def shard_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    @staticmethod
    def _key(catalog_id: str, shard_id: str) -> str:
        return f"{catalog_id}/{shard_id}"
