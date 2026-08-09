"""Namespaced, ordered, replayable schema migrations (DQK-003).

This module is the single source of truth for:

* versioned executable migrations and seed migrations with content checksums;
* compatibility windows that gate which schema versions may apply a step;
* exclusive lock ownership for a single migrator per namespace;
* dry-run planning, crash-safe resume (or fail-closed), and rollback metadata;
* immutable migration receipts and a deterministic schema digest.

Importing this module is inert: it never opens DuckDB, never touches the
filesystem, and never installs packages.  Persistence is injected through a
:class:`MigrationStore` (an in-memory store for unit tests, or a DuckDB-backed
store when the optional runtime is available).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

__all__ = [
    "MIGRATIONS_SCHEMA",
    "META_NAMESPACE",
    "AppliedMigrationRecord",
    "CompatibilityWindow",
    "DuckDBMigrationStore",
    "InMemoryMigrationStore",
    "Migration",
    "MigrationBatchResult",
    "MigrationChecksumError",
    "MigrationCompatibilityError",
    "MigrationError",
    "MigrationLock",
    "MigrationLockError",
    "MigrationPlan",
    "MigrationPlanStep",
    "MigrationReceipt",
    "MigrationRegistry",
    "MigrationRunner",
    "MigrationStateError",
    "MigrationStatus",
    "MigrationStore",
    "RollbackMetadata",
    "SchemaRegistryEntry",
    "build_default_meta_migrations",
    "canonical_migration_bytes",
    "compute_migration_checksum",
    "compute_schema_digest",
    "normalize_utc_timestamp",
    "utc_now",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

MIGRATIONS_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-migrations@1"
META_NAMESPACE: Final[str] = "meta"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MIGRATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MigrationError(ValueError):
    """Base error for migration definition, planning, or execution failures."""


class MigrationChecksumError(MigrationError):
    """Raised when an applied or planned migration checksum is unknown/modified."""


class MigrationLockError(MigrationError):
    """Raised when a migration lock cannot be acquired or is held by another owner."""


class MigrationStateError(MigrationError):
    """Raised when migration state is inconsistent and must fail closed."""


class MigrationCompatibilityError(MigrationError):
    """Raised when the current schema version is outside a migration's window."""


