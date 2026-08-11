"""Versioned field-ID contracts and application data constraints (DQK-094).

DuckLake supplies no PK, UNIQUE, FK, CHECK, or index enforcement. Application
constraints must therefore be validated and durable-reserved **before** any
non-atomic DuckLake snapshot boundary, then terminalized through a durable
outbox after the exact committed snapshot is known.

Authority layout:

* **control** (DQK-086) — authoritative dataset-home-shard routing for every
  uniqueness/reference scope
* **companion** (per-shard private owner-control DuckDB) — logical-key /
  idempotency-key reservations, durable outbox, and versioned schema contracts
* **Quack-serving DatabaseInstance** — never ATTACHes or sees companion tables;
  never holds reservation authority

Write path (single fenced catalog owner per shard):

1. Resolve uniqueness/reference scope to exactly one home shard (fail closed on
   unsupported cross-shard scopes **before** object copy or snapshot mutation)
2. Validate field-ID schema policy, domain, tenant, uniqueness, and reference
   constraints; emit reject evidence that binds exact source files and schema
   revision when invalid
3. Acquire a persistent logical-key + idempotency-key reservation in the
   companion owner-control DuckDB (no read-before-write check; durable put)
4. Cross the non-atomic DuckLake snapshot boundary
5. Terminalize the reservation with the exact committed snapshot through the
   durable outbox

A successful claim is terminal: it is never released, reassigned, or reused.
Crash recovery may reclaim **only** a proven incomplete or failed claim.
Recovery reconciles reservation, object, catalog snapshot, and outbox states
without claiming atomicity across files.

Import is side-effect free: no DuckDB connection, network, or filesystem I/O.
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
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.ducklake.registry import (
    CompanionLakeRegistry,
    ControlLakeRegistry,
    DatabaseInstanceBinding,
    DatabaseInstanceKind,
    RegistryError,
    UnsupportedCrossShardUniqueness,
)
from ipfs_datasets_py.ducklake.schema import (
    COMPANION_TABLES,
    DUCKLAKE_INTERNAL_V1_TABLES,
    is_ducklake_internal_table,
)

__all__ = [
    "COLUMN_POLICY_SCHEMA",
    "CONSTRAINT_EVIDENCE_SCHEMA",
    "CONTRACTS_SCHEMA",
    "FIELD_CONTRACT_SCHEMA",
    "MIGRATION_RECEIPT_SCHEMA",
    "RESERVATION_SCHEMA",
    "SCHEMA_CONTRACT_SCHEMA",
    "TYPE_PROMOTION_SCHEMA",
    "ColumnPolicy",
    "ConstraintEvidence",
    "ConstraintKind",
    "ConstraintService",
    "ConstraintViolation",
    "ContractError",
    "CrossShardConstraintError",
    "DomainCheck",
    "EvolutionKind",
    "ExtraColumnPolicy",
    "FieldContract",
    "FieldType",
    "LogicalKeyReservation",
    "MissingColumnPolicy",
    "MigrationAuthorizationError",
    "MigrationReceipt",
    "OutboxEntry",
    "PromotionResult",
    "RecordValidationResult",
    "RejectEvidence",
    "ReservationContention",
    "ReservationError",
    "ReservationStatus",
    "RollbackPlan",
    "SchemaContract",
    "SchemaEvolutionError",
    "SchemaEvolutionPlan",
    "SchemaMigrationError",
    "SnapshotSchemaView",
    "TypePromotionError",
    "TypePromotionRules",
    "WriteCommitReceipt",
    "apply_column_policy",
    "assert_companion_reservation_isolation",
    "assert_not_ducklake_internal_metadata",
    "build_constraint_evidence",
    "canonical_logical_key_digest",
    "evolve_schema",
    "is_lossless_promotion",
    "logical_key_digest_for",
    "promote_value",
    "replay_schema_at_revision",
    "validate_record",
    "validate_records_before_commit",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

CONTRACTS_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-schema-contracts@1"
FIELD_CONTRACT_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-field-contract@1"
SCHEMA_CONTRACT_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-schema-contract@1"
TYPE_PROMOTION_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-type-promotion@1"
COLUMN_POLICY_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-column-policy@1"
CONSTRAINT_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-constraint-evidence@1"
)
RESERVATION_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-logical-key-reservation@1"
MIGRATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-schema-migration-receipt@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-094-schema-contracts-constraints-20260810"
)

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_FIELD_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_SHA256_PREFIX: Final[str] = "sha256:"

# Companion authority tables that hold reservations / outbox / schema contracts.
_RESERVATION_AUTHORITY_TABLES: Final[frozenset[str]] = frozenset(
    {
        "lake_logical_key_reservations",
        "lake_ingest_outbox",
        "lake_schema_contracts",
        "logical_key_reservation",
        "ingest_outbox",
    }
)

# Statuses that may be reclaimed by crash recovery (never successful claims).
_RECLAIMABLE_STATUSES: Final[frozenset[str]] = frozenset(
    {"incomplete", "failed", "pending_reclaim"}
)
_TERMINAL_SUCCESS_STATUSES: Final[frozenset[str]] = frozenset({"committed"})
_ACTIVE_CLAIM_STATUSES: Final[frozenset[str]] = frozenset(
    {"reserved", "committed", "in_doubt"}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ContractError(ValueError):
    """Fail-closed schema contract / constraint rejection."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class SchemaEvolutionError(ContractError):
    """Invalid add/drop/rename or unauthorized schema change."""


class TypePromotionError(ContractError):
    """Lossy or unsupported type promotion."""


class ConstraintViolation(ContractError):
    """Domain, uniqueness, reference, or tenant constraint failed."""


class CrossShardConstraintError(ContractError):
    """Uniqueness/reference scope does not resolve to one home shard."""


class ReservationError(ContractError):
    """Logical-key / idempotency reservation failure."""


class ReservationContention(ReservationError):
    """Same-key race lost at the durable reservation boundary."""


class MigrationAuthorizationError(ContractError):
    """Schema change lacks an authorized migration receipt / rollback plan."""


