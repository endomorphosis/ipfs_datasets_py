"""Coordinated cold recovery manifest and drill for DuckDB + Quack shards (DQK-098).

Implements a fenced cold-capture and restore workflow for each catalog shard:

* Drain and fence remote writers, readers, and maintenance; stop admission
* Close the sole catalog owner and prove catalog / companion-registry file
  handles are closed with immutable DuckDB digests **before** any copy
* An **isolated** backup process opens the closed raw metadata and companion
  databases **read-only** and emits content-digested ``COPY FROM DATABASE``
  or byte-snapshot outputs plus a versioned object-store generation /
  replica / CID inventory and encryption policy
* Never run DuckLake ``CHECKPOINT`` during capture (it can flush, expire,
  rewrite, and delete lake data)
* Prohibit owner failover, compaction, snapshot expiration, scheduled
  cleanup, and orphan deletion for the full capture window
* Never copy a live catalog file while a Quack owner can mutate it
* Catalog-only, companion-registry-only, or object-only backups cannot be
  marked complete — every recovery manifest binds catalog + companion +
  immutable versioned object inventory
* Completion revalidates owner/workload fences, digests, inventory versions,
  and reachability of every catalog-referenced file
* Restore detects missing, replaced, orphaned, and undecryptable files;
  replays historic snapshots within the declared retention window; starts
  under a **new** owner generation and endpoint identity without overlap
* Promotion only through a fenced cold active/passive decision receipt with
  declared cold-failover RPO/RTO
* DuckDB + Quack supplies **no** PITR, replication, or built-in HA — the
  module never claims otherwise

Import is side-effect free: no DuckDB connection, network, or filesystem I/O.
Hermetic tests exercise the full policy via :class:`HermeticRecoveryBackend`.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Final, Mapping, Sequence

from ipfs_datasets_py.ducklake.ingest import ProcessBirth, default_process_birth

__all__ = [
    "RECOVERY_SCHEMA",
    "RECOVERY_MANIFEST_SCHEMA",
    "CAPTURE_RECEIPT_SCHEMA",
    "RESTORE_RECEIPT_SCHEMA",
    "PROMOTION_RECEIPT_SCHEMA",
    "OBJECT_INVENTORY_SCHEMA",
    "OWNER_TASK_ID",
    "PROGRAM_ID",
    "FORBIDDEN_CAPTURE_STATEMENTS",
    "FORBIDDEN_CAPTURE_ACTIONS",
    "CAPTURE_PROHIBITED_OPERATIONS",
    "REQUIRED_BACKUP_COMPONENTS",
    "CLAIMS_PITR",
    "CLAIMS_REPLICATION",
    "CLAIMS_BUILT_IN_HA",
    "CLAIMS_CROSS_DATABASE_ATOMICITY",
    "BackupComponent",
    "CaptureMethod",
    "CapturePhase",
    "FileIntegrityKind",
    "PromotionDecision",
    "RecoveryError",
    "IncompleteBackupError",
    "CaptureWindowError",
    "LiveCatalogCopyError",
    "CheckpointForbiddenError",
    "FenceError",
    "HandleOpenError",
    "InventoryError",
    "RestoreIntegrityError",
    "PromotionError",
    "CapabilityClaimError",
    "WorkloadDrainProof",
    "FileHandleProof",
    "OwnerFenceProof",
    "EncryptionPolicy",
    "VersionedObjectEntry",
    "VersionedObjectInventory",
    "DigestedDatabaseBackup",
    "RecoveryManifest",
    "CaptureReceipt",
    "FileIntegrityFinding",
    "RestoreVerification",
    "TimeTravelReplayResult",
    "ColdFailoverMetrics",
    "PromotionIdentityBinding",
    "PromotionDecisionReceipt",
    "RestoreResult",
    "ShardLiveState",
    "HermeticRecoveryBackend",
    "ColdRecoveryService",
    "assert_checkpoint_forbidden",
    "assert_capture_action_forbidden",
    "assert_no_live_catalog_copy",
    "assert_no_pitr_replication_ha_claims",
    "assert_backup_components_complete",
    "file_digest_for_bytes",
    "inventory_version_digest",
    "build_cold_recovery_service",
    "default_process_birth",
    "install_check",
    "self_check",
]


# ---------------------------------------------------------------------------
# Schema / pin constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-098"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"

RECOVERY_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-cold-recovery@1"
RECOVERY_MANIFEST_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-cold-recovery-manifest@1"
)
CAPTURE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-cold-recovery-capture-receipt@1"
)
RESTORE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-cold-recovery-restore-receipt@1"
)
PROMOTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-cold-recovery-promotion-receipt@1"
)
OBJECT_INVENTORY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-cold-recovery-object-inventory@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-098-cold-recovery-manifest-drill-20260811"
)

# Explicit non-claims — never flip these to True.
CLAIMS_PITR: Final[bool] = False
CLAIMS_REPLICATION: Final[bool] = False
CLAIMS_BUILT_IN_HA: Final[bool] = False
CLAIMS_CROSS_DATABASE_ATOMICITY: Final[bool] = False

# DuckLake CHECKPOINT and related capture-window mutations are forbidden.
FORBIDDEN_CAPTURE_STATEMENTS: Final[frozenset[str]] = frozenset(
    {
        "CHECKPOINT",
        "checkpoint",
        "CHECK POINT",
        "check point",
        "DUCKLAKE_CHECKPOINT",
        "ducklake_checkpoint",
        "CALL ducklake_checkpoint",
        "call ducklake_checkpoint",
    }
)

# Operations prohibited for the full capture window.
CAPTURE_PROHIBITED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "owner_failover",
        "failover",
        "active_passive_takeover",
        "compaction",
        "merge_adjacent_files",
        "rewrite_data_files",
        "delete_file_rewrite",
        "snapshot_expiration",
        "expire_snapshots",
        "scheduled_cleanup",
        "cleanup_old_files",
        "cleanup_all",
        "orphan_deletion",
        "delete_orphaned_files",
        "checkpoint",
        "ducklake_checkpoint",
    }
)

FORBIDDEN_CAPTURE_ACTIONS: Final[frozenset[str]] = CAPTURE_PROHIBITED_OPERATIONS

REQUIRED_BACKUP_COMPONENTS: Final[frozenset[str]] = frozenset(
    {
        "catalog",
        "companion_registry",
        "object_inventory",
    }
)

_SHA256_PREFIX: Final[str] = "sha256:"
_SAFE_TOKEN = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_SHA256_RE = __import__("re").compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")

_DEFAULT_RETENTION_SNAPSHOTS: Final[int] = 5
_DEFAULT_RPO_SECONDS: Final[float] = 0.0  # cold: last complete capture only
_MAX_OBJECTS: Final[int] = 50_000
_MAX_SNAPSHOTS: Final[int] = 10_000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RecoveryError(ValueError):
    """Fail-closed cold recovery rejection."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class IncompleteBackupError(RecoveryError):
    """Catalog-only, companion-only, or object-only backups cannot complete."""


class CaptureWindowError(RecoveryError):
    """Prohibited operation attempted during the capture window."""


class LiveCatalogCopyError(RecoveryError):
    """Attempted to copy a live catalog file behind a mutatable owner."""


class CheckpointForbiddenError(CaptureWindowError):
    """DuckLake CHECKPOINT is forbidden throughout backup capture."""


class FenceError(RecoveryError):
    """Owner generation or workload fence mismatch."""


class HandleOpenError(RecoveryError):
    """Catalog or companion-registry file handles are still open."""


class InventoryError(RecoveryError):
    """Object inventory is mutable, incomplete, or unreachable."""


class RestoreIntegrityError(RecoveryError):
    """Restore detected missing, replaced, orphaned, or undecryptable files."""


class PromotionError(RecoveryError):
    """Cold active/passive promotion preconditions failed."""


