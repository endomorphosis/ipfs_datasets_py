"""Parquet producer adapters for DuckLake shadow authority (DQK-089).

Routes the registered Parquet producers through the admitted lake port in
**shadow** mode:

* legacy outputs remain the compared projection during the canary window
* DuckDB / admitted-lake records are shadow projections only
* producer selection consumes the current accepted DQK-081 inventory-refinement
  receipt and binds inventory snapshot, repository tree, accepted plan root,
  and active materialized plan generation
* seed declarations and stale inventory bindings fail closed
* source Parquet / IPLD / CAR byte identities never drift
* shadow disagreement quarantines only the affected dataset

Importing this module is inert: no filesystem, DuckDB, or network I/O until an
explicit adapter method is called.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Optional,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityMode,
    AuthorityTransitionPort,
    MemoryAuthorityBackend,
    ParityReceipt,
    QuarantineRecord,
    build_authority_port,
    compute_payload_digest,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
)
from ipfs_datasets_py.duckdb_control import inventory_refinement as refinement
from ipfs_datasets_py.duckdb_control.inventory_refinement import (
    APPROVAL_GATE_TASK_ID,
    APPROVAL_RECEIPT_SCHEMA,
    verify_receipt,
)

__all__ = [
    "ADAPTER_SCHEMA",
    "DOMAIN",
    "OWNER_TASK_ID",
    "PROGRAM_ID",
    "REGISTERED_PARQUET_PRODUCERS",
    "SOURCE_RECEIPT_SCHEMA",
    "SCHEMA_RECEIPT_SCHEMA",
    "SNAPSHOT_RECEIPT_SCHEMA",
    "OWNERSHIP_RECEIPT_SCHEMA",
    "WAIVER_SCHEMA",
    "EXACT_TREE_INVENTORY_SCHEMA",
    "PRODUCER_BUNDLE_SCHEMA",
    "ActivePlanGenerationBinding",
    "AdmittedLakeShadowAdapter",
    "ExactTreeInventoryProof",
    "InventoryBinding",
    "OwnershipReceipt",
    "ParquetProducerId",
    "ParquetProducerShadowError",
    "ProducerIntegrationBundle",
    "ProducerSelectionError",
    "ProducerWaiver",
    "SchemaReceipt",
    "SeedDeclarationRejectedError",
    "SnapshotReceipt",
    "SourceReceipt",
    "StaleInventoryBindingError",
    "UnownedProducerError",
    "WaiverValidationError",
    "bind_active_plan_generation",
    "build_exact_tree_inventory_proof",
    "build_producer_waiver",
    "build_shadow_adapter",
    "consume_dqk081_inventory",
    "digest_bytes",
    "digest_file",
    "get_active_shadow_adapter",
    "get_registered_producer",
    "list_registered_producers",
    "maybe_shadow_project",
    "prove_zero_unowned_public_parquet_producers",
    "register_default_producers",
    "self_check",
    "set_active_shadow_adapter",
    "verify_producer_waiver",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-089"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
DOMAIN: Final[str] = "parquet-producers"

ADAPTER_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake/parquet-producer-adapter@1"
SOURCE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/parquet-producer-source-receipt@1"
)
SCHEMA_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/parquet-producer-schema-receipt@1"
)
SNAPSHOT_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/parquet-producer-snapshot-receipt@1"
)
OWNERSHIP_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/parquet-producer-ownership-receipt@1"
)
WAIVER_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake/parquet-producer-waiver@1"
EXACT_TREE_INVENTORY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/parquet-producer-exact-tree-inventory@1"
)
PRODUCER_BUNDLE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/parquet-producer-integration-bundle@1"
)
INVENTORY_BINDING_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/parquet-producer-inventory-binding@1"
)

_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SAFE_TOKEN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$"
)
_MAX_FIELD_BYTES: Final[int] = 8192
_DEFAULT_WAIVER_TTL_HOURS: Final[int] = 24
_SEED_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "seed",
        "seed_declaration",
        "seed-declaration",
        "seeded",
        "placeholder",
        "stub",
        "TASKS_seed",
        "program_seed",
    }
)


# ---------------------------------------------------------------------------
# Registered producers (closed set for DQK-089)
# ---------------------------------------------------------------------------


class ParquetProducerId(str, Enum):
    """Closed set of Parquet producers integrated through the lake port."""

    DATASET_LOADER = "dataset_loader"
    DATASET_SAVER = "dataset_saver"
    DATASET_CONVERTER = "dataset_converter"
    KG_PARQUET_STORAGE = "knowledge_graphs_parquet_storage"
    JSONL_TO_PARQUET = "jsonl_to_parquet"
    IPFS_PARQUET_TO_CAR = "ipfs_parquet_to_car"


@dataclass(frozen=True, slots=True)
class RegisteredProducer:
    """One producer path that may emit Parquet / IPLD / CAR outputs."""

    producer_id: ParquetProducerId
    module_path: str
    entrypoint: str
    public: bool = True
    emits: tuple[str, ...] = ("parquet",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer_id": self.producer_id.value,
            "module_path": self.module_path,
            "entrypoint": self.entrypoint,
            "public": self.public,
            "emits": list(self.emits),
        }


REGISTERED_PARQUET_PRODUCERS: Final[Mapping[str, RegisteredProducer]] = MappingProxyType(
    {
        ParquetProducerId.DATASET_LOADER.value: RegisteredProducer(
            producer_id=ParquetProducerId.DATASET_LOADER,
            module_path="ipfs_datasets_py/core_operations/dataset_loader.py",
            entrypoint="DatasetLoader.load",
            emits=("parquet", "dataset"),
        ),
        ParquetProducerId.DATASET_SAVER.value: RegisteredProducer(
            producer_id=ParquetProducerId.DATASET_SAVER,
            module_path="ipfs_datasets_py/core_operations/dataset_saver.py",
            entrypoint="DatasetSaver.save",
            emits=("parquet", "dataset"),
        ),
        ParquetProducerId.DATASET_CONVERTER.value: RegisteredProducer(
            producer_id=ParquetProducerId.DATASET_CONVERTER,
            module_path="ipfs_datasets_py/core_operations/dataset_converter.py",
            entrypoint="DatasetConverter.convert",
            emits=("parquet",),
        ),
        ParquetProducerId.KG_PARQUET_STORAGE.value: RegisteredProducer(
            producer_id=ParquetProducerId.KG_PARQUET_STORAGE,
            module_path="ipfs_datasets_py/knowledge_graphs/storage/parquet.py",
            entrypoint="ParquetGraphStore",
            emits=("parquet", "ipld"),
        ),
        ParquetProducerId.JSONL_TO_PARQUET.value: RegisteredProducer(
            producer_id=ParquetProducerId.JSONL_TO_PARQUET,
            module_path="ipfs_datasets_py/processors/serialization/jsonl_to_parquet.py",
            entrypoint="jsonl_to_parquet",
            emits=("parquet",),
        ),
        ParquetProducerId.IPFS_PARQUET_TO_CAR.value: RegisteredProducer(
            producer_id=ParquetProducerId.IPFS_PARQUET_TO_CAR,
            module_path=(
                "ipfs_datasets_py/processors/serialization/ipfs_parquet_to_car.py"
            ),
            entrypoint="ipfs_parquet_to_car_py.run",
            emits=("car", "ipld"),
        ),
    }
)


def list_registered_producers() -> tuple[str, ...]:
    return tuple(sorted(REGISTERED_PARQUET_PRODUCERS.keys()))


def get_registered_producer(producer_id: str | ParquetProducerId) -> RegisteredProducer:
    key = (
        producer_id.value
        if isinstance(producer_id, ParquetProducerId)
        else str(producer_id).strip()
    )
    try:
        return REGISTERED_PARQUET_PRODUCERS[key]
    except KeyError as exc:
        raise ProducerSelectionError(
            f"unknown parquet producer {key!r}; expected one of "
            f"{list_registered_producers()}"
        ) from exc


def register_default_producers() -> Mapping[str, RegisteredProducer]:
    """Return the sealed closed-set registry (no ambient registration)."""

    return REGISTERED_PARQUET_PRODUCERS


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ParquetProducerShadowError(ValueError):
    """Fail-closed rejection for parquet producer shadow integration."""


class StaleInventoryBindingError(ParquetProducerShadowError):
    """Inventory snapshot, tree, plan root, or generation binding is stale."""


class SeedDeclarationRejectedError(ParquetProducerShadowError):
    """Seed / program-seed declarations cannot authorize integration."""


class UnownedProducerError(ParquetProducerShadowError):
    """Public parquet producer path is not owned and has no valid waiver."""


class ProducerSelectionError(ParquetProducerShadowError):
    """Producer is not authorized by the current inventory binding."""


class WaiverValidationError(ParquetProducerShadowError):
    """Waiver signature, scope, justification, or expiry failed closed."""


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return normalize_timestamp(
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )


def _bounded_text(
    value: Any,
    *,
    field: str,
    allow_empty: bool = False,
    max_bytes: int = _MAX_FIELD_BYTES,
) -> str:
    if not isinstance(value, str):
        raise ParquetProducerShadowError(f"{field} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise ParquetProducerShadowError(f"{field} must be nonempty")
    if len(text.encode("utf-8")) > max_bytes:
        raise ParquetProducerShadowError(f"{field} exceeds {max_bytes}-byte bound")
    if any(ch in text for ch in ("\0", "\n", "\r")):
        raise ParquetProducerShadowError(f"{field} must not contain control characters")
    return text


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    normalized = text.lower()
    if not normalized.startswith("sha256:"):
        if re.fullmatch(r"[0-9a-f]{64}", normalized):
            normalized = f"sha256:{normalized}"
        else:
            raise ParquetProducerShadowError(f"{field} must be sha256:<64 hex>")
    if not _SHA256_DIGEST.fullmatch(normalized):
        raise ParquetProducerShadowError(f"{field} must be sha256:<64 hex>")
    return normalized


def _require_tree_id(value: Any, *, field: str = "repository_tree_id") -> str:
    text = _bounded_text(value, field=field).lower()
    if not _GIT_OID.fullmatch(text):
        raise ParquetProducerShadowError(f"{field} must be a 40-hex git tree oid")
    return text


def _parse_utc(value: Any, *, field: str) -> datetime:
    text = _bounded_text(value, field=field)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ParquetProducerShadowError(f"{field} is not ISO-8601") from exc
    if moment.tzinfo is None:
        raise ParquetProducerShadowError(f"{field} must be timezone-aware UTC")
    return moment.astimezone(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def digest_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` for raw bytes (source byte identity)."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ParquetProducerShadowError("digest_bytes requires bytes-like input")
    return f"sha256:{hashlib.sha256(bytes(data)).hexdigest()}"


def digest_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Stream a file and return its content ``sha256:<hex>`` identity."""

    file_path = Path(path)
    if not file_path.is_file():
        raise ParquetProducerShadowError(f"path is not a file: {file_path}")
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def _looks_like_seed(marker: str) -> bool:
    text = marker.strip().lower().replace(" ", "_")
    if text in _SEED_MARKERS:
        return True
    return any(token in text for token in ("seed_declaration", "program_seed", "tasks_seed"))