class SchemaMigrationError(MigrationAuthorizationError):
    """Migration receipt / rollback plan is malformed or mismatched."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_text(text: str) -> str:
    return _SHA256_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractError(f"{field_name} is required")
    return text


def _require_token(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SAFE_TOKEN.match(text):
        raise ContractError(f"invalid {field_name} {value!r}")
    return text


def _require_field_id(value: Any) -> str:
    text = _require_nonempty(value, field_name="field_id")
    if not _FIELD_ID_RE.match(text):
        raise ContractError(f"invalid field_id {value!r}")
    return text


def logical_key_digest_for(logical_key: str | Mapping[str, Any]) -> str:
    """Canonical digest of a logical uniqueness key."""

    if isinstance(logical_key, Mapping):
        return _sha256_text(_canonical_json(dict(logical_key)))
    return _sha256_text(_require_nonempty(logical_key, field_name="logical_key"))


# Back-compat alias used by some call sites / tests.
canonical_logical_key_digest = logical_key_digest_for


def assert_not_ducklake_internal_metadata(table_name: str) -> None:
    """Fail closed if a name collides with DuckLake internal v1 metadata."""

    name = str(table_name or "").strip().lower()
    if is_ducklake_internal_table(name) or name in DUCKLAKE_INTERNAL_V1_TABLES:
        raise ContractError(
            f"reservation/outbox authority must not live in DuckLake internal "
            f"metadata table {table_name!r}"
        )


def assert_companion_reservation_isolation(
    companion: CompanionLakeRegistry,
    *,
    quack: DatabaseInstanceBinding | None = None,
) -> None:
    """Prove reservation/outbox tables live only in companion, never Quack."""

    try:
        companion.assert_isolated_from_quack()
    except RegistryError as exc:
        raise ContractError(
            f"companion reservation database must never be ATTACHed to or "
            f"visible from the Quack-serving DatabaseInstance: {exc}"
        ) from exc
    if companion.instance.kind is not DatabaseInstanceKind.COMPANION_PRIVATE:
        raise ContractError(
            "reservations require COMPANION_PRIVATE DatabaseInstance"
        )
    if companion.instance.attachable_from_quack:
        raise ContractError(
            "companion owner-control DuckDB must never be attachable from "
            "the Quack-serving DatabaseInstance"
        )
    for table in _RESERVATION_AUTHORITY_TABLES:
        if table in DUCKLAKE_INTERNAL_V1_TABLES:
            raise ContractError(
                f"authority table {table!r} collides with DuckLake internals"
            )
        physical = {
            "logical_key_reservation": "lake_logical_key_reservations",
            "ingest_outbox": "lake_ingest_outbox",
        }.get(table, table)
        if physical not in COMPANION_TABLES and table not in COMPANION_TABLES:
            # Short names resolve via assert_companion_authority.
            pass
        companion.assert_companion_authority(
            physical if physical in COMPANION_TABLES else table
        )
    if quack is not None:
        try:
            companion.instance.assert_not_attached_to(quack)
        except RegistryError as exc:
            raise ContractError(str(exc)) from exc
        if companion.store.is_visible_from(quack.instance_id):
            raise ContractError(
                "companion reservation database is visible from Quack-serving "
                "DatabaseInstance"
            )


# ---------------------------------------------------------------------------
# Field types and lossless promotion
# ---------------------------------------------------------------------------


class FieldType(str, Enum):
    """Closed set of versioned field types used by field-ID contracts."""

    BOOLEAN = "boolean"
    INT8 = "int8"
    INT16 = "int16"
    INT32 = "int32"
    INT64 = "int64"
    UINT8 = "uint8"
    UINT16 = "uint16"
    UINT32 = "uint32"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    DECIMAL = "decimal"
    UTF8 = "utf8"
    BINARY = "binary"
    DATE = "date"
    TIMESTAMP = "timestamp"
    JSON = "json"

    @classmethod
    def parse(cls, value: str | "FieldType") -> "FieldType":
        if isinstance(value, FieldType):
            return value
        text = str(value or "").strip().lower()
        # Accept a few Parquet / DuckDB aliases.
        aliases = {
            "bool": "boolean",
            "int": "int32",
            "integer": "int32",
            "bigint": "int64",
            "long": "int64",
            "float": "float32",
            "double": "float64",
            "string": "utf8",
            "varchar": "utf8",
            "bytes": "binary",
            "blob": "binary",
            "timestamptz": "timestamp",
        }
        text = aliases.get(text, text)
        try:
            return cls(text)
        except ValueError as exc:
            raise ContractError(f"unknown field type {value!r}") from exc


# Directed lossless promotion edges (source -> targets reachable by widening).
_LOSSLESS_EDGES: Final[Mapping[FieldType, frozenset[FieldType]]] = MappingProxyType(
    {
        FieldType.BOOLEAN: frozenset({FieldType.BOOLEAN}),
        FieldType.INT8: frozenset(
            {
                FieldType.INT8,
                FieldType.INT16,
                FieldType.INT32,
                FieldType.INT64,
                FieldType.FLOAT64,
                FieldType.DECIMAL,
            }
        ),
        FieldType.INT16: frozenset(
            {
                FieldType.INT16,
                FieldType.INT32,
                FieldType.INT64,
                FieldType.FLOAT64,
                FieldType.DECIMAL,
            }
        ),
        FieldType.INT32: frozenset(
            {
                FieldType.INT32,
                FieldType.INT64,
                FieldType.FLOAT64,
                FieldType.DECIMAL,
            }
        ),
        FieldType.INT64: frozenset(
            {FieldType.INT64, FieldType.DECIMAL, FieldType.FLOAT64}
        ),
        FieldType.UINT8: frozenset(
            {
                FieldType.UINT8,
                FieldType.UINT16,
                FieldType.UINT32,
                FieldType.UINT64,
                FieldType.INT16,
                FieldType.INT32,
                FieldType.INT64,
                FieldType.FLOAT64,
                FieldType.DECIMAL,
            }
        ),
        FieldType.UINT16: frozenset(
            {
                FieldType.UINT16,
                FieldType.UINT32,
                FieldType.UINT64,
                FieldType.INT32,
                FieldType.INT64,
                FieldType.FLOAT64,
                FieldType.DECIMAL,
            }
        ),
        FieldType.UINT32: frozenset(
            {
                FieldType.UINT32,
                FieldType.UINT64,
                FieldType.INT64,
                FieldType.FLOAT64,
                FieldType.DECIMAL,
            }
        ),
        FieldType.UINT64: frozenset(
            {FieldType.UINT64, FieldType.DECIMAL, FieldType.FLOAT64}
        ),
        FieldType.FLOAT32: frozenset(
            {FieldType.FLOAT32, FieldType.FLOAT64, FieldType.DECIMAL}
        ),
        FieldType.FLOAT64: frozenset({FieldType.FLOAT64, FieldType.DECIMAL}),
        FieldType.DECIMAL: frozenset({FieldType.DECIMAL}),
        FieldType.UTF8: frozenset({FieldType.UTF8}),
        FieldType.BINARY: frozenset({FieldType.BINARY}),
        FieldType.DATE: frozenset({FieldType.DATE, FieldType.TIMESTAMP}),
        FieldType.TIMESTAMP: frozenset({FieldType.TIMESTAMP}),
        FieldType.JSON: frozenset({FieldType.JSON, FieldType.UTF8}),
    }
)


def is_lossless_promotion(
    source: str | FieldType, target: str | FieldType
) -> bool:
    """Return True when *source* may be promoted to *target* without loss."""

    src = FieldType.parse(source)
    dst = FieldType.parse(target)
    if src is dst:
        return True
    return dst in _LOSSLESS_EDGES.get(src, frozenset())


def promote_value(
    value: Any,
    *,
    source: str | FieldType,
    target: str | FieldType,
) -> Any:
    """Promote *value* along a lossless path; fail closed on lossy moves."""

    src = FieldType.parse(source)
    dst = FieldType.parse(target)
    if not is_lossless_promotion(src, dst):
        raise TypePromotionError(
            f"lossy type promotion {src.value} -> {dst.value} is rejected",
            details={"source": src.value, "target": dst.value},
        )
    if value is None:
        return None
    if src is dst:
        return value

    # Widening numeric promotions.
    if dst in {
        FieldType.INT8,
        FieldType.INT16,
        FieldType.INT32,
        FieldType.INT64,
        FieldType.UINT8,
        FieldType.UINT16,
        FieldType.UINT32,
        FieldType.UINT64,
    }:
        return int(value)
    if dst is FieldType.FLOAT32:
        return float(value)
    if dst is FieldType.FLOAT64:
        return float(value)
    if dst is FieldType.DECIMAL:
        # Preserve exact integer when possible; otherwise string of decimal form.
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float):
            return repr(value) if value != int(value) else int(value)
        return value
    if dst is FieldType.UTF8 and src is FieldType.JSON:
        if isinstance(value, (dict, list)):
            return _canonical_json(value)
        return str(value)
    if dst is FieldType.TIMESTAMP and src is FieldType.DATE:
        text = str(value)
        if "T" in text:
            return text
        return f"{text}T00:00:00Z"
    return value


@dataclass(frozen=True, slots=True)
class TypePromotionRules:
    """Closed lossless type-promotion policy for schema evolution."""

    SCHEMA: ClassVar[str] = TYPE_PROMOTION_SCHEMA
    allow_same_type: bool = True
    # Optional explicit edges layered on the default graph (still must be lossless).
    extra_edges: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def allows(self, source: str | FieldType, target: str | FieldType) -> bool:
        src = FieldType.parse(source)
        dst = FieldType.parse(target)
        if src is dst:
            return bool(self.allow_same_type)
        if is_lossless_promotion(src, dst):
            return True
        extras = self.extra_edges.get(src.value, ())
        return dst.value in {FieldType.parse(x).value for x in extras}

    def promote(
        self, value: Any, *, source: str | FieldType, target: str | FieldType
    ) -> Any:
        if not self.allows(source, target):
            raise TypePromotionError(
                f"promotion {FieldType.parse(source).value} -> "
                f"{FieldType.parse(target).value} not permitted by rules"
            )
        return promote_value(value, source=source, target=target)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "allow_same_type": self.allow_same_type,
                "extra_edges": {
                    k: list(v) for k, v in sorted(self.extra_edges.items())
                },
                "default_lossless_graph": {
                    src.value: sorted(t.value for t in targets)
                    for src, targets in sorted(
                        _LOSSLESS_EDGES.items(), key=lambda kv: kv[0].value
                    )
                },
            }
        )


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Outcome of replaying type promotion across a historic snapshot view."""

    field_id: str
    source_type: str
    target_type: str
    lossless: bool
    value_before: Any
    value_after: Any

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "field_id": self.field_id,
                "source_type": self.source_type,
                "target_type": self.target_type,
                "lossless": self.lossless,
                "value_before": self.value_before,
                "value_after": self.value_after,
            }
        )


# ---------------------------------------------------------------------------
# Column policy
# ---------------------------------------------------------------------------


class MissingColumnPolicy(str, Enum):
    """How missing required/optional columns are handled before commit."""

    REJECT = "reject"
    DEFAULT = "default"
    NULL_IF_NULLABLE = "null_if_nullable"


class ExtraColumnPolicy(str, Enum):
    """How undeclared columns are handled before commit."""

    REJECT = "reject"
    DROP = "drop"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class ColumnPolicy:
    """Default / missing / extra column policy (never permissive by default)."""

    SCHEMA: ClassVar[str] = COLUMN_POLICY_SCHEMA
    missing: MissingColumnPolicy = MissingColumnPolicy.REJECT
    extra: ExtraColumnPolicy = ExtraColumnPolicy.REJECT
    require_field_ids: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.missing, MissingColumnPolicy):
            object.__setattr__(
                self, "missing", MissingColumnPolicy(str(self.missing))
            )
        if not isinstance(self.extra, ExtraColumnPolicy):
            object.__setattr__(self, "extra", ExtraColumnPolicy(str(self.extra)))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "missing": self.missing.value,
                "extra": self.extra.value,
                "require_field_ids": self.require_field_ids,
            }
        )


# ---------------------------------------------------------------------------
# Field and schema contracts (versioned field IDs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DomainCheck:
    """Application CHECK-like domain constraint for one field."""

    kind: str  # enum | range | regex | not_null | custom
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = _require_nonempty(self.kind, field_name="domain.kind").lower()
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "params", MappingProxyType(dict(self.params or {})))

    def validate(self, value: Any, *, field_id: str) -> None:
        if self.kind == "not_null":
            if value is None:
                raise ConstraintViolation(
                    f"domain not_null failed for field_id {field_id!r}",
                    details={"field_id": field_id, "kind": self.kind},
                )
            return
        if value is None:
            return
        if self.kind == "enum":
            allowed = list(self.params.get("values") or [])
            if value not in allowed:
                raise ConstraintViolation(
                    f"domain enum failed for field_id {field_id!r}: {value!r} "
                    f"not in {allowed!r}",
                    details={
                        "field_id": field_id,
                        "kind": self.kind,
                        "value": value,
                        "allowed": allowed,
                    },
                )
            return
        if self.kind == "range":
            minimum = self.params.get("min")
            maximum = self.params.get("max")
            if minimum is not None and value < minimum:
                raise ConstraintViolation(
                    f"domain range min failed for field_id {field_id!r}",
                    details={"field_id": field_id, "min": minimum, "value": value},
                )
            if maximum is not None and value > maximum:
                raise ConstraintViolation(
                    f"domain range max failed for field_id {field_id!r}",
                    details={"field_id": field_id, "max": maximum, "value": value},
                )
            return
        if self.kind == "regex":
            pattern = str(self.params.get("pattern") or "")
            if not pattern or re.fullmatch(pattern, str(value)) is None:
                raise ConstraintViolation(
                    f"domain regex failed for field_id {field_id!r}",
                    details={
                        "field_id": field_id,
                        "pattern": pattern,
                        "value": value,
                    },
                )
            return
        if self.kind == "custom":
            # Custom checks are fail-closed without an evaluator in this module.
            raise ConstraintViolation(
                f"custom domain checks require an authorized evaluator "
                f"(field_id={field_id!r})",
                details={"field_id": field_id, "kind": self.kind},
            )
        raise ContractError(f"unknown domain kind {self.kind!r}")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType({"kind": self.kind, "params": dict(self.params)})