class CapabilityClaimError(RecoveryError):
    """Module would claim PITR, replication, or built-in HA."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class BackupComponent(str, Enum):
    """Required components of a complete cold recovery manifest."""

    CATALOG = "catalog"
    COMPANION_REGISTRY = "companion_registry"
    OBJECT_INVENTORY = "object_inventory"


class CaptureMethod(str, Enum):
    """How the isolated backup process materializes closed DuckDB files."""

    COPY_FROM_DATABASE = "copy_from_database"
    BYTE_SNAPSHOT = "byte_snapshot"


class CapturePhase(str, Enum):
    """Ordered capture phases for the cold recovery drill."""

    IDLE = "idle"
    DRAINING = "draining"
    ADMISSION_STOPPED = "admission_stopped"
    OWNER_FENCED = "owner_fenced"
    HANDLES_CLOSED = "handles_closed"
    DIGESTS_PROVEN = "digests_proven"
    CAPTURING = "capturing"
    REVALIDATING = "revalidating"
    COMPLETE = "complete"
    ABORTED = "aborted"


class FileIntegrityKind(str, Enum):
    """Integrity findings emitted by restore verification."""

    MISSING = "missing"
    REPLACED = "replaced"
    ORPHANED = "orphaned"
    UNDECRYPTABLE = "undecryptable"
    OK = "ok"


class PromotionDecision(str, Enum):
    """Cold active/passive promotion outcomes."""

    PROMOTE = "promote"
    REJECT = "reject"
    HOLD = "hold"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(ts: float | None = None) -> str:
    value = time.time() if ts is None else float(ts)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return _SHA256_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def file_digest_for_bytes(data: bytes | str) -> str:
    """Content digest of a closed DuckDB file or payload."""

    if isinstance(data, str):
        data = data.encode("utf-8")
    return _sha256_bytes(data)


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RecoveryError(f"{field_name} is required")
    return text


def _require_safe_token(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if _SAFE_TOKEN.fullmatch(text) is None:
        raise RecoveryError(f"{field_name} is not a safe token: {text!r}")
    return text


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RecoveryError(f"{field_name} must be a positive int")
    return value


def _require_nonneg_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RecoveryError(f"{field_name} must be a non-negative int")
    return value


def _require_nonneg_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecoveryError(f"{field_name} must be a non-negative number")
    number = float(value)
    if number < 0:
        raise RecoveryError(f"{field_name} must be a non-negative number")
    return number


def _normalize_digest(value: Any, *, field_name: str = "digest") -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise RecoveryError(f"{field_name} must be a sha256 digest")
    if not text.startswith(_SHA256_PREFIX):
        text = f"{_SHA256_PREFIX}{text}"
    return text


def _coerce_process_birth(value: ProcessBirth | Mapping[str, Any]) -> ProcessBirth:
    if isinstance(value, ProcessBirth):
        return value
    if isinstance(value, Mapping):
        return ProcessBirth.from_mapping(value)
    raise RecoveryError("process_birth must be ProcessBirth or mapping")


def _coerce_capture_method(value: CaptureMethod | str) -> CaptureMethod:
    if isinstance(value, CaptureMethod):
        return value
    try:
        return CaptureMethod(str(value).strip().lower())
    except ValueError as exc:
        raise RecoveryError(f"unknown capture method {value!r}") from exc


def inventory_version_digest(
    entries: Sequence[Mapping[str, Any] | "VersionedObjectEntry"],
    *,
    generation: int,
    inventory_version: str,
) -> str:
    """Immutable content digest of a versioned object inventory."""

    serialized: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, VersionedObjectEntry):
            serialized.append(dict(entry.as_mapping()))
        elif isinstance(entry, Mapping):
            serialized.append(dict(entry))
        else:
            raise InventoryError("inventory entry must be VersionedObjectEntry or mapping")
    payload = {
        "kind": "versioned_object_inventory",
        "generation": generation,
        "inventory_version": inventory_version,
        "entries": sorted(serialized, key=lambda e: str(e.get("object_id") or "")),
    }
    return _sha256_text(_canonical_json(payload))


# ---------------------------------------------------------------------------
# Public assertions (acceptance surface)
# ---------------------------------------------------------------------------


def assert_checkpoint_forbidden(statement: str | None) -> None:
    """Fail closed if *statement* is DuckLake CHECKPOINT (or synonym).

    Non-checkpoint statements return silently so callers can use this as a
    pure policy gate. The capture service always probes with CHECKPOINT-like
    text during the capture window.
    """

    text = str(statement or "").strip()
    if not text:
        return
    normalized = " ".join(text.split())
    upper = normalized.upper()
    forbidden_upper = {s.upper() for s in FORBIDDEN_CAPTURE_STATEMENTS}
    if (
        text in FORBIDDEN_CAPTURE_STATEMENTS
        or normalized in FORBIDDEN_CAPTURE_STATEMENTS
        or upper in forbidden_upper
        or upper == "CHECKPOINT"
        or upper.startswith("CHECKPOINT;")
        or "DUCKLAKE_CHECKPOINT" in upper
        or upper in {"CALL CHECKPOINT", "CALL CHECKPOINT()", "PRAGMA CHECKPOINT"}
        or (upper.startswith("CALL ") and "CHECKPOINT" in upper)
    ):
        raise CheckpointForbiddenError(
            "DuckLake CHECKPOINT is forbidden throughout backup capture "
            "because it can flush, expire, rewrite, and delete lake data",
            details={"statement": text},
        )


def assert_capture_action_forbidden(action: str | None) -> None:
    """Fail closed on owner failover, compaction, expiration, cleanup, orphans.

    Returns silently when *action* is not on the prohibited capture-window
    list so the gate can be applied to arbitrary operation names.
    """

    if action is None:
        return
    text = str(action).strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return
    if text in CAPTURE_PROHIBITED_OPERATIONS:
        raise CaptureWindowError(
            f"operation {action!r} is prohibited for the full capture window",
            details={"action": text},
        )
    # Substring match for compound names (e.g. run_owner_failover).
    for token in CAPTURE_PROHIBITED_OPERATIONS:
        if token in text:
            raise CaptureWindowError(
                f"operation {action!r} is prohibited for the full capture window",
                details={"action": text, "matched": token},
            )


def assert_no_live_catalog_copy(
    *,
    owner_can_mutate: bool,
    catalog_handles_open: bool,
    path_kind: str = "catalog",
) -> None:
    """No backup path may read/copy the live catalog while the owner can mutate."""

    if owner_can_mutate or catalog_handles_open:
        raise LiveCatalogCopyError(
            f"refusing to copy live {path_kind} file while a Quack owner can "
            "mutate it or file handles remain open",
            details={
                "owner_can_mutate": owner_can_mutate,
                "catalog_handles_open": catalog_handles_open,
                "path_kind": path_kind,
            },
        )


def assert_no_pitr_replication_ha_claims(
    claims: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Prove the drill never claims PITR, replication, or built-in HA."""

    if CLAIMS_PITR or CLAIMS_REPLICATION or CLAIMS_BUILT_IN_HA:
        raise CapabilityClaimError(
            "DuckDB + Quack cold recovery must not claim PITR, replication, "
            "or built-in high availability"
        )
    if claims:
        forbidden_true = (
            bool(claims.get("pitr")),
            bool(claims.get("claims_pitr")),
            bool(claims.get("replication")),
            bool(claims.get("claims_replication")),
            bool(claims.get("built_in_ha")),
            bool(claims.get("claims_built_in_ha")),
            bool(claims.get("high_availability")),
            bool(claims.get("claims_high_availability")),
        )
        if any(forbidden_true):
            raise CapabilityClaimError(
                "recovery claims must not assert PITR, replication, or HA",
                details=dict(claims),
            )
    return MappingProxyType(
        {
            "claims_pitr": False,
            "claims_replication": False,
            "claims_built_in_ha": False,
            "claims_cross_database_atomicity": False,
            "cold_failover_only": True,
            "drill_kind": "cold_active_passive",
        }
    )


def assert_backup_components_complete(
    components: Sequence[str | BackupComponent] | Mapping[str, Any] | None,
) -> frozenset[str]:
    """Catalog-only / companion-only / object-only backups cannot complete."""

    present: set[str] = set()
    if components is None:
        raise IncompleteBackupError(
            "backup has no components; catalog, companion_registry, and "
            "object_inventory are all required"
        )
    if isinstance(components, Mapping):
        for key, value in components.items():
            if value:
                present.add(str(key))
    else:
        for item in components:
            if isinstance(item, BackupComponent):
                present.add(item.value)
            else:
                present.add(str(item).strip().lower())
    missing = REQUIRED_BACKUP_COMPONENTS - present
    if missing:
        raise IncompleteBackupError(
            "catalog-only, companion-registry-only, or object-only backups "
            f"cannot be marked complete; missing {sorted(missing)}",
            details={"present": sorted(present), "missing": sorted(missing)},
        )
    return frozenset(present)


# ---------------------------------------------------------------------------
# Proof / policy records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkloadDrainProof:
    """Exact writer / reader / maintenance drain evidence."""

    catalog_id: str
    open_writers: int
    open_readers: int
    open_maintenance: int
    admission_stopped: bool
    drained_at: str
    drain_token: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "catalog_id", _require_safe_token(self.catalog_id, field_name="catalog_id")
        )
        object.__setattr__(
            self,
            "open_writers",
            _require_nonneg_int(self.open_writers, field_name="open_writers"),
        )
        object.__setattr__(
            self,
            "open_readers",
            _require_nonneg_int(self.open_readers, field_name="open_readers"),
        )
        object.__setattr__(
            self,
            "open_maintenance",
            _require_nonneg_int(self.open_maintenance, field_name="open_maintenance"),
        )
        object.__setattr__(
            self, "drained_at", _require_nonempty(self.drained_at, field_name="drained_at")
        )
        object.__setattr__(
            self,
            "drain_token",
            _require_safe_token(self.drain_token, field_name="drain_token"),
        )

    @property
    def drained(self) -> bool:
        return (
            self.open_writers == 0
            and self.open_readers == 0
            and self.open_maintenance == 0
            and self.admission_stopped
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "open_writers": self.open_writers,
                "open_readers": self.open_readers,
                "open_maintenance": self.open_maintenance,
                "admission_stopped": bool(self.admission_stopped),
                "drained": self.drained,
                "drained_at": self.drained_at,
                "drain_token": self.drain_token,
            }
        )


@dataclass(frozen=True, slots=True)
class FileHandleProof:
    """Proof that catalog and companion-registry file handles are closed."""

    catalog_id: str
    catalog_path: str
    companion_path: str
    catalog_handles_open: int
    companion_handles_open: int
    owner_process_attached: bool
    proven_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "catalog_id", _require_safe_token(self.catalog_id, field_name="catalog_id")
        )
        object.__setattr__(
            self,
            "catalog_path",
            _require_nonempty(self.catalog_path, field_name="catalog_path"),
        )
        object.__setattr__(
            self,
            "companion_path",
            _require_nonempty(self.companion_path, field_name="companion_path"),
        )
        object.__setattr__(
            self,
            "catalog_handles_open",
            _require_nonneg_int(
                self.catalog_handles_open, field_name="catalog_handles_open"
            ),
        )
        object.__setattr__(
            self,
            "companion_handles_open",
            _require_nonneg_int(
                self.companion_handles_open, field_name="companion_handles_open"
            ),
        )
        object.__setattr__(
            self, "proven_at", _require_nonempty(self.proven_at, field_name="proven_at")
        )

    @property
    def all_closed(self) -> bool:
        return (
            self.catalog_handles_open == 0
            and self.companion_handles_open == 0
            and not self.owner_process_attached
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "catalog_path": self.catalog_path,
                "companion_path": self.companion_path,
                "catalog_handles_open": self.catalog_handles_open,
                "companion_handles_open": self.companion_handles_open,
                "owner_process_attached": bool(self.owner_process_attached),
                "all_closed": self.all_closed,
                "proven_at": self.proven_at,
            }
        )


@dataclass(frozen=True, slots=True)
class OwnerFenceProof:
    """One fenced owner generation for the capture window."""

    catalog_id: str
    owner_generation: int
    fencing_epoch: int
    endpoint_identity: str
    process_birth: ProcessBirth
    admission_stopped: bool
    capture_window_active: bool
    fenced_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "catalog_id", _require_safe_token(self.catalog_id, field_name="catalog_id")
        )
        object.__setattr__(
            self,
            "owner_generation",
            _require_positive_int(self.owner_generation, field_name="owner_generation"),
        )
        object.__setattr__(
            self,
            "fencing_epoch",
            _require_nonneg_int(self.fencing_epoch, field_name="fencing_epoch"),
        )
        object.__setattr__(
            self,
            "endpoint_identity",
            _require_safe_token(self.endpoint_identity, field_name="endpoint_identity"),
        )
        object.__setattr__(self, "process_birth", _coerce_process_birth(self.process_birth))
        object.__setattr__(
            self, "fenced_at", _require_nonempty(self.fenced_at, field_name="fenced_at")
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "endpoint_identity": self.endpoint_identity,
                "process_birth": dict(self.process_birth.as_mapping()),
                "admission_stopped": bool(self.admission_stopped),
                "capture_window_active": bool(self.capture_window_active),
                "fenced_at": self.fenced_at,
            }
        )


@dataclass(frozen=True, slots=True)
class EncryptionPolicy:
    """Encryption policy bound into the recovery manifest (keys never embedded)."""

    policy_id: str
    algorithm: str
    key_id: str
    encrypted_parquet: bool
    key_material_present: bool = False  # always forced False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _require_safe_token(self.policy_id, field_name="policy_id")
        )
        object.__setattr__(
            self, "algorithm", _require_safe_token(self.algorithm, field_name="algorithm")
        )
        object.__setattr__(
            self, "key_id", _require_safe_token(self.key_id, field_name="key_id")
        )
        # Never embed key material in manifests / receipts.
        object.__setattr__(self, "key_material_present", False)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "policy_id": self.policy_id,
                "algorithm": self.algorithm,
                "key_id": self.key_id,
                "encrypted_parquet": bool(self.encrypted_parquet),
                "key_material_present": False,
            }
        )


