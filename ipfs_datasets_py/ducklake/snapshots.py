"""Immutable multi-shard snapshot vectors and authoritative reader leases (DQK-090).

Capture and validate an ordered vector with exactly one member per DuckDB +
Quack DuckLake catalog shard. Each member binds catalog identity, catalog-owner
generation, Quack endpoint identity, catalog-global snapshot ID, schema version,
storage root, included logical datasets, source revisions, and policy decision.

Authoritative reader-lease acquire / renew / release operations are database-
backed (never file-only). Leases bind the vector, worker process-birth
identity, task/run identity, lease token, deadline, and generation fence.
PID reuse, a stale fence, or a foreign token fails closed.

Only the fenced catalog owner ATTACHes its DuckDB metadata file and proves
``SNAPSHOT_VERSION`` equals the receipted catalog-global snapshot under safe
non-bootstrap / non-migration options
(``CREATE_IF_NOT_EXISTS=false``, ``OVERRIDE_DATA_PATH=false``,
``AUTOMATIC_MIGRATION=false``). Remote workers open only the authenticated
Quack endpoint.

Import is side-effect free: no DuckDB connection, no filesystem authority, no
network. Unit tests use hermetic in-memory database stores.
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
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.ducklake.capabilities import ATTACH_SAFE_OPTIONS
from ipfs_datasets_py.ducklake.catalog import (
    AttachStatement,
    CatalogError,
    build_ducklake_attach_statement,
    require_safe_attach_options,
)
from ipfs_datasets_py.ducklake.config import (
    AttachMode,
    CatalogShardProfile,
    ProcessBirthBinding,
)

__all__ = [
    "OWNER_SNAPSHOT_ATTACH_SCHEMA",
    "READER_LEASE_SCHEMA",
    "REMOTE_WORKER_ATTACH_SCHEMA",
    "SIGNED_SNAPSHOT_EVIDENCE_SCHEMA",
    "SNAPSHOT_VECTOR_MEMBER_SCHEMA",
    "SNAPSHOT_VECTOR_SCHEMA",
    "TIME_TRAVEL_REPLAY_SCHEMA",
    "AuthoritativeSnapshotDatabase",
    "LeaseStatus",
    "OwnerSnapshotAttachPlan",
    "ReaderLease",
    "ReaderLeaseError",
    "RemoteWorkerAttachPlan",
    "SignedSnapshotEvidence",
    "SnapshotAttachError",
    "SnapshotError",
    "SnapshotRetentionError",
    "SnapshotVector",
    "SnapshotVectorError",
    "SnapshotVectorMember",
    "TimeTravelReplayResult",
    "assert_database_backed_authority",
    "build_owner_snapshot_attach",
    "build_remote_worker_attach",
    "capture_snapshot_vector",
    "canonical_member_order",
    "prove_owner_snapshot_version",
    "replay_time_travel",
    "validate_snapshot_vector",
    "vector_identity_digest",
    "verify_remote_snapshot_receipt",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

SNAPSHOT_VECTOR_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-snapshot-vector@1"
SNAPSHOT_VECTOR_MEMBER_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-snapshot-vector-member@1"
)
READER_LEASE_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-reader-lease@1"
SIGNED_SNAPSHOT_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-signed-snapshot-evidence@1"
)
OWNER_SNAPSHOT_ATTACH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-owner-snapshot-attach@1"
)
REMOTE_WORKER_ATTACH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-remote-worker-attach@1"
)
TIME_TRAVEL_REPLAY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-time-travel-replay@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-090-snapshot-vectors-reader-leases-20260810"
)

# Tables held only in the authoritative in-memory / DuckDB registry store —
# never as standalone files.
_VECTOR_TABLE: Final[str] = "lake_snapshot_vectors"
_LEASE_TABLE: Final[str] = "lake_reader_leases"

_DEFAULT_LEASE_TTL_SECONDS: Final[int] = 300
_MAX_LEASE_TTL_SECONDS: Final[int] = 86_400
_MIN_LEASE_TTL_SECONDS: Final[int] = 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SnapshotError(ValueError):
    """Fail-closed snapshot-vector or reader-lease rejection."""


class SnapshotVectorError(SnapshotError):
    """Snapshot vector construction or validation failed."""


class ReaderLeaseError(SnapshotError):
    """Reader-lease acquire, renew, or release failed closed."""


class SnapshotRetentionError(SnapshotError):
    """Time-travel target is outside the catalog-global retention window."""


class SnapshotAttachError(SnapshotError):
    """Owner or remote ATTACH plan failed closed."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LeaseStatus(str, Enum):
    """Lifecycle of an authoritative reader lease."""

    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(ts: float | None = None) -> str:
    clock = time.time() if ts is None else float(ts)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock))


def _parse_utc_iso(value: str) -> float:
    """Parse a UTC ISO-8601 timestamp (``...Z`` or offset-aware) to epoch seconds."""

    text = str(value or "").strip()
    if not text:
        raise SnapshotError("timestamp is required")
    try:
        from datetime import datetime

        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise SnapshotError(f"invalid timestamp {value!r}") from exc


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_of(payload: Any) -> str:
    return "sha256:" + _sha256_text(_canonical_json(payload))


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SnapshotError(f"{field_name} is required")
    return text


def _require_nonneg_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SnapshotError(f"{field_name} must be a non-negative int")
    return value


def _require_pos_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SnapshotError(f"{field_name} must be a positive int")
    return value


def _coerce_process_birth(value: Any) -> ProcessBirthBinding:
    if isinstance(value, ProcessBirthBinding):
        return value
    if isinstance(value, Mapping):
        return ProcessBirthBinding(
            pid=int(value["pid"]),
            boot_id=str(value["boot_id"]),
            start_ticks=int(value["start_ticks"]),
            cmdline_sha256=str(value["cmdline_sha256"]),
        )
    raise SnapshotError("process_birth must be ProcessBirthBinding or mapping")


def _process_birth_equal(a: ProcessBirthBinding, b: ProcessBirthBinding) -> bool:
    return (
        a.pid == b.pid
        and a.boot_id == b.boot_id
        and a.start_ticks == b.start_ticks
        and a.cmdline_sha256 == b.cmdline_sha256
    )


def _stable_str_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    items = sorted({str(v).strip() for v in values if str(v).strip()})
    return tuple(items)


def _stable_str_mapping(values: Mapping[str, Any] | None) -> Mapping[str, str]:
    if not values:
        return MappingProxyType({})
    out: dict[str, str] = {}
    for key, val in values.items():
        k = str(key).strip()
        if not k:
            raise SnapshotError("source_revisions keys must be non-empty")
        out[k] = str(val).strip()
    return MappingProxyType(dict(sorted(out.items())))