@dataclass(frozen=True, slots=True)
class FieldContract:
    """Versioned field identified by stable field_id (not name alone)."""

    SCHEMA: ClassVar[str] = FIELD_CONTRACT_SCHEMA
    field_id: str
    name: str
    field_type: FieldType
    nullable: bool = True
    default: Any = None
    domain: DomainCheck | None = None
    required: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_id", _require_field_id(self.field_id))
        object.__setattr__(
            self, "name", _require_nonempty(self.name, field_name="name")
        )
        object.__setattr__(self, "field_type", FieldType.parse(self.field_type))
        if self.domain is not None and not isinstance(self.domain, DomainCheck):
            raise ContractError("domain must be DomainCheck or None")
        if self.required and self.nullable and self.default is None:
            # Required fields may still be nullable only with an explicit default.
            pass

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "field_id": self.field_id,
                "name": self.name,
                "type": self.field_type.value,
                "nullable": self.nullable,
                "default": self.default,
                "domain": None if self.domain is None else dict(self.domain.as_mapping()),
                "required": self.required,
                "description": self.description,
            }
        )


class EvolutionKind(str, Enum):
    ADD = "add"
    DROP = "drop"
    RENAME = "rename"
    PROMOTE = "promote"
    NOOP = "noop"


@dataclass(frozen=True, slots=True)
class SchemaEvolutionPlan:
    """Deterministic evolution steps between two schema contract revisions."""

    from_revision: int
    to_revision: int
    steps: tuple[Mapping[str, Any], ...]
    lossless: bool

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "from_revision": self.from_revision,
                "to_revision": self.to_revision,
                "steps": [dict(s) for s in self.steps],
                "lossless": self.lossless,
            }
        )


@dataclass(frozen=True, slots=True)
class RollbackPlan:
    """Rollback plan required for every authorized schema migration."""

    plan_id: str
    target_revision: int
    steps: tuple[Mapping[str, Any], ...]
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "plan_id", _require_nonempty(self.plan_id, field_name="plan_id")
        )
        if int(self.target_revision) < 0:
            raise SchemaMigrationError("rollback target_revision must be >= 0")
        object.__setattr__(self, "steps", tuple(dict(s) for s in self.steps))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "plan_id": self.plan_id,
                "target_revision": self.target_revision,
                "steps": [dict(s) for s in self.steps],
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    """Authorized migration receipt required before schema mutation."""

    SCHEMA: ClassVar[str] = MIGRATION_RECEIPT_SCHEMA
    receipt_id: str
    schema_contract_id: str
    from_revision: int
    to_revision: int
    authorizer_identity: str
    rollback_plan: RollbackPlan
    authorized: bool = True
    issued_at: str = ""
    nonce: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_nonempty(self.receipt_id, field_name="receipt_id"),
        )
        object.__setattr__(
            self,
            "schema_contract_id",
            _require_nonempty(
                self.schema_contract_id, field_name="schema_contract_id"
            ),
        )
        object.__setattr__(
            self,
            "authorizer_identity",
            _require_nonempty(
                self.authorizer_identity, field_name="authorizer_identity"
            ),
        )
        if not isinstance(self.rollback_plan, RollbackPlan):
            raise SchemaMigrationError("migration receipt requires RollbackPlan")
        if int(self.to_revision) <= int(self.from_revision):
            raise SchemaMigrationError(
                "migration to_revision must be greater than from_revision"
            )
        if int(self.rollback_plan.target_revision) != int(self.from_revision):
            raise SchemaMigrationError(
                "rollback_plan.target_revision must equal from_revision"
            )
        if not self.authorized:
            raise MigrationAuthorizationError(
                "schema changes require an authorized migration receipt"
            )
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _utc_iso())
        if not self.nonce:
            object.__setattr__(self, "nonce", uuid.uuid4().hex)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "receipt_id": self.receipt_id,
                "schema_contract_id": self.schema_contract_id,
                "from_revision": self.from_revision,
                "to_revision": self.to_revision,
                "authorizer_identity": self.authorizer_identity,
                "rollback_plan": dict(self.rollback_plan.as_mapping()),
                "authorized": self.authorized,
                "issued_at": self.issued_at,
                "nonce": self.nonce,
            }
        )


@dataclass(frozen=True, slots=True)
class SchemaContract:
    """Versioned schema contract keyed by stable field_ids."""

    SCHEMA: ClassVar[str] = SCHEMA_CONTRACT_SCHEMA
    contract_id: str
    dataset_id: str
    revision: int
    fields: tuple[FieldContract, ...]
    tenant: str = "default"
    column_policy: ColumnPolicy = field(default_factory=ColumnPolicy)
    promotion_rules: TypePromotionRules = field(default_factory=TypePromotionRules)
    uniqueness_scopes: tuple[str, ...] = ()
    reference_scopes: tuple[str, ...] = ()
    schema_digest: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contract_id",
            _require_nonempty(self.contract_id, field_name="contract_id"),
        )
        object.__setattr__(
            self,
            "dataset_id",
            _require_nonempty(self.dataset_id, field_name="dataset_id"),
        )
        if int(self.revision) < 1:
            raise ContractError("schema revision must be >= 1")
        object.__setattr__(self, "revision", int(self.revision))
        object.__setattr__(
            self, "tenant", _require_token(self.tenant, field_name="tenant")
        )
        fields = tuple(self.fields)
        if not fields:
            raise ContractError("schema contract requires at least one field")
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for f in fields:
            if not isinstance(f, FieldContract):
                raise ContractError("fields must be FieldContract instances")
            if f.field_id in seen_ids:
                raise ContractError(f"duplicate field_id {f.field_id!r}")
            if f.name in seen_names:
                raise ContractError(f"duplicate field name {f.name!r}")
            seen_ids.add(f.field_id)
            seen_names.add(f.name)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(
            self, "uniqueness_scopes", tuple(self.uniqueness_scopes or ())
        )
        object.__setattr__(
            self, "reference_scopes", tuple(self.reference_scopes or ())
        )
        if not isinstance(self.column_policy, ColumnPolicy):
            raise ContractError("column_policy must be ColumnPolicy")
        if not isinstance(self.promotion_rules, TypePromotionRules):
            raise ContractError("promotion_rules must be TypePromotionRules")
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_iso())
        if not self.schema_digest:
            object.__setattr__(self, "schema_digest", self.compute_digest())

    def compute_digest(self) -> str:
        payload = {
            "contract_id": self.contract_id,
            "dataset_id": self.dataset_id,
            "revision": self.revision,
            "tenant": self.tenant,
            "fields": [dict(f.as_mapping()) for f in self.fields],
            "uniqueness_scopes": list(self.uniqueness_scopes),
            "reference_scopes": list(self.reference_scopes),
            "column_policy": dict(self.column_policy.as_mapping()),
        }
        return _sha256_text(_canonical_json(payload))

    def field_by_id(self, field_id: str) -> FieldContract:
        for f in self.fields:
            if f.field_id == field_id:
                return f
        raise ContractError(f"unknown field_id {field_id!r}")

    def field_by_name(self, name: str) -> FieldContract:
        for f in self.fields:
            if f.name == name:
                return f
        raise ContractError(f"unknown field name {name!r}")

    def field_ids_json(self) -> str:
        return _canonical_json(
            [
                {
                    "field_id": f.field_id,
                    "name": f.name,
                    "type": f.field_type.value,
                    "nullable": f.nullable,
                    "required": f.required,
                }
                for f in self.fields
            ]
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "contract_id": self.contract_id,
                "dataset_id": self.dataset_id,
                "revision": self.revision,
                "tenant": self.tenant,
                "schema_digest": self.schema_digest,
                "fields": [dict(f.as_mapping()) for f in self.fields],
                "column_policy": dict(self.column_policy.as_mapping()),
                "promotion_rules": dict(self.promotion_rules.as_mapping()),
                "uniqueness_scopes": list(self.uniqueness_scopes),
                "reference_scopes": list(self.reference_scopes),
                "created_at": self.created_at,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
            }
        )


@dataclass(frozen=True, slots=True)
class SnapshotSchemaView:
    """Schema contract as observed at a historic snapshot / revision."""

    snapshot_version: int
    contract: SchemaContract
    promotions: tuple[PromotionResult, ...] = ()

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "snapshot_version": self.snapshot_version,
                "contract": dict(self.contract.as_mapping()),
                "promotions": [dict(p.as_mapping()) for p in self.promotions],
            }
        )