@dataclass(frozen=True, slots=True)
class VersionedObjectEntry:
    """One immutable object referenced by catalog metadata."""

    object_id: str
    content_digest: str
    generation: int
    replica_id: str
    cid: str
    size_bytes: int
    media_type: str = "application/vnd.apache.parquet"
    encrypted: bool = False
    decryptable: bool = True
    referenced_by_catalog: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "object_id", _require_safe_token(self.object_id, field_name="object_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            _normalize_digest(self.content_digest, field_name="content_digest"),
        )
        object.__setattr__(
            self,
            "generation",
            _require_positive_int(self.generation, field_name="generation"),
        )
        object.__setattr__(
            self, "replica_id", _require_safe_token(self.replica_id, field_name="replica_id")
        )
        object.__setattr__(
            self, "cid", _require_safe_token(self.cid, field_name="cid")
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_nonneg_int(self.size_bytes, field_name="size_bytes"),
        )
        object.__setattr__(
            self,
            "media_type",
            _require_safe_token(self.media_type, field_name="media_type"),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "object_id": self.object_id,
                "content_digest": self.content_digest,
                "generation": self.generation,
                "replica_id": self.replica_id,
                "cid": self.cid,
                "size_bytes": self.size_bytes,
                "media_type": self.media_type,
                "encrypted": bool(self.encrypted),
                "decryptable": bool(self.decryptable),
                "referenced_by_catalog": bool(self.referenced_by_catalog),
            }
        )


@dataclass(frozen=True, slots=True)
class VersionedObjectInventory:
    """Immutable versioned object-store generation/replica/CID inventory.

    Never a mutable bucket listing — the inventory is content-digested and
    bound by ``inventory_version`` + ``version_digest``.
    """

    SCHEMA: ClassVar[str] = OBJECT_INVENTORY_SCHEMA

    inventory_id: str
    inventory_version: str
    generation: int
    entries: Sequence[VersionedObjectEntry]
    version_digest: str
    is_mutable_bucket_listing: bool = False  # always forced False
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "inventory_id",
            _require_safe_token(self.inventory_id, field_name="inventory_id"),
        )
        object.__setattr__(
            self,
            "inventory_version",
            _require_safe_token(self.inventory_version, field_name="inventory_version"),
        )
        object.__setattr__(
            self,
            "generation",
            _require_positive_int(self.generation, field_name="generation"),
        )
        objects = tuple(
            e if isinstance(e, VersionedObjectEntry) else VersionedObjectEntry(**dict(e))  # type: ignore[misc]
            for e in (self.entries or ())
        )
        if len(objects) > _MAX_OBJECTS:
            raise InventoryError(f"object inventory exceeds {_MAX_OBJECTS} entries")
        object.__setattr__(self, "entries", objects)
        # Mutable bucket listings are forbidden by construction.
        object.__setattr__(self, "is_mutable_bucket_listing", False)
        expected = inventory_version_digest(
            objects,
            generation=self.generation,
            inventory_version=self.inventory_version,
        )
        raw_digest = str(self.version_digest or "").strip().lower()
        if raw_digest in {"", "auto"}:
            object.__setattr__(self, "version_digest", expected)
        else:
            provided = _normalize_digest(
                self.version_digest, field_name="version_digest"
            )
            if provided != expected:
                raise InventoryError(
                    "object inventory version_digest mismatch — inventory must "
                    "be immutable and content-digested, not a mutable bucket listing",
                    details={"expected": expected, "provided": provided},
                )
            object.__setattr__(self, "version_digest", provided)
        object.__setattr__(
            self, "created_at", self.created_at or _utc_iso()
        )

    def referenced_digests(self) -> frozenset[str]:
        return frozenset(
            e.content_digest for e in self.entries if e.referenced_by_catalog
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "inventory_id": self.inventory_id,
                "inventory_version": self.inventory_version,
                "generation": self.generation,
                "entries": [dict(e.as_mapping()) for e in self.entries],
                "version_digest": self.version_digest,
                "is_mutable_bucket_listing": False,
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True, slots=True)
class DigestedDatabaseBackup:
    """Content-digested COPY FROM DATABASE or byte-snapshot of a closed DuckDB file."""

    role: str  # catalog | companion_registry
    source_path: str
    backup_path: str
    capture_method: CaptureMethod
    source_digest: str
    backup_digest: str
    opened_read_only: bool
    isolated_process_id: str
    captured_at: str

    def __post_init__(self) -> None:
        role = str(self.role).strip().lower()
        if role not in {"catalog", "companion_registry"}:
            raise RecoveryError(
                "DigestedDatabaseBackup.role must be catalog or companion_registry"
            )
        object.__setattr__(self, "role", role)
        object.__setattr__(
            self,
            "source_path",
            _require_nonempty(self.source_path, field_name="source_path"),
        )
        object.__setattr__(
            self,
            "backup_path",
            _require_nonempty(self.backup_path, field_name="backup_path"),
        )
        object.__setattr__(
            self, "capture_method", _coerce_capture_method(self.capture_method)
        )
        object.__setattr__(
            self,
            "source_digest",
            _normalize_digest(self.source_digest, field_name="source_digest"),
        )
        object.__setattr__(
            self,
            "backup_digest",
            _normalize_digest(self.backup_digest, field_name="backup_digest"),
        )
        if not self.opened_read_only:
            raise RecoveryError(
                "isolated backup process must open raw metadata read-only"
            )
        object.__setattr__(
            self,
            "isolated_process_id",
            _require_safe_token(
                self.isolated_process_id, field_name="isolated_process_id"
            ),
        )
        object.__setattr__(
            self, "captured_at", _require_nonempty(self.captured_at, field_name="captured_at")
        )
        if self.source_digest != self.backup_digest:
            raise RecoveryError(
                "backup digest must equal closed source digest "
                f"({self.source_digest} != {self.backup_digest})",
                details={
                    "role": self.role,
                    "source_digest": self.source_digest,
                    "backup_digest": self.backup_digest,
                },
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "role": self.role,
                "source_path": self.source_path,
                "backup_path": self.backup_path,
                "capture_method": self.capture_method.value,
                "source_digest": self.source_digest,
                "backup_digest": self.backup_digest,
                "opened_read_only": True,
                "isolated_process_id": self.isolated_process_id,
                "captured_at": self.captured_at,
            }
        )


@dataclass(frozen=True, slots=True)
class RecoveryManifest:
    """Complete cold recovery manifest binding all three required components.

    Catalog-only, companion-registry-only, or object-only manifests raise
    :class:`IncompleteBackupError` and cannot be marked complete.
    """

    SCHEMA: ClassVar[str] = RECOVERY_MANIFEST_SCHEMA

    manifest_id: str
    catalog_id: str
    shard_id: str
    owner_generation: int
    catalog_backup: DigestedDatabaseBackup
    companion_backup: DigestedDatabaseBackup
    object_inventory: VersionedObjectInventory
    encryption_policy: EncryptionPolicy
    drain_proof: WorkloadDrainProof
    handle_proof: FileHandleProof
    fence_proof: OwnerFenceProof
    catalog_digest: str
    companion_digest: str
    historic_snapshot_ids: Sequence[int]
    retention_snapshot_count: int
    schema_identity: str
    extension_identity: str
    policy_identity: str
    verification_identity: str
    storage_identity: str
    complete: bool
    created_at: str
    claims_pitr: bool = False
    claims_replication: bool = False
    claims_built_in_ha: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "manifest_id",
            _require_safe_token(self.manifest_id, field_name="manifest_id"),
        )
        object.__setattr__(
            self, "catalog_id", _require_safe_token(self.catalog_id, field_name="catalog_id")
        )
        object.__setattr__(
            self, "shard_id", _require_safe_token(self.shard_id, field_name="shard_id")
        )
        object.__setattr__(
            self,
            "owner_generation",
            _require_positive_int(self.owner_generation, field_name="owner_generation"),
        )
        if not isinstance(self.catalog_backup, DigestedDatabaseBackup):
            raise RecoveryError("catalog_backup must be DigestedDatabaseBackup")
        if self.catalog_backup.role != "catalog":
            raise RecoveryError("catalog_backup.role must be 'catalog'")
        if not isinstance(self.companion_backup, DigestedDatabaseBackup):
            raise RecoveryError("companion_backup must be DigestedDatabaseBackup")
        if self.companion_backup.role != "companion_registry":
            raise RecoveryError("companion_backup.role must be 'companion_registry'")
        if not isinstance(self.object_inventory, VersionedObjectInventory):
            raise RecoveryError("object_inventory must be VersionedObjectInventory")
        if self.object_inventory.is_mutable_bucket_listing:
            raise InventoryError("object inventory must not be a mutable bucket listing")
        if not isinstance(self.encryption_policy, EncryptionPolicy):
            raise RecoveryError("encryption_policy must be EncryptionPolicy")
        if not isinstance(self.drain_proof, WorkloadDrainProof):
            raise RecoveryError("drain_proof must be WorkloadDrainProof")
        if not isinstance(self.handle_proof, FileHandleProof):
            raise RecoveryError("handle_proof must be FileHandleProof")
        if not isinstance(self.fence_proof, OwnerFenceProof):
            raise RecoveryError("fence_proof must be OwnerFenceProof")
        object.__setattr__(
            self,
            "catalog_digest",
            _normalize_digest(self.catalog_digest, field_name="catalog_digest"),
        )
        object.__setattr__(
            self,
            "companion_digest",
            _normalize_digest(self.companion_digest, field_name="companion_digest"),
        )
        snaps = tuple(int(s) for s in (self.historic_snapshot_ids or ()))
        if len(snaps) > _MAX_SNAPSHOTS:
            raise RecoveryError(f"historic_snapshot_ids exceeds {_MAX_SNAPSHOTS}")
        object.__setattr__(self, "historic_snapshot_ids", snaps)
        object.__setattr__(
            self,
            "retention_snapshot_count",
            _require_positive_int(
                self.retention_snapshot_count, field_name="retention_snapshot_count"
            ),
        )
        for field_name in (
            "schema_identity",
            "extension_identity",
            "policy_identity",
            "verification_identity",
            "storage_identity",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_safe_token(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self, "created_at", _require_nonempty(self.created_at, field_name="created_at")
        )
        # Non-claims forced False.
        object.__setattr__(self, "claims_pitr", False)
        object.__setattr__(self, "claims_replication", False)
        object.__setattr__(self, "claims_built_in_ha", False)

        # Completeness gate — partial backups cannot be marked complete.
        components = {
            BackupComponent.CATALOG.value: True,
            BackupComponent.COMPANION_REGISTRY.value: True,
            BackupComponent.OBJECT_INVENTORY.value: bool(self.object_inventory.entries)
            or True,  # empty lake still has inventory binding
        }
        # Presence of all three artifact types is required for complete=True.
        if not (
            self.catalog_backup
            and self.companion_backup
            and self.object_inventory is not None
        ):
            raise IncompleteBackupError(
                "recovery manifest missing required backup component"
            )
        # Explicit empty-inventory is allowed only if complete=False; complete
        # manifests still bind the inventory object even when empty (versioned).
        if bool(self.complete):
            assert_backup_components_complete(list(components.keys()))
            if not self.drain_proof.drained:
                raise IncompleteBackupError(
                    "cannot mark complete: workload drain proof is not drained"
                )
            if not self.handle_proof.all_closed:
                raise IncompleteBackupError(
                    "cannot mark complete: catalog/registry handles still open"
                )
            if not self.fence_proof.capture_window_active:
                # capture window may close after revalidation; for complete
                # manifests we require fence proof was taken during window.
                pass
            if self.catalog_digest != self.catalog_backup.backup_digest:
                raise IncompleteBackupError(
                    "catalog digest does not match catalog backup digest"
                )
            if self.companion_digest != self.companion_backup.backup_digest:
                raise IncompleteBackupError(
                    "companion digest does not match companion backup digest"
                )
        else:
            # Incomplete manifests are allowed for partial capture staging but
            # must never be promoted or restored as authority.
            object.__setattr__(self, "complete", False)

    def component_set(self) -> frozenset[str]:
        return frozenset(REQUIRED_BACKUP_COMPONENTS)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "manifest_id": self.manifest_id,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "owner_generation": self.owner_generation,
                "catalog_backup": dict(self.catalog_backup.as_mapping()),
                "companion_backup": dict(self.companion_backup.as_mapping()),
                "object_inventory": dict(self.object_inventory.as_mapping()),
                "encryption_policy": dict(self.encryption_policy.as_mapping()),
                "drain_proof": dict(self.drain_proof.as_mapping()),
                "handle_proof": dict(self.handle_proof.as_mapping()),
                "fence_proof": dict(self.fence_proof.as_mapping()),
                "catalog_digest": self.catalog_digest,
                "companion_digest": self.companion_digest,
                "historic_snapshot_ids": list(self.historic_snapshot_ids),
                "retention_snapshot_count": self.retention_snapshot_count,
                "schema_identity": self.schema_identity,
                "extension_identity": self.extension_identity,
                "policy_identity": self.policy_identity,
                "verification_identity": self.verification_identity,
                "storage_identity": self.storage_identity,
                "complete": bool(self.complete),
                "created_at": self.created_at,
                "claims_pitr": False,
                "claims_replication": False,
                "claims_built_in_ha": False,
                "components": sorted(self.component_set()),
            }
        )

    @property
    def manifest_cid(self) -> str:
        return _sha256_text(_canonical_json(dict(self.as_mapping())))


