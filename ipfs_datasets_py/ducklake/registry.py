"""Typed dual-scope lake registries (DQK-086).

The small **control** DuckDB is the sole writer for catalog-shard identities,
dataset-to-home-shard routing, owner-generation leases, snapshot-vector roots,
shard-migration receipts, promotion/release decisions, and signed shard
projections.

Each shard owns a separate private **companion** owner-control DuckDB for
shard-local sources, schemas, file identities, ingest receipts, reader leases,
logical-key reservations, outbox entries, ownership state, maintenance
authorizations, retention, and publication lineage. Companion registries run in
a private DuckDB ``DatabaseInstance`` that is never ATTACHed to or visible from
the Quack-serving ``DatabaseInstance``; owner-side code exchanges only typed
content-bound records.

Home-shard moves drain source and destination owners, then complete one fenced
control-DB CAS receipt before either side resumes. Signed shard projections are
content-bound caches; stale projections fail owner startup.

Import is side-effect free. Unit tests use hermetic memory stores that survive
simulated restart without requiring the optional ``duckdb`` package.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence

from ipfs_datasets_py.duckdb_control.migrations import (
    MemoryMigrationBackend,
    MigrationCatalog,
    MigrationReceipt,
    MigrationRunner,
    SCHEMA_DIGEST_PREFIX,
    schema_digest_for,
)
from ipfs_datasets_py.ducklake.schema import (
    COMPANION_NAMESPACE,
    COMPANION_TABLES,
    CONTROL_NAMESPACE,
    ContentIdentity,
    IdentityKind,
    LakeIdentityError,
    LakeSchemaError,
    LogicalDatasetAlias,
    RegistryScope,
    SnapshotIdentity,
    authority_table_matrix,
    companion_migration_catalog,
    control_migration_catalog,
    is_ducklake_internal_table,
    scope_for_table,
)

__all__ = [
    "COMPANION_REGISTRY_SCHEMA",
    "CONTROL_REGISTRY_SCHEMA",
    "DATABASE_INSTANCE_SCHEMA",
    "HOME_SHARD_MOVE_RECEIPT_SCHEMA",
    "SIGNED_SHARD_PROJECTION_SCHEMA",
    "AuthorityViolation",
    "CasConflict",
    "CompanionLakeRegistry",
    "ControlLakeRegistry",
    "DatabaseInstanceBinding",
    "DatabaseInstanceKind",
    "HomeShardMoveReceipt",
    "HomeShardMoveStatus",
    "IdempotentReplay",
    "MemoryRegistryStore",
    "OwnerDrainState",
    "RegistryError",
    "RegistryMigrationGate",
    "SignedShardProjection",
    "StaleProjectionError",
    "UnsupportedCrossShardUniqueness",
    "apply_registry_migrations",
    "assert_no_mutable_manifest_authority",
    "authority_table_matrix",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

CONTROL_REGISTRY_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-control-registry@1"
COMPANION_REGISTRY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-companion-registry@1"
)
DATABASE_INSTANCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-database-instance@1"
)
HOME_SHARD_MOVE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-home-shard-move-receipt@1"
)
SIGNED_SHARD_PROJECTION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-signed-shard-projection@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-086-lake-registry-repos-20260810"
)

# Tables companions must never redefine (global control authority).
_COMPANION_FORBIDDEN_WRITES: Final[frozenset[str]] = frozenset(
    {
        "lake_catalogs",
        "lake_catalog_shards",
        "lake_dataset_home_shards",
        "lake_catalog_owner_generations",
        "lake_snapshot_vector_roots",
        "lake_shard_migrations",
        "lake_promotion_decisions",
        "lake_promotion_executions",
        "lake_release_receipts",
        "lake_signed_shard_projections",
        "lake_datasets",
        # acceptance short names
        "lake_catalog",
        "dataset_home_shard",
        "catalog_owner_generation",
        "snapshot_vector_root",
        "shard_migration",
        "promotion_decision",
        "promotion_execution",
    }
)

# Tables only control may write.
_CONTROL_EXCLUSIVE: Final[frozenset[str]] = frozenset(
    {
        "lake_catalogs",
        "lake_catalog_shards",
        "lake_datasets",
        "lake_dataset_home_shards",
        "lake_catalog_owner_generations",
        "lake_snapshot_vector_roots",
        "lake_shard_migrations",
        "lake_promotion_decisions",
        "lake_promotion_executions",
        "lake_release_receipts",
        "lake_signed_shard_projections",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RegistryError(ValueError):
    """Fail-closed lake registry rejection."""


class AuthorityViolation(RegistryError):
    """A scope attempted to write outside its exclusive authority."""


class CasConflict(RegistryError):
    """Compare-and-swap revision mismatch."""


class UnsupportedCrossShardUniqueness(RegistryError):
    """Uniqueness/reference scope does not resolve to one home shard."""


class StaleProjectionError(RegistryError):
    """Signed shard projection is stale relative to expected content digest."""


class IdempotentReplay(RegistryError):
    """Idempotency key reused with a different request digest (fail closed)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_of(payload: Any) -> str:
    return "sha256:" + _sha256_text(_canonical_json(payload))


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RegistryError(f"{field_name} is required")
    return text


def assert_no_mutable_manifest_authority(
    *,
    source: str,
    is_mutable_json: bool = False,
    is_mutable_parquet_manifest: bool = False,
) -> None:
    """Reject treating mutable JSON or Parquet manifests as authority."""

    if is_mutable_json or is_mutable_parquet_manifest:
        raise RegistryError(
            f"mutable JSON/Parquet manifest is not authoritative "
            f"(source={source!r}); authority lives in control/companion DuckDB "
            "registry tables"
        )


# ---------------------------------------------------------------------------
# Database instance isolation
# ---------------------------------------------------------------------------


class DatabaseInstanceKind(str, Enum):
    """Kinds of DuckDB DatabaseInstance used by the lake topology."""

    CONTROL = "control"
    COMPANION_PRIVATE = "companion_private"
    QUACK_SERVING = "quack_serving"


@dataclass(frozen=True, slots=True)
class DatabaseInstanceBinding:
    """Binding for one DuckDB DatabaseInstance (never cross-attached).

    Companion registries use ``COMPANION_PRIVATE``. The Quack-serving instance
    is a separate binding; companions are never ATTACHed into it.
    """

    SCHEMA: ClassVar[str] = DATABASE_INSTANCE_SCHEMA
    instance_id: str
    kind: DatabaseInstanceKind
    path: str = ":memory:"
    private: bool = True
    attachable_from_quack: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instance_id",
            _require_nonempty(self.instance_id, field_name="instance_id"),
        )
        kind = self.kind
        if not isinstance(kind, DatabaseInstanceKind):
            kind = DatabaseInstanceKind(str(kind))
            object.__setattr__(self, "kind", kind)
        path = str(self.path or ":memory:").strip() or ":memory:"
        object.__setattr__(self, "path", path)
        if kind is DatabaseInstanceKind.COMPANION_PRIVATE:
            if not self.private:
                raise RegistryError("companion DatabaseInstance must be private")
            if self.attachable_from_quack:
                raise RegistryError(
                    "companion registry DatabaseInstance must never be attachable "
                    "from the Quack-serving DatabaseInstance"
                )
        if kind is DatabaseInstanceKind.QUACK_SERVING and self.private:
            # Quack-serving may be private to its process, but is never a companion.
            pass

    def assert_not_attached_to(self, other: DatabaseInstanceBinding) -> None:
        """Fail closed if this instance would be visible from ``other``."""

        if self.instance_id == other.instance_id:
            raise RegistryError(
                "companion and Quack-serving must use distinct DatabaseInstance ids"
            )
        if (
            self.kind is DatabaseInstanceKind.COMPANION_PRIVATE
            and other.kind is DatabaseInstanceKind.QUACK_SERVING
            and self.attachable_from_quack
        ):
            raise RegistryError(
                "companion registry must never be ATTACHed to or visible from "
                "the Quack-serving DatabaseInstance"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": DATABASE_INSTANCE_SCHEMA,
                "instance_id": self.instance_id,
                "kind": self.kind.value,
                "path": self.path,
                "private": self.private,
                "attachable_from_quack": self.attachable_from_quack,
            }
        )