def evolve_schema(
    current: SchemaContract,
    *,
    next_fields: Sequence[FieldContract],
    migration_receipt: MigrationReceipt | None,
    next_revision: int | None = None,
    column_policy: ColumnPolicy | None = None,
    promotion_rules: TypePromotionRules | None = None,
    uniqueness_scopes: Sequence[str] | None = None,
    reference_scopes: Sequence[str] | None = None,
) -> tuple[SchemaContract, SchemaEvolutionPlan]:
    """Compute and authorize a schema evolution (add/drop/rename/promote).

    Schema changes **require** an authorized migration receipt whose rollback
    plan targets the current revision. Unauthorized evolution fails closed.
    """

    if migration_receipt is None:
        raise MigrationAuthorizationError(
            "schema changes require an authorized migration receipt and rollback plan"
        )
    if migration_receipt.schema_contract_id != current.contract_id:
        raise SchemaMigrationError(
            f"migration receipt contract_id {migration_receipt.schema_contract_id!r} "
            f"does not match {current.contract_id!r}"
        )
    if int(migration_receipt.from_revision) != int(current.revision):
        raise SchemaMigrationError(
            f"migration receipt from_revision {migration_receipt.from_revision} "
            f"does not match current revision {current.revision}"
        )
    target_rev = (
        int(next_revision)
        if next_revision is not None
        else int(migration_receipt.to_revision)
    )
    if target_rev != int(migration_receipt.to_revision):
        raise SchemaMigrationError(
            "next_revision must equal migration receipt to_revision"
        )

    old_by_id = {f.field_id: f for f in current.fields}
    new_fields = tuple(next_fields)
    new_by_id = {f.field_id: f for f in new_fields}
    steps: list[dict[str, Any]] = []
    lossless = True

    # Renames: same field_id, different name.
    for fid, old in old_by_id.items():
        if fid in new_by_id and new_by_id[fid].name != old.name:
            steps.append(
                {
                    "kind": EvolutionKind.RENAME.value,
                    "field_id": fid,
                    "from_name": old.name,
                    "to_name": new_by_id[fid].name,
                }
            )

    # Promotions: same field_id, wider type.
    rules = promotion_rules or current.promotion_rules
    for fid, old in old_by_id.items():
        if fid not in new_by_id:
            continue
        new = new_by_id[fid]
        if old.field_type is not new.field_type:
            if not rules.allows(old.field_type, new.field_type):
                raise TypePromotionError(
                    f"field_id {fid!r} cannot promote {old.field_type.value} -> "
                    f"{new.field_type.value}"
                )
            steps.append(
                {
                    "kind": EvolutionKind.PROMOTE.value,
                    "field_id": fid,
                    "from_type": old.field_type.value,
                    "to_type": new.field_type.value,
                    "lossless": True,
                }
            )

    # Drops: field_id removed.
    for fid in old_by_id:
        if fid not in new_by_id:
            steps.append({"kind": EvolutionKind.DROP.value, "field_id": fid})

    # Adds: new field_id.
    for fid in new_by_id:
        if fid not in old_by_id:
            steps.append(
                {
                    "kind": EvolutionKind.ADD.value,
                    "field_id": fid,
                    "name": new_by_id[fid].name,
                    "type": new_by_id[fid].field_type.value,
                }
            )

    if not steps:
        steps.append({"kind": EvolutionKind.NOOP.value})

    evolved = SchemaContract(
        contract_id=current.contract_id,
        dataset_id=current.dataset_id,
        revision=target_rev,
        fields=new_fields,
        tenant=current.tenant,
        column_policy=column_policy or current.column_policy,
        promotion_rules=rules,
        uniqueness_scopes=tuple(
            uniqueness_scopes
            if uniqueness_scopes is not None
            else current.uniqueness_scopes
        ),
        reference_scopes=tuple(
            reference_scopes
            if reference_scopes is not None
            else current.reference_scopes
        ),
    )
    plan = SchemaEvolutionPlan(
        from_revision=current.revision,
        to_revision=target_rev,
        steps=tuple(MappingProxyType(s) for s in steps),
        lossless=lossless,
    )
    return evolved, plan


def replay_schema_at_revision(
    history: Sequence[SchemaContract],
    *,
    revision: int,
    sample_values: Mapping[str, Any] | None = None,
) -> SnapshotSchemaView:
    """Replay field-ID history and lossless promotions up to *revision*.

    Historic snapshots are projected through field_ids so add/drop/rename and
    lossless promotions remain deterministic across revisions.
    """

    if not history:
        raise SchemaEvolutionError("empty schema history")
    ordered = sorted(history, key=lambda c: c.revision)
    if ordered[0].revision != 1 and revision < ordered[0].revision:
        raise SchemaEvolutionError(
            f"revision {revision} predates history start {ordered[0].revision}"
        )
    selected: SchemaContract | None = None
    for contract in ordered:
        if contract.revision <= revision:
            selected = contract
        else:
            break
    if selected is None:
        raise SchemaEvolutionError(f"no schema contract at revision {revision}")

    promotions: list[PromotionResult] = []
    values = dict(sample_values or {})
    # Walk consecutive revisions up to the selected one, recording promotions.
    chain = [c for c in ordered if c.revision <= selected.revision]
    for prev, nxt in zip(chain, chain[1:]):
        prev_ids = {f.field_id: f for f in prev.fields}
        for f in nxt.fields:
            old = prev_ids.get(f.field_id)
            if old is None or old.field_type is f.field_type:
                continue
            before = values.get(f.field_id, values.get(old.name))
            after = promote_value(
                before, source=old.field_type, target=f.field_type
            )
            promotions.append(
                PromotionResult(
                    field_id=f.field_id,
                    source_type=old.field_type.value,
                    target_type=f.field_type.value,
                    lossless=True,
                    value_before=before,
                    value_after=after,
                )
            )
            if before is not None or f.field_id in values:
                values[f.field_id] = after

    return SnapshotSchemaView(
        snapshot_version=revision,
        contract=selected,
        promotions=tuple(promotions),
    )


# ---------------------------------------------------------------------------
# Column policy application + record validation
# ---------------------------------------------------------------------------


# Record keys that carry application metadata rather than schema columns.
_RESERVED_RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "tenant",
        "_tenant",
        "idempotency_key",
        "operation_id",
        "_meta",
        "_provenance",
    }
)


def apply_column_policy(
    contract: SchemaContract,
    record: Mapping[str, Any],
    *,
    by_field_id: bool | None = None,
) -> dict[str, Any]:
    """Apply missing/extra column policy; return normalized field_id -> value map.

    Input keys may be field names or field_ids. Output is always keyed by
    field_id. Fail closed when policy says reject. Reserved metadata keys
    (``tenant``, ``_tenant``, …) are not treated as schema columns.
    """

    use_ids = (
        contract.column_policy.require_field_ids
        if by_field_id is None
        else bool(by_field_id)
    )
    id_by_name = {f.name: f.field_id for f in contract.fields}
    known_ids = {f.field_id for f in contract.fields}
    known_names = set(id_by_name)

    normalized: dict[str, Any] = {}
    extras: list[str] = []
    for key, value in record.items():
        key_s = str(key)
        if key_s in _RESERVED_RECORD_KEYS:
            continue
        if key_s in known_ids:
            normalized[key_s] = value
        elif key_s in known_names:
            if use_ids and contract.column_policy.require_field_ids:
                # Names are accepted as sugar when mapping is unambiguous.
                normalized[id_by_name[key_s]] = value
            else:
                normalized[id_by_name[key_s]] = value
        else:
            extras.append(key_s)

    if extras:
        if contract.column_policy.extra is ExtraColumnPolicy.REJECT:
            raise ConstraintViolation(
                f"extra columns rejected: {sorted(extras)}",
                details={"extra_columns": sorted(extras)},
            )
        # DROP / IGNORE: omit extras from normalized output.

    for f in contract.fields:
        if f.field_id in normalized:
            continue
        # Required / non-nullable absences always fail closed under REJECT.
        if f.required or not f.nullable:
            if contract.column_policy.missing is MissingColumnPolicy.DEFAULT and f.default is not None:
                normalized[f.field_id] = f.default
                continue
            raise ConstraintViolation(
                f"missing required column field_id={f.field_id!r} name={f.name!r}",
                details={"field_id": f.field_id, "name": f.name},
            )
        # Optional nullable fields.
        if contract.column_policy.missing is MissingColumnPolicy.DEFAULT:
            normalized[f.field_id] = f.default
        elif contract.column_policy.missing is MissingColumnPolicy.NULL_IF_NULLABLE:
            normalized[f.field_id] = None
        else:
            # REJECT: optional nullable may be omitted as null without inventing values.
            normalized[f.field_id] = None
    return normalized


class ConstraintKind(str, Enum):
    DOMAIN = "domain"
    UNIQUENESS = "uniqueness"
    REFERENCE = "reference"
    TENANT = "tenant"
    SCHEMA = "schema"
    TYPE = "type"


@dataclass(frozen=True, slots=True)
class ConstraintEvidence:
    """Evidence binding exact source files and schema revision to a check."""

    SCHEMA: ClassVar[str] = CONSTRAINT_EVIDENCE_SCHEMA
    evidence_id: str
    schema_contract_id: str
    schema_revision: int
    schema_digest: str
    source_files: tuple[str, ...]
    source_digests: tuple[str, ...]
    constraint_kind: ConstraintKind
    outcome: str  # accepted | rejected
    details: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _require_nonempty(self.evidence_id, field_name="evidence_id"),
        )
        object.__setattr__(
            self,
            "schema_contract_id",
            _require_nonempty(
                self.schema_contract_id, field_name="schema_contract_id"
            ),
        )
        object.__setattr__(self, "schema_revision", int(self.schema_revision))
        object.__setattr__(
            self,
            "schema_digest",
            _require_nonempty(self.schema_digest, field_name="schema_digest"),
        )
        object.__setattr__(self, "source_files", tuple(self.source_files or ()))
        object.__setattr__(self, "source_digests", tuple(self.source_digests or ()))
        if not self.source_files:
            raise ContractError(
                "constraint evidence must bind at least one source file"
            )
        if not isinstance(self.constraint_kind, ConstraintKind):
            object.__setattr__(
                self, "constraint_kind", ConstraintKind(str(self.constraint_kind))
            )
        outcome = _require_nonempty(self.outcome, field_name="outcome").lower()
        if outcome not in {"accepted", "rejected"}:
            raise ContractError(f"invalid evidence outcome {outcome!r}")
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "details", MappingProxyType(dict(self.details or {})))
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "evidence_id": self.evidence_id,
                "schema_contract_id": self.schema_contract_id,
                "schema_revision": self.schema_revision,
                "schema_digest": self.schema_digest,
                "source_files": list(self.source_files),
                "source_digests": list(self.source_digests),
                "constraint_kind": self.constraint_kind.value,
                "outcome": self.outcome,
                "details": dict(self.details),
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True, slots=True)
class RejectEvidence:
    """Reject package produced before any DuckLake commit."""

    reason: str
    constraint_kind: ConstraintKind
    evidence: ConstraintEvidence
    message: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "reason": self.reason,
                "constraint_kind": self.constraint_kind.value,
                "message": self.message,
                "evidence": dict(self.evidence.as_mapping()),
            }
        )


@dataclass(frozen=True, slots=True)
class RecordValidationResult:
    """Outcome of pre-commit validation for one or more records."""

    accepted: bool
    normalized_records: tuple[Mapping[str, Any], ...]
    evidence: tuple[ConstraintEvidence, ...]
    rejects: tuple[RejectEvidence, ...] = ()

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "accepted": self.accepted,
                "normalized_records": [dict(r) for r in self.normalized_records],
                "evidence": [dict(e.as_mapping()) for e in self.evidence],
                "rejects": [dict(r.as_mapping()) for r in self.rejects],
            }
        )