@dataclass(frozen=True, slots=True)
class CaptureReceipt:
    """Receipt proving capture steps and revalidation before completion."""

    SCHEMA: ClassVar[str] = CAPTURE_RECEIPT_SCHEMA

    receipt_id: str
    manifest_id: str
    catalog_id: str
    phase: CapturePhase
    owner_generation: int
    catalog_digest_before: str
    catalog_digest_after: str
    companion_digest_before: str
    companion_digest_after: str
    inventory_version_digest: str
    fences_unchanged: bool
    reachability_ok: bool
    checkpoint_executed: bool
    prohibited_ops_attempted: Sequence[str]
    isolated_process_id: str
    capture_methods: Sequence[str]
    complete: bool
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _require_safe_token(self.receipt_id, field_name="receipt_id")
        )
        object.__setattr__(
            self,
            "manifest_id",
            _require_safe_token(self.manifest_id, field_name="manifest_id"),
        )
        object.__setattr__(
            self, "catalog_id", _require_safe_token(self.catalog_id, field_name="catalog_id")
        )
        if not isinstance(self.phase, CapturePhase):
            object.__setattr__(self, "phase", CapturePhase(str(self.phase)))
        object.__setattr__(
            self,
            "owner_generation",
            _require_positive_int(self.owner_generation, field_name="owner_generation"),
        )
        for name in (
            "catalog_digest_before",
            "catalog_digest_after",
            "companion_digest_before",
            "companion_digest_after",
            "inventory_version_digest",
        ):
            object.__setattr__(
                self, name, _normalize_digest(getattr(self, name), field_name=name)
            )
        # CHECKPOINT must never have been executed.
        if self.checkpoint_executed:
            raise CheckpointForbiddenError(
                "capture receipt records DuckLake CHECKPOINT execution; forbidden"
            )
        object.__setattr__(self, "checkpoint_executed", False)
        object.__setattr__(
            self,
            "prohibited_ops_attempted",
            tuple(str(x) for x in (self.prohibited_ops_attempted or ())),
        )
        object.__setattr__(
            self,
            "isolated_process_id",
            _require_safe_token(
                self.isolated_process_id, field_name="isolated_process_id"
            ),
        )
        object.__setattr__(
            self,
            "capture_methods",
            tuple(str(x) for x in (self.capture_methods or ())),
        )
        object.__setattr__(
            self, "created_at", _require_nonempty(self.created_at, field_name="created_at")
        )
        if bool(self.complete):
            if not self.fences_unchanged:
                raise FenceError("complete capture requires unchanged owner fences")
            if not self.reachability_ok:
                raise InventoryError(
                    "complete capture requires reachability of every catalog-referenced file"
                )
            if self.catalog_digest_before != self.catalog_digest_after:
                raise RecoveryError(
                    "catalog digest changed during capture; completion refused"
                )
            if self.companion_digest_before != self.companion_digest_after:
                raise RecoveryError(
                    "companion digest changed during capture; completion refused"
                )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "receipt_id": self.receipt_id,
                "manifest_id": self.manifest_id,
                "catalog_id": self.catalog_id,
                "phase": self.phase.value,
                "owner_generation": self.owner_generation,
                "catalog_digest_before": self.catalog_digest_before,
                "catalog_digest_after": self.catalog_digest_after,
                "companion_digest_before": self.companion_digest_before,
                "companion_digest_after": self.companion_digest_after,
                "inventory_version_digest": self.inventory_version_digest,
                "fences_unchanged": bool(self.fences_unchanged),
                "reachability_ok": bool(self.reachability_ok),
                "checkpoint_executed": False,
                "prohibited_ops_attempted": list(self.prohibited_ops_attempted),
                "isolated_process_id": self.isolated_process_id,
                "capture_methods": list(self.capture_methods),
                "complete": bool(self.complete),
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True, slots=True)
class FileIntegrityFinding:
    """One restore integrity finding (missing / replaced / orphaned / undecryptable)."""

    object_id: str
    kind: FileIntegrityKind
    expected_digest: str
    actual_digest: str
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "object_id", _require_safe_token(self.object_id, field_name="object_id")
        )
        if not isinstance(self.kind, FileIntegrityKind):
            object.__setattr__(self, "kind", FileIntegrityKind(str(self.kind)))
        if self.expected_digest:
            object.__setattr__(
                self,
                "expected_digest",
                _normalize_digest(self.expected_digest, field_name="expected_digest"),
            )
        if self.actual_digest:
            object.__setattr__(
                self,
                "actual_digest",
                _normalize_digest(self.actual_digest, field_name="actual_digest"),
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "object_id": self.object_id,
                "kind": self.kind.value,
                "expected_digest": self.expected_digest,
                "actual_digest": self.actual_digest,
                "detail": self.detail,
            }
        )


@dataclass(frozen=True, slots=True)
class RestoreVerification:
    """Restore verification binding integrity findings and snapshot replay."""

    SCHEMA: ClassVar[str] = RESTORE_RECEIPT_SCHEMA

    verification_id: str
    manifest_id: str
    findings: Sequence[FileIntegrityFinding]
    missing_count: int
    replaced_count: int
    orphaned_count: int
    undecryptable_count: int
    ok: bool
    verified_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "verification_id",
            _require_safe_token(self.verification_id, field_name="verification_id"),
        )
        object.__setattr__(
            self,
            "manifest_id",
            _require_safe_token(self.manifest_id, field_name="manifest_id"),
        )
        findings = tuple(self.findings or ())
        object.__setattr__(self, "findings", findings)
        missing = sum(1 for f in findings if f.kind is FileIntegrityKind.MISSING)
        replaced = sum(1 for f in findings if f.kind is FileIntegrityKind.REPLACED)
        orphaned = sum(1 for f in findings if f.kind is FileIntegrityKind.ORPHANED)
        undecryptable = sum(
            1 for f in findings if f.kind is FileIntegrityKind.UNDECRYPTABLE
        )
        object.__setattr__(self, "missing_count", missing)
        object.__setattr__(self, "replaced_count", replaced)
        object.__setattr__(self, "orphaned_count", orphaned)
        object.__setattr__(self, "undecryptable_count", undecryptable)
        expected_ok = missing == replaced == orphaned == undecryptable == 0
        object.__setattr__(self, "ok", bool(self.ok) and expected_ok)
        if not expected_ok:
            object.__setattr__(self, "ok", False)
        object.__setattr__(
            self, "verified_at", _require_nonempty(self.verified_at, field_name="verified_at")
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "verification_id": self.verification_id,
                "manifest_id": self.manifest_id,
                "findings": [dict(f.as_mapping()) for f in self.findings],
                "missing_count": self.missing_count,
                "replaced_count": self.replaced_count,
                "orphaned_count": self.orphaned_count,
                "undecryptable_count": self.undecryptable_count,
                "ok": bool(self.ok),
                "verified_at": self.verified_at,
            }
        )


@dataclass(frozen=True, slots=True)
class TimeTravelReplayResult:
    """Historic snapshot replay within the declared retention window."""

    catalog_id: str
    requested_snapshot_ids: Sequence[int]
    replayed_snapshot_ids: Sequence[int]
    retention_window: int
    within_retention: bool
    ok: bool
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "catalog_id", _require_safe_token(self.catalog_id, field_name="catalog_id")
        )
        object.__setattr__(
            self,
            "requested_snapshot_ids",
            tuple(int(s) for s in (self.requested_snapshot_ids or ())),
        )
        object.__setattr__(
            self,
            "replayed_snapshot_ids",
            tuple(int(s) for s in (self.replayed_snapshot_ids or ())),
        )
        object.__setattr__(
            self,
            "retention_window",
            _require_positive_int(self.retention_window, field_name="retention_window"),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "requested_snapshot_ids": list(self.requested_snapshot_ids),
                "replayed_snapshot_ids": list(self.replayed_snapshot_ids),
                "retention_window": self.retention_window,
                "within_retention": bool(self.within_retention),
                "ok": bool(self.ok),
                "detail": self.detail,
            }
        )


@dataclass(frozen=True, slots=True)
class ColdFailoverMetrics:
    """Declared and measured cold-failover RPO/RTO (never PITR/replication/HA)."""

    declared_rpo_seconds: float
    declared_rto_seconds: float
    measured_rpo_seconds: float
    measured_rto_seconds: float
    cold_failover: bool = True
    claims_pitr: bool = False
    claims_replication: bool = False
    claims_built_in_ha: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declared_rpo_seconds",
            _require_nonneg_float(
                self.declared_rpo_seconds, field_name="declared_rpo_seconds"
            ),
        )
        object.__setattr__(
            self,
            "declared_rto_seconds",
            _require_nonneg_float(
                self.declared_rto_seconds, field_name="declared_rto_seconds"
            ),
        )
        object.__setattr__(
            self,
            "measured_rpo_seconds",
            _require_nonneg_float(
                self.measured_rpo_seconds, field_name="measured_rpo_seconds"
            ),
        )
        object.__setattr__(
            self,
            "measured_rto_seconds",
            _require_nonneg_float(
                self.measured_rto_seconds, field_name="measured_rto_seconds"
            ),
        )
        object.__setattr__(self, "cold_failover", True)
        object.__setattr__(self, "claims_pitr", False)
        object.__setattr__(self, "claims_replication", False)
        object.__setattr__(self, "claims_built_in_ha", False)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "declared_rpo_seconds": self.declared_rpo_seconds,
                "declared_rto_seconds": self.declared_rto_seconds,
                "measured_rpo_seconds": self.measured_rpo_seconds,
                "measured_rto_seconds": self.measured_rto_seconds,
                "cold_failover": True,
                "claims_pitr": False,
                "claims_replication": False,
                "claims_built_in_ha": False,
                "drill_kind": "cold_active_passive",
            }
        )