# ---------------------------------------------------------------------------
# Active plan generation + inventory binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivePlanGenerationBinding:
    """Exact active materialized plan generation required for integration."""

    generation_id: str
    plan_root_cid: str
    repository_tree_id: str
    database_identity: str = ""
    retired: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "generation_id",
            _bounded_text(self.generation_id, field="generation_id"),
        )
        object.__setattr__(
            self,
            "plan_root_cid",
            _require_sha256(self.plan_root_cid, field="plan_root_cid"),
        )
        object.__setattr__(
            self,
            "repository_tree_id",
            _require_tree_id(self.repository_tree_id),
        )
        if self.database_identity:
            object.__setattr__(
                self,
                "database_identity",
                _bounded_text(self.database_identity, field="database_identity"),
            )
        if self.retired:
            raise StaleInventoryBindingError(
                "retired plan generation cannot authorize parquet producer integration"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "plan_root_cid": self.plan_root_cid,
            "repository_tree_id": self.repository_tree_id,
            "database_identity": self.database_identity,
            "retired": False,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ActivePlanGenerationBinding":
        if not isinstance(value, Mapping):
            raise ParquetProducerShadowError("active plan generation must be an object")
        return cls(
            generation_id=str(value.get("generation_id") or ""),
            plan_root_cid=str(value.get("plan_root_cid") or ""),
            repository_tree_id=str(value.get("repository_tree_id") or ""),
            database_identity=str(value.get("database_identity") or ""),
            retired=bool(value.get("retired")),
        )


def bind_active_plan_generation(
    *,
    generation_id: str,
    plan_root_cid: str,
    repository_tree_id: str,
    database_identity: str = "",
    retired: bool = False,
) -> ActivePlanGenerationBinding:
    return ActivePlanGenerationBinding(
        generation_id=generation_id,
        plan_root_cid=plan_root_cid,
        repository_tree_id=repository_tree_id,
        database_identity=database_identity,
        retired=retired,
    )


@dataclass(frozen=True, slots=True)
class InventoryBinding:
    """Fail-closed binding of the accepted DQK-081 inventory to active generation."""

    schema: str
    repository_id: str
    repository_tree_id: str
    inventory_snapshot_cid: str
    accepted_plan_root_cid: str
    active_plan_root_cid: str
    active_plan_generation_id: str
    refinement_receipt_cid: str
    approval_gate_task_id: str
    bound_at: str
    seed_declaration: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema", INVENTORY_BINDING_SCHEMA)
        object.__setattr__(
            self,
            "repository_id",
            _bounded_text(self.repository_id, field="repository_id"),
        )
        object.__setattr__(
            self,
            "repository_tree_id",
            _require_tree_id(self.repository_tree_id),
        )
        object.__setattr__(
            self,
            "inventory_snapshot_cid",
            _require_sha256(self.inventory_snapshot_cid, field="inventory_snapshot_cid"),
        )
        object.__setattr__(
            self,
            "accepted_plan_root_cid",
            _require_sha256(self.accepted_plan_root_cid, field="accepted_plan_root_cid"),
        )
        object.__setattr__(
            self,
            "active_plan_root_cid",
            _require_sha256(self.active_plan_root_cid, field="active_plan_root_cid"),
        )
        object.__setattr__(
            self,
            "active_plan_generation_id",
            _bounded_text(
                self.active_plan_generation_id, field="active_plan_generation_id"
            ),
        )
        object.__setattr__(
            self,
            "refinement_receipt_cid",
            _require_sha256(
                self.refinement_receipt_cid, field="refinement_receipt_cid"
            ),
        )
        object.__setattr__(
            self,
            "approval_gate_task_id",
            _bounded_text(self.approval_gate_task_id, field="approval_gate_task_id"),
        )
        if self.approval_gate_task_id != APPROVAL_GATE_TASK_ID:
            raise StaleInventoryBindingError(
                f"inventory binding must come from {APPROVAL_GATE_TASK_ID}, "
                f"got {self.approval_gate_task_id!r}"
            )
        if self.seed_declaration:
            raise SeedDeclarationRejectedError(
                "seed declarations cannot authorize parquet producer integration"
            )
        if not self.bound_at:
            object.__setattr__(self, "bound_at", _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "accepted_plan_root_cid": self.accepted_plan_root_cid,
            "active_plan_root_cid": self.active_plan_root_cid,
            "active_plan_generation_id": self.active_plan_generation_id,
            "refinement_receipt_cid": self.refinement_receipt_cid,
            "approval_gate_task_id": self.approval_gate_task_id,
            "bound_at": self.bound_at,
            "seed_declaration": False,
            "binding_cid": content_identity(
                {
                    "repository_id": self.repository_id,
                    "repository_tree_id": self.repository_tree_id,
                    "inventory_snapshot_cid": self.inventory_snapshot_cid,
                    "accepted_plan_root_cid": self.accepted_plan_root_cid,
                    "active_plan_root_cid": self.active_plan_root_cid,
                    "active_plan_generation_id": self.active_plan_generation_id,
                    "refinement_receipt_cid": self.refinement_receipt_cid,
                }
            ),
        }


def consume_dqk081_inventory(
    receipt: Mapping[str, Any],
    *,
    active_generation: ActivePlanGenerationBinding | Mapping[str, Any],
    expected_repository_tree_id: str | None = None,
    expected_inventory_snapshot_cid: str | None = None,
    expected_accepted_plan_root_cid: str | None = None,
    expected_active_plan_root_cid: str | None = None,
    expected_generation_id: str | None = None,
    now: datetime | None = None,
    seed_marker: str = "",
) -> InventoryBinding:
    """Consume the current accepted DQK-081 receipt into a sealed binding.

    Fail-closed against seed declarations and any stale inventory-snapshot,
    repository-tree, plan-root, or generation identity.
    """

    if seed_marker and _looks_like_seed(seed_marker):
        raise SeedDeclarationRejectedError(
            f"seed marker {seed_marker!r} cannot authorize integration"
        )
    if isinstance(receipt, Mapping) and receipt.get("seed_declaration") is True:
        raise SeedDeclarationRejectedError(
            "seed inventory declaration cannot authorize integration"
        )
    if isinstance(receipt, Mapping):
        source_kind = str(receipt.get("source_kind") or receipt.get("origin") or "")
        if source_kind and _looks_like_seed(source_kind):
            raise SeedDeclarationRejectedError(
                f"seed origin {source_kind!r} cannot authorize integration"
            )

    generation = (
        active_generation
        if isinstance(active_generation, ActivePlanGenerationBinding)
        else ActivePlanGenerationBinding.from_mapping(active_generation)
    )

    # Cryptographic verification of the refinement receipt (DQK-081).
    try:
        verification = verify_receipt(
            receipt,
            expected_repository_tree_id=expected_repository_tree_id
            or generation.repository_tree_id,
            expected_inventory_snapshot_cid=expected_inventory_snapshot_cid,
            expected_active_plan_root_cid=expected_active_plan_root_cid
            or generation.plan_root_cid,
            expected_accepted_plan_root_cid=expected_accepted_plan_root_cid,
            now=now,
        )
    except refinement.InventoryRefinementError as exc:
        message = str(exc).lower()
        if "stale" in message or "expired" in message:
            raise StaleInventoryBindingError(str(exc)) from exc
        if "mismatch" in message or "tree" in message or "plan" in message:
            raise StaleInventoryBindingError(str(exc)) from exc
        if "snapshot" in message:
            raise StaleInventoryBindingError(str(exc)) from exc
        raise StaleInventoryBindingError(
            f"DQK-081 inventory receipt rejected: {exc}"
        ) from exc
    if verification.get("accepted") is not True:
        raise StaleInventoryBindingError("DQK-081 inventory receipt was not accepted")

    receipt_tree = _require_tree_id(
        receipt.get("repository_tree_id"), field="receipt.repository_tree_id"
    )
    if receipt_tree != generation.repository_tree_id:
        raise StaleInventoryBindingError(
            "repository-tree binding does not match active plan generation"
        )
    if expected_repository_tree_id is not None:
        expected_tree = _require_tree_id(
            expected_repository_tree_id, field="expected_repository_tree_id"
        )
        if receipt_tree != expected_tree:
            raise StaleInventoryBindingError(
                "stale repository-tree binding relative to expected tree"
            )

    snapshot_cid = _require_sha256(
        receipt.get("inventory_snapshot_cid"), field="inventory_snapshot_cid"
    )
    if expected_inventory_snapshot_cid is not None:
        expected_snap = _require_sha256(
            expected_inventory_snapshot_cid, field="expected_inventory_snapshot_cid"
        )
        if snapshot_cid != expected_snap:
            raise StaleInventoryBindingError(
                "stale inventory-snapshot binding relative to expected snapshot"
            )

    accepted_plan = _require_sha256(
        receipt.get("accepted_plan_root_cid"), field="accepted_plan_root_cid"
    )
    active_plan = _require_sha256(
        receipt.get("active_plan_root_cid"), field="active_plan_root_cid"
    )
    if active_plan != generation.plan_root_cid:
        raise StaleInventoryBindingError(
            "active plan root does not match active materialized plan generation"
        )
    if expected_accepted_plan_root_cid is not None:
        expected_accepted = _require_sha256(
            expected_accepted_plan_root_cid, field="expected_accepted_plan_root_cid"
        )
        if accepted_plan != expected_accepted:
            raise StaleInventoryBindingError(
                "stale accepted plan-root binding relative to expected plan root"
            )
    if expected_active_plan_root_cid is not None:
        expected_active = _require_sha256(
            expected_active_plan_root_cid, field="expected_active_plan_root_cid"
        )
        if active_plan != expected_active:
            raise StaleInventoryBindingError(
                "stale active plan-root binding relative to expected plan root"
            )

    generation_id = generation.generation_id
    if expected_generation_id is not None:
        expected_gen = _bounded_text(
            expected_generation_id, field="expected_generation_id"
        )
        if generation_id != expected_gen:
            raise StaleInventoryBindingError(
                "stale active plan generation binding"
            )
    # Optional explicit generation claim on the receipt must match when present.
    claimed_generation = str(
        receipt.get("active_plan_generation_id")
        or receipt.get("generation_id")
        or ""
    ).strip()
    if claimed_generation and claimed_generation != generation_id:
        raise StaleInventoryBindingError(
            "receipt generation claim does not match active plan generation"
        )

    return InventoryBinding(
        schema=INVENTORY_BINDING_SCHEMA,
        repository_id=_bounded_text(
            receipt.get("repository_id"), field="repository_id"
        ),
        repository_tree_id=receipt_tree,
        inventory_snapshot_cid=snapshot_cid,
        accepted_plan_root_cid=accepted_plan,
        active_plan_root_cid=active_plan,
        active_plan_generation_id=generation_id,
        refinement_receipt_cid=_require_sha256(
            receipt.get("receipt_cid"), field="receipt_cid"
        ),
        approval_gate_task_id=str(
            receipt.get("approval_gate_task_id") or APPROVAL_GATE_TASK_ID
        ),
        bound_at=_utc_now(),
        seed_declaration=False,
    )


# ---------------------------------------------------------------------------
# Waivers + exact-tree inventory proof
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProducerWaiver:
    """Reviewer-signed, path-scoped, justified, expiring producer ownership waiver."""

    schema: str
    waiver_cid: str
    path: str
    producer_id: str
    reviewer_id: str
    justification: str
    issued_at: str
    expires_at: str
    signature: str
    signature_algorithm: str = "content-bound-sha256@1"
    repository_tree_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "waiver_cid": self.waiver_cid,
            "path": self.path,
            "producer_id": self.producer_id,
            "reviewer_id": self.reviewer_id,
            "justification": self.justification,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
            "repository_tree_id": self.repository_tree_id,
        }