# ---------------------------------------------------------------------------
# Snapshot vector member + vector
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SnapshotVectorMember:
    """One immutable member of a multi-shard snapshot vector.

    Exactly one member is allowed per DuckDB + Quack catalog shard. Members
    bind the Quack endpoint, catalog-owner generation, DuckDB catalog identity,
    and catalog-global snapshot id together with schema, storage, datasets,
    source revisions, and policy decision.
    """

    catalog_id: str
    owner_generation: int
    fencing_epoch: int
    quack_endpoint_identity: str
    catalog_global_snapshot_id: int
    schema_version: str
    storage_root: str
    logical_datasets: tuple[str, ...] = ()
    source_revisions: Mapping[str, str] = field(default_factory=dict)
    policy_decision_id: str = ""
    policy_decision: Mapping[str, Any] = field(default_factory=dict)
    tenant_id: str = "default"
    catalog_digest: str = ""
    shard_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self,
            "owner_generation",
            _require_pos_int(self.owner_generation, field_name="owner_generation"),
        )
        object.__setattr__(
            self,
            "fencing_epoch",
            _require_pos_int(self.fencing_epoch, field_name="fencing_epoch"),
        )
        object.__setattr__(
            self,
            "quack_endpoint_identity",
            _require_nonempty(
                self.quack_endpoint_identity, field_name="quack_endpoint_identity"
            ),
        )
        object.__setattr__(
            self,
            "catalog_global_snapshot_id",
            _require_nonneg_int(
                self.catalog_global_snapshot_id,
                field_name="catalog_global_snapshot_id",
            ),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_nonempty(self.schema_version, field_name="schema_version"),
        )
        object.__setattr__(
            self,
            "storage_root",
            _require_nonempty(self.storage_root, field_name="storage_root"),
        )
        datasets = _stable_str_tuple(self.logical_datasets)
        object.__setattr__(self, "logical_datasets", datasets)
        object.__setattr__(
            self, "source_revisions", _stable_str_mapping(self.source_revisions)
        )
        policy_id = str(self.policy_decision_id or "").strip()
        policy_body = dict(self.policy_decision or {})
        if policy_body and not policy_id:
            policy_id = str(policy_body.get("decision_id") or "").strip()
        if not policy_id:
            raise SnapshotVectorError(
                "every snapshot vector member requires a policy_decision_id"
            )
        object.__setattr__(self, "policy_decision_id", policy_id)
        object.__setattr__(self, "policy_decision", MappingProxyType(policy_body))
        tenant = str(self.tenant_id or "default").strip() or "default"
        object.__setattr__(self, "tenant_id", tenant)
        digest = str(self.catalog_digest or "").strip()
        if digest and not digest.startswith("sha256:"):
            if len(digest) == 64 and all(c in "0123456789abcdefABCDEF" for c in digest):
                digest = f"sha256:{digest.lower()}"
            else:
                raise SnapshotVectorError("catalog_digest must be sha256:<64-hex>")
        object.__setattr__(self, "catalog_digest", digest)
        object.__setattr__(self, "shard_id", str(self.shard_id or "").strip())

    @property
    def snapshot_version(self) -> int:
        """Alias for catalog-global snapshot id (DuckLake SNAPSHOT_VERSION)."""

        return self.catalog_global_snapshot_id

    def member_digest(self) -> str:
        return _digest_of(self.as_mapping())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": SNAPSHOT_VECTOR_MEMBER_SCHEMA,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "quack_endpoint_identity": self.quack_endpoint_identity,
                "catalog_global_snapshot_id": self.catalog_global_snapshot_id,
                "snapshot_version": self.catalog_global_snapshot_id,
                "schema_version": self.schema_version,
                "storage_root": self.storage_root,
                "logical_datasets": list(self.logical_datasets),
                "source_revisions": dict(self.source_revisions),
                "policy_decision_id": self.policy_decision_id,
                "policy_decision": dict(self.policy_decision),
                "tenant_id": self.tenant_id,
                "catalog_digest": self.catalog_digest,
            }
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SnapshotVectorMember":
        data = dict(value)
        snap = data.get("catalog_global_snapshot_id", data.get("snapshot_version"))
        return cls(
            catalog_id=str(data.get("catalog_id") or ""),
            owner_generation=int(data["owner_generation"]),
            fencing_epoch=int(data["fencing_epoch"]),
            quack_endpoint_identity=str(data.get("quack_endpoint_identity") or ""),
            catalog_global_snapshot_id=int(snap),
            schema_version=str(data.get("schema_version") or ""),
            storage_root=str(data.get("storage_root") or ""),
            logical_datasets=tuple(data.get("logical_datasets") or ()),
            source_revisions=dict(data.get("source_revisions") or {}),
            policy_decision_id=str(data.get("policy_decision_id") or ""),
            policy_decision=dict(data.get("policy_decision") or {}),
            tenant_id=str(data.get("tenant_id") or "default"),
            catalog_digest=str(data.get("catalog_digest") or ""),
            shard_id=str(data.get("shard_id") or ""),
        )


def canonical_member_order(
    members: Sequence[SnapshotVectorMember],
) -> tuple[SnapshotVectorMember, ...]:
    """Return members sorted by catalog_id (stable, deterministic order)."""

    return tuple(sorted(members, key=lambda m: m.catalog_id))


def vector_identity_digest(members: Sequence[SnapshotVectorMember]) -> str:
    """Order-independent content digest over the full member set.

    Members are sorted by ``catalog_id`` before hashing so presentation order
    never changes the vector identity.
    """

    ordered = canonical_member_order(tuple(members))
    body = [dict(m.as_mapping()) for m in ordered]
    return _digest_of(
        {
            "schema": SNAPSHOT_VECTOR_SCHEMA,
            "members": body,
            "member_count": len(body),
        }
    )