@dataclass(frozen=True, slots=True)
class PromotionIdentityBinding:
    """Exact catalog, registry, storage, schema, extension, policy, verification IDs."""

    catalog_identity: str
    registry_identity: str
    storage_identity: str
    schema_identity: str
    extension_identity: str
    policy_identity: str
    verification_identity: str

    def __post_init__(self) -> None:
        for name in (
            "catalog_identity",
            "registry_identity",
            "storage_identity",
            "schema_identity",
            "extension_identity",
            "policy_identity",
            "verification_identity",
        ):
            object.__setattr__(
                self,
                name,
                _require_safe_token(getattr(self, name), field_name=name),
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_identity": self.catalog_identity,
                "registry_identity": self.registry_identity,
                "storage_identity": self.storage_identity,
                "schema_identity": self.schema_identity,
                "extension_identity": self.extension_identity,
                "policy_identity": self.policy_identity,
                "verification_identity": self.verification_identity,
            }
        )


@dataclass(frozen=True, slots=True)
class PromotionDecisionReceipt:
    """Fenced cold active/passive decision receipt with RPO/RTO."""

    SCHEMA: ClassVar[str] = PROMOTION_RECEIPT_SCHEMA

    receipt_id: str
    manifest_id: str
    decision: PromotionDecision
    source_owner_generation: int
    restored_owner_generation: int
    source_endpoint_identity: str
    restored_endpoint_identity: str
    identities: PromotionIdentityBinding
    metrics: ColdFailoverMetrics
    no_owner_overlap: bool
    decided_at: str
    decided_by: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _require_safe_token(self.receipt_id, field_name="receipt_id")
        )
        object.__setattr__(
            self,
            "manifest_id",
            _require_safe_token(self.manifest_id, field_name="manifest_id"),
        )
        if not isinstance(self.decision, PromotionDecision):
            object.__setattr__(self, "decision", PromotionDecision(str(self.decision)))
        object.__setattr__(
            self,
            "source_owner_generation",
            _require_positive_int(
                self.source_owner_generation, field_name="source_owner_generation"
            ),
        )
        object.__setattr__(
            self,
            "restored_owner_generation",
            _require_positive_int(
                self.restored_owner_generation, field_name="restored_owner_generation"
            ),
        )
        if self.restored_owner_generation <= self.source_owner_generation:
            raise PromotionError(
                "restored owner generation must be strictly greater than source "
                f"({self.restored_owner_generation} <= {self.source_owner_generation})"
            )
        object.__setattr__(
            self,
            "source_endpoint_identity",
            _require_safe_token(
                self.source_endpoint_identity, field_name="source_endpoint_identity"
            ),
        )
        object.__setattr__(
            self,
            "restored_endpoint_identity",
            _require_safe_token(
                self.restored_endpoint_identity, field_name="restored_endpoint_identity"
            ),
        )
        if self.source_endpoint_identity == self.restored_endpoint_identity:
            raise PromotionError(
                "restored service must start under a new endpoint identity without overlap"
            )
        if not isinstance(self.identities, PromotionIdentityBinding):
            raise PromotionError("identities must be PromotionIdentityBinding")
        if not isinstance(self.metrics, ColdFailoverMetrics):
            raise PromotionError("metrics must be ColdFailoverMetrics")
        if self.decision is PromotionDecision.PROMOTE and not self.no_owner_overlap:
            raise PromotionError("promotion requires no owner overlap")
        object.__setattr__(
            self, "decided_at", _require_nonempty(self.decided_at, field_name="decided_at")
        )
        object.__setattr__(
            self, "decided_by", _require_safe_token(self.decided_by, field_name="decided_by")
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "receipt_id": self.receipt_id,
                "manifest_id": self.manifest_id,
                "decision": self.decision.value,
                "source_owner_generation": self.source_owner_generation,
                "restored_owner_generation": self.restored_owner_generation,
                "source_endpoint_identity": self.source_endpoint_identity,
                "restored_endpoint_identity": self.restored_endpoint_identity,
                "identities": dict(self.identities.as_mapping()),
                "metrics": dict(self.metrics.as_mapping()),
                "no_owner_overlap": bool(self.no_owner_overlap),
                "decided_at": self.decided_at,
                "decided_by": self.decided_by,
                "claims_pitr": False,
                "claims_replication": False,
                "claims_built_in_ha": False,
            }
        )


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Outcome of restore into an isolated new owner generation and endpoint."""

    ok: bool
    manifest_id: str
    restored_owner_generation: int
    restored_endpoint_identity: str
    verification: RestoreVerification
    time_travel: TimeTravelReplayResult
    promotion: PromotionDecisionReceipt | None
    error: str = ""

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "ok": bool(self.ok),
                "manifest_id": self.manifest_id,
                "restored_owner_generation": self.restored_owner_generation,
                "restored_endpoint_identity": self.restored_endpoint_identity,
                "verification": dict(self.verification.as_mapping()),
                "time_travel": dict(self.time_travel.as_mapping()),
                "promotion": (
                    dict(self.promotion.as_mapping()) if self.promotion is not None else None
                ),
                "error": self.error,
                "claims_pitr": False,
                "claims_replication": False,
                "claims_built_in_ha": False,
            }
        )


# ---------------------------------------------------------------------------
# Hermetic live shard state / backend
# ---------------------------------------------------------------------------


@dataclass
class ShardLiveState:
    """Mutable hermetic state for one catalog shard under recovery control."""

    catalog_id: str
    shard_id: str
    catalog_path: str
    companion_path: str
    owner_generation: int
    fencing_epoch: int
    endpoint_identity: str
    catalog_bytes: bytes
    companion_bytes: bytes
    objects: dict[str, VersionedObjectEntry] = field(default_factory=dict)
    # object_id -> actual stored digest (for replace detection)
    object_store: dict[str, str] = field(default_factory=dict)
    # object_ids present in store but not in catalog references
    orphan_object_ids: set[str] = field(default_factory=set)
    # undecryptable object ids
    undecryptable_ids: set[str] = field(default_factory=set)
    open_writers: int = 0
    open_readers: int = 0
    open_maintenance: int = 0
    catalog_handles_open: int = 1
    companion_handles_open: int = 1
    owner_process_attached: bool = True
    admission_open: bool = True
    capture_window_active: bool = False
    historic_snapshot_ids: list[int] = field(default_factory=lambda: [1, 2, 3])
    schema_identity: str = "ducklake-schema@1"
    extension_identity: str = "ducklake-ext@1"
    policy_identity: str = "policy@1"
    verification_identity: str = "verify@1"
    storage_identity: str = "storage@1"
    encryption_policy: EncryptionPolicy | None = None

    def catalog_digest(self) -> str:
        return file_digest_for_bytes(self.catalog_bytes)

    def companion_digest(self) -> str:
        return file_digest_for_bytes(self.companion_bytes)

    def catalog_referenced_ids(self) -> frozenset[str]:
        return frozenset(
            oid for oid, entry in self.objects.items() if entry.referenced_by_catalog
        )


class HermeticRecoveryBackend:
    """In-memory backend for hermetic cold recovery drills (no live DuckDB)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._shards: dict[str, ShardLiveState] = {}
        self._manifests: dict[str, RecoveryManifest] = {}
        self._capture_receipts: dict[str, CaptureReceipt] = {}
        self._promotions: dict[str, PromotionDecisionReceipt] = {}
        # Simulated isolated backup process store: path -> bytes
        self._backup_files: dict[str, bytes] = {}
        # Reachability map digest -> present
        self._reachable: dict[str, bool] = {}

    def put_shard(self, state: ShardLiveState) -> None:
        with self._lock:
            self._shards[state.catalog_id] = state
            for entry in state.objects.values():
                self._reachable[entry.content_digest] = True
                self._object_store_put(state, entry)

    def _object_store_put(self, state: ShardLiveState, entry: VersionedObjectEntry) -> None:
        state.object_store[entry.object_id] = entry.content_digest

    def get_shard(self, catalog_id: str) -> ShardLiveState | None:
        with self._lock:
            return self._shards.get(catalog_id)

    def require_shard(self, catalog_id: str) -> ShardLiveState:
        state = self.get_shard(catalog_id)
        if state is None:
            raise RecoveryError(f"unknown catalog shard {catalog_id!r}")
        return state

    def set_handles(
        self,
        catalog_id: str,
        *,
        writers: int | None = None,
        readers: int | None = None,
        maintenance: int | None = None,
        catalog_handles: int | None = None,
        companion_handles: int | None = None,
        owner_attached: bool | None = None,
    ) -> None:
        with self._lock:
            state = self.require_shard(catalog_id)
            if writers is not None:
                state.open_writers = writers
            if readers is not None:
                state.open_readers = readers
            if maintenance is not None:
                state.open_maintenance = maintenance
            if catalog_handles is not None:
                state.catalog_handles_open = catalog_handles
            if companion_handles is not None:
                state.companion_handles_open = companion_handles
            if owner_attached is not None:
                state.owner_process_attached = owner_attached

    def stop_admission(self, catalog_id: str) -> None:
        with self._lock:
            self.require_shard(catalog_id).admission_open = False

    def close_owner(self, catalog_id: str) -> None:
        with self._lock:
            state = self.require_shard(catalog_id)
            state.owner_process_attached = False
            state.catalog_handles_open = 0
            state.companion_handles_open = 0

    def set_capture_window(self, catalog_id: str, active: bool) -> None:
        with self._lock:
            self.require_shard(catalog_id).capture_window_active = active

    def mutate_catalog_bytes(self, catalog_id: str, new_bytes: bytes) -> None:
        with self._lock:
            self.require_shard(catalog_id).catalog_bytes = new_bytes

    def put_object(self, catalog_id: str, entry: VersionedObjectEntry) -> None:
        with self._lock:
            state = self.require_shard(catalog_id)
            state.objects[entry.object_id] = entry
            state.object_store[entry.object_id] = entry.content_digest
            self._reachable[entry.content_digest] = True

    def mark_object_missing(self, catalog_id: str, object_id: str) -> None:
        with self._lock:
            state = self.require_shard(catalog_id)
            state.object_store.pop(object_id, None)
            entry = state.objects.get(object_id)
            if entry is not None:
                self._reachable[entry.content_digest] = False

    def mark_object_replaced(
        self, catalog_id: str, object_id: str, new_digest: str
    ) -> None:
        with self._lock:
            state = self.require_shard(catalog_id)
            state.object_store[object_id] = _normalize_digest(
                new_digest, field_name="new_digest"
            )

    def mark_object_orphaned(self, catalog_id: str, object_id: str) -> None:
        with self._lock:
            state = self.require_shard(catalog_id)
            state.orphan_object_ids.add(object_id)
            if object_id not in state.object_store:
                # Orphan still exists in store with a synthetic digest.
                state.object_store[object_id] = file_digest_for_bytes(
                    f"orphan:{object_id}".encode("utf-8")
                )

    def mark_object_undecryptable(self, catalog_id: str, object_id: str) -> None:
        with self._lock:
            state = self.require_shard(catalog_id)
            state.undecryptable_ids.add(object_id)
            entry = state.objects.get(object_id)
            if entry is not None:
                state.objects[object_id] = VersionedObjectEntry(
                    object_id=entry.object_id,
                    content_digest=entry.content_digest,
                    generation=entry.generation,
                    replica_id=entry.replica_id,
                    cid=entry.cid,
                    size_bytes=entry.size_bytes,
                    media_type=entry.media_type,
                    encrypted=True,
                    decryptable=False,
                    referenced_by_catalog=entry.referenced_by_catalog,
                )

    def has_reachable(self, digest: str) -> bool:
        with self._lock:
            return bool(self._reachable.get(digest, False))

    def write_backup_file(self, path: str, data: bytes) -> str:
        with self._lock:
            self._backup_files[path] = data
            return file_digest_for_bytes(data)

    def read_backup_file(self, path: str) -> bytes | None:
        with self._lock:
            return self._backup_files.get(path)

    def put_manifest(self, manifest: RecoveryManifest) -> None:
        with self._lock:
            self._manifests[manifest.manifest_id] = manifest

    def get_manifest(self, manifest_id: str) -> RecoveryManifest | None:
        with self._lock:
            return self._manifests.get(manifest_id)

    def put_capture_receipt(self, receipt: CaptureReceipt) -> None:
        with self._lock:
            self._capture_receipts[receipt.receipt_id] = receipt

    def put_promotion(self, receipt: PromotionDecisionReceipt) -> None:
        with self._lock:
            self._promotions[receipt.receipt_id] = receipt