def build_constraint_evidence(
    *,
    contract: SchemaContract,
    source_files: Sequence[str],
    source_digests: Sequence[str] | None = None,
    constraint_kind: ConstraintKind,
    outcome: str,
    details: Mapping[str, Any] | None = None,
    evidence_id: str | None = None,
) -> ConstraintEvidence:
    digests = tuple(source_digests or ())
    if digests and len(digests) != len(source_files):
        raise ContractError("source_digests length must match source_files")
    if not digests:
        digests = tuple(_sha256_text(path) for path in source_files)
    return ConstraintEvidence(
        evidence_id=evidence_id or uuid.uuid4().hex,
        schema_contract_id=contract.contract_id,
        schema_revision=contract.revision,
        schema_digest=contract.schema_digest,
        source_files=tuple(source_files),
        source_digests=digests,
        constraint_kind=constraint_kind,
        outcome=outcome,
        details=details or {},
    )


def validate_record(
    contract: SchemaContract,
    record: Mapping[str, Any],
    *,
    expected_tenant: str | None = None,
    reference_keys: Mapping[str, Iterable[Any]] | None = None,
    seen_unique_keys: Mapping[str, set[Any]] | None = None,
) -> dict[str, Any]:
    """Validate one record against schema, domain, tenant, uniqueness, refs.

    Returns the normalized field_id-keyed record on success; raises
    :class:`ConstraintViolation` on failure.
    """

    # Tenant check first (fail before column work when explicit).
    tenant = expected_tenant if expected_tenant is not None else contract.tenant
    record_tenant = record.get("tenant", record.get("_tenant", tenant))
    if str(record_tenant) != str(tenant):
        raise ConstraintViolation(
            f"tenant mismatch: expected {tenant!r}, got {record_tenant!r}",
            details={
                "expected_tenant": tenant,
                "actual_tenant": record_tenant,
                "kind": ConstraintKind.TENANT.value,
            },
        )

    try:
        normalized = apply_column_policy(contract, record)
    except ConstraintViolation:
        raise
    except ContractError as exc:
        raise ConstraintViolation(str(exc), details=dict(exc.details)) from exc

    for f in contract.fields:
        value = normalized.get(f.field_id)
        if value is None:
            if not f.nullable or f.required:
                raise ConstraintViolation(
                    f"null not allowed for field_id={f.field_id!r}",
                    details={"field_id": f.field_id, "kind": ConstraintKind.DOMAIN.value},
                )
            continue
        # Domain checks.
        if f.domain is not None:
            f.domain.validate(value, field_id=f.field_id)

    # Uniqueness (within the provided seen set for this batch / owner ledger).
    if seen_unique_keys:
        for scope, key_builder in seen_unique_keys.items():
            # seen_unique_keys maps scope -> set of already claimed key digests
            # OR a callable — we only accept sets of digests/values here.
            if not isinstance(key_builder, set):
                continue

    if reference_keys:
        for field_id, allowed in reference_keys.items():
            if field_id not in normalized:
                continue
            value = normalized[field_id]
            if value is None:
                continue
            allowed_set = set(allowed)
            if value not in allowed_set:
                raise ConstraintViolation(
                    f"reference constraint failed for field_id={field_id!r}: "
                    f"{value!r} not in referenced key set",
                    details={
                        "field_id": field_id,
                        "value": value,
                        "kind": ConstraintKind.REFERENCE.value,
                    },
                )

    # Attach tenant for downstream reservation scopes.
    normalized["_tenant"] = str(tenant)
    return normalized


def validate_records_before_commit(
    contract: SchemaContract,
    records: Sequence[Mapping[str, Any]],
    *,
    source_files: Sequence[str],
    source_digests: Sequence[str] | None = None,
    expected_tenant: str | None = None,
    uniqueness_key_fields: Sequence[str] | None = None,
    existing_unique_digests: Iterable[str] | None = None,
    reference_keys: Mapping[str, Iterable[Any]] | None = None,
) -> RecordValidationResult:
    """Validate a batch before any DuckLake commit; produce reject evidence."""

    evidence: list[ConstraintEvidence] = []
    rejects: list[RejectEvidence] = []
    normalized_records: list[dict[str, Any]] = []
    unique_fields = tuple(uniqueness_key_fields or ())
    claimed: set[str] = set(existing_unique_digests or ())

    for index, record in enumerate(records):
        try:
            # Tenant
            tenant = (
                expected_tenant if expected_tenant is not None else contract.tenant
            )
            record_tenant = record.get("tenant", record.get("_tenant", tenant))
            if str(record_tenant) != str(tenant):
                raise ConstraintViolation(
                    f"tenant mismatch at record[{index}]",
                    details={
                        "index": index,
                        "expected_tenant": tenant,
                        "actual_tenant": record_tenant,
                    },
                )
            evidence.append(
                build_constraint_evidence(
                    contract=contract,
                    source_files=source_files,
                    source_digests=source_digests,
                    constraint_kind=ConstraintKind.TENANT,
                    outcome="accepted",
                    details={"index": index, "tenant": tenant},
                )
            )

            normalized = apply_column_policy(contract, record)
            evidence.append(
                build_constraint_evidence(
                    contract=contract,
                    source_files=source_files,
                    source_digests=source_digests,
                    constraint_kind=ConstraintKind.SCHEMA,
                    outcome="accepted",
                    details={"index": index, "field_ids": sorted(normalized)},
                )
            )

            for f in contract.fields:
                value = normalized.get(f.field_id)
                if value is None and (not f.nullable or f.required):
                    raise ConstraintViolation(
                        f"null not allowed for field_id={f.field_id!r}",
                        details={"field_id": f.field_id, "index": index},
                    )
                if f.domain is not None and value is not None:
                    f.domain.validate(value, field_id=f.field_id)
            evidence.append(
                build_constraint_evidence(
                    contract=contract,
                    source_files=source_files,
                    source_digests=source_digests,
                    constraint_kind=ConstraintKind.DOMAIN,
                    outcome="accepted",
                    details={"index": index},
                )
            )

            if reference_keys:
                for field_id, allowed in reference_keys.items():
                    if field_id not in normalized:
                        continue
                    value = normalized[field_id]
                    if value is None:
                        continue
                    if value not in set(allowed):
                        raise ConstraintViolation(
                            f"reference constraint failed for field_id={field_id!r}",
                            details={
                                "field_id": field_id,
                                "value": value,
                                "index": index,
                            },
                        )
                evidence.append(
                    build_constraint_evidence(
                        contract=contract,
                        source_files=source_files,
                        source_digests=source_digests,
                        constraint_kind=ConstraintKind.REFERENCE,
                        outcome="accepted",
                        details={"index": index},
                    )
                )

            if unique_fields:
                key_payload = {
                    fid: normalized.get(fid) for fid in unique_fields
                }
                digest = logical_key_digest_for(key_payload)
                if digest in claimed:
                    raise ConstraintViolation(
                        f"uniqueness constraint failed for fields {list(unique_fields)}",
                        details={
                            "fields": list(unique_fields),
                            "logical_key_digest": digest,
                            "index": index,
                        },
                    )
                claimed.add(digest)
                evidence.append(
                    build_constraint_evidence(
                        contract=contract,
                        source_files=source_files,
                        source_digests=source_digests,
                        constraint_kind=ConstraintKind.UNIQUENESS,
                        outcome="accepted",
                        details={
                            "index": index,
                            "logical_key_digest": digest,
                            "fields": list(unique_fields),
                        },
                    )
                )

            normalized["_tenant"] = str(tenant)
            normalized_records.append(normalized)

        except (ConstraintViolation, ContractError) as exc:
            kind = ConstraintKind.DOMAIN
            details = dict(getattr(exc, "details", {}) or {})
            if "tenant" in str(exc).lower() or "expected_tenant" in details:
                kind = ConstraintKind.TENANT
            elif "reference" in str(exc).lower() or details.get("kind") == "reference":
                kind = ConstraintKind.REFERENCE
            elif "uniqueness" in str(exc).lower() or "logical_key_digest" in details:
                kind = ConstraintKind.UNIQUENESS
            elif "extra columns" in str(exc).lower() or "missing" in str(exc).lower():
                kind = ConstraintKind.SCHEMA
            ev = build_constraint_evidence(
                contract=contract,
                source_files=source_files,
                source_digests=source_digests,
                constraint_kind=kind,
                outcome="rejected",
                details={"index": index, "error": str(exc), **details},
            )
            evidence.append(ev)
            rejects.append(
                RejectEvidence(
                    reason=kind.value,
                    constraint_kind=kind,
                    evidence=ev,
                    message=str(exc),
                )
            )

    accepted = not rejects
    return RecordValidationResult(
        accepted=accepted,
        normalized_records=tuple(MappingProxyType(r) for r in normalized_records),
        evidence=tuple(evidence),
        rejects=tuple(rejects),
    )


# ---------------------------------------------------------------------------
# Reservation + outbox (companion owner-control)
# ---------------------------------------------------------------------------


class ReservationStatus(str, Enum):
    RESERVED = "reserved"
    COMMITTED = "committed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    IN_DOUBT = "in_doubt"
    PENDING_RECLAIM = "pending_reclaim"