def validate_snapshot_vector(
    members: Sequence[SnapshotVectorMember],
    *,
    expected_schema_version: str | None = None,
    expected_tenant_id: str | None = None,
) -> tuple[SnapshotVectorMember, ...]:
    """Validate membership invariants; fail closed on any violation.

    Rejects empty vectors, duplicate catalog ids, mixed tenants, stale/expired
    markers (negative generations already rejected at construction), and
    schema-incompatible members when an expected schema is supplied.
    """

    if not members:
        raise SnapshotVectorError("snapshot vector requires at least one member")
    seen_catalogs: set[str] = set()
    tenants: set[str] = set()
    schemas: set[str] = set()
    endpoints: set[str] = set()
    validated: list[SnapshotVectorMember] = []
    for raw in members:
        if not isinstance(raw, SnapshotVectorMember):
            raise SnapshotVectorError(
                "every member must be a SnapshotVectorMember instance"
            )
        if raw.catalog_id in seen_catalogs:
            raise SnapshotVectorError(
                f"duplicate catalog member {raw.catalog_id!r}; exactly one member "
                "per DuckDB + Quack catalog shard is required"
            )
        seen_catalogs.add(raw.catalog_id)
        tenants.add(raw.tenant_id)
        schemas.add(raw.schema_version)
        # Endpoint may be reused only for the same catalog; different catalogs
        # must not share an endpoint identity (mixed-shard endpoint collision).
        if raw.quack_endpoint_identity in endpoints:
            raise SnapshotVectorError(
                f"duplicate Quack endpoint identity "
                f"{raw.quack_endpoint_identity!r} across catalog shards"
            )
        endpoints.add(raw.quack_endpoint_identity)
        if expected_tenant_id is not None and raw.tenant_id != expected_tenant_id:
            raise SnapshotVectorError(
                f"mixed-tenant member {raw.catalog_id!r}: tenant "
                f"{raw.tenant_id!r} != expected {expected_tenant_id!r}"
            )
        if (
            expected_schema_version is not None
            and raw.schema_version != expected_schema_version
        ):
            raise SnapshotVectorError(
                f"schema-incompatible member {raw.catalog_id!r}: "
                f"schema_version {raw.schema_version!r} != "
                f"expected {expected_schema_version!r}"
            )
        validated.append(raw)
    if len(tenants) > 1:
        raise SnapshotVectorError(
            f"mixed-tenant snapshot vector is forbidden; tenants={sorted(tenants)}"
        )
    if expected_schema_version is None and len(schemas) > 1:
        # Cross-shard schema drift fails closed unless callers explicitly
        # capture heterogeneous schemas under a federation policy later.
        raise SnapshotVectorError(
            f"schema-incompatible members in vector; schema_versions={sorted(schemas)}"
        )
    return canonical_member_order(validated)


@dataclass(frozen=True, slots=True)
class SnapshotVector:
    """Immutable ordered multi-shard snapshot vector.

    Identity is deterministic and order-independent (canonical sort by
    catalog_id). Presentation order is always the canonical order.
    """

    members: tuple[SnapshotVectorMember, ...]
    vector_id: str = ""
    captured_at: str = ""
    representation: str = "database"

    def __post_init__(self) -> None:
        ordered = validate_snapshot_vector(self.members)
        object.__setattr__(self, "members", ordered)
        vid = str(self.vector_id or "").strip() or vector_identity_digest(ordered)
        object.__setattr__(self, "vector_id", vid)
        captured = str(self.captured_at or "").strip() or _utc_iso()
        object.__setattr__(self, "captured_at", captured)
        rep = str(self.representation or "database").strip().lower()
        if rep in {"file", "filesystem", "path", "json_file", "parquet_file"}:
            raise SnapshotVectorError(
                "snapshot vectors must not be represented only by a file; "
                "authority lives in the control/companion database"
            )
        object.__setattr__(self, "representation", rep)

    @property
    def identity_digest(self) -> str:
        return vector_identity_digest(self.members)

    @property
    def member_count(self) -> int:
        return len(self.members)

    def member_for(self, catalog_id: str) -> SnapshotVectorMember:
        for member in self.members:
            if member.catalog_id == catalog_id:
                return member
        raise SnapshotVectorError(f"catalog {catalog_id!r} is not in this vector")

    def catalog_ids(self) -> tuple[str, ...]:
        return tuple(m.catalog_id for m in self.members)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": SNAPSHOT_VECTOR_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "vector_id": self.vector_id,
                "identity_digest": self.identity_digest,
                "member_count": self.member_count,
                "members": [dict(m.as_mapping()) for m in self.members],
                "captured_at": self.captured_at,
                "representation": self.representation,
                "order_independent_identity": True,
                "one_member_per_catalog_shard": True,
                "cross_shard_atomicity": False,
            }
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SnapshotVector":
        members = tuple(
            SnapshotVectorMember.from_mapping(m)
            for m in (value.get("members") or ())
        )
        return cls(
            members=members,
            vector_id=str(value.get("vector_id") or ""),
            captured_at=str(value.get("captured_at") or ""),
            representation=str(value.get("representation") or "database"),
        )


def capture_snapshot_vector(
    members: Sequence[SnapshotVectorMember | Mapping[str, Any]],
    *,
    vector_id: str | None = None,
    expected_schema_version: str | None = None,
    expected_tenant_id: str | None = None,
) -> SnapshotVector:
    """Capture and validate an immutable snapshot vector from members.

    Input order does not affect identity. Exactly one member per catalog
    shard is enforced. Independent shards are never implied to be atomic.
    """

    built: list[SnapshotVectorMember] = []
    for item in members:
        if isinstance(item, SnapshotVectorMember):
            built.append(item)
        elif isinstance(item, Mapping):
            built.append(SnapshotVectorMember.from_mapping(item))
        else:
            raise SnapshotVectorError(
                "members must be SnapshotVectorMember or mapping values"
            )
    ordered = validate_snapshot_vector(
        built,
        expected_schema_version=expected_schema_version,
        expected_tenant_id=expected_tenant_id,
    )
    return SnapshotVector(
        members=ordered,
        vector_id=str(vector_id or "") or vector_identity_digest(ordered),
    )


# ---------------------------------------------------------------------------
# Owner / remote ATTACH plans and signed evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnerSnapshotAttachPlan:
    """Owner-only ATTACH plan proving SNAPSHOT_VERSION equals the receipt.

    Remote workers must never receive a catalog file path. Non-bootstrap /
    non-migration ATTACH always forces the three safe flags to false.
    """

    catalog_id: str
    catalog_path: str
    data_path: str
    snapshot_version: int
    owner_generation: int
    fencing_epoch: int
    attach: AttachStatement
    mode: str = AttachMode.SAFE.value

    def __post_init__(self) -> None:
        if not isinstance(self.attach, AttachStatement):
            raise SnapshotAttachError("attach must be AttachStatement")
        require_safe_attach_options(self.attach.options)
        opts = self.attach.ducklake_options()
        for key, expected in ATTACH_SAFE_OPTIONS.items():
            if bool(opts.get(key)) is not bool(expected):
                raise SnapshotAttachError(
                    f"owner non-bootstrap ATTACH requires {key}={expected!r}"
                )
        if self.attach.snapshot_version != self.snapshot_version:
            raise SnapshotAttachError(
                "ATTACH SNAPSHOT_VERSION must equal receipted catalog-global snapshot"
            )
        object.__setattr__(
            self,
            "fencing_epoch",
            _require_pos_int(self.fencing_epoch, field_name="fencing_epoch"),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": OWNER_SNAPSHOT_ATTACH_SCHEMA,
                "catalog_id": self.catalog_id,
                "catalog_path": self.catalog_path,
                "data_path": self.data_path,
                "snapshot_version": self.snapshot_version,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "mode": self.mode,
                "attach": dict(self.attach.as_mapping()),
                "safe_options": dict(ATTACH_SAFE_OPTIONS),
                "owner_opens_catalog_file": True,
                "remote_opens_catalog_file": False,
            }
        )


