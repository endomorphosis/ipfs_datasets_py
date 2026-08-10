"""Logical federation over multiple Parquet datasets across DuckLake shards (DQK-091).

Map registered DuckDB + Quack DuckLake catalog shards, schemas, tables, and
views into versioned logical datasets; compile bounded unions and joins with
explicit field-ID / type reconciliation, partition and statistics pruning,
tenant policy, and snapshot-vector binding across heterogeneous Parquet
sources. Push each shard-local subplan through that shard's typed Quack
endpoint and combine **only** snapshot-receipted results; never ATTACH a
remote shard's catalog file.

Acceptance (DQK-091)
--------------------
* Queries aggregate at least two independently versioned Parquet datasets
  served by distinct DuckDB + Quack catalog shards
* The federation plan binds each shard endpoint, owner generation, snapshot,
  schema, and subresult digest
* No federating worker opens, copies, or network-mounts a catalog metadata file
* Field-ID remapping, missing columns, lossless type promotion, and partition
  evolution are deterministic
* File and row pruning are visible in bounded query evidence
* One unavailable catalog yields a typed policy-selected partial or failed
  result

Import is side-effect free: no DuckDB connection, no filesystem authority,
no network. Integration tests inject hermetic Quack endpoint doubles.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Iterable,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.ducklake.contracts import (
    ColumnPolicy,
    FieldContract,
    FieldType,
    MissingColumnPolicy,
    SchemaContract,
    TypePromotionError,
    TypePromotionRules,
    apply_column_policy,
    is_lossless_promotion,
    promote_value,
)
from ipfs_datasets_py.ducklake.snapshots import (
    SnapshotVector,
    SnapshotVectorMember,
    build_remote_worker_attach,
    verify_remote_snapshot_receipt,
    SignedSnapshotEvidence,
)

__all__ = [
    "FEDERATION_SCHEMA",
    "FEDERATION_PLAN_SCHEMA",
    "FEDERATION_RESULT_SCHEMA",
    "SHARD_SUBPLAN_SCHEMA",
    "SHARD_SUBRESULT_SCHEMA",
    "PRUNING_EVIDENCE_SCHEMA",
    "SCHEMA_RECONCILIATION_SCHEMA",
    "FEDERATION_IMPLEMENTATION_GENERATION",
    "CatalogFileAccessError",
    "CatalogUnavailableError",
    "FederationError",
    "FederationOp",
    "FederationPlan",
    "FederationStatus",
    "FederatedParquetQueryEngine",
    "FederatedQueryResult",
    "FieldRemapping",
    "FileFragment",
    "LogicalRelation",
    "LogicalRelationKind",
    "PartialFailurePolicy",
    "PartitionEvolution",
    "PartitionKey",
    "Predicate",
    "PruningEvidence",
    "QuackShardClient",
    "SchemaReconciliation",
    "SchemaReconciliationError",
    "ShardEndpointBinding",
    "ShardSubplan",
    "ShardSubresult",
    "ShardSubresultStatus",
    "TenantPolicy",
    "TenantPolicyError",
    "TypedFailure",
    "VersionedLogicalDataset",
    "assert_no_catalog_file_access",
    "combine_subresults",
    "compile_federation_plan",
    "deterministic_field_remapping",
    "least_upper_bound_type",
    "open_default_federation_engine",
    "prune_fragments",
    "push_subplan_via_quack",
    "reconcile_schemas",
]


# ---------------------------------------------------------------------------
# Schema pins / constants
# ---------------------------------------------------------------------------

FEDERATION_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-parquet-federation@1"
FEDERATION_PLAN_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-federation-plan@1"
)
FEDERATION_RESULT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-federation-result@1"
)
SHARD_SUBPLAN_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-federation-subplan@1"
)
SHARD_SUBRESULT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-federation-subresult@1"
)
PRUNING_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-federation-pruning@1"
)
SCHEMA_RECONCILIATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-federation-schema-reconcile@1"
)

FEDERATION_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-091-parquet-federation-20260810"
)

_SAFE_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_FIELD_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")

# Paths / schemes that must never appear as a federating-worker attach target.
_CATALOG_FILE_MARKERS: Final[tuple[str, ...]] = (
    ".duckdb",
    ".db",
    "file:",
    "nfs:",
    "smb:",
    "cifs:",
    "\\\\",
)

DEFAULT_MAX_ROWS: Final[int] = 100_000
DEFAULT_MAX_FILES_PER_SHARD: Final[int] = 10_000
MAX_DATASETS_PER_PLAN: Final[int] = 64
MAX_JOIN_KEYS: Final[int] = 16


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederationError(ValueError):
    """Fail-closed federation policy, plan, schema, or execution rejection."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "FEDERATION",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.details = dict(details or {})


class CatalogFileAccessError(FederationError):
    """Raised when a federating worker would open/copy/mount a catalog file."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="CATALOG_FILE_ACCESS", details=details)


class CatalogUnavailableError(FederationError):
    """Typed failure when a catalog shard endpoint is unavailable."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="CATALOG_UNAVAILABLE", details=details)


class SchemaReconciliationError(FederationError):
    """Field-ID remapping or type promotion cannot be reconciled deterministically."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="SCHEMA_RECONCILE", details=details)


class TenantPolicyError(FederationError):
    """Tenant / domain policy denied the federated query."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message, code="TENANT_POLICY", details=details)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LogicalRelationKind(str, Enum):
    """Catalog object kinds that map into versioned logical datasets."""

    TABLE = "table"
    VIEW = "view"
    SCHEMA = "schema"


class FederationOp(str, Enum):
    """Bounded federation operators over independently versioned datasets."""

    UNION_ALL = "union_all"
    INNER_JOIN = "inner_join"
    LEFT_JOIN = "left_join"


class PartialFailurePolicy(str, Enum):
    """How one unavailable catalog is handled.

    * ``FAIL`` / ``REQUIRE_ALL`` — overall failed unless every shard succeeds
    * ``PARTIAL`` / ``CONTINUE`` — return successes + typed partial failure
    * ``FAIL_FAST`` — abort siblings after first non-success (still typed)
    """

    FAIL = "fail"
    PARTIAL = "partial"
    REQUIRE_ALL = "require_all"
    CONTINUE = "continue"
    FAIL_FAST = "fail_fast"

    def allows_partial(self) -> bool:
        return self in {PartialFailurePolicy.PARTIAL, PartialFailurePolicy.CONTINUE}