# ---------------------------------------------------------------------------
# Time / digest helpers
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return the current UTC time (timezone-aware)."""

    return datetime.now(timezone.utc)


def normalize_utc_timestamp(value: datetime | str) -> str:
    """Normalize to UTC ISO-8601 with ``Z`` and second precision."""

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MigrationError("timestamp must not be empty")
        candidate = text.replace("Z", "+00:00") if text.endswith("Z") else text
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise MigrationError(f"timestamp is not ISO-8601: {value!r}") from exc
    elif isinstance(value, datetime):
        moment = value
    else:
        raise MigrationError("timestamp must be datetime or ISO-8601 text")

    if moment.tzinfo is None:
        raise MigrationError("timestamp must be timezone-aware (UTC required)")
    utc = moment.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json_bytes(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"payload is not canonical-JSON-safe: {exc}") from exc


def _sha256_hex_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_of(payload: Any) -> str:
    return f"sha256:{_sha256_hex_of(_canonical_json_bytes(payload))}"


def _require_digest(value: str, *, field_name: str = "checksum") -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"{field_name} must be nonempty text")
    text = value.strip().lower()
    if text.startswith("sha256:"):
        hex_part = text[len("sha256:") :]
    else:
        hex_part = text
    if _SHA256_HEX.fullmatch(hex_part) is None:
        raise MigrationError(
            f"{field_name} must be sha256:<64 lowercase hex> or 64 hex chars"
        )
    return f"sha256:{hex_part}"


def _require_namespace(value: str) -> str:
    if not isinstance(value, str) or _NAMESPACE_RE.fullmatch(value) is None:
        raise MigrationError(
            f"namespace must match {_NAMESPACE_RE.pattern!r}; got {value!r}"
        )
    return value


def _require_migration_id(value: str) -> str:
    if not isinstance(value, str) or _MIGRATION_ID_RE.fullmatch(value) is None:
        raise MigrationError(
            f"migration_id must match {_MIGRATION_ID_RE.pattern!r}; got {value!r}"
        )
    return value


def _require_owner(value: str) -> str:
    if not isinstance(value, str) or _OWNER_RE.fullmatch(value) is None:
        raise MigrationError(
            f"owner_id must match {_OWNER_RE.pattern!r}; got {value!r}"
        )
    return value


def _require_version(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise MigrationError("version must be a positive integer")
    return value


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


class MigrationStatus(str, Enum):
    """Lifecycle status of a migration application attempt."""

    PENDING = "pending"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class CompatibilityWindow:
    """Inclusive schema-version window required before applying a migration.

    ``current_version`` must satisfy
    ``min_schema_version <= current_version <= max_schema_version``.
    For a first migration on an empty database, use ``(0, 0)``.
    """

    min_schema_version: int
    max_schema_version: int

    def __post_init__(self) -> None:
        for name, value in (
            ("min_schema_version", self.min_schema_version),
            ("max_schema_version", self.max_schema_version),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MigrationError(f"{name} must be a non-negative integer")
        if self.min_schema_version > self.max_schema_version:
            raise MigrationError(
                "min_schema_version must be <= max_schema_version"
            )

    def allows(self, current_version: int) -> bool:
        return self.min_schema_version <= current_version <= self.max_schema_version

    def to_dict(self) -> dict[str, int]:
        return {
            "min_schema_version": self.min_schema_version,
            "max_schema_version": self.max_schema_version,
        }


@dataclass(frozen=True)
class RollbackMetadata:
    """Declared rollback strategy for a migration (metadata only; not auto-run)."""

    strategy: str = "none"
    down_sql: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        strategy = (self.strategy or "none").strip().lower()
        allowed = {"none", "sql", "restore_snapshot", "manual"}
        if strategy not in allowed:
            raise MigrationError(
                f"rollback strategy must be one of {sorted(allowed)}; got {strategy!r}"
            )
        object.__setattr__(self, "strategy", strategy)
        if not isinstance(self.down_sql, str):
            raise MigrationError("down_sql must be text")
        if not isinstance(self.notes, str):
            raise MigrationError("notes must be text")
        if strategy == "sql" and not self.down_sql.strip():
            raise MigrationError("sql rollback strategy requires non-empty down_sql")

    def to_dict(self) -> dict[str, str]:
        return {
            "strategy": self.strategy,
            "down_sql": self.down_sql,
            "notes": self.notes,
        }


def canonical_migration_bytes(
    *,
    namespace: str,
    version: int,
    migration_id: str,
    up_sql: str,
    description: str = "",
    compatibility: CompatibilityWindow | Mapping[str, int] | None = None,
    rollback: RollbackMetadata | Mapping[str, str] | None = None,
) -> bytes:
    """Return deterministic bytes used for a migration content checksum."""

    if isinstance(compatibility, CompatibilityWindow):
        compat_dict = compatibility.to_dict()
    elif compatibility is None:
        compat_dict = CompatibilityWindow(0, 0).to_dict()
    else:
        compat_dict = dict(compatibility)

    if isinstance(rollback, RollbackMetadata):
        rollback_dict = rollback.to_dict()
    elif rollback is None:
        rollback_dict = RollbackMetadata().to_dict()
    else:
        rollback_dict = dict(rollback)

    payload = {
        "compatibility": compat_dict,
        "description": description or "",
        "migration_id": migration_id,
        "namespace": namespace,
        "rollback": rollback_dict,
        "schema": MIGRATIONS_SCHEMA,
        "up_sql": up_sql or "",
        "version": version,
    }
    return _canonical_json_bytes(payload)


def compute_migration_checksum(
    *,
    namespace: str,
    version: int,
    migration_id: str,
    up_sql: str,
    description: str = "",
    compatibility: CompatibilityWindow | Mapping[str, int] | None = None,
    rollback: RollbackMetadata | Mapping[str, str] | None = None,
) -> str:
    """Compute ``sha256:<hex>`` over :func:`canonical_migration_bytes`."""

    raw = canonical_migration_bytes(
        namespace=namespace,
        version=version,
        migration_id=migration_id,
        up_sql=up_sql,
        description=description,
        compatibility=compatibility,
        rollback=rollback,
    )
    return f"sha256:{_sha256_hex_of(raw)}"


@dataclass(frozen=True)
class Migration:
    """A single ordered migration step within a namespace."""

    namespace: str
    version: int
    migration_id: str
    up_sql: str
    description: str = ""
    checksum: str = ""
    compatibility: CompatibilityWindow = field(
        default_factory=lambda: CompatibilityWindow(0, 0)
    )
    rollback: RollbackMetadata = field(default_factory=RollbackMetadata)
    apply_fn: Optional[Callable[["Migration", "MigrationContext"], None]] = field(
        default=None, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _require_namespace(self.namespace))
        object.__setattr__(self, "version", _require_version(self.version))
        object.__setattr__(
            self, "migration_id", _require_migration_id(self.migration_id)
        )
        if not isinstance(self.up_sql, str):
            raise MigrationError("up_sql must be text")
        if not isinstance(self.description, str):
            raise MigrationError("description must be text")
        if not isinstance(self.compatibility, CompatibilityWindow):
            raise MigrationError("compatibility must be a CompatibilityWindow")
        if not isinstance(self.rollback, RollbackMetadata):
            raise MigrationError("rollback must be RollbackMetadata")

        expected = compute_migration_checksum(
            namespace=self.namespace,
            version=self.version,
            migration_id=self.migration_id,
            up_sql=self.up_sql,
            description=self.description,
            compatibility=self.compatibility,
            rollback=self.rollback,
        )
        if self.checksum:
            normalized = _require_digest(self.checksum)
            if normalized != expected:
                raise MigrationChecksumError(
                    f"migration {self.namespace}/{self.migration_id} checksum "
                    f"mismatch: provided {normalized}, expected {expected}"
                )
            object.__setattr__(self, "checksum", normalized)
        else:
            object.__setattr__(self, "checksum", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATIONS_SCHEMA,
            "namespace": self.namespace,
            "version": self.version,
            "migration_id": self.migration_id,
            "description": self.description,
            "up_sql": self.up_sql,
            "checksum": self.checksum,
            "compatibility": self.compatibility.to_dict(),
            "rollback": self.rollback.to_dict(),
        }

    def identity_payload(self) -> dict[str, Any]:
        """Stable identity used for schema digests (no SQL body)."""

        return {
            "checksum": self.checksum,
            "migration_id": self.migration_id,
            "namespace": self.namespace,
            "version": self.version,
        }


@dataclass(frozen=True)
class AppliedMigrationRecord:
    """Durable record of a migration that reached a terminal or in-progress state."""

    namespace: str
    version: int
    migration_id: str
    checksum: str
    status: MigrationStatus
    owner_id: str
    batch_id: str
    started_at: str
    completed_at: str = ""
    schema_digest_before: str = ""
    schema_digest_after: str = ""
    error: str = ""
    rollback: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _require_namespace(self.namespace))
        object.__setattr__(self, "version", _require_version(self.version))
        object.__setattr__(
            self, "migration_id", _require_migration_id(self.migration_id)
        )
        object.__setattr__(self, "checksum", _require_digest(self.checksum))
        if not isinstance(self.status, MigrationStatus):
            object.__setattr__(self, "status", MigrationStatus(str(self.status)))
        object.__setattr__(self, "owner_id", _require_owner(self.owner_id))
        if not isinstance(self.batch_id, str) or not self.batch_id.strip():
            raise MigrationError("batch_id must be nonempty")
        object.__setattr__(
            self, "started_at", normalize_utc_timestamp(self.started_at)
        )
        if self.completed_at:
            object.__setattr__(
                self, "completed_at", normalize_utc_timestamp(self.completed_at)
            )
        if self.schema_digest_before:
            object.__setattr__(
                self,
                "schema_digest_before",
                _require_digest(self.schema_digest_before, field_name="schema_digest_before"),
            )
        if self.schema_digest_after:
            object.__setattr__(
                self,
                "schema_digest_after",
                _require_digest(self.schema_digest_after, field_name="schema_digest_after"),
            )
        object.__setattr__(
            self,
            "rollback",
            MappingProxyType(dict(self.rollback or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "version": self.version,
            "migration_id": self.migration_id,
            "checksum": self.checksum,
            "status": self.status.value,
            "owner_id": self.owner_id,
            "batch_id": self.batch_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "schema_digest_before": self.schema_digest_before,
            "schema_digest_after": self.schema_digest_after,
            "error": self.error,
            "rollback": dict(self.rollback),
        }


@dataclass(frozen=True)
class MigrationReceipt:
    """Immutable receipt for a completed migration step (success or failure)."""

    receipt_id: str
    batch_id: str
    namespace: str
    version: int
    migration_id: str
    checksum: str
    owner_id: str
    status: MigrationStatus
    started_at: str
    completed_at: str
    schema_digest_before: str
    schema_digest_after: str
    dry_run: bool
    rollback: Mapping[str, str] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, str) or not self.receipt_id.strip():
            raise MigrationError("receipt_id must be nonempty")
        object.__setattr__(self, "namespace", _require_namespace(self.namespace))
        object.__setattr__(self, "version", _require_version(self.version))
        object.__setattr__(
            self, "migration_id", _require_migration_id(self.migration_id)
        )
        object.__setattr__(self, "checksum", _require_digest(self.checksum))
        object.__setattr__(self, "owner_id", _require_owner(self.owner_id))
        if not isinstance(self.status, MigrationStatus):
            object.__setattr__(self, "status", MigrationStatus(str(self.status)))
        object.__setattr__(
            self, "started_at", normalize_utc_timestamp(self.started_at)
        )
        object.__setattr__(
            self, "completed_at", normalize_utc_timestamp(self.completed_at)
        )
        if self.schema_digest_before:
            object.__setattr__(
                self,
                "schema_digest_before",
                _require_digest(self.schema_digest_before, field_name="schema_digest_before"),
            )
        if self.schema_digest_after:
            object.__setattr__(
                self,
                "schema_digest_after",
                _require_digest(self.schema_digest_after, field_name="schema_digest_after"),
            )
        object.__setattr__(
            self, "rollback", MappingProxyType(dict(self.rollback or {}))
        )
        if not isinstance(self.dry_run, bool):
            raise MigrationError("dry_run must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATIONS_SCHEMA,
            "receipt_id": self.receipt_id,
            "batch_id": self.batch_id,
            "namespace": self.namespace,
            "version": self.version,
            "migration_id": self.migration_id,
            "checksum": self.checksum,
            "owner_id": self.owner_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "schema_digest_before": self.schema_digest_before,
            "schema_digest_after": self.schema_digest_after,
            "dry_run": self.dry_run,
            "rollback": dict(self.rollback),
            "error": self.error,
        }

    @property
    def receipt_digest(self) -> str:
        return _digest_of(self.to_dict())


@dataclass(frozen=True)
class MigrationLock:
    """Exclusive lock ownership for migrations in one namespace."""

    namespace: str
    owner_id: str
    acquired_at: str
    expires_at: str
    lease_token: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _require_namespace(self.namespace))
        object.__setattr__(self, "owner_id", _require_owner(self.owner_id))
        object.__setattr__(
            self, "acquired_at", normalize_utc_timestamp(self.acquired_at)
        )
        object.__setattr__(
            self, "expires_at", normalize_utc_timestamp(self.expires_at)
        )
        if not isinstance(self.lease_token, str) or not self.lease_token.strip():
            raise MigrationError("lease_token must be nonempty")

    def is_expired(self, now: datetime | str | None = None) -> bool:
        moment = normalize_utc_timestamp(now or utc_now())
        return moment >= self.expires_at

    def to_dict(self) -> dict[str, str]:
        return {
            "namespace": self.namespace,
            "owner_id": self.owner_id,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "lease_token": self.lease_token,
        }


@dataclass(frozen=True)
class SchemaRegistryEntry:
    """Current schema head for a namespace."""

    namespace: str
    current_version: int
    schema_digest: str
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _require_namespace(self.namespace))
        if (
            not isinstance(self.current_version, int)
            or isinstance(self.current_version, bool)
            or self.current_version < 0
        ):
            raise MigrationError("current_version must be a non-negative integer")
        object.__setattr__(
            self,
            "schema_digest",
            _require_digest(self.schema_digest, field_name="schema_digest"),
        )
        object.__setattr__(
            self, "updated_at", normalize_utc_timestamp(self.updated_at)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "current_version": self.current_version,
            "schema_digest": self.schema_digest,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MigrationPlanStep:
    """One planned migration application (dry-run or live)."""

    migration: Migration
    action: str  # apply | resume | skip
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "migration": self.migration.to_dict(),
        }


@dataclass(frozen=True)
class MigrationPlan:
    """Ordered plan of migration steps for a namespace."""

    namespace: str
    current_version: int
    target_version: int
    schema_digest_before: str
    schema_digest_after: str
    steps: tuple[MigrationPlanStep, ...]
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATIONS_SCHEMA,
            "namespace": self.namespace,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "schema_digest_before": self.schema_digest_before,
            "schema_digest_after": self.schema_digest_after,
            "dry_run": self.dry_run,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class MigrationBatchResult:
    """Result of applying (or dry-running) a batch of migrations."""

    batch_id: str
    namespace: str
    owner_id: str
    dry_run: bool
    started_at: str
    completed_at: str
    schema_digest_before: str
    schema_digest_after: str
    applied_versions: tuple[int, ...]
    receipts: tuple[MigrationReceipt, ...]
    resumed: bool = False
    failed: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATIONS_SCHEMA,
            "batch_id": self.batch_id,
            "namespace": self.namespace,
            "owner_id": self.owner_id,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "schema_digest_before": self.schema_digest_before,
            "schema_digest_after": self.schema_digest_after,
            "applied_versions": list(self.applied_versions),
            "receipts": [r.to_dict() for r in self.receipts],
            "resumed": self.resumed,
            "failed": self.failed,
            "error": self.error,
        }


def compute_schema_digest(
    applied: Sequence[Migration | AppliedMigrationRecord | Mapping[str, Any]],
) -> str:
    """Deterministic digest of applied migrations in version order.

    Fresh databases that apply the full ordered chain and upgraded databases
    that apply the same chain in stages must converge to this digest.
    """

    items: list[dict[str, Any]] = []
    for entry in applied:
        if isinstance(entry, Migration):
            items.append(entry.identity_payload())
        elif isinstance(entry, AppliedMigrationRecord):
            if entry.status not in (MigrationStatus.APPLIED,):
                continue
            items.append(
                {
                    "checksum": entry.checksum,
                    "migration_id": entry.migration_id,
                    "namespace": entry.namespace,
                    "version": entry.version,
                }
            )
        elif isinstance(entry, Mapping):
            items.append(
                {
                    "checksum": _require_digest(str(entry["checksum"])),
                    "migration_id": str(entry["migration_id"]),
                    "namespace": str(entry["namespace"]),
                    "version": int(entry["version"]),
                }
            )
        else:
            raise MigrationError(
                f"unsupported applied migration type: {type(entry)!r}"
            )

    items.sort(key=lambda item: (item["namespace"], int(item["version"])))
    return _digest_of({"schema": MIGRATIONS_SCHEMA, "migrations": items})


# ---------------------------------------------------------------------------
# Store protocol + implementations
# ---------------------------------------------------------------------------


class MigrationContext:
    """Execution context passed to optional pure-Python ``apply_fn`` hooks."""

    def __init__(self, store: "MigrationStore", *, dry_run: bool) -> None:
        self.store = store
        self.dry_run = dry_run
        self.executed_sql: list[str] = []

    def execute_sql(self, sql: str) -> None:
        if self.dry_run:
            self.executed_sql.append(sql)
            return
        self.store.execute_sql(sql)
        self.executed_sql.append(sql)


@runtime_checkable
class MigrationStore(Protocol):
    """Persistence surface for migration meta-state and SQL execution."""

    def ensure_bootstrap(self) -> None:
        """Create meta tables / structures if absent."""

    def get_schema_entry(self, namespace: str) -> SchemaRegistryEntry | None: ...

    def upsert_schema_entry(self, entry: SchemaRegistryEntry) -> None: ...

    def list_applied(
        self, namespace: str, *, include_non_terminal: bool = False
    ) -> list[AppliedMigrationRecord]: ...

    def get_applied(
        self, namespace: str, version: int
    ) -> AppliedMigrationRecord | None: ...

    def get_in_progress(self, namespace: str) -> AppliedMigrationRecord | None: ...

    def put_applied(self, record: AppliedMigrationRecord) -> None: ...

    def get_lock(self, namespace: str) -> MigrationLock | None: ...

    def put_lock(self, lock: MigrationLock) -> None: ...

    def delete_lock(self, namespace: str, *, owner_id: str, lease_token: str) -> None: ...

    def append_receipt(self, receipt: MigrationReceipt) -> None: ...

    def list_receipts(self, namespace: str) -> list[MigrationReceipt]: ...

    def execute_sql(self, sql: str) -> None: ...


class InMemoryMigrationStore:
    """Thread-safe in-memory store used by unit tests and pure planning."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._schema: dict[str, SchemaRegistryEntry] = {}
        self._applied: dict[tuple[str, int], AppliedMigrationRecord] = {}
        self._locks: dict[str, MigrationLock] = {}
        self._receipts: list[MigrationReceipt] = []
        self._sql_log: list[str] = []
        self._bootstrapped = False

    def ensure_bootstrap(self) -> None:
        with self._lock:
            self._bootstrapped = True

    def get_schema_entry(self, namespace: str) -> SchemaRegistryEntry | None:
        with self._lock:
            return self._schema.get(namespace)

    def upsert_schema_entry(self, entry: SchemaRegistryEntry) -> None:
        with self._lock:
            self._schema[entry.namespace] = entry

    def list_applied(
        self, namespace: str, *, include_non_terminal: bool = False
    ) -> list[AppliedMigrationRecord]:
        with self._lock:
            rows = [
                record
                for (ns, _), record in sorted(self._applied.items())
                if ns == namespace
            ]
        if include_non_terminal:
            return rows
        return [r for r in rows if r.status == MigrationStatus.APPLIED]

    def get_applied(
        self, namespace: str, version: int
    ) -> AppliedMigrationRecord | None:
        with self._lock:
            return self._applied.get((namespace, version))

    def get_in_progress(self, namespace: str) -> AppliedMigrationRecord | None:
        with self._lock:
            for (ns, _), record in sorted(self._applied.items()):
                if ns == namespace and record.status == MigrationStatus.APPLYING:
                    return record
        return None

    def put_applied(self, record: AppliedMigrationRecord) -> None:
        with self._lock:
            self._applied[(record.namespace, record.version)] = record

    def get_lock(self, namespace: str) -> MigrationLock | None:
        with self._lock:
            return self._locks.get(namespace)

    def put_lock(self, lock: MigrationLock) -> None:
        with self._lock:
            self._locks[lock.namespace] = lock

    def delete_lock(
        self, namespace: str, *, owner_id: str, lease_token: str
    ) -> None:
        with self._lock:
            current = self._locks.get(namespace)
            if current is None:
                return
            if current.owner_id != owner_id or current.lease_token != lease_token:
                raise MigrationLockError(
                    f"cannot release lock for {namespace}: ownership mismatch"
                )
            del self._locks[namespace]

    def append_receipt(self, receipt: MigrationReceipt) -> None:
        with self._lock:
            self._receipts.append(receipt)

    def list_receipts(self, namespace: str) -> list[MigrationReceipt]:
        with self._lock:
            return [r for r in self._receipts if r.namespace == namespace]

    def execute_sql(self, sql: str) -> None:
        with self._lock:
            self._sql_log.append(sql)

    @property
    def sql_log(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._sql_log)