@dataclass(frozen=True, slots=True)
class RemoteWorkerAttachPlan:
    """Remote worker attaches only the authenticated Quack endpoint."""

    catalog_id: str
    quack_endpoint_identity: str
    owner_generation: int
    fencing_epoch: int
    snapshot_version: int
    vector_id: str
    opens_catalog_file: bool = False

    def __post_init__(self) -> None:
        if self.opens_catalog_file:
            raise SnapshotAttachError(
                "remote workers must not open the catalog file; attach only the "
                "authenticated Quack endpoint"
            )
        object.__setattr__(
            self,
            "quack_endpoint_identity",
            _require_nonempty(
                self.quack_endpoint_identity, field_name="quack_endpoint_identity"
            ),
        )
        endpoint = self.quack_endpoint_identity.lower()
        # Reject file-path-like "endpoints".
        if endpoint.startswith(("/", "file:", "ducklake:")) or endpoint.endswith(
            (".duckdb", ".db")
        ):
            raise SnapshotAttachError(
                "remote worker attach target must be an authenticated Quack "
                f"endpoint, not a catalog file path ({self.quack_endpoint_identity!r})"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": REMOTE_WORKER_ATTACH_SCHEMA,
                "catalog_id": self.catalog_id,
                "quack_endpoint_identity": self.quack_endpoint_identity,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "snapshot_version": self.snapshot_version,
                "vector_id": self.vector_id,
                "opens_catalog_file": False,
                "attach_target": "authenticated_quack_endpoint",
            }
        )


@dataclass(frozen=True, slots=True)
class SignedSnapshotEvidence:
    """Signed snapshot evidence returned through the typed Quack operation."""

    evidence_id: str
    catalog_id: str
    snapshot_version: int
    owner_generation: int
    fencing_epoch: int
    vector_id: str
    attach_snapshot_version: int
    signature: str
    signer_identity: str
    body_digest: str
    issued_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _require_nonempty(self.evidence_id, field_name="evidence_id"),
        )
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
        if self.attach_snapshot_version != self.snapshot_version:
            raise SnapshotAttachError(
                "signed evidence attach SNAPSHOT_VERSION must equal receipted "
                "catalog-global snapshot"
            )
        issued = str(self.issued_at or "").strip() or _utc_iso()
        object.__setattr__(self, "issued_at", issued)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": SIGNED_SNAPSHOT_EVIDENCE_SCHEMA,
                "evidence_id": self.evidence_id,
                "catalog_id": self.catalog_id,
                "snapshot_version": self.snapshot_version,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "vector_id": self.vector_id,
                "attach_snapshot_version": self.attach_snapshot_version,
                "signature": self.signature,
                "signer_identity": self.signer_identity,
                "body_digest": self.body_digest,
                "issued_at": self.issued_at,
            }
        )


def build_owner_snapshot_attach(
    profile: CatalogShardProfile,
    member: SnapshotVectorMember,
    *,
    alias: str | None = None,
) -> OwnerSnapshotAttachPlan:
    """Build the fenced owner's safe ATTACH plan for a vector member.

    Only the catalog owner may call this with a catalog file path. Remote
    workers must use :func:`build_remote_worker_attach` instead.
    """

    if profile.catalog_id != member.catalog_id:
        raise SnapshotAttachError(
            f"profile catalog_id {profile.catalog_id!r} does not match member "
            f"{member.catalog_id!r}"
        )
    if profile.owner_lease.owner_generation != member.owner_generation:
        raise SnapshotAttachError(
            "owner-generation mismatch between profile and vector member"
        )
    if profile.owner_lease.fencing_epoch != member.fencing_epoch:
        raise SnapshotAttachError(
            "fencing_epoch mismatch between profile and vector member"
        )
    statement = build_ducklake_attach_statement(
        profile,
        alias=alias,
        mode=AttachMode.SAFE,
        snapshot_version=member.catalog_global_snapshot_id,
    )
    require_safe_attach_options(statement.options)
    return OwnerSnapshotAttachPlan(
        catalog_id=member.catalog_id,
        catalog_path=profile.catalog_metadata.path,
        data_path=profile.parquet_namespace.data_path,
        snapshot_version=member.catalog_global_snapshot_id,
        owner_generation=member.owner_generation,
        fencing_epoch=member.fencing_epoch,
        attach=statement,
    )


def prove_owner_snapshot_version(
    plan: OwnerSnapshotAttachPlan,
    *,
    observed_snapshot_version: int,
    signer_identity: str,
    vector_id: str,
    sign: Callable[[str], str] | None = None,
) -> SignedSnapshotEvidence:
    """Prove ATTACH SNAPSHOT_VERSION equals the receipted catalog-global snapshot.

    Returns signed evidence for the typed Quack snapshot operation.
    """

    if observed_snapshot_version != plan.snapshot_version:
        raise SnapshotAttachError(
            f"DuckLake ATTACH SNAPSHOT_VERSION {observed_snapshot_version} does not "
            f"equal receipted catalog-global snapshot {plan.snapshot_version}"
        )
    body = {
        "catalog_id": plan.catalog_id,
        "snapshot_version": plan.snapshot_version,
        "owner_generation": plan.owner_generation,
        "fencing_epoch": plan.fencing_epoch,
        "vector_id": vector_id,
        "attach_snapshot_version": observed_snapshot_version,
    }
    body_digest = _digest_of(body)
    if sign is None:
        # Deterministic HMAC-style stand-in: hash of body + signer (no secrets).
        signature = "sig:" + _sha256_text(body_digest + "|" + signer_identity)
    else:
        signature = sign(body_digest)
    return SignedSnapshotEvidence(
        evidence_id=f"evid-{uuid.uuid4().hex[:16]}",
        catalog_id=plan.catalog_id,
        snapshot_version=plan.snapshot_version,
        owner_generation=plan.owner_generation,
        fencing_epoch=int(plan.fencing_epoch),
        vector_id=vector_id,
        attach_snapshot_version=observed_snapshot_version,
        signature=signature,
        signer_identity=_require_nonempty(
            signer_identity, field_name="signer_identity"
        ),
        body_digest=body_digest,
    )