# ---------------------------------------------------------------------------
# Migration gate (owner-gated apply)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegistryMigrationGate:
    """Owner-gated migration apply for one registry scope."""

    scope: RegistryScope
    owner_id: str
    authorized: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.scope, RegistryScope):
            object.__setattr__(self, "scope", RegistryScope(str(self.scope)))
        object.__setattr__(
            self, "owner_id", _require_nonempty(self.owner_id, field_name="owner_id")
        )


def apply_registry_migrations(
    catalog: MigrationCatalog,
    backend: MemoryMigrationBackend,
    *,
    gate: RegistryMigrationGate,
    dry_run: bool = False,
    resume: bool = True,
) -> tuple[MigrationReceipt, ...]:
    """Apply checksummed migrations under exclusive owner gate."""

    if not gate.authorized:
        raise RegistryError(
            f"migrations for scope {gate.scope.value} require authorized owner gate "
            f"(owner_id={gate.owner_id!r})"
        )
    expected_ns = (
        CONTROL_NAMESPACE
        if gate.scope is RegistryScope.CONTROL
        else COMPANION_NAMESPACE
    )
    if catalog.namespace != expected_ns:
        raise RegistryError(
            f"catalog namespace {catalog.namespace!r} does not match gate scope "
            f"{gate.scope.value} (expected {expected_ns})"
        )
    # Reject any migration body that would touch DuckLake internals.
    for migration in catalog.migrations:
        for line in migration.sql.splitlines():
            for token in line.replace("(", " ").replace(",", " ").split():
                name = token.strip("`\"'").lower()
                if is_ducklake_internal_table(name):
                    raise LakeSchemaError(
                        f"migration {migration.migration_id} references DuckLake "
                        f"internal table {name!r}"
                    )
    runner = MigrationRunner(catalog, backend, owner_id=gate.owner_id)
    # Scope-specific lock name so control and companion never share a lock.
    lock_name = f"ducklake.{gate.scope.value}.schema_migrations"
    original_lock = MigrationRunner.LOCK_NAME
    try:
        # Temporarily specialize lock name for this apply.
        MigrationRunner.LOCK_NAME = lock_name  # type: ignore[misc]
        return runner.apply(dry_run=dry_run, resume=resume)
    finally:
        MigrationRunner.LOCK_NAME = original_lock  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Memory store (restart-survivable)
# ---------------------------------------------------------------------------


class MemoryRegistryStore:
    """Hermetic multi-table store with CAS, idempotency, and restart dump/load.

    Simulates a single DuckDB file without importing ``duckdb``. State dumped
    via :meth:`export_state` and reloaded via :meth:`import_state` models
    process restart while preserving CAS revisions and provenance.
    """

    def __init__(self, *, scope: RegistryScope, instance_id: str = "") -> None:
        if not isinstance(scope, RegistryScope):
            scope = RegistryScope(str(scope))
        self.scope = scope
        self.instance_id = instance_id or uuid.uuid4().hex
        self._lock = threading.RLock()
        self.tables: dict[str, dict[str, dict[str, Any]]] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}
        self.owner_drain: dict[str, str] = {}
        self.schema_digest: str = SCHEMA_DIGEST_PREFIX + ("00" * 32)
        self.migration_backend = MemoryMigrationBackend()
        self._attached_from: set[str] = set()

    def export_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "scope": self.scope.value,
                "instance_id": self.instance_id,
                "tables": copy.deepcopy(self.tables),
                "idempotency": copy.deepcopy(self.idempotency),
                "owner_drain": dict(self.owner_drain),
                "schema_digest": self.schema_digest,
                "migration_applied": dict(self.migration_backend.list_applied()),
                "migration_versions": dict(self.migration_backend.applied_versions()),
                "migration_receipts": list(self.migration_backend.receipts),
                "in_progress": self.migration_backend.get_in_progress(),
            }

    def import_state(self, state: Mapping[str, Any]) -> None:
        with self._lock:
            scope = RegistryScope(str(state["scope"]))
            if scope is not self.scope:
                raise RegistryError(
                    f"cannot import state for scope {scope.value} into {self.scope.value}"
                )
            self.instance_id = str(state.get("instance_id") or self.instance_id)
            self.tables = copy.deepcopy(dict(state.get("tables") or {}))
            self.idempotency = copy.deepcopy(dict(state.get("idempotency") or {}))
            self.owner_drain = dict(state.get("owner_drain") or {})
            self.schema_digest = str(
                state.get("schema_digest") or self.schema_digest
            )
            backend = MemoryMigrationBackend()
            backend.applied = dict(state.get("migration_applied") or {})
            backend.applied_version_map = dict(state.get("migration_versions") or {})
            backend.receipts = list(state.get("migration_receipts") or [])
            in_progress = state.get("in_progress")
            if in_progress:
                backend.mark_in_progress(str(in_progress))
            self.migration_backend = backend

    def mark_attached_from(self, other_instance_id: str) -> None:
        """Record an illegal ATTACH for isolation tests."""

        self._attached_from.add(str(other_instance_id))

    def is_visible_from(self, other_instance_id: str) -> bool:
        return str(other_instance_id) in self._attached_from

    def _table(self, name: str) -> dict[str, dict[str, Any]]:
        return self.tables.setdefault(name, {})

    def get_row(self, table: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._table(table).get(key)
            return None if row is None else copy.deepcopy(row)

    def list_rows(self, table: str) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(v) for v in self._table(table).values()]

    def cas_upsert(
        self,
        table: str,
        key: str,
        row: Mapping[str, Any],
        *,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        with self._lock:
            store = self._table(table)
            existing = store.get(key)
            if existing is None:
                if expected_revision not in (None, 0):
                    raise CasConflict(
                        f"CAS create {table}/{key}: expected revision "
                        f"{expected_revision}, found missing"
                    )
                new_rev = 1
            else:
                current = int(existing.get("cas_revision", 0))
                if expected_revision is None:
                    raise CasConflict(
                        f"CAS update {table}/{key} requires expected_revision"
                    )
                if current != int(expected_revision):
                    raise CasConflict(
                        f"CAS conflict {table}/{key}: expected {expected_revision}, "
                        f"found {current}"
                    )
                new_rev = current + 1
            payload = dict(row)
            payload["cas_revision"] = new_rev
            store[key] = payload
            return copy.deepcopy(payload)

    def put_if_absent(
        self, table: str, key: str, row: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            store = self._table(table)
            if key in store:
                return copy.deepcopy(store[key]), False
            payload = dict(row)
            payload.setdefault("cas_revision", 1)
            store[key] = payload
            return copy.deepcopy(payload), True

    def remember_idempotent(
        self,
        *,
        key: str,
        operation: str,
        request_digest: str,
        response: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        with self._lock:
            existing = self.idempotency.get(key)
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    raise IdempotentReplay(
                        f"idempotency key {key!r} reused with different request "
                        f"(stored {existing['request_digest']}, got {request_digest})"
                    )
                if existing["operation"] != operation:
                    raise IdempotentReplay(
                        f"idempotency key {key!r} bound to operation "
                        f"{existing['operation']!r}, not {operation!r}"
                    )
                return MappingProxyType(copy.deepcopy(existing["response"]))
            record = {
                "idempotency_key": key,
                "operation": operation,
                "request_digest": request_digest,
                "response": copy.deepcopy(dict(response)),
                "cas_revision": 1,
                "created_at": _utc_iso(),
            }
            self.idempotency[key] = record
            return MappingProxyType(copy.deepcopy(record["response"]))

    def lookup_idempotent(self, key: str) -> Mapping[str, Any] | None:
        with self._lock:
            existing = self.idempotency.get(key)
            if existing is None:
                return None
            return MappingProxyType(copy.deepcopy(existing["response"]))


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


class OwnerDrainState(str, Enum):
    ACTIVE = "active"
    DRAINING = "draining"
    DRAINED = "drained"
    RESUMED = "resumed"


class HomeShardMoveStatus(str, Enum):
    PENDING = "pending"
    DRAINED = "drained"
    COMMITTED = "committed"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class HomeShardMoveReceipt:
    """Fenced control-DB CAS receipt for one home-shard move."""

    SCHEMA: ClassVar[str] = HOME_SHARD_MOVE_RECEIPT_SCHEMA
    migration_receipt_id: str
    dataset_id: str
    source_shard_id: str
    destination_shard_id: str
    source_drained: bool
    destination_drained: bool
    fence_token: str
    cas_revision: int
    status: HomeShardMoveStatus
    receipt_digest: str
    created_at: str
    completed_at: str = ""

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HOME_SHARD_MOVE_RECEIPT_SCHEMA,
                "migration_receipt_id": self.migration_receipt_id,
                "dataset_id": self.dataset_id,
                "source_shard_id": self.source_shard_id,
                "destination_shard_id": self.destination_shard_id,
                "source_drained": self.source_drained,
                "destination_drained": self.destination_drained,
                "fence_token": self.fence_token,
                "cas_revision": self.cas_revision,
                "status": self.status.value
                if isinstance(self.status, HomeShardMoveStatus)
                else str(self.status),
                "receipt_digest": self.receipt_digest,
                "created_at": self.created_at,
                "completed_at": self.completed_at,
            }
        )


@dataclass(frozen=True, slots=True)
class SignedShardProjection:
    """Content-bound signed projection cache for one shard (not authority)."""

    SCHEMA: ClassVar[str] = SIGNED_SHARD_PROJECTION_SCHEMA
    projection_id: str
    shard_id: str
    content_digest: str
    signature: str
    signer_identity: str
    payload: Mapping[str, Any]
    cas_revision: int = 1
    issued_at: str = ""
    expires_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "projection_id",
            _require_nonempty(self.projection_id, field_name="projection_id"),
        )
        object.__setattr__(
            self, "shard_id", _require_nonempty(self.shard_id, field_name="shard_id")
        )
        digest = str(self.content_digest or "").strip()
        if not digest.startswith("sha256:") or len(digest) != 71:
            # Allow caller to omit and recompute from payload.
            computed = _digest_of(dict(self.payload))
            if digest and digest != computed:
                raise RegistryError(
                    f"signed projection content_digest mismatch "
                    f"(given {digest}, computed {computed})"
                )
            object.__setattr__(self, "content_digest", computed)
        object.__setattr__(
            self,
            "signature",
            _require_nonempty(self.signature, field_name="signature"),
        )
        object.__setattr__(
            self,
            "signer_identity",
            _require_nonempty(self.signer_identity, field_name="signer_identity"),
        )
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": SIGNED_SHARD_PROJECTION_SCHEMA,
                "projection_id": self.projection_id,
                "shard_id": self.shard_id,
                "content_digest": self.content_digest,
                "signature": self.signature,
                "signer_identity": self.signer_identity,
                "payload": dict(self.payload),
                "cas_revision": self.cas_revision,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "cache_only": True,
                "authoritative": False,
            }
        )


