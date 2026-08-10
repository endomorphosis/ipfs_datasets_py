"""DuckLake application registry schema and checksummed migrations (DQK-086).

Defines two independent migration scopes that never touch DuckLake's internal
v1.0 catalog tables:

* **control** — small authoritative control DuckDB (catalog-shard identities,
  dataset-to-home-shard routing, owner-generation leases, snapshot-vector
  roots, shard-migration receipts, promotion/release decisions, signed shard
  projections)
* **companion** — per-shard private owner-control DuckDB (sources, schemas,
  file identities, ingest receipts, reader leases, logical-key reservations,
  outbox entries, ownership state, maintenance authorizations, retention,
  publication lineage)

Logical dataset aliases are distinct from content identities and snapshot
identities. Mutable JSON/Parquet manifests are never treated as authority.

Import is side-effect free: no DuckDB connection, no filesystem writes, no
network. Unit tests apply migrations through the hermetic
:class:`~ipfs_datasets_py.duckdb_control.migrations.MemoryMigrationBackend`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence

from ipfs_datasets_py.duckdb_control.migrations import (
    Migration,
    MigrationCatalog,
    RollbackMetadata,
    SCHEMA_DIGEST_PREFIX,
    schema_digest_for,
)

__all__ = [
    "COMPANION_NAMESPACE",
    "COMPANION_TABLES",
    "CONTROL_NAMESPACE",
    "CONTROL_TABLES",
    "DUCKLAKE_INTERNAL_V1_TABLES",
    "IDENTITY_KIND_SCHEMA",
    "LAKE_REGISTRY_SCHEMA",
    "REGISTRY_SCOPE_SCHEMA",
    "ContentIdentity",
    "IdentityKind",
    "LakeIdentityError",
    "LakeSchemaError",
    "LogicalDatasetAlias",
    "RegistryScope",
    "SnapshotIdentity",
    "companion_migration_catalog",
    "control_migration_catalog",
    "default_companion_migrations",
    "default_control_migrations",
    "is_ducklake_internal_table",
    "scope_for_table",
    "schema_digest_for",
    "table_authority",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

LAKE_REGISTRY_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-registry@1"
REGISTRY_SCOPE_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-registry-scope@1"
IDENTITY_KIND_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-identity-kind@1"

CONTROL_NAMESPACE: Final[str] = "ducklake_control"
COMPANION_NAMESPACE: Final[str] = "ducklake_companion"

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-086-lake-registry-schema-20260810"
)

# DuckLake internal v1.0 metadata tables (never created/altered by application
# migrations). Names follow the public DuckLake catalog layout; keep the set
# explicit so authority checks fail closed if a migration body drifts.
DUCKLAKE_INTERNAL_V1_TABLES: Final[frozenset[str]] = frozenset(
    {
        "ducklake_metadata",
        "ducklake_schema",
        "ducklake_table",
        "ducklake_view",
        "ducklake_column",
        "ducklake_partition",
        "ducklake_partition_column",
        "ducklake_data_file",
        "ducklake_delete_file",
        "ducklake_files_scheduled_for_deletion",
        "ducklake_inlined_data_tables",
        "ducklake_column_tag",
        "ducklake_tag",
        "ducklake_snapshot",
        "ducklake_snapshot_changes",
        "ducklake_table_stats",
        "ducklake_table_column_stats",
        "ducklake_file_column_stats",
    }
)

# Control-plane authority tables (sole writer: small control DuckDB).
CONTROL_TABLES: Final[frozenset[str]] = frozenset(
    {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
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
        "lake_idempotency_keys",
    }
)

# Companion-plane authority tables (per-shard private owner-control DuckDB).
COMPANION_TABLES: Final[frozenset[str]] = frozenset(
    {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
        "lake_sources",
        "lake_schema_contracts",
        "lake_file_identities",
        "lake_ingest_receipts",
        "lake_reader_leases",
        "lake_logical_key_reservations",
        "lake_ingest_outbox",
        "lake_ownership_state",
        "lake_maintenance_authorizations",
        "lake_retention_policies",
        "lake_publication_lineage",
        "lake_idempotency_keys",
    }
)

# Acceptance-criteria short names → authority table.
_ACCEPTANCE_AUTHORITY_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "lake_catalog": "lake_catalogs",
        "dataset_home_shard": "lake_dataset_home_shards",
        "catalog_owner_generation": "lake_catalog_owner_generations",
        "snapshot_vector_root": "lake_snapshot_vector_roots",
        "shard_migration": "lake_shard_migrations",
        "promotion_decision": "lake_promotion_decisions",
        "promotion_execution": "lake_promotion_executions",
        "lake_release_receipts": "lake_release_receipts",
        "reader_lease": "lake_reader_leases",
        "logical_key_reservation": "lake_logical_key_reservations",
        "ingest_outbox": "lake_ingest_outbox",
        "maintenance_authorization": "lake_maintenance_authorizations",
    }
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:@/-]{0,255}$")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_CID_RE = re.compile(r"^(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{10,200})$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LakeSchemaError(ValueError):
    """Fail-closed lake registry schema / migration catalog rejection."""


class LakeIdentityError(LakeSchemaError):
    """Logical alias, content identity, or snapshot identity is invalid."""


# ---------------------------------------------------------------------------
# Scopes and identity kinds
# ---------------------------------------------------------------------------


class RegistryScope(str, Enum):
    """Authority scope for application registry tables."""

    CONTROL = "control"
    COMPANION = "companion"


class IdentityKind(str, Enum):
    """Closed set of distinct identity kinds (never interchangeable)."""

    LOGICAL_DATASET_ALIAS = "logical_dataset_alias"
    CONTENT = "content"
    SNAPSHOT = "snapshot"


def table_authority(table_name: str) -> RegistryScope | None:
    """Return the authority scope for ``table_name``, or None if unknown.

    Acceptance short-names (e.g. ``dataset_home_shard``) resolve to the same
    scope as their physical table.
    """

    name = str(table_name or "").strip()
    if not name:
        return None
    physical = _ACCEPTANCE_AUTHORITY_ALIASES.get(name, name)
    if physical in CONTROL_TABLES and physical not in {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
        "lake_idempotency_keys",
    }:
        # Shared bookkeeping tables exist in both scopes; for exclusive
        # control authority names, prefer control when listed in CONTROL_TABLES
        # as a control-only domain table.
        if physical in COMPANION_TABLES - {
            "schema_registry",
            "schema_migrations",
            "migration_locks",
            "lake_idempotency_keys",
        }:
            return None
        if physical in CONTROL_TABLES - {
            "schema_registry",
            "schema_migrations",
            "migration_locks",
            "lake_idempotency_keys",
        }:
            return RegistryScope.CONTROL
    if physical in CONTROL_TABLES - {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
        "lake_idempotency_keys",
    }:
        return RegistryScope.CONTROL
    if physical in COMPANION_TABLES - {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
        "lake_idempotency_keys",
    }:
        return RegistryScope.COMPANION
    if physical in {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
        "lake_idempotency_keys",
    }:
        # Bookkeeping is scope-local; caller must supply scope.
        return None
    return None


def scope_for_table(table_name: str) -> RegistryScope:
    """Resolve exclusive authority scope; raise if ambiguous or unknown."""

    name = str(table_name or "").strip()
    physical = _ACCEPTANCE_AUTHORITY_ALIASES.get(name, name)
    exclusive_control = CONTROL_TABLES - {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
        "lake_idempotency_keys",
    }
    exclusive_companion = COMPANION_TABLES - {
        "schema_registry",
        "schema_migrations",
        "migration_locks",
        "lake_idempotency_keys",
    }
    if physical in exclusive_control:
        return RegistryScope.CONTROL
    if physical in exclusive_companion:
        return RegistryScope.COMPANION
    raise LakeSchemaError(
        f"table {table_name!r} has no exclusive authority scope "
        "(bookkeeping is scope-local or name is unknown)"
    )


def is_ducklake_internal_table(table_name: str) -> bool:
    """True when ``table_name`` is a DuckLake internal v1.0 metadata table."""

    return str(table_name or "").strip().lower() in DUCKLAKE_INTERNAL_V1_TABLES


# ---------------------------------------------------------------------------
# Typed identities (logical ≠ content ≠ snapshot)
# ---------------------------------------------------------------------------


def _require_token(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or not _SAFE_ID_RE.match(text):
        raise LakeIdentityError(f"{field_name} must be a safe non-empty token")
    return text


def _require_digest(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LakeIdentityError(f"{field_name} is required")
    if text.startswith("sha256:"):
        hexpart = text[7:]
    elif _SHA256_RE.match(text) and ":" not in text:
        hexpart = text
        text = f"sha256:{hexpart}"
    else:
        raise LakeIdentityError(f"{field_name} must be sha256:<64-hex>")
    if len(hexpart) != 64 or any(c not in "0123456789abcdefABCDEF" for c in hexpart):
        raise LakeIdentityError(f"{field_name} must be sha256:<64-hex>")
    return f"sha256:{hexpart.lower()}"


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LogicalDatasetAlias:
    """Stable logical name for a dataset; not a content or snapshot id."""

    SCHEMA: ClassVar[str] = IDENTITY_KIND_SCHEMA
    alias: str
    tenant: str = "default"
    namespace: str = "default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "alias", _require_token(self.alias, field_name="alias"))
        object.__setattr__(
            self, "tenant", _require_token(self.tenant, field_name="tenant")
        )
        object.__setattr__(
            self, "namespace", _require_token(self.namespace, field_name="namespace")
        )

    @property
    def kind(self) -> IdentityKind:
        return IdentityKind.LOGICAL_DATASET_ALIAS

    @property
    def dataset_id(self) -> str:
        return f"{self.tenant}/{self.namespace}/{self.alias}"

    def identity_id(self) -> str:
        body = {
            "kind": self.kind.value,
            "alias": self.alias,
            "tenant": self.tenant,
            "namespace": self.namespace,
        }
        return "logical:" + _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": IDENTITY_KIND_SCHEMA,
                "kind": self.kind.value,
                "alias": self.alias,
                "tenant": self.tenant,
                "namespace": self.namespace,
                "dataset_id": self.dataset_id,
                "identity_id": self.identity_id(),
            }
        )


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """Content-bound identity (CID and/or whole-file digest); not a logical alias."""

    SCHEMA: ClassVar[str] = IDENTITY_KIND_SCHEMA
    content_digest: str
    content_cid: str = ""
    media_type: str = "parquet"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "content_digest",
            _require_digest(self.content_digest, field_name="content_digest"),
        )
        cid = str(self.content_cid or "").strip()
        if cid and not _CID_RE.match(cid):
            raise LakeIdentityError("content_cid must be a CIDv0 or CIDv1 string")
        object.__setattr__(self, "content_cid", cid)
        media = str(self.media_type or "parquet").strip().lower()
        if media not in {"parquet", "ipld-raw", "ipld-dag-cbor", "car", "bytes"}:
            raise LakeIdentityError(f"unsupported media_type {self.media_type!r}")
        object.__setattr__(self, "media_type", media)

    @property
    def kind(self) -> IdentityKind:
        return IdentityKind.CONTENT

    def identity_id(self) -> str:
        body = {
            "kind": self.kind.value,
            "content_digest": self.content_digest,
            "content_cid": self.content_cid,
            "media_type": self.media_type,
        }
        return "content:" + _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": IDENTITY_KIND_SCHEMA,
                "kind": self.kind.value,
                "content_digest": self.content_digest,
                "content_cid": self.content_cid,
                "media_type": self.media_type,
                "identity_id": self.identity_id(),
            }
        )


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    """Catalog-global snapshot identity for one shard; not a logical alias."""

    SCHEMA: ClassVar[str] = IDENTITY_KIND_SCHEMA
    catalog_id: str
    snapshot_version: int
    snapshot_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "catalog_id", _require_token(self.catalog_id, field_name="catalog_id")
        )
        if (
            not isinstance(self.snapshot_version, int)
            or isinstance(self.snapshot_version, bool)
            or self.snapshot_version < 0
        ):
            raise LakeIdentityError("snapshot_version must be a non-negative int")
        digest = str(self.snapshot_digest or "").strip()
        if digest:
            digest = _require_digest(digest, field_name="snapshot_digest")
        object.__setattr__(self, "snapshot_digest", digest)

    @property
    def kind(self) -> IdentityKind:
        return IdentityKind.SNAPSHOT

    def identity_id(self) -> str:
        body = {
            "kind": self.kind.value,
            "catalog_id": self.catalog_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_digest": self.snapshot_digest,
        }
        return "snapshot:" + _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": IDENTITY_KIND_SCHEMA,
                "kind": self.kind.value,
                "catalog_id": self.catalog_id,
                "snapshot_version": self.snapshot_version,
                "snapshot_digest": self.snapshot_digest,
                "identity_id": self.identity_id(),
            }
        )


# ---------------------------------------------------------------------------
# Migration SQL bodies
# ---------------------------------------------------------------------------


def _assert_sql_avoids_ducklake_internal(sql: str, *, migration_id: str) -> None:
    lowered = sql.lower()
    for table in DUCKLAKE_INTERNAL_V1_TABLES:
        # Match CREATE/ALTER/DROP TABLE ... ducklake_* as whole identifiers.
        pattern = re.compile(
            rf"\b(create|alter|drop)\s+table\b[^;]*\b{re.escape(table)}\b",
            re.IGNORECASE,
        )
        if pattern.search(lowered):
            raise LakeSchemaError(
                f"migration {migration_id} must not modify DuckLake internal "
                f"v1.0 table {table!r}"
            )


def _control_bootstrap_sql() -> str:
    return """
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
CREATE TABLE IF NOT EXISTS lake_idempotency_keys (
    idempotency_key VARCHAR PRIMARY KEY,
    operation VARCHAR NOT NULL,
    request_digest VARCHAR NOT NULL,
    response_json VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL
);
""".strip()


def _control_catalog_sql() -> str:
    return """