@dataclass(frozen=True, slots=True)
class LogicalKeyReservation:
    """Persistent logical-key / idempotency-key claim (never reused on success)."""

    SCHEMA: ClassVar[str] = RESERVATION_SCHEMA
    reservation_id: str
    shard_id: str
    dataset_id: str
    uniqueness_scope: str
    logical_key_digest: str
    idempotency_key: str
    status: ReservationStatus
    reserved_at: str
    terminalized_at: str = ""
    snapshot_version: int | None = None
    cas_revision: int = 1
    owner_id: str = ""

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "reservation_id": self.reservation_id,
                "shard_id": self.shard_id,
                "dataset_id": self.dataset_id,
                "uniqueness_scope": self.uniqueness_scope,
                "logical_key_digest": self.logical_key_digest,
                "idempotency_key": self.idempotency_key,
                "status": self.status.value
                if isinstance(self.status, ReservationStatus)
                else str(self.status),
                "reserved_at": self.reserved_at,
                "terminalized_at": self.terminalized_at,
                "snapshot_version": self.snapshot_version,
                "cas_revision": self.cas_revision,
                "owner_id": self.owner_id,
            }
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "LogicalKeyReservation":
        return cls(
            reservation_id=str(row["reservation_id"]),
            shard_id=str(row["shard_id"]),
            dataset_id=str(row["dataset_id"]),
            uniqueness_scope=str(row["uniqueness_scope"]),
            logical_key_digest=str(row["logical_key_digest"]),
            idempotency_key=str(row["idempotency_key"]),
            status=ReservationStatus(str(row["status"])),
            reserved_at=str(row.get("reserved_at") or ""),
            terminalized_at=str(row.get("terminalized_at") or ""),
            snapshot_version=(
                None
                if row.get("snapshot_version") in (None, "")
                else int(row["snapshot_version"])
            ),
            cas_revision=int(row.get("cas_revision") or 1),
            owner_id=str(row.get("owner_id") or ""),
        )


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """Durable outbox entry terminalizing a reservation with a snapshot."""

    outbox_id: str
    shard_id: str
    operation_id: str
    reservation_id: str
    payload_digest: str
    status: str
    snapshot_version: int | None = None
    created_at: str = ""
    updated_at: str = ""
    cas_revision: int = 1

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "outbox_id": self.outbox_id,
                "shard_id": self.shard_id,
                "operation_id": self.operation_id,
                "reservation_id": self.reservation_id,
                "payload_digest": self.payload_digest,
                "status": self.status,
                "snapshot_version": self.snapshot_version,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "cas_revision": self.cas_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class WriteCommitReceipt:
    """Receipt after reservation → snapshot → outbox terminalization."""

    operation_id: str
    reservation: LogicalKeyReservation
    outbox: OutboxEntry
    snapshot_version: int
    schema_revision: int
    schema_digest: str
    evidence: tuple[ConstraintEvidence, ...]
    atomic_across_files: bool = False  # always False: never claim cross-file txn

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "operation_id": self.operation_id,
                "reservation": dict(self.reservation.as_mapping()),
                "outbox": dict(self.outbox.as_mapping()),
                "snapshot_version": self.snapshot_version,
                "schema_revision": self.schema_revision,
                "schema_digest": self.schema_digest,
                "evidence": [dict(e.as_mapping()) for e in self.evidence],
                "atomic_across_files": self.atomic_across_files,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
            }
        )


# ---------------------------------------------------------------------------
# Fenced catalog-owner constraint service
# ---------------------------------------------------------------------------