def build_remote_worker_attach(
    member: SnapshotVectorMember,
    *,
    vector_id: str,
) -> RemoteWorkerAttachPlan:
    """Build a remote-worker attach plan that opens only the Quack endpoint."""

    return RemoteWorkerAttachPlan(
        catalog_id=member.catalog_id,
        quack_endpoint_identity=member.quack_endpoint_identity,
        owner_generation=member.owner_generation,
        fencing_epoch=member.fencing_epoch,
        snapshot_version=member.catalog_global_snapshot_id,
        vector_id=vector_id,
        opens_catalog_file=False,
    )


def verify_remote_snapshot_receipt(
    member: SnapshotVectorMember,
    evidence: SignedSnapshotEvidence,
    *,
    expected_vector_id: str,
) -> None:
    """Remote worker verifies owner generation and snapshot receipt before read."""

    if evidence.catalog_id != member.catalog_id:
        raise SnapshotAttachError("snapshot evidence catalog_id mismatch")
    if evidence.vector_id != expected_vector_id:
        raise SnapshotAttachError("snapshot evidence vector_id mismatch")
    if evidence.owner_generation != member.owner_generation:
        raise SnapshotAttachError(
            "stale or foreign owner-generation on snapshot evidence"
        )
    if evidence.fencing_epoch != member.fencing_epoch:
        raise SnapshotAttachError("stale fencing_epoch on snapshot evidence")
    if evidence.snapshot_version != member.catalog_global_snapshot_id:
        raise SnapshotAttachError(
            "snapshot evidence does not match receipted catalog-global snapshot"
        )
    if evidence.attach_snapshot_version != evidence.snapshot_version:
        raise SnapshotAttachError(
            "snapshot evidence attach version does not equal receipted snapshot"
        )


# ---------------------------------------------------------------------------
# Reader leases
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReaderLease:
    """Authoritative database-backed reader lease bound to a snapshot vector.

    Acquire, renew, and release bind process-birth identity, task/run identity,
    lease token, deadline, and generation fence. The raw lease token is redacted
    from public projections.
    """

    lease_id: str
    lease_token: str = field(repr=False)
    vector_id: str
    catalog_id: str
    snapshot_version: int
    owner_generation: int
    fencing_epoch: int
    process_birth: ProcessBirthBinding
    task_id: str
    run_id: str
    worker_id: str
    acquired_at: str
    expires_at: str
    status: LeaseStatus = LeaseStatus.ACTIVE
    renewed_at: str = ""
    shard_id: str = ""
    representation: str = "database"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "lease_id", _require_nonempty(self.lease_id, field_name="lease_id")
        )
        token = str(self.lease_token or "")
        if not token:
            raise ReaderLeaseError("lease_token is required")
        object.__setattr__(self, "lease_token", token)
        object.__setattr__(
            self, "vector_id", _require_nonempty(self.vector_id, field_name="vector_id")
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self,
            "snapshot_version",
            _require_nonneg_int(self.snapshot_version, field_name="snapshot_version"),
        )
        object.__setattr__(
            self,
            "owner_generation",
            _require_pos_int(self.owner_generation, field_name="owner_generation"),
        )
        object.__setattr__(
            self,
            "fencing_epoch",
            _require_pos_int(self.fencing_epoch, field_name="fencing_epoch"),
        )
        birth = _coerce_process_birth(self.process_birth)
        object.__setattr__(self, "process_birth", birth)
        object.__setattr__(
            self, "task_id", _require_nonempty(self.task_id, field_name="task_id")
        )
        object.__setattr__(
            self, "run_id", _require_nonempty(self.run_id, field_name="run_id")
        )
        object.__setattr__(
            self, "worker_id", _require_nonempty(self.worker_id, field_name="worker_id")
        )
        status = self.status
        if not isinstance(status, LeaseStatus):
            status = LeaseStatus(str(status))
            object.__setattr__(self, "status", status)
        rep = str(self.representation or "database").strip().lower()
        if rep in {"file", "filesystem", "path", "json_file"}:
            raise ReaderLeaseError(
                "reader leases must not be represented only by a file; "
                "authority lives in the companion database"
            )
        object.__setattr__(self, "representation", rep)

    def is_expired(self, *, now: float | None = None) -> bool:
        if self.status is LeaseStatus.EXPIRED:
            return True
        if self.status is LeaseStatus.RELEASED:
            return False
        clock = time.time() if now is None else float(now)
        return clock >= _parse_utc_iso(self.expires_at)

    def is_live(self, *, now: float | None = None) -> bool:
        return self.status is LeaseStatus.ACTIVE and not self.is_expired(now=now)

    def as_mapping(self, *, reveal_token: bool = False) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": READER_LEASE_SCHEMA,
                "lease_id": self.lease_id,
                "lease_token": self.lease_token if reveal_token else "***",
                "vector_id": self.vector_id,
                "catalog_id": self.catalog_id,
                "shard_id": self.shard_id,
                "snapshot_version": self.snapshot_version,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "process_birth": dict(self.process_birth.as_mapping()),
                "task_id": self.task_id,
                "run_id": self.run_id,
                "worker_id": self.worker_id,
                "acquired_at": self.acquired_at,
                "renewed_at": self.renewed_at,
                "expires_at": self.expires_at,
                "status": self.status.value,
                "representation": self.representation,
            }
        )

    def to_row(self) -> dict[str, Any]:
        """Full durable row including the lease token (database authority)."""

        row = dict(self.as_mapping(reveal_token=True))
        row["process_birth_json"] = _canonical_json(dict(self.process_birth.as_mapping()))
        row["body_json"] = _canonical_json(row)
        return row

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ReaderLease":
        birth_raw = row.get("process_birth")
        if birth_raw is None and row.get("process_birth_json"):
            birth_raw = json.loads(str(row["process_birth_json"]))
        return cls(
            lease_id=str(row["lease_id"]),
            lease_token=str(row.get("lease_token") or ""),
            vector_id=str(row["vector_id"]),
            catalog_id=str(row["catalog_id"]),
            snapshot_version=int(row["snapshot_version"]),
            owner_generation=int(row["owner_generation"]),
            fencing_epoch=int(row["fencing_epoch"]),
            process_birth=_coerce_process_birth(birth_raw),
            task_id=str(row["task_id"]),
            run_id=str(row["run_id"]),
            worker_id=str(row["worker_id"]),
            acquired_at=str(row["acquired_at"]),
            expires_at=str(row["expires_at"]),
            status=LeaseStatus(str(row.get("status") or LeaseStatus.ACTIVE.value)),
            renewed_at=str(row.get("renewed_at") or ""),
            shard_id=str(row.get("shard_id") or ""),
            representation=str(row.get("representation") or "database"),
        )


