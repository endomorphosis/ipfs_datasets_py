"""Namespaced, checksummed schema migration catalog and runner (DQK-003).

Migrations are ordered, replayable, and bound to a content checksum of their
SQL body.  A fresh database and an upgraded database converge to the same
schema digest.  Interrupted apply resumes or fails closed.  Unknown or
modified migration checksums are rejected.

Importing this module is inert.  Applying migrations requires an explicit
:class:`MigrationRunner` call; unit tests use an in-memory backend.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Final, Mapping, Protocol, Sequence

__all__ = [
    "MIGRATION_CATALOG_SCHEMA",
    "MIGRATION_RECEIPT_SCHEMA",
    "Migration",
    "MigrationCatalog",
    "MigrationError",
    "MigrationReceipt",
    "MigrationRunner",
    "MemoryMigrationBackend",
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
SCHEMA_DIGEST_PREFIX: Final[str] = "schema-digest:sha256:"


class MigrationError(ValueError):
    """Fail-closed migration catalog or apply rejection."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class Migration:
    """One ordered migration step."""

    migration_id: str
    version: int
    namespace: str
    description: str
    sql: str
    checksum: str = ""

    def __post_init__(self) -> None:
        if not self.migration_id.strip():
            raise MigrationError("migration_id is required")
        if not isinstance(self.version, int) or self.version < 1:
            raise MigrationError("version must be a positive integer")
        if not self.namespace.strip():
            raise MigrationError("namespace is required")
        if not self.sql.strip():
            raise MigrationError("sql body is required")
        expected = "sha256:" + _sha256_text(self.sql.strip() + "\n")
        if self.checksum:
            if self.checksum != expected:
                raise MigrationError(
                    f"migration {self.migration_id} checksum mismatch "
                    f"(catalog {self.checksum}, computed {expected})"
                )
        else:
            object.__setattr__(self, "checksum", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "version": self.version,
            "namespace": self.namespace,
            "description": self.description,
            "sql": self.sql,
            "checksum": self.checksum,
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
""".strip(),
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
        ),
    )


@dataclass(frozen=True)
class MigrationCatalog:
    SCHEMA: ClassVar[str] = MIGRATION_CATALOG_SCHEMA
    migrations: tuple[Migration, ...]
    namespace: str = "duckdb_control"

    def __post_init__(self) -> None:
        if not self.migrations:
            raise MigrationError("catalog must contain at least one migration")
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
                    f"migration {item.migration_id} namespace mismatch"
                )
            seen_ids.add(item.migration_id)
            seen_versions.add(item.version)
        # Ensure strictly increasing versions in order.
        versions = [m.version for m in ordered]
        if versions != list(range(versions[0], versions[0] + len(versions))):
            raise MigrationError("migration versions must be contiguous")
        object.__setattr__(self, "migrations", ordered)

    @property
    def digest(self) -> str:
        payload = [item.to_dict() for item in self.migrations]
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + _sha256_text(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "namespace": self.namespace,
            "digest": self.digest,
            "migrations": [item.to_dict() for item in self.migrations],
        }


def schema_digest_for(applied: Sequence[Migration]) -> str:
    """Converge fresh and upgraded DBs to one digest of applied migrations."""

    payload = [
        {"migration_id": m.migration_id, "checksum": m.checksum, "version": m.version}
        for m in sorted(applied, key=lambda item: item.version)
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return SCHEMA_DIGEST_PREFIX + _sha256_text(raw)


@dataclass(frozen=True)
class MigrationReceipt:
    SCHEMA: ClassVar[str] = MIGRATION_RECEIPT_SCHEMA
    migration_id: str
    checksum: str
    status: str
    schema_digest: str
    dry_run: bool = False
    resumed: bool = False
    applied_at: str = field(default_factory=_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "migration_id": self.migration_id,
            "checksum": self.checksum,
            "status": self.status,
            "schema_digest": self.schema_digest,
            "dry_run": self.dry_run,
            "resumed": self.resumed,
            "applied_at": self.applied_at,
        }


class MigrationBackend(Protocol):
    def list_applied(self) -> Mapping[str, str]:
        """Return mapping migration_id -> checksum for applied migrations."""

    def begin(self) -> None: ...
    def execute(self, sql: str) -> None: ...
    def record_applied(self, migration: Migration, receipt: MigrationReceipt) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def get_in_progress(self) -> str | None:
        """Return migration_id marked in_progress, if any."""

    def mark_in_progress(self, migration_id: str) -> None: ...


class MemoryMigrationBackend:
    """Hermetic backend for unit tests (no DuckDB required)."""

    def __init__(self) -> None:
        self.applied: dict[str, str] = {}
        self.receipts: list[dict[str, Any]] = []
        self.statements: list[str] = []
        self._in_progress: str | None = None
        self._txn = False
        self._txn_statements: list[str] = []

    def list_applied(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.applied))

    def begin(self) -> None:
        if self._txn:
            raise MigrationError("transaction already open")
        self._txn = True
        self._txn_statements = []

    def execute(self, sql: str) -> None:
        if not self._txn:
            raise MigrationError("execute requires an open transaction")
        self._txn_statements.append(sql)

    def record_applied(self, migration: Migration, receipt: MigrationReceipt) -> None:
        if not self._txn:
            raise MigrationError("record_applied requires an open transaction")
        self.applied[migration.migration_id] = migration.checksum
        self.receipts.append(receipt.to_dict())
        self._in_progress = None

    def commit(self) -> None:
        if not self._txn:
            raise MigrationError("no transaction to commit")
        self.statements.extend(self._txn_statements)
        self._txn_statements = []
        self._txn = False

    def rollback(self) -> None:
        self._txn_statements = []
        self._txn = False

    def get_in_progress(self) -> str | None:
        return self._in_progress

    def mark_in_progress(self, migration_id: str) -> None:
        self._in_progress = migration_id

    def fail_mid_apply(self) -> None:
        """Simulate crash after mark_in_progress before commit."""

        self._txn_statements = []
        self._txn = False


class MigrationRunner:
    """Apply a catalog against a backend with resume and checksum enforcement."""

    def __init__(
        self,
        catalog: MigrationCatalog,
        backend: MigrationBackend,
    ) -> None:
        self.catalog = catalog
        self.backend = backend

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
        # Reject unknown applied ids.
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

    def apply(
        self,
        *,
        dry_run: bool = False,
        resume: bool = True,
    ) -> tuple[MigrationReceipt, ...]:
        in_progress = self.backend.get_in_progress()
        if in_progress and not resume:
            raise MigrationError(
                f"interrupted migration {in_progress!r} requires resume=True"
            )

        receipts: list[MigrationReceipt] = []
        for migration in self.pending():
            resumed = in_progress == migration.migration_id
            if dry_run:
                receipts.append(
                    MigrationReceipt(
                        migration_id=migration.migration_id,
                        checksum=migration.checksum,
                        status="dry_run",
                        schema_digest=self.schema_digest(),
                        dry_run=True,
                        resumed=resumed,
                    )
                )
                continue
            self.backend.begin()
            try:
                self.backend.mark_in_progress(migration.migration_id)
                self.backend.execute(migration.sql)
                # provisional digest includes this migration
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
                )
                self.backend.record_applied(migration, receipt)
                self.backend.commit()
                receipts.append(receipt)
                in_progress = None
            except Exception:
                self.backend.rollback()
                raise
        return tuple(receipts)