class FederationStatus(str, Enum):
    """Terminal status of a federated query."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class ShardSubresultStatus(str, Enum):
    """Terminal status of one shard-local subplan."""

    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    SKIPPED = "skipped"
    RECEIPT_REJECTED = "receipt_rejected"


class FailureKind(str, Enum):
    """Closed set of typed partial / terminal failure kinds."""

    CATALOG_UNAVAILABLE = "catalog_unavailable"
    SNAPSHOT_MISMATCH = "snapshot_mismatch"
    SCHEMA_INCOMPATIBLE = "schema_incompatible"
    TENANT_DENIED = "tenant_denied"
    EXECUTION_ERROR = "execution_error"
    BUDGET_EXCEEDED = "budget_exceeded"
    CATALOG_FILE_ACCESS = "catalog_file_access"
    RECEIPT_REJECTED = "receipt_rejected"
    INTERNAL = "internal"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(ts: float | None = None) -> str:
    clock = time.time() if ts is None else float(ts)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock))


def _json_ready(value: Any) -> Any:
    """Convert MappingProxyType / nested mappings to plain JSON-ready values."""

    if isinstance(value, MappingProxyType):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, Mapping) and not isinstance(value, (str, bytes)):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_ready(v) for v in value)
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        _json_ready(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_of(payload: Any) -> str:
    return "sha256:" + _sha256_text(_canonical_json(payload))


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise FederationError(f"{field_name} is required", code="REQUIRED")
    return text


def _require_token(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_TOKEN.fullmatch(text):
        raise FederationError(f"invalid {field_name} {value!r}", code="TOKEN")
    return text


def _require_ident(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_IDENT.fullmatch(text):
        raise FederationError(f"invalid {field_name} {value!r}", code="IDENT")
    return text


def _require_field_id(value: Any) -> str:
    text = _require_nonempty(value, field_name="field_id")
    if not _FIELD_ID_RE.fullmatch(text):
        raise FederationError(f"invalid field_id {value!r}", code="FIELD_ID")
    return text


def _stable_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({str(v).strip() for v in values if str(v).strip()}))


def assert_no_catalog_file_access(
    target: str,
    *,
    context: str = "federating worker",
) -> None:
    """Fail closed if *target* looks like a catalog metadata file path/mount.

    Federating workers must open only authenticated Quack endpoints. Opening,
    copying, or network-mounting a live DuckDB catalog metadata file is
    forbidden (NFS / SMB / object URLs / ``file:`` / bare ``.duckdb`` paths).
    """

    raw = str(target or "").strip()
    if not raw:
        raise CatalogFileAccessError(
            f"{context} attach target is empty",
            target=target,
        )
    lowered = raw.lower()
    # Explicit Quack endpoint schemes are the only allowed remote surface.
    if lowered.startswith(("quack://", "quacks://")):
        if any(marker in lowered for marker in (".duckdb", ".db")):
            raise CatalogFileAccessError(
                f"{context} must not encode a catalog file in the Quack endpoint",
                target=target,
            )
        return
    # Reject absolute paths, UNC, network mounts, and object-store authority.
    if lowered.startswith(
        (
            "/",
            "file:",
            "nfs:",
            "smb:",
            "cifs:",
            "s3://",
            "gs://",
            "az://",
            "https://",
            "http://",
            "ducklake:",
        )
    ) or lowered.startswith("\\\\") or any(
        lowered.endswith(ext) for ext in (".duckdb", ".db")
    ):
        raise CatalogFileAccessError(
            f"{context} must not open, copy, or network-mount a catalog metadata "
            f"file (got {target!r}); use an authenticated Quack endpoint only",
            target=target,
        )
    # Bare host:port without scheme is also rejected — require quack(s)://.
    raise CatalogFileAccessError(
        f"{context} attach target must be quack:// or quacks:// "
        f"(got {target!r})",
        target=target,
    )


# ---------------------------------------------------------------------------
# Tenant policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    """Tenant / domain gate applied before plan compilation and execution."""

    tenant_id: str
    allowed_datasets: frozenset[str] = field(default_factory=frozenset)
    allowed_catalogs: frozenset[str] = field(default_factory=frozenset)
    deny_cross_tenant: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenant_id",
            _require_token(self.tenant_id, field_name="tenant_id"),
        )
        object.__setattr__(
            self,
            "allowed_datasets",
            frozenset(str(d).strip() for d in self.allowed_datasets if str(d).strip()),
        )
        object.__setattr__(
            self,
            "allowed_catalogs",
            frozenset(str(c).strip() for c in self.allowed_catalogs if str(c).strip()),
        )

    def authorize_dataset(self, *, dataset_id: str, tenant: str, catalog_id: str) -> None:
        if self.deny_cross_tenant and tenant != self.tenant_id:
            raise TenantPolicyError(
                f"tenant {self.tenant_id!r} denied cross-tenant dataset "
                f"{dataset_id!r} (owner tenant {tenant!r})",
                dataset_id=dataset_id,
                tenant=tenant,
            )
        if self.allowed_datasets and dataset_id not in self.allowed_datasets:
            raise TenantPolicyError(
                f"tenant {self.tenant_id!r} is not allowed dataset {dataset_id!r}",
                dataset_id=dataset_id,
            )
        if self.allowed_catalogs and catalog_id not in self.allowed_catalogs:
            raise TenantPolicyError(
                f"tenant {self.tenant_id!r} is not allowed catalog {catalog_id!r}",
                catalog_id=catalog_id,
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "tenant_id": self.tenant_id,
                "allowed_datasets": sorted(self.allowed_datasets),
                "allowed_catalogs": sorted(self.allowed_catalogs),
                "deny_cross_tenant": self.deny_cross_tenant,
            }
        )


# ---------------------------------------------------------------------------
# Logical dataset mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicalRelation:
    """One catalog schema / table / view mapped into a logical dataset."""

    dataset_id: str
    catalog_id: str
    shard_id: str
    quack_endpoint_identity: str
    relation_kind: LogicalRelationKind
    schema_name: str
    relation_name: str
    schema_contract: SchemaContract
    snapshot_version: int
    owner_generation: int
    fencing_epoch: int = 1
    tenant: str = "default"
    partition_keys: tuple[str, ...] = ()
    source_revision: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dataset_id", _require_nonempty(self.dataset_id, field_name="dataset_id")
        )
        object.__setattr__(
            self, "catalog_id", _require_token(self.catalog_id, field_name="catalog_id")
        )
        object.__setattr__(
            self, "shard_id", _require_token(self.shard_id, field_name="shard_id")
        )
        endpoint = _require_nonempty(
            self.quack_endpoint_identity, field_name="quack_endpoint_identity"
        )
        assert_no_catalog_file_access(endpoint, context="logical relation endpoint")
        object.__setattr__(self, "quack_endpoint_identity", endpoint)
        if not isinstance(self.relation_kind, LogicalRelationKind):
            object.__setattr__(
                self, "relation_kind", LogicalRelationKind(str(self.relation_kind))
            )
        object.__setattr__(
            self, "schema_name", _require_ident(self.schema_name, field_name="schema_name")
        )
        object.__setattr__(
            self,
            "relation_name",
            _require_ident(self.relation_name, field_name="relation_name"),
        )
        if not isinstance(self.schema_contract, SchemaContract):
            raise FederationError("schema_contract must be SchemaContract")
        if (
            not isinstance(self.snapshot_version, int)
            or isinstance(self.snapshot_version, bool)
            or self.snapshot_version < 0
        ):
            raise FederationError("snapshot_version must be a non-negative int")
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise FederationError("owner_generation must be a positive int")
        if (
            not isinstance(self.fencing_epoch, int)
            or isinstance(self.fencing_epoch, bool)
            or self.fencing_epoch < 1
        ):
            raise FederationError("fencing_epoch must be a positive int")
        object.__setattr__(
            self, "tenant", _require_token(self.tenant, field_name="tenant")
        )
        keys = tuple(
            _require_field_id(k) if _FIELD_ID_RE.fullmatch(str(k)) else _require_ident(k, field_name="partition_key")
            for k in self.partition_keys
        )
        # Deterministic partition-key order.
        object.__setattr__(self, "partition_keys", tuple(sorted(keys)))
        object.__setattr__(self, "source_revision", str(self.source_revision or "").strip())

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.relation_name}"

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "dataset_id": self.dataset_id,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "quack_endpoint_identity": self.quack_endpoint_identity,
                "relation_kind": self.relation_kind.value,
                "schema_name": self.schema_name,
                "relation_name": self.relation_name,
                "qualified_name": self.qualified_name,
                "schema_digest": self.schema_contract.schema_digest,
                "schema_revision": self.schema_contract.revision,
                "snapshot_version": self.snapshot_version,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "tenant": self.tenant,
                "partition_keys": list(self.partition_keys),
                "source_revision": self.source_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class VersionedLogicalDataset:
    """Versioned logical dataset bound to one home shard + snapshot."""

    dataset_id: str
    relation: LogicalRelation
    content_digest: str = ""
    logical_alias: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dataset_id", _require_nonempty(self.dataset_id, field_name="dataset_id")
        )
        if not isinstance(self.relation, LogicalRelation):
            raise FederationError("relation must be LogicalRelation")
        if self.relation.dataset_id != self.dataset_id:
            raise FederationError(
                f"dataset_id mismatch: {self.dataset_id!r} vs relation "
                f"{self.relation.dataset_id!r}"
            )
        digest = str(self.content_digest or "").strip()
        if digest and not digest.startswith("sha256:"):
            if len(digest) == 64 and all(c in "0123456789abcdefABCDEF" for c in digest):
                digest = f"sha256:{digest.lower()}"
            else:
                raise FederationError("content_digest must be sha256:<64-hex>")
        object.__setattr__(self, "content_digest", digest)
        alias = str(self.logical_alias or "").strip() or self.dataset_id.rsplit("/", 1)[-1]
        object.__setattr__(self, "logical_alias", alias)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "dataset_id": self.dataset_id,
                "logical_alias": self.logical_alias,
                "content_digest": self.content_digest,
                "relation": dict(self.relation.as_mapping()),
            }
        )


# ---------------------------------------------------------------------------
# Partition evolution + file / row pruning
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartitionKey:
    """One partition column value (field_id keyed)."""

    field_id: str
    value: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_id", _require_field_id(self.field_id))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType({"field_id": self.field_id, "value": self.value})


@dataclass(frozen=True, slots=True)
class PartitionEvolution:
    """Deterministic partition-key evolution across heterogeneous sources.

    Partition columns present in only some sources are nullable in the unified
    partition space. Order is always sorted by field_id so evolution is
    presentation-order independent.
    """

    partition_field_ids: tuple[str, ...]
    source_partitions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ids = tuple(sorted({_require_field_id(x) for x in self.partition_field_ids}))
        object.__setattr__(self, "partition_field_ids", ids)
        normalized: dict[str, tuple[str, ...]] = {}
        for src, keys in (self.source_partitions or {}).items():
            normalized[str(src)] = tuple(sorted({_require_field_id(k) for k in keys}))
        object.__setattr__(self, "source_partitions", MappingProxyType(normalized))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "partition_field_ids": list(self.partition_field_ids),
                "source_partitions": {
                    k: list(v) for k, v in sorted(self.source_partitions.items())
                },
            }
        )


@dataclass(frozen=True, slots=True)
class FileFragment:
    """One Parquet file (or row-group group) with partition + statistics."""

    file_id: str
    path: str
    content_digest: str
    row_count: int
    byte_size: int = 0
    partition: Mapping[str, Any] = field(default_factory=dict)
    column_stats: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # column_stats: field_id -> {min, max, null_count}

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "file_id", _require_nonempty(self.file_id, field_name="file_id")
        )
        object.__setattr__(
            self, "path", _require_nonempty(self.path, field_name="path")
        )
        digest = str(self.content_digest or "").strip()
        if digest and not digest.startswith("sha256:"):
            if len(digest) == 64 and all(c in "0123456789abcdefABCDEF" for c in digest):
                digest = f"sha256:{digest.lower()}"
        object.__setattr__(self, "content_digest", digest)
        if (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count < 0
        ):
            raise FederationError("row_count must be a non-negative int")
        object.__setattr__(self, "partition", MappingProxyType(dict(self.partition or {})))
        stats: dict[str, Mapping[str, Any]] = {}
        for fid, body in (self.column_stats or {}).items():
            stats[str(fid)] = MappingProxyType(dict(body or {}))
        object.__setattr__(self, "column_stats", MappingProxyType(stats))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "file_id": self.file_id,
                "path": self.path,
                "content_digest": self.content_digest,
                "row_count": self.row_count,
                "byte_size": self.byte_size,
                "partition": dict(self.partition),
                "column_stats": {k: dict(v) for k, v in self.column_stats.items()},
            }
        )


@dataclass(frozen=True, slots=True)
class Predicate:
    """Bounded push-down predicate used for partition / statistics pruning.

    Supports equality on partition keys and range on numeric/date columns.
    """

    field_id: str
    op: str  # eq | ne | lt | le | gt | ge | in
    value: Any = None
    values: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_id", _require_field_id(self.field_id))
        op = str(self.op or "").strip().lower()
        if op not in {"eq", "ne", "lt", "le", "gt", "ge", "in"}:
            raise FederationError(f"unsupported predicate op {self.op!r}", code="PREDICATE")
        object.__setattr__(self, "op", op)
        object.__setattr__(self, "values", tuple(self.values or ()))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "field_id": self.field_id,
                "op": self.op,
                "value": self.value,
                "values": list(self.values),
            }
        )


def _cmp_may_match(op: str, *, lo: Any, hi: Any, value: Any, values: Sequence[Any]) -> bool:
    """Return True if the [lo, hi] range might contain rows matching the predicate."""

    try:
        if op == "eq":
            if lo is not None and value < lo:
                return False
            if hi is not None and value > hi:
                return False
            return True
        if op == "ne":
            # Only prune when the entire range is a single equal value.
            if lo is not None and hi is not None and lo == hi == value:
                return False
            return True
        if op == "lt":
            if lo is not None and lo >= value:
                return False
            return True
        if op == "le":
            if lo is not None and lo > value:
                return False
            return True
        if op == "gt":
            if hi is not None and hi <= value:
                return False
            return True
        if op == "ge":
            if hi is not None and hi < value:
                return False
            return True
        if op == "in":
            if not values:
                return False
            for v in values:
                if lo is not None and v < lo:
                    continue
                if hi is not None and v > hi:
                    continue
                return True
            # Also accept when stats absent.
            if lo is None and hi is None:
                return True
            return False
    except TypeError:
        # Incomparable types → cannot prune.
        return True
    return True


def _partition_matches(partition: Mapping[str, Any], predicates: Sequence[Predicate]) -> bool:
    for pred in predicates:
        if pred.field_id not in partition:
            continue
        actual = partition[pred.field_id]
        if pred.op == "eq" and actual != pred.value:
            return False
        if pred.op == "ne" and actual == pred.value:
            return False
        if pred.op == "in" and actual not in pred.values:
            return False
        if pred.op in {"lt", "le", "gt", "ge"}:
            try:
                if pred.op == "lt" and not (actual < pred.value):
                    return False
                if pred.op == "le" and not (actual <= pred.value):
                    return False
                if pred.op == "gt" and not (actual > pred.value):
                    return False
                if pred.op == "ge" and not (actual >= pred.value):
                    return False
            except TypeError:
                continue
    return True


def _stats_may_match(
    column_stats: Mapping[str, Mapping[str, Any]],
    predicates: Sequence[Predicate],
) -> bool:
    for pred in predicates:
        stats = column_stats.get(pred.field_id)
        if not stats:
            continue
        lo = stats.get("min")
        hi = stats.get("max")
        if not _cmp_may_match(
            pred.op, lo=lo, hi=hi, value=pred.value, values=pred.values
        ):
            return False
    return True


@dataclass(frozen=True, slots=True)
class PruningEvidence:
    """Bounded, visible file and row pruning evidence for one shard subplan."""

    SCHEMA: ClassVar[str] = PRUNING_EVIDENCE_SCHEMA
    files_considered: int
    files_selected: int
    files_pruned: int
    rows_considered: int
    rows_selected: int
    rows_pruned: int
    pruned_file_ids: tuple[str, ...] = ()
    selected_file_ids: tuple[str, ...] = ()
    predicates: tuple[Predicate, ...] = ()
    partition_pruned_files: int = 0
    statistics_pruned_files: int = 0

    def __post_init__(self) -> None:
        if self.files_considered < 0 or self.files_selected < 0 or self.files_pruned < 0:
            raise FederationError("pruning file counts must be non-negative")
        if self.files_selected + self.files_pruned != self.files_considered:
            raise FederationError(
                "files_selected + files_pruned must equal files_considered",
                details={
                    "files_considered": self.files_considered,
                    "files_selected": self.files_selected,
                    "files_pruned": self.files_pruned,
                },
            )
        if self.rows_selected + self.rows_pruned != self.rows_considered:
            raise FederationError(
                "rows_selected + rows_pruned must equal rows_considered"
            )
        object.__setattr__(
            self,
            "pruned_file_ids",
            tuple(sorted(self.pruned_file_ids)),
        )
        object.__setattr__(
            self,
            "selected_file_ids",
            tuple(sorted(self.selected_file_ids)),
        )
        object.__setattr__(self, "predicates", tuple(self.predicates))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "files_considered": self.files_considered,
                "files_selected": self.files_selected,
                "files_pruned": self.files_pruned,
                "rows_considered": self.rows_considered,
                "rows_selected": self.rows_selected,
                "rows_pruned": self.rows_pruned,
                "pruned_file_ids": list(self.pruned_file_ids),
                "selected_file_ids": list(self.selected_file_ids),
                "predicates": [dict(p.as_mapping()) for p in self.predicates],
                "partition_pruned_files": self.partition_pruned_files,
                "statistics_pruned_files": self.statistics_pruned_files,
            }
        )


def prune_fragments(
    fragments: Sequence[FileFragment],
    predicates: Sequence[Predicate],
    *,
    max_files: int = DEFAULT_MAX_FILES_PER_SHARD,
) -> tuple[tuple[FileFragment, ...], PruningEvidence]:
    """Deterministically prune files by partition keys then column statistics."""

    if max_files < 1:
        raise FederationError("max_files must be >= 1")
    ordered = tuple(sorted(fragments, key=lambda f: (f.file_id, f.path)))
    preds = tuple(predicates or ())
    selected: list[FileFragment] = []
    pruned_ids: list[str] = []
    selected_ids: list[str] = []
    rows_considered = 0
    rows_selected = 0
    partition_pruned = 0
    stats_pruned = 0

    for frag in ordered:
        rows_considered += frag.row_count
        if preds and not _partition_matches(frag.partition, preds):
            pruned_ids.append(frag.file_id)
            partition_pruned += 1
            continue
        if preds and not _stats_may_match(frag.column_stats, preds):
            pruned_ids.append(frag.file_id)
            stats_pruned += 1
            continue
        selected.append(frag)
        selected_ids.append(frag.file_id)
        rows_selected += frag.row_count

    if len(selected) > max_files:
        raise FederationError(
            f"selected files {len(selected)} exceed max_files {max_files}",
            code="BUDGET",
            details={"selected": len(selected), "max_files": max_files},
        )

    evidence = PruningEvidence(
        files_considered=len(ordered),
        files_selected=len(selected),
        files_pruned=len(pruned_ids),
        rows_considered=rows_considered,
        rows_selected=rows_selected,
        rows_pruned=rows_considered - rows_selected,
        pruned_file_ids=tuple(pruned_ids),
        selected_file_ids=tuple(selected_ids),
        predicates=preds,
        partition_pruned_files=partition_pruned,
        statistics_pruned_files=stats_pruned,
    )
    return tuple(selected), evidence


# ---------------------------------------------------------------------------
# Field-ID remapping + schema reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldRemapping:
    """Deterministic source field_id → unified field_id + type promotion."""

    source_field_id: str
    target_field_id: str
    source_type: FieldType
    target_type: FieldType
    source_name: str = ""
    target_name: str = ""
    promoted: bool = False
    missing: bool = False
    default_value: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_field_id", _require_field_id(self.source_field_id)
        )
        object.__setattr__(
            self, "target_field_id", _require_field_id(self.target_field_id)
        )
        object.__setattr__(self, "source_type", FieldType.parse(self.source_type))
        object.__setattr__(self, "target_type", FieldType.parse(self.target_type))
        if not self.missing and not is_lossless_promotion(
            self.source_type, self.target_type
        ):
            raise SchemaReconciliationError(
                f"lossy promotion {self.source_type.value} -> "
                f"{self.target_type.value} for field_id {self.source_field_id!r}",
                source_field_id=self.source_field_id,
                source_type=self.source_type.value,
                target_type=self.target_type.value,
            )
        object.__setattr__(
            self,
            "promoted",
            bool(self.promoted) or (self.source_type is not self.target_type),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "source_field_id": self.source_field_id,
                "target_field_id": self.target_field_id,
                "source_type": self.source_type.value,
                "target_type": self.target_type.value,
                "source_name": self.source_name,
                "target_name": self.target_name,
                "promoted": self.promoted,
                "missing": self.missing,
                "default_value": self.default_value,
            }
        )


def least_upper_bound_type(
    types: Sequence[str | FieldType],
    *,
    rules: TypePromotionRules | None = None,
) -> FieldType:
    """Compute a deterministic lossless least-upper-bound field type.

    Preference order among candidates that dominate all inputs follows the
    closed FieldType value order so the result is presentation-order independent.
    """

    parsed = [FieldType.parse(t) for t in types]
    if not parsed:
        raise SchemaReconciliationError("cannot compute LUB of empty type set")
    if len(parsed) == 1:
        return parsed[0]
    promotion = rules or TypePromotionRules()
    # Candidate set: every type that is a lossless promotion target of all inputs.
    candidates: list[FieldType] = []
    for cand in FieldType:
        if all(promotion.allows(src, cand) for src in parsed):
            candidates.append(cand)
    if not candidates:
        raise SchemaReconciliationError(
            "no lossless least-upper-bound type for "
            + ", ".join(sorted(t.value for t in parsed)),
            types=sorted(t.value for t in parsed),
        )
    # Prefer the "narrowest" candidate: fewest incoming edges among inputs that
    # are already equal to cand, then stable FieldType definition order.
    def _score(cand: FieldType) -> tuple[int, str]:
        # 0 if cand is already one of the inputs (prefer no-op when possible)
        present = 0 if cand in parsed else 1
        return (present, cand.value)

    return sorted(candidates, key=_score)[0]


def deterministic_field_remapping(
    source: SchemaContract,
    target_fields: Sequence[FieldContract],
    *,
    column_policy: ColumnPolicy | None = None,
    promotion_rules: TypePromotionRules | None = None,
) -> tuple[FieldRemapping, ...]:
    """Build deterministic source→target remappings keyed by field_id.

    Matching is by stable ``field_id`` only (names may differ across shards).
    Missing source columns are filled per *column_policy*; lossy promotions
    fail closed.
    """

    policy = column_policy or source.column_policy
    rules = promotion_rules or source.promotion_rules
    source_by_id = {f.field_id: f for f in source.fields}
    remaps: list[FieldRemapping] = []
    # Target fields sorted by field_id for determinism.
    for target in sorted(target_fields, key=lambda f: f.field_id):
        src = source_by_id.get(target.field_id)
        if src is None:
            if target.required or not target.nullable:
                if (
                    policy.missing is MissingColumnPolicy.DEFAULT
                    and target.default is not None
                ):
                    remaps.append(
                        FieldRemapping(
                            source_field_id=target.field_id,
                            target_field_id=target.field_id,
                            source_type=target.field_type,
                            target_type=target.field_type,
                            source_name=target.name,
                            target_name=target.name,
                            missing=True,
                            default_value=target.default,
                        )
                    )
                    continue
                if policy.missing is MissingColumnPolicy.NULL_IF_NULLABLE and target.nullable:
                    remaps.append(
                        FieldRemapping(
                            source_field_id=target.field_id,
                            target_field_id=target.field_id,
                            source_type=target.field_type,
                            target_type=target.field_type,
                            source_name=target.name,
                            target_name=target.name,
                            missing=True,
                            default_value=None,
                        )
                    )
                    continue
                if not target.required and target.nullable:
                    remaps.append(
                        FieldRemapping(
                            source_field_id=target.field_id,
                            target_field_id=target.field_id,
                            source_type=target.field_type,
                            target_type=target.field_type,
                            source_name=target.name,
                            target_name=target.name,
                            missing=True,
                            default_value=None,
                        )
                    )
                    continue
                raise SchemaReconciliationError(
                    f"missing required field_id {target.field_id!r} in source "
                    f"schema {source.contract_id!r}",
                    field_id=target.field_id,
                    source_contract=source.contract_id,
                )
            remaps.append(
                FieldRemapping(
                    source_field_id=target.field_id,
                    target_field_id=target.field_id,
                    source_type=target.field_type,
                    target_type=target.field_type,
                    source_name=target.name,
                    target_name=target.name,
                    missing=True,
                    default_value=(
                        target.default
                        if policy.missing is MissingColumnPolicy.DEFAULT
                        else None
                    ),
                )
            )
            continue
        if not rules.allows(src.field_type, target.field_type):
            raise SchemaReconciliationError(
                f"cannot promote field_id {src.field_id!r} from "
                f"{src.field_type.value} to {target.field_type.value}",
                field_id=src.field_id,
                source_type=src.field_type.value,
                target_type=target.field_type.value,
            )
        remaps.append(
            FieldRemapping(
                source_field_id=src.field_id,
                target_field_id=target.field_id,
                source_type=src.field_type,
                target_type=target.field_type,
                source_name=src.name,
                target_name=target.name,
                promoted=src.field_type is not target.field_type,
            )
        )
    return tuple(remaps)


@dataclass(frozen=True, slots=True)
class SchemaReconciliation:
    """Unified output schema + per-source field remappings."""

    SCHEMA: ClassVar[str] = SCHEMA_RECONCILIATION_SCHEMA
    unified_fields: tuple[FieldContract, ...]
    remappings: Mapping[str, tuple[FieldRemapping, ...]]
    partition_evolution: PartitionEvolution
    schema_digest: str = ""

    def __post_init__(self) -> None:
        fields = tuple(sorted(self.unified_fields, key=lambda f: f.field_id))
        if not fields:
            raise SchemaReconciliationError("unified schema requires at least one field")
        object.__setattr__(self, "unified_fields", fields)
        normalized: dict[str, tuple[FieldRemapping, ...]] = {}
        for dataset_id, remaps in (self.remappings or {}).items():
            normalized[str(dataset_id)] = tuple(remaps)
        object.__setattr__(self, "remappings", MappingProxyType(normalized))
        if not isinstance(self.partition_evolution, PartitionEvolution):
            raise SchemaReconciliationError(
                "partition_evolution must be PartitionEvolution"
            )
        if not self.schema_digest:
            object.__setattr__(
                self,
                "schema_digest",
                _digest_of(
                    {
                        "fields": [dict(f.as_mapping()) for f in fields],
                        "remappings": {
                            k: [dict(r.as_mapping()) for r in v]
                            for k, v in sorted(normalized.items())
                        },
                        "partition_evolution": dict(
                            self.partition_evolution.as_mapping()
                        ),
                    }
                ),
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "schema_digest": self.schema_digest,
                "unified_fields": [dict(f.as_mapping()) for f in self.unified_fields],
                "remappings": {
                    k: [dict(r.as_mapping()) for r in v]
                    for k, v in sorted(self.remappings.items())
                },
                "partition_evolution": dict(self.partition_evolution.as_mapping()),
            }
        )


def reconcile_schemas(
    datasets: Sequence[VersionedLogicalDataset],
    *,
    column_policy: ColumnPolicy | None = None,
    promotion_rules: TypePromotionRules | None = None,
) -> SchemaReconciliation:
    """Reconcile heterogeneous source schemas into one deterministic unified schema.

    Field identity is by ``field_id``. Types are lifted to a lossless LUB.
    Partition keys across sources are unioned (partition evolution).
    """

    if len(datasets) < 1:
        raise SchemaReconciliationError("reconcile_schemas requires at least one dataset")
    rules = promotion_rules or TypePromotionRules()
    # Union of field_ids in sorted order.
    field_ids: set[str] = set()
    name_votes: dict[str, set[str]] = {}
    type_votes: dict[str, list[FieldType]] = {}
    nullable_votes: dict[str, bool] = {}
    required_votes: dict[str, bool] = {}
    defaults: dict[str, Any] = {}
    for ds in datasets:
        for f in ds.relation.schema_contract.fields:
            field_ids.add(f.field_id)
            name_votes.setdefault(f.field_id, set()).add(f.name)
            type_votes.setdefault(f.field_id, []).append(f.field_type)
            nullable_votes[f.field_id] = nullable_votes.get(f.field_id, False) or f.nullable
            # Required only if required in every source that has it AND present in all.
            if f.field_id not in required_votes:
                required_votes[f.field_id] = f.required
            else:
                required_votes[f.field_id] = required_votes[f.field_id] and f.required
            if f.default is not None and f.field_id not in defaults:
                defaults[f.field_id] = f.default

    # Fields present in only some sources become nullable / not required.
    present_counts: dict[str, int] = {fid: 0 for fid in field_ids}
    for ds in datasets:
        ids = {f.field_id for f in ds.relation.schema_contract.fields}
        for fid in ids:
            present_counts[fid] += 1
    n = len(datasets)
    unified: list[FieldContract] = []
    for fid in sorted(field_ids):
        lub = least_upper_bound_type(type_votes[fid], rules=rules)
        names = sorted(name_votes[fid])
        # Prefer lexicographically first name for determinism.
        name = names[0]
        nullable = nullable_votes.get(fid, True) or present_counts[fid] < n
        required = bool(required_votes.get(fid, False)) and present_counts[fid] == n
        unified.append(
            FieldContract(
                field_id=fid,
                name=name,
                field_type=lub,
                nullable=nullable,
                default=defaults.get(fid),
                required=required,
            )
        )

    policy = column_policy or ColumnPolicy(
        missing=MissingColumnPolicy.NULL_IF_NULLABLE,
        require_field_ids=True,
    )
    remappings: dict[str, tuple[FieldRemapping, ...]] = {}
    for ds in datasets:
        remappings[ds.dataset_id] = deterministic_field_remapping(
            ds.relation.schema_contract,
            unified,
            column_policy=policy,
            promotion_rules=rules,
        )

    source_partitions = {
        ds.dataset_id: tuple(ds.relation.partition_keys) for ds in datasets
    }
    all_partition_ids = sorted(
        {k for keys in source_partitions.values() for k in keys}
    )
    evolution = PartitionEvolution(
        partition_field_ids=tuple(all_partition_ids),
        source_partitions=source_partitions,
    )
    return SchemaReconciliation(
        unified_fields=tuple(unified),
        remappings=remappings,
        partition_evolution=evolution,
    )


def _project_row(
    row: Mapping[str, Any],
    remaps: Sequence[FieldRemapping],
) -> dict[str, Any]:
    """Project one source row through remappings into unified field_id space."""

    # Accept either field_id or name keys in the source row.
    out: dict[str, Any] = {}
    for remap in remaps:
        if remap.missing:
            out[remap.target_field_id] = remap.default_value
            continue
        if remap.source_field_id in row:
            value = row[remap.source_field_id]
        elif remap.source_name and remap.source_name in row:
            value = row[remap.source_name]
        else:
            value = remap.default_value
        if value is not None and remap.promoted:
            try:
                value = promote_value(
                    value, source=remap.source_type, target=remap.target_type
                )
            except TypePromotionError as exc:
                raise SchemaReconciliationError(
                    str(exc), field_id=remap.source_field_id
                ) from exc
        out[remap.target_field_id] = value
    return out


# ---------------------------------------------------------------------------
# Plan types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShardEndpointBinding:
    """Per-shard binding of endpoint, owner generation, snapshot, and schema."""

    catalog_id: str
    shard_id: str
    quack_endpoint_identity: str
    owner_generation: int
    fencing_epoch: int
    snapshot_version: int
    schema_digest: str
    schema_revision: int
    dataset_id: str
    opens_catalog_file: bool = False
    catalog_metadata_path: str = ""  # never used by workers; diagnostic only

    def __post_init__(self) -> None:
        if self.opens_catalog_file:
            raise CatalogFileAccessError(
                "federation plan bindings must set opens_catalog_file=False; "
                "workers never open remote catalog metadata files",
                catalog_id=self.catalog_id,
            )
        object.__setattr__(
            self, "catalog_id", _require_token(self.catalog_id, field_name="catalog_id")
        )
        object.__setattr__(
            self, "shard_id", _require_token(self.shard_id, field_name="shard_id")
        )
        endpoint = _require_nonempty(
            self.quack_endpoint_identity, field_name="quack_endpoint_identity"
        )
        assert_no_catalog_file_access(endpoint, context="shard endpoint binding")
        object.__setattr__(self, "quack_endpoint_identity", endpoint)
        object.__setattr__(
            self, "schema_digest", _require_nonempty(self.schema_digest, field_name="schema_digest")
        )
        object.__setattr__(
            self, "dataset_id", _require_nonempty(self.dataset_id, field_name="dataset_id")
        )
        # Explicitly clear any accidental catalog path so plans never carry
        # authority paths into workers.
        object.__setattr__(self, "catalog_metadata_path", "")
        object.__setattr__(self, "opens_catalog_file", False)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "quack_endpoint_identity": self.quack_endpoint_identity,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "snapshot_version": self.snapshot_version,
                "schema_digest": self.schema_digest,
                "schema_revision": self.schema_revision,
                "dataset_id": self.dataset_id,
                "opens_catalog_file": False,
                "attach_target": "authenticated_quack_endpoint",
            }
        )


@dataclass(frozen=True, slots=True)
class ShardSubplan:
    """One shard-local subplan pushed through a typed Quack endpoint."""

    SCHEMA: ClassVar[str] = SHARD_SUBPLAN_SCHEMA
    subplan_id: str
    dataset_id: str
    binding: ShardEndpointBinding
    qualified_relation: str
    projected_field_ids: tuple[str, ...]
    remappings: tuple[FieldRemapping, ...]
    predicates: tuple[Predicate, ...]
    selected_file_ids: tuple[str, ...]
    pruning: PruningEvidence
    vector_id: str
    subresult_digest_placeholder: str = ""  # filled after execution
    canonical_sql: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "subplan_id", _require_nonempty(self.subplan_id, field_name="subplan_id")
        )
        if not isinstance(self.binding, ShardEndpointBinding):
            raise FederationError("binding must be ShardEndpointBinding")
        if self.binding.opens_catalog_file:
            raise CatalogFileAccessError(
                "subplan binding must not open catalog files",
                subplan_id=self.subplan_id,
            )
        object.__setattr__(
            self,
            "projected_field_ids",
            tuple(sorted({_require_field_id(f) for f in self.projected_field_ids})),
        )
        object.__setattr__(self, "remappings", tuple(self.remappings))
        object.__setattr__(self, "predicates", tuple(self.predicates))
        object.__setattr__(
            self, "selected_file_ids", tuple(sorted(self.selected_file_ids))
        )
        object.__setattr__(
            self, "vector_id", _require_nonempty(self.vector_id, field_name="vector_id")
        )
        if not self.canonical_sql:
            cols = ", ".join(self.projected_field_ids) or "*"
            preds = " AND ".join(
                f"{p.field_id} {p.op} ?" for p in self.predicates
            )
            where = f" WHERE {preds}" if preds else ""
            sql = (
                f"SELECT {cols} FROM {self.qualified_relation}"
                f"{where} /* snapshot={self.binding.snapshot_version} "
                f"files={len(self.selected_file_ids)} */"
            )
            object.__setattr__(self, "canonical_sql", sql)

    def plan_digest(self) -> str:
        return _digest_of(self.as_mapping())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "subplan_id": self.subplan_id,
                "dataset_id": self.dataset_id,
                "binding": dict(self.binding.as_mapping()),
                "qualified_relation": self.qualified_relation,
                "projected_field_ids": list(self.projected_field_ids),
                "remappings": [dict(r.as_mapping()) for r in self.remappings],
                "predicates": [dict(p.as_mapping()) for p in self.predicates],
                "selected_file_ids": list(self.selected_file_ids),
                "pruning": dict(self.pruning.as_mapping()),
                "vector_id": self.vector_id,
                "canonical_sql": self.canonical_sql,
                "opens_catalog_file": False,
            }
        )


@dataclass(frozen=True, slots=True)
class FederationPlan:
    """Compiled federation plan over ≥2 independently versioned datasets."""

    SCHEMA: ClassVar[str] = FEDERATION_PLAN_SCHEMA
    plan_id: str
    op: FederationOp
    dataset_ids: tuple[str, ...]
    subplans: tuple[ShardSubplan, ...]
    reconciliation: SchemaReconciliation
    snapshot_vector_id: str
    snapshot_vector_digest: str
    tenant_policy: TenantPolicy
    partial_failure_policy: PartialFailurePolicy
    join_keys: tuple[str, ...] = ()
    max_rows: int = DEFAULT_MAX_ROWS
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "plan_id", _require_nonempty(self.plan_id, field_name="plan_id")
        )
        if not isinstance(self.op, FederationOp):
            object.__setattr__(self, "op", FederationOp(str(self.op)))
        ids = tuple(self.dataset_ids)
        if len(ids) < 2:
            raise FederationError(
                "federation plan requires at least two independently versioned datasets",
                code="PLAN",
            )
        if len(ids) != len(set(ids)):
            raise FederationError("duplicate dataset_id in federation plan", code="PLAN")
        object.__setattr__(self, "dataset_ids", ids)
        if len(self.subplans) < 2:
            raise FederationError(
                "federation plan requires subplans for at least two catalog shards",
                code="PLAN",
            )
        catalogs = {sp.binding.catalog_id for sp in self.subplans}
        if len(catalogs) < 2:
            raise FederationError(
                "federation requires distinct DuckDB + Quack catalog shards; "
                f"got catalogs={sorted(catalogs)}",
                code="PLAN",
            )
        # Every subplan must refuse catalog-file open.
        for sp in self.subplans:
            if sp.binding.opens_catalog_file:
                raise CatalogFileAccessError(
                    "plan subplan opens catalog file",
                    subplan_id=sp.subplan_id,
                )
        object.__setattr__(self, "subplans", tuple(self.subplans))
        if not isinstance(self.reconciliation, SchemaReconciliation):
            raise FederationError("reconciliation must be SchemaReconciliation")
        object.__setattr__(
            self,
            "snapshot_vector_id",
            _require_nonempty(self.snapshot_vector_id, field_name="snapshot_vector_id"),
        )
        object.__setattr__(
            self,
            "snapshot_vector_digest",
            _require_nonempty(
                self.snapshot_vector_digest, field_name="snapshot_vector_digest"
            ),
        )
        if not isinstance(self.tenant_policy, TenantPolicy):
            raise FederationError("tenant_policy must be TenantPolicy")
        if not isinstance(self.partial_failure_policy, PartialFailurePolicy):
            object.__setattr__(
                self,
                "partial_failure_policy",
                PartialFailurePolicy(str(self.partial_failure_policy)),
            )
        keys = tuple(sorted({_require_field_id(k) for k in self.join_keys}))
        if self.op in {FederationOp.INNER_JOIN, FederationOp.LEFT_JOIN}:
            if not keys:
                raise FederationError(
                    f"{self.op.value} requires at least one join key",
                    code="PLAN",
                )
            if len(keys) > MAX_JOIN_KEYS:
                raise FederationError("too many join keys", code="PLAN")
        object.__setattr__(self, "join_keys", keys)
        if (
            not isinstance(self.max_rows, int)
            or isinstance(self.max_rows, bool)
            or self.max_rows < 1
        ):
            raise FederationError("max_rows must be a positive int")
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_iso())

    def plan_digest(self) -> str:
        return _digest_of(self.as_mapping())

    def binding_for(self, catalog_id: str) -> ShardEndpointBinding:
        for sp in self.subplans:
            if sp.binding.catalog_id == catalog_id:
                return sp.binding
        raise FederationError(f"no binding for catalog {catalog_id!r}")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "plan_id": self.plan_id,
                "op": self.op.value,
                "dataset_ids": list(self.dataset_ids),
                "subplans": [dict(sp.as_mapping()) for sp in self.subplans],
                "reconciliation": dict(self.reconciliation.as_mapping()),
                "snapshot_vector_id": self.snapshot_vector_id,
                "snapshot_vector_digest": self.snapshot_vector_digest,
                "tenant_policy": dict(self.tenant_policy.as_mapping()),
                "partial_failure_policy": self.partial_failure_policy.value,
                "join_keys": list(self.join_keys),
                "max_rows": self.max_rows,
                "created_at": self.created_at,
                "implementation_generation": FEDERATION_IMPLEMENTATION_GENERATION,
                "opens_catalog_file": False,
            }
        )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedFailure:
    """Typed partial / terminal failure for one shard."""

    kind: FailureKind
    catalog_id: str
    dataset_id: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FailureKind):
            object.__setattr__(self, "kind", FailureKind(str(self.kind)))
        object.__setattr__(self, "details", MappingProxyType(dict(self.details or {})))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "kind": self.kind.value,
                "catalog_id": self.catalog_id,
                "dataset_id": self.dataset_id,
                "message": self.message,
                "details": dict(self.details),
            }
        )


@dataclass(frozen=True, slots=True)
class ShardSubresult:
    """Snapshot-receipted result of one shard-local subplan."""

    SCHEMA: ClassVar[str] = SHARD_SUBRESULT_SCHEMA
    subplan_id: str
    dataset_id: str
    catalog_id: str
    status: ShardSubresultStatus
    rows: tuple[Mapping[str, Any], ...]
    subresult_digest: str
    snapshot_version: int
    owner_generation: int
    schema_digest: str
    quack_endpoint_identity: str
    pruning: PruningEvidence | None = None
    snapshot_evidence: Mapping[str, Any] | None = None
    failure: TypedFailure | None = None
    opens_catalog_file: bool = False

    def __post_init__(self) -> None:
        if self.opens_catalog_file:
            raise CatalogFileAccessError(
                "subresult must not indicate catalog file open",
                subplan_id=self.subplan_id,
            )
        if not isinstance(self.status, ShardSubresultStatus):
            object.__setattr__(self, "status", ShardSubresultStatus(str(self.status)))
        normalized_rows = tuple(
            MappingProxyType(dict(r)) for r in (self.rows or ())
        )
        object.__setattr__(self, "rows", normalized_rows)
        if self.status is ShardSubresultStatus.SUCCEEDED and not self.subresult_digest:
            object.__setattr__(
                self,
                "subresult_digest",
                _digest_of(
                    {
                        "subplan_id": self.subplan_id,
                        "rows": [dict(r) for r in normalized_rows],
                        "snapshot_version": self.snapshot_version,
                        "schema_digest": self.schema_digest,
                    }
                ),
            )
        object.__setattr__(self, "opens_catalog_file", False)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "subplan_id": self.subplan_id,
                "dataset_id": self.dataset_id,
                "catalog_id": self.catalog_id,
                "status": self.status.value,
                "row_count": len(self.rows),
                "subresult_digest": self.subresult_digest,
                "snapshot_version": self.snapshot_version,
                "owner_generation": self.owner_generation,
                "schema_digest": self.schema_digest,
                "quack_endpoint_identity": self.quack_endpoint_identity,
                "pruning": None if self.pruning is None else dict(self.pruning.as_mapping()),
                "snapshot_evidence": (
                    None if self.snapshot_evidence is None else dict(self.snapshot_evidence)
                ),
                "failure": None if self.failure is None else dict(self.failure.as_mapping()),
                "opens_catalog_file": False,
            }
        )


@dataclass(frozen=True, slots=True)
class FederatedQueryResult:
    """Combined federation result with bounded query evidence."""

    SCHEMA: ClassVar[str] = FEDERATION_RESULT_SCHEMA
    plan_id: str
    plan_digest: str
    status: FederationStatus
    rows: tuple[Mapping[str, Any], ...]
    result_digest: str
    subresults: tuple[ShardSubresult, ...]
    failures: tuple[TypedFailure, ...]
    pruning_evidence: tuple[Mapping[str, Any], ...]
    snapshot_vector_id: str
    snapshot_vector_digest: str
    partial_failure_policy: PartialFailurePolicy
    created_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, FederationStatus):
            object.__setattr__(self, "status", FederationStatus(str(self.status)))
        object.__setattr__(
            self, "rows", tuple(MappingProxyType(dict(r)) for r in (self.rows or ()))
        )
        object.__setattr__(self, "subresults", tuple(self.subresults))
        object.__setattr__(self, "failures", tuple(self.failures))
        object.__setattr__(
            self,
            "pruning_evidence",
            tuple(MappingProxyType(dict(p)) for p in (self.pruning_evidence or ())),
        )
        if not isinstance(self.partial_failure_policy, PartialFailurePolicy):
            object.__setattr__(
                self,
                "partial_failure_policy",
                PartialFailurePolicy(str(self.partial_failure_policy)),
            )
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_iso())
        if not self.result_digest:
            object.__setattr__(
                self,
                "result_digest",
                _digest_of(
                    {
                        "plan_id": self.plan_id,
                        "status": self.status.value,
                        "rows": [dict(r) for r in self.rows],
                        "subresult_digests": [
                            sr.subresult_digest for sr in self.subresults
                        ],
                        "snapshot_vector_id": self.snapshot_vector_id,
                    }
                ),
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "plan_id": self.plan_id,
                "plan_digest": self.plan_digest,
                "status": self.status.value,
                "row_count": len(self.rows),
                "result_digest": self.result_digest,
                "subresults": [dict(sr.as_mapping()) for sr in self.subresults],
                "failures": [dict(f.as_mapping()) for f in self.failures],
                "pruning_evidence": [dict(p) for p in self.pruning_evidence],
                "snapshot_vector_id": self.snapshot_vector_id,
                "snapshot_vector_digest": self.snapshot_vector_digest,
                "partial_failure_policy": self.partial_failure_policy.value,
                "created_at": self.created_at,
                "implementation_generation": FEDERATION_IMPLEMENTATION_GENERATION,
                "opens_catalog_file": False,
            }
        )


# ---------------------------------------------------------------------------
# Quack endpoint protocol + push
# ---------------------------------------------------------------------------


class QuackShardClient(Protocol):
    """Typed Quack endpoint client for one catalog shard.

    Implementations must never open, copy, or network-mount catalog metadata
    files. Only authenticated Quack transport is permitted.
    """

    catalog_id: str
    quack_endpoint_identity: str
    available: bool

    def execute_subplan(
        self,
        subplan: ShardSubplan,
        *,
        snapshot_evidence: SignedSnapshotEvidence | Mapping[str, Any] | None = None,
    ) -> ShardSubresult:
        """Execute a shard-local subplan; return a snapshot-receipted subresult."""
        ...


def push_subplan_via_quack(
    client: QuackShardClient,
    subplan: ShardSubplan,
    *,
    snapshot_evidence: SignedSnapshotEvidence | Mapping[str, Any] | None = None,
    member: SnapshotVectorMember | None = None,
) -> ShardSubresult:
    """Push one subplan through a typed Quack endpoint (never ATTACH catalog)."""

    assert_no_catalog_file_access(
        subplan.binding.quack_endpoint_identity,
        context="push_subplan_via_quack",
    )
    if subplan.binding.opens_catalog_file:
        raise CatalogFileAccessError(
            "refusing to push subplan that opens a catalog file",
            subplan_id=subplan.subplan_id,
        )
    if client.catalog_id != subplan.binding.catalog_id:
        raise FederationError(
            f"client catalog {client.catalog_id!r} does not match subplan "
            f"{subplan.binding.catalog_id!r}",
            code="ENDPOINT",
        )
    # Remote worker attach plan proves we only open Quack.
    if member is not None:
        remote = build_remote_worker_attach(member, vector_id=subplan.vector_id)
        if remote.opens_catalog_file:
            raise CatalogFileAccessError(
                "remote worker attach plan must not open catalog files"
            )
        if isinstance(snapshot_evidence, SignedSnapshotEvidence):
            verify_remote_snapshot_receipt(
                member, snapshot_evidence, expected_vector_id=subplan.vector_id
            )

    if not getattr(client, "available", True):
        return ShardSubresult(
            subplan_id=subplan.subplan_id,
            dataset_id=subplan.dataset_id,
            catalog_id=subplan.binding.catalog_id,
            status=ShardSubresultStatus.UNAVAILABLE,
            rows=(),
            subresult_digest="",
            snapshot_version=subplan.binding.snapshot_version,
            owner_generation=subplan.binding.owner_generation,
            schema_digest=subplan.binding.schema_digest,
            quack_endpoint_identity=subplan.binding.quack_endpoint_identity,
            pruning=subplan.pruning,
            failure=TypedFailure(
                kind=FailureKind.CATALOG_UNAVAILABLE,
                catalog_id=subplan.binding.catalog_id,
                dataset_id=subplan.dataset_id,
                message=f"catalog {subplan.binding.catalog_id!r} is unavailable",
            ),
        )

    result = client.execute_subplan(subplan, snapshot_evidence=snapshot_evidence)
    if result.opens_catalog_file:
        raise CatalogFileAccessError(
            "Quack client reported catalog file open; federating workers must not",
            catalog_id=result.catalog_id,
        )
    return result


# ---------------------------------------------------------------------------
# Plan compilation
# ---------------------------------------------------------------------------


def compile_federation_plan(
    datasets: Sequence[VersionedLogicalDataset],
    *,
    snapshot_vector: SnapshotVector,
    op: FederationOp = FederationOp.UNION_ALL,
    predicates: Sequence[Predicate] = (),
    fragments_by_dataset: Mapping[str, Sequence[FileFragment]] | None = None,
    tenant_policy: TenantPolicy | None = None,
    partial_failure_policy: PartialFailurePolicy = PartialFailurePolicy.PARTIAL,
    join_keys: Sequence[str] = (),
    max_rows: int = DEFAULT_MAX_ROWS,
    plan_id: str | None = None,
    column_policy: ColumnPolicy | None = None,
) -> FederationPlan:
    """Compile a bounded federation plan over independently versioned datasets.

    The plan binds each shard endpoint, owner generation, snapshot, schema, and
    (placeholder) subresult digest. No catalog metadata path is attached.
    """

    ds_list = list(datasets)
    if len(ds_list) < 2:
        raise FederationError(
            "federation requires at least two independently versioned datasets"
        )
    if len(ds_list) > MAX_DATASETS_PER_PLAN:
        raise FederationError(f"at most {MAX_DATASETS_PER_PLAN} datasets per plan")

    # Snapshot vector must cover every catalog.
    vector = snapshot_vector
    if not isinstance(vector, SnapshotVector):
        raise FederationError("snapshot_vector must be SnapshotVector")

    tenant = tenant_policy or TenantPolicy(tenant_id=ds_list[0].relation.tenant)

    # Authorize each dataset under tenant policy.
    for ds in ds_list:
        tenant.authorize_dataset(
            dataset_id=ds.dataset_id,
            tenant=ds.relation.tenant,
            catalog_id=ds.relation.catalog_id,
        )
        # Bind snapshot member.
        try:
            member = vector.member_for(ds.relation.catalog_id)
        except Exception as exc:
            raise FederationError(
                f"snapshot vector has no member for catalog "
                f"{ds.relation.catalog_id!r}",
                code="SNAPSHOT",
            ) from exc
        if member.owner_generation != ds.relation.owner_generation:
            raise FederationError(
                f"owner_generation mismatch for {ds.relation.catalog_id!r}: "
                f"dataset={ds.relation.owner_generation} "
                f"vector={member.owner_generation}",
                code="SNAPSHOT",
            )
        if member.catalog_global_snapshot_id != ds.relation.snapshot_version:
            raise FederationError(
                f"snapshot mismatch for {ds.relation.catalog_id!r}: "
                f"dataset={ds.relation.snapshot_version} "
                f"vector={member.catalog_global_snapshot_id}",
                code="SNAPSHOT",
            )
        if member.tenant_id != ds.relation.tenant and tenant.deny_cross_tenant:
            raise TenantPolicyError(
                f"snapshot member tenant {member.tenant_id!r} mismatches dataset "
                f"tenant {ds.relation.tenant!r}",
                catalog_id=ds.relation.catalog_id,
            )
        # Endpoint identity must match and never be a catalog file.
        assert_no_catalog_file_access(
            member.quack_endpoint_identity, context="snapshot vector member"
        )
        if member.quack_endpoint_identity != ds.relation.quack_endpoint_identity:
            raise FederationError(
                f"quack endpoint mismatch for {ds.relation.catalog_id!r}",
                code="ENDPOINT",
            )

    reconciliation = reconcile_schemas(
        ds_list, column_policy=column_policy
    )
    projected = tuple(f.field_id for f in reconciliation.unified_fields)
    preds = tuple(predicates or ())
    frag_map = dict(fragments_by_dataset or {})

    subplans: list[ShardSubplan] = []
    for ds in sorted(ds_list, key=lambda d: d.dataset_id):
        member = vector.member_for(ds.relation.catalog_id)
        frags = tuple(frag_map.get(ds.dataset_id, ()))
        selected, pruning = prune_fragments(frags, preds)
        binding = ShardEndpointBinding(
            catalog_id=ds.relation.catalog_id,
            shard_id=ds.relation.shard_id or member.shard_id or ds.relation.catalog_id,
            quack_endpoint_identity=ds.relation.quack_endpoint_identity,
            owner_generation=ds.relation.owner_generation,
            fencing_epoch=ds.relation.fencing_epoch,
            snapshot_version=ds.relation.snapshot_version,
            schema_digest=ds.relation.schema_contract.schema_digest,
            schema_revision=ds.relation.schema_contract.revision,
            dataset_id=ds.dataset_id,
            opens_catalog_file=False,
        )
        remaps = reconciliation.remappings[ds.dataset_id]
        subplans.append(
            ShardSubplan(
                subplan_id=f"sp-{ds.relation.catalog_id}-{_sha256_text(ds.dataset_id)[:12]}",
                dataset_id=ds.dataset_id,
                binding=binding,
                qualified_relation=ds.relation.qualified_name,
                projected_field_ids=projected,
                remappings=remaps,
                predicates=preds,
                selected_file_ids=tuple(f.file_id for f in selected),
                pruning=pruning,
                vector_id=vector.vector_id,
            )
        )

    return FederationPlan(
        plan_id=plan_id or f"fed-{uuid.uuid4().hex[:16]}",
        op=op,
        dataset_ids=tuple(ds.dataset_id for ds in sorted(ds_list, key=lambda d: d.dataset_id)),
        subplans=tuple(subplans),
        reconciliation=reconciliation,
        snapshot_vector_id=vector.vector_id,
        snapshot_vector_digest=vector.identity_digest,
        tenant_policy=tenant,
        partial_failure_policy=partial_failure_policy,
        join_keys=tuple(join_keys or ()),
        max_rows=max_rows,
    )


# ---------------------------------------------------------------------------
# Combine subresults
# ---------------------------------------------------------------------------


def _join_key_tuple(row: Mapping[str, Any], keys: Sequence[str]) -> tuple[Any, ...]:
    return tuple(row.get(k) for k in keys)


def combine_subresults(
    plan: FederationPlan,
    subresults: Sequence[ShardSubresult],
) -> FederatedQueryResult:
    """Combine snapshot-receipted subresults under the plan operator + policy."""

    by_subplan = {sr.subplan_id: sr for sr in subresults}
    ordered: list[ShardSubresult] = []
    failures: list[TypedFailure] = []
    for sp in plan.subplans:
        sr = by_subplan.get(sp.subplan_id)
        if sr is None:
            failure = TypedFailure(
                kind=FailureKind.INTERNAL,
                catalog_id=sp.binding.catalog_id,
                dataset_id=sp.dataset_id,
                message=f"missing subresult for subplan {sp.subplan_id!r}",
            )
            failures.append(failure)
            ordered.append(
                ShardSubresult(
                    subplan_id=sp.subplan_id,
                    dataset_id=sp.dataset_id,
                    catalog_id=sp.binding.catalog_id,
                    status=ShardSubresultStatus.FAILED,
                    rows=(),
                    subresult_digest="",
                    snapshot_version=sp.binding.snapshot_version,
                    owner_generation=sp.binding.owner_generation,
                    schema_digest=sp.binding.schema_digest,
                    quack_endpoint_identity=sp.binding.quack_endpoint_identity,
                    pruning=sp.pruning,
                    failure=failure,
                )
            )
            continue
        # Only combine snapshot-receipted successes.
        if sr.status is ShardSubresultStatus.SUCCEEDED:
            if not sr.subresult_digest:
                failure = TypedFailure(
                    kind=FailureKind.RECEIPT_REJECTED,
                    catalog_id=sr.catalog_id,
                    dataset_id=sr.dataset_id,
                    message="succeeded subresult missing subresult_digest",
                )
                failures.append(failure)
                ordered.append(
                    ShardSubresult(
                        subplan_id=sr.subplan_id,
                        dataset_id=sr.dataset_id,
                        catalog_id=sr.catalog_id,
                        status=ShardSubresultStatus.RECEIPT_REJECTED,
                        rows=(),
                        subresult_digest="",
                        snapshot_version=sr.snapshot_version,
                        owner_generation=sr.owner_generation,
                        schema_digest=sr.schema_digest,
                        quack_endpoint_identity=sr.quack_endpoint_identity,
                        pruning=sr.pruning,
                        failure=failure,
                    )
                )
                continue
            if sr.snapshot_version != sp.binding.snapshot_version:
                failure = TypedFailure(
                    kind=FailureKind.SNAPSHOT_MISMATCH,
                    catalog_id=sr.catalog_id,
                    dataset_id=sr.dataset_id,
                    message="subresult snapshot does not match plan binding",
                    details={
                        "expected": sp.binding.snapshot_version,
                        "actual": sr.snapshot_version,
                    },
                )
                failures.append(failure)
                ordered.append(
                    ShardSubresult(
                        subplan_id=sr.subplan_id,
                        dataset_id=sr.dataset_id,
                        catalog_id=sr.catalog_id,
                        status=ShardSubresultStatus.RECEIPT_REJECTED,
                        rows=(),
                        subresult_digest=sr.subresult_digest,
                        snapshot_version=sr.snapshot_version,
                        owner_generation=sr.owner_generation,
                        schema_digest=sr.schema_digest,
                        quack_endpoint_identity=sr.quack_endpoint_identity,
                        pruning=sr.pruning,
                        failure=failure,
                    )
                )
                continue
            ordered.append(sr)
        else:
            if sr.failure is not None:
                failures.append(sr.failure)
            else:
                failures.append(
                    TypedFailure(
                        kind=(
                            FailureKind.CATALOG_UNAVAILABLE
                            if sr.status is ShardSubresultStatus.UNAVAILABLE
                            else FailureKind.EXECUTION_ERROR
                        ),
                        catalog_id=sr.catalog_id,
                        dataset_id=sr.dataset_id,
                        message=f"subplan {sr.subplan_id} status={sr.status.value}",
                    )
                )
            ordered.append(sr)

    successes = [
        sr for sr in ordered if sr.status is ShardSubresultStatus.SUCCEEDED
    ]
    policy = plan.partial_failure_policy
    any_failure = bool(failures) or len(successes) < len(plan.subplans)

    if any_failure and not policy.allows_partial():
        status = FederationStatus.FAILED
        rows: tuple[Mapping[str, Any], ...] = ()
    elif any_failure and policy.allows_partial():
        if not successes:
            status = FederationStatus.FAILED
            rows = ()
        else:
            status = FederationStatus.PARTIAL
            rows = _apply_op(plan, successes)
    else:
        status = FederationStatus.COMPLETE
        rows = _apply_op(plan, successes)

    if len(rows) > plan.max_rows:
        raise FederationError(
            f"combined rows {len(rows)} exceed max_rows {plan.max_rows}",
            code="BUDGET",
        )

    pruning_ev = []
    for sr in ordered:
        if sr.pruning is not None:
            body = dict(sr.pruning.as_mapping())
            body["catalog_id"] = sr.catalog_id
            body["dataset_id"] = sr.dataset_id
            pruning_ev.append(body)

    return FederatedQueryResult(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest(),
        status=status,
        rows=rows,
        result_digest="",  # computed in __post_init__
        subresults=tuple(ordered),
        failures=tuple(failures),
        pruning_evidence=tuple(pruning_ev),
        snapshot_vector_id=plan.snapshot_vector_id,
        snapshot_vector_digest=plan.snapshot_vector_digest,
        partial_failure_policy=policy,
    )


def _apply_op(
    plan: FederationPlan,
    successes: Sequence[ShardSubresult],
) -> tuple[Mapping[str, Any], ...]:
    if not successes:
        return ()
    # Project rows through remappings (already projected by client ideally).
    projected_sets: list[list[dict[str, Any]]] = []
    for sr in successes:
        remaps = None
        for sp in plan.subplans:
            if sp.subplan_id == sr.subplan_id:
                remaps = sp.remappings
                break
        rows: list[dict[str, Any]] = []
        for raw in sr.rows:
            if remaps:
                # If already in target space, pass through missing-safe.
                if all(r.target_field_id in raw for r in remaps if not r.missing):
                    row = {r.target_field_id: raw.get(r.target_field_id, r.default_value) for r in remaps}
                else:
                    row = _project_row(raw, remaps)
            else:
                row = dict(raw)
            row["_dataset_id"] = sr.dataset_id
            row["_catalog_id"] = sr.catalog_id
            rows.append(row)
        # Deterministic row order within shard.
        rows.sort(key=lambda r: _canonical_json(r))
        projected_sets.append(rows)

    if plan.op is FederationOp.UNION_ALL:
        combined = [r for group in projected_sets for r in group]
        combined.sort(key=lambda r: (_canonical_json({k: v for k, v in r.items() if not k.startswith("_")}), r.get("_catalog_id", "")))
        return tuple(MappingProxyType(r) for r in combined)

    # Joins: left is first success by dataset_id order; right is the rest chained.
    if plan.op in {FederationOp.INNER_JOIN, FederationOp.LEFT_JOIN}:
        keys = plan.join_keys
        left_rows = projected_sets[0]
        right_groups = projected_sets[1:]
        current = left_rows
        for right_rows in right_groups:
            index: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for r in right_rows:
                index.setdefault(_join_key_tuple(r, keys), []).append(r)
            joined: list[dict[str, Any]] = []
            for left in current:
                lk = _join_key_tuple(left, keys)
                matches = index.get(lk, [])
                if matches:
                    for right in matches:
                        merged = dict(left)
                        for k, v in right.items():
                            if k.startswith("_"):
                                merged[k] = (
                                    f"{merged.get(k, '')}+{v}"
                                    if k in merged
                                    else v
                                )
                            elif k not in merged or merged[k] is None:
                                merged[k] = v
                        joined.append(merged)
                elif plan.op is FederationOp.LEFT_JOIN:
                    joined.append(dict(left))
            current = joined
        current.sort(key=lambda r: _canonical_json(r))
        return tuple(MappingProxyType(r) for r in current)

    raise FederationError(f"unsupported federation op {plan.op!r}")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class FederatedParquetQueryEngine:
    """Compile and execute federated Parquet queries across Quack shards.

    Workers never ATTACH remote catalog files; each subplan is pushed through
    the shard's typed Quack endpoint and only snapshot-receipted results are
    combined.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, VersionedLogicalDataset] = {}
        self._fragments: dict[str, list[FileFragment]] = {}
        self._clients: dict[str, QuackShardClient] = {}
        self._evidence: dict[str, SignedSnapshotEvidence | Mapping[str, Any]] = {}
        self._members: dict[str, SnapshotVectorMember] = {}
        self._lock = threading.RLock()

    def register_dataset(
        self,
        dataset: VersionedLogicalDataset,
        *,
        fragments: Sequence[FileFragment] | None = None,
    ) -> None:
        with self._lock:
            if not isinstance(dataset, VersionedLogicalDataset):
                raise FederationError("dataset must be VersionedLogicalDataset")
            assert_no_catalog_file_access(
                dataset.relation.quack_endpoint_identity,
                context="register_dataset",
            )
            self._datasets[dataset.dataset_id] = dataset
            if fragments is not None:
                self._fragments[dataset.dataset_id] = list(fragments)

    def register_fragments(
        self, dataset_id: str, fragments: Sequence[FileFragment]
    ) -> None:
        with self._lock:
            if dataset_id not in self._datasets:
                raise FederationError(f"unknown dataset_id {dataset_id!r}")
            self._fragments[dataset_id] = list(fragments)

    def register_quack_client(self, client: QuackShardClient) -> None:
        with self._lock:
            assert_no_catalog_file_access(
                client.quack_endpoint_identity, context="register_quack_client"
            )
            self._clients[client.catalog_id] = client

    def register_snapshot_evidence(
        self,
        catalog_id: str,
        evidence: SignedSnapshotEvidence | Mapping[str, Any],
        *,
        member: SnapshotVectorMember | None = None,
    ) -> None:
        with self._lock:
            self._evidence[catalog_id] = evidence
            if member is not None:
                self._members[catalog_id] = member

    def list_datasets(self) -> tuple[VersionedLogicalDataset, ...]:
        with self._lock:
            return tuple(
                self._datasets[k] for k in sorted(self._datasets)
            )

    def compile(
        self,
        dataset_ids: Sequence[str],
        *,
        snapshot_vector: SnapshotVector,
        op: FederationOp = FederationOp.UNION_ALL,
        predicates: Sequence[Predicate] = (),
        tenant_policy: TenantPolicy | None = None,
        partial_failure_policy: PartialFailurePolicy = PartialFailurePolicy.PARTIAL,
        join_keys: Sequence[str] = (),
        max_rows: int = DEFAULT_MAX_ROWS,
        plan_id: str | None = None,
    ) -> FederationPlan:
        with self._lock:
            datasets = []
            for did in dataset_ids:
                if did not in self._datasets:
                    raise FederationError(f"unknown dataset_id {did!r}")
                datasets.append(self._datasets[did])
            frags = {
                did: tuple(self._fragments.get(did, ()))
                for did in dataset_ids
            }
        return compile_federation_plan(
            datasets,
            snapshot_vector=snapshot_vector,
            op=op,
            predicates=predicates,
            fragments_by_dataset=frags,
            tenant_policy=tenant_policy,
            partial_failure_policy=partial_failure_policy,
            join_keys=join_keys,
            max_rows=max_rows,
            plan_id=plan_id,
        )

    def execute(
        self,
        plan: FederationPlan,
        *,
        snapshot_vector: SnapshotVector | None = None,
    ) -> FederatedQueryResult:
        """Push each subplan through its Quack endpoint; combine receipted results."""

        if not isinstance(plan, FederationPlan):
            raise FederationError("plan must be FederationPlan")
        # Hard guarantee: no subplan opens a catalog file.
        for sp in plan.subplans:
            assert_no_catalog_file_access(
                sp.binding.quack_endpoint_identity,
                context="execute federation plan",
            )
            if sp.binding.opens_catalog_file:
                raise CatalogFileAccessError(
                    "plan binding opens catalog file",
                    subplan_id=sp.subplan_id,
                )

        subresults: list[ShardSubresult] = []
        fail_fast = plan.partial_failure_policy is PartialFailurePolicy.FAIL_FAST

        for sp in plan.subplans:
            with self._lock:
                client = self._clients.get(sp.binding.catalog_id)
                evidence = self._evidence.get(sp.binding.catalog_id)
                member = self._members.get(sp.binding.catalog_id)
            if member is None and snapshot_vector is not None:
                try:
                    member = snapshot_vector.member_for(sp.binding.catalog_id)
                except Exception:
                    member = None

            if client is None:
                failure = TypedFailure(
                    kind=FailureKind.CATALOG_UNAVAILABLE,
                    catalog_id=sp.binding.catalog_id,
                    dataset_id=sp.dataset_id,
                    message=(
                        f"no Quack client registered for catalog "
                        f"{sp.binding.catalog_id!r}"
                    ),
                )
                subresults.append(
                    ShardSubresult(
                        subplan_id=sp.subplan_id,
                        dataset_id=sp.dataset_id,
                        catalog_id=sp.binding.catalog_id,
                        status=ShardSubresultStatus.UNAVAILABLE,
                        rows=(),
                        subresult_digest="",
                        snapshot_version=sp.binding.snapshot_version,
                        owner_generation=sp.binding.owner_generation,
                        schema_digest=sp.binding.schema_digest,
                        quack_endpoint_identity=sp.binding.quack_endpoint_identity,
                        pruning=sp.pruning,
                        failure=failure,
                    )
                )
                if fail_fast:
                    # Skip remaining as SKIPPED.
                    for rest in plan.subplans[len(subresults) :]:
                        subresults.append(
                            ShardSubresult(
                                subplan_id=rest.subplan_id,
                                dataset_id=rest.dataset_id,
                                catalog_id=rest.binding.catalog_id,
                                status=ShardSubresultStatus.SKIPPED,
                                rows=(),
                                subresult_digest="",
                                snapshot_version=rest.binding.snapshot_version,
                                owner_generation=rest.binding.owner_generation,
                                schema_digest=rest.binding.schema_digest,
                                quack_endpoint_identity=rest.binding.quack_endpoint_identity,
                                pruning=rest.pruning,
                                failure=TypedFailure(
                                    kind=FailureKind.CATALOG_UNAVAILABLE,
                                    catalog_id=rest.binding.catalog_id,
                                    dataset_id=rest.dataset_id,
                                    message="skipped after fail_fast",
                                ),
                            )
                        )
                    break
                continue

            try:
                sr = push_subplan_via_quack(
                    client,
                    sp,
                    snapshot_evidence=evidence,
                    member=member,
                )
            except CatalogFileAccessError:
                raise
            except Exception as exc:  # noqa: BLE001 — typed into subresult
                sr = ShardSubresult(
                    subplan_id=sp.subplan_id,
                    dataset_id=sp.dataset_id,
                    catalog_id=sp.binding.catalog_id,
                    status=ShardSubresultStatus.FAILED,
                    rows=(),
                    subresult_digest="",
                    snapshot_version=sp.binding.snapshot_version,
                    owner_generation=sp.binding.owner_generation,
                    schema_digest=sp.binding.schema_digest,
                    quack_endpoint_identity=sp.binding.quack_endpoint_identity,
                    pruning=sp.pruning,
                    failure=TypedFailure(
                        kind=FailureKind.EXECUTION_ERROR,
                        catalog_id=sp.binding.catalog_id,
                        dataset_id=sp.dataset_id,
                        message=str(exc),
                    ),
                )
            subresults.append(sr)
            if (
                fail_fast
                and sr.status is not ShardSubresultStatus.SUCCEEDED
            ):
                for rest in plan.subplans[len(subresults) :]:
                    subresults.append(
                        ShardSubresult(
                            subplan_id=rest.subplan_id,
                            dataset_id=rest.dataset_id,
                            catalog_id=rest.binding.catalog_id,
                            status=ShardSubresultStatus.SKIPPED,
                            rows=(),
                            subresult_digest="",
                            snapshot_version=rest.binding.snapshot_version,
                            owner_generation=rest.binding.owner_generation,
                            schema_digest=rest.binding.schema_digest,
                            quack_endpoint_identity=rest.binding.quack_endpoint_identity,
                            pruning=rest.pruning,
                            failure=TypedFailure(
                                kind=FailureKind.CATALOG_UNAVAILABLE,
                                catalog_id=rest.binding.catalog_id,
                                dataset_id=rest.dataset_id,
                                message="skipped after fail_fast",
                            ),
                        )
                    )
                break

        return combine_subresults(plan, subresults)

    def query(
        self,
        dataset_ids: Sequence[str],
        *,
        snapshot_vector: SnapshotVector,
        op: FederationOp = FederationOp.UNION_ALL,
        predicates: Sequence[Predicate] = (),
        tenant_policy: TenantPolicy | None = None,
        partial_failure_policy: PartialFailurePolicy = PartialFailurePolicy.PARTIAL,
        join_keys: Sequence[str] = (),
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> FederatedQueryResult:
        plan = self.compile(
            dataset_ids,
            snapshot_vector=snapshot_vector,
            op=op,
            predicates=predicates,
            tenant_policy=tenant_policy,
            partial_failure_policy=partial_failure_policy,
            join_keys=join_keys,
            max_rows=max_rows,
        )
        return self.execute(plan, snapshot_vector=snapshot_vector)


def open_default_federation_engine() -> FederatedParquetQueryEngine:
    """Return a fresh federation engine (side-effect free factory)."""

    return FederatedParquetQueryEngine()


# ---------------------------------------------------------------------------
# Hermetic in-memory Quack client (test + local doubles)
# ---------------------------------------------------------------------------


@dataclass
class InMemoryQuackShardClient:
    """Hermetic Quack endpoint double that never opens catalog files."""

    catalog_id: str
    quack_endpoint_identity: str
    rows_by_dataset: dict[str, list[Mapping[str, Any]]] = field(default_factory=dict)
    available: bool = True
    owner_generation: int = 1
    snapshot_version: int = 0
    schema_digest: str = ""
    opened_catalog_file: bool = False  # always remains False

    def __post_init__(self) -> None:
        assert_no_catalog_file_access(
            self.quack_endpoint_identity, context="InMemoryQuackShardClient"
        )
        self.opened_catalog_file = False

    def execute_subplan(
        self,
        subplan: ShardSubplan,
        *,
        snapshot_evidence: SignedSnapshotEvidence | Mapping[str, Any] | None = None,
    ) -> ShardSubresult:
        if self.opened_catalog_file:
            raise CatalogFileAccessError(
                "InMemoryQuackShardClient must never open catalog files"
            )
        assert_no_catalog_file_access(
            subplan.binding.quack_endpoint_identity,
            context="InMemoryQuackShardClient.execute_subplan",
        )
        if not self.available:
            raise CatalogUnavailableError(
                f"catalog {self.catalog_id!r} unavailable",
                catalog_id=self.catalog_id,
            )
        if (
            self.snapshot_version
            and self.snapshot_version != subplan.binding.snapshot_version
        ):
            return ShardSubresult(
                subplan_id=subplan.subplan_id,
                dataset_id=subplan.dataset_id,
                catalog_id=self.catalog_id,
                status=ShardSubresultStatus.RECEIPT_REJECTED,
                rows=(),
                subresult_digest="",
                snapshot_version=self.snapshot_version,
                owner_generation=self.owner_generation,
                schema_digest=self.schema_digest or subplan.binding.schema_digest,
                quack_endpoint_identity=self.quack_endpoint_identity,
                pruning=subplan.pruning,
                failure=TypedFailure(
                    kind=FailureKind.SNAPSHOT_MISMATCH,
                    catalog_id=self.catalog_id,
                    dataset_id=subplan.dataset_id,
                    message="endpoint snapshot does not match plan binding",
                ),
            )

        raw_rows = list(self.rows_by_dataset.get(subplan.dataset_id, []))
        # Optional local predicate filter for hermetic realism.
        filtered: list[dict[str, Any]] = []
        for row in raw_rows:
            if subplan.predicates and not _row_matches_predicates(row, subplan.predicates):
                continue
            projected = _project_row(row, subplan.remappings)
            filtered.append(projected)

        evidence_map: Mapping[str, Any] | None
        if isinstance(snapshot_evidence, SignedSnapshotEvidence):
            evidence_map = snapshot_evidence.as_mapping()
        elif snapshot_evidence is not None:
            evidence_map = dict(snapshot_evidence)
        else:
            evidence_map = {
                "catalog_id": self.catalog_id,
                "snapshot_version": subplan.binding.snapshot_version,
                "owner_generation": subplan.binding.owner_generation,
                "receipted": True,
            }

        digest = _digest_of(
            {
                "subplan_id": subplan.subplan_id,
                "rows": filtered,
                "snapshot_version": subplan.binding.snapshot_version,
                "schema_digest": subplan.binding.schema_digest,
            }
        )
        return ShardSubresult(
            subplan_id=subplan.subplan_id,
            dataset_id=subplan.dataset_id,
            catalog_id=self.catalog_id,
            status=ShardSubresultStatus.SUCCEEDED,
            rows=tuple(filtered),
            subresult_digest=digest,
            snapshot_version=subplan.binding.snapshot_version,
            owner_generation=subplan.binding.owner_generation,
            schema_digest=subplan.binding.schema_digest,
            quack_endpoint_identity=self.quack_endpoint_identity,
            pruning=subplan.pruning,
            snapshot_evidence=evidence_map,
            opens_catalog_file=False,
        )


def _row_matches_predicates(
    row: Mapping[str, Any], predicates: Sequence[Predicate]
) -> bool:
    for pred in predicates:
        if pred.field_id not in row and not any(
            # allow name-keyed rows in hermetic fixtures
            True for _ in ()
        ):
            # If the field is absent, do not filter out (pushdown incomplete).
            if pred.field_id not in row:
                continue
        actual = row.get(pred.field_id)
        if actual is None and pred.field_id not in row:
            continue
        try:
            if pred.op == "eq" and actual != pred.value:
                return False
            if pred.op == "ne" and actual == pred.value:
                return False
            if pred.op == "lt" and not (actual < pred.value):
                return False
            if pred.op == "le" and not (actual <= pred.value):
                return False
            if pred.op == "gt" and not (actual > pred.value):
                return False
            if pred.op == "ge" and not (actual >= pred.value):
                return False
            if pred.op == "in" and actual not in pred.values:
                return False
        except TypeError:
            continue
    return True


# Re-export hermetic client for tests.
__all__ = list(__all__) + ["InMemoryQuackShardClient", "FailureKind"]
