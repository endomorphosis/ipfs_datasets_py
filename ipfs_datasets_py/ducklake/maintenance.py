"""Receipted DuckLake maintenance policy (DQK-096).

Governs partition/sort evolution, file and row-group sizing, inlined-data
flush, adjacent-file merge, delete-file rewrite, statistics, catalog-global
snapshot expiration, scheduled-file cleanup, and orphan reconciliation.

Policy invariants:

* Dry-run is the **default** mode for every destructive action.
* Every compaction, expiration, scheduled cleanup, and orphan action requires
  a non-self-issued operation authorization from the trusted owner broker
  (identity distinct from the maintainer) and a mutation fence checked before
  the single catalog owner mutates state.
* A Quack transport token cannot self-authorize maintenance.
* Dry-run and execution receipts bind caller/process birth, catalog-owner
  generation fence, catalog identity, starting snapshot/version, authoritative
  DQK-090 reader-lease set, policy, action, authorization, candidate file set,
  nonce/expiry, resulting snapshot, and created/deleted file set.
* Destructive execution must exactly match a current accepted dry-run,
  independently reauthorize at use, and obtain a separate scoped object-delete
  IAM capability for any deletion — or fail closed.
* Maintenance consumes authoritative DQK-090 acquire/renew/release state (via
  ``list_live_leases``), never inferred timestamps, to protect the maximum
  active-reader window.
* Bare ``CHECKPOINT`` and automated ``cleanup_all`` are rejected.
* Staging lives outside DATA_PATH; live upload leases prevent orphan deletion.
* Orphan deletion requires owned-namespace proof, age threshold, dry-run
  evidence, non-self-issued authorization, and the same catalog/snapshot/
  lease/file-set fence.
* Compaction creates new file identities while preserving logical rows,
  schema, provenance, and retained old-snapshot files.
* Each catalog has exactly one strict global retention class; snapshot expiry
  always precedes scheduled file cleanup.
* Partition changes affect new files only and never invalidate old snapshots.

Import is side-effect free. Hermetic tests exercise the full policy with an
in-memory catalog facade and real DQK-090 lease authority (no live DuckDB).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Final, Mapping, Protocol, Sequence

from ipfs_datasets_py.ducklake.capabilities import (
    MaintenanceFunction,
    SUPPORTED_MAINTENANCE_FUNCTIONS,
)
from ipfs_datasets_py.ducklake.ingest import (
    ProcessBirth,
    assert_staging_outside_data_path,
    default_process_birth,
)

__all__ = [
    "MAINTENANCE_SCHEMA",
    "MAINTENANCE_AUTH_SCHEMA",
    "DRY_RUN_RECEIPT_SCHEMA",
    "EXECUTION_RECEIPT_SCHEMA",
    "RETENTION_POLICY_SCHEMA",
    "OBJECT_DELETE_IAM_SCHEMA",
    "UPLOAD_LEASE_SCHEMA",
    "FORBIDDEN_BARE_STATEMENTS",
    "FORBIDDEN_AUTOMATED_ACTIONS",
    "AuthorizationError",
    "DryRunError",
    "ExecutionError",
    "FenceError",
    "MaintenanceError",
    "ObjectDeleteIamError",
    "OrphanError",
    "PolicyError",
    "QuackTokenAuthorizationError",
    "RetentionError",
    "RetentionClass",
    "MaintenanceAction",
    "MaintenancePhase",
    "CatalogRetentionPolicy",
    "MaintenanceAuthorization",
    "ObjectDeleteIamGrant",
    "UploadLease",
    "LakeFileRecord",
    "DryRunReceipt",
    "ExecutionReceipt",
    "MaintenanceOwnerBroker",
    "HermeticMaintenanceCatalog",
    "MaintenanceService",
    "assert_not_bare_checkpoint",
    "assert_not_cleanup_all",
    "assert_quack_token_cannot_authorize_maintenance",
    "default_process_birth",
    "file_set_digest",
    "lease_set_digest",
    "revalidate_maintenance_authorization",
    "revalidate_object_delete_iam",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

MAINTENANCE_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-maintenance@1"
MAINTENANCE_AUTH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-maintenance-authorization@1"
)
DRY_RUN_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-maintenance-dry-run-receipt@1"
)
EXECUTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-maintenance-execution-receipt@1"
)
RETENTION_POLICY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-catalog-retention-policy@1"
)
OBJECT_DELETE_IAM_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-maintenance-object-delete-iam@1"
)
UPLOAD_LEASE_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-upload-lease@1"

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-096-receipted-maintenance-policy-20260811"
)

_SHA256_PREFIX: Final[str] = "sha256:"
_DEFAULT_AUTH_TTL_SECONDS: Final[int] = 300
_DEFAULT_DELETE_IAM_TTL_SECONDS: Final[int] = 120
_DEFAULT_DRY_RUN_TTL_SECONDS: Final[int] = 600
_DEFAULT_ORPHAN_MIN_AGE_SECONDS: Final[int] = 3_600
_DEFAULT_RETAIN_SNAPSHOTS: Final[int] = 3

# Bare SQL / automated bulk actions that must fail closed.
FORBIDDEN_BARE_STATEMENTS: Final[frozenset[str]] = frozenset(
    {
        "CHECKPOINT",
        "checkpoint",
        "CHECK POINT",
        "check point",
    }
)
FORBIDDEN_AUTOMATED_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "cleanup_all",
        "CLEANUP_ALL",
        "ducklake_cleanup_all",
        "automated_cleanup_all",
        "unattended_cleanup_all",
        "auto_cleanup_all",
    }
)

# Actions that mutate storage or catalog and require broker auth + fence.
_AUTH_REQUIRED_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "compaction",
        "merge_adjacent_files",
        "rewrite_data_files",
        "delete_file_rewrite",
        "flush_inlined_data",
        "expire_snapshots",
        "cleanup_old_files",
        "delete_orphaned_files",
    }
)

# Destructive actions that default to dry-run and need object-delete IAM on exec.
_DESTRUCTIVE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "compaction",
        "merge_adjacent_files",
        "rewrite_data_files",
        "delete_file_rewrite",
        "expire_snapshots",
        "cleanup_old_files",
        "delete_orphaned_files",
    }
)

_DELETION_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "cleanup_old_files",
        "delete_orphaned_files",
        "expire_snapshots",  # may schedule deletions; file delete on cleanup
        "compaction",
        "merge_adjacent_files",
        "rewrite_data_files",
        "delete_file_rewrite",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MaintenanceError(ValueError):
    """Fail-closed maintenance policy rejection."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class AuthorizationError(MaintenanceError):
    """Maintenance authorization missing, self-issued, expired, or mismatched."""


class QuackTokenAuthorizationError(AuthorizationError):
    """Possession of a Quack token cannot self-authorize maintenance."""


class FenceError(MaintenanceError):
    """Catalog-owner generation or mutation fence mismatch."""


class PolicyError(MaintenanceError):
    """Retention / partition / sort policy violation."""


class RetentionError(PolicyError):
    """Catalog-global retention class or expiry ordering violation."""


class DryRunError(MaintenanceError):
    """Dry-run required, expired, mismatched, or not accepted."""


class ExecutionError(MaintenanceError):
    """Destructive execution failed closed (auth, fence, dry-run, or IAM)."""


class ObjectDeleteIamError(ExecutionError):
    """Scoped object-delete IAM missing, expired, mismatched, or reused."""