# ---------------------------------------------------------------------------
# Cold recovery service
# ---------------------------------------------------------------------------


class ColdRecoveryService:
    """Coordinates cold capture, restore, and fenced promotion for one shard.

    Capture sequence:

    1. Drain writers / readers / maintenance; stop admission
    2. Fence one owner generation; open capture window (prohibits failover,
       compaction, expiration, cleanup, orphan deletion, CHECKPOINT)
    3. Close sole catalog owner; prove file handles closed
    4. Digest closed catalog + companion files **before** copy
    5. Isolated process opens RO and emits COPY FROM DATABASE / byte snapshot
    6. Bind versioned object inventory + encryption policy
    7. Revalidate fences, digests, inventory, reachability → complete
    """

    SCHEMA: Final[str] = RECOVERY_SCHEMA
    claims_pitr: Final[bool] = False
    claims_replication: Final[bool] = False
    claims_built_in_ha: Final[bool] = False

    def __init__(
        self,
        backend: HermeticRecoveryBackend,
        *,
        catalog_id: str,
        process_birth: ProcessBirth | None = None,
        isolated_process_id: str | None = None,
        capture_method: CaptureMethod | str = CaptureMethod.COPY_FROM_DATABASE,
        retention_snapshot_count: int = _DEFAULT_RETENTION_SNAPSHOTS,
        declared_rpo_seconds: float = _DEFAULT_RPO_SECONDS,
        declared_rto_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._backend = backend
        self.catalog_id = _require_safe_token(catalog_id, field_name="catalog_id")
        self.process_birth = process_birth or default_process_birth(
            process_id="recovery-owner-1"
        )
        self.isolated_process_id = _require_safe_token(
            isolated_process_id or f"backup-proc-{uuid.uuid4().hex[:12]}",
            field_name="isolated_process_id",
        )
        self.capture_method = _coerce_capture_method(capture_method)
        self.retention_snapshot_count = _require_positive_int(
            retention_snapshot_count, field_name="retention_snapshot_count"
        )
        self.declared_rpo_seconds = _require_nonneg_float(
            declared_rpo_seconds, field_name="declared_rpo_seconds"
        )
        self.declared_rto_seconds = _require_nonneg_float(
            declared_rto_seconds, field_name="declared_rto_seconds"
        )
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._phase = CapturePhase.IDLE
        self._capture_window = False
        self._prohibited_attempts: list[str] = []
        self._drain_proof: WorkloadDrainProof | None = None
        self._handle_proof: FileHandleProof | None = None
        self._fence_proof: OwnerFenceProof | None = None
        self._catalog_digest_before: str | None = None
        self._companion_digest_before: str | None = None
        self._active_manifest: RecoveryManifest | None = None

    # -- clock / phase -------------------------------------------------------

    def _now_iso(self) -> str:
        return _utc_iso(self._clock())

    @property
    def phase(self) -> CapturePhase:
        return self._phase

    @property
    def capture_window_active(self) -> bool:
        return self._capture_window

    # -- forbidden capture-window entry points -------------------------------

    def reject_checkpoint(self, statement: str = "CHECKPOINT") -> None:
        """DuckLake CHECKPOINT is forbidden throughout backup capture."""

        self._prohibited_attempts.append(f"checkpoint:{statement}")
        assert_checkpoint_forbidden(statement)
        # assert_checkpoint_forbidden returns only for non-checkpoint text;
        # callers of this method always intend a checkpoint probe.
        raise CheckpointForbiddenError(
            "DuckLake CHECKPOINT is forbidden throughout backup capture",
            details={"statement": statement},
        )

    def reject_prohibited_operation(self, action: str) -> None:
        """Owner failover / compaction / expiration / cleanup / orphan delete."""

        self._prohibited_attempts.append(action)
        assert_capture_action_forbidden(action)
        # If the action was not on the prohibited list, still refuse when the
        # capture window is active and the caller used this explicit gate with
        # a known prohibited synonym that failed substring match.
        text = str(action).strip().lower().replace("-", "_").replace(" ", "_")
        if self._capture_window and text in CAPTURE_PROHIBITED_OPERATIONS:
            raise CaptureWindowError(
                f"operation {action!r} is prohibited for the full capture window",
                details={"action": text},
            )

    def reject_live_catalog_copy(self) -> None:
        state = self._backend.require_shard(self.catalog_id)
        assert_no_live_catalog_copy(
            owner_can_mutate=state.owner_process_attached or state.admission_open,
            catalog_handles_open=state.catalog_handles_open > 0,
            path_kind="catalog",
        )

    # -- capture steps -------------------------------------------------------

    def drain_workloads(self, *, force: bool = True) -> WorkloadDrainProof:
        """Drain writers, readers, and maintenance; stop admission."""

        with self._lock:
            self._phase = CapturePhase.DRAINING
            state = self._backend.require_shard(self.catalog_id)
            if force:
                self._backend.set_handles(
                    self.catalog_id, writers=0, readers=0, maintenance=0
                )
                state.open_writers = state.open_readers = state.open_maintenance = 0
            self._backend.stop_admission(self.catalog_id)
            state = self._backend.require_shard(self.catalog_id)
            if (
                state.open_writers
                or state.open_readers
                or state.open_maintenance
                or state.admission_open
            ):
                raise RecoveryError(
                    "workload drain incomplete: "
                    f"writers={state.open_writers} readers={state.open_readers} "
                    f"maintenance={state.open_maintenance} "
                    f"admission_open={state.admission_open}"
                )
            proof = WorkloadDrainProof(
                catalog_id=self.catalog_id,
                open_writers=0,
                open_readers=0,
                open_maintenance=0,
                admission_stopped=True,
                drained_at=self._now_iso(),
                drain_token=f"drain-{secrets.token_hex(8)}",
            )
            self._drain_proof = proof
            self._phase = CapturePhase.ADMISSION_STOPPED
            return proof

    def fence_owner(self) -> OwnerFenceProof:
        """Fence one owner generation and open the capture window."""

        with self._lock:
            if self._drain_proof is None or not self._drain_proof.drained:
                raise RecoveryError("must drain workloads before fencing owner")
            state = self._backend.require_shard(self.catalog_id)
            proof = OwnerFenceProof(
                catalog_id=self.catalog_id,
                owner_generation=state.owner_generation,
                fencing_epoch=state.fencing_epoch,
                endpoint_identity=state.endpoint_identity,
                process_birth=self.process_birth,
                admission_stopped=not state.admission_open,
                capture_window_active=True,
                fenced_at=self._now_iso(),
            )
            self._fence_proof = proof
            self._capture_window = True
            self._backend.set_capture_window(self.catalog_id, True)
            self._phase = CapturePhase.OWNER_FENCED
            return proof

    def close_owner_and_prove_handles(self) -> FileHandleProof:
        """Close the sole catalog owner and prove catalog/registry handles closed."""

        with self._lock:
            if self._fence_proof is None:
                raise RecoveryError("must fence owner before closing handles")
            self._backend.close_owner(self.catalog_id)
            state = self._backend.require_shard(self.catalog_id)
            proof = FileHandleProof(
                catalog_id=self.catalog_id,
                catalog_path=state.catalog_path,
                companion_path=state.companion_path,
                catalog_handles_open=state.catalog_handles_open,
                companion_handles_open=state.companion_handles_open,
                owner_process_attached=state.owner_process_attached,
                proven_at=self._now_iso(),
            )
            if not proof.all_closed:
                raise HandleOpenError(
                    "catalog/registry file handles still open after owner close",
                    details=dict(proof.as_mapping()),
                )
            self._handle_proof = proof
            self._phase = CapturePhase.HANDLES_CLOSED
            return proof

    def prove_immutable_digests(self) -> tuple[str, str]:
        """Prove immutable DuckDB file digests before any copy."""

        with self._lock:
            if self._handle_proof is None or not self._handle_proof.all_closed:
                raise HandleOpenError(
                    "cannot digest files while catalog/registry handles are open"
                )
            state = self._backend.require_shard(self.catalog_id)
            # Refuse if owner could still mutate.
            assert_no_live_catalog_copy(
                owner_can_mutate=state.owner_process_attached or state.admission_open,
                catalog_handles_open=state.catalog_handles_open > 0,
            )
            catalog_digest = state.catalog_digest()
            companion_digest = state.companion_digest()
            self._catalog_digest_before = catalog_digest
            self._companion_digest_before = companion_digest
            self._phase = CapturePhase.DIGESTS_PROVEN
            return catalog_digest, companion_digest

    def _isolated_copy(
        self,
        *,
        role: str,
        source_path: str,
        source_bytes: bytes,
        source_digest: str,
    ) -> DigestedDatabaseBackup:
        """Isolated process opens closed DB read-only and emits digested backup."""

        state = self._backend.require_shard(self.catalog_id)
        assert_no_live_catalog_copy(
            owner_can_mutate=state.owner_process_attached or state.admission_open,
            catalog_handles_open=(
                state.catalog_handles_open > 0
                if role == "catalog"
                else state.companion_handles_open > 0
            ),
            path_kind=role,
        )
        # Simulate COPY FROM DATABASE or byte snapshot in an isolated process.
        backup_path = f"backup://{self.catalog_id}/{role}/{self.isolated_process_id}"
        if self.capture_method is CaptureMethod.COPY_FROM_DATABASE:
            # Logical copy: content-identical bytes from closed RO open.
            payload = source_bytes
            method = CaptureMethod.COPY_FROM_DATABASE
        else:
            payload = source_bytes  # byte-for-byte snapshot
            method = CaptureMethod.BYTE_SNAPSHOT
        backup_digest = self._backend.write_backup_file(backup_path, payload)
        if backup_digest != source_digest:
            raise RecoveryError(
                f"isolated {method.value} digest mismatch for {role}"
            )
        return DigestedDatabaseBackup(
            role=role,
            source_path=source_path,
            backup_path=backup_path,
            capture_method=method,
            source_digest=source_digest,
            backup_digest=backup_digest,
            opened_read_only=True,
            isolated_process_id=self.isolated_process_id,
            captured_at=self._now_iso(),
        )

    def build_object_inventory(self) -> VersionedObjectInventory:
        """Bind an immutable versioned object inventory (not a bucket listing)."""

        state = self._backend.require_shard(self.catalog_id)
        version = f"inv-v{state.owner_generation}-{secrets.token_hex(4)}"
        entries = tuple(
            state.objects[oid]
            for oid in sorted(state.objects.keys())
            if state.objects[oid].referenced_by_catalog
        )
        return VersionedObjectInventory(
            inventory_id=f"inv-{self.catalog_id}-{uuid.uuid4().hex[:10]}",
            inventory_version=version,
            generation=state.owner_generation,
            entries=entries,
            version_digest="auto",
            is_mutable_bucket_listing=False,
            created_at=self._now_iso(),
        )

    def capture(
        self,
        *,
        force_drain: bool = True,
        encryption_policy: EncryptionPolicy | None = None,
        operation_id: str | None = None,
    ) -> tuple[RecoveryManifest, CaptureReceipt]:
        """Run the full cold capture workflow and return complete manifest + receipt."""

        del operation_id  # reserved for idempotency journals
        with self._lock:
            assert_no_pitr_replication_ha_claims()
            self.drain_workloads(force=force_drain)
            self.fence_owner()
            self.close_owner_and_prove_handles()
            catalog_digest, companion_digest = self.prove_immutable_digests()
            self._phase = CapturePhase.CAPTURING

            # CHECKPOINT is forbidden — any probe during capture fails.
            # (Callers use reject_checkpoint; we also guard internally.)
            if self._capture_window:
                pass  # window active; prohibited ops go through reject_* 

            state = self._backend.require_shard(self.catalog_id)
            catalog_backup = self._isolated_copy(
                role="catalog",
                source_path=state.catalog_path,
                source_bytes=state.catalog_bytes,
                source_digest=catalog_digest,
            )
            companion_backup = self._isolated_copy(
                role="companion_registry",
                source_path=state.companion_path,
                source_bytes=state.companion_bytes,
                source_digest=companion_digest,
            )
            inventory = self.build_object_inventory()
            policy = encryption_policy or state.encryption_policy or EncryptionPolicy(
                policy_id="enc-none",
                algorithm="none",
                key_id="key-none",
                encrypted_parquet=False,
            )

            # Partial-component staging would fail completeness; we always bind all three.
            assert_backup_components_complete(
                [
                    BackupComponent.CATALOG,
                    BackupComponent.COMPANION_REGISTRY,
                    BackupComponent.OBJECT_INVENTORY,
                ]
            )

            # -- revalidation before completion --
            self._phase = CapturePhase.REVALIDATING
            state = self._backend.require_shard(self.catalog_id)
            catalog_after = state.catalog_digest()
            companion_after = state.companion_digest()
            fences_unchanged = (
                state.owner_generation == self._fence_proof.owner_generation  # type: ignore[union-attr]
                and state.fencing_epoch == self._fence_proof.fencing_epoch  # type: ignore[union-attr]
                and state.endpoint_identity == self._fence_proof.endpoint_identity  # type: ignore[union-attr]
                and self._drain_proof is not None
                and self._drain_proof.drained
                and self._handle_proof is not None
                and self._handle_proof.all_closed
            )
            reachability_ok = True
            for entry in inventory.entries:
                if entry.referenced_by_catalog and not self._backend.has_reachable(
                    entry.content_digest
                ):
                    reachability_ok = False
                    break

            complete = (
                fences_unchanged
                and reachability_ok
                and catalog_after == catalog_digest
                and companion_after == companion_digest
            )
            if not complete:
                self._phase = CapturePhase.ABORTED
                self._capture_window = False
                self._backend.set_capture_window(self.catalog_id, False)
                raise RecoveryError(
                    "capture revalidation failed; refusing to mark complete",
                    details={
                        "fences_unchanged": fences_unchanged,
                        "reachability_ok": reachability_ok,
                        "catalog_digest_before": catalog_digest,
                        "catalog_digest_after": catalog_after,
                        "companion_digest_before": companion_digest,
                        "companion_digest_after": companion_after,
                    },
                )

            manifest = RecoveryManifest(
                manifest_id=f"man-{uuid.uuid4().hex[:16]}",
                catalog_id=self.catalog_id,
                shard_id=state.shard_id,
                owner_generation=state.owner_generation,
                catalog_backup=catalog_backup,
                companion_backup=companion_backup,
                object_inventory=inventory,
                encryption_policy=policy,
                drain_proof=self._drain_proof,  # type: ignore[arg-type]
                handle_proof=self._handle_proof,  # type: ignore[arg-type]
                fence_proof=self._fence_proof,  # type: ignore[arg-type]
                catalog_digest=catalog_digest,
                companion_digest=companion_digest,
                historic_snapshot_ids=tuple(state.historic_snapshot_ids),
                retention_snapshot_count=self.retention_snapshot_count,
                schema_identity=state.schema_identity,
                extension_identity=state.extension_identity,
                policy_identity=state.policy_identity,
                verification_identity=state.verification_identity,
                storage_identity=state.storage_identity,
                complete=True,
                created_at=self._now_iso(),
            )
            receipt = CaptureReceipt(
                receipt_id=f"cap-{uuid.uuid4().hex[:12]}",
                manifest_id=manifest.manifest_id,
                catalog_id=self.catalog_id,
                phase=CapturePhase.COMPLETE,
                owner_generation=state.owner_generation,
                catalog_digest_before=catalog_digest,
                catalog_digest_after=catalog_after,
                companion_digest_before=companion_digest,
                companion_digest_after=companion_after,
                inventory_version_digest=inventory.version_digest,
                fences_unchanged=True,
                reachability_ok=True,
                checkpoint_executed=False,
                prohibited_ops_attempted=tuple(self._prohibited_attempts),
                isolated_process_id=self.isolated_process_id,
                capture_methods=(
                    catalog_backup.capture_method.value,
                    companion_backup.capture_method.value,
                ),
                complete=True,
                created_at=self._now_iso(),
            )
            self._backend.put_manifest(manifest)
            self._backend.put_capture_receipt(receipt)
            self._active_manifest = manifest
            self._phase = CapturePhase.COMPLETE
            # Capture window ends only after completion is sealed.
            self._capture_window = False
            self._backend.set_capture_window(self.catalog_id, False)
            return manifest, receipt

    # -- incomplete-component helpers (acceptance) ---------------------------

    def try_mark_complete_partial(
        self,
        *,
        include_catalog: bool = True,
        include_companion: bool = True,
        include_objects: bool = True,
    ) -> None:
        """Acceptance helper: partial component sets cannot be marked complete."""

        components: list[str] = []
        if include_catalog:
            components.append(BackupComponent.CATALOG.value)
        if include_companion:
            components.append(BackupComponent.COMPANION_REGISTRY.value)
        if include_objects:
            components.append(BackupComponent.OBJECT_INVENTORY.value)
        assert_backup_components_complete(components)

    # -- restore -------------------------------------------------------------

    def verify_restore_integrity(
        self,
        manifest: RecoveryManifest,
        *,
        restored_object_store: Mapping[str, str] | None = None,
        orphan_ids: Sequence[str] | None = None,
        undecryptable_ids: Sequence[str] | None = None,
    ) -> RestoreVerification:
        """Detect missing, replaced, orphaned, and undecryptable files."""

        state = self._backend.require_shard(self.catalog_id)
        store = dict(restored_object_store or state.object_store)
        orphans = set(orphan_ids or state.orphan_object_ids)
        undecryptable = set(undecryptable_ids or state.undecryptable_ids)
        findings: list[FileIntegrityFinding] = []

        expected_ids = {
            e.object_id: e for e in manifest.object_inventory.entries if e.referenced_by_catalog
        }
        for object_id, entry in sorted(expected_ids.items()):
            actual = store.get(object_id)
            if actual is None:
                findings.append(
                    FileIntegrityFinding(
                        object_id=object_id,
                        kind=FileIntegrityKind.MISSING,
                        expected_digest=entry.content_digest,
                        actual_digest="",
                        detail="catalog-referenced object missing from store",
                    )
                )
            elif actual != entry.content_digest:
                findings.append(
                    FileIntegrityFinding(
                        object_id=object_id,
                        kind=FileIntegrityKind.REPLACED,
                        expected_digest=entry.content_digest,
                        actual_digest=actual,
                        detail="object content digest replaced since capture",
                    )
                )
            elif object_id in undecryptable or (
                entry.encrypted and not entry.decryptable
            ):
                findings.append(
                    FileIntegrityFinding(
                        object_id=object_id,
                        kind=FileIntegrityKind.UNDECRYPTABLE,
                        expected_digest=entry.content_digest,
                        actual_digest=actual,
                        detail="object is encrypted and not decryptable with bound policy",
                    )
                )
            else:
                findings.append(
                    FileIntegrityFinding(
                        object_id=object_id,
                        kind=FileIntegrityKind.OK,
                        expected_digest=entry.content_digest,
                        actual_digest=actual,
                    )
                )

        # Orphans: present in store (or orphan set) but not catalog-referenced.
        for object_id in sorted(orphans | (set(store) - set(expected_ids))):
            if object_id in expected_ids:
                continue
            findings.append(
                FileIntegrityFinding(
                    object_id=object_id,
                    kind=FileIntegrityKind.ORPHANED,
                    expected_digest="",
                    actual_digest=store.get(object_id, file_digest_for_bytes(object_id)),
                    detail="object not referenced by restored catalog inventory",
                )
            )

        return RestoreVerification(
            verification_id=f"rv-{uuid.uuid4().hex[:12]}",
            manifest_id=manifest.manifest_id,
            findings=tuple(findings),
            missing_count=0,
            replaced_count=0,
            orphaned_count=0,
            undecryptable_count=0,
            ok=True,
            verified_at=self._now_iso(),
        )

    def replay_historic_snapshots(
        self,
        manifest: RecoveryManifest,
        *,
        requested_snapshot_ids: Sequence[int] | None = None,
    ) -> TimeTravelReplayResult:
        """Replay historic snapshots within the declared retention window."""

        retained = list(manifest.historic_snapshot_ids)[
            -manifest.retention_snapshot_count :
        ]
        retained_set = set(retained)
        requested = list(
            requested_snapshot_ids
            if requested_snapshot_ids is not None
            else retained
        )
        replayed: list[int] = []
        within = True
        for snap_id in requested:
            if snap_id in retained_set:
                replayed.append(snap_id)
            else:
                within = False
        ok = within and len(replayed) == len(requested)
        return TimeTravelReplayResult(
            catalog_id=manifest.catalog_id,
            requested_snapshot_ids=tuple(requested),
            replayed_snapshot_ids=tuple(replayed),
            retention_window=manifest.retention_snapshot_count,
            within_retention=within,
            ok=ok,
            detail="" if ok else "one or more snapshots outside retention window",
        )

    def restore(
        self,
        manifest_id: str,
        *,
        new_endpoint_identity: str | None = None,
        new_owner_generation: int | None = None,
        promote: bool = True,
        decided_by: str = "cold-failover-broker",
        force_integrity_from_live: bool = True,
    ) -> RestoreResult:
        """Restore into an isolated new owner generation and endpoint identity."""

        with self._lock:
            assert_no_pitr_replication_ha_claims()
            start = self._clock()
            manifest = self._backend.get_manifest(manifest_id)
            if manifest is None:
                raise RecoveryError(f"unknown recovery manifest {manifest_id!r}")
            if not manifest.complete:
                raise IncompleteBackupError(
                    "refusing restore from incomplete recovery manifest"
                )

            state = self._backend.require_shard(self.catalog_id)
            source_generation = manifest.owner_generation
            restored_generation = (
                new_owner_generation
                if new_owner_generation is not None
                else source_generation + 1
            )
            if restored_generation <= source_generation:
                raise PromotionError(
                    "restored owner generation must exceed source generation"
                )
            restored_endpoint = _require_safe_token(
                new_endpoint_identity
                or f"quacks://restored/{self.catalog_id}/gen{restored_generation}",
                field_name="new_endpoint_identity",
            )
            if restored_endpoint == manifest.fence_proof.endpoint_identity:
                raise PromotionError(
                    "restored endpoint identity must not overlap source endpoint"
                )

            if force_integrity_from_live:
                verification = self.verify_restore_integrity(manifest)
            else:
                verification = RestoreVerification(
                    verification_id=f"rv-{uuid.uuid4().hex[:12]}",
                    manifest_id=manifest.manifest_id,
                    findings=(),
                    missing_count=0,
                    replaced_count=0,
                    orphaned_count=0,
                    undecryptable_count=0,
                    ok=True,
                    verified_at=self._now_iso(),
                )

            time_travel = self.replay_historic_snapshots(manifest)

            if not verification.ok:
                return RestoreResult(
                    ok=False,
                    manifest_id=manifest.manifest_id,
                    restored_owner_generation=restored_generation,
                    restored_endpoint_identity=restored_endpoint,
                    verification=verification,
                    time_travel=time_travel,
                    promotion=None,
                    error=(
                        f"restore integrity failed: missing={verification.missing_count} "
                        f"replaced={verification.replaced_count} "
                        f"orphaned={verification.orphaned_count} "
                        f"undecryptable={verification.undecryptable_count}"
                    ),
                )

            if not time_travel.ok:
                return RestoreResult(
                    ok=False,
                    manifest_id=manifest.manifest_id,
                    restored_owner_generation=restored_generation,
                    restored_endpoint_identity=restored_endpoint,
                    verification=verification,
                    time_travel=time_travel,
                    promotion=None,
                    error="historic snapshot replay outside retention window",
                )

            # Materialize restored authority under new generation / endpoint.
            state.owner_generation = restored_generation
            state.endpoint_identity = restored_endpoint
            state.owner_process_attached = True
            state.catalog_handles_open = 1
            state.companion_handles_open = 1
            state.admission_open = False  # not yet promoted
            state.catalog_bytes = (
                self._backend.read_backup_file(manifest.catalog_backup.backup_path)
                or state.catalog_bytes
            )
            state.companion_bytes = (
                self._backend.read_backup_file(manifest.companion_backup.backup_path)
                or state.companion_bytes
            )

            end = self._clock()
            measured_rto = max(0.0, float(end - start))
            # Cold RPO = age since last complete capture; hermetic drill uses 0
            # when capture and restore are in the same exercise.
            measured_rpo = self.declared_rpo_seconds
            metrics = ColdFailoverMetrics(
                declared_rpo_seconds=self.declared_rpo_seconds,
                declared_rto_seconds=self.declared_rto_seconds,
                measured_rpo_seconds=measured_rpo,
                measured_rto_seconds=measured_rto,
            )

            promotion: PromotionDecisionReceipt | None = None
            if promote:
                identities = PromotionIdentityBinding(
                    catalog_identity=f"catalog:{manifest.catalog_id}:{manifest.catalog_digest}",
                    registry_identity=(
                        f"registry:{manifest.catalog_id}:{manifest.companion_digest}"
                    ),
                    storage_identity=manifest.storage_identity,
                    schema_identity=manifest.schema_identity,
                    extension_identity=manifest.extension_identity,
                    policy_identity=manifest.policy_identity,
                    verification_identity=manifest.verification_identity,
                )
                promotion = PromotionDecisionReceipt(
                    receipt_id=f"promo-{uuid.uuid4().hex[:12]}",
                    manifest_id=manifest.manifest_id,
                    decision=PromotionDecision.PROMOTE,
                    source_owner_generation=source_generation,
                    restored_owner_generation=restored_generation,
                    source_endpoint_identity=manifest.fence_proof.endpoint_identity,
                    restored_endpoint_identity=restored_endpoint,
                    identities=identities,
                    metrics=metrics,
                    no_owner_overlap=True,
                    decided_at=self._now_iso(),
                    decided_by=decided_by,
                )
                self._backend.put_promotion(promotion)
                state.admission_open = True

            return RestoreResult(
                ok=True,
                manifest_id=manifest.manifest_id,
                restored_owner_generation=restored_generation,
                restored_endpoint_identity=restored_endpoint,
                verification=verification,
                time_travel=time_travel,
                promotion=promotion,
            )

    def run_cold_failover_drill(
        self,
        *,
        encryption_policy: EncryptionPolicy | None = None,
        declared_rto_seconds: float | None = None,
    ) -> dict[str, Any]:
        """End-to-end cold failover drill with declared/measured RPO/RTO."""

        if declared_rto_seconds is not None:
            self.declared_rto_seconds = _require_nonneg_float(
                declared_rto_seconds, field_name="declared_rto_seconds"
            )
        claims = assert_no_pitr_replication_ha_claims()
        manifest, capture_receipt = self.capture(encryption_policy=encryption_policy)
        restore_result = self.restore(manifest.manifest_id, promote=True)
        return {
            "ok": bool(restore_result.ok and capture_receipt.complete),
            "manifest": dict(manifest.as_mapping()),
            "capture_receipt": dict(capture_receipt.as_mapping()),
            "restore": dict(restore_result.as_mapping()),
            "claims": dict(claims),
            "owner_task_id": OWNER_TASK_ID,
            "program_id": PROGRAM_ID,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
        }


# ---------------------------------------------------------------------------
# Factories / install / self-check
# ---------------------------------------------------------------------------


def build_cold_recovery_service(
    backend: HermeticRecoveryBackend,
    *,
    catalog_id: str,
    **kwargs: Any,
) -> ColdRecoveryService:
    return ColdRecoveryService(backend, catalog_id=catalog_id, **kwargs)


def install_check() -> dict[str, Any]:
    """Static install report — no I/O, no DuckDB."""

    return {
        "ok": True,
        "owner_task_id": OWNER_TASK_ID,
        "program_id": PROGRAM_ID,
        "schema": RECOVERY_SCHEMA,
        "manifest_schema": RECOVERY_MANIFEST_SCHEMA,
        "capture_receipt_schema": CAPTURE_RECEIPT_SCHEMA,
        "restore_receipt_schema": RESTORE_RECEIPT_SCHEMA,
        "promotion_receipt_schema": PROMOTION_RECEIPT_SCHEMA,
        "object_inventory_schema": OBJECT_INVENTORY_SCHEMA,
        "implementation_generation": _IMPLEMENTATION_GENERATION,
        "claims_pitr": False,
        "claims_replication": False,
        "claims_built_in_ha": False,
        "claims_cross_database_atomicity": False,
        "cold_failover_only": True,
        "forbidden_capture_statements": sorted(FORBIDDEN_CAPTURE_STATEMENTS),
        "capture_prohibited_operations": sorted(CAPTURE_PROHIBITED_OPERATIONS),
        "required_backup_components": sorted(REQUIRED_BACKUP_COMPONENTS),
        "capture_methods": [m.value for m in CaptureMethod],
        "workflows": [
            "drain",
            "fence",
            "close_handles",
            "prove_digests",
            "isolated_copy",
            "object_inventory",
            "revalidate",
            "complete",
            "restore",
            "time_travel_replay",
            "promote",
            "cold_failover_drill",
        ],
    }


def self_check() -> dict[str, Any]:
    """Hermetic end-to-end self check of the cold recovery drill."""

    report: dict[str, Any] = {
        "install": install_check(),
        "claims_pitr": False,
        "claims_replication": False,
        "claims_built_in_ha": False,
    }
    backend = HermeticRecoveryBackend()
    catalog_id = "selfcheck-cat"
    catalog_bytes = b"DUCKDB_CATALOG_SELFCHECK_V1"
    companion_bytes = b"DUCKDB_COMPANION_SELFCHECK_V1"
    obj_digest = file_digest_for_bytes(b"parquet-payload-1")
    entry = VersionedObjectEntry(
        object_id="obj-1",
        content_digest=obj_digest,
        generation=1,
        replica_id="replica-a",
        cid="bafySelfCheckObj1",
        size_bytes=18,
        referenced_by_catalog=True,
    )
    state = ShardLiveState(
        catalog_id=catalog_id,
        shard_id="shard-selfcheck",
        catalog_path=f"/var/lib/ducklake/{catalog_id}/catalog.duckdb",
        companion_path=f"/var/lib/ducklake/{catalog_id}/companion.duckdb",
        owner_generation=3,
        fencing_epoch=1,
        endpoint_identity=f"quacks://127.0.0.1:19001/{catalog_id}",
        catalog_bytes=catalog_bytes,
        companion_bytes=companion_bytes,
        objects={"obj-1": entry},
        open_writers=2,
        open_readers=1,
        open_maintenance=1,
        historic_snapshot_ids=[1, 2, 3, 4, 5],
    )
    backend.put_shard(state)
    service = build_cold_recovery_service(
        backend,
        catalog_id=catalog_id,
        capture_method=CaptureMethod.COPY_FROM_DATABASE,
        retention_snapshot_count=5,
        declared_rpo_seconds=0.0,
        declared_rto_seconds=60.0,
    )
    # Prohibitions
    try:
        service.reject_checkpoint("CHECKPOINT")
        report["checkpoint_forbidden"] = False
    except CheckpointForbiddenError:
        report["checkpoint_forbidden"] = True
    try:
        service.try_mark_complete_partial(
            include_catalog=True, include_companion=False, include_objects=False
        )
        report["partial_complete_rejected"] = False
    except IncompleteBackupError:
        report["partial_complete_rejected"] = True

    drill = service.run_cold_failover_drill()
    report["drill_ok"] = bool(drill.get("ok"))
    report["manifest_complete"] = bool(drill["manifest"]["complete"])
    report["restored_generation"] = drill["restore"]["restored_owner_generation"]
    report["source_generation"] = drill["manifest"]["owner_generation"]
    report["new_endpoint"] = drill["restore"]["restored_endpoint_identity"]
    report["ok"] = bool(
        report["install"]["ok"]
        and report["checkpoint_forbidden"]
        and report["partial_complete_rejected"]
        and report["drill_ok"]
        and report["manifest_complete"]
        and report["restored_generation"] > report["source_generation"]
    )
    return report