CREATE TABLE IF NOT EXISTS lake_catalogs (
    catalog_id VARCHAR PRIMARY KEY,
    catalog_digest VARCHAR NOT NULL,
    storage_kind VARCHAR NOT NULL,
    metadata_path VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    provenance_json VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_catalog_shards (
    shard_id VARCHAR PRIMARY KEY,
    catalog_id VARCHAR NOT NULL,
    ring_position INTEGER NOT NULL,
    endpoint_identity VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    UNIQUE (catalog_id, ring_position)
);
CREATE TABLE IF NOT EXISTS lake_datasets (
    dataset_id VARCHAR PRIMARY KEY,
    logical_alias VARCHAR NOT NULL,
    tenant VARCHAR NOT NULL,
    namespace VARCHAR NOT NULL,
    identity_kind VARCHAR NOT NULL,
    identity_id VARCHAR NOT NULL,
    content_identity_id VARCHAR,
    snapshot_identity_id VARCHAR,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    UNIQUE (tenant, namespace, logical_alias)
);
CREATE TABLE IF NOT EXISTS lake_dataset_home_shards (
    dataset_id VARCHAR PRIMARY KEY,
    home_shard_id VARCHAR NOT NULL,
    uniqueness_scope VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    assigned_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    provenance_json VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_catalog_owner_generations (
    catalog_id VARCHAR NOT NULL,
    owner_generation BIGINT NOT NULL,
    lease_id VARCHAR NOT NULL,
    fencing_epoch BIGINT NOT NULL,
    owner_identity VARCHAR NOT NULL,
    process_birth_json VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    acquired_at VARCHAR NOT NULL,
    expires_at VARCHAR NOT NULL,
    PRIMARY KEY (catalog_id, owner_generation)
);
CREATE TABLE IF NOT EXISTS lake_snapshot_vector_roots (
    vector_root_id VARCHAR PRIMARY KEY,
    root_digest VARCHAR NOT NULL,
    member_count INTEGER NOT NULL,
    members_json VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_shard_migrations (
    migration_receipt_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR NOT NULL,
    source_shard_id VARCHAR NOT NULL,
    destination_shard_id VARCHAR NOT NULL,
    source_drained BOOLEAN NOT NULL,
    destination_drained BOOLEAN NOT NULL,
    fence_token VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    completed_at VARCHAR,
    receipt_digest VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_promotion_decisions (
    decision_id VARCHAR PRIMARY KEY,
    subject VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    evidence_digest VARCHAR NOT NULL,
    signer_identity VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    decided_at VARCHAR NOT NULL,
    expires_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_promotion_executions (
    execution_id VARCHAR PRIMARY KEY,
    decision_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    executor_identity VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    started_at VARCHAR NOT NULL,
    completed_at VARCHAR,
    receipt_digest VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_release_receipts (
    receipt_id VARCHAR PRIMARY KEY,
    release_id VARCHAR NOT NULL,
    vector_root_id VARCHAR NOT NULL,
    decision_id VARCHAR NOT NULL,
    execution_id VARCHAR NOT NULL,
    binding_digest VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    published_at VARCHAR NOT NULL,
    body_json VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_signed_shard_projections (
    projection_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    signature VARCHAR NOT NULL,
    signer_identity VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    issued_at VARCHAR NOT NULL,
    expires_at VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL
);
""".strip()


def _companion_bootstrap_sql() -> str:
    return """
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
CREATE TABLE IF NOT EXISTS lake_idempotency_keys (
    idempotency_key VARCHAR PRIMARY KEY,
    operation VARCHAR NOT NULL,
    request_digest VARCHAR NOT NULL,
    response_json VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL
);
""".strip()


def _companion_local_sql() -> str:
    return """
CREATE TABLE IF NOT EXISTS lake_sources (
    source_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    source_uri VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    content_cid VARCHAR,
    object_generation VARCHAR,
    etag VARCHAR,
    cas_revision BIGINT NOT NULL,
    admitted_at VARCHAR NOT NULL,
    provenance_json VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_schema_contracts (
    contract_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    schema_digest VARCHAR NOT NULL,
    field_ids_json VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_file_identities (
    file_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    owned_path VARCHAR NOT NULL,
    source_id VARCHAR,
    cas_revision BIGINT NOT NULL,
    registered_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_ingest_receipts (
    receipt_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    operation_id VARCHAR NOT NULL,
    snapshot_version BIGINT,
    status VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL,
    body_json VARCHAR NOT NULL,
    UNIQUE (shard_id, operation_id)
);
CREATE TABLE IF NOT EXISTS lake_reader_leases (
    lease_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    reader_identity VARCHAR NOT NULL,
    snapshot_version BIGINT NOT NULL,
    fencing_epoch BIGINT NOT NULL,
    cas_revision BIGINT NOT NULL,
    acquired_at VARCHAR NOT NULL,
    expires_at VARCHAR NOT NULL,
    status VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_logical_key_reservations (
    reservation_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    uniqueness_scope VARCHAR NOT NULL,
    logical_key_digest VARCHAR NOT NULL,
    idempotency_key VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    reserved_at VARCHAR NOT NULL,
    terminalized_at VARCHAR,
    snapshot_version BIGINT,
    UNIQUE (shard_id, uniqueness_scope, logical_key_digest)
);
CREATE TABLE IF NOT EXISTS lake_ingest_outbox (
    outbox_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    operation_id VARCHAR NOT NULL,
    payload_digest VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    UNIQUE (shard_id, operation_id)
);
CREATE TABLE IF NOT EXISTS lake_ownership_state (
    ownership_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    subject_kind VARCHAR NOT NULL,
    subject_id VARCHAR NOT NULL,
    owner_generation BIGINT NOT NULL,
    status VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    updated_at VARCHAR NOT NULL,
    UNIQUE (shard_id, subject_kind, subject_id)
);
CREATE TABLE IF NOT EXISTS lake_maintenance_authorizations (
    authorization_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    authorizer_identity VARCHAR NOT NULL,
    subject_digest VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    issued_at VARCHAR NOT NULL,
    expires_at VARCHAR NOT NULL,
    status VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_retention_policies (
    policy_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    retention_class VARCHAR NOT NULL,
    retain_snapshots INTEGER NOT NULL,
    cas_revision BIGINT NOT NULL,
    updated_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS lake_publication_lineage (
    lineage_id VARCHAR PRIMARY KEY,
    shard_id VARCHAR NOT NULL,
    publication_id VARCHAR NOT NULL,
    parent_publication_id VARCHAR,
    content_digest VARCHAR NOT NULL,
    cas_revision BIGINT NOT NULL,
    published_at VARCHAR NOT NULL
);
""".strip()


def default_control_migrations() -> tuple[Migration, ...]:
    """Ordered checksummed migrations for the control registry DuckDB."""

    bootstrap = _control_bootstrap_sql()
    catalog = _control_catalog_sql()
    _assert_sql_avoids_ducklake_internal(bootstrap, migration_id="0001_control_bootstrap")
    _assert_sql_avoids_ducklake_internal(catalog, migration_id="0002_control_catalog")
    return (
        Migration(
            migration_id="0001_control_bootstrap",
            version=1,
            namespace=CONTROL_NAMESPACE,
            description="Control registry migration bookkeeping and idempotency",
            sql=bootstrap,
            compatible_from=0,
            compatible_to=0,
            rollback=RollbackMetadata(
                strategy="sql",
                down_sql="""
DROP TABLE IF EXISTS lake_idempotency_keys;
DROP TABLE IF EXISTS migration_locks;
DROP TABLE IF EXISTS schema_migrations;
DROP TABLE IF EXISTS schema_registry;
""".strip(),
                notes="Bootstrap reverse; only safe on empty control registry",
            ),
        ),
        Migration(
            migration_id="0002_control_catalog",
            version=2,
            namespace=CONTROL_NAMESPACE,
            description=(
                "Control authority: catalogs, shards, home routing, owner "
                "generations, vector roots, migrations, promotion, release, projections"
            ),
            sql=catalog,
            compatible_from=1,
            compatible_to=1,
            rollback=RollbackMetadata(
                strategy="sql",
                down_sql="""
DROP TABLE IF EXISTS lake_signed_shard_projections;
DROP TABLE IF EXISTS lake_release_receipts;
DROP TABLE IF EXISTS lake_promotion_executions;
DROP TABLE IF EXISTS lake_promotion_decisions;
DROP TABLE IF EXISTS lake_shard_migrations;
DROP TABLE IF EXISTS lake_snapshot_vector_roots;
DROP TABLE IF EXISTS lake_catalog_owner_generations;
DROP TABLE IF EXISTS lake_dataset_home_shards;
DROP TABLE IF EXISTS lake_datasets;
DROP TABLE IF EXISTS lake_catalog_shards;
DROP TABLE IF EXISTS lake_catalogs;
""".strip(),
                notes="Drops control authority tables",
            ),
        ),
    )


def default_companion_migrations() -> tuple[Migration, ...]:
    """Ordered checksummed migrations for a per-shard companion registry DuckDB."""

    bootstrap = _companion_bootstrap_sql()
    local = _companion_local_sql()
    _assert_sql_avoids_ducklake_internal(
        bootstrap, migration_id="0001_companion_bootstrap"
    )
    _assert_sql_avoids_ducklake_internal(local, migration_id="0002_companion_local")
    return (
        Migration(
            migration_id="0001_companion_bootstrap",
            version=1,
            namespace=COMPANION_NAMESPACE,
            description="Companion registry migration bookkeeping and idempotency",
            sql=bootstrap,
            compatible_from=0,
            compatible_to=0,
            rollback=RollbackMetadata(
                strategy="sql",
                down_sql="""
DROP TABLE IF EXISTS lake_idempotency_keys;
DROP TABLE IF EXISTS migration_locks;
DROP TABLE IF EXISTS schema_migrations;
DROP TABLE IF EXISTS schema_registry;
""".strip(),
                notes="Bootstrap reverse; only safe on empty companion registry",
            ),
        ),
        Migration(
            migration_id="0002_companion_local",
            version=2,
            namespace=COMPANION_NAMESPACE,
            description=(
                "Companion authority: sources, schemas, files, ingest, reader "
                "leases, logical keys, outbox, ownership, maintenance, retention, lineage"
            ),
            sql=local,
            compatible_from=1,
            compatible_to=1,
            rollback=RollbackMetadata(
                strategy="sql",
                down_sql="""
DROP TABLE IF EXISTS lake_publication_lineage;
DROP TABLE IF EXISTS lake_retention_policies;
DROP TABLE IF EXISTS lake_maintenance_authorizations;
DROP TABLE IF EXISTS lake_ownership_state;
DROP TABLE IF EXISTS lake_ingest_outbox;
DROP TABLE IF EXISTS lake_logical_key_reservations;
DROP TABLE IF EXISTS lake_reader_leases;
DROP TABLE IF EXISTS lake_ingest_receipts;
DROP TABLE IF EXISTS lake_file_identities;
DROP TABLE IF EXISTS lake_schema_contracts;
DROP TABLE IF EXISTS lake_sources;
""".strip(),
                notes="Drops companion authority tables",
            ),
        ),
    )


def control_migration_catalog() -> MigrationCatalog:
    """Return the control-scope migration catalog."""

    return MigrationCatalog(
        migrations=default_control_migrations(),
        namespace=CONTROL_NAMESPACE,
    )


def companion_migration_catalog() -> MigrationCatalog:
    """Return the companion-scope migration catalog."""

    return MigrationCatalog(
        migrations=default_companion_migrations(),
        namespace=COMPANION_NAMESPACE,
    )


def authority_table_matrix() -> Mapping[str, str]:
    """Map exclusive authority tables to their scope name."""

    matrix: dict[str, str] = {}
    for table in sorted(
        CONTROL_TABLES
        - {
            "schema_registry",
            "schema_migrations",
            "migration_locks",
            "lake_idempotency_keys",
        }
    ):
        matrix[table] = RegistryScope.CONTROL.value
    for table in sorted(
        COMPANION_TABLES
        - {
            "schema_registry",
            "schema_migrations",
            "migration_locks",
            "lake_idempotency_keys",
        }
    ):
        matrix[table] = RegistryScope.COMPANION.value
    for short, physical in _ACCEPTANCE_AUTHORITY_ALIASES.items():
        if physical in matrix:
            matrix[short] = matrix[physical]
    return MappingProxyType(matrix)