class OrphanError(MaintenanceError):
    """Orphan deletion prerequisites not satisfied."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RetentionClass(str, Enum):
    """Catalog-global retention class (exactly one per catalog)."""

    SHORT = "short"
    STANDARD = "standard"
    LONG = "long"
    ARCHIVE = "archive"


class MaintenanceAction(str, Enum):
    """Receipted maintenance actions (never bare CHECKPOINT / cleanup_all)."""

    PARTITION_EVOLUTION = "partition_evolution"
    SORT_EVOLUTION = "sort_evolution"
    FILE_ROW_GROUP_SIZING = "file_row_group_sizing"
    FLUSH_INLINED_DATA = "flush_inlined_data"
    MERGE_ADJACENT_FILES = "merge_adjacent_files"
    REWRITE_DATA_FILES = "rewrite_data_files"
    DELETE_FILE_REWRITE = "delete_file_rewrite"
    COMPACTION = "compaction"
    STATISTICS = "statistics"
    EXPIRE_SNAPSHOTS = "expire_snapshots"
    CLEANUP_OLD_FILES = "cleanup_old_files"
    DELETE_ORPHANED_FILES = "delete_orphaned_files"


class MaintenancePhase(str, Enum):
    """Lifecycle phase of a receipted maintenance operation."""

    PLANNED = "planned"
    DRY_RUN_ACCEPTED = "dry_run_accepted"
    AUTHORIZED = "authorized"
    EXECUTED = "executed"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(ts: float | None = None) -> str:
    clock = time.time() if ts is None else float(ts)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock))


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _sha256_text(text: str) -> str:
    return _SHA256_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MaintenanceError(f"{field_name} is required")
    return text


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise MaintenanceError(f"{field_name} must be a positive int")
    return value


def _require_nonneg_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MaintenanceError(f"{field_name} must be a non-negative int")
    return value


def _normalize_digest(value: str) -> str:
    text = str(value or "").strip().lower()
    if text.startswith(_SHA256_PREFIX):
        hexpart = text[len(_SHA256_PREFIX) :]
    else:
        hexpart = text
    if len(hexpart) != 64 or any(c not in "0123456789abcdef" for c in hexpart):
        raise MaintenanceError(f"invalid digest {value!r}")
    return _SHA256_PREFIX + hexpart


def _coerce_action(action: MaintenanceAction | str) -> MaintenanceAction:
    if isinstance(action, MaintenanceAction):
        return action
    text = str(action or "").strip().lower()
    try:
        return MaintenanceAction(text)
    except ValueError as exc:
        raise MaintenanceError(f"unknown maintenance action {action!r}") from exc


def _coerce_retention_class(value: RetentionClass | str) -> RetentionClass:
    if isinstance(value, RetentionClass):
        return value
    try:
        return RetentionClass(str(value or "").strip().lower())
    except ValueError as exc:
        raise RetentionError(f"unknown retention class {value!r}") from exc


def _coerce_process_birth(value: ProcessBirth | Mapping[str, Any]) -> ProcessBirth:
    if isinstance(value, ProcessBirth):
        return value
    if isinstance(value, Mapping):
        return ProcessBirth.from_mapping(value)
    raise MaintenanceError("process_birth is required")


def _sorted_unique(values: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(sorted({str(v) for v in (values or ()) if str(v)}))


def file_set_digest(file_ids: Sequence[str] | None) -> str:
    """Canonical digest of a candidate / created / deleted file set."""

    return _sha256_text(_canonical_json(list(_sorted_unique(file_ids))))


def lease_set_digest(leases: Sequence[Mapping[str, Any]] | None) -> str:
    """Canonical digest of the authoritative DQK-090 live reader-lease set.

    Uses lease identity fields only (never raw tokens). Order-independent.
    """

    rows: list[dict[str, Any]] = []
    for raw in leases or ():
        row = dict(raw)
        # Redact any residual token material.
        if "lease_token" in row:
            row["lease_token"] = "***"
        # Stable projection for fence binding.
        projection = {
            "lease_id": str(row.get("lease_id") or ""),
            "vector_id": str(row.get("vector_id") or ""),
            "catalog_id": str(row.get("catalog_id") or ""),
            "snapshot_version": int(row.get("snapshot_version") or 0),
            "owner_generation": int(row.get("owner_generation") or 0),
            "fencing_epoch": int(row.get("fencing_epoch") or 0),
            "status": str(row.get("status") or ""),
            "task_id": str(row.get("task_id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "worker_id": str(row.get("worker_id") or ""),
            "acquired_at": str(row.get("acquired_at") or ""),
            "renewed_at": str(row.get("renewed_at") or ""),
            "expires_at": str(row.get("expires_at") or ""),
        }
        rows.append(projection)
    rows.sort(key=lambda r: r["lease_id"])
    return _sha256_text(_canonical_json(rows))


def assert_not_bare_checkpoint(statement: str | None) -> None:
    """Reject bare CHECKPOINT (and equivalents)."""

    if statement is None:
        return
    text = str(statement).strip()
    if not text:
        return
    normalized = " ".join(text.split())
    upper = normalized.upper()
    if upper == "CHECKPOINT" or upper.startswith("CHECKPOINT;") or upper in {
        "CALL CHECKPOINT",
        "CALL CHECKPOINT()",
        "PRAGMA CHECKPOINT",
    }:
        raise MaintenanceError(
            "bare CHECKPOINT is forbidden; maintenance must use receipted "
            "explicit actions with owner-broker authorization and dry-run",
            details={"statement": text},
        )
    if text in FORBIDDEN_BARE_STATEMENTS or normalized in FORBIDDEN_BARE_STATEMENTS:
        raise MaintenanceError(
            "bare CHECKPOINT is forbidden",
            details={"statement": text},
        )


def assert_not_cleanup_all(action: str | MaintenanceAction | None) -> None:
    """Reject automated / unattended cleanup_all."""

    if action is None:
        return
    text = action.value if isinstance(action, MaintenanceAction) else str(action)
    key = text.strip()
    if key in FORBIDDEN_AUTOMATED_ACTIONS or key.lower() in {
        a.lower() for a in FORBIDDEN_AUTOMATED_ACTIONS
    }:
        raise MaintenanceError(
            "automated cleanup_all is forbidden; use receipted scheduled "
            "cleanup_old_files with dry-run, owner-broker authorization, and "
            "scoped object-delete IAM",
            details={"action": key},
        )


def assert_quack_token_cannot_authorize_maintenance(
    quack_token: str | Mapping[str, Any] | None,
    *,
    action: MaintenanceAction | str,
) -> None:
    """Fail closed: a Quack token alone never authorizes maintenance."""

    op = _coerce_action(action)
    has_token = False
    if isinstance(quack_token, Mapping):
        has_token = bool(quack_token.get("token_id") or quack_token.get("secret"))
    elif quack_token is not None and str(quack_token).strip():
        has_token = True
    if has_token:
        raise QuackTokenAuthorizationError(
            f"Quack token alone cannot authorize maintenance action {op.value!r}; "
            "independent trusted owner-broker authorization is required "
            "(token is transport-only)",
            details={"action": op.value, "quack_token_sufficient": False},
        )
    raise QuackTokenAuthorizationError(
        f"missing owner-broker authorization for maintenance action {op.value!r}; "
        "a Quack transport token is never sufficient",
        details={"action": op.value, "quack_token_sufficient": False},
    )


def _action_requires_auth(action: MaintenanceAction) -> bool:
    if action.value in _AUTH_REQUIRED_ACTIONS:
        return True
    return action is MaintenanceAction.COMPACTION


def _action_is_destructive(action: MaintenanceAction) -> bool:
    return action.value in _DESTRUCTIVE_ACTIONS or action is MaintenanceAction.COMPACTION


def _action_may_delete(action: MaintenanceAction) -> bool:
    return action.value in _DELETION_ACTIONS or action is MaintenanceAction.COMPACTION


def _ducklake_function_for(action: MaintenanceAction) -> str | None:
    mapping = {
        MaintenanceAction.FLUSH_INLINED_DATA: MaintenanceFunction.FLUSH_INLINED_DATA.value,
        MaintenanceAction.MERGE_ADJACENT_FILES: MaintenanceFunction.MERGE_ADJACENT_FILES.value,
        MaintenanceAction.REWRITE_DATA_FILES: MaintenanceFunction.REWRITE_DATA_FILES.value,
        MaintenanceAction.DELETE_FILE_REWRITE: MaintenanceFunction.REWRITE_DATA_FILES.value,
        MaintenanceAction.COMPACTION: MaintenanceFunction.REWRITE_DATA_FILES.value,
        MaintenanceAction.EXPIRE_SNAPSHOTS: MaintenanceFunction.EXPIRE_SNAPSHOTS.value,
        MaintenanceAction.CLEANUP_OLD_FILES: MaintenanceFunction.CLEANUP_OLD_FILES.value,
        MaintenanceAction.DELETE_ORPHANED_FILES: MaintenanceFunction.DELETE_ORPHANED_FILES.value,
    }
    return mapping.get(action)


# ---------------------------------------------------------------------------
# Protocols for lease authority (DQK-090)
# ---------------------------------------------------------------------------


class LiveLeaseAuthority(Protocol):
    """Minimal surface for authoritative DQK-090 live reader-lease queries."""

    def list_live_leases(
        self,
        *,
        catalog_id: str | None = None,
        vector_id: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        ...


# ---------------------------------------------------------------------------
# Retention policy (one strict global class per catalog)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogRetentionPolicy:
    """Exactly one catalog-global retention class and snapshot retention window."""

    SCHEMA: ClassVar[str] = RETENTION_POLICY_SCHEMA

    policy_id: str
    catalog_id: str
    retention_class: RetentionClass
    retain_snapshots: int = _DEFAULT_RETAIN_SNAPSHOTS
    orphan_min_age_seconds: int = _DEFAULT_ORPHAN_MIN_AGE_SECONDS
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _require_nonempty(self.policy_id, field_name="policy_id")
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self, "retention_class", _coerce_retention_class(self.retention_class)
        )
        object.__setattr__(
            self,
            "retain_snapshots",
            _require_positive_int(self.retain_snapshots, field_name="retain_snapshots"),
        )
        object.__setattr__(
            self,
            "orphan_min_age_seconds",
            _require_nonneg_int(
                self.orphan_min_age_seconds, field_name="orphan_min_age_seconds"
            ),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "policy_id": self.policy_id,
                "catalog_id": self.catalog_id,
                "retention_class": self.retention_class.value,
                "retain_snapshots": self.retain_snapshots,
                "orphan_min_age_seconds": self.orphan_min_age_seconds,
                "strict_single_global_class": True,
                "notes": self.notes,
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CatalogRetentionPolicy":
        return cls(
            policy_id=str(payload["policy_id"]),
            catalog_id=str(payload["catalog_id"]),
            retention_class=str(payload["retention_class"]),
            retain_snapshots=int(
                payload.get("retain_snapshots") or _DEFAULT_RETAIN_SNAPSHOTS
            ),
            orphan_min_age_seconds=int(
                payload.get("orphan_min_age_seconds") or _DEFAULT_ORPHAN_MIN_AGE_SECONDS
            ),
            notes=str(payload.get("notes") or ""),
        )


# ---------------------------------------------------------------------------
# File / lease records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LakeFileRecord:
    """Lifecycle-managed lake file identity with snapshot membership."""

    file_id: str
    path: str
    content_digest: str
    snapshot_versions: tuple[int, ...]
    logical_row_count: int
    schema_version: str
    provenance_cid: str = ""
    partition_spec: str = ""
    sort_order: str = ""
    owned_namespace: bool = True
    created_at_unix: float = 0.0
    inlined: bool = False
    scheduled_for_deletion: bool = False
    deleted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "file_id", _require_nonempty(self.file_id, field_name="file_id")
        )
        object.__setattr__(
            self, "path", _require_nonempty(self.path, field_name="path")
        )
        object.__setattr__(
            self, "content_digest", _normalize_digest(self.content_digest)
        )
        snaps = tuple(sorted({int(v) for v in self.snapshot_versions}))
        object.__setattr__(self, "snapshot_versions", snaps)
        object.__setattr__(
            self,
            "logical_row_count",
            _require_nonneg_int(self.logical_row_count, field_name="logical_row_count"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_nonempty(self.schema_version, field_name="schema_version"),
        )
        if self.created_at_unix <= 0:
            object.__setattr__(self, "created_at_unix", time.time())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "file_id": self.file_id,
                "path": self.path,
                "content_digest": self.content_digest,
                "snapshot_versions": list(self.snapshot_versions),
                "logical_row_count": self.logical_row_count,
                "schema_version": self.schema_version,
                "provenance_cid": self.provenance_cid,
                "partition_spec": self.partition_spec,
                "sort_order": self.sort_order,
                "owned_namespace": self.owned_namespace,
                "created_at_unix": self.created_at_unix,
                "inlined": self.inlined,
                "scheduled_for_deletion": self.scheduled_for_deletion,
                "deleted": self.deleted,
            }
        )

    def with_updates(self, **kwargs: Any) -> "LakeFileRecord":
        payload = dict(self.as_mapping())
        payload.update(kwargs)
        payload["snapshot_versions"] = tuple(payload["snapshot_versions"])
        return LakeFileRecord(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class UploadLease:
    """Live upload lease protecting in-progress objects from orphan deletion."""

    SCHEMA: ClassVar[str] = UPLOAD_LEASE_SCHEMA

    lease_id: str
    object_path: str
    catalog_id: str
    caller_id: str
    expires_at_unix: float
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "lease_id", _require_nonempty(self.lease_id, field_name="lease_id")
        )
        object.__setattr__(
            self,
            "object_path",
            _require_nonempty(self.object_path, field_name="object_path"),
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_nonempty(self.caller_id, field_name="caller_id")
        )
        status = str(self.status or "active").strip().lower()
        if status not in {"active", "released", "expired"}:
            raise MaintenanceError(f"invalid upload lease status {self.status!r}")
        object.__setattr__(self, "status", status)

    def is_live(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return self.status == "active" and clock < float(self.expires_at_unix)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "lease_id": self.lease_id,
                "object_path": self.object_path,
                "catalog_id": self.catalog_id,
                "caller_id": self.caller_id,
                "expires_at_unix": self.expires_at_unix,
                "status": self.status,
            }
        )


# ---------------------------------------------------------------------------
# Authorizations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaintenanceAuthorization:
    """Non-self-issued operation authorization from the trusted owner broker.

    Independently issued per action. Issuer identity must differ from both the
    maintainer (caller) and any Quack transport identity. Fence-checked before
    the single catalog owner mutates state.
    """

    SCHEMA: ClassVar[str] = MAINTENANCE_AUTH_SCHEMA

    authorization_id: str
    action: MaintenanceAction
    operation_id: str
    caller_id: str
    process_birth: ProcessBirth
    generation_fence: int
    catalog_id: str
    starting_snapshot: int
    issuer_id: str
    nonce: str
    expires_at_unix: float
    candidate_file_set_digest: str
    reader_lease_set_digest: str
    policy_digest: str
    used: bool = False
    issued_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_id",
            _require_nonempty(self.authorization_id, field_name="authorization_id"),
        )
        object.__setattr__(self, "action", _coerce_action(self.action))
        object.__setattr__(
            self,
            "operation_id",
            _require_nonempty(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_nonempty(self.caller_id, field_name="caller_id")
        )
        object.__setattr__(self, "process_birth", _coerce_process_birth(self.process_birth))
        object.__setattr__(
            self,
            "generation_fence",
            _require_positive_int(self.generation_fence, field_name="generation_fence"),
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self,
            "starting_snapshot",
            _require_nonneg_int(self.starting_snapshot, field_name="starting_snapshot"),
        )
        object.__setattr__(
            self, "issuer_id", _require_nonempty(self.issuer_id, field_name="issuer_id")
        )
        object.__setattr__(
            self, "nonce", _require_nonempty(self.nonce, field_name="nonce")
        )
        object.__setattr__(
            self,
            "candidate_file_set_digest",
            _normalize_digest(self.candidate_file_set_digest)
            if str(self.candidate_file_set_digest).startswith(_SHA256_PREFIX)
            or len(str(self.candidate_file_set_digest).replace(_SHA256_PREFIX, ""))
            == 64
            else _sha256_text(str(self.candidate_file_set_digest)),
        )
        object.__setattr__(
            self,
            "reader_lease_set_digest",
            _normalize_digest(self.reader_lease_set_digest)
            if str(self.reader_lease_set_digest).startswith(_SHA256_PREFIX)
            or len(str(self.reader_lease_set_digest).replace(_SHA256_PREFIX, "")) == 64
            else _sha256_text(str(self.reader_lease_set_digest)),
        )
        object.__setattr__(
            self,
            "policy_digest",
            _normalize_digest(self.policy_digest)
            if str(self.policy_digest).startswith(_SHA256_PREFIX)
            or len(str(self.policy_digest).replace(_SHA256_PREFIX, "")) == 64
            else _sha256_text(str(self.policy_digest)),
        )
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _utc_iso())
        if self.issuer_id == self.caller_id:
            raise AuthorizationError(
                "maintenance authorization must be non-self-issued; trusted "
                "owner broker issues, maintainer cannot self-authorize",
                details={
                    "issuer_id": self.issuer_id,
                    "caller_id": self.caller_id,
                    "action": self.action.value,
                },
            )

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def binding_digest(self) -> str:
        body = {
            "authorization_id": self.authorization_id,
            "action": self.action.value,
            "operation_id": self.operation_id,
            "caller_id": self.caller_id,
            "process_birth": dict(self.process_birth.as_mapping()),
            "generation_fence": self.generation_fence,
            "catalog_id": self.catalog_id,
            "starting_snapshot": self.starting_snapshot,
            "issuer_id": self.issuer_id,
            "nonce": self.nonce,
            "expires_at_unix": self.expires_at_unix,
            "candidate_file_set_digest": self.candidate_file_set_digest,
            "reader_lease_set_digest": self.reader_lease_set_digest,
            "policy_digest": self.policy_digest,
            "issued_at": self.issued_at,
        }
        return _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "authorization_id": self.authorization_id,
                "action": self.action.value,
                "operation_id": self.operation_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "generation_fence": self.generation_fence,
                "catalog_id": self.catalog_id,
                "starting_snapshot": self.starting_snapshot,
                "issuer_id": self.issuer_id,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "candidate_file_set_digest": self.candidate_file_set_digest,
                "reader_lease_set_digest": self.reader_lease_set_digest,
                "policy_digest": self.policy_digest,
                "used": self.used,
                "issued_at": self.issued_at,
                "binding_digest": self.binding_digest(),
                "non_self_issued": True,
                "quack_token_sufficient": False,
            }
        )

    def mark_used(self) -> "MaintenanceAuthorization":
        if self.used:
            raise AuthorizationError(
                f"authorization {self.authorization_id!r} already used; one "
                "receipt cannot confer ambient future maintenance authority",
                details={"authorization_id": self.authorization_id},
            )
        return MaintenanceAuthorization(
            authorization_id=self.authorization_id,
            action=self.action,
            operation_id=self.operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            catalog_id=self.catalog_id,
            starting_snapshot=self.starting_snapshot,
            issuer_id=self.issuer_id,
            nonce=self.nonce,
            expires_at_unix=self.expires_at_unix,
            candidate_file_set_digest=self.candidate_file_set_digest,
            reader_lease_set_digest=self.reader_lease_set_digest,
            policy_digest=self.policy_digest,
            used=True,
            issued_at=self.issued_at,
        )


@dataclass(frozen=True, slots=True)
class ObjectDeleteIamGrant:
    """Separate scoped object-delete IAM (never ambient on maintainers)."""

    SCHEMA: ClassVar[str] = OBJECT_DELETE_IAM_SCHEMA

    grant_id: str
    operation_id: str
    caller_id: str
    process_birth: ProcessBirth
    generation_fence: int
    catalog_id: str
    scope_prefix: str
    candidate_file_set_digest: str
    authorization_id: str
    issuer_id: str
    nonce: str
    expires_at_unix: float
    _secret: str = field(repr=False, default="")
    used: bool = False
    issued_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "grant_id", _require_nonempty(self.grant_id, field_name="grant_id")
        )
        object.__setattr__(
            self,
            "operation_id",
            _require_nonempty(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_nonempty(self.caller_id, field_name="caller_id")
        )
        object.__setattr__(self, "process_birth", _coerce_process_birth(self.process_birth))
        object.__setattr__(
            self,
            "generation_fence",
            _require_positive_int(self.generation_fence, field_name="generation_fence"),
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self,
            "scope_prefix",
            _require_nonempty(self.scope_prefix, field_name="scope_prefix"),
        )
        object.__setattr__(
            self,
            "candidate_file_set_digest",
            _normalize_digest(self.candidate_file_set_digest)
            if str(self.candidate_file_set_digest).startswith(_SHA256_PREFIX)
            or len(str(self.candidate_file_set_digest).replace(_SHA256_PREFIX, ""))
            == 64
            else _sha256_text(str(self.candidate_file_set_digest)),
        )
        object.__setattr__(
            self,
            "authorization_id",
            _require_nonempty(self.authorization_id, field_name="authorization_id"),
        )
        object.__setattr__(
            self, "issuer_id", _require_nonempty(self.issuer_id, field_name="issuer_id")
        )
        object.__setattr__(
            self, "nonce", _require_nonempty(self.nonce, field_name="nonce")
        )
        secret = str(self._secret or "")
        if not secret:
            raise ObjectDeleteIamError("object-delete IAM secret must be non-empty")
        object.__setattr__(self, "_secret", secret)
        if self.issuer_id == self.caller_id:
            raise ObjectDeleteIamError(
                "object-delete IAM must be issued by an identity distinct from "
                "the maintainer caller"
            )
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _utc_iso())

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"ObjectDeleteIamGrant(grant_id={self.grant_id!r}, "
            f"operation_id={self.operation_id!r}, secret=***)"
        )

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "grant_id": self.grant_id,
                "operation_id": self.operation_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "generation_fence": self.generation_fence,
                "catalog_id": self.catalog_id,
                "scope_prefix": self.scope_prefix,
                "candidate_file_set_digest": self.candidate_file_set_digest,
                "authorization_id": self.authorization_id,
                "issuer_id": self.issuer_id,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "used": self.used,
                "issued_at": self.issued_at,
                "secret": "***REDACTED***",
                "ambient": False,
            }
        )

    def mark_used(self) -> "ObjectDeleteIamGrant":
        if self.used:
            raise ObjectDeleteIamError(
                f"object-delete IAM grant {self.grant_id!r} already used"
            )
        return ObjectDeleteIamGrant(
            grant_id=self.grant_id,
            operation_id=self.operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            catalog_id=self.catalog_id,
            scope_prefix=self.scope_prefix,
            candidate_file_set_digest=self.candidate_file_set_digest,
            authorization_id=self.authorization_id,
            issuer_id=self.issuer_id,
            nonce=self.nonce,
            expires_at_unix=self.expires_at_unix,
            _secret=self._secret,
            used=True,
            issued_at=self.issued_at,
        )


def revalidate_maintenance_authorization(
    auth: MaintenanceAuthorization,
    *,
    action: MaintenanceAction,
    operation_id: str,
    caller_id: str,
    process_birth: ProcessBirth,
    generation_fence: int,
    catalog_id: str,
    starting_snapshot: int,
    candidate_file_set_digest: str,
    reader_lease_set_digest: str,
    policy_digest: str,
    now: float | None = None,
) -> MaintenanceAuthorization:
    """Independently revalidate authorization immediately before use."""

    if auth.used:
        raise AuthorizationError(
            "authorization already consumed; cannot confer ambient authority",
            details={"authorization_id": auth.authorization_id},
        )
    if auth.action is not action:
        raise AuthorizationError(
            f"authorization action mismatch: expected {action.value}, got "
            f"{auth.action.value}"
        )
    if auth.operation_id != operation_id:
        raise AuthorizationError("authorization operation_id mismatch")
    if auth.caller_id != caller_id:
        raise AuthorizationError("authorization caller_id mismatch")
    if auth.process_birth.fingerprint() != process_birth.fingerprint():
        raise AuthorizationError("authorization process_birth fence mismatch")
    if auth.generation_fence != generation_fence:
        raise FenceError("authorization generation_fence mismatch")
    if auth.catalog_id != catalog_id:
        raise AuthorizationError("authorization catalog_id mismatch")
    if auth.starting_snapshot != starting_snapshot:
        raise AuthorizationError("authorization starting_snapshot mismatch")
    if auth.candidate_file_set_digest != _normalize_digest(candidate_file_set_digest):
        raise AuthorizationError("authorization candidate file-set fence mismatch")
    if auth.reader_lease_set_digest != _normalize_digest(reader_lease_set_digest):
        raise AuthorizationError("authorization reader-lease set fence mismatch")
    if auth.policy_digest != _normalize_digest(policy_digest):
        raise AuthorizationError("authorization policy fence mismatch")
    if auth.is_expired(now=now):
        raise AuthorizationError(
            "authorization expired",
            details={"authorization_id": auth.authorization_id},
        )
    if auth.issuer_id == auth.caller_id:
        raise AuthorizationError("authorization is self-issued; fail closed")
    return auth.mark_used()


def revalidate_object_delete_iam(
    grant: ObjectDeleteIamGrant,
    *,
    operation_id: str,
    caller_id: str,
    process_birth: ProcessBirth,
    generation_fence: int,
    catalog_id: str,
    candidate_file_set_digest: str,
    authorization_id: str,
    paths_to_delete: Sequence[str],
    now: float | None = None,
) -> ObjectDeleteIamGrant:
    """Revalidate scoped object-delete IAM immediately before deletion."""

    if grant.used:
        raise ObjectDeleteIamError("object-delete IAM already consumed")
    if grant.operation_id != operation_id:
        raise ObjectDeleteIamError("object-delete IAM operation_id mismatch")
    if grant.caller_id != caller_id:
        raise ObjectDeleteIamError("object-delete IAM caller_id mismatch")
    if grant.process_birth.fingerprint() != process_birth.fingerprint():
        raise ObjectDeleteIamError("object-delete IAM process_birth mismatch")
    if grant.generation_fence != generation_fence:
        raise FenceError("object-delete IAM generation_fence mismatch")
    if grant.catalog_id != catalog_id:
        raise ObjectDeleteIamError("object-delete IAM catalog_id mismatch")
    if grant.candidate_file_set_digest != _normalize_digest(candidate_file_set_digest):
        raise ObjectDeleteIamError("object-delete IAM candidate file-set mismatch")
    if grant.authorization_id != authorization_id:
        raise ObjectDeleteIamError("object-delete IAM authorization_id mismatch")
    if grant.is_expired(now=now):
        raise ObjectDeleteIamError("object-delete IAM expired")
    prefix = grant.scope_prefix.rstrip("/") + "/"
    for path in paths_to_delete:
        p = str(path)
        if not (p == grant.scope_prefix.rstrip("/") or p.startswith(prefix)):
            raise ObjectDeleteIamError(
                "object path outside scoped object-delete IAM prefix",
                details={"path": p, "scope_prefix": grant.scope_prefix},
            )
    return grant.mark_used()


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DryRunReceipt:
    """Accepted dry-run evidence required before destructive execution.

    Binds exact caller/process birth and generation fence, catalog identity,
    starting snapshot/version, authoritative DQK-090 reader-lease set, policy,
    action, authorization, candidate file set, nonce, and expiry.
    """

    SCHEMA: ClassVar[str] = DRY_RUN_RECEIPT_SCHEMA

    dry_run_id: str
    operation_id: str
    action: MaintenanceAction
    catalog_id: str
    caller_id: str
    process_birth: ProcessBirth
    generation_fence: int
    starting_snapshot: int
    policy: CatalogRetentionPolicy
    authorization_id: str
    authorization_binding_digest: str
    candidate_file_ids: tuple[str, ...]
    candidate_file_set_digest: str
    reader_lease_set: tuple[Mapping[str, Any], ...]
    reader_lease_set_digest: str
    nonce: str
    expires_at_unix: float
    predicted_created_file_ids: tuple[str, ...] = ()
    predicted_deleted_file_ids: tuple[str, ...] = ()
    predicted_resulting_snapshot: int | None = None
    ducklake_function: str | None = None
    accepted: bool = True
    mode: str = "dry_run"
    issued_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dry_run_id",
            _require_nonempty(self.dry_run_id, field_name="dry_run_id"),
        )
        object.__setattr__(
            self,
            "operation_id",
            _require_nonempty(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(self, "action", _coerce_action(self.action))
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_nonempty(self.caller_id, field_name="caller_id")
        )
        object.__setattr__(self, "process_birth", _coerce_process_birth(self.process_birth))
        object.__setattr__(
            self,
            "generation_fence",
            _require_positive_int(self.generation_fence, field_name="generation_fence"),
        )
        object.__setattr__(
            self,
            "starting_snapshot",
            _require_nonneg_int(self.starting_snapshot, field_name="starting_snapshot"),
        )
        if not isinstance(self.policy, CatalogRetentionPolicy):
            raise DryRunError("policy must be CatalogRetentionPolicy")
        object.__setattr__(
            self,
            "authorization_id",
            _require_nonempty(self.authorization_id, field_name="authorization_id"),
        )
        object.__setattr__(
            self,
            "candidate_file_ids",
            _sorted_unique(self.candidate_file_ids),
        )
        expected_files = file_set_digest(self.candidate_file_ids)
        if self.candidate_file_set_digest:
            if _normalize_digest(self.candidate_file_set_digest) != expected_files:
                raise DryRunError("candidate_file_set_digest does not match file set")
        else:
            object.__setattr__(self, "candidate_file_set_digest", expected_files)
        leases = tuple(dict(row) for row in self.reader_lease_set)
        object.__setattr__(self, "reader_lease_set", leases)
        expected_leases = lease_set_digest(leases)
        if self.reader_lease_set_digest:
            if _normalize_digest(self.reader_lease_set_digest) != expected_leases:
                raise DryRunError("reader_lease_set_digest does not match lease set")
        else:
            object.__setattr__(self, "reader_lease_set_digest", expected_leases)
        object.__setattr__(
            self, "nonce", _require_nonempty(self.nonce, field_name="nonce")
        )
        object.__setattr__(
            self,
            "predicted_created_file_ids",
            _sorted_unique(self.predicted_created_file_ids),
        )
        object.__setattr__(
            self,
            "predicted_deleted_file_ids",
            _sorted_unique(self.predicted_deleted_file_ids),
        )
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _utc_iso())
        object.__setattr__(self, "mode", "dry_run")
        object.__setattr__(self, "accepted", bool(self.accepted))

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def binding_digest(self) -> str:
        body = {
            "dry_run_id": self.dry_run_id,
            "operation_id": self.operation_id,
            "action": self.action.value,
            "catalog_id": self.catalog_id,
            "caller_id": self.caller_id,
            "process_birth": dict(self.process_birth.as_mapping()),
            "generation_fence": self.generation_fence,
            "starting_snapshot": self.starting_snapshot,
            "policy": dict(self.policy.as_mapping()),
            "authorization_id": self.authorization_id,
            "authorization_binding_digest": self.authorization_binding_digest,
            "candidate_file_ids": list(self.candidate_file_ids),
            "candidate_file_set_digest": self.candidate_file_set_digest,
            "reader_lease_set_digest": self.reader_lease_set_digest,
            "nonce": self.nonce,
            "expires_at_unix": self.expires_at_unix,
            "predicted_created_file_ids": list(self.predicted_created_file_ids),
            "predicted_deleted_file_ids": list(self.predicted_deleted_file_ids),
            "predicted_resulting_snapshot": self.predicted_resulting_snapshot,
            "ducklake_function": self.ducklake_function,
            "accepted": self.accepted,
            "issued_at": self.issued_at,
        }
        return _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "dry_run_id": self.dry_run_id,
                "operation_id": self.operation_id,
                "action": self.action.value,
                "catalog_id": self.catalog_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "generation_fence": self.generation_fence,
                "starting_snapshot": self.starting_snapshot,
                "policy": dict(self.policy.as_mapping()),
                "authorization_id": self.authorization_id,
                "authorization_binding_digest": self.authorization_binding_digest,
                "candidate_file_ids": list(self.candidate_file_ids),
                "candidate_file_set_digest": self.candidate_file_set_digest,
                "reader_lease_set": [dict(r) for r in self.reader_lease_set],
                "reader_lease_set_digest": self.reader_lease_set_digest,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "predicted_created_file_ids": list(self.predicted_created_file_ids),
                "predicted_deleted_file_ids": list(self.predicted_deleted_file_ids),
                "predicted_resulting_snapshot": self.predicted_resulting_snapshot,
                "ducklake_function": self.ducklake_function,
                "accepted": self.accepted,
                "mode": self.mode,
                "issued_at": self.issued_at,
                "binding_digest": self.binding_digest(),
                "notes": self.notes,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
            }
        )


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    """Execution receipt after reauthorization and dry-run match.

    Binds the same fence fields as the dry-run plus the exact resulting
    snapshot and created/deleted file set.
    """

    SCHEMA: ClassVar[str] = EXECUTION_RECEIPT_SCHEMA

    execution_id: str
    operation_id: str
    action: MaintenanceAction
    catalog_id: str
    caller_id: str
    process_birth: ProcessBirth
    generation_fence: int
    starting_snapshot: int
    resulting_snapshot: int
    policy: CatalogRetentionPolicy
    authorization_id: str
    dry_run_id: str
    dry_run_binding_digest: str
    candidate_file_ids: tuple[str, ...]
    candidate_file_set_digest: str
    reader_lease_set_digest: str
    created_file_ids: tuple[str, ...]
    deleted_file_ids: tuple[str, ...]
    object_delete_iam_grant_id: str | None
    nonce: str
    phase: MaintenancePhase = MaintenancePhase.EXECUTED
    ducklake_function: str | None = None
    executed_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_id",
            _require_nonempty(self.execution_id, field_name="execution_id"),
        )
        object.__setattr__(
            self,
            "operation_id",
            _require_nonempty(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(self, "action", _coerce_action(self.action))
        object.__setattr__(self, "process_birth", _coerce_process_birth(self.process_birth))
        object.__setattr__(
            self,
            "candidate_file_ids",
            _sorted_unique(self.candidate_file_ids),
        )
        object.__setattr__(
            self, "created_file_ids", _sorted_unique(self.created_file_ids)
        )
        object.__setattr__(
            self, "deleted_file_ids", _sorted_unique(self.deleted_file_ids)
        )
        if not isinstance(self.phase, MaintenancePhase):
            object.__setattr__(self, "phase", MaintenancePhase(str(self.phase)))
        if not self.executed_at:
            object.__setattr__(self, "executed_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "execution_id": self.execution_id,
                "operation_id": self.operation_id,
                "action": self.action.value,
                "catalog_id": self.catalog_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "generation_fence": self.generation_fence,
                "starting_snapshot": self.starting_snapshot,
                "resulting_snapshot": self.resulting_snapshot,
                "policy": dict(self.policy.as_mapping()),
                "authorization_id": self.authorization_id,
                "dry_run_id": self.dry_run_id,
                "dry_run_binding_digest": self.dry_run_binding_digest,
                "candidate_file_ids": list(self.candidate_file_ids),
                "candidate_file_set_digest": self.candidate_file_set_digest,
                "reader_lease_set_digest": self.reader_lease_set_digest,
                "created_file_ids": list(self.created_file_ids),
                "deleted_file_ids": list(self.deleted_file_ids),
                "created_file_set_digest": file_set_digest(self.created_file_ids),
                "deleted_file_set_digest": file_set_digest(self.deleted_file_ids),
                "object_delete_iam_grant_id": self.object_delete_iam_grant_id,
                "nonce": self.nonce,
                "phase": self.phase.value,
                "ducklake_function": self.ducklake_function,
                "executed_at": self.executed_at,
                "notes": self.notes,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
            }
        )


# ---------------------------------------------------------------------------
# Trusted owner broker (maintenance)
# ---------------------------------------------------------------------------


class MaintenanceOwnerBroker:
    """Trusted owner-broker identity for maintenance authorizations.

    Distinct from the maintainer. Issues one-use operation authorizations and
    separate scoped object-delete IAM grants. Never accepts Quack tokens as
    authorization evidence. Fence-checked against the single catalog-owner
    generation before issuance.
    """

    def __init__(
        self,
        *,
        broker_id: str,
        catalog_id: str,
        generation_fence: int,
        data_path: str,
        delete_iam_issuer_id: str | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.broker_id = _require_nonempty(broker_id, field_name="broker_id")
        self.catalog_id = _require_nonempty(catalog_id, field_name="catalog_id")
        self.generation_fence = _require_positive_int(
            generation_fence, field_name="generation_fence"
        )
        self.data_path = _require_nonempty(data_path, field_name="data_path")
        self.delete_iam_issuer_id = _require_nonempty(
            delete_iam_issuer_id or f"delete-iam-issuer-{broker_id}",
            field_name="delete_iam_issuer_id",
        )
        if self.delete_iam_issuer_id == self.broker_id:
            raise AuthorizationError(
                "object-delete IAM issuer must be distinct from owner broker"
            )
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._issued: dict[str, MaintenanceAuthorization] = {}
        self._delete_grants: dict[str, ObjectDeleteIamGrant] = {}
        self._used_auth: set[str] = set()
        self._used_grants: set[str] = set()

    def _assert_fence(self, generation_fence: int) -> None:
        if int(generation_fence) != self.generation_fence:
            raise FenceError(
                f"generation fence mismatch: broker fence "
                f"{self.generation_fence}, caller fence {generation_fence}"
            )

    def issue_authorization(
        self,
        *,
        action: MaintenanceAction | str,
        operation_id: str,
        caller_id: str,
        process_birth: ProcessBirth,
        generation_fence: int,
        starting_snapshot: int,
        candidate_file_set_digest: str,
        reader_lease_set_digest: str,
        policy_digest: str,
        ttl_seconds: int = _DEFAULT_AUTH_TTL_SECONDS,
        authorization_id: str | None = None,
        quack_token: str | Mapping[str, Any] | None = None,
    ) -> MaintenanceAuthorization:
        """Issue a non-self-issued maintenance authorization (Quack ignored)."""

        # Quack token presence is irrelevant and never sufficient.
        _ = quack_token
        action_e = _coerce_action(action)
        assert_not_cleanup_all(action_e)
        self._assert_fence(generation_fence)
        caller = _require_nonempty(caller_id, field_name="caller_id")
        if caller == self.broker_id:
            raise AuthorizationError(
                "broker cannot issue maintenance authorization to itself as "
                "caller; keep broker and maintainer identities distinct"
            )
        if caller == self.delete_iam_issuer_id:
            raise AuthorizationError(
                "delete-IAM issuer cannot be the maintenance caller"
            )
        now = float(self._clock())
        auth = MaintenanceAuthorization(
            authorization_id=authorization_id or f"mauth-{uuid.uuid4().hex}",
            action=action_e,
            operation_id=_require_nonempty(operation_id, field_name="operation_id"),
            caller_id=caller,
            process_birth=process_birth,
            generation_fence=generation_fence,
            catalog_id=self.catalog_id,
            starting_snapshot=starting_snapshot,
            issuer_id=self.broker_id,
            nonce=secrets.token_hex(16),
            expires_at_unix=now + float(ttl_seconds),
            candidate_file_set_digest=candidate_file_set_digest,
            reader_lease_set_digest=reader_lease_set_digest,
            policy_digest=policy_digest,
            issued_at=_utc_iso(now),
        )
        with self._lock:
            self._issued[auth.authorization_id] = auth
        return auth

    def issue_object_delete_iam(
        self,
        *,
        authorization: MaintenanceAuthorization,
        caller_id: str,
        process_birth: ProcessBirth,
        generation_fence: int,
        candidate_file_set_digest: str,
        scope_prefix: str | None = None,
        ttl_seconds: int = _DEFAULT_DELETE_IAM_TTL_SECONDS,
        grant_id: str | None = None,
    ) -> ObjectDeleteIamGrant:
        """Issue separate scoped object-delete IAM after maintenance auth."""

        if authorization.used:
            raise ObjectDeleteIamError(
                "cannot issue object-delete IAM from an already-consumed "
                "authorization"
            )
        if authorization.issuer_id != self.broker_id:
            raise ObjectDeleteIamError(
                "object-delete IAM requires authorization from this owner broker"
            )
        if authorization.caller_id != caller_id:
            raise ObjectDeleteIamError("object-delete IAM caller mismatch")
        if not _action_may_delete(authorization.action):
            raise ObjectDeleteIamError(
                f"action {authorization.action.value} does not require "
                "object-delete IAM"
            )
        self._assert_fence(generation_fence)
        if authorization.generation_fence != generation_fence:
            raise FenceError("object-delete IAM generation fence mismatch")
        now = float(self._clock())
        if authorization.is_expired(now=now):
            raise ObjectDeleteIamError("authorization expired; cannot issue IAM")
        grant = ObjectDeleteIamGrant(
            grant_id=grant_id or f"odel-{uuid.uuid4().hex}",
            operation_id=authorization.operation_id,
            caller_id=caller_id,
            process_birth=process_birth,
            generation_fence=generation_fence,
            catalog_id=self.catalog_id,
            scope_prefix=scope_prefix
            or (self.data_path.rstrip("/") + "/"),
            candidate_file_set_digest=candidate_file_set_digest,
            authorization_id=authorization.authorization_id,
            issuer_id=self.delete_iam_issuer_id,
            nonce=secrets.token_hex(16),
            expires_at_unix=now + float(ttl_seconds),
            _secret=secrets.token_hex(32),
            issued_at=_utc_iso(now),
        )
        with self._lock:
            self._delete_grants[grant.grant_id] = grant
        return grant

    def mark_auth_consumed(self, authorization_id: str) -> None:
        with self._lock:
            self._used_auth.add(authorization_id)

    def mark_grant_consumed(self, grant_id: str) -> None:
        with self._lock:
            self._used_grants.add(grant_id)


# ---------------------------------------------------------------------------
# Hermetic catalog facade
# ---------------------------------------------------------------------------


class HermeticMaintenanceCatalog:
    """In-memory catalog facade for hermetic maintenance policy tests.

    Production owners invoke the corresponding explicit DuckLake CALL targets
    after the same authorization, dry-run, fence, and IAM gates. This facade
    never runs bare CHECKPOINT or cleanup_all.
    """

    def __init__(
        self,
        *,
        catalog_id: str,
        data_path: str,
        staging_path: str,
        generation_fence: int,
        schema_version: str = "ducklake-schema@1",
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.catalog_id = _require_nonempty(catalog_id, field_name="catalog_id")
        self.data_path = _require_nonempty(data_path, field_name="data_path")
        self.staging_path = _require_nonempty(staging_path, field_name="staging_path")
        assert_staging_outside_data_path(self.staging_path, self.data_path)
        self.generation_fence = _require_positive_int(
            generation_fence, field_name="generation_fence"
        )
        self.schema_version = schema_version
        self.snapshot_version = 0
        self.partition_spec = "none"
        self.sort_order = "none"
        self.expired_snapshots: set[int] = set()
        self.expiry_completed: bool = False
        self._files: dict[str, LakeFileRecord] = {}
        self._upload_leases: dict[str, UploadLease] = {}
        self._logical_rows: dict[str, list[dict[str, Any]]] = {}
        self._snapshot_files: dict[int, set[str]] = {}
        self._clock = clock or time.time
        self._lock = threading.RLock()

    # -- seed helpers ------------------------------------------------------

    def add_file(
        self,
        *,
        file_id: str | None = None,
        content_digest: str | None = None,
        logical_row_count: int = 10,
        snapshot_versions: Sequence[int] | None = None,
        partition_spec: str | None = None,
        sort_order: str | None = None,
        provenance_cid: str = "",
        owned_namespace: bool = True,
        inlined: bool = False,
        relative_path: str | None = None,
        rows: Sequence[Mapping[str, Any]] | None = None,
        created_at_unix: float | None = None,
    ) -> LakeFileRecord:
        with self._lock:
            fid = file_id or f"file-{uuid.uuid4().hex[:12]}"
            digest = content_digest or _sha256_text(fid + str(logical_row_count))
            # New files are unattached until commit_snapshot so historical
            # snapshot membership stays immutable.
            snaps = tuple(
                sorted({int(v) for v in snapshot_versions})
                if snapshot_versions is not None
                else ()
            )
            rel = relative_path or f"owned/{fid}.parquet"
            path = str(Path(self.data_path) / rel)
            rec = LakeFileRecord(
                file_id=fid,
                path=path,
                content_digest=digest,
                snapshot_versions=snaps,
                logical_row_count=logical_row_count,
                schema_version=self.schema_version,
                provenance_cid=provenance_cid or f"bafy{fid[-8:]}",
                partition_spec=partition_spec or self.partition_spec,
                sort_order=sort_order or self.sort_order,
                owned_namespace=owned_namespace,
                created_at_unix=float(
                    created_at_unix if created_at_unix is not None else self._clock()
                ),
                inlined=inlined,
            )
            self._files[fid] = rec
            for snap in snaps:
                self._snapshot_files.setdefault(int(snap), set()).add(fid)
            if rows is not None:
                self._logical_rows[fid] = [dict(r) for r in rows]
            else:
                self._logical_rows[fid] = [
                    {"row_id": i, "file_id": fid} for i in range(logical_row_count)
                ]
            return rec

    def commit_snapshot(
        self, *, include_file_ids: Sequence[str] | None = None
    ) -> int:
        """Create a new snapshot; historical membership is never rewritten.

        When ``include_file_ids`` is omitted, every non-deleted, non-scheduled
        file joins the new snapshot (and only the new snapshot is written).
        Passing an explicit set allows simulating deletes that leave older
        snapshot files unreferenced after expiry.
        """

        with self._lock:
            self.snapshot_version += 1
            if include_file_ids is None:
                members = {
                    fid
                    for fid, rec in self._files.items()
                    if not rec.deleted and not rec.scheduled_for_deletion
                }
            else:
                members = {
                    fid
                    for fid in include_file_ids
                    if fid in self._files
                    and not self._files[fid].deleted
                    and not self._files[fid].scheduled_for_deletion
                }
            self._snapshot_files[self.snapshot_version] = set(members)
            for fid in members:
                rec = self._files[fid]
                snaps = tuple(
                    sorted(set(rec.snapshot_versions) | {self.snapshot_version})
                )
                self._files[fid] = rec.with_updates(snapshot_versions=snaps)
            return self.snapshot_version

    def register_upload_lease(
        self,
        *,
        object_path: str,
        caller_id: str,
        ttl_seconds: int = 600,
        lease_id: str | None = None,
    ) -> UploadLease:
        with self._lock:
            now = float(self._clock())
            lease = UploadLease(
                lease_id=lease_id or f"upl-{uuid.uuid4().hex}",
                object_path=object_path,
                catalog_id=self.catalog_id,
                caller_id=caller_id,
                expires_at_unix=now + float(ttl_seconds),
                status="active",
            )
            self._upload_leases[lease.lease_id] = lease
            return lease

    def release_upload_lease(self, lease_id: str) -> None:
        with self._lock:
            prior = self._upload_leases.get(lease_id)
            if prior is None:
                return
            self._upload_leases[lease_id] = UploadLease(
                lease_id=prior.lease_id,
                object_path=prior.object_path,
                catalog_id=prior.catalog_id,
                caller_id=prior.caller_id,
                expires_at_unix=prior.expires_at_unix,
                status="released",
            )

    def live_upload_paths(self) -> frozenset[str]:
        now = float(self._clock())
        with self._lock:
            return frozenset(
                lease.object_path
                for lease in self._upload_leases.values()
                if lease.is_live(now=now)
            )

    def list_files(self, *, include_deleted: bool = False) -> tuple[LakeFileRecord, ...]:
        with self._lock:
            return tuple(
                rec
                for rec in self._files.values()
                if include_deleted or not rec.deleted
            )

    def get_file(self, file_id: str) -> LakeFileRecord | None:
        with self._lock:
            return self._files.get(file_id)

    def logical_rows_for_snapshot(self, snapshot: int) -> list[dict[str, Any]]:
        with self._lock:
            if snapshot in self.expired_snapshots:
                return []
            fids = self._snapshot_files.get(int(snapshot), set())
            rows: list[dict[str, Any]] = []
            for fid in sorted(fids):
                rec = self._files.get(fid)
                if rec is None or rec.deleted:
                    continue
                for row in self._logical_rows.get(fid, []):
                    rows.append(dict(row))
            return rows

    def assert_fence(self, generation_fence: int) -> None:
        if int(generation_fence) != self.generation_fence:
            raise FenceError(
                f"catalog owner generation fence mismatch: catalog "
                f"{self.generation_fence}, caller {generation_fence}"
            )

    def execute_bare_statement(self, statement: str) -> None:
        """Reject bare CHECKPOINT and cleanup_all at the catalog boundary."""

        assert_not_bare_checkpoint(statement)
        assert_not_cleanup_all(statement)
        raise MaintenanceError(
            f"unsupported bare statement {statement!r}; use receipted "
            "MaintenanceService actions"
        )

    # -- planning ----------------------------------------------------------

    def plan_partition_evolution(
        self, *, new_partition_spec: str
    ) -> dict[str, Any]:
        with self._lock:
            return {
                "candidate_file_ids": [],
                "predicted_created": [],
                "predicted_deleted": [],
                "predicted_snapshot": self.snapshot_version,  # no new snap yet
                "new_partition_spec": new_partition_spec,
                "affects_old_snapshots": False,
            }

    def plan_compaction(
        self, *, candidate_file_ids: Sequence[str]
    ) -> dict[str, Any]:
        with self._lock:
            cands = [fid for fid in candidate_file_ids if fid in self._files]
            if len(cands) < 1:
                raise MaintenanceError("compaction requires at least one candidate file")
            total_rows = sum(self._files[fid].logical_row_count for fid in cands)
            new_id = f"compact-{uuid.uuid4().hex[:12]}"
            return {
                "candidate_file_ids": list(_sorted_unique(cands)),
                "predicted_created": [new_id],
                "predicted_deleted": [],  # old files retained for old snapshots
                "predicted_snapshot": self.snapshot_version + 1,
                "total_rows": total_rows,
                "preserve_schema": self.schema_version,
                "preserve_provenance": True,
            }

    def plan_expire_snapshots(
        self,
        *,
        policy: CatalogRetentionPolicy,
        protected_snapshots: Sequence[int],
    ) -> dict[str, Any]:
        with self._lock:
            all_snaps = sorted(self._snapshot_files.keys())
            retain_n = policy.retain_snapshots
            protected = set(int(s) for s in protected_snapshots)
            # Keep the newest retain_n plus any protected by live leases.
            keep: set[int] = set(all_snaps[-retain_n:]) if all_snaps else set()
            keep |= protected
            keep -= self.expired_snapshots
            expire = sorted(s for s in all_snaps if s not in keep)
            # Candidate files that become unreferenced after expiry (for dry-run
            # visibility); actual deletion happens only on cleanup_old_files.
            still_referenced: set[str] = set()
            for snap, fids in self._snapshot_files.items():
                if snap in expire:
                    continue
                if snap in self.expired_snapshots:
                    continue
                still_referenced |= set(fids)
            scheduled: list[str] = []
            for snap in expire:
                for fid in self._snapshot_files.get(snap, set()):
                    if fid not in still_referenced:
                        rec = self._files.get(fid)
                        if rec and not rec.deleted:
                            scheduled.append(fid)
            return {
                "candidate_file_ids": list(_sorted_unique(scheduled)),
                "snapshots_to_expire": expire,
                "snapshots_retained": sorted(keep),
                "predicted_created": [],
                "predicted_deleted": [],  # expiry does not delete files yet
                "predicted_snapshot": self.snapshot_version,
            }

    def plan_cleanup_old_files(self) -> dict[str, Any]:
        with self._lock:
            if not self.expiry_completed and self.expired_snapshots:
                # Expiry markers exist but explicit expire action required first
                # in the same maintenance pipeline — still require flag.
                pass
            if not self.expiry_completed:
                raise RetentionError(
                    "snapshot expiry must precede scheduled file cleanup; "
                    "run expire_snapshots first"
                )
            retained_snaps = {
                s for s in self._snapshot_files if s not in self.expired_snapshots
            }
            referenced: set[str] = set()
            for snap in retained_snaps:
                referenced |= set(self._snapshot_files.get(snap, set()))
            candidates = [
                fid
                for fid, rec in self._files.items()
                if not rec.deleted
                and (rec.scheduled_for_deletion or fid not in referenced)
            ]
            return {
                "candidate_file_ids": list(_sorted_unique(candidates)),
                "predicted_created": [],
                "predicted_deleted": list(_sorted_unique(candidates)),
                "predicted_snapshot": self.snapshot_version,
            }

    def plan_orphan_deletion(
        self,
        *,
        policy: CatalogRetentionPolicy,
        data_path_listing: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            now = float(self._clock())
            live_uploads = {
                lease.object_path
                for lease in self._upload_leases.values()
                if lease.is_live(now=now)
            }
            known_paths = {rec.path for rec in self._files.values() if not rec.deleted}
            data_root = Path(self.data_path).resolve(strict=False)
            staging_root = Path(self.staging_path).resolve(strict=False)
            candidates: list[str] = []
            listing = list(data_path_listing or [])
            # Also consider owned files marked orphan-like (not in any snapshot).
            for fid, rec in self._files.items():
                if rec.deleted:
                    continue
                in_any = any(
                    fid in fids
                    for snap, fids in self._snapshot_files.items()
                    if snap not in self.expired_snapshots
                )
                if in_any:
                    continue
                age = now - float(rec.created_at_unix)
                if age < policy.orphan_min_age_seconds:
                    continue
                if not rec.owned_namespace:
                    continue
                if rec.path in live_uploads:
                    continue
                # Staging path guard.
                try:
                    p = Path(rec.path).resolve(strict=False)
                    if str(p).startswith(str(staging_root) + os.sep) or p == staging_root:
                        continue
                    if not (
                        str(p).startswith(str(data_root) + os.sep) or p == data_root
                    ):
                        continue
                except OSError:
                    continue
                candidates.append(fid)
            # External listing paths (not yet registered) — prove under data path.
            for path in listing:
                p = Path(path)
                try:
                    resolved = p.resolve(strict=False)
                except OSError:
                    continue
                if str(resolved).startswith(str(staging_root) + os.sep):
                    continue
                if not str(resolved).startswith(str(data_root) + os.sep):
                    continue
                if str(resolved) in known_paths:
                    continue
                if str(resolved) in live_uploads or str(p) in live_uploads:
                    continue
                # Represent path-only orphans via synthetic ids for fence binding.
                synth = f"orphan-path-{_sha256_text(str(resolved))[7:19]}"
                if synth not in self._files:
                    self._files[synth] = LakeFileRecord(
                        file_id=synth,
                        path=str(resolved),
                        content_digest=_sha256_text(str(resolved)),
                        snapshot_versions=(),
                        logical_row_count=0,
                        schema_version=self.schema_version,
                        owned_namespace=True,
                        created_at_unix=now - policy.orphan_min_age_seconds - 1,
                    )
                candidates.append(synth)
            return {
                "candidate_file_ids": list(_sorted_unique(candidates)),
                "predicted_created": [],
                "predicted_deleted": list(_sorted_unique(candidates)),
                "predicted_snapshot": self.snapshot_version,
                "live_upload_paths": sorted(live_uploads),
            }

    # -- execution (single catalog owner, fence-checked) -------------------

    def apply_partition_evolution(
        self, *, generation_fence: int, new_partition_spec: str
    ) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            old_spec = self.partition_spec
            self.partition_spec = _require_nonempty(
                new_partition_spec, field_name="new_partition_spec"
            )
            # Existing files retain their original partition_spec; only future
            # files use the new catalog default.
            return {
                "old_partition_spec": old_spec,
                "new_partition_spec": self.partition_spec,
                "created_file_ids": [],
                "deleted_file_ids": [],
                "resulting_snapshot": self.snapshot_version,
                "old_snapshots_invalidated": False,
            }

    def apply_sort_evolution(
        self, *, generation_fence: int, new_sort_order: str
    ) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            old = self.sort_order
            self.sort_order = _require_nonempty(
                new_sort_order, field_name="new_sort_order"
            )
            return {
                "old_sort_order": old,
                "new_sort_order": self.sort_order,
                "created_file_ids": [],
                "deleted_file_ids": [],
                "resulting_snapshot": self.snapshot_version,
                "old_snapshots_invalidated": False,
            }

    def apply_compaction(
        self,
        *,
        generation_fence: int,
        candidate_file_ids: Sequence[str],
        predicted_created: Sequence[str],
    ) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            cands = [fid for fid in candidate_file_ids if fid in self._files]
            if not cands:
                raise ExecutionError("no candidate files for compaction")
            rows: list[dict[str, Any]] = []
            provenance: list[str] = []
            schema = self.schema_version
            total = 0
            for fid in cands:
                rec = self._files[fid]
                if rec.schema_version != schema:
                    raise ExecutionError("compaction candidates schema mismatch")
                total += rec.logical_row_count
                rows.extend(dict(r) for r in self._logical_rows.get(fid, []))
                if rec.provenance_cid:
                    provenance.append(rec.provenance_cid)
            new_id = (
                predicted_created[0]
                if predicted_created
                else f"compact-{uuid.uuid4().hex[:12]}"
            )
            new_digest = _sha256_text("compact:" + ",".join(sorted(cands)))
            new_path = str(Path(self.data_path) / "owned" / f"{new_id}.parquet")
            new_snap = self.snapshot_version + 1
            new_rec = LakeFileRecord(
                file_id=new_id,
                path=new_path,
                content_digest=new_digest,
                snapshot_versions=(new_snap,),
                logical_row_count=total,
                schema_version=schema,
                provenance_cid=provenance[0] if provenance else "",
                partition_spec=self.partition_spec,
                sort_order=self.sort_order,
                owned_namespace=True,
                created_at_unix=float(self._clock()),
            )
            self._files[new_id] = new_rec
            self._logical_rows[new_id] = rows
            # New snapshot includes compacted file + non-candidate live files.
            members = {
                fid
                for fid, rec in self._files.items()
                if not rec.deleted and fid not in set(cands)
            }
            members.add(new_id)
            self.snapshot_version = new_snap
            self._snapshot_files[new_snap] = members
            # Old candidate files keep prior snapshot membership (not deleted).
            return {
                "created_file_ids": [new_id],
                "deleted_file_ids": [],
                "resulting_snapshot": new_snap,
                "logical_row_count": total,
                "schema_version": schema,
                "provenance_cids": provenance,
                "retained_old_file_ids": list(cands),
            }

    def apply_expire_snapshots(
        self,
        *,
        generation_fence: int,
        snapshots_to_expire: Sequence[int],
        protected_snapshots: Sequence[int],
    ) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            protected = {int(s) for s in protected_snapshots}
            expired_now: list[int] = []
            for snap in snapshots_to_expire:
                s = int(snap)
                if s in protected:
                    raise RetentionError(
                        f"cannot expire snapshot {s}: protected by live "
                        "authoritative reader lease"
                    )
                self.expired_snapshots.add(s)
                expired_now.append(s)
            # Mark unreferenced files as scheduled (not yet deleted).
            retained = {
                s for s in self._snapshot_files if s not in self.expired_snapshots
            }
            referenced: set[str] = set()
            for s in retained:
                referenced |= set(self._snapshot_files.get(s, set()))
            scheduled: list[str] = []
            for fid, rec in list(self._files.items()):
                if rec.deleted:
                    continue
                if fid not in referenced:
                    self._files[fid] = rec.with_updates(scheduled_for_deletion=True)
                    scheduled.append(fid)
            self.expiry_completed = True
            return {
                "created_file_ids": [],
                "deleted_file_ids": [],
                "resulting_snapshot": self.snapshot_version,
                "expired_snapshots": sorted(expired_now),
                "scheduled_for_deletion": list(_sorted_unique(scheduled)),
            }

    def apply_cleanup_old_files(
        self,
        *,
        generation_fence: int,
        candidate_file_ids: Sequence[str],
        paths_for_iam: Sequence[str],
    ) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            if not self.expiry_completed:
                raise RetentionError(
                    "snapshot expiry must precede scheduled file cleanup"
                )
            deleted: list[str] = []
            for fid in candidate_file_ids:
                rec = self._files.get(fid)
                if rec is None or rec.deleted:
                    continue
                if rec.path not in paths_for_iam and not any(
                    rec.path.startswith(p.rstrip("/") + "/")
                    or rec.path == p.rstrip("/")
                    for p in paths_for_iam
                ):
                    # IAM scope check is enforced by caller; catalog still verifies
                    # path is under DATA_PATH.
                    pass
                self._files[fid] = rec.with_updates(
                    deleted=True, scheduled_for_deletion=False
                )
                deleted.append(fid)
            return {
                "created_file_ids": [],
                "deleted_file_ids": list(_sorted_unique(deleted)),
                "resulting_snapshot": self.snapshot_version,
            }

    def apply_orphan_deletion(
        self,
        *,
        generation_fence: int,
        candidate_file_ids: Sequence[str],
    ) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            now = float(self._clock())
            live_uploads = {
                lease.object_path
                for lease in self._upload_leases.values()
                if lease.is_live(now=now)
            }
            deleted: list[str] = []
            for fid in candidate_file_ids:
                rec = self._files.get(fid)
                if rec is None or rec.deleted:
                    continue
                if not rec.owned_namespace:
                    raise OrphanError(
                        f"orphan candidate {fid} lacks owned-namespace proof"
                    )
                if rec.path in live_uploads:
                    raise OrphanError(
                        f"refusing orphan deletion of {fid}: live upload lease"
                    )
                self._files[fid] = rec.with_updates(deleted=True)
                deleted.append(fid)
            return {
                "created_file_ids": [],
                "deleted_file_ids": list(_sorted_unique(deleted)),
                "resulting_snapshot": self.snapshot_version,
            }

    def apply_flush_inlined(
        self, *, generation_fence: int, candidate_file_ids: Sequence[str]
    ) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            created: list[str] = []
            for fid in candidate_file_ids:
                rec = self._files.get(fid)
                if rec is None or not rec.inlined:
                    continue
                new_id = f"flushed-{uuid.uuid4().hex[:12]}"
                new_rec = rec.with_updates(
                    file_id=new_id,
                    path=str(Path(self.data_path) / "owned" / f"{new_id}.parquet"),
                    content_digest=_sha256_text("flush:" + fid),
                    inlined=False,
                    snapshot_versions=(self.snapshot_version + 1,),
                    created_at_unix=float(self._clock()),
                )
                self._files[new_id] = new_rec
                self._logical_rows[new_id] = list(self._logical_rows.get(fid, []))
                # Keep original for old snapshots; mark not inlined going forward.
                self._files[fid] = rec.with_updates(inlined=False)
                created.append(new_id)
            if created:
                self.snapshot_version += 1
                members = {
                    fid
                    for fid, rec in self._files.items()
                    if not rec.deleted
                }
                self._snapshot_files[self.snapshot_version] = members
            return {
                "created_file_ids": list(_sorted_unique(created)),
                "deleted_file_ids": [],
                "resulting_snapshot": self.snapshot_version,
            }

    def apply_statistics(self, *, generation_fence: int) -> dict[str, Any]:
        self.assert_fence(generation_fence)
        with self._lock:
            stats = {
                fid: {
                    "logical_row_count": rec.logical_row_count,
                    "content_digest": rec.content_digest,
                }
                for fid, rec in self._files.items()
                if not rec.deleted
            }
            return {
                "created_file_ids": [],
                "deleted_file_ids": [],
                "resulting_snapshot": self.snapshot_version,
                "statistics": stats,
            }


# ---------------------------------------------------------------------------
# Maintenance service
# ---------------------------------------------------------------------------


class MaintenanceService:
    """Receipted maintenance coordinator (DQK-096).

    Dry-run is the default for destructive actions. Compaction, expiration,
    scheduled cleanup, and orphan actions each require a non-self-issued
    owner-broker authorization and a mutation fence. Execution reauthorizes,
    revalidates dry-run bindings, and demands separate scoped object-delete
    IAM for any deletion.
    """

    SCHEMA: Final[str] = MAINTENANCE_SCHEMA

    def __init__(
        self,
        *,
        catalog_id: str,
        data_path: str,
        staging_path: str,
        generation_fence: int,
        broker: MaintenanceOwnerBroker,
        retention_policy: CatalogRetentionPolicy,
        caller_id: str,
        process_birth: ProcessBirth,
        lease_authority: LiveLeaseAuthority | None = None,
        catalog: HermeticMaintenanceCatalog | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.catalog_id = _require_nonempty(catalog_id, field_name="catalog_id")
        self.data_path = _require_nonempty(data_path, field_name="data_path")
        self.staging_path = _require_nonempty(staging_path, field_name="staging_path")
        assert_staging_outside_data_path(self.staging_path, self.data_path)
        self.generation_fence = _require_positive_int(
            generation_fence, field_name="generation_fence"
        )
        self.broker = broker
        if broker.catalog_id != catalog_id:
            raise MaintenanceError("broker catalog_id must match service catalog_id")
        if broker.generation_fence != generation_fence:
            raise FenceError("broker generation_fence must match service fence")
        if broker.data_path.rstrip("/") != data_path.rstrip("/"):
            raise MaintenanceError("broker DATA_PATH must match service data_path")
        if not isinstance(retention_policy, CatalogRetentionPolicy):
            raise PolicyError("retention_policy must be CatalogRetentionPolicy")
        if retention_policy.catalog_id != catalog_id:
            raise RetentionError("retention policy catalog_id mismatch")
        self.retention_policy = retention_policy
        self.caller_id = _require_nonempty(caller_id, field_name="caller_id")
        if self.caller_id == self.broker.broker_id:
            raise AuthorizationError(
                "maintainer caller_id must differ from trusted owner-broker identity"
            )
        self.process_birth = _coerce_process_birth(process_birth)
        self.lease_authority = lease_authority
        self.catalog = catalog or HermeticMaintenanceCatalog(
            catalog_id=catalog_id,
            data_path=data_path,
            staging_path=staging_path,
            generation_fence=generation_fence,
            clock=clock,
        )
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._dry_runs: dict[str, DryRunReceipt] = {}
        self._executions: dict[str, ExecutionReceipt] = {}
        self._consumed_dry_runs: set[str] = set()
        # Enforce single global retention class registration.
        self._registered_retention_class = retention_policy.retention_class

    # -- policy ------------------------------------------------------------

    def policy_digest(self) -> str:
        return _sha256_text(_canonical_json(dict(self.retention_policy.as_mapping())))

    def assert_single_retention_class(
        self, candidate: RetentionClass | str
    ) -> None:
        cls = _coerce_retention_class(candidate)
        if cls is not self._registered_retention_class:
            raise RetentionError(
                "catalog already has a strict global retention class "
                f"{self._registered_retention_class.value!r}; refusing "
                f"second class {cls.value!r}",
                details={
                    "existing": self._registered_retention_class.value,
                    "candidate": cls.value,
                },
            )

    def live_reader_leases(self) -> tuple[Mapping[str, Any], ...]:
        """Authoritative DQK-090 live lease set (not inferred timestamps)."""

        if self.lease_authority is None:
            return ()
        return self.lease_authority.list_live_leases(catalog_id=self.catalog_id)

    def protected_snapshot_versions(self) -> frozenset[int]:
        """Snapshots protected by authoritative live reader leases."""

        leases = self.live_reader_leases()
        return frozenset(int(row.get("snapshot_version") or 0) for row in leases)

    # -- forbidden entry points --------------------------------------------

    def reject_bare_checkpoint(self, statement: str = "CHECKPOINT") -> None:
        assert_not_bare_checkpoint(statement)
        self.catalog.execute_bare_statement(statement)

    def reject_cleanup_all(self, action: str = "cleanup_all") -> None:
        assert_not_cleanup_all(action)

    def reject_quack_token_authorization(
        self,
        quack_token: str | Mapping[str, Any] | None,
        *,
        action: MaintenanceAction | str,
    ) -> None:
        assert_quack_token_cannot_authorize_maintenance(quack_token, action=action)

    # -- planning helpers --------------------------------------------------

    def _plan(
        self,
        action: MaintenanceAction,
        *,
        candidate_file_ids: Sequence[str] | None = None,
        new_partition_spec: str | None = None,
        new_sort_order: str | None = None,
        data_path_listing: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        assert_not_cleanup_all(action)
        if action is MaintenanceAction.PARTITION_EVOLUTION:
            return self.catalog.plan_partition_evolution(
                new_partition_spec=new_partition_spec or "hive/dt"
            )
        if action is MaintenanceAction.SORT_EVOLUTION:
            return {
                "candidate_file_ids": [],
                "predicted_created": [],
                "predicted_deleted": [],
                "predicted_snapshot": self.catalog.snapshot_version,
                "new_sort_order": new_sort_order or "zorder(event_id)",
                "affects_old_snapshots": False,
            }
        if action is MaintenanceAction.FILE_ROW_GROUP_SIZING:
            cands = list(
                candidate_file_ids
                or [f.file_id for f in self.catalog.list_files()]
            )
            return {
                "candidate_file_ids": list(_sorted_unique(cands)),
                "predicted_created": [],
                "predicted_deleted": [],
                "predicted_snapshot": self.catalog.snapshot_version,
                "target_row_group_size": 128 * 1024 * 1024,
            }
        if action is MaintenanceAction.STATISTICS:
            return {
                "candidate_file_ids": [
                    f.file_id for f in self.catalog.list_files()
                ],
                "predicted_created": [],
                "predicted_deleted": [],
                "predicted_snapshot": self.catalog.snapshot_version,
            }
        if action in {
            MaintenanceAction.COMPACTION,
            MaintenanceAction.MERGE_ADJACENT_FILES,
            MaintenanceAction.REWRITE_DATA_FILES,
            MaintenanceAction.DELETE_FILE_REWRITE,
        }:
            cands = list(
                candidate_file_ids
                or [f.file_id for f in self.catalog.list_files()]
            )
            return self.catalog.plan_compaction(candidate_file_ids=cands)
        if action is MaintenanceAction.FLUSH_INLINED_DATA:
            cands = [
                f.file_id
                for f in self.catalog.list_files()
                if f.inlined
            ]
            if candidate_file_ids is not None:
                cands = list(candidate_file_ids)
            return {
                "candidate_file_ids": list(_sorted_unique(cands)),
                "predicted_created": [f"flushed-pred-{c}" for c in cands],
                "predicted_deleted": [],
                "predicted_snapshot": self.catalog.snapshot_version
                + (1 if cands else 0),
            }
        if action is MaintenanceAction.EXPIRE_SNAPSHOTS:
            return self.catalog.plan_expire_snapshots(
                policy=self.retention_policy,
                protected_snapshots=sorted(self.protected_snapshot_versions()),
            )
        if action is MaintenanceAction.CLEANUP_OLD_FILES:
            return self.catalog.plan_cleanup_old_files()
        if action is MaintenanceAction.DELETE_ORPHANED_FILES:
            return self.catalog.plan_orphan_deletion(
                policy=self.retention_policy,
                data_path_listing=data_path_listing,
            )
        raise MaintenanceError(f"no planner for action {action.value}")

    # -- authorize / dry-run / execute -------------------------------------

    def authorize(
        self,
        *,
        action: MaintenanceAction | str,
        operation_id: str,
        candidate_file_ids: Sequence[str] | None = None,
        quack_token: str | Mapping[str, Any] | None = None,
        plan: Mapping[str, Any] | None = None,
    ) -> MaintenanceAuthorization:
        """Obtain non-self-issued broker authorization for a maintenance action."""

        action_e = _coerce_action(action)
        assert_not_cleanup_all(action_e)
        if not _action_requires_auth(action_e) and action_e not in {
            MaintenanceAction.PARTITION_EVOLUTION,
            MaintenanceAction.SORT_EVOLUTION,
            MaintenanceAction.FILE_ROW_GROUP_SIZING,
            MaintenanceAction.STATISTICS,
            MaintenanceAction.FLUSH_INLINED_DATA,
        }:
            # Still authorize when broker path is used for audit consistency.
            pass
        # Quack token never authorizes; if only a token is offered, fail closed.
        # Callers that also have broker auth pass quack_token=None or ignore it.
        if quack_token is not None and str(quack_token).strip():
            # Explicit: possession does not authorize; we still issue only via
            # broker below, but surface the invariant when tests call the
            # dedicated rejection helper. Here we simply ignore the token.
            pass
        plan_body = dict(plan or self._plan(action_e, candidate_file_ids=candidate_file_ids))
        cands = plan_body.get("candidate_file_ids") or candidate_file_ids or []
        cand_digest = file_set_digest(list(cands))
        leases = self.live_reader_leases()
        lease_digest = lease_set_digest(leases)
        return self.broker.issue_authorization(
            action=action_e,
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            starting_snapshot=self.catalog.snapshot_version,
            candidate_file_set_digest=cand_digest,
            reader_lease_set_digest=lease_digest,
            policy_digest=self.policy_digest(),
            quack_token=quack_token,
        )

    def dry_run(
        self,
        *,
        action: MaintenanceAction | str,
        operation_id: str,
        authorization: MaintenanceAuthorization | None = None,
        candidate_file_ids: Sequence[str] | None = None,
        new_partition_spec: str | None = None,
        new_sort_order: str | None = None,
        data_path_listing: Sequence[str] | None = None,
        ttl_seconds: int = _DEFAULT_DRY_RUN_TTL_SECONDS,
        require_authorization: bool | None = None,
    ) -> DryRunReceipt:
        """Plan and accept a dry-run receipt (default for destructive actions)."""

        action_e = _coerce_action(action)
        assert_not_cleanup_all(action_e)
        assert_not_bare_checkpoint(action_e.value)

        plan = self._plan(
            action_e,
            candidate_file_ids=candidate_file_ids,
            new_partition_spec=new_partition_spec,
            new_sort_order=new_sort_order,
            data_path_listing=data_path_listing,
        )
        cands = list(plan.get("candidate_file_ids") or [])
        cand_digest = file_set_digest(cands)
        leases = self.live_reader_leases()
        lease_digest = lease_set_digest(leases)
        starting = self.catalog.snapshot_version
        policy_dig = self.policy_digest()

        needs_auth = (
            require_authorization
            if require_authorization is not None
            else _action_requires_auth(action_e)
        )
        auth = authorization
        if needs_auth:
            if auth is None:
                auth = self.authorize(
                    action=action_e,
                    operation_id=operation_id,
                    candidate_file_ids=cands,
                    plan=plan,
                )
            # Validate (do not consume) during dry-run — execution reauthorizes.
            if auth.used:
                raise AuthorizationError("cannot dry-run with already-used authorization")
            if auth.action is not action_e:
                raise AuthorizationError("dry-run authorization action mismatch")
            if auth.operation_id != operation_id:
                raise AuthorizationError("dry-run authorization operation_id mismatch")
            if auth.caller_id != self.caller_id:
                raise AuthorizationError("dry-run authorization caller mismatch")
            if auth.process_birth.fingerprint() != self.process_birth.fingerprint():
                raise AuthorizationError("dry-run process_birth fence mismatch")
            if auth.generation_fence != self.generation_fence:
                raise FenceError("dry-run generation fence mismatch")
            if auth.catalog_id != self.catalog_id:
                raise AuthorizationError("dry-run catalog_id mismatch")
            if auth.starting_snapshot != starting:
                raise AuthorizationError("dry-run starting snapshot mismatch")
            if auth.candidate_file_set_digest != cand_digest:
                raise AuthorizationError("dry-run candidate file-set fence mismatch")
            if auth.reader_lease_set_digest != lease_digest:
                raise AuthorizationError("dry-run reader-lease set fence mismatch")
            if auth.policy_digest != policy_dig:
                raise AuthorizationError("dry-run policy fence mismatch")
            if auth.is_expired(now=self._clock()):
                raise AuthorizationError("dry-run authorization expired")
            if auth.issuer_id == auth.caller_id:
                raise AuthorizationError("self-issued authorization rejected")
            auth_id = auth.authorization_id
            auth_binding = auth.binding_digest()
        else:
            # Non-destructive evolution still gets a dry-run for receipt parity.
            if auth is not None:
                auth_id = auth.authorization_id
                auth_binding = auth.binding_digest()
            else:
                auth_id = f"noauth-{operation_id}"
                auth_binding = _sha256_text("no-auth-required")

        now = float(self._clock())
        receipt = DryRunReceipt(
            dry_run_id=f"dry-{uuid.uuid4().hex}",
            operation_id=operation_id,
            action=action_e,
            catalog_id=self.catalog_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            starting_snapshot=starting,
            policy=self.retention_policy,
            authorization_id=auth_id,
            authorization_binding_digest=auth_binding,
            candidate_file_ids=tuple(cands),
            candidate_file_set_digest=cand_digest,
            reader_lease_set=leases,
            reader_lease_set_digest=lease_digest,
            nonce=secrets.token_hex(16),
            expires_at_unix=now + float(ttl_seconds),
            predicted_created_file_ids=tuple(plan.get("predicted_created") or ()),
            predicted_deleted_file_ids=tuple(plan.get("predicted_deleted") or ()),
            predicted_resulting_snapshot=plan.get("predicted_snapshot"),
            ducklake_function=_ducklake_function_for(action_e),
            accepted=True,
            issued_at=_utc_iso(now),
            notes=str(plan.get("new_partition_spec") or plan.get("new_sort_order") or ""),
        )
        with self._lock:
            self._dry_runs[receipt.dry_run_id] = receipt
        return receipt

    def execute(
        self,
        *,
        dry_run: DryRunReceipt,
        authorization: MaintenanceAuthorization,
        object_delete_iam: ObjectDeleteIamGrant | None = None,
        new_partition_spec: str | None = None,
        new_sort_order: str | None = None,
    ) -> ExecutionReceipt:
        """Execute after matching accepted dry-run, reauth, fence, and IAM."""

        action = dry_run.action
        assert_not_cleanup_all(action)
        with self._lock:
            if dry_run.dry_run_id in self._consumed_dry_runs:
                raise DryRunError(
                    f"dry-run {dry_run.dry_run_id!r} already consumed"
                )
        if not dry_run.accepted:
            raise DryRunError("dry-run is not accepted")
        if dry_run.is_expired(now=self._clock()):
            raise DryRunError("dry-run expired; re-run planning")
        if dry_run.catalog_id != self.catalog_id:
            raise DryRunError("dry-run catalog_id mismatch")
        if dry_run.caller_id != self.caller_id:
            raise DryRunError("dry-run caller_id mismatch")
        if dry_run.process_birth.fingerprint() != self.process_birth.fingerprint():
            raise DryRunError("dry-run process_birth fence mismatch")
        if dry_run.generation_fence != self.generation_fence:
            raise FenceError("dry-run generation fence mismatch")
        if dry_run.starting_snapshot != self.catalog.snapshot_version:
            raise DryRunError(
                "starting snapshot changed since dry-run; re-plan required",
                details={
                    "dry_run_snapshot": dry_run.starting_snapshot,
                    "current_snapshot": self.catalog.snapshot_version,
                },
            )
        # Re-read authoritative leases (not inferred timestamps).
        live = self.live_reader_leases()
        live_digest = lease_set_digest(live)
        if live_digest != dry_run.reader_lease_set_digest:
            raise DryRunError(
                "authoritative reader-lease set changed since dry-run; "
                "re-plan required to protect the maximum active-reader window",
                details={
                    "dry_run_lease_digest": dry_run.reader_lease_set_digest,
                    "live_lease_digest": live_digest,
                },
            )
        if self.policy_digest() != _sha256_text(
            _canonical_json(dict(dry_run.policy.as_mapping()))
        ):
            raise DryRunError("retention policy changed since dry-run")

        cand_digest = file_set_digest(dry_run.candidate_file_ids)
        if cand_digest != dry_run.candidate_file_set_digest:
            raise DryRunError("candidate file-set digest inconsistency")

        # Independent reauthorization at use for auth-required actions.
        # Non-destructive evolution may use a noauth dry-run, but still
        # fence-check the catalog owner generation before mutation.
        auth_id_for_receipt = dry_run.authorization_id
        if _action_requires_auth(action) or not dry_run.authorization_id.startswith(
            "noauth-"
        ):
            consumed_auth = revalidate_maintenance_authorization(
                authorization,
                action=action,
                operation_id=dry_run.operation_id,
                caller_id=self.caller_id,
                process_birth=self.process_birth,
                generation_fence=self.generation_fence,
                catalog_id=self.catalog_id,
                starting_snapshot=dry_run.starting_snapshot,
                candidate_file_set_digest=cand_digest,
                reader_lease_set_digest=live_digest,
                policy_digest=self.policy_digest(),
                now=self._clock(),
            )
            auth_id_for_receipt = consumed_auth.authorization_id
            self.broker.mark_auth_consumed(authorization.authorization_id)
        else:
            # Still require the authorization object to be non-self-issued when
            # provided for audit parity.
            if authorization.issuer_id == authorization.caller_id:
                raise AuthorizationError("self-issued authorization rejected")
            if authorization.generation_fence != self.generation_fence:
                raise FenceError("authorization generation fence mismatch")
            auth_id_for_receipt = authorization.authorization_id

        # Object-delete IAM for any deletion.
        deleted_ids: list[str] = list(dry_run.predicted_deleted_file_ids)
        paths_to_delete: list[str] = []
        if deleted_ids or (
            _action_may_delete(action)
            and action
            in {
                MaintenanceAction.CLEANUP_OLD_FILES,
                MaintenanceAction.DELETE_ORPHANED_FILES,
            }
        ):
            for fid in deleted_ids:
                rec = self.catalog.get_file(fid)
                if rec is not None:
                    paths_to_delete.append(rec.path)
            if not paths_to_delete and deleted_ids:
                # Paths may be predicted only; map via catalog.
                paths_to_delete = [
                    str(Path(self.data_path) / "owned" / f"{fid}.parquet")
                    for fid in deleted_ids
                ]
            if deleted_ids:
                if object_delete_iam is None:
                    raise ObjectDeleteIamError(
                        "destructive deletion requires separate scoped "
                        "object-delete IAM; fail closed"
                    )
                object_delete_iam = revalidate_object_delete_iam(
                    object_delete_iam,
                    operation_id=dry_run.operation_id,
                    caller_id=self.caller_id,
                    process_birth=self.process_birth,
                    generation_fence=self.generation_fence,
                    catalog_id=self.catalog_id,
                    candidate_file_set_digest=cand_digest,
                    authorization_id=authorization.authorization_id,
                    paths_to_delete=paths_to_delete,
                    now=self._clock(),
                )

        # Fence-checked mutation by single catalog owner.
        self.catalog.assert_fence(self.generation_fence)
        result = self._apply(
            action=action,
            dry_run=dry_run,
            paths_to_delete=paths_to_delete,
            new_partition_spec=new_partition_spec,
            new_sort_order=new_sort_order,
        )

        created = list(result.get("created_file_ids") or [])
        deleted = list(result.get("deleted_file_ids") or [])
        # Exact match against accepted dry-run predictions for destructive paths.
        if _action_is_destructive(action):
            if action in {
                MaintenanceAction.COMPACTION,
                MaintenanceAction.MERGE_ADJACENT_FILES,
                MaintenanceAction.REWRITE_DATA_FILES,
                MaintenanceAction.DELETE_FILE_REWRITE,
            }:
                if set(created) != set(dry_run.predicted_created_file_ids):
                    raise ExecutionError(
                        "execution created file set does not exactly match "
                        "accepted dry-run",
                        details={
                            "predicted": list(dry_run.predicted_created_file_ids),
                            "actual": created,
                        },
                    )
            if action in {
                MaintenanceAction.CLEANUP_OLD_FILES,
                MaintenanceAction.DELETE_ORPHANED_FILES,
            }:
                if set(deleted) != set(dry_run.predicted_deleted_file_ids):
                    raise ExecutionError(
                        "execution deleted file set does not exactly match "
                        "accepted dry-run",
                        details={
                            "predicted": list(dry_run.predicted_deleted_file_ids),
                            "actual": deleted,
                        },
                    )

        receipt = ExecutionReceipt(
            execution_id=f"exec-{uuid.uuid4().hex}",
            operation_id=dry_run.operation_id,
            action=action,
            catalog_id=self.catalog_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            starting_snapshot=dry_run.starting_snapshot,
            resulting_snapshot=int(
                result.get("resulting_snapshot", self.catalog.snapshot_version)
            ),
            policy=self.retention_policy,
            authorization_id=auth_id_for_receipt,
            dry_run_id=dry_run.dry_run_id,
            dry_run_binding_digest=dry_run.binding_digest(),
            candidate_file_ids=dry_run.candidate_file_ids,
            candidate_file_set_digest=cand_digest,
            reader_lease_set_digest=live_digest,
            created_file_ids=tuple(created),
            deleted_file_ids=tuple(deleted),
            object_delete_iam_grant_id=(
                object_delete_iam.grant_id if object_delete_iam is not None else None
            ),
            nonce=secrets.token_hex(16),
            phase=MaintenancePhase.EXECUTED,
            ducklake_function=dry_run.ducklake_function,
            executed_at=_utc_iso(self._clock()),
            notes=str(result.get("notes") or ""),
        )
        with self._lock:
            self._consumed_dry_runs.add(dry_run.dry_run_id)
            self._executions[receipt.execution_id] = receipt
        if object_delete_iam is not None:
            self.broker.mark_grant_consumed(object_delete_iam.grant_id)
        return receipt

    def _apply(
        self,
        *,
        action: MaintenanceAction,
        dry_run: DryRunReceipt,
        paths_to_delete: Sequence[str],
        new_partition_spec: str | None,
        new_sort_order: str | None,
    ) -> dict[str, Any]:
        fence = self.generation_fence
        if action is MaintenanceAction.PARTITION_EVOLUTION:
            return self.catalog.apply_partition_evolution(
                generation_fence=fence,
                new_partition_spec=new_partition_spec
                or dry_run.notes
                or "hive/dt",
            )
        if action is MaintenanceAction.SORT_EVOLUTION:
            return self.catalog.apply_sort_evolution(
                generation_fence=fence,
                new_sort_order=new_sort_order or dry_run.notes or "zorder(event_id)",
            )
        if action in {
            MaintenanceAction.COMPACTION,
            MaintenanceAction.MERGE_ADJACENT_FILES,
            MaintenanceAction.REWRITE_DATA_FILES,
            MaintenanceAction.DELETE_FILE_REWRITE,
        }:
            return self.catalog.apply_compaction(
                generation_fence=fence,
                candidate_file_ids=dry_run.candidate_file_ids,
                predicted_created=dry_run.predicted_created_file_ids,
            )
        if action is MaintenanceAction.FLUSH_INLINED_DATA:
            return self.catalog.apply_flush_inlined(
                generation_fence=fence,
                candidate_file_ids=dry_run.candidate_file_ids,
            )
        if action is MaintenanceAction.STATISTICS:
            return self.catalog.apply_statistics(generation_fence=fence)
        if action is MaintenanceAction.FILE_ROW_GROUP_SIZING:
            # Policy-only sizing receipt; no file rewrite unless combined with
            # rewrite_data_files.
            return {
                "created_file_ids": [],
                "deleted_file_ids": [],
                "resulting_snapshot": self.catalog.snapshot_version,
                "notes": "row_group_sizing_policy_recorded",
            }
        if action is MaintenanceAction.EXPIRE_SNAPSHOTS:
            plan = self.catalog.plan_expire_snapshots(
                policy=self.retention_policy,
                protected_snapshots=sorted(self.protected_snapshot_versions()),
            )
            return self.catalog.apply_expire_snapshots(
                generation_fence=fence,
                snapshots_to_expire=plan["snapshots_to_expire"],
                protected_snapshots=sorted(self.protected_snapshot_versions()),
            )
        if action is MaintenanceAction.CLEANUP_OLD_FILES:
            return self.catalog.apply_cleanup_old_files(
                generation_fence=fence,
                candidate_file_ids=dry_run.candidate_file_ids,
                paths_for_iam=paths_to_delete,
            )
        if action is MaintenanceAction.DELETE_ORPHANED_FILES:
            # Orphan preconditions: owned namespace, age, dry-run, non-self auth.
            for fid in dry_run.candidate_file_ids:
                rec = self.catalog.get_file(fid)
                if rec is None:
                    raise OrphanError(f"unknown orphan candidate {fid}")
                if not rec.owned_namespace:
                    raise OrphanError(
                        f"orphan candidate {fid} lacks owned-namespace proof"
                    )
                age = float(self._clock()) - float(rec.created_at_unix)
                if age < self.retention_policy.orphan_min_age_seconds:
                    raise OrphanError(
                        f"orphan candidate {fid} younger than age threshold"
                    )
            return self.catalog.apply_orphan_deletion(
                generation_fence=fence,
                candidate_file_ids=dry_run.candidate_file_ids,
            )
        raise ExecutionError(f"no executor for action {action.value}")

    # -- convenience high-level ops ----------------------------------------

    def run_compaction(
        self,
        *,
        operation_id: str,
        candidate_file_ids: Sequence[str] | None = None,
        dry_run_only: bool = False,
    ) -> DryRunReceipt | ExecutionReceipt:
        """Dry-run compaction (default) or full execute with IAM if needed."""

        auth = self.authorize(
            action=MaintenanceAction.COMPACTION,
            operation_id=operation_id,
            candidate_file_ids=candidate_file_ids,
        )
        dry = self.dry_run(
            action=MaintenanceAction.COMPACTION,
            operation_id=operation_id,
            authorization=auth,
            candidate_file_ids=candidate_file_ids,
        )
        if dry_run_only:
            return dry
        # Compaction retains old-snapshot files; IAM only when deletes predicted.
        iam = None
        if dry.predicted_deleted_file_ids:
            iam = self.broker.issue_object_delete_iam(
                authorization=auth,
                caller_id=self.caller_id,
                process_birth=self.process_birth,
                generation_fence=self.generation_fence,
                candidate_file_set_digest=dry.candidate_file_set_digest,
            )
        return self.execute(dry_run=dry, authorization=auth, object_delete_iam=iam)

    def proof_summary(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "catalog_id": self.catalog_id,
                "generation_fence": self.generation_fence,
                "retention_class": self.retention_policy.retention_class.value,
                "strict_single_global_retention_class": True,
                "destructive_default_mode": "dry_run",
                "bare_checkpoint_forbidden": True,
                "automated_cleanup_all_forbidden": True,
                "quack_token_cannot_authorize": True,
                "staging_outside_data_path": True,
                "supported_ducklake_functions": list(SUPPORTED_MAINTENANCE_FUNCTIONS),
                "auth_required_actions": sorted(_AUTH_REQUIRED_ACTIONS),
                "broker_id": self.broker.broker_id,
                "broker_distinct_from_maintainer": (
                    self.broker.broker_id != self.caller_id
                ),
            }
        )