# ---------------------------------------------------------------------------
# Authoritative database (never file-only)
# ---------------------------------------------------------------------------


class AuthoritativeSnapshotDatabase:
    """Database-backed authority for snapshot vectors and reader leases.

    Models the control + companion tables that hold vectors and leases without
    requiring the optional ``duckdb`` package. Export/import simulates process
    restart while preserving CAS-style rows. Vectors and leases are never
    authoritative when represented only by a file.
    """

    def __init__(self, *, instance_id: str = "") -> None:
        self.instance_id = instance_id or uuid.uuid4().hex
        self._lock = threading.RLock()
        self._vectors: dict[str, dict[str, Any]] = {}
        self._leases: dict[str, dict[str, Any]] = {}
        self._clock: Callable[[], float] = time.time
        # Catalog-race retry budget (no cross-shard atomicity claim).
        self.catalog_race_max_attempts: int = 3

    # -- clock injection ---------------------------------------------------

    def set_clock(self, clock: Callable[[], float]) -> None:
        self._clock = clock

    def _now(self) -> float:
        return float(self._clock())

    # -- representation guard ----------------------------------------------

    def assert_not_file_authority(self, *, source: str, is_file_only: bool) -> None:
        if is_file_only:
            raise SnapshotError(
                f"snapshot vector or reader lease source {source!r} is file-only; "
                "authority must live in the control/companion database tables "
                f"{_VECTOR_TABLE!r} / {_LEASE_TABLE!r}"
            )

    # -- vector authority --------------------------------------------------

    def put_vector(self, vector: SnapshotVector) -> Mapping[str, Any]:
        """Persist a validated snapshot vector (control-scope authority)."""

        if not isinstance(vector, SnapshotVector):
            raise SnapshotVectorError("vector must be SnapshotVector")
        self.assert_not_file_authority(
            source=vector.vector_id, is_file_only=vector.representation == "file"
        )
        with self._lock:
            row = {
                "vector_id": vector.vector_id,
                "identity_digest": vector.identity_digest,
                "member_count": vector.member_count,
                "members_json": _canonical_json(
                    [dict(m.as_mapping()) for m in vector.members]
                ),
                "body_json": _canonical_json(dict(vector.as_mapping())),
                "captured_at": vector.captured_at,
                "representation": "database",
                "table": _VECTOR_TABLE,
            }
            self._vectors[vector.vector_id] = row
            return MappingProxyType(dict(row))

    def get_vector(self, vector_id: str) -> SnapshotVector | None:
        with self._lock:
            row = self._vectors.get(str(vector_id))
            if row is None:
                return None
            body = json.loads(row["body_json"])
            return SnapshotVector.from_mapping(body)

    def list_vector_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._vectors))

    # -- lease authority ---------------------------------------------------

    def acquire_lease(
        self,
        *,
        vector: SnapshotVector,
        catalog_id: str,
        process_birth: ProcessBirthBinding | Mapping[str, Any],
        task_id: str,
        run_id: str,
        worker_id: str,
        ttl_seconds: int = _DEFAULT_LEASE_TTL_SECONDS,
        lease_id: str | None = None,
        expected_owner_generation: int | None = None,
        expected_fencing_epoch: int | None = None,
    ) -> ReaderLease:
        """Acquire an authoritative reader lease before any read.

        Binds process birth, task/run, generation fence, vector, and a secret
        lease token. Fail closed on generation mismatch.
        """

        if not isinstance(vector, SnapshotVector):
            raise ReaderLeaseError("vector must be SnapshotVector")
        member = vector.member_for(catalog_id)
        birth = _coerce_process_birth(process_birth)
        if expected_owner_generation is not None and (
            expected_owner_generation != member.owner_generation
        ):
            raise ReaderLeaseError(
                "stale owner-generation fence on lease acquire "
                f"(expected {expected_owner_generation}, member has "
                f"{member.owner_generation})"
            )
        if expected_fencing_epoch is not None and (
            expected_fencing_epoch != member.fencing_epoch
        ):
            raise ReaderLeaseError(
                "stale fencing_epoch on lease acquire "
                f"(expected {expected_fencing_epoch}, member has "
                f"{member.fencing_epoch})"
            )
        ttl = int(ttl_seconds)
        if ttl < _MIN_LEASE_TTL_SECONDS or ttl > _MAX_LEASE_TTL_SECONDS:
            raise ReaderLeaseError(
                f"ttl_seconds out of range [{_MIN_LEASE_TTL_SECONDS}, "
                f"{_MAX_LEASE_TTL_SECONDS}]"
            )
        now = self._now()
        lid = str(lease_id or "").strip() or f"rl-{uuid.uuid4().hex}"
        token = secrets.token_urlsafe(32)
        lease = ReaderLease(
            lease_id=lid,
            lease_token=token,
            vector_id=vector.vector_id,
            catalog_id=member.catalog_id,
            snapshot_version=member.catalog_global_snapshot_id,
            owner_generation=member.owner_generation,
            fencing_epoch=member.fencing_epoch,
            process_birth=birth,
            task_id=_require_nonempty(task_id, field_name="task_id"),
            run_id=_require_nonempty(run_id, field_name="run_id"),
            worker_id=_require_nonempty(worker_id, field_name="worker_id"),
            acquired_at=_utc_iso(now),
            expires_at=_utc_iso(now + ttl),
            status=LeaseStatus.ACTIVE,
            renewed_at="",
            shard_id=member.shard_id,
            representation="database",
        )
        with self._lock:
            if lid in self._leases:
                raise ReaderLeaseError(f"lease_id {lid!r} already exists")
            # Ensure vector is durable before lease references it.
            if vector.vector_id not in self._vectors:
                self.put_vector(vector)
            self._leases[lid] = lease.to_row()
            return lease

    def _load_lease(self, lease_id: str) -> ReaderLease:
        row = self._leases.get(str(lease_id))
        if row is None:
            raise ReaderLeaseError(f"unknown lease_id {lease_id!r}")
        return ReaderLease.from_row(row)

    def _assert_fence(
        self,
        lease: ReaderLease,
        *,
        lease_token: str,
        process_birth: ProcessBirthBinding,
        task_id: str,
        run_id: str,
        owner_generation: int | None,
        fencing_epoch: int | None,
        action: str,
    ) -> ReaderLease:
        # Expiry first (crashed readers lose protection only through expiry).
        if lease.status is LeaseStatus.RELEASED:
            raise ReaderLeaseError(
                f"cannot {action} a released lease {lease.lease_id!r}"
            )
        if lease.is_expired(now=self._now()) or lease.status is LeaseStatus.EXPIRED:
            # Materialize expiry.
            expired = ReaderLease(
                lease_id=lease.lease_id,
                lease_token=lease.lease_token,
                vector_id=lease.vector_id,
                catalog_id=lease.catalog_id,
                snapshot_version=lease.snapshot_version,
                owner_generation=lease.owner_generation,
                fencing_epoch=lease.fencing_epoch,
                process_birth=lease.process_birth,
                task_id=lease.task_id,
                run_id=lease.run_id,
                worker_id=lease.worker_id,
                acquired_at=lease.acquired_at,
                expires_at=lease.expires_at,
                status=LeaseStatus.EXPIRED,
                renewed_at=lease.renewed_at,
                shard_id=lease.shard_id,
            )
            self._leases[lease.lease_id] = expired.to_row()
            raise ReaderLeaseError(
                f"cannot {action} expired lease {lease.lease_id!r}; crashed "
                "readers lose protection only through bounded lease expiry"
            )
        if not secrets.compare_digest(str(lease_token), lease.lease_token):
            raise ReaderLeaseError(
                f"foreign lease token rejected on {action} for {lease.lease_id!r}"
            )
        if not _process_birth_equal(process_birth, lease.process_birth):
            # PID reuse: same pid with different boot/start_ticks fails closed.
            if process_birth.pid == lease.process_birth.pid:
                raise ReaderLeaseError(
                    f"PID reuse detected on {action} for lease {lease.lease_id!r}; "
                    "process birth identity does not match"
                )
            raise ReaderLeaseError(
                f"process birth identity mismatch on {action} for "
                f"lease {lease.lease_id!r}"
            )
        if task_id != lease.task_id or run_id != lease.run_id:
            raise ReaderLeaseError(
                f"task/run fence mismatch on {action} for lease {lease.lease_id!r}"
            )
        if (
            owner_generation is not None
            and owner_generation != lease.owner_generation
        ):
            raise ReaderLeaseError(
                f"stale owner-generation fence on {action} for lease "
                f"{lease.lease_id!r}"
            )
        if fencing_epoch is not None and fencing_epoch != lease.fencing_epoch:
            raise ReaderLeaseError(
                f"stale fencing_epoch on {action} for lease {lease.lease_id!r}"
            )
        return lease

    def renew_lease(
        self,
        *,
        lease_id: str,
        lease_token: str,
        process_birth: ProcessBirthBinding | Mapping[str, Any],
        task_id: str,
        run_id: str,
        ttl_seconds: int = _DEFAULT_LEASE_TTL_SECONDS,
        owner_generation: int | None = None,
        fencing_epoch: int | None = None,
    ) -> ReaderLease:
        """Renew an active lease while the worker remains reading."""

        birth = _coerce_process_birth(process_birth)
        ttl = int(ttl_seconds)
        if ttl < _MIN_LEASE_TTL_SECONDS or ttl > _MAX_LEASE_TTL_SECONDS:
            raise ReaderLeaseError("ttl_seconds out of range for renew")
        with self._lock:
            lease = self._load_lease(lease_id)
            lease = self._assert_fence(
                lease,
                lease_token=lease_token,
                process_birth=birth,
                task_id=task_id,
                run_id=run_id,
                owner_generation=owner_generation,
                fencing_epoch=fencing_epoch,
                action="renew",
            )
            now = self._now()
            renewed = ReaderLease(
                lease_id=lease.lease_id,
                lease_token=lease.lease_token,
                vector_id=lease.vector_id,
                catalog_id=lease.catalog_id,
                snapshot_version=lease.snapshot_version,
                owner_generation=lease.owner_generation,
                fencing_epoch=lease.fencing_epoch,
                process_birth=lease.process_birth,
                task_id=lease.task_id,
                run_id=lease.run_id,
                worker_id=lease.worker_id,
                acquired_at=lease.acquired_at,
                expires_at=_utc_iso(now + ttl),
                status=LeaseStatus.ACTIVE,
                renewed_at=_utc_iso(now),
                shard_id=lease.shard_id,
            )
            self._leases[lease.lease_id] = renewed.to_row()
            return renewed

    def release_lease(
        self,
        *,
        lease_id: str,
        lease_token: str,
        process_birth: ProcessBirthBinding | Mapping[str, Any],
        task_id: str,
        run_id: str,
        owner_generation: int | None = None,
        fencing_epoch: int | None = None,
    ) -> ReaderLease:
        """Release only the exact fenced lease token after all reads finish."""

        birth = _coerce_process_birth(process_birth)
        with self._lock:
            lease = self._load_lease(lease_id)
            lease = self._assert_fence(
                lease,
                lease_token=lease_token,
                process_birth=birth,
                task_id=task_id,
                run_id=run_id,
                owner_generation=owner_generation,
                fencing_epoch=fencing_epoch,
                action="release",
            )
            released = ReaderLease(
                lease_id=lease.lease_id,
                lease_token=lease.lease_token,
                vector_id=lease.vector_id,
                catalog_id=lease.catalog_id,
                snapshot_version=lease.snapshot_version,
                owner_generation=lease.owner_generation,
                fencing_epoch=lease.fencing_epoch,
                process_birth=lease.process_birth,
                task_id=lease.task_id,
                run_id=lease.run_id,
                worker_id=lease.worker_id,
                acquired_at=lease.acquired_at,
                expires_at=lease.expires_at,
                status=LeaseStatus.RELEASED,
                renewed_at=lease.renewed_at,
                shard_id=lease.shard_id,
            )
            self._leases[lease.lease_id] = released.to_row()
            return released

    def expire_due_leases(self) -> tuple[str, ...]:
        """Materialize expiry for crashed readers (bounded lease expiry only)."""

        now = self._now()
        expired_ids: list[str] = []
        with self._lock:
            for lid, row in list(self._leases.items()):
                lease = ReaderLease.from_row(row)
                if lease.status is LeaseStatus.ACTIVE and lease.is_expired(now=now):
                    expired = ReaderLease(
                        lease_id=lease.lease_id,
                        lease_token=lease.lease_token,
                        vector_id=lease.vector_id,
                        catalog_id=lease.catalog_id,
                        snapshot_version=lease.snapshot_version,
                        owner_generation=lease.owner_generation,
                        fencing_epoch=lease.fencing_epoch,
                        process_birth=lease.process_birth,
                        task_id=lease.task_id,
                        run_id=lease.run_id,
                        worker_id=lease.worker_id,
                        acquired_at=lease.acquired_at,
                        expires_at=lease.expires_at,
                        status=LeaseStatus.EXPIRED,
                        renewed_at=lease.renewed_at,
                        shard_id=lease.shard_id,
                    )
                    self._leases[lid] = expired.to_row()
                    expired_ids.append(lid)
        return tuple(sorted(expired_ids))

    def list_live_leases(
        self,
        *,
        catalog_id: str | None = None,
        vector_id: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        """Exact live reader-lease set consumed by DQK-096 maintenance.

        Returns active, non-expired leases only. Crashed readers are absent
        once bounded lease expiry has been materialised.
        """

        self.expire_due_leases()
        now = self._now()
        live: list[Mapping[str, Any]] = []
        with self._lock:
            for row in self._leases.values():
                lease = ReaderLease.from_row(row)
                if not lease.is_live(now=now):
                    continue
                if catalog_id is not None and lease.catalog_id != catalog_id:
                    continue
                if vector_id is not None and lease.vector_id != vector_id:
                    continue
                # Maintenance projection: redacted token, full fence bindings.
                live.append(lease.as_mapping(reveal_token=False))
        return tuple(sorted(live, key=lambda r: str(r["lease_id"])))

    def get_lease(self, lease_id: str) -> ReaderLease | None:
        with self._lock:
            row = self._leases.get(str(lease_id))
            if row is None:
                return None
            return ReaderLease.from_row(row)

    # -- catalog race retry (no cross-shard atomicity) ---------------------

    def with_catalog_race_retry(
        self,
        operation: Callable[[], Any],
        *,
        is_retryable: Callable[[BaseException], bool] | None = None,
    ) -> Any:
        """Retry a single-catalog operation on transient races.

        Never claims atomicity across independent shards: each shard's
        operation is retried independently.
        """

        attempts = max(1, int(self.catalog_race_max_attempts))
        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                return operation()
            except SnapshotError as exc:
                last_exc = exc
                retryable = (
                    is_retryable(exc)
                    if is_retryable is not None
                    else ("race" in str(exc).lower() or "conflict" in str(exc).lower())
                )
                if not retryable or attempt >= attempts:
                    raise
            except CatalogError as exc:
                last_exc = exc
                if attempt >= attempts:
                    raise SnapshotError(str(exc)) from exc
        assert last_exc is not None  # pragma: no cover
        raise last_exc

    # -- restart survival --------------------------------------------------

    def export_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "instance_id": self.instance_id,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "tables": {
                    _VECTOR_TABLE: dict(self._vectors),
                    _LEASE_TABLE: dict(self._leases),
                },
                "representation": "database",
            }

    def import_state(self, state: Mapping[str, Any]) -> None:
        with self._lock:
            tables = dict(state.get("tables") or {})
            self._vectors = dict(tables.get(_VECTOR_TABLE) or {})
            self._leases = dict(tables.get(_LEASE_TABLE) or {})
            self.instance_id = str(state.get("instance_id") or self.instance_id)