class DuckDBMigrationStore:
    """DuckDB-backed store for production control catalogs.

    Constructed only when a live DuckDB connection is supplied.  Importing
    this module never imports ``duckdb``.
    """

    _BOOTSTRAP_SQL: Final[tuple[str, ...]] = (
        """
        CREATE TABLE IF NOT EXISTS meta_schema_registry (
            namespace VARCHAR PRIMARY KEY,
            current_version INTEGER NOT NULL,
            schema_digest VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS meta_schema_migrations (
            namespace VARCHAR NOT NULL,
            version INTEGER NOT NULL,
            migration_id VARCHAR NOT NULL,
            checksum VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            owner_id VARCHAR NOT NULL,
            batch_id VARCHAR NOT NULL,
            started_at VARCHAR NOT NULL,
            completed_at VARCHAR NOT NULL DEFAULT '',
            schema_digest_before VARCHAR NOT NULL DEFAULT '',
            schema_digest_after VARCHAR NOT NULL DEFAULT '',
            error VARCHAR NOT NULL DEFAULT '',
            rollback_json VARCHAR NOT NULL DEFAULT '{}',
            PRIMARY KEY (namespace, version)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS meta_migration_locks (
            namespace VARCHAR PRIMARY KEY,
            owner_id VARCHAR NOT NULL,
            acquired_at VARCHAR NOT NULL,
            expires_at VARCHAR NOT NULL,
            lease_token VARCHAR NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS meta_migration_receipts (
            receipt_id VARCHAR PRIMARY KEY,
            batch_id VARCHAR NOT NULL,
            namespace VARCHAR NOT NULL,
            version INTEGER NOT NULL,
            migration_id VARCHAR NOT NULL,
            checksum VARCHAR NOT NULL,
            owner_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            started_at VARCHAR NOT NULL,
            completed_at VARCHAR NOT NULL,
            schema_digest_before VARCHAR NOT NULL,
            schema_digest_after VARCHAR NOT NULL,
            dry_run BOOLEAN NOT NULL,
            rollback_json VARCHAR NOT NULL,
            error VARCHAR NOT NULL DEFAULT '',
            receipt_digest VARCHAR NOT NULL
        )
        """,
    )

    def __init__(self, connection: Any) -> None:
        if connection is None:
            raise MigrationError("DuckDB connection is required")
        self._conn = connection

    def ensure_bootstrap(self) -> None:
        for statement in self._BOOTSTRAP_SQL:
            self._conn.execute(statement)

    def get_schema_entry(self, namespace: str) -> SchemaRegistryEntry | None:
        row = self._conn.execute(
            """
            SELECT namespace, current_version, schema_digest, updated_at
            FROM meta_schema_registry WHERE namespace = ?
            """,
            [namespace],
        ).fetchone()
        if row is None:
            return None
        return SchemaRegistryEntry(
            namespace=row[0],
            current_version=int(row[1]),
            schema_digest=row[2],
            updated_at=row[3],
        )

    def upsert_schema_entry(self, entry: SchemaRegistryEntry) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO meta_schema_registry
                (namespace, current_version, schema_digest, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                entry.namespace,
                entry.current_version,
                entry.schema_digest,
                entry.updated_at,
            ],
        )

    def list_applied(
        self, namespace: str, *, include_non_terminal: bool = False
    ) -> list[AppliedMigrationRecord]:
        rows = self._conn.execute(
            """
            SELECT namespace, version, migration_id, checksum, status, owner_id,
                   batch_id, started_at, completed_at, schema_digest_before,
                   schema_digest_after, error, rollback_json
            FROM meta_schema_migrations
            WHERE namespace = ?
            ORDER BY version ASC
            """,
            [namespace],
        ).fetchall()
        records = [self._row_to_applied(row) for row in rows]
        if include_non_terminal:
            return records
        return [r for r in records if r.status == MigrationStatus.APPLIED]

    def get_applied(
        self, namespace: str, version: int
    ) -> AppliedMigrationRecord | None:
        row = self._conn.execute(
            """
            SELECT namespace, version, migration_id, checksum, status, owner_id,
                   batch_id, started_at, completed_at, schema_digest_before,
                   schema_digest_after, error, rollback_json
            FROM meta_schema_migrations
            WHERE namespace = ? AND version = ?
            """,
            [namespace, version],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_applied(row)

    def get_in_progress(self, namespace: str) -> AppliedMigrationRecord | None:
        row = self._conn.execute(
            """
            SELECT namespace, version, migration_id, checksum, status, owner_id,
                   batch_id, started_at, completed_at, schema_digest_before,
                   schema_digest_after, error, rollback_json
            FROM meta_schema_migrations
            WHERE namespace = ? AND status = ?
            ORDER BY version ASC
            LIMIT 1
            """,
            [namespace, MigrationStatus.APPLYING.value],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_applied(row)

    def put_applied(self, record: AppliedMigrationRecord) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO meta_schema_migrations (
                namespace, version, migration_id, checksum, status, owner_id,
                batch_id, started_at, completed_at, schema_digest_before,
                schema_digest_after, error, rollback_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record.namespace,
                record.version,
                record.migration_id,
                record.checksum,
                record.status.value,
                record.owner_id,
                record.batch_id,
                record.started_at,
                record.completed_at,
                record.schema_digest_before,
                record.schema_digest_after,
                record.error,
                json.dumps(dict(record.rollback), sort_keys=True, separators=(",", ":")),
            ],
        )

    def get_lock(self, namespace: str) -> MigrationLock | None:
        row = self._conn.execute(
            """
            SELECT namespace, owner_id, acquired_at, expires_at, lease_token
            FROM meta_migration_locks WHERE namespace = ?
            """,
            [namespace],
        ).fetchone()
        if row is None:
            return None
        return MigrationLock(
            namespace=row[0],
            owner_id=row[1],
            acquired_at=row[2],
            expires_at=row[3],
            lease_token=row[4],
        )

    def put_lock(self, lock: MigrationLock) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO meta_migration_locks
                (namespace, owner_id, acquired_at, expires_at, lease_token)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                lock.namespace,
                lock.owner_id,
                lock.acquired_at,
                lock.expires_at,
                lock.lease_token,
            ],
        )

    def delete_lock(
        self, namespace: str, *, owner_id: str, lease_token: str
    ) -> None:
        current = self.get_lock(namespace)
        if current is None:
            return
        if current.owner_id != owner_id or current.lease_token != lease_token:
            raise MigrationLockError(
                f"cannot release lock for {namespace}: ownership mismatch"
            )
        self._conn.execute(
            "DELETE FROM meta_migration_locks WHERE namespace = ?",
            [namespace],
        )

    def append_receipt(self, receipt: MigrationReceipt) -> None:
        self._conn.execute(
            """
            INSERT INTO meta_migration_receipts (
                receipt_id, batch_id, namespace, version, migration_id, checksum,
                owner_id, status, started_at, completed_at, schema_digest_before,
                schema_digest_after, dry_run, rollback_json, error, receipt_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                receipt.receipt_id,
                receipt.batch_id,
                receipt.namespace,
                receipt.version,
                receipt.migration_id,
                receipt.checksum,
                receipt.owner_id,
                receipt.status.value,
                receipt.started_at,
                receipt.completed_at,
                receipt.schema_digest_before,
                receipt.schema_digest_after,
                receipt.dry_run,
                json.dumps(dict(receipt.rollback), sort_keys=True, separators=(",", ":")),
                receipt.error,
                receipt.receipt_digest,
            ],
        )

    def list_receipts(self, namespace: str) -> list[MigrationReceipt]:
        rows = self._conn.execute(
            """
            SELECT receipt_id, batch_id, namespace, version, migration_id, checksum,
                   owner_id, status, started_at, completed_at, schema_digest_before,
                   schema_digest_after, dry_run, rollback_json, error
            FROM meta_migration_receipts
            WHERE namespace = ?
            ORDER BY version ASC, completed_at ASC
            """,
            [namespace],
        ).fetchall()
        results: list[MigrationReceipt] = []
        for row in rows:
            results.append(
                MigrationReceipt(
                    receipt_id=row[0],
                    batch_id=row[1],
                    namespace=row[2],
                    version=int(row[3]),
                    migration_id=row[4],
                    checksum=row[5],
                    owner_id=row[6],
                    status=MigrationStatus(row[7]),
                    started_at=row[8],
                    completed_at=row[9],
                    schema_digest_before=row[10],
                    schema_digest_after=row[11],
                    dry_run=bool(row[12]),
                    rollback=json.loads(row[13] or "{}"),
                    error=row[14] or "",
                )
            )
        return results

    def execute_sql(self, sql: str) -> None:
        self._conn.execute(sql)

    @staticmethod
    def _row_to_applied(row: Sequence[Any]) -> AppliedMigrationRecord:
        return AppliedMigrationRecord(
            namespace=row[0],
            version=int(row[1]),
            migration_id=row[2],
            checksum=row[3],
            status=MigrationStatus(row[4]),
            owner_id=row[5],
            batch_id=row[6],
            started_at=row[7],
            completed_at=row[8] or "",
            schema_digest_before=row[9] or "",
            schema_digest_after=row[10] or "",
            error=row[11] or "",
            rollback=json.loads(row[12] or "{}"),
        )


# ---------------------------------------------------------------------------
# Registry + runner
# ---------------------------------------------------------------------------


class MigrationRegistry:
    """In-process registry of ordered migrations, keyed by namespace."""

    def __init__(self) -> None:
        self._by_namespace: dict[str, dict[int, Migration]] = {}

    def register(self, migration: Migration) -> None:
        if not isinstance(migration, Migration):
            raise MigrationError("register() requires a Migration instance")
        bucket = self._by_namespace.setdefault(migration.namespace, {})
        existing = bucket.get(migration.version)
        if existing is not None:
            if existing.checksum != migration.checksum:
                raise MigrationChecksumError(
                    f"duplicate version {migration.namespace}@{migration.version} "
                    f"with different checksum"
                )
            if existing.migration_id != migration.migration_id:
                raise MigrationError(
                    f"duplicate version {migration.namespace}@{migration.version} "
                    f"with different migration_id"
                )
            return
        # migration_id uniqueness within namespace
        for other in bucket.values():
            if other.migration_id == migration.migration_id:
                raise MigrationError(
                    f"duplicate migration_id {migration.migration_id!r} "
                    f"in namespace {migration.namespace}"
                )
        bucket[migration.version] = migration

    def register_many(self, migrations: Iterable[Migration]) -> None:
        for migration in migrations:
            self.register(migration)

    def namespaces(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_namespace))

    def get(self, namespace: str, version: int) -> Migration | None:
        return self._by_namespace.get(namespace, {}).get(version)

    def get_by_id(self, namespace: str, migration_id: str) -> Migration | None:
        for migration in self._by_namespace.get(namespace, {}).values():
            if migration.migration_id == migration_id:
                return migration
        return None

    def ordered(self, namespace: str) -> list[Migration]:
        _require_namespace(namespace)
        bucket = self._by_namespace.get(namespace, {})
        versions = sorted(bucket)
        # Require contiguous versions starting at 1 for replay safety.
        if versions and versions != list(range(1, len(versions) + 1)):
            raise MigrationStateError(
                f"namespace {namespace} migrations must be contiguous versions "
                f"starting at 1; got {versions}"
            )
        return [bucket[v] for v in versions]

    def expected_checksum(self, namespace: str, version: int) -> str | None:
        migration = self.get(namespace, version)
        return None if migration is None else migration.checksum


class MigrationRunner:
    """Plan and apply namespaced migrations against a :class:`MigrationStore`."""

    DEFAULT_LOCK_TTL_SECONDS: Final[int] = 300

    def __init__(
        self,
        store: MigrationStore,
        registry: MigrationRegistry,
        *,
        owner_id: str,
        lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.owner_id = _require_owner(owner_id)
        if (
            not isinstance(lock_ttl_seconds, int)
            or isinstance(lock_ttl_seconds, bool)
            or lock_ttl_seconds < 1
        ):
            raise MigrationError("lock_ttl_seconds must be a positive integer")
        self.lock_ttl_seconds = lock_ttl_seconds
        self._clock = clock or utc_now
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    # -- public API --------------------------------------------------------

    def schema_digest(self, namespace: str) -> str:
        """Return the durable schema digest for *namespace* (empty chain = digest)."""

        self.store.ensure_bootstrap()
        applied = self.store.list_applied(namespace)
        if not applied:
            return compute_schema_digest(())
        return compute_schema_digest(applied)

    def current_version(self, namespace: str) -> int:
        self.store.ensure_bootstrap()
        entry = self.store.get_schema_entry(namespace)
        if entry is not None:
            return entry.current_version
        applied = self.store.list_applied(namespace)
        if not applied:
            return 0
        return max(record.version for record in applied)

    def verify_checksums(self, namespace: str) -> None:
        """Reject unknown applied migrations and modified checksums (fail closed)."""

        self.store.ensure_bootstrap()
        _require_namespace(namespace)
        registry_chain = self.registry.ordered(namespace)
        by_version = {m.version: m for m in registry_chain}
        applied = self.store.list_applied(namespace, include_non_terminal=True)

        for record in applied:
            expected = by_version.get(record.version)
            if expected is None:
                raise MigrationChecksumError(
                    f"unknown applied migration {namespace}@{record.version} "
                    f"id={record.migration_id} checksum={record.checksum}"
                )
            if expected.checksum != record.checksum:
                raise MigrationChecksumError(
                    f"modified migration checksum for {namespace}@"
                    f"{record.version} id={record.migration_id}: "
                    f"store={record.checksum} registry={expected.checksum}"
                )
            if expected.migration_id != record.migration_id:
                raise MigrationChecksumError(
                    f"migration_id drift for {namespace}@{record.version}: "
                    f"store={record.migration_id} registry={expected.migration_id}"
                )

        # Applied set must be a prefix of the registry chain (no holes).
        applied_applied = [
            r for r in applied if r.status == MigrationStatus.APPLIED
        ]
        if not applied_applied:
            return
        max_applied = max(r.version for r in applied_applied)
        for version in range(1, max_applied + 1):
            record = self.store.get_applied(namespace, version)
            if record is None or record.status != MigrationStatus.APPLIED:
                raise MigrationStateError(
                    f"migration chain hole at {namespace}@{version}"
                )

    def dry_run(self, namespace: str) -> MigrationPlan:
        """Build an ordered plan without mutating schema state."""

        return self._build_plan(namespace, dry_run=True)

    def apply(
        self,
        namespace: str,
        *,
        dry_run: bool = False,
        resume: bool = True,
        target_version: int | None = None,
    ) -> MigrationBatchResult:
        """Apply pending migrations for *namespace*.

        Parameters
        ----------
        dry_run:
            When true, produce receipts and a plan result without durable apply.
        resume:
            When an ``APPLYING`` record exists, re-run that step if checksums
            still match; otherwise fail closed.  When false, any in-progress
            record fails closed immediately.
        target_version:
            Optional inclusive version cap; defaults to the registry head.
        """

        self.store.ensure_bootstrap()
        namespace = _require_namespace(namespace)
        started_at = normalize_utc_timestamp(self._clock())
        batch_id = self._id_factory()

        lock: MigrationLock | None = None
        if not dry_run:
            lock = self._acquire_lock(namespace)

        try:
            self.verify_checksums(namespace)
            plan = self._build_plan(
                namespace,
                dry_run=dry_run,
                resume=resume,
                target_version=target_version,
            )
            if dry_run:
                # Emit dry-run receipts for planned apply/resume steps.
                receipts: list[MigrationReceipt] = []
                for step in plan.steps:
                    if step.action not in ("apply", "resume"):
                        continue
                    now = normalize_utc_timestamp(self._clock())
                    receipts.append(
                        MigrationReceipt(
                            receipt_id=self._id_factory(),
                            batch_id=batch_id,
                            namespace=namespace,
                            version=step.migration.version,
                            migration_id=step.migration.migration_id,
                            checksum=step.migration.checksum,
                            owner_id=self.owner_id,
                            status=MigrationStatus.APPLIED,
                            started_at=now,
                            completed_at=now,
                            schema_digest_before=plan.schema_digest_before,
                            schema_digest_after=plan.schema_digest_after,
                            dry_run=True,
                            rollback=step.migration.rollback.to_dict(),
                        )
                    )
                completed_at = normalize_utc_timestamp(self._clock())
                return MigrationBatchResult(
                    batch_id=batch_id,
                    namespace=namespace,
                    owner_id=self.owner_id,
                    dry_run=True,
                    started_at=started_at,
                    completed_at=completed_at,
                    schema_digest_before=plan.schema_digest_before,
                    schema_digest_after=plan.schema_digest_after,
                    applied_versions=tuple(
                        s.migration.version
                        for s in plan.steps
                        if s.action in ("apply", "resume")
                    ),
                    receipts=tuple(receipts),
                    resumed=any(s.action == "resume" for s in plan.steps),
                )

            return self._execute_plan(
                plan,
                batch_id=batch_id,
                started_at=started_at,
                resume=resume,
            )
        finally:
            if lock is not None:
                try:
                    self.store.delete_lock(
                        namespace,
                        owner_id=lock.owner_id,
                        lease_token=lock.lease_token,
                    )
                except MigrationLockError:
                    # Another owner stole an expired lease; fail closed only if
                    # still held by us would be required for further writes.
                    pass

    # -- internals ---------------------------------------------------------

    def _build_plan(
        self,
        namespace: str,
        *,
        dry_run: bool,
        resume: bool = True,
        target_version: int | None = None,
    ) -> MigrationPlan:
        self.store.ensure_bootstrap()
        namespace = _require_namespace(namespace)
        chain = self.registry.ordered(namespace)
        if target_version is not None:
            if (
                not isinstance(target_version, int)
                or isinstance(target_version, bool)
                or target_version < 0
            ):
                raise MigrationError("target_version must be a non-negative integer")
            chain = [m for m in chain if m.version <= target_version]

        current = self.current_version(namespace)
        digest_before = self.schema_digest(namespace)
        in_progress = self.store.get_in_progress(namespace)
        steps: list[MigrationPlanStep] = []
        simulated_applied: list[Migration] = []
        for record in self.store.list_applied(namespace):
            mig = self.registry.get(namespace, record.version)
            if mig is None:
                raise MigrationChecksumError(
                    f"unknown applied migration {namespace}@{record.version}"
                )
            simulated_applied.append(mig)
        simulated_version = current

        if in_progress is not None:
            expected = self.registry.get(namespace, in_progress.version)
            if expected is None:
                raise MigrationChecksumError(
                    f"in-progress migration {namespace}@{in_progress.version} "
                    f"is unknown to the registry"
                )
            if expected.checksum != in_progress.checksum:
                raise MigrationChecksumError(
                    f"in-progress migration checksum modified for "
                    f"{namespace}@{in_progress.version}"
                )
            if not resume:
                raise MigrationStateError(
                    f"interrupted migration {namespace}@{in_progress.version} "
                    f"present and resume is disabled (fail closed)"
                )
            if not expected.compatibility.allows(simulated_version):
                # Resume applies against the version at interruption; for
                # APPLYING the durable head is still the previous version.
                pass
            steps.append(
                MigrationPlanStep(
                    migration=expected,
                    action="resume",
                    reason="interrupted APPLYING record; checksum verified",
                )
            )
            simulated_applied = [
                m for m in simulated_applied if m.version != expected.version
            ]
            simulated_applied.append(expected)
            simulated_version = expected.version

        for migration in chain:
            if migration.version <= simulated_version:
                # Already applied (or just resumed into simulated head).
                record = self.store.get_applied(namespace, migration.version)
                if record is not None and record.status == MigrationStatus.APPLIED:
                    if record.checksum != migration.checksum:
                        raise MigrationChecksumError(
                            f"modified migration checksum for {namespace}@"
                            f"{migration.version}"
                        )
                    steps.append(
                        MigrationPlanStep(
                            migration=migration,
                            action="skip",
                            reason="already applied",
                        )
                    )
                    continue
                if (
                    in_progress is not None
                    and in_progress.version == migration.version
                ):
                    # Already added as resume.
                    continue
            # Pending apply.
            if migration.version != simulated_version + 1:
                raise MigrationStateError(
                    f"cannot apply {namespace}@{migration.version}: "
                    f"expected next version {simulated_version + 1}"
                )
            if not migration.compatibility.allows(simulated_version):
                raise MigrationCompatibilityError(
                    f"migration {namespace}/{migration.migration_id} "
                    f"compatibility window "
                    f"[{migration.compatibility.min_schema_version}, "
                    f"{migration.compatibility.max_schema_version}] "
                    f"rejects current_version={simulated_version}"
                )
            steps.append(
                MigrationPlanStep(
                    migration=migration,
                    action="apply",
                    reason="pending",
                )
            )
            simulated_applied.append(migration)
            simulated_version = migration.version

        digest_after = compute_schema_digest(simulated_applied)
        return MigrationPlan(
            namespace=namespace,
            current_version=current,
            target_version=simulated_version,
            schema_digest_before=digest_before,
            schema_digest_after=digest_after,
            steps=tuple(steps),
            dry_run=dry_run,
        )

    def _execute_plan(
        self,
        plan: MigrationPlan,
        *,
        batch_id: str,
        started_at: str,
        resume: bool,
    ) -> MigrationBatchResult:
        namespace = plan.namespace
        receipts: list[MigrationReceipt] = []
        applied_versions: list[int] = []
        resumed = False
        digest_before = plan.schema_digest_before
        current_digest = digest_before
        failed = False
        error = ""

        for step in plan.steps:
            if step.action == "skip":
                continue
            if step.action == "resume":
                resumed = True
            migration = step.migration
            step_started = normalize_utc_timestamp(self._clock())
            before = current_digest

            # Mark APPLYING (durable) before executing body.
            applying = AppliedMigrationRecord(
                namespace=namespace,
                version=migration.version,
                migration_id=migration.migration_id,
                checksum=migration.checksum,
                status=MigrationStatus.APPLYING,
                owner_id=self.owner_id,
                batch_id=batch_id,
                started_at=step_started,
                schema_digest_before=before,
                rollback=migration.rollback.to_dict(),
            )
            self.store.put_applied(applying)

            try:
                self._run_migration_body(migration, dry_run=False)
            except Exception as exc:  # noqa: BLE001 — fail closed with durable FAILED
                failed = True
                error = f"{type(exc).__name__}: {exc}"
                step_completed = normalize_utc_timestamp(self._clock())
                failed_record = AppliedMigrationRecord(
                    namespace=namespace,
                    version=migration.version,
                    migration_id=migration.migration_id,
                    checksum=migration.checksum,
                    status=MigrationStatus.FAILED,
                    owner_id=self.owner_id,
                    batch_id=batch_id,
                    started_at=step_started,
                    completed_at=step_completed,
                    schema_digest_before=before,
                    schema_digest_after=before,
                    error=error,
                    rollback=migration.rollback.to_dict(),
                )
                self.store.put_applied(failed_record)
                receipt = MigrationReceipt(
                    receipt_id=self._id_factory(),
                    batch_id=batch_id,
                    namespace=namespace,
                    version=migration.version,
                    migration_id=migration.migration_id,
                    checksum=migration.checksum,
                    owner_id=self.owner_id,
                    status=MigrationStatus.FAILED,
                    started_at=step_started,
                    completed_at=step_completed,
                    schema_digest_before=before,
                    schema_digest_after=before,
                    dry_run=False,
                    rollback=migration.rollback.to_dict(),
                    error=error,
                )
                self.store.append_receipt(receipt)
                receipts.append(receipt)
                break

            # Compute post-apply digest including this migration.
            durable = [
                m
                for m in self.registry.ordered(namespace)
                if m.version < migration.version
                and (
                    (rec := self.store.get_applied(namespace, m.version)) is not None
                    and rec.status == MigrationStatus.APPLIED
                )
            ]
            durable.append(migration)
            after = compute_schema_digest(durable)
            step_completed = normalize_utc_timestamp(self._clock())

            applied_record = AppliedMigrationRecord(
                namespace=namespace,
                version=migration.version,
                migration_id=migration.migration_id,
                checksum=migration.checksum,
                status=MigrationStatus.APPLIED,
                owner_id=self.owner_id,
                batch_id=batch_id,
                started_at=step_started,
                completed_at=step_completed,
                schema_digest_before=before,
                schema_digest_after=after,
                rollback=migration.rollback.to_dict(),
            )
            self.store.put_applied(applied_record)
            self.store.upsert_schema_entry(
                SchemaRegistryEntry(
                    namespace=namespace,
                    current_version=migration.version,
                    schema_digest=after,
                    updated_at=step_completed,
                )
            )
            receipt = MigrationReceipt(
                receipt_id=self._id_factory(),
                batch_id=batch_id,
                namespace=namespace,
                version=migration.version,
                migration_id=migration.migration_id,
                checksum=migration.checksum,
                owner_id=self.owner_id,
                status=MigrationStatus.APPLIED,
                started_at=step_started,
                completed_at=step_completed,
                schema_digest_before=before,
                schema_digest_after=after,
                dry_run=False,
                rollback=migration.rollback.to_dict(),
            )
            self.store.append_receipt(receipt)
            receipts.append(receipt)
            applied_versions.append(migration.version)
            current_digest = after

        completed_at = normalize_utc_timestamp(self._clock())
        # Final verification after successful path.
        if not failed:
            self.verify_checksums(namespace)
            current_digest = self.schema_digest(namespace)

        return MigrationBatchResult(
            batch_id=batch_id,
            namespace=namespace,
            owner_id=self.owner_id,
            dry_run=False,
            started_at=started_at,
            completed_at=completed_at,
            schema_digest_before=digest_before,
            schema_digest_after=current_digest,
            applied_versions=tuple(applied_versions),
            receipts=tuple(receipts),
            resumed=resumed,
            failed=failed,
            error=error,
        )

    def _run_migration_body(self, migration: Migration, *, dry_run: bool) -> None:
        context = MigrationContext(self.store, dry_run=dry_run)
        if migration.apply_fn is not None:
            migration.apply_fn(migration, context)
        elif migration.up_sql.strip():
            # Support multi-statement bodies split on semicolons for stores
            # that execute one statement at a time.
            for statement in _split_sql_statements(migration.up_sql):
                context.execute_sql(statement)
        # Empty body is allowed (marker / seed bookkeeping only).

    def _acquire_lock(self, namespace: str) -> MigrationLock:
        now = self._clock()
        now_text = normalize_utc_timestamp(now)
        expires = normalize_utc_timestamp(
            now + timedelta(seconds=self.lock_ttl_seconds)
        )
        lease_token = self._id_factory()

        existing = self.store.get_lock(namespace)
        if existing is not None:
            if not existing.is_expired(now) and existing.owner_id != self.owner_id:
                raise MigrationLockError(
                    f"namespace {namespace} is locked by owner {existing.owner_id!r} "
                    f"until {existing.expires_at}"
                )
            if not existing.is_expired(now) and existing.owner_id == self.owner_id:
                refreshed = MigrationLock(
                    namespace=namespace,
                    owner_id=self.owner_id,
                    acquired_at=existing.acquired_at,
                    expires_at=expires,
                    lease_token=existing.lease_token,
                )
                self.store.put_lock(refreshed)
                return refreshed
            # Expired lock may be stolen with a fresh lease token.
        lock = MigrationLock(
            namespace=namespace,
            owner_id=self.owner_id,
            acquired_at=now_text,
            expires_at=expires,
            lease_token=lease_token,
        )
        self.store.put_lock(lock)
        return lock


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL body on top-level semicolons (no string/escape awareness beyond quotes)."""

    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    text = sql
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == ";" and not in_single and not in_double:
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def build_default_meta_migrations() -> list[Migration]:
    """Bootstrap migrations that create the meta schema-registry tables.

    These are pure bookkeeping SQL strings for DuckDB stores; the in-memory
    store treats them as logged SQL via :meth:`MigrationStore.execute_sql`.
    """

    migrations: list[Migration] = []
    specs = [
        (
            1,
            "001_create_schema_registry",
            "Create meta schema_registry table",
            """
            CREATE TABLE IF NOT EXISTS meta_schema_registry (
                namespace VARCHAR PRIMARY KEY,
                current_version INTEGER NOT NULL,
                schema_digest VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            CompatibilityWindow(0, 0),
        ),
        (
            2,
            "002_create_schema_migrations",
            "Create meta schema_migrations table",
            """
            CREATE TABLE IF NOT EXISTS meta_schema_migrations (
                namespace VARCHAR NOT NULL,
                version INTEGER NOT NULL,
                migration_id VARCHAR NOT NULL,
                checksum VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                owner_id VARCHAR NOT NULL,
                batch_id VARCHAR NOT NULL,
                started_at VARCHAR NOT NULL,
                completed_at VARCHAR NOT NULL DEFAULT '',
                schema_digest_before VARCHAR NOT NULL DEFAULT '',
                schema_digest_after VARCHAR NOT NULL DEFAULT '',
                error VARCHAR NOT NULL DEFAULT '',
                rollback_json VARCHAR NOT NULL DEFAULT '{}',
                PRIMARY KEY (namespace, version)
            )
            """,
            CompatibilityWindow(1, 1),
        ),
        (
            3,
            "003_create_migration_batches_and_locks",
            "Create migration lock and receipt tables",
            """
            CREATE TABLE IF NOT EXISTS meta_migration_locks (
                namespace VARCHAR PRIMARY KEY,
                owner_id VARCHAR NOT NULL,
                acquired_at VARCHAR NOT NULL,
                expires_at VARCHAR NOT NULL,
                lease_token VARCHAR NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta_migration_receipts (
                receipt_id VARCHAR PRIMARY KEY,
                batch_id VARCHAR NOT NULL,
                namespace VARCHAR NOT NULL,
                version INTEGER NOT NULL,
                migration_id VARCHAR NOT NULL,
                checksum VARCHAR NOT NULL,
                owner_id VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                started_at VARCHAR NOT NULL,
                completed_at VARCHAR NOT NULL,
                schema_digest_before VARCHAR NOT NULL,
                schema_digest_after VARCHAR NOT NULL,
                dry_run BOOLEAN NOT NULL,
                rollback_json VARCHAR NOT NULL,
                error VARCHAR NOT NULL DEFAULT '',
                receipt_digest VARCHAR NOT NULL
            )
            """,
            CompatibilityWindow(2, 2),
        ),
    ]
    for version, migration_id, description, up_sql, window in specs:
        migrations.append(
            Migration(
                namespace=META_NAMESPACE,
                version=version,
                migration_id=migration_id,
                description=description,
                up_sql=up_sql.strip(),
                compatibility=window,
                rollback=RollbackMetadata(
                    strategy="none",
                    notes="meta bootstrap is forward-only; restore from backup",
                ),
            )
        )
    return migrations