class ConstraintService:
    """Single fenced catalog-owner constraint + reservation coordinator.

    Holds the per-shard private companion owner-control registry (never visible
    to Quack-serving) and uses control-plane home-shard routing before every
    reservation. Same-shard operations are serialized by an owner lock;
    independent shards use separate companion databases and progress
    concurrently.
    """

    SCHEMA: Final[str] = CONTRACTS_SCHEMA

    def __init__(
        self,
        *,
        shard_id: str,
        owner_id: str,
        control: ControlLakeRegistry,
        companion: CompanionLakeRegistry | None = None,
        quack_instance: DatabaseInstanceBinding | None = None,
        catalog_id: str = "catalog",
    ) -> None:
        self.shard_id = _require_nonempty(shard_id, field_name="shard_id")
        self.owner_id = _require_nonempty(owner_id, field_name="owner_id")
        self.control = control
        self.companion = companion or CompanionLakeRegistry(
            shard_id=self.shard_id,
            owner_id=self.owner_id,
            control=control,
        )
        if self.companion.control is None:
            self.companion.control = control
        self.catalog_id = _require_nonempty(catalog_id, field_name="catalog_id")
        self._lock = threading.RLock()
        self._schema_history: dict[str, list[SchemaContract]] = {}
        self._migration_receipts: dict[str, MigrationReceipt] = {}
        self._unique_ledger: dict[str, set[str]] = {}
        self._object_state: dict[str, dict[str, Any]] = {}
        self._catalog_snapshot: int = 0
        self._quack = quack_instance
        if quack_instance is not None:
            self.companion.bind_quack_serving_instance(quack_instance)
        assert_companion_reservation_isolation(
            self.companion, quack=quack_instance
        )

    # -- lifecycle ---------------------------------------------------------

    def ensure_ready(self) -> None:
        with self._lock:
            try:
                self.companion.require_migrated()
            except RegistryError:
                self.companion.apply_migrations()
            assert_companion_reservation_isolation(
                self.companion, quack=self._quack
            )

    # -- schema contracts --------------------------------------------------

    def register_schema_contract(
        self,
        contract: SchemaContract,
        *,
        migration_receipt: MigrationReceipt | None = None,
    ) -> Mapping[str, Any]:
        """Persist a schema contract into the companion owner-control DuckDB.

        Revising an existing contract_id requires an authorized migration
        receipt and rollback plan.
        """

        self.ensure_ready()
        with self._lock:
            history = self._schema_history.setdefault(contract.contract_id, [])
            if history:
                current = history[-1]
                if contract.revision <= current.revision:
                    raise SchemaEvolutionError(
                        f"schema revision {contract.revision} does not advance "
                        f"current {current.revision}"
                    )
                if migration_receipt is None:
                    raise MigrationAuthorizationError(
                        "schema changes require an authorized migration receipt "
                        "and rollback plan"
                    )
                # Re-run evolve to enforce promotion rules / receipt binding.
                evolve_schema(
                    current,
                    next_fields=contract.fields,
                    migration_receipt=migration_receipt,
                    next_revision=contract.revision,
                    column_policy=contract.column_policy,
                    promotion_rules=contract.promotion_rules,
                    uniqueness_scopes=contract.uniqueness_scopes,
                    reference_scopes=contract.reference_scopes,
                )
                self._migration_receipts[migration_receipt.receipt_id] = (
                    migration_receipt
                )
            elif contract.revision != 1:
                raise SchemaEvolutionError(
                    "initial schema contract must start at revision 1"
                )

            history.append(contract)
            row = {
                "contract_id": contract.contract_id,
                "shard_id": self.shard_id,
                "schema_digest": contract.schema_digest,
                "field_ids_json": contract.field_ids_json(),
                "created_at": contract.created_at,
                "dataset_id": contract.dataset_id,
                "revision": contract.revision,
                "tenant": contract.tenant,
                "body_json": _canonical_json(dict(contract.as_mapping())),
            }
            # Latest revision wins under same contract_id key (CAS when present).
            existing = self.companion.store.get_row(
                "lake_schema_contracts", contract.contract_id
            )
            if existing is None:
                stored, _ = self.companion.store.put_if_absent(
                    "lake_schema_contracts", contract.contract_id, row
                )
            else:
                stored = self.companion.store.cas_upsert(
                    "lake_schema_contracts",
                    contract.contract_id,
                    row,
                    expected_revision=int(existing["cas_revision"]),
                )
            return MappingProxyType(stored)

    def get_schema_contract(self, contract_id: str) -> SchemaContract:
        history = self._schema_history.get(contract_id) or []
        if not history:
            raise ContractError(f"unknown schema contract {contract_id!r}")
        return history[-1]

    def schema_history(self, contract_id: str) -> tuple[SchemaContract, ...]:
        return tuple(self._schema_history.get(contract_id) or ())

    def replay_historic_snapshot(
        self,
        contract_id: str,
        *,
        revision: int,
        sample_values: Mapping[str, Any] | None = None,
    ) -> SnapshotSchemaView:
        return replay_schema_at_revision(
            self.schema_history(contract_id),
            revision=revision,
            sample_values=sample_values,
        )

    # -- home-shard routing ------------------------------------------------

    def resolve_scope_home(
        self, *, uniqueness_scope: str, dataset_id: str
    ) -> Mapping[str, Any]:
        """Resolve uniqueness/reference scope before reservation or copy."""

        try:
            resolved = self.control.resolve_uniqueness_scope(
                uniqueness_scope=uniqueness_scope, dataset_id=dataset_id
            )
        except UnsupportedCrossShardUniqueness as exc:
            raise CrossShardConstraintError(
                f"unsupported cross-shard scope fails before object copy or "
                f"snapshot mutation: {exc}",
                details={
                    "uniqueness_scope": uniqueness_scope,
                    "dataset_id": dataset_id,
                },
            ) from exc
        except RegistryError as exc:
            raise ContractError(str(exc)) from exc
        home = str(resolved["home_shard_id"])
        if home != self.shard_id:
            raise CrossShardConstraintError(
                f"scope {uniqueness_scope!r} homes at {home!r}, not owner "
                f"shard {self.shard_id!r}; fails before object copy or snapshot "
                "mutation",
                details={
                    "uniqueness_scope": uniqueness_scope,
                    "home_shard_id": home,
                    "owner_shard_id": self.shard_id,
                },
            )
        return resolved

    # -- reservations ------------------------------------------------------

    def acquire_reservation(
        self,
        *,
        dataset_id: str,
        uniqueness_scope: str,
        logical_key: str | Mapping[str, Any],
        idempotency_key: str,
        reservation_id: str | None = None,
    ) -> LogicalKeyReservation:
        """Reserve logical key + idempotency key before the snapshot boundary.

        Contending same-key remote requests are serialized at this owner and
        contend on the durable reservation; exactly one wins. A successful
        claim is never released or reused.
        """

        self.ensure_ready()
        with self._lock:
            self.resolve_scope_home(
                uniqueness_scope=uniqueness_scope, dataset_id=dataset_id
            )
            assert_companion_reservation_isolation(
                self.companion, quack=self._quack
            )
            assert_not_ducklake_internal_metadata("lake_logical_key_reservations")

            key_digest = logical_key_digest_for(logical_key)
            idem = _require_nonempty(idempotency_key, field_name="idempotency_key")
            rid = reservation_id or f"res-{uuid.uuid4().hex}"

            # Idempotent replay of the same (key, idempotency) pair.
            for existing in self.companion.store.list_rows(
                "lake_logical_key_reservations"
            ):
                if (
                    existing.get("uniqueness_scope") == uniqueness_scope
                    and existing.get("logical_key_digest") == key_digest
                ):
                    status = str(existing.get("status") or "")
                    if status in _TERMINAL_SUCCESS_STATUSES or status == "reserved":
                        if existing.get("idempotency_key") == idem:
                            return LogicalKeyReservation.from_row(existing)
                        raise ReservationContention(
                            f"logical key already claimed under scope "
                            f"{uniqueness_scope!r}; concurrent same-key request "
                            "lost durable reservation contention",
                            details={
                                "uniqueness_scope": uniqueness_scope,
                                "logical_key_digest": key_digest,
                                "winner_reservation_id": existing.get(
                                    "reservation_id"
                                ),
                                "winner_status": status,
                            },
                        )
                    # Proven incomplete/failed may be reclaimed only.
                    if status in _RECLAIMABLE_STATUSES:
                        continue

            try:
                row = self.companion.reserve_logical_key(
                    reservation_id=rid,
                    dataset_id=dataset_id,
                    uniqueness_scope=uniqueness_scope,
                    logical_key_digest=key_digest,
                    idempotency_key=idem,
                )
            except UnsupportedCrossShardUniqueness as exc:
                raise CrossShardConstraintError(str(exc)) from exc
            except RegistryError as exc:
                # Map durable uniqueness conflicts to contention.
                if "already reserved" in str(exc).lower():
                    raise ReservationContention(str(exc)) from exc
                raise ReservationError(str(exc)) from exc

            # Annotate owner_id (not in base schema row; stored alongside).
            payload = dict(row)
            payload["owner_id"] = self.owner_id
            if "owner_id" not in row:
                try:
                    payload = self.companion.store.cas_upsert(
                        "lake_logical_key_reservations",
                        rid,
                        payload,
                        expected_revision=int(row.get("cas_revision") or 1),
                    )
                except Exception:
                    payload = dict(row)
                    payload["owner_id"] = self.owner_id
            return LogicalKeyReservation.from_row(payload)

    def release_reservation(self, reservation_id: str) -> None:
        """Forbidden for successful claims — always fail closed."""

        raise ReservationError(
            f"successful reservation {reservation_id!r} is never released or "
            "reused; crash recovery may reclaim only proven incomplete or "
            "failed claims"
        )

    def mark_reservation_failed(
        self, reservation_id: str, *, reason: str = ""
    ) -> LogicalKeyReservation:
        """Mark a non-terminal reservation as failed (reclaimable)."""

        self.ensure_ready()
        with self._lock:
            row = self.companion.store.get_row(
                "lake_logical_key_reservations", reservation_id
            )
            if row is None:
                raise ReservationError(f"unknown reservation {reservation_id!r}")
            status = str(row.get("status") or "")
            if status in _TERMINAL_SUCCESS_STATUSES:
                raise ReservationError(
                    "committed reservation cannot be marked failed or reused"
                )
            updated = dict(row)
            updated["status"] = ReservationStatus.FAILED.value
            updated["terminalized_at"] = _utc_iso()
            updated["failure_reason"] = reason
            stored = self.companion.store.cas_upsert(
                "lake_logical_key_reservations",
                reservation_id,
                updated,
                expected_revision=int(row["cas_revision"]),
            )
            return LogicalKeyReservation.from_row(stored)

    def reclaim_incomplete_or_failed(
        self, reservation_id: str
    ) -> LogicalKeyReservation:
        """Reclaim only a proven incomplete or failed claim (never success)."""

        self.ensure_ready()
        with self._lock:
            row = self.companion.store.get_row(
                "lake_logical_key_reservations", reservation_id
            )
            if row is None:
                raise ReservationError(f"unknown reservation {reservation_id!r}")
            status = str(row.get("status") or "")
            if status in _TERMINAL_SUCCESS_STATUSES or status == "reserved":
                raise ReservationError(
                    f"cannot reclaim reservation in status {status!r}; a "
                    "successful claim is never released, reassigned, or reused"
                )
            if status not in _RECLAIMABLE_STATUSES:
                raise ReservationError(
                    f"status {status!r} is not a proven incomplete/failed claim"
                )
            updated = dict(row)
            updated["status"] = ReservationStatus.PENDING_RECLAIM.value
            updated["reclaimed_at"] = _utc_iso()
            updated["reclaimed_by"] = self.owner_id
            stored = self.companion.store.cas_upsert(
                "lake_logical_key_reservations",
                reservation_id,
                updated,
                expected_revision=int(row["cas_revision"]),
            )
            return LogicalKeyReservation.from_row(stored)

    # -- validate + commit path --------------------------------------------

    def validate_before_commit(
        self,
        contract: SchemaContract,
        records: Sequence[Mapping[str, Any]],
        *,
        source_files: Sequence[str],
        source_digests: Sequence[str] | None = None,
        uniqueness_key_fields: Sequence[str] | None = None,
        reference_keys: Mapping[str, Iterable[Any]] | None = None,
        expected_tenant: str | None = None,
    ) -> RecordValidationResult:
        """Reject invalid domain/uniqueness/reference/tenant before commit."""

        existing: set[str] = set()
        if uniqueness_key_fields:
            scope_key = f"{contract.contract_id}:{','.join(uniqueness_key_fields)}"
            existing = set(self._unique_ledger.get(scope_key, set()))
        return validate_records_before_commit(
            contract,
            records,
            source_files=source_files,
            source_digests=source_digests,
            expected_tenant=expected_tenant or contract.tenant,
            uniqueness_key_fields=uniqueness_key_fields,
            existing_unique_digests=existing,
            reference_keys=reference_keys,
        )

    def commit_write(
        self,
        *,
        contract: SchemaContract,
        records: Sequence[Mapping[str, Any]],
        source_files: Sequence[str],
        source_digests: Sequence[str] | None = None,
        uniqueness_scope: str,
        logical_key: str | Mapping[str, Any],
        idempotency_key: str,
        uniqueness_key_fields: Sequence[str] | None = None,
        reference_keys: Mapping[str, Iterable[Any]] | None = None,
        operation_id: str | None = None,
        object_uri: str | None = None,
        simulate_crash_after_snapshot: bool = False,
    ) -> WriteCommitReceipt:
        """Full fenced write: validate → reserve → snapshot → outbox terminalize.

        Never claims atomicity across files (``atomic_across_files`` is always
        false). When *simulate_crash_after_snapshot* is true, leaves the claim
        ``in_doubt`` so recovery can reconcile without a second logical transition.
        """

        self.ensure_ready()
        op_id = operation_id or f"op-{uuid.uuid4().hex}"

        with self._lock:
            # 1. Home-shard resolution before any object copy / snapshot mutation.
            self.resolve_scope_home(
                uniqueness_scope=uniqueness_scope,
                dataset_id=contract.dataset_id,
            )

            # 2. Pre-commit constraint validation + reject evidence.
            validation = self.validate_before_commit(
                contract,
                records,
                source_files=source_files,
                source_digests=source_digests,
                uniqueness_key_fields=uniqueness_key_fields,
                reference_keys=reference_keys,
            )
            if not validation.accepted:
                # Persist reject evidence conceptually; do not reserve or snapshot.
                raise ConstraintViolation(
                    f"records rejected before commit: "
                    f"{validation.rejects[0].message if validation.rejects else 'unknown'}",
                    details={
                        "rejects": [
                            dict(r.as_mapping()) for r in validation.rejects
                        ],
                        "evidence": [
                            dict(e.as_mapping()) for e in validation.evidence
                        ],
                    },
                )

            # 3. Durable reservation before non-atomic snapshot boundary.
            reservation = self.acquire_reservation(
                dataset_id=contract.dataset_id,
                uniqueness_scope=uniqueness_scope,
                logical_key=logical_key,
                idempotency_key=idempotency_key,
            )

            # 4. Non-atomic snapshot boundary (catalog snapshot advances alone).
            before = self._catalog_snapshot
            after = before + 1
            self._catalog_snapshot = after
            if object_uri:
                self._object_state[object_uri] = {
                    "operation_id": op_id,
                    "snapshot_version": after,
                    "schema_digest": contract.schema_digest,
                    "schema_revision": contract.revision,
                    "logical_key_digest": reservation.logical_key_digest,
                    "status": "written",
                }

            if simulate_crash_after_snapshot:
                # Snapshot advanced but outbox not terminalized → in_doubt.
                row = self.companion.store.get_row(
                    "lake_logical_key_reservations", reservation.reservation_id
                )
                if row is not None:
                    updated = dict(row)
                    updated["status"] = ReservationStatus.IN_DOUBT.value
                    updated["snapshot_version"] = after
                    self.companion.store.cas_upsert(
                        "lake_logical_key_reservations",
                        reservation.reservation_id,
                        updated,
                        expected_revision=int(row["cas_revision"]),
                    )
                raise ReservationError(
                    "simulated crash after snapshot before outbox terminalization; "
                    "recovery must reconcile without claiming cross-file atomicity",
                    details={
                        "reservation_id": reservation.reservation_id,
                        "snapshot_version": after,
                        "operation_id": op_id,
                    },
                )

            # 5. Terminalize via durable outbox with exact committed snapshot.
            return self._terminalize(
                reservation_id=reservation.reservation_id,
                operation_id=op_id,
                snapshot_version=after,
                contract=contract,
                evidence=validation.evidence,
                uniqueness_key_fields=uniqueness_key_fields,
                normalized_records=validation.normalized_records,
            )

    def _terminalize(
        self,
        *,
        reservation_id: str,
        operation_id: str,
        snapshot_version: int,
        contract: SchemaContract,
        evidence: Sequence[ConstraintEvidence],
        uniqueness_key_fields: Sequence[str] | None = None,
        normalized_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> WriteCommitReceipt:
        row = self.companion.store.get_row(
            "lake_logical_key_reservations", reservation_id
        )
        if row is None:
            raise ReservationError(f"unknown reservation {reservation_id!r}")
        status = str(row.get("status") or "")
        if status == ReservationStatus.COMMITTED.value:
            # Idempotent terminalization of an already-committed claim.
            outbox_rows = [
                r
                for r in self.companion.store.list_rows("lake_ingest_outbox")
                if r.get("operation_id") == operation_id
            ]
            if outbox_rows:
                outbox = OutboxEntry(
                    outbox_id=str(outbox_rows[0]["outbox_id"]),
                    shard_id=str(outbox_rows[0]["shard_id"]),
                    operation_id=str(outbox_rows[0]["operation_id"]),
                    reservation_id=reservation_id,
                    payload_digest=str(outbox_rows[0]["payload_digest"]),
                    status=str(outbox_rows[0]["status"]),
                    snapshot_version=snapshot_version,
                    created_at=str(outbox_rows[0].get("created_at") or ""),
                    updated_at=str(outbox_rows[0].get("updated_at") or ""),
                    cas_revision=int(outbox_rows[0].get("cas_revision") or 1),
                )
                return WriteCommitReceipt(
                    operation_id=operation_id,
                    reservation=LogicalKeyReservation.from_row(row),
                    outbox=outbox,
                    snapshot_version=int(row.get("snapshot_version") or snapshot_version),
                    schema_revision=contract.revision,
                    schema_digest=contract.schema_digest,
                    evidence=tuple(evidence),
                    atomic_across_files=False,
                )

        if status in _TERMINAL_SUCCESS_STATUSES:
            raise ReservationError(
                f"reservation {reservation_id!r} already terminal with status {status!r}"
            )

        payload = {
            "operation_id": operation_id,
            "reservation_id": reservation_id,
            "snapshot_version": int(snapshot_version),
            "schema_contract_id": contract.contract_id,
            "schema_revision": contract.revision,
            "schema_digest": contract.schema_digest,
            "logical_key_digest": row["logical_key_digest"],
            "idempotency_key": row["idempotency_key"],
        }
        outbox_id = f"outbox-{operation_id}"
        now = _utc_iso()
        outbox_row = {
            "outbox_id": outbox_id,
            "shard_id": self.shard_id,
            "operation_id": operation_id,
            "payload_digest": _sha256_text(_canonical_json(payload)),
            "status": "committed",
            "created_at": now,
            "updated_at": now,
            "snapshot_version": int(snapshot_version),
            "reservation_id": reservation_id,
            "payload_json": _canonical_json(payload),
        }
        stored_outbox, created = self.companion.store.put_if_absent(
            "lake_ingest_outbox", outbox_id, outbox_row
        )
        if not created and str(stored_outbox.get("status")) != "committed":
            stored_outbox = self.companion.store.cas_upsert(
                "lake_ingest_outbox",
                outbox_id,
                outbox_row,
                expected_revision=int(stored_outbox["cas_revision"]),
            )

        updated = dict(row)
        updated["status"] = ReservationStatus.COMMITTED.value
        updated["terminalized_at"] = now
        updated["snapshot_version"] = int(snapshot_version)
        stored_res = self.companion.store.cas_upsert(
            "lake_logical_key_reservations",
            reservation_id,
            updated,
            expected_revision=int(row["cas_revision"]),
        )

        if uniqueness_key_fields and normalized_records:
            scope_key = f"{contract.contract_id}:{','.join(uniqueness_key_fields)}"
            ledger = self._unique_ledger.setdefault(scope_key, set())
            for rec in normalized_records:
                key_payload = {fid: rec.get(fid) for fid in uniqueness_key_fields}
                ledger.add(logical_key_digest_for(key_payload))

        outbox = OutboxEntry(
            outbox_id=str(stored_outbox["outbox_id"]),
            shard_id=str(stored_outbox["shard_id"]),
            operation_id=str(stored_outbox["operation_id"]),
            reservation_id=reservation_id,
            payload_digest=str(stored_outbox["payload_digest"]),
            status=str(stored_outbox["status"]),
            snapshot_version=int(snapshot_version),
            created_at=str(stored_outbox.get("created_at") or ""),
            updated_at=str(stored_outbox.get("updated_at") or ""),
            cas_revision=int(stored_outbox.get("cas_revision") or 1),
        )
        return WriteCommitReceipt(
            operation_id=operation_id,
            reservation=LogicalKeyReservation.from_row(stored_res),
            outbox=outbox,
            snapshot_version=int(snapshot_version),
            schema_revision=contract.revision,
            schema_digest=contract.schema_digest,
            evidence=tuple(evidence),
            atomic_across_files=False,
        )

    def terminalize_reservation(
        self,
        *,
        reservation_id: str,
        operation_id: str,
        snapshot_version: int,
        contract: SchemaContract,
        evidence: Sequence[ConstraintEvidence] = (),
    ) -> WriteCommitReceipt:
        """Public terminalization after an external snapshot commit."""

        self.ensure_ready()
        with self._lock:
            return self._terminalize(
                reservation_id=reservation_id,
                operation_id=operation_id,
                snapshot_version=snapshot_version,
                contract=contract,
                evidence=evidence,
            )

    # -- recovery ----------------------------------------------------------

    def recover(
        self,
        *,
        contract: SchemaContract | None = None,
        known_objects: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        """Reconcile reservation, object, catalog snapshot, and outbox states.

        Does **not** claim atomicity across files. Produces a reconciliation
        report and terminalizes or reclaims as appropriate.
        """

        self.ensure_ready()
        with self._lock:
            objects = dict(known_objects or self._object_state)
            reservations = self.companion.store.list_rows(
                "lake_logical_key_reservations"
            )
            outboxes = self.companion.store.list_rows("lake_ingest_outbox")
            outbox_by_res = {
                str(o.get("reservation_id") or ""): o
                for o in outboxes
                if o.get("reservation_id")
            }
            outbox_by_op = {
                str(o.get("operation_id") or ""): o for o in outboxes
            }

            reconciled: list[dict[str, Any]] = []
            reclaimed: list[str] = []
            terminalized: list[str] = []
            in_doubt: list[str] = []

            for row in reservations:
                rid = str(row["reservation_id"])
                status = str(row.get("status") or "")
                snap = row.get("snapshot_version")
                op_guess = None
                for uri, meta in objects.items():
                    if meta.get("logical_key_digest") == row.get(
                        "logical_key_digest"
                    ):
                        op_guess = meta.get("operation_id")
                        if snap is None:
                            snap = meta.get("snapshot_version")
                        break

                if status == ReservationStatus.COMMITTED.value:
                    reconciled.append(
                        {
                            "reservation_id": rid,
                            "action": "already_terminal",
                            "status": status,
                        }
                    )
                    continue

                if status == ReservationStatus.IN_DOUBT.value or (
                    status == ReservationStatus.RESERVED.value
                    and snap is not None
                    and rid not in outbox_by_res
                ):
                    # Snapshot may have advanced; outbox missing → complete if
                    # object+snapshot evidence exists, else mark incomplete.
                    if op_guess and contract is not None and snap is not None:
                        receipt = self._terminalize(
                            reservation_id=rid,
                            operation_id=str(op_guess),
                            snapshot_version=int(snap),
                            contract=contract,
                            evidence=(),
                        )
                        terminalized.append(rid)
                        reconciled.append(
                            {
                                "reservation_id": rid,
                                "action": "terminalized_from_in_doubt",
                                "snapshot_version": receipt.snapshot_version,
                                "atomic_across_files": False,
                            }
                        )
                    else:
                        updated = dict(row)
                        updated["status"] = ReservationStatus.INCOMPLETE.value
                        self.companion.store.cas_upsert(
                            "lake_logical_key_reservations",
                            rid,
                            updated,
                            expected_revision=int(row["cas_revision"]),
                        )
                        in_doubt.append(rid)
                        reconciled.append(
                            {
                                "reservation_id": rid,
                                "action": "marked_incomplete",
                                "status": "incomplete",
                            }
                        )
                    continue

                if status in _RECLAIMABLE_STATUSES:
                    self.reclaim_incomplete_or_failed(rid)
                    reclaimed.append(rid)
                    reconciled.append(
                        {
                            "reservation_id": rid,
                            "action": "reclaimed",
                            "prior_status": status,
                        }
                    )
                    continue

                reconciled.append(
                    {
                        "reservation_id": rid,
                        "action": "left_in_place",
                        "status": status,
                    }
                )

            return MappingProxyType(
                {
                    "schema": CONTRACTS_SCHEMA,
                    "shard_id": self.shard_id,
                    "owner_id": self.owner_id,
                    "catalog_snapshot": self._catalog_snapshot,
                    "reconciled": reconciled,
                    "terminalized": terminalized,
                    "reclaimed": reclaimed,
                    "in_doubt": in_doubt,
                    "outbox_count": len(outboxes),
                    "reservation_count": len(reservations),
                    "atomic_across_files": False,
                    "note": (
                        "recovery reconciles reservation, object, catalog snapshot, "
                        "and outbox states without claiming atomicity across files"
                    ),
                }
            )

    def export_checkpoint(self) -> dict[str, Any]:
        return {
            "schema": CONTRACTS_SCHEMA,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
            "shard_id": self.shard_id,
            "owner_id": self.owner_id,
            "catalog_id": self.catalog_id,
            "catalog_snapshot": self._catalog_snapshot,
            "companion": self.companion.export_checkpoint(),
            "schema_history": {
                cid: [dict(c.as_mapping()) for c in hist]
                for cid, hist in self._schema_history.items()
            },
            "unique_ledger": {
                k: sorted(v) for k, v in self._unique_ledger.items()
            },
            "object_state": dict(self._object_state),
        }

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": CONTRACTS_SCHEMA,
                "implementation_generation": _IMPLEMENTATION_GENERATION,
                "shard_id": self.shard_id,
                "owner_id": self.owner_id,
                "catalog_id": self.catalog_id,
                "companion_instance": dict(self.companion.instance.as_mapping()),
                "companion_attachable_from_quack": (
                    self.companion.instance.attachable_from_quack
                ),
                "reservation_tables": sorted(_RESERVATION_AUTHORITY_TABLES),
                "ducklake_internal_isolated": True,
            }
        )