def assert_database_backed_authority(
    *,
    source: str,
    is_file_only: bool = False,
    representation: str = "database",
) -> None:
    """Reject file-only snapshot vector or reader-lease representations."""

    rep = str(representation or "").strip().lower()
    if is_file_only or rep in {"file", "filesystem", "path", "json_file", "parquet_file"}:
        raise SnapshotError(
            f"{source!r} must not be represented only by a file; "
            f"store rows in {_VECTOR_TABLE} / {_LEASE_TABLE}"
        )


# ---------------------------------------------------------------------------
# Time-travel replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TimeTravelReplayResult:
    """Result of replaying a query against a retained snapshot vector."""

    vector_id: str
    logical_result_digest: str
    snapshot_versions: Mapping[str, int]
    retained: bool = True
    replayed_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_versions",
            MappingProxyType(dict(self.snapshot_versions)),
        )
        replayed = str(self.replayed_at or "").strip() or _utc_iso()
        object.__setattr__(self, "replayed_at", replayed)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": TIME_TRAVEL_REPLAY_SCHEMA,
                "vector_id": self.vector_id,
                "logical_result_digest": self.logical_result_digest,
                "snapshot_versions": dict(self.snapshot_versions),
                "retained": self.retained,
                "replayed_at": self.replayed_at,
            }
        )