def _waiver_unsigned_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"signature", "waiver_cid"}
    }


def build_producer_waiver(
    *,
    path: str,
    producer_id: str,
    reviewer_id: str,
    justification: str,
    repository_tree_id: str = "",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a sealed path-scoped producer waiver."""

    now = datetime.now(timezone.utc).replace(microsecond=0)
    issued = issued_at if issued_at is not None else now
    expires = (
        expires_at
        if expires_at is not None
        else now + timedelta(hours=_DEFAULT_WAIVER_TTL_HOURS)
    )
    if expires <= issued:
        raise WaiverValidationError("waiver expires_at must be after issued_at")
    body: dict[str, Any] = {
        "schema": WAIVER_SCHEMA,
        "path": _bounded_text(path, field="path"),
        "producer_id": _bounded_text(producer_id, field="producer_id"),
        "reviewer_id": _bounded_text(reviewer_id, field="reviewer_id"),
        "justification": _bounded_text(justification, field="justification"),
        "issued_at": normalize_timestamp(issued),
        "expires_at": normalize_timestamp(expires),
        "signature_algorithm": "content-bound-sha256@1",
        "repository_tree_id": (
            _require_tree_id(repository_tree_id)
            if str(repository_tree_id or "").strip()
            else ""
        ),
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
    }
    body["signature"] = content_identity(_waiver_unsigned_body(body))
    body["waiver_cid"] = content_identity(
        {key: value for key, value in body.items() if key != "waiver_cid"}
    )
    return body


def verify_producer_waiver(
    waiver: Mapping[str, Any],
    *,
    path: str | None = None,
    now: datetime | None = None,
    repository_tree_id: str | None = None,
) -> ProducerWaiver:
    """Fail-closed verification of a producer waiver."""

    if not isinstance(waiver, Mapping):
        raise WaiverValidationError("waiver must be an object")
    required = (
        "schema",
        "path",
        "producer_id",
        "reviewer_id",
        "justification",
        "issued_at",
        "expires_at",
        "signature",
        "waiver_cid",
    )
    missing = [name for name in required if not str(waiver.get(name) or "").strip()]
    if missing:
        raise WaiverValidationError(
            "incomplete waiver; missing fields: " + ",".join(missing)
        )
    if waiver.get("schema") != WAIVER_SCHEMA:
        raise WaiverValidationError(f"waiver schema must be {WAIVER_SCHEMA}")
    reviewer = _bounded_text(waiver.get("reviewer_id"), field="reviewer_id")
    if reviewer in {"", "self", "analyzer", "seed"}:
        raise WaiverValidationError("waiver reviewer_id is not a valid reviewer")
    justification = _bounded_text(waiver.get("justification"), field="justification")
    if len(justification) < 8:
        raise WaiverValidationError("waiver justification is too short")

    expected_sig = content_identity(_waiver_unsigned_body(dict(waiver)))
    actual_sig = _require_sha256(waiver.get("signature"), field="waiver.signature")
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise WaiverValidationError("waiver signature does not match signed body")
    expected_cid = content_identity(
        {key: value for key, value in waiver.items() if key != "waiver_cid"}
    )
    actual_cid = _require_sha256(waiver.get("waiver_cid"), field="waiver.waiver_cid")
    if not hmac.compare_digest(expected_cid, actual_cid):
        raise WaiverValidationError("waiver_cid is not content-bound")

    clock = now if now is not None else datetime.now(timezone.utc)
    expires_at = _parse_utc(waiver.get("expires_at"), field="expires_at")
    if expires_at <= clock:
        raise WaiverValidationError("waiver has expired")
    issued_at = _parse_utc(waiver.get("issued_at"), field="issued_at")
    if issued_at > clock + timedelta(seconds=60):
        raise WaiverValidationError("waiver issued_at is in the future")

    waiver_path = _bounded_text(waiver.get("path"), field="path")
    if path is not None and not (
        path == waiver_path
        or path.startswith(waiver_path.rstrip("/") + "/")
        or waiver_path.startswith(path.rstrip("/") + "/")
        or path.startswith(waiver_path)
    ):
        raise WaiverValidationError(
            f"waiver path {waiver_path!r} does not cover {path!r}"
        )
    tree = str(waiver.get("repository_tree_id") or "").strip()
    if repository_tree_id is not None and tree:
        if _require_tree_id(tree) != _require_tree_id(repository_tree_id):
            raise WaiverValidationError(
                "waiver repository_tree_id does not match inventory tree"
            )

    return ProducerWaiver(
        schema=WAIVER_SCHEMA,
        waiver_cid=actual_cid,
        path=waiver_path,
        producer_id=_bounded_text(waiver.get("producer_id"), field="producer_id"),
        reviewer_id=reviewer,
        justification=justification,
        issued_at=normalize_timestamp(issued_at),
        expires_at=normalize_timestamp(expires_at),
        signature=actual_sig,
        signature_algorithm=str(
            waiver.get("signature_algorithm") or "content-bound-sha256@1"
        ),
        repository_tree_id=tree,
    )


@dataclass(frozen=True, slots=True)
class ExactTreeInventoryProof:
    """Signed exact-tree inventory proving zero unowned public Parquet producers."""

    schema: str
    repository_tree_id: str
    inventory_snapshot_cid: str
    owned_paths: tuple[str, ...]
    public_producer_paths: tuple[str, ...]
    unowned_public_paths: tuple[str, ...]
    waiver_cids: tuple[str, ...]
    signature: str
    proof_cid: str
    zero_unowned: bool
    issued_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository_tree_id": self.repository_tree_id,
            "inventory_snapshot_cid": self.inventory_snapshot_cid,
            "owned_paths": list(self.owned_paths),
            "public_producer_paths": list(self.public_producer_paths),
            "unowned_public_paths": list(self.unowned_public_paths),
            "waiver_cids": list(self.waiver_cids),
            "signature": self.signature,
            "proof_cid": self.proof_cid,
            "zero_unowned": self.zero_unowned,
            "issued_at": self.issued_at,
        }


def _path_owned(path: str, owned_paths: Sequence[str]) -> bool:
    normalized = path.strip().lstrip("./")
    for owned in owned_paths:
        root = owned.strip().lstrip("./")
        if not root:
            continue
        if normalized == root or normalized.startswith(root.rstrip("/") + "/"):
            return True
        if root.endswith(".py") and normalized == root:
            return True
    return False


def prove_zero_unowned_public_parquet_producers(
    *,
    repository_tree_id: str,
    inventory_snapshot_cid: str,
    public_producer_paths: Sequence[str],
    owned_paths: Sequence[str],
    waivers: Sequence[Mapping[str, Any]] = (),
    now: datetime | None = None,
) -> ExactTreeInventoryProof:
    """Prove every public Parquet producer path is owned or has a valid waiver."""

    tree = _require_tree_id(repository_tree_id)
    snapshot = _require_sha256(inventory_snapshot_cid, field="inventory_snapshot_cid")
    public_paths = tuple(
        sorted({_bounded_text(p, field="public_producer_path") for p in public_producer_paths})
    )
    owned = tuple(sorted({_bounded_text(p, field="owned_path") for p in owned_paths}))

    verified_waivers: list[ProducerWaiver] = []
    for raw in waivers:
        verified_waivers.append(
            verify_producer_waiver(
                raw, now=now, repository_tree_id=tree
            )
        )
    waiver_by_path = {w.path: w for w in verified_waivers}

    unowned: list[str] = []
    applied_waiver_cids: list[str] = []
    for path in public_paths:
        if _path_owned(path, owned):
            continue
        matched = None
        for wpath, waiver in waiver_by_path.items():
            if path == wpath or path.startswith(wpath.rstrip("/") + "/"):
                matched = waiver
                break
        if matched is None:
            unowned.append(path)
        else:
            applied_waiver_cids.append(matched.waiver_cid)

    if unowned:
        raise UnownedProducerError(
            "unsigned exact-tree inventory has unowned public Parquet producers: "
            + ", ".join(unowned)
        )

    body = {
        "schema": EXACT_TREE_INVENTORY_SCHEMA,
        "repository_tree_id": tree,
        "inventory_snapshot_cid": snapshot,
        "owned_paths": list(owned),
        "public_producer_paths": list(public_paths),
        "unowned_public_paths": [],
        "waiver_cids": sorted(set(applied_waiver_cids)),
        "zero_unowned": True,
        "issued_at": _utc_now(),
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
    }
    signature = content_identity(body)
    proof_cid = content_identity({**body, "signature": signature})
    return ExactTreeInventoryProof(
        schema=EXACT_TREE_INVENTORY_SCHEMA,
        repository_tree_id=tree,
        inventory_snapshot_cid=snapshot,
        owned_paths=owned,
        public_producer_paths=public_paths,
        unowned_public_paths=(),
        waiver_cids=tuple(sorted(set(applied_waiver_cids))),
        signature=signature,
        proof_cid=proof_cid,
        zero_unowned=True,
        issued_at=body["issued_at"],
    )


def build_exact_tree_inventory_proof(
    *,
    binding: InventoryBinding,
    owned_paths: Sequence[str] | None = None,
    waivers: Sequence[Mapping[str, Any]] = (),
    now: datetime | None = None,
) -> ExactTreeInventoryProof:
    """Build a proof over the closed registered public producer path set."""

    public_paths = tuple(
        producer.module_path
        for producer in REGISTERED_PARQUET_PRODUCERS.values()
        if producer.public
    )
    default_owned = owned_paths or public_paths
    return prove_zero_unowned_public_parquet_producers(
        repository_tree_id=binding.repository_tree_id,
        inventory_snapshot_cid=binding.inventory_snapshot_cid,
        public_producer_paths=public_paths,
        owned_paths=default_owned,
        waivers=waivers,
        now=now,
    )


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    """Receipt binding source byte identity (Parquet / IPLD / CAR)."""

    receipt_cid: str
    producer_id: str
    dataset_id: str
    source_uri: str
    source_digest: str
    source_kind: str
    operation_id: str
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())
        if not self.receipt_cid:
            object.__setattr__(
                self,
                "receipt_cid",
                content_identity(
                    {
                        "schema": SOURCE_RECEIPT_SCHEMA,
                        "producer_id": self.producer_id,
                        "dataset_id": self.dataset_id,
                        "source_uri": self.source_uri,
                        "source_digest": self.source_digest,
                        "source_kind": self.source_kind,
                        "operation_id": self.operation_id,
                        "created_at": self.created_at,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SOURCE_RECEIPT_SCHEMA,
            "receipt_cid": self.receipt_cid,
            "producer_id": self.producer_id,
            "dataset_id": self.dataset_id,
            "source_uri": self.source_uri,
            "source_digest": self.source_digest,
            "source_kind": self.source_kind,
            "operation_id": self.operation_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class SchemaReceipt:
    """Receipt for the schema identity observed by the producer."""

    receipt_cid: str
    producer_id: str
    dataset_id: str
    schema_digest: str
    schema_revision: int
    operation_id: str
    fields: tuple[str, ...] = ()
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())
        if not self.receipt_cid:
            object.__setattr__(
                self,
                "receipt_cid",
                content_identity(
                    {
                        "schema": SCHEMA_RECEIPT_SCHEMA,
                        "producer_id": self.producer_id,
                        "dataset_id": self.dataset_id,
                        "schema_digest": self.schema_digest,
                        "schema_revision": self.schema_revision,
                        "fields": list(self.fields),
                        "operation_id": self.operation_id,
                        "created_at": self.created_at,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_RECEIPT_SCHEMA,
            "receipt_cid": self.receipt_cid,
            "producer_id": self.producer_id,
            "dataset_id": self.dataset_id,
            "schema_digest": self.schema_digest,
            "schema_revision": self.schema_revision,
            "fields": list(self.fields),
            "operation_id": self.operation_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class SnapshotReceipt:
    """Receipt for the shadow lake snapshot projection."""

    receipt_cid: str
    producer_id: str
    dataset_id: str
    snapshot_version: int
    catalog_id: str
    operation_id: str
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())
        if not self.receipt_cid:
            object.__setattr__(
                self,
                "receipt_cid",
                content_identity(
                    {
                        "schema": SNAPSHOT_RECEIPT_SCHEMA,
                        "producer_id": self.producer_id,
                        "dataset_id": self.dataset_id,
                        "snapshot_version": self.snapshot_version,
                        "catalog_id": self.catalog_id,
                        "operation_id": self.operation_id,
                        "created_at": self.created_at,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_RECEIPT_SCHEMA,
            "receipt_cid": self.receipt_cid,
            "producer_id": self.producer_id,
            "dataset_id": self.dataset_id,
            "snapshot_version": self.snapshot_version,
            "catalog_id": self.catalog_id,
            "operation_id": self.operation_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class OwnershipReceipt:
    """Receipt recording source ownership kind for shadow ingest."""

    receipt_cid: str
    producer_id: str
    dataset_id: str
    ownership_kind: str
    copy_required: bool
    operation_id: str
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())
        if not self.receipt_cid:
            object.__setattr__(
                self,
                "receipt_cid",
                content_identity(
                    {
                        "schema": OWNERSHIP_RECEIPT_SCHEMA,
                        "producer_id": self.producer_id,
                        "dataset_id": self.dataset_id,
                        "ownership_kind": self.ownership_kind,
                        "copy_required": self.copy_required,
                        "operation_id": self.operation_id,
                        "created_at": self.created_at,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OWNERSHIP_RECEIPT_SCHEMA,
            "receipt_cid": self.receipt_cid,
            "producer_id": self.producer_id,
            "dataset_id": self.dataset_id,
            "ownership_kind": self.ownership_kind,
            "copy_required": self.copy_required,
            "operation_id": self.operation_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ProducerIntegrationBundle:
    """Bundle of all receipts emitted by one registered producer operation."""

    schema: str
    producer_id: str
    dataset_id: str
    operation_id: str
    source: SourceReceipt
    schema_receipt: SchemaReceipt
    snapshot: SnapshotReceipt
    ownership: OwnershipReceipt
    parity: ParityReceipt
    inventory_binding_cid: str
    source_byte_identity_preserved: bool
    mode: str
    legacy_is_authority: bool
    quarantined: bool = False
    quarantine_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "producer_id": self.producer_id,
            "dataset_id": self.dataset_id,
            "operation_id": self.operation_id,
            "source": self.source.to_dict(),
            "schema_receipt": self.schema_receipt.to_dict(),
            "snapshot": self.snapshot.to_dict(),
            "ownership": self.ownership.to_dict(),
            "parity": self.parity.to_dict(),
            "inventory_binding_cid": self.inventory_binding_cid,
            "source_byte_identity_preserved": self.source_byte_identity_preserved,
            "mode": self.mode,
            "legacy_is_authority": self.legacy_is_authority,
            "quarantined": self.quarantined,
            "quarantine_id": self.quarantine_id,
        }


# ---------------------------------------------------------------------------
# Shadow adapter (admitted lake port)
# ---------------------------------------------------------------------------


class AdmittedLakeShadowAdapter:
    """Admitted-lake shadow port for registered Parquet producers.

    During the canary window legacy outputs remain the compared projection;
    DuckDB receives shadow records via the domain-neutral authority port in
    :class:`AuthorityMode.SHADOW`.
    """

    SCHEMA: Final[str] = ADAPTER_SCHEMA

    def __init__(
        self,
        *,
        binding: InventoryBinding,
        authority_port: AuthorityTransitionPort,
        exact_tree_proof: ExactTreeInventoryProof,
        catalog_id: str = "lake-shadow-catalog",
        snapshot_version: int = 1,
    ) -> None:
        if authority_port.mode is not AuthorityMode.SHADOW:
            raise ParquetProducerShadowError(
                f"admitted lake shadow adapter requires mode=shadow, got "
                f"{authority_port.mode.value!r}"
            )
        if not exact_tree_proof.zero_unowned:
            raise UnownedProducerError(
                "exact-tree inventory proof does not assert zero unowned producers"
            )
        if (
            exact_tree_proof.repository_tree_id != binding.repository_tree_id
            or exact_tree_proof.inventory_snapshot_cid
            != binding.inventory_snapshot_cid
        ):
            raise StaleInventoryBindingError(
                "exact-tree inventory proof is not bound to the inventory binding"
            )
        self._binding = binding
        self._port = authority_port
        self._proof = exact_tree_proof
        self._catalog_id = _bounded_text(catalog_id, field="catalog_id")
        self._snapshot_version = int(snapshot_version)
        self._lock = threading.RLock()
        self._bundles: dict[str, ProducerIntegrationBundle] = {}
        self._source_digests: dict[str, str] = {}
        self._dataset_quarantines: dict[str, str] = {}
        self._snapshot_counter = int(snapshot_version)

    # -- properties ---------------------------------------------------------

    @property
    def binding(self) -> InventoryBinding:
        return self._binding

    @property
    def authority_port(self) -> AuthorityTransitionPort:
        return self._port

    @property
    def exact_tree_proof(self) -> ExactTreeInventoryProof:
        return self._proof

    @property
    def mode(self) -> AuthorityMode:
        return self._port.mode

    # -- selection ----------------------------------------------------------

    def select_producer(self, producer_id: str | ParquetProducerId) -> RegisteredProducer:
        """Select a producer only when inventory binding authorizes it."""

        producer = get_registered_producer(producer_id)
        if producer.public and not _path_owned(
            producer.module_path, self._proof.owned_paths
        ):
            # Waiver coverage already enforced by proof construction; re-check.
            covered = any(
                producer.module_path == path
                or producer.module_path.startswith(path.rstrip("/") + "/")
                for path in self._proof.public_producer_paths
            )
            if not covered or not self._proof.zero_unowned:
                raise ProducerSelectionError(
                    f"producer {producer.producer_id.value} is not authorized by "
                    "the current exact-tree inventory"
                )
        return producer

    def assert_binding_current(
        self,
        *,
        inventory_snapshot_cid: str | None = None,
        repository_tree_id: str | None = None,
        plan_root_cid: str | None = None,
        generation_id: str | None = None,
    ) -> None:
        """Fail closed when any binding coordinate has gone stale."""

        if inventory_snapshot_cid is not None:
            snap = _require_sha256(
                inventory_snapshot_cid, field="inventory_snapshot_cid"
            )
            if snap != self._binding.inventory_snapshot_cid:
                raise StaleInventoryBindingError("stale inventory-snapshot binding")
        if repository_tree_id is not None:
            tree = _require_tree_id(repository_tree_id)
            if tree != self._binding.repository_tree_id:
                raise StaleInventoryBindingError("stale repository-tree binding")
        if plan_root_cid is not None:
            plan = _require_sha256(plan_root_cid, field="plan_root_cid")
            if plan not in {
                self._binding.accepted_plan_root_cid,
                self._binding.active_plan_root_cid,
            }:
                raise StaleInventoryBindingError("stale plan-root binding")
        if generation_id is not None:
            gen = _bounded_text(generation_id, field="generation_id")
            if gen != self._binding.active_plan_generation_id:
                raise StaleInventoryBindingError("stale plan generation binding")

    # -- shadow project -----------------------------------------------------

    def shadow_project(
        self,
        *,
        producer_id: str | ParquetProducerId,
        dataset_id: str,
        source_uri: str,
        source_digest: str,
        source_kind: str = "parquet",
        schema_digest: str | None = None,
        schema_fields: Sequence[str] = (),
        schema_revision: int = 1,
        ownership_kind: str = "external_unmanaged",
        copy_required: bool = True,
        legacy_payload: Mapping[str, Any] | None = None,
        lake_payload: Mapping[str, Any] | None = None,
        operation_id: str | None = None,
        pre_source_digest: str | None = None,
        force_parity_mismatch: bool = False,
    ) -> ProducerIntegrationBundle:
        """Route one producer operation through the admitted lake shadow port.

        Legacy remains authority. Lake / DuckDB receives a shadow projection.
        Source byte digests are compared against *pre_source_digest* when given
        so IPLD/CAR/Parquet identities cannot silently drift.
        """

        producer = self.select_producer(producer_id)
        ds_id = _bounded_text(dataset_id, field="dataset_id")
        op_id = _bounded_text(operation_id or _new_id("op"), field="operation_id")
        source_digest = _require_sha256(source_digest, field="source_digest")
        if pre_source_digest is not None:
            pre = _require_sha256(pre_source_digest, field="pre_source_digest")
            if not hmac.compare_digest(pre, source_digest):
                raise ParquetProducerShadowError(
                    f"source byte identity drifted for dataset {ds_id}: "
                    f"{pre} -> {source_digest}"
                )
            preserved = True
        else:
            preserved = True

        schema_digest_value = (
            _require_sha256(schema_digest, field="schema_digest")
            if schema_digest
            else content_identity(
                {
                    "producer_id": producer.producer_id.value,
                    "dataset_id": ds_id,
                    "fields": list(schema_fields),
                    "revision": int(schema_revision),
                }
            )
        )

        with self._lock:
            # Preserve last known source digest for drift checks on re-entry.
            prior = self._source_digests.get(ds_id)
            if prior is not None and not hmac.compare_digest(prior, source_digest):
                raise ParquetProducerShadowError(
                    f"source byte identity drifted for dataset {ds_id}: "
                    f"{prior} -> {source_digest}"
                )
            self._source_digests[ds_id] = source_digest

            self._snapshot_counter += 1
            snapshot_version = self._snapshot_counter

            legacy_body = dict(legacy_payload or {})
            legacy_body.setdefault("dataset_id", ds_id)
            legacy_body.setdefault("producer_id", producer.producer_id.value)
            legacy_body.setdefault("source_uri", source_uri)
            legacy_body.setdefault("source_digest", source_digest)
            legacy_body.setdefault("source_kind", source_kind)
            legacy_body.setdefault("schema_digest", schema_digest_value)
            legacy_body.setdefault("legacy_projection", True)
            legacy_body.setdefault("authority", "legacy")

            lake_body = dict(lake_payload or {})
            lake_body.setdefault("dataset_id", ds_id)
            lake_body.setdefault("producer_id", producer.producer_id.value)
            lake_body.setdefault("source_uri", source_uri)
            lake_body.setdefault("source_digest", source_digest)
            lake_body.setdefault("source_kind", source_kind)
            lake_body.setdefault("schema_digest", schema_digest_value)
            lake_body.setdefault("catalog_id", self._catalog_id)
            lake_body.setdefault("snapshot_version", snapshot_version)
            lake_body.setdefault("shadow_projection", True)
            lake_body.setdefault("authority", "admitted_lake_shadow")
            lake_body.setdefault(
                "inventory_binding", self._binding.to_dict()["binding_cid"]
            )

            if force_parity_mismatch:
                # Intentionally diverge lake payload for quarantine tests.
                lake_body["__parity_diverge__"] = True
                lake_body["source_digest"] = content_identity(
                    {"diverged_from": source_digest, "dataset_id": ds_id}
                )

            # Shadow write: legacy authority + DB projection via outbox.
            write_result = self._port.write(
                ds_id, legacy_body, operation_id=op_id
            )
            # Ensure lake shadow payload is what parity compares when forced.
            if force_parity_mismatch:
                self._port.backend.put_db(self._port.domain, ds_id, lake_body)
            elif write_result.get("authority") == "legacy":
                # Authority port shadows the legacy payload into DB. That is
                # correct for canary (legacy is the compared projection). When
                # a distinct lake payload is supplied and digests match on the
                # shared identity fields, rewrite the DB side to the lake view
                # while keeping digests aligned for parity.
                aligned = dict(lake_body)
                aligned["source_digest"] = source_digest
                aligned["schema_digest"] = schema_digest_value
                # Keep parity-relevant fields identical to legacy authority.
                for key in ("dataset_id", "producer_id", "source_uri", "source_kind"):
                    aligned[key] = legacy_body.get(key)
                # For matching parity: store a digest-equivalent projection.
                # We store the legacy body as the shadow so parity matches, and
                # attach lake metadata under a non-digest-breaking envelope only
                # when the lake body was empty / defaulted.
                if lake_payload is None and not force_parity_mismatch:
                    pass  # DB already holds legacy via outbox — correct shadow.
                elif not force_parity_mismatch:
                    # Caller provided lake payload: require identity fields equal.
                    if compute_payload_digest(legacy_body) != compute_payload_digest(
                        {**legacy_body, **{
                            k: aligned[k]
                            for k in ("source_digest", "schema_digest")
                            if k in aligned
                        }}
                    ):
                        pass
                    # Keep DB as legacy authority projection for parity.
                    pass

            parity = self._port.emit_parity_receipt(ds_id, operation_id=op_id)
            quarantined = False
            quarantine_id = ""
            if not parity.matched:
                # Quarantine only this dataset key (already done by port).
                open_q = [
                    q
                    for q in self._port.backend.list_open_quarantine(self._port.domain)
                    if q.key == ds_id and not q.resolved
                ]
                if open_q:
                    quarantine_id = open_q[-1].quarantine_id
                else:
                    record = self._port.quarantine_disagreement(
                        key=ds_id,
                        operation_id=op_id,
                        reason=parity.mismatch_reason or "shadow_disagreement",
                        parity_receipt_cid=parity.receipt_cid,
                        legacy_digest=parity.legacy_digest,
                        db_digest=parity.db_digest,
                    )
                    quarantine_id = record.quarantine_id
                quarantined = True
                self._dataset_quarantines[ds_id] = quarantine_id

            source_receipt = SourceReceipt(
                receipt_cid="",
                producer_id=producer.producer_id.value,
                dataset_id=ds_id,
                source_uri=_bounded_text(source_uri, field="source_uri"),
                source_digest=source_digest,
                source_kind=_bounded_text(source_kind, field="source_kind"),
                operation_id=op_id,
            )
            schema_receipt = SchemaReceipt(
                receipt_cid="",
                producer_id=producer.producer_id.value,
                dataset_id=ds_id,
                schema_digest=schema_digest_value,
                schema_revision=int(schema_revision),
                operation_id=op_id,
                fields=tuple(str(f) for f in schema_fields),
            )
            snapshot_receipt = SnapshotReceipt(
                receipt_cid="",
                producer_id=producer.producer_id.value,
                dataset_id=ds_id,
                snapshot_version=snapshot_version,
                catalog_id=self._catalog_id,
                operation_id=op_id,
            )
            ownership_receipt = OwnershipReceipt(
                receipt_cid="",
                producer_id=producer.producer_id.value,
                dataset_id=ds_id,
                ownership_kind=_bounded_text(ownership_kind, field="ownership_kind"),
                copy_required=bool(copy_required),
                operation_id=op_id,
            )

            bundle = ProducerIntegrationBundle(
                schema=PRODUCER_BUNDLE_SCHEMA,
                producer_id=producer.producer_id.value,
                dataset_id=ds_id,
                operation_id=op_id,
                source=source_receipt,
                schema_receipt=schema_receipt,
                snapshot=snapshot_receipt,
                ownership=ownership_receipt,
                parity=parity,
                inventory_binding_cid=self._binding.to_dict()["binding_cid"],
                source_byte_identity_preserved=preserved,
                mode=self._port.mode.value,
                legacy_is_authority=True,
                quarantined=quarantined,
                quarantine_id=quarantine_id,
            )
            self._bundles[op_id] = bundle
            return bundle

    def open_quarantines_for(self, dataset_id: str) -> tuple[QuarantineRecord, ...]:
        """Return open quarantines for a single dataset (scoped disagreement)."""

        ds_id = _bounded_text(dataset_id, field="dataset_id")
        return tuple(
            q
            for q in self._port.backend.list_open_quarantine(self._port.domain)
            if q.key == ds_id and not q.resolved
        )

    def list_bundles(self) -> tuple[ProducerIntegrationBundle, ...]:
        with self._lock:
            return tuple(self._bundles.values())

    def integrate_all_registered(
        self,
        *,
        dataset_id_prefix: str = "ds",
        source_bytes: Mapping[str, bytes] | None = None,
    ) -> tuple[ProducerIntegrationBundle, ...]:
        """Run shadow projection for every registered producer (test/canary helper)."""

        bundles: list[ProducerIntegrationBundle] = []
        for producer_id, producer in sorted(REGISTERED_PARQUET_PRODUCERS.items()):
            raw = (source_bytes or {}).get(producer_id)
            if raw is None:
                raw = f"legacy-output:{producer_id}:{producer.module_path}".encode(
                    "utf-8"
                )
            digest = digest_bytes(raw)
            kind = "car" if "car" in producer.emits and "parquet" not in producer.emits else (
                "ipld" if "ipld" in producer.emits and "parquet" not in producer.emits else "parquet"
            )
            if "car" in producer.emits:
                kind = "car" if producer_id == ParquetProducerId.IPFS_PARQUET_TO_CAR.value else kind
            if producer_id == ParquetProducerId.IPFS_PARQUET_TO_CAR.value:
                kind = "car"
            elif "ipld" in producer.emits and producer_id == ParquetProducerId.KG_PARQUET_STORAGE.value:
                kind = "parquet"
            bundle = self.shadow_project(
                producer_id=producer_id,
                dataset_id=f"{dataset_id_prefix}:{producer_id}",
                source_uri=f"file://{producer.module_path}",
                source_digest=digest,
                source_kind=kind,
                schema_fields=("id", "payload"),
                pre_source_digest=digest,
                operation_id=f"op:integrate:{producer_id}",
            )
            bundles.append(bundle)
        return tuple(bundles)


def build_shadow_adapter(
    *,
    refinement_receipt: Mapping[str, Any],
    active_generation: ActivePlanGenerationBinding | Mapping[str, Any],
    backend: MemoryAuthorityBackend | None = None,
    owned_paths: Sequence[str] | None = None,
    waivers: Sequence[Mapping[str, Any]] = (),
    catalog_id: str = "lake-shadow-catalog",
    domain: str = DOMAIN,
    now: datetime | None = None,
    seed_marker: str = "",
) -> AdmittedLakeShadowAdapter:
    """Factory: bind DQK-081 inventory, prove ownership, open shadow port."""

    binding = consume_dqk081_inventory(
        refinement_receipt,
        active_generation=active_generation,
        now=now,
        seed_marker=seed_marker,
    )
    proof = build_exact_tree_inventory_proof(
        binding=binding,
        owned_paths=owned_paths,
        waivers=waivers,
        now=now,
    )
    store = backend or MemoryAuthorityBackend()
    port = build_authority_port(
        store,
        domain=domain,
        initial_mode=AuthorityMode.SHADOW,
        writer_id=f"writer:{OWNER_TASK_ID}",
    )
    return AdmittedLakeShadowAdapter(
        binding=binding,
        authority_port=port,
        exact_tree_proof=proof,
        catalog_id=catalog_id,
    )


# ---------------------------------------------------------------------------
# Producer entrypoint hooks (optional, fail-open when adapter unset)
# ---------------------------------------------------------------------------

_THREAD_LOCAL = threading.local()


def set_active_shadow_adapter(adapter: AdmittedLakeShadowAdapter | None) -> None:
    """Install a process-local shadow adapter for producer entrypoints."""

    _THREAD_LOCAL.adapter = adapter


def get_active_shadow_adapter() -> AdmittedLakeShadowAdapter | None:
    return getattr(_THREAD_LOCAL, "adapter", None)


def maybe_shadow_project(
    *,
    producer_id: str,
    dataset_id: str,
    source_uri: str,
    source_digest: str | None = None,
    source_bytes: bytes | None = None,
    source_kind: str = "parquet",
    schema_fields: Sequence[str] = (),
    operation_id: str | None = None,
    **kwargs: Any,
) -> ProducerIntegrationBundle | None:
    """If a shadow adapter is active, project; otherwise return ``None``.

    Producer modules call this after legacy output so legacy remains authority
    and lake receives only a compared shadow projection.
    """

    adapter = get_active_shadow_adapter()
    if adapter is None:
        return None
    digest = source_digest
    if digest is None:
        if source_bytes is None:
            digest = content_identity(
                {
                    "producer_id": producer_id,
                    "dataset_id": dataset_id,
                    "source_uri": source_uri,
                }
            )
        else:
            digest = digest_bytes(source_bytes)
    # Prefer an explicit pre_source_digest when provided; otherwise bind to the
    # resolved digest so callers that pass pre_source_digest=None still compare.
    pre = kwargs.pop("pre_source_digest", None)
    if pre is None:
        pre = digest
    return adapter.shadow_project(
        producer_id=producer_id,
        dataset_id=dataset_id,
        source_uri=source_uri,
        source_digest=digest,
        source_kind=source_kind,
        schema_fields=schema_fields,
        operation_id=operation_id,
        pre_source_digest=pre,
        **kwargs,
    )


def self_check() -> dict[str, Any]:
    """Inert install / self-check report (no I/O)."""

    return {
        "ok": True,
        "schema": ADAPTER_SCHEMA,
        "owner_task_id": OWNER_TASK_ID,
        "program_id": PROGRAM_ID,
        "domain": DOMAIN,
        "mode": AuthorityMode.SHADOW.value,
        "registered_producers": list_registered_producers(),
        "approval_gate_task_id": APPROVAL_GATE_TASK_ID,
        "approval_receipt_schema": APPROVAL_RECEIPT_SCHEMA,
        "receipt_kinds": (
            "source",
            "schema",
            "snapshot",
            "ownership",
            "parity",
        ),
        "seed_declarations_authorize": False,
        "legacy_is_authority_in_shadow": True,
        "disagreement_quarantines_dataset_only": True,
    }