# ---------------------------------------------------------------------------
# Control registry
# ---------------------------------------------------------------------------


class ControlLakeRegistry:
    """Sole writer for control-scope lake registry authority tables."""

    SCHEMA: Final[str] = CONTROL_REGISTRY_SCHEMA
    SCOPE: Final[RegistryScope] = RegistryScope.CONTROL

    def __init__(
        self,
        store: MemoryRegistryStore | None = None,
        *,
        owner_id: str = "control-owner",
        instance: DatabaseInstanceBinding | None = None,
    ) -> None:
        self.store = store or MemoryRegistryStore(scope=RegistryScope.CONTROL)
        if self.store.scope is not RegistryScope.CONTROL:
            raise RegistryError("ControlLakeRegistry requires a control-scope store")
        self.owner_id = _require_nonempty(owner_id, field_name="owner_id")
        self.instance = instance or DatabaseInstanceBinding(
            instance_id=f"control-{self.store.instance_id}",
            kind=DatabaseInstanceKind.CONTROL,
            path=":memory:control",
            private=True,
            attachable_from_quack=False,
        )
        self._migrations_applied = False
        self._lock = threading.RLock()

    # -- migrations --------------------------------------------------------

    def apply_migrations(
        self, *, dry_run: bool = False, resume: bool = True
    ) -> tuple[MigrationReceipt, ...]:
        gate = RegistryMigrationGate(
            scope=RegistryScope.CONTROL,
            owner_id=self.owner_id,
            authorized=True,
        )
        receipts = apply_registry_migrations(
            control_migration_catalog(),
            self.store.migration_backend,
            gate=gate,
            dry_run=dry_run,
            resume=resume,
        )
        if not dry_run:
            self._migrations_applied = True
            self.store.schema_digest = schema_digest_for(
                list(control_migration_catalog().migrations)
            )
        return receipts

    def require_migrated(self) -> None:
        applied = set(self.store.migration_backend.list_applied())
        expected = {m.migration_id for m in control_migration_catalog().migrations}
        if applied != expected and not expected.issubset(applied):
            raise RegistryError(
                "control registry migrations not fully applied "
                f"(applied={sorted(applied)}, expected={sorted(expected)})"
            )
        self._migrations_applied = True

    # -- authority guards --------------------------------------------------

    def assert_control_authority(self, table: str) -> None:
        name = str(table or "").strip()
        if name in _COMPANION_FORBIDDEN_WRITES or name in _CONTROL_EXCLUSIVE:
            return
        try:
            if scope_for_table(name) is RegistryScope.CONTROL:
                return
        except LakeSchemaError:
            pass
        # Allow acceptance short names already covered.
        if name in {
            "lake_catalog",
            "dataset_home_shard",
            "catalog_owner_generation",
            "snapshot_vector_root",
            "shard_migration",
            "promotion_decision",
            "promotion_execution",
            "lake_release_receipts",
        }:
            return
        raise AuthorityViolation(
            f"table {table!r} is not under control registry exclusive authority"
        )

    def reject_companion_authority_write(self, table: str) -> None:
        """Control does not own companion-local operational tables as primary
        writer for shard-local state (except routing identity)."""

        try:
            scope = scope_for_table(table)
        except LakeSchemaError:
            return
        if scope is RegistryScope.COMPANION:
            raise AuthorityViolation(
                f"control registry does not own companion table {table!r} "
                "(reader_lease, logical_key_reservation, ingest_outbox, "
                "maintenance_authorization are companion-scoped)"
            )

    # -- catalogs / shards -------------------------------------------------

    def register_catalog(
        self,
        *,
        catalog_id: str,
        catalog_digest: str,
        storage_kind: str,
        metadata_path: str,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_catalogs")
        cid = _require_nonempty(catalog_id, field_name="catalog_id")
        request = {
            "catalog_id": cid,
            "catalog_digest": _require_nonempty(
                catalog_digest, field_name="catalog_digest"
            ),
            "storage_kind": _require_nonempty(
                storage_kind, field_name="storage_kind"
            ),
            "metadata_path": _require_nonempty(
                metadata_path, field_name="metadata_path"
            ),
        }
        req_digest = _digest_of(request)
        if idempotency_key:
            prior = self.store.lookup_idempotent(idempotency_key)
            if prior is not None:
                return self.store.remember_idempotent(
                    key=idempotency_key,
                    operation="register_catalog",
                    request_digest=req_digest,
                    response=prior,
                )
        now = _utc_iso()
        row = {
            **request,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "provenance_json": _canonical_json(
                {"owner_id": self.owner_id, "implementation": _IMPLEMENTATION_GENERATION}
            ),
        }
        stored, created = self.store.put_if_absent("lake_catalogs", cid, row)
        if not created and stored.get("catalog_digest") != request["catalog_digest"]:
            raise CasConflict(
                f"catalog {cid!r} already registered with different digest"
            )
        result = MappingProxyType(stored)
        if idempotency_key:
            return self.store.remember_idempotent(
                key=idempotency_key,
                operation="register_catalog",
                request_digest=req_digest,
                response=result,
            )
        return result

    def register_shard(
        self,
        *,
        shard_id: str,
        catalog_id: str,
        ring_position: int,
        endpoint_identity: str,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_catalog_shards")
        if self.store.get_row("lake_catalogs", catalog_id) is None:
            raise RegistryError(f"unknown catalog_id {catalog_id!r}")
        if (
            not isinstance(ring_position, int)
            or isinstance(ring_position, bool)
            or ring_position < 0
        ):
            raise RegistryError("ring_position must be a non-negative int")
        sid = _require_nonempty(shard_id, field_name="shard_id")
        # Enforce unique (catalog_id, ring_position) before insert.
        for other in self.store.list_rows("lake_catalog_shards"):
            if (
                other["shard_id"] != sid
                and other["catalog_id"] == catalog_id
                and int(other["ring_position"]) == ring_position
            ):
                raise RegistryError(
                    f"ring position {ring_position} already used in catalog {catalog_id!r}"
                )
        now = _utc_iso()
        row = {
            "shard_id": sid,
            "catalog_id": catalog_id,
            "ring_position": ring_position,
            "endpoint_identity": _require_nonempty(
                endpoint_identity, field_name="endpoint_identity"
            ),
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        stored, created = self.store.put_if_absent("lake_catalog_shards", sid, row)
        if not created:
            if (
                stored["catalog_id"] != catalog_id
                or int(stored["ring_position"]) != ring_position
            ):
                raise CasConflict(
                    f"shard {sid!r} already registered with different ring"
                )
        self.store.owner_drain.setdefault(sid, OwnerDrainState.ACTIVE.value)
        return MappingProxyType(stored)

    # -- datasets / home shards --------------------------------------------

    def register_logical_dataset(
        self,
        alias: LogicalDatasetAlias,
        *,
        content_identity: ContentIdentity | None = None,
        snapshot_identity: SnapshotIdentity | None = None,
    ) -> Mapping[str, Any]:
        """Register a logical alias; content/snapshot ids remain distinct fields."""

        self.require_migrated()
        self.assert_control_authority("lake_datasets")
        if not isinstance(alias, LogicalDatasetAlias):
            raise LakeIdentityError("alias must be LogicalDatasetAlias")
        if content_identity is not None and not isinstance(
            content_identity, ContentIdentity
        ):
            raise LakeIdentityError("content_identity must be ContentIdentity")
        if snapshot_identity is not None and not isinstance(
            snapshot_identity, SnapshotIdentity
        ):
            raise LakeIdentityError("snapshot_identity must be SnapshotIdentity")
        # Distinctness: never use content digest as logical alias.
        if content_identity is not None:
            if content_identity.content_digest == alias.identity_id():
                raise LakeIdentityError(
                    "logical dataset alias must be distinct from content identity"
                )
            if content_identity.identity_id() == alias.identity_id():
                raise LakeIdentityError(
                    "logical dataset alias must be distinct from content identity"
                )
        if snapshot_identity is not None:
            if snapshot_identity.identity_id() == alias.identity_id():
                raise LakeIdentityError(
                    "logical dataset alias must be distinct from snapshot identity"
                )
        now = _utc_iso()
        row = {
            "dataset_id": alias.dataset_id,
            "logical_alias": alias.alias,
            "tenant": alias.tenant,
            "namespace": alias.namespace,
            "identity_kind": IdentityKind.LOGICAL_DATASET_ALIAS.value,
            "identity_id": alias.identity_id(),
            "content_identity_id": (
                None if content_identity is None else content_identity.identity_id()
            ),
            "snapshot_identity_id": (
                None if snapshot_identity is None else snapshot_identity.identity_id()
            ),
            "created_at": now,
            "updated_at": now,
        }
        stored, created = self.store.put_if_absent(
            "lake_datasets", alias.dataset_id, row
        )
        if not created and stored["identity_id"] != alias.identity_id():
            raise CasConflict(
                f"dataset {alias.dataset_id!r} already registered with different identity"
            )
        return MappingProxyType(stored)

    def assign_home_shard(
        self,
        *,
        dataset_id: str,
        home_shard_id: str,
        uniqueness_scope: str,
        expected_revision: int | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_dataset_home_shards")
        did = _require_nonempty(dataset_id, field_name="dataset_id")
        if self.store.get_row("lake_datasets", did) is None:
            raise RegistryError(f"unknown dataset_id {did!r}")
        sid = _require_nonempty(home_shard_id, field_name="home_shard_id")
        if self.store.get_row("lake_catalog_shards", sid) is None:
            raise RegistryError(f"unknown home_shard_id {sid!r}")
        scope = _require_nonempty(uniqueness_scope, field_name="uniqueness_scope")
        now = _utc_iso()
        existing = self.store.get_row("lake_dataset_home_shards", did)
        row = {
            "dataset_id": did,
            "home_shard_id": sid,
            "uniqueness_scope": scope,
            "assigned_at": now if existing is None else existing["assigned_at"],
            "updated_at": now,
            "provenance_json": _canonical_json(dict(provenance or {})),
        }
        exp = expected_revision if existing is not None else (expected_revision or 0)
        stored = self.store.cas_upsert(
            "lake_dataset_home_shards",
            did,
            row,
            expected_revision=exp,
        )
        return MappingProxyType(stored)

    def resolve_home_shard(self, *, dataset_id: str) -> Mapping[str, Any]:
        self.require_migrated()
        did = _require_nonempty(dataset_id, field_name="dataset_id")
        row = self.store.get_row("lake_dataset_home_shards", did)
        if row is None:
            raise RegistryError(f"no home shard for dataset_id {did!r}")
        return MappingProxyType(row)

    def resolve_uniqueness_scope(
        self, *, uniqueness_scope: str, dataset_id: str | None = None
    ) -> Mapping[str, Any]:
        """Resolve a uniqueness/reference scope to exactly one home shard.

        Unsupported cross-shard uniqueness fails before ingest.
        """

        self.require_migrated()
        scope = _require_nonempty(uniqueness_scope, field_name="uniqueness_scope")
        if scope.startswith("cross_shard:") or scope == "*":
            raise UnsupportedCrossShardUniqueness(
                f"unsupported cross-shard uniqueness scope {scope!r} fails before ingest"
            )
        homes: list[dict[str, Any]] = []
        for row in self.store.list_rows("lake_dataset_home_shards"):
            if row["uniqueness_scope"] == scope:
                if dataset_id is None or row["dataset_id"] == dataset_id:
                    homes.append(row)
        if dataset_id is not None:
            home = self.store.get_row("lake_dataset_home_shards", dataset_id)
            if home is None:
                raise RegistryError(
                    f"uniqueness scope {scope!r} has no home for dataset {dataset_id!r}"
                )
            if home["uniqueness_scope"] != scope and not scope.startswith(
                f"dataset:{dataset_id}"
            ):
                # Allow dataset-local scopes that bind via dataset_id.
                if scope != f"dataset:{dataset_id}":
                    raise UnsupportedCrossShardUniqueness(
                        f"uniqueness scope {scope!r} does not match dataset "
                        f"{dataset_id!r} home scope {home['uniqueness_scope']!r}"
                    )
            return MappingProxyType(
                {
                    "uniqueness_scope": scope,
                    "home_shard_id": home["home_shard_id"],
                    "dataset_id": dataset_id,
                    "authoritative": True,
                }
            )
        if not homes:
            raise RegistryError(f"uniqueness scope {scope!r} has no home assignment")
        shard_ids = {h["home_shard_id"] for h in homes}
        if len(shard_ids) != 1:
            raise UnsupportedCrossShardUniqueness(
                f"uniqueness scope {scope!r} resolves to multiple home shards "
                f"{sorted(shard_ids)}; unsupported cross-shard uniqueness fails "
                "before ingest"
            )
        home = homes[0]
        return MappingProxyType(
            {
                "uniqueness_scope": scope,
                "home_shard_id": home["home_shard_id"],
                "dataset_id": home["dataset_id"],
                "authoritative": True,
            }
        )

    # -- owner generations -------------------------------------------------

    def record_owner_generation(
        self,
        *,
        catalog_id: str,
        owner_generation: int,
        lease_id: str,
        fencing_epoch: int,
        owner_identity: str,
        process_birth: Mapping[str, Any],
        expires_at: str,
        expected_revision: int | None = 0,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_catalog_owner_generations")
        if (
            not isinstance(owner_generation, int)
            or isinstance(owner_generation, bool)
            or owner_generation < 1
        ):
            raise RegistryError("owner_generation must be a positive int")
        key = f"{catalog_id}:{owner_generation}"
        now = _utc_iso()
        row = {
            "catalog_id": catalog_id,
            "owner_generation": owner_generation,
            "lease_id": _require_nonempty(lease_id, field_name="lease_id"),
            "fencing_epoch": int(fencing_epoch),
            "owner_identity": _require_nonempty(
                owner_identity, field_name="owner_identity"
            ),
            "process_birth_json": _canonical_json(dict(process_birth)),
            "status": "active",
            "acquired_at": now,
            "expires_at": _require_nonempty(expires_at, field_name="expires_at"),
        }
        stored = self.store.cas_upsert(
            "lake_catalog_owner_generations",
            key,
            row,
            expected_revision=expected_revision,
        )
        return MappingProxyType(stored)

    # -- snapshot vector roots ---------------------------------------------

    def put_snapshot_vector_root(
        self,
        *,
        vector_root_id: str,
        members: Sequence[Mapping[str, Any]],
        expected_revision: int | None = 0,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_snapshot_vector_roots")
        vid = _require_nonempty(vector_root_id, field_name="vector_root_id")
        member_list = [dict(m) for m in members]
        if not member_list:
            raise RegistryError("snapshot vector root requires at least one member")
        root_digest = _digest_of(member_list)
        now = _utc_iso()
        existing = self.store.get_row("lake_snapshot_vector_roots", vid)
        row = {
            "vector_root_id": vid,
            "root_digest": root_digest,
            "member_count": len(member_list),
            "members_json": _canonical_json(member_list),
            "created_at": now if existing is None else existing["created_at"],
            "updated_at": now,
        }
        exp = expected_revision if existing is not None else (expected_revision or 0)
        stored = self.store.cas_upsert(
            "lake_snapshot_vector_roots", vid, row, expected_revision=exp
        )
        return MappingProxyType(stored)

    # -- promotion / release -----------------------------------------------

    def record_promotion_decision(
        self,
        *,
        decision_id: str,
        subject: str,
        decision: str,
        evidence_digest: str,
        signer_identity: str,
        expires_at: str,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_promotion_decisions")
        did = _require_nonempty(decision_id, field_name="decision_id")
        dec = _require_nonempty(decision, field_name="decision").lower()
        if dec not in {"accepted", "rejected", "deferred"}:
            raise RegistryError("decision must be accepted|rejected|deferred")
        row = {
            "decision_id": did,
            "subject": _require_nonempty(subject, field_name="subject"),
            "decision": dec,
            "evidence_digest": _require_nonempty(
                evidence_digest, field_name="evidence_digest"
            ),
            "signer_identity": _require_nonempty(
                signer_identity, field_name="signer_identity"
            ),
            "decided_at": _utc_iso(),
            "expires_at": _require_nonempty(expires_at, field_name="expires_at"),
        }
        stored, _ = self.store.put_if_absent("lake_promotion_decisions", did, row)
        return MappingProxyType(stored)

    def record_promotion_execution(
        self,
        *,
        execution_id: str,
        decision_id: str,
        executor_identity: str,
        status: str = "completed",
        receipt_digest: str = "",
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_promotion_executions")
        if self.store.get_row("lake_promotion_decisions", decision_id) is None:
            raise RegistryError(f"unknown decision_id {decision_id!r}")
        eid = _require_nonempty(execution_id, field_name="execution_id")
        now = _utc_iso()
        row = {
            "execution_id": eid,
            "decision_id": decision_id,
            "status": _require_nonempty(status, field_name="status"),
            "executor_identity": _require_nonempty(
                executor_identity, field_name="executor_identity"
            ),
            "started_at": now,
            "completed_at": now,
            "receipt_digest": receipt_digest or _digest_of({"execution_id": eid}),
        }
        stored, _ = self.store.put_if_absent("lake_promotion_executions", eid, row)
        return MappingProxyType(stored)

    def record_release_receipt(
        self,
        *,
        receipt_id: str,
        release_id: str,
        vector_root_id: str,
        decision_id: str,
        execution_id: str,
        binding: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_release_receipts")
        rid = _require_nonempty(receipt_id, field_name="receipt_id")
        body = dict(binding)
        row = {
            "receipt_id": rid,
            "release_id": _require_nonempty(release_id, field_name="release_id"),
            "vector_root_id": _require_nonempty(
                vector_root_id, field_name="vector_root_id"
            ),
            "decision_id": decision_id,
            "execution_id": execution_id,
            "binding_digest": _digest_of(body),
            "published_at": _utc_iso(),
            "body_json": _canonical_json(body),
        }
        stored, _ = self.store.put_if_absent("lake_release_receipts", rid, row)
        return MappingProxyType(stored)

    # -- signed projections (cache only) -----------------------------------

    def put_signed_shard_projection(
        self, projection: SignedShardProjection
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_control_authority("lake_signed_shard_projections")
        if not isinstance(projection, SignedShardProjection):
            raise RegistryError("projection must be SignedShardProjection")
        row = dict(projection.as_mapping())
        row["payload_json"] = _canonical_json(dict(projection.payload))
        stored, _ = self.store.put_if_absent(
            "lake_signed_shard_projections", projection.projection_id, row
        )
        return MappingProxyType(stored)

    def validate_projection_for_owner_startup(
        self,
        *,
        shard_id: str,
        expected_content_digest: str,
        projection_id: str | None = None,
    ) -> Mapping[str, Any]:
        """Stale signed projections fail owner startup."""

        self.require_migrated()
        expected = _require_nonempty(
            expected_content_digest, field_name="expected_content_digest"
        )
        candidates = [
            r
            for r in self.store.list_rows("lake_signed_shard_projections")
            if r["shard_id"] == shard_id
            and (projection_id is None or r["projection_id"] == projection_id)
        ]
        if not candidates:
            raise StaleProjectionError(
                f"no signed projection for shard {shard_id!r}; owner startup fails"
            )
        # Prefer exact projection_id match, else latest by cas_revision.
        candidates.sort(key=lambda r: int(r.get("cas_revision", 0)), reverse=True)
        chosen = candidates[0]
        if chosen["content_digest"] != expected:
            raise StaleProjectionError(
                f"stale projection for shard {shard_id!r}: "
                f"stored {chosen['content_digest']}, expected {expected}; "
                "owner startup fails"
            )
        return MappingProxyType(chosen)

    # -- home-shard move ---------------------------------------------------

    def set_owner_drain_state(self, shard_id: str, state: OwnerDrainState | str) -> None:
        sid = _require_nonempty(shard_id, field_name="shard_id")
        if self.store.get_row("lake_catalog_shards", sid) is None:
            raise RegistryError(f"unknown shard_id {sid!r}")
        if not isinstance(state, OwnerDrainState):
            state = OwnerDrainState(str(state))
        self.store.owner_drain[sid] = state.value

    def owner_drain_state(self, shard_id: str) -> OwnerDrainState:
        raw = self.store.owner_drain.get(shard_id, OwnerDrainState.ACTIVE.value)
        return OwnerDrainState(raw)

    def begin_home_shard_move(
        self,
        *,
        dataset_id: str,
        destination_shard_id: str,
        fence_token: str | None = None,
    ) -> HomeShardMoveReceipt:
        """Start a home-shard move; requires both owners drained before commit."""

        self.require_migrated()
        self.assert_control_authority("lake_shard_migrations")
        home = self.resolve_home_shard(dataset_id=dataset_id)
        source = home["home_shard_id"]
        dest = _require_nonempty(
            destination_shard_id, field_name="destination_shard_id"
        )
        if source == dest:
            raise RegistryError("source and destination shards must differ")
        if self.store.get_row("lake_catalog_shards", dest) is None:
            raise RegistryError(f"unknown destination_shard_id {dest!r}")
        token = fence_token or uuid.uuid4().hex
        rid = f"move-{_sha256_text(dataset_id + source + dest + token)[:16]}"
        now = _utc_iso()
        body = {
            "migration_receipt_id": rid,
            "dataset_id": dataset_id,
            "source_shard_id": source,
            "destination_shard_id": dest,
            "source_drained": False,
            "destination_drained": False,
            "fence_token": token,
            "status": HomeShardMoveStatus.PENDING.value,
            "created_at": now,
            "completed_at": "",
            "receipt_digest": "",
        }
        body["receipt_digest"] = _digest_of(body)
        stored = self.store.cas_upsert(
            "lake_shard_migrations", rid, body, expected_revision=0
        )
        return HomeShardMoveReceipt(
            migration_receipt_id=stored["migration_receipt_id"],
            dataset_id=stored["dataset_id"],
            source_shard_id=stored["source_shard_id"],
            destination_shard_id=stored["destination_shard_id"],
            source_drained=bool(stored["source_drained"]),
            destination_drained=bool(stored["destination_drained"]),
            fence_token=stored["fence_token"],
            cas_revision=int(stored["cas_revision"]),
            status=HomeShardMoveStatus(stored["status"]),
            receipt_digest=stored["receipt_digest"],
            created_at=stored["created_at"],
            completed_at=stored.get("completed_at") or "",
        )

    def commit_home_shard_move(
        self,
        *,
        migration_receipt_id: str,
        expected_revision: int,
        fence_token: str,
    ) -> HomeShardMoveReceipt:
        """CAS-commit home-shard move after both owners are drained."""

        self.require_migrated()
        self.assert_control_authority("lake_shard_migrations")
        rid = _require_nonempty(
            migration_receipt_id, field_name="migration_receipt_id"
        )
        existing = self.store.get_row("lake_shard_migrations", rid)
        if existing is None:
            raise RegistryError(f"unknown migration_receipt_id {rid!r}")
        if existing["fence_token"] != fence_token:
            raise RegistryError("fence_token mismatch for home-shard move")
        source = existing["source_shard_id"]
        dest = existing["destination_shard_id"]
        if self.owner_drain_state(source) is not OwnerDrainState.DRAINED:
            raise RegistryError(
                f"source owner {source!r} must be drained before home-shard move CAS"
            )
        if self.owner_drain_state(dest) is not OwnerDrainState.DRAINED:
            raise RegistryError(
                f"destination owner {dest!r} must be drained before home-shard move CAS"
            )
        if existing["status"] == HomeShardMoveStatus.COMMITTED.value:
            return HomeShardMoveReceipt(
                migration_receipt_id=existing["migration_receipt_id"],
                dataset_id=existing["dataset_id"],
                source_shard_id=existing["source_shard_id"],
                destination_shard_id=existing["destination_shard_id"],
                source_drained=True,
                destination_drained=True,
                fence_token=existing["fence_token"],
                cas_revision=int(existing["cas_revision"]),
                status=HomeShardMoveStatus.COMMITTED,
                receipt_digest=existing["receipt_digest"],
                created_at=existing["created_at"],
                completed_at=existing.get("completed_at") or "",
            )
        now = _utc_iso()
        body = {
            **existing,
            "source_drained": True,
            "destination_drained": True,
            "status": HomeShardMoveStatus.COMMITTED.value,
            "completed_at": now,
        }
        # Recompute digest without cas_revision noise.
        digest_body = {
            k: body[k]
            for k in (
                "migration_receipt_id",
                "dataset_id",
                "source_shard_id",
                "destination_shard_id",
                "source_drained",
                "destination_drained",
                "fence_token",
                "status",
                "created_at",
                "completed_at",
            )
        }
        body["receipt_digest"] = _digest_of(digest_body)
        stored = self.store.cas_upsert(
            "lake_shard_migrations",
            rid,
            body,
            expected_revision=expected_revision,
        )
        # Update home assignment under its current revision.
        home = self.store.get_row("lake_dataset_home_shards", existing["dataset_id"])
        if home is None:
            raise RegistryError("home assignment missing during move commit")
        self.assign_home_shard(
            dataset_id=existing["dataset_id"],
            home_shard_id=dest,
            uniqueness_scope=home["uniqueness_scope"],
            expected_revision=int(home["cas_revision"]),
            provenance={
                "migration_receipt_id": rid,
                "fence_token": fence_token,
                "prior_home": source,
            },
        )
        return HomeShardMoveReceipt(
            migration_receipt_id=stored["migration_receipt_id"],
            dataset_id=stored["dataset_id"],
            source_shard_id=stored["source_shard_id"],
            destination_shard_id=stored["destination_shard_id"],
            source_drained=True,
            destination_drained=True,
            fence_token=stored["fence_token"],
            cas_revision=int(stored["cas_revision"]),
            status=HomeShardMoveStatus.COMMITTED,
            receipt_digest=stored["receipt_digest"],
            created_at=stored["created_at"],
            completed_at=stored.get("completed_at") or "",
        )

    def resume_owner_after_move(
        self, *, shard_id: str, migration_receipt_id: str
    ) -> None:
        """Resume a drained owner only after the move receipt is committed."""

        receipt = self.store.get_row("lake_shard_migrations", migration_receipt_id)
        if receipt is None:
            raise RegistryError(f"unknown migration_receipt_id {migration_receipt_id!r}")
        if receipt["status"] != HomeShardMoveStatus.COMMITTED.value:
            raise RegistryError(
                "owners may resume only after the fenced control-DB CAS move "
                "receipt is committed"
            )
        if shard_id not in {
            receipt["source_shard_id"],
            receipt["destination_shard_id"],
        }:
            raise RegistryError(
                f"shard {shard_id!r} is not a party to migration {migration_receipt_id!r}"
            )
        self.set_owner_drain_state(shard_id, OwnerDrainState.RESUMED)

    # -- restart -----------------------------------------------------------

    def export_checkpoint(self) -> dict[str, Any]:
        return {
            "schema": CONTROL_REGISTRY_SCHEMA,
            "owner_id": self.owner_id,
            "instance": dict(self.instance.as_mapping()),
            "store": self.store.export_state(),
        }

    @classmethod
    def from_checkpoint(cls, checkpoint: Mapping[str, Any]) -> ControlLakeRegistry:
        store = MemoryRegistryStore(scope=RegistryScope.CONTROL)
        store.import_state(checkpoint["store"])
        inst = checkpoint.get("instance") or {}
        binding = DatabaseInstanceBinding(
            instance_id=str(inst.get("instance_id") or store.instance_id),
            kind=DatabaseInstanceKind(
                str(inst.get("kind") or DatabaseInstanceKind.CONTROL.value)
            ),
            path=str(inst.get("path") or ":memory:control"),
            private=bool(inst.get("private", True)),
            attachable_from_quack=bool(inst.get("attachable_from_quack", False)),
        )
        reg = cls(
            store,
            owner_id=str(checkpoint.get("owner_id") or "control-owner"),
            instance=binding,
        )
        reg._migrations_applied = True
        return reg

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": CONTROL_REGISTRY_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "scope": self.SCOPE.value,
                "owner_id": self.owner_id,
                "instance": dict(self.instance.as_mapping()),
                "schema_digest": self.store.schema_digest,
                "authority_tables": sorted(_CONTROL_EXCLUSIVE),
                "mutable_manifest_authoritative": False,
            }
        )


# ---------------------------------------------------------------------------
# Companion registry
# ---------------------------------------------------------------------------


class CompanionLakeRegistry:
    """Per-shard private companion owner-control registry.

    Never ATTACHed to the Quack-serving DatabaseInstance. Cannot redefine the
    global shard ring, home assignment, owner generation, or vector root.
    """

    SCHEMA: Final[str] = COMPANION_REGISTRY_SCHEMA
    SCOPE: Final[RegistryScope] = RegistryScope.COMPANION

    def __init__(
        self,
        *,
        shard_id: str,
        store: MemoryRegistryStore | None = None,
        owner_id: str = "companion-owner",
        instance: DatabaseInstanceBinding | None = None,
        control: ControlLakeRegistry | None = None,
    ) -> None:
        self.shard_id = _require_nonempty(shard_id, field_name="shard_id")
        self.store = store or MemoryRegistryStore(
            scope=RegistryScope.COMPANION,
            instance_id=f"companion-{self.shard_id}",
        )
        if self.store.scope is not RegistryScope.COMPANION:
            raise RegistryError("CompanionLakeRegistry requires a companion-scope store")
        self.owner_id = _require_nonempty(owner_id, field_name="owner_id")
        self.instance = instance or DatabaseInstanceBinding(
            instance_id=f"companion-db-{self.shard_id}-{self.store.instance_id[:8]}",
            kind=DatabaseInstanceKind.COMPANION_PRIVATE,
            path=f":memory:companion:{self.shard_id}",
            private=True,
            attachable_from_quack=False,
        )
        if self.instance.kind is not DatabaseInstanceKind.COMPANION_PRIVATE:
            raise RegistryError(
                "companion registry requires COMPANION_PRIVATE DatabaseInstance"
            )
        if self.instance.attachable_from_quack:
            raise RegistryError(
                "companion registry DatabaseInstance must never be attachable "
                "from Quack-serving"
            )
        self.control = control
        self._migrations_applied = False
        self._quack_instance: DatabaseInstanceBinding | None = None

    def bind_quack_serving_instance(
        self, quack: DatabaseInstanceBinding
    ) -> None:
        """Record the Quack-serving instance and assert isolation."""

        if quack.kind is not DatabaseInstanceKind.QUACK_SERVING:
            raise RegistryError("expected QUACK_SERVING DatabaseInstance")
        self.instance.assert_not_attached_to(quack)
        if self.store.is_visible_from(quack.instance_id):
            raise RegistryError(
                "companion registry is visible from Quack-serving DatabaseInstance"
            )
        self._quack_instance = quack

    def assert_isolated_from_quack(self) -> None:
        if self.instance.attachable_from_quack:
            raise RegistryError(
                "companion registry must never be attachable from Quack-serving"
            )
        if self._quack_instance is not None:
            self.instance.assert_not_attached_to(self._quack_instance)
            if self.store.is_visible_from(self._quack_instance.instance_id):
                raise RegistryError(
                    "companion registry must never be ATTACHed to or visible "
                    "from the Quack-serving DatabaseInstance"
                )

    def apply_migrations(
        self, *, dry_run: bool = False, resume: bool = True
    ) -> tuple[MigrationReceipt, ...]:
        gate = RegistryMigrationGate(
            scope=RegistryScope.COMPANION,
            owner_id=self.owner_id,
            authorized=True,
        )
        receipts = apply_registry_migrations(
            companion_migration_catalog(),
            self.store.migration_backend,
            gate=gate,
            dry_run=dry_run,
            resume=resume,
        )
        if not dry_run:
            self._migrations_applied = True
            self.store.schema_digest = schema_digest_for(
                list(companion_migration_catalog().migrations)
            )
        return receipts

    def require_migrated(self) -> None:
        applied = set(self.store.migration_backend.list_applied())
        expected = {
            m.migration_id for m in companion_migration_catalog().migrations
        }
        if not expected.issubset(applied):
            raise RegistryError(
                "companion registry migrations not fully applied "
                f"(applied={sorted(applied)}, expected={sorted(expected)})"
            )
        self._migrations_applied = True

    def _reject_global_redefinition(self, table: str) -> None:
        name = str(table or "").strip()
        if name in _COMPANION_FORBIDDEN_WRITES:
            raise AuthorityViolation(
                f"companion registry cannot redefine global control authority "
                f"table {table!r} (shard ring, home assignment, owner generation, "
                "or vector root)"
            )
        try:
            if scope_for_table(name) is RegistryScope.CONTROL:
                raise AuthorityViolation(
                    f"companion cannot write control authority table {table!r}"
                )
        except LakeSchemaError:
            pass

    def assert_companion_authority(self, table: str) -> None:
        self._reject_global_redefinition(table)
        name = str(table or "").strip()
        exclusive = COMPANION_TABLES - {
            "schema_registry",
            "schema_migrations",
            "migration_locks",
            "lake_idempotency_keys",
        }
        physical = {
            "reader_lease": "lake_reader_leases",
            "logical_key_reservation": "lake_logical_key_reservations",
            "ingest_outbox": "lake_ingest_outbox",
            "maintenance_authorization": "lake_maintenance_authorizations",
        }.get(name, name)
        if physical not in exclusive:
            raise AuthorityViolation(
                f"table {table!r} is not companion registry authority"
            )

    # -- shard-local operations --------------------------------------------

    def put_source(
        self,
        *,
        source_id: str,
        source_uri: str,
        content: ContentIdentity,
        object_generation: str = "",
        etag: str = "",
        provenance: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_isolated_from_quack()
        self.assert_companion_authority("lake_sources")
        if not isinstance(content, ContentIdentity):
            raise LakeIdentityError("content must be ContentIdentity")
        sid = _require_nonempty(source_id, field_name="source_id")
        row = {
            "source_id": sid,
            "shard_id": self.shard_id,
            "source_uri": _require_nonempty(source_uri, field_name="source_uri"),
            "content_digest": content.content_digest,
            "content_cid": content.content_cid,
            "object_generation": object_generation,
            "etag": etag,
            "admitted_at": _utc_iso(),
            "provenance_json": _canonical_json(dict(provenance or {})),
        }
        stored, _ = self.store.put_if_absent("lake_sources", sid, row)
        return MappingProxyType(stored)

    def acquire_reader_lease(
        self,
        *,
        lease_id: str,
        reader_identity: str,
        snapshot_version: int,
        fencing_epoch: int,
        expires_at: str,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_isolated_from_quack()
        self.assert_companion_authority("lake_reader_leases")
        lid = _require_nonempty(lease_id, field_name="lease_id")
        row = {
            "lease_id": lid,
            "shard_id": self.shard_id,
            "reader_identity": _require_nonempty(
                reader_identity, field_name="reader_identity"
            ),
            "snapshot_version": int(snapshot_version),
            "fencing_epoch": int(fencing_epoch),
            "acquired_at": _utc_iso(),
            "expires_at": _require_nonempty(expires_at, field_name="expires_at"),
            "status": "active",
        }
        stored, _ = self.store.put_if_absent("lake_reader_leases", lid, row)
        return MappingProxyType(stored)

    def reserve_logical_key(
        self,
        *,
        reservation_id: str,
        dataset_id: str,
        uniqueness_scope: str,
        logical_key_digest: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        """Reserve a logical key only after control home-shard resolution."""

        self.require_migrated()
        self.assert_isolated_from_quack()
        self.assert_companion_authority("lake_logical_key_reservations")
        if self.control is None:
            raise RegistryError(
                "logical key reservation requires a control registry for "
                "authoritative home-shard resolution"
            )
        resolved = self.control.resolve_uniqueness_scope(
            uniqueness_scope=uniqueness_scope, dataset_id=dataset_id
        )
        if resolved["home_shard_id"] != self.shard_id:
            raise UnsupportedCrossShardUniqueness(
                f"uniqueness scope {uniqueness_scope!r} for dataset {dataset_id!r} "
                f"homes at {resolved['home_shard_id']!r}, not companion shard "
                f"{self.shard_id!r}; fails before ingest"
            )
        rid = _require_nonempty(reservation_id, field_name="reservation_id")
        key_digest = _require_nonempty(
            logical_key_digest, field_name="logical_key_digest"
        )
        # Unique on (shard, scope, key digest).
        for existing in self.store.list_rows("lake_logical_key_reservations"):
            if (
                existing["uniqueness_scope"] == uniqueness_scope
                and existing["logical_key_digest"] == key_digest
                and existing["status"] in {"reserved", "committed"}
            ):
                if existing.get("idempotency_key") == idempotency_key:
                    return MappingProxyType(existing)
                raise RegistryError(
                    f"logical key already reserved under scope {uniqueness_scope!r}"
                )
        row = {
            "reservation_id": rid,
            "shard_id": self.shard_id,
            "dataset_id": dataset_id,
            "uniqueness_scope": uniqueness_scope,
            "logical_key_digest": key_digest,
            "idempotency_key": _require_nonempty(
                idempotency_key, field_name="idempotency_key"
            ),
            "status": "reserved",
            "reserved_at": _utc_iso(),
            "terminalized_at": "",
            "snapshot_version": None,
        }
        stored, _ = self.store.put_if_absent(
            "lake_logical_key_reservations", rid, row
        )
        return MappingProxyType(stored)

    def enqueue_ingest_outbox(
        self,
        *,
        outbox_id: str,
        operation_id: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_isolated_from_quack()
        self.assert_companion_authority("lake_ingest_outbox")
        oid = _require_nonempty(outbox_id, field_name="outbox_id")
        now = _utc_iso()
        row = {
            "outbox_id": oid,
            "shard_id": self.shard_id,
            "operation_id": _require_nonempty(
                operation_id, field_name="operation_id"
            ),
            "payload_digest": _digest_of(dict(payload)),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        stored, _ = self.store.put_if_absent("lake_ingest_outbox", oid, row)
        return MappingProxyType(stored)

    def authorize_maintenance(
        self,
        *,
        authorization_id: str,
        action: str,
        authorizer_identity: str,
        subject_digest: str,
        expires_at: str,
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_isolated_from_quack()
        self.assert_companion_authority("lake_maintenance_authorizations")
        aid = _require_nonempty(authorization_id, field_name="authorization_id")
        row = {
            "authorization_id": aid,
            "shard_id": self.shard_id,
            "action": _require_nonempty(action, field_name="action"),
            "authorizer_identity": _require_nonempty(
                authorizer_identity, field_name="authorizer_identity"
            ),
            "subject_digest": _require_nonempty(
                subject_digest, field_name="subject_digest"
            ),
            "issued_at": _utc_iso(),
            "expires_at": _require_nonempty(expires_at, field_name="expires_at"),
            "status": "active",
        }
        stored, _ = self.store.put_if_absent(
            "lake_maintenance_authorizations", aid, row
        )
        return MappingProxyType(stored)

    def put_ownership_state(
        self,
        *,
        ownership_id: str,
        subject_kind: str,
        subject_id: str,
        owner_generation: int,
        status: str = "owned",
    ) -> Mapping[str, Any]:
        self.require_migrated()
        self.assert_isolated_from_quack()
        self.assert_companion_authority("lake_ownership_state")
        oid = _require_nonempty(ownership_id, field_name="ownership_id")
        row = {
            "ownership_id": oid,
            "shard_id": self.shard_id,
            "subject_kind": _require_nonempty(
                subject_kind, field_name="subject_kind"
            ),
            "subject_id": _require_nonempty(subject_id, field_name="subject_id"),
            "owner_generation": int(owner_generation),
            "status": status,
            "updated_at": _utc_iso(),
        }
        stored, _ = self.store.put_if_absent("lake_ownership_state", oid, row)
        return MappingProxyType(stored)

    def export_checkpoint(self) -> dict[str, Any]:
        return {
            "schema": COMPANION_REGISTRY_SCHEMA,
            "shard_id": self.shard_id,
            "owner_id": self.owner_id,
            "instance": dict(self.instance.as_mapping()),
            "store": self.store.export_state(),
        }

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: Mapping[str, Any],
        *,
        control: ControlLakeRegistry | None = None,
    ) -> CompanionLakeRegistry:
        store = MemoryRegistryStore(scope=RegistryScope.COMPANION)
        store.import_state(checkpoint["store"])
        inst = checkpoint.get("instance") or {}
        binding = DatabaseInstanceBinding(
            instance_id=str(inst.get("instance_id") or store.instance_id),
            kind=DatabaseInstanceKind.COMPANION_PRIVATE,
            path=str(inst.get("path") or ":memory:companion"),
            private=True,
            attachable_from_quack=False,
        )
        reg = cls(
            shard_id=str(checkpoint["shard_id"]),
            store=store,
            owner_id=str(checkpoint.get("owner_id") or "companion-owner"),
            instance=binding,
            control=control,
        )
        reg._migrations_applied = True
        return reg

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": COMPANION_REGISTRY_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "scope": self.SCOPE.value,
                "shard_id": self.shard_id,
                "owner_id": self.owner_id,
                "instance": dict(self.instance.as_mapping()),
                "schema_digest": self.store.schema_digest,
                "attachable_from_quack": False,
                "quack_visible": False,
                "mutable_manifest_authoritative": False,
            }
        )