def replay_time_travel(
    vector: SnapshotVector,
    *,
    retained_snapshots: Mapping[str, Sequence[int]],
    logical_query_id: str,
    result_builder: Callable[[SnapshotVector], Any] | None = None,
) -> TimeTravelReplayResult:
    """Replay at the vector's snapshots or raise a typed retention error.

    ``retained_snapshots`` maps ``catalog_id`` → retained snapshot versions.
    When every member's snapshot is retained, the logical result is
    deterministic for a given ``logical_query_id`` + vector identity.
    """

    if not isinstance(vector, SnapshotVector):
        raise SnapshotVectorError("vector must be SnapshotVector")
    missing: list[str] = []
    versions: dict[str, int] = {}
    for member in vector.members:
        retained = set(int(v) for v in (retained_snapshots.get(member.catalog_id) or ()))
        versions[member.catalog_id] = member.catalog_global_snapshot_id
        if member.catalog_global_snapshot_id not in retained:
            missing.append(
                f"{member.catalog_id}@{member.catalog_global_snapshot_id}"
            )
    if missing:
        raise SnapshotRetentionError(
            "time-travel target outside retention window for members: "
            + ", ".join(missing)
        )
    if result_builder is not None:
        payload = result_builder(vector)
        digest = _digest_of(payload)
    else:
        digest = _digest_of(
            {
                "logical_query_id": _require_nonempty(
                    logical_query_id, field_name="logical_query_id"
                ),
                "vector_identity": vector.identity_digest,
                "snapshot_versions": versions,
            }
        )
    return TimeTravelReplayResult(
        vector_id=vector.vector_id,
        logical_result_digest=digest,
        snapshot_versions=versions,
        retained=True,
    )
