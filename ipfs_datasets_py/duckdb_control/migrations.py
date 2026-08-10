"""Namespaced, checksummed schema migration catalog and runner (DQK-003).

Migrations are ordered, replayable, and bound to a content checksum of their
SQL body.  Each step may declare a compatibility window (inclusive applied
schema-version bounds), optional rollback SQL metadata, and is applied under
exclusive lock ownership.

A fresh database and an upgraded database converge to the same schema digest.
Interrupted apply resumes or fails closed.  Unknown or modified migration
checksums are rejected.  Dry-run plans without mutating state.  Receipts are
immutable and content-addressable.

Importing this module is inert.  Applying migrations requires an explicit
:class:`MigrationRunner` call; unit tests use an in-memory backend.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Protocol, Sequence

__all__ = [
    "MIGRATION_CATALOG_SCHEMA",
    "MIGRATION_LOCK_SCHEMA",
    "MIGRATION_RECEIPT_SCHEMA",
    "Migration",
    "MigrationCatalog",
    "MigrationError",
    "MigrationLock",
    "MigrationLockError",
    "MigrationReceipt",
    "MigrationRunner",
    "MemoryMigrationBackend",
    "RollbackMetadata",
    "SCHEMA_DIGEST_PREFIX",
    "default_control_plane_migrations",
    "schema_digest_for",
]


MIGRATION_CATALOG_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-migration-catalog@1"
)
MIGRATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-migration-receipt@1"
)
MIGRATION_LOCK_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-migration-lock@1"
)
SCHEMA_DIGEST_PREFIX: Final[str] = "schema-digest:sha256:"

_LOCK_TTL_SECONDS: Final[int] = 300


class MigrationError(ValueError):
    """Fail-closed migration catalog or apply rejection."""


class MigrationLockError(MigrationError):
    """Exclusive migration lock cannot be acquired or is held by another owner."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Migration step
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RollbackMetadata:
    """Optional reversible metadata attached to a migration or receipt.

    Rollback is never automatic: operators use this plan to reverse a step.
    The ``down_sql`` body (when present) is checksummed independently of the
    forward migration so tampering is detectable.
    """

    strategy: str = "none"
    down_sql: str = ""
    notes: str = ""
    checksum: str = ""

    def __post_init__(self) -> None:
        strategy = str(self.strategy or "none").strip().lower()
        if strategy not in {"none", "manual", "sql"}:
            raise MigrationError(
                f"unsupported rollback strategy {self.strategy!r}; "
                "expected none|manual|sql"
            )
        object.__setattr__(self, "strategy", strategy)
        down = (self.down_sql or "").strip()
        if strategy == "sql" and not down:
            raise MigrationError("rollback strategy 'sql' requires down_sql")
        if strategy != "sql" and down:
            raise MigrationError(
                "down_sql is only valid when rollback strategy is 'sql'"
            )
        object.__setattr__(self, "down_sql", down)
        object.__setattr__(self, "notes", str(self.notes or "").strip())
        if down:
            expected = "sha256:" + _sha256_text(down + "\n")
            if self.checksum and self.checksum != expected:
                raise MigrationError(
                    f"rollback checksum mismatch "
                    f"(catalog {self.checksum}, computed {expected})"
                )
            object.__setattr__(self, "checksum", expected)
        elif self.checksum:
            raise MigrationError("rollback checksum without down_sql")
        else:
            object.__setattr__(self, "checksum", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "down_sql": self.down_sql,
            "notes": self.notes,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class Migration:
    """One ordered migration step with optional compatibility window.

    Compatibility window fields are inclusive schema *version* bounds for the
    already-applied maximum version.  A migration with
    ``compatible_from=1`` / ``compatible_to=3`` may only run when the highest
    applied version is in ``[1, 3]`` (or when nothing is applied and
    ``compatible_from`` is the bootstrap edge, i.e. ``None`` or ``0``).
    """

    migration_id: str
    version: int
    namespace: str
    description: str
    sql: str
    checksum: str = ""
    compatible_from: int | None = None
    compatible_to: int | None = None
    rollback: RollbackMetadata = field(default_factory=RollbackMetadata)

    def __post_init__(self) -> None:
        if not isinstance(self.migration_id, str) or not self.migration_id.strip():
            raise MigrationError("migration_id is required")
        object.__setattr__(self, "migration_id", self.migration_id.strip())
        if not isinstance(self.version, int) or isinstance(self.version, bool):
            raise MigrationError("version must be a positive integer")
        if self.version < 1:
            raise MigrationError("version must be a positive integer")
        if not isinstance(self.namespace, str) or not self.namespace.strip():
            raise MigrationError("namespace is required")
        object.__setattr__(self, "namespace", self.namespace.strip())
        if not isinstance(self.description, str):
            raise MigrationError("description must be text")
        object.__setattr__(self, "description", self.description.strip())
        if not isinstance(self.sql, str) or not self.sql.strip():
            raise MigrationError("sql body is required")
        # Normalize trailing newline for stable checksums.
        body = self.sql.strip() + "\n"
        object.__setattr__(self, "sql", body)
        expected = "sha256:" + _sha256_text(body)
        if self.checksum:
            if self.checksum != expected:
                raise MigrationError(
                    f"migration {self.migration_id} checksum mismatch "
                    f"(catalog {self.checksum}, computed {expected})"
                )
        else:
            object.__setattr__(self, "checksum", expected)

        for name in ("compatible_from", "compatible_to"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise MigrationError(f"{name} must be a non-negative int or None")
        if (
            self.compatible_from is not None
            and self.compatible_to is not None
            and self.compatible_from > self.compatible_to
        ):
            raise MigrationError(
                f"migration {self.migration_id} has inverted compatibility window "
                f"[{self.compatible_from}, {self.compatible_to}]"
            )
        if not isinstance(self.rollback, RollbackMetadata):
            raise MigrationError("rollback must be RollbackMetadata")

    def is_compatible_with(self, applied_max_version: int | None) -> bool:
        """Return whether this migration may run given the current applied max."""

        # Nothing applied yet: allow bootstrap when compatible_from is None or 0.
        if applied_max_version is None:
            if self.compatible_from is None or self.compatible_from == 0:
                return True
            return False
        if self.compatible_from is not None and applied_max_version < self.compatible_from:
            return False
        if self.compatible_to is not None and applied_max_version > self.compatible_to:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "version": self.version,
            "namespace": self.namespace,
            "description": self.description,
            "sql": self.sql,
            "checksum": self.checksum,
            "compatible_from": self.compatible_from,
            "compatible_to": self.compatible_to,
            "rollback": self.rollback.to_dict(),
        }


def default_control_plane_migrations() -> tuple[Migration, ...]:
    """Minimal bootstrap migrations for the datasets control plane."""

    return (
        Migration(
            migration_id="0001_schema_registry",
            version=1,
            namespace="duckdb_control",
            description="Schema registry and migration receipt tables",
            sql="""
CREATE TABLE IF NOT EXISTS schema_registry (
    namespace VARCHAR NOT NULL,
    schema_id VARCHAR NOT NULL,
    version INTEGER NOT NULL,
    checksum VARCHAR NOT NULL,
    installed_at VARCHAR NOT NULL,
    PRIMARY KEY (namespace, schema_id)
);
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id VARCHAR PRIMARY KEY,
    version INTEGER NOT NULL,
    namespace VARCHAR NOT NULL,
    checksum VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    applied_at VARCHAR NOT NULL,
    receipt_json VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_locks (
    lock_name VARCHAR PRIMARY KEY,
    owner_id VARCHAR NOT NULL,
    token VARCHAR NOT NULL,
    acquired_at VARCHAR NOT NULL,
    expires_at VARCHAR NOT NULL
);
""".strip(),
            compatible_from=0,
            compatible_to=0,
            rollback=RollbackMetadata(
                strategy="sql",
                down_sql="""
DROP TABLE IF EXISTS migration_locks;
DROP TABLE IF EXISTS schema_migrations;
DROP TABLE IF EXISTS schema_registry;
""".strip(),
                notes="Bootstrap reverse; only safe on empty control plane",
            ),
        ),
        Migration(
            migration_id="0002_control_snapshots",
            version=2,
            namespace="duckdb_control",
            description="Snapshot and generation bookkeeping",
            sql="""
CREATE TABLE IF NOT EXISTS store_generations (
    generation INTEGER PRIMARY KEY,
    schema_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS control_snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    generation INTEGER NOT NULL,
    schema_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    body_json VARCHAR NOT NULL
);
""".strip(),
            compatible_from=1,
            compatible_to=1,
            rollback=RollbackMetadata(
                strategy="sql",
                down_sql="""
DROP TABLE IF EXISTS control_snapshots;
DROP TABLE IF EXISTS store_generations;
""".strip(),
                notes="Drops snapshot bookkeeping tables",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationCatalog:
    """Ordered, namespaced, checksummed migration catalog."""

    SCHEMA: ClassVar[str] = MIGRATION_CATALOG_SCHEMA
    migrations: tuple[Migration, ...]
    namespace: str = "duckdb_control"

    def __post_init__(self) -> None:
        if not self.migrations:
            raise MigrationError("catalog must contain at least one migration")
        if not isinstance(self.namespace, str) or not self.namespace.strip():
            raise MigrationError("catalog namespace is required")
        object.__setattr__(self, "namespace", self.namespace.strip())
        seen_ids: set[str] = set()
        seen_versions: set[int] = set()
        ordered = tuple(sorted(self.migrations, key=lambda m: m.version))
        for item in ordered:
            if item.migration_id in seen_ids:
                raise MigrationError(f"duplicate migration_id {item.migration_id}")
            if item.version in seen_versions:
                raise MigrationError(f"duplicate version {item.version}")
            if item.namespace != self.namespace:
                raise MigrationError(
                    f"migration {item.migration_id} namespace mismatch "
                    f"(catalog {self.namespace}, migration {item.namespace})"
                )
            seen_ids.add(item.migration_id)
            seen_versions.add(item.version)
        versions = [m.version for m in ordered]
        if versions != list(range(versions[0], versions[0] + len(versions))):
            raise MigrationError("migration versions must be contiguous")
        object.__setattr__(self, "migrations", ordered)

    @property
    def digest(self) -> str:
        payload = [item.to_dict() for item in self.migrations]
        return "sha256:" + _sha256_text(_canonical_json(payload))

    def by_id(self, migration_id: str) -> Migration:
        for item in self.migrations:
            if item.migration_id == migration_id:
                return item
        raise MigrationError(f"migration {migration_id!r} not in catalog")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "namespace": self.namespace,
            "digest": self.digest,
            "migrations": [item.to_dict() for item in self.migrations],
        }


def schema_digest_for(applied: Sequence[Migration]) -> str:
    """Converge fresh and upgraded DBs to one digest of applied migrations.

    Digest inputs are migration identity + checksum + version only (not SQL
    bodies again) so partial upgrade paths that reach the same applied set
    always agree.
    """

    payload = [
        {
            "migration_id": m.migration_id,
            "checksum": m.checksum,
            "version": m.version,
        }
        for m in sorted(applied, key=lambda item: item.version)
    ]
    return SCHEMA_DIGEST_PREFIX + _sha256_text(_canonical_json(payload))


# ---------------------------------------------------------------------------
# Lock ownership
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationLock:
    """Exclusive lock ownership record for migration apply."""

    SCHEMA: ClassVar[str] = MIGRATION_LOCK_SCHEMA
    lock_name: str
    owner_id: str
    token: str
    acquired_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for name in ("lock_name", "owner_id", "token", "acquired_at", "expires_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise MigrationError(f"lock field {name} is required")
            object.__setattr__(self, name, value.strip())

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": self.SCHEMA,
            "lock_name": self.lock_name,
            "owner_id": self.owner_id,
            "token": self.token,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
        }

    @property
    def identity_id(self) -> str:
        return "sha256:" + _sha256_text(_canonical_json(self.to_dict()))


# ---------------------------------------------------------------------------
# Receipts (immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationReceipt:
    """Immutable apply receipt for one migration step."""

    SCHEMA: ClassVar[str] = MIGRATION_RECEIPT_SCHEMA
    migration_id: str
    checksum: str
    status: str
    schema_digest: str
    dry_run: bool = False
    resumed: bool = False
    lock_owner: str = ""
    version: int = 0
    namespace: str = ""
    rollback: RollbackMetadata = field(default_factory=RollbackMetadata)
    applied_at: str = field(default_factory=_utc_iso)
    receipt_id: str = ""

    def __post_init__(self) -> None:
        if not self.migration_id.strip():
            raise MigrationError("receipt migration_id is required")
        if not self.checksum.startswith("sha256:"):
            raise MigrationError("receipt checksum must be sha256:...")
        allowed = {
            "applied",
            "dry_run",
            "resumed",
            "failed",
            "skipped",
            "rolled_back",
        }
        if self.status not in allowed:
            raise MigrationError(f"unsupported receipt status {self.status!r}")
        if not self.schema_digest.startswith(SCHEMA_DIGEST_PREFIX):
            # dry-run of empty may still report a digest prefix; require form
            if not self.schema_digest.startswith("schema-digest:"):
                raise MigrationError("receipt schema_digest must use schema-digest prefix")
        if not isinstance(self.rollback, RollbackMetadata):
            raise MigrationError("receipt rollback must be RollbackMetadata")
        # Bind an immutable content id once; callers cannot rewrite fields.
        if not self.receipt_id:
            body = {
                "migration_id": self.migration_id,
                "checksum": self.checksum,
                "status": self.status,
                "schema_digest": self.schema_digest,
                "dry_run": self.dry_run,
                "resumed": self.resumed,
                "lock_owner": self.lock_owner,
                "version": self.version,
                "namespace": self.namespace,
                "rollback": self.rollback.to_dict(),
                "applied_at": self.applied_at,
            }
            object.__setattr__(
                self,
                "receipt_id",
                "sha256:" + _sha256_text(_canonical_json(body)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "receipt_id": self.receipt_id,
            "migration_id": self.migration_id,
            "checksum": self.checksum,
            "status": self.status,
            "schema_digest": self.schema_digest,
            "dry_run": self.dry_run,
            "resumed": self.resumed,
            "lock_owner": self.lock_owner,
            "version": self.version,
            "namespace": self.namespace,
            "rollback": self.rollback.to_dict(),
            "applied_at": self.applied_at,
        }


# ---------------------------------------------------------------------------
# Backend protocol + hermetic memory backend
# ---------------------------------------------------------------------------


class MigrationBackend(Protocol):
    def list_applied(self) -> Mapping[str, str]:
        """Return mapping migration_id -> checksum for applied migrations."""

    def applied_versions(self) -> Mapping[str, int]:
        """Return mapping migration_id -> version for applied migrations."""

    def begin(self) -> None: ...

    def execute(self, sql: str) -> None: ...

    def record_applied(self, migration: Migration, receipt: MigrationReceipt) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def get_in_progress(self) -> str | None:
        """Return migration_id marked in_progress, if any."""

    def mark_in_progress(self, migration_id: str) -> None: ...

    def acquire_lock(
        self,
        *,
        lock_name: str,
        owner_id: str,
        token: str,
        ttl_seconds: int = _LOCK_TTL_SECONDS,
    ) -> MigrationLock: ...

    def release_lock(self, *, lock_name: str, owner_id: str, token: str) -> None: ...

    def current_lock(self, lock_name: str) -> MigrationLock | None: ...


class MemoryMigrationBackend:
    """Hermetic backend for unit tests (no DuckDB required)."""

    def __init__(self) -> None:
        self.applied: dict[str, str] = {}
        self.applied_version_map: dict[str, int] = {}
        self.receipts: list[dict[str, Any]] = []
        self.statements: list[str] = []
        self._in_progress: str | None = None
        self._txn = False
        self._txn_statements: list[str] = []
        self._txn_applied: dict[str, str] | None = None
        self._txn_versions: dict[str, int] | None = None
        self._txn_receipts: list[dict[str, Any]] | None = None
        self._txn_in_progress: str | None = None
        self._locks: dict[str, MigrationLock] = {}
        self._lock_expiry_epoch: dict[str, float] = {}

    def list_applied(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.applied))

    def applied_versions(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self.applied_version_map))

    def begin(self) -> None:
        if self._txn:
            raise MigrationError("transaction already open")
        self._txn = True
        self._txn_statements = []
        self._txn_applied = dict(self.applied)
        self._txn_versions = dict(self.applied_version_map)
        self._txn_receipts = []
        self._txn_in_progress = self._in_progress

    def execute(self, sql: str) -> None:
        if not self._txn:
            raise MigrationError("execute requires an open transaction")
        self._txn_statements.append(sql)

    def record_applied(self, migration: Migration, receipt: MigrationReceipt) -> None:
        if not self._txn or self._txn_applied is None or self._txn_versions is None:
            raise MigrationError("record_applied requires an open transaction")
        self._txn_applied[migration.migration_id] = migration.checksum
        self._txn_versions[migration.migration_id] = migration.version
        self._txn_receipts = list(self._txn_receipts or [])
        self._txn_receipts.append(receipt.to_dict())
        self._txn_in_progress = None

    def commit(self) -> None:
        if not self._txn:
            raise MigrationError("no transaction to commit")
        self.statements.extend(self._txn_statements)
        if self._txn_applied is not None:
            self.applied = dict(self._txn_applied)
        if self._txn_versions is not None:
            self.applied_version_map = dict(self._txn_versions)
        if self._txn_receipts:
            self.receipts.extend(self._txn_receipts)
        self._in_progress = self._txn_in_progress
        self._txn_statements = []
        self._txn_applied = None
        self._txn_versions = None
        self._txn_receipts = None
        self._txn_in_progress = None
        self._txn = False

    def rollback(self) -> None:
        self._txn_statements = []
        self._txn_applied = None
        self._txn_versions = None
        self._txn_receipts = None
        self._txn_in_progress = None
        self._txn = False

    def get_in_progress(self) -> str | None:
        return self._in_progress

    def mark_in_progress(self, migration_id: str) -> None:
        # Persist in-progress outside the transaction so a crash mid-apply
        # still leaves a resume marker (fail-closed / resume contract).
        self._in_progress = migration_id
        if self._txn:
            self._txn_in_progress = migration_id

    def fail_mid_apply(self) -> None:
        """Simulate crash after mark_in_progress before commit."""

        self._txn_statements = []
        self._txn_applied = None
        self._txn_versions = None
        self._txn_receipts = None
        self._txn_in_progress = None
        self._txn = False
        # Leave _in_progress set.

    def acquire_lock(
        self,
        *,
        lock_name: str,
        owner_id: str,
        token: str,
        ttl_seconds: int = _LOCK_TTL_SECONDS,
    ) -> MigrationLock:
        now = time.time()
        existing = self._locks.get(lock_name)
        if existing is not None:
            exp_ts = self._lock_expiry_epoch.get(lock_name, 0.0)
            if exp_ts > now:
                if existing.owner_id != owner_id or existing.token != token:
                    raise MigrationLockError(
                        f"migration lock {lock_name!r} held by owner "
                        f"{existing.owner_id!r}"
                    )
                return existing
            # Expired — reclaimable.
            self._locks.pop(lock_name, None)
            self._lock_expiry_epoch.pop(lock_name, None)
        ttl = max(1, int(ttl_seconds))
        acquired = _utc_iso()
        expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + ttl))
        lock = MigrationLock(
            lock_name=lock_name,
            owner_id=owner_id,
            token=token,
            acquired_at=acquired,
            expires_at=expires,
        )
        self._locks[lock_name] = lock
        self._lock_expiry_epoch[lock_name] = now + ttl
        return lock

    def release_lock(self, *, lock_name: str, owner_id: str, token: str) -> None:
        existing = self._locks.get(lock_name)
        if existing is None:
            return
        if existing.owner_id != owner_id or existing.token != token:
            raise MigrationLockError(
                f"cannot release migration lock {lock_name!r}: ownership mismatch"
            )
        del self._locks[lock_name]
        self._lock_expiry_epoch.pop(lock_name, None)

    def current_lock(self, lock_name: str) -> MigrationLock | None:
        existing = self._locks.get(lock_name)
        if existing is None:
            return None
        if self._lock_expiry_epoch.get(lock_name, 0.0) <= time.time():
            self._locks.pop(lock_name, None)
            self._lock_expiry_epoch.pop(lock_name, None)
            return None
        return existing


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class MigrationRunner:
    """Apply a catalog against a backend with lock, resume, and checksum checks."""

    LOCK_NAME: ClassVar[str] = "duckdb_control.schema_migrations"

    def __init__(
        self,
        catalog: MigrationCatalog,
        backend: MigrationBackend,
        *,
        owner_id: str = "local",
    ) -> None:
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise MigrationError("owner_id is required")
        self.catalog = catalog
        self.backend = backend
        self.owner_id = owner_id.strip()
        self._lock_token: str | None = None

    def _applied_max_version(self) -> int | None:
        versions = list(self.backend.applied_versions().values())
        if not versions:
            # Fallback: derive from catalog for backends that only store checksums.
            applied_ids = set(self.backend.list_applied())
            if not applied_ids:
                return None
            known = [
                m.version
                for m in self.catalog.migrations
                if m.migration_id in applied_ids
            ]
            return max(known) if known else None
        return max(versions)

    def pending(self) -> tuple[Migration, ...]:
        applied = self.backend.list_applied()
        pending: list[Migration] = []
        for migration in self.catalog.migrations:
            checksum = applied.get(migration.migration_id)
            if checksum is None:
                pending.append(migration)
                continue
            if checksum != migration.checksum:
                raise MigrationError(
                    f"applied migration {migration.migration_id} checksum "
                    f"drift: stored {checksum}, catalog {migration.checksum}"
                )
        known = {m.migration_id for m in self.catalog.migrations}
        for applied_id in applied:
            if applied_id not in known:
                raise MigrationError(
                    f"unknown applied migration {applied_id!r} not in catalog"
                )
        return tuple(pending)

    def schema_digest(self) -> str:
        applied_ids = set(self.backend.list_applied())
        applied = [m for m in self.catalog.migrations if m.migration_id in applied_ids]
        return schema_digest_for(applied)

    def _assert_compatibility(self, migration: Migration) -> None:
        applied_max = self._applied_max_version()
        if not migration.is_compatible_with(applied_max):
            raise MigrationError(
                f"migration {migration.migration_id} outside compatibility window "
                f"compatible_from={migration.compatible_from} "
                f"compatible_to={migration.compatible_to} "
                f"applied_max_version={applied_max}"
            )

    def acquire_lock(self, *, ttl_seconds: int = _LOCK_TTL_SECONDS) -> MigrationLock:
        token = self._lock_token or uuid.uuid4().hex
        lock = self.backend.acquire_lock(
            lock_name=self.LOCK_NAME,
            owner_id=self.owner_id,
            token=token,
            ttl_seconds=ttl_seconds,
        )
        self._lock_token = lock.token
        return lock

    def release_lock(self) -> None:
        if self._lock_token is None:
            return
        self.backend.release_lock(
            lock_name=self.LOCK_NAME,
            owner_id=self.owner_id,
            token=self._lock_token,
        )
        self._lock_token = None

    def apply(
        self,
        *,
        dry_run: bool = False,
        resume: bool = True,
        hold_lock: bool = True,
    ) -> tuple[MigrationReceipt, ...]:
        in_progress = self.backend.get_in_progress()
        if in_progress and not resume:
            raise MigrationError(
                f"interrupted migration {in_progress!r} requires resume=True"
            )

        # Fail closed when an in-progress marker points at an unknown id.
        if in_progress is not None:
            known = {m.migration_id for m in self.catalog.migrations}
            if in_progress not in known:
                raise MigrationError(
                    f"interrupted migration {in_progress!r} is not in catalog"
                )
            applied = self.backend.list_applied()
            if in_progress in applied:
                # Stale marker after a successful apply — clear via resume path.
                pass
            elif in_progress not in {m.migration_id for m in self.pending()}:
                raise MigrationError(
                    f"interrupted migration {in_progress!r} is not pending "
                    "and not applied (fail closed)"
                )

        lock: MigrationLock | None = None
        if not dry_run and hold_lock:
            lock = self.acquire_lock()

        receipts: list[MigrationReceipt] = []
        # Simulated applied set for dry-run compatibility + digest planning.
        planned_ids = set(self.backend.list_applied())
        planned_max = self._applied_max_version()
        try:
            for migration in self.pending():
                resumed = in_progress == migration.migration_id

                # Compatibility: dry-run advances a planned max; live apply
                # reads backend state after each commit.
                if dry_run:
                    if not migration.is_compatible_with(planned_max):
                        raise MigrationError(
                            f"migration {migration.migration_id} outside "
                            f"compatibility window "
                            f"compatible_from={migration.compatible_from} "
                            f"compatible_to={migration.compatible_to} "
                            f"applied_max_version={planned_max}"
                        )
                else:
                    self._assert_compatibility(migration)

                if dry_run:
                    planned_ids.add(migration.migration_id)
                    planned_max = (
                        migration.version
                        if planned_max is None
                        else max(planned_max, migration.version)
                    )
                    provisional = schema_digest_for(
                        [
                            m
                            for m in self.catalog.migrations
                            if m.migration_id in planned_ids
                        ]
                    )
                    receipts.append(
                        MigrationReceipt(
                            migration_id=migration.migration_id,
                            checksum=migration.checksum,
                            status="dry_run",
                            schema_digest=provisional,
                            dry_run=True,
                            resumed=resumed,
                            lock_owner="",
                            version=migration.version,
                            namespace=migration.namespace,
                            rollback=migration.rollback,
                        )
                    )
                    continue

                self.backend.begin()
                try:
                    self.backend.mark_in_progress(migration.migration_id)
                    self.backend.execute(migration.sql)
                    provisional = schema_digest_for(
                        [
                            m
                            for m in self.catalog.migrations
                            if m.migration_id in self.backend.list_applied()
                            or m.migration_id == migration.migration_id
                        ]
                    )
                    receipt = MigrationReceipt(
                        migration_id=migration.migration_id,
                        checksum=migration.checksum,
                        status="applied",
                        schema_digest=provisional,
                        dry_run=False,
                        resumed=resumed,
                        lock_owner=self.owner_id if lock is not None else "",
                        version=migration.version,
                        namespace=migration.namespace,
                        rollback=migration.rollback,
                    )
                    self.backend.record_applied(migration, receipt)
                    self.backend.commit()
                    receipts.append(receipt)
                    in_progress = None
                except Exception:
                    self.backend.rollback()
                    raise
            return tuple(receipts)
        finally:
            if lock is not None:
                try:
                    self.release_lock()
                except MigrationLockError:
                    # Prefer not masking a successful apply with a release race.
                    pass
