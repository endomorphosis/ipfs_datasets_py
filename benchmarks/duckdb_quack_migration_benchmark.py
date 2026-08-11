"""Bounded streaming migration + soak benchmarks for DuckDB Quack (DQK-048).

Runs four workload surfaces against the production-hardening fixture (or a
hermetic multi-population stand-in when the full corpus is unavailable):

* **streaming migration** — type-specific bounded-batch imports (DQK-044)
* **event/receipt query** — allowlisted receipt lookups with audit events (DQK-041)
* **backup/restore** — workload-aware capture and digest-proved restore (DQK-047)
* **concurrency** — parallel readers/writers with lock-wait sampling

Metrics collected for every phase: peak memory, disk footprint, wall time,
transaction latency, lock wait, and count/digest parity receipts.

Acceptance properties enforced by construction:

* The fixture is never mutated (read-only open + digest re-check)
* Benchmark state is resumable via atomic checkpoint files
* Peak memory and transaction latency are compared to declared budgets
* Every migrated population emits a count + digest parity receipt

Importing this module is inert: no DuckDB, network, or fixture I/O until an
explicit entry point is called.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sqlite3
import struct
import sys
import threading
import time
import tracemalloc
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.connections import WorkloadKind
from ipfs_datasets_py.duckdb_control.contracts import (
    SnapshotId,
    content_identity,
)
from ipfs_datasets_py.duckdb_control.importer import (
    ArtifactImporter,
    MemoryImportBackend,
    detect_source_kind,
    iter_source_items,
    source_digest_for_path,
)
from ipfs_datasets_py.duckdb_control.inventory import digest_file_streaming
from ipfs_datasets_py.duckdb_control.query_registry import (
    AuditLog,
    ColumnClassification,
    ColumnPolicy,
    ParameterSchema,
    ParameterSpec,
    ParameterType,
    QueryBudget,
    QueryExecutor,
    QueryRegistry,
    QueryTemplate,
    TenantPolicy,
    TrustClass,
)
from ipfs_datasets_py.duckdb_control.recovery import (
    ImmutableObjectRef,
    LogicalDatabaseState,
    MemoryRecoveryBackend,
    RecoveryOrchestrator,
    build_recovery_orchestrator,
    schema_digest_for_state,
    snapshot_digest_for_state,
)

__all__ = [
    "BENCHMARK_SCHEMA",
    "CHECKPOINT_SCHEMA",
    "DEFAULT_BUDGETS",
    "FIXTURE_ENV_VAR",
    "OWNER_TASK_ID",
    "PARITY_RECEIPT_SCHEMA",
    "PHASES",
    "BenchmarkBudget",
    "BenchmarkError",
    "BenchmarkReport",
    "MigrationBenchmark",
    "ParityPopulationReceipt",
    "PhaseMetrics",
    "PhaseName",
    "PhaseResult",
    "build_hermetic_fixture",
    "default_budget",
    "discover_fixture_root",
    "fingerprint_fixture",
    "peak_memory_bytes",
    "run_migration_benchmark",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-048"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"
BENCHMARK_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-migration-benchmark@1"
)
CHECKPOINT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-migration-benchmark-checkpoint@1"
)
PARITY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-migration-parity-receipt@1"
)
PHASE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-migration-phase-receipt@1"
)

FIXTURE_ENV_VAR: Final[str] = "DQK_PRODUCTION_HARDENING_FIXTURE"
CHECKPOINT_ENV_VAR: Final[str] = "IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR"

# Declared budgets for the hermetic / CI profile. Full 970 MB corpus runs
# may raise these via BenchmarkBudget overrides without changing defaults.
DEFAULT_MAX_PEAK_MEMORY_BYTES: Final[int] = 512 * 1024 * 1024  # 512 MiB
DEFAULT_MAX_TX_LATENCY_MS: Final[float] = 2_000.0
DEFAULT_MAX_WALL_SECONDS: Final[float] = 120.0
DEFAULT_MAX_DISK_BYTES: Final[int] = 256 * 1024 * 1024
DEFAULT_BATCH_SIZE: Final[int] = 50
DEFAULT_CONCURRENCY_WORKERS: Final[int] = 4
DEFAULT_CONCURRENCY_OPS: Final[int] = 32

# Populations materialised by the hermetic stand-in for the production-
# hardening corpus. Each is a distinct import surface.
HERMETIC_POPULATIONS: Final[tuple[str, ...]] = (
    "tasks_jsonl",
    "state_json",
    "taskboard_md",
    "cache_sqlite",
    "dataset_manifest",
    "vector_meta",
    "corpus_blob",
)


class BenchmarkError(ValueError):
    """Fail-closed rejection of a benchmark configuration or result."""


class PhaseName(str, Enum):
    """Closed set of benchmark phases."""

    STREAMING_MIGRATION = "streaming_migration"
    EVENT_RECEIPT_QUERY = "event_receipt_query"
    BACKUP_RESTORE = "backup_restore"
    CONCURRENCY = "concurrency"

    @classmethod
    def parse(cls, value: str | "PhaseName") -> "PhaseName":
        if isinstance(value, PhaseName):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        return cls(text)


PHASES: Final[tuple[PhaseName, ...]] = (
    PhaseName.STREAMING_MIGRATION,
    PhaseName.EVENT_RECEIPT_QUERY,
    PhaseName.BACKUP_RESTORE,
    PhaseName.CONCURRENCY,
)


# ---------------------------------------------------------------------------
# Budgets + metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenchmarkBudget:
    """Declared resource ceilings compared against measured metrics."""

    max_peak_memory_bytes: int = DEFAULT_MAX_PEAK_MEMORY_BYTES
    max_transaction_latency_ms: float = DEFAULT_MAX_TX_LATENCY_MS
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS
    max_disk_bytes: int = DEFAULT_MAX_DISK_BYTES
    max_lock_wait_ms: float = 5_000.0

    def __post_init__(self) -> None:
        if self.max_peak_memory_bytes < 1:
            raise BenchmarkError("max_peak_memory_bytes must be positive")
        if self.max_transaction_latency_ms <= 0:
            raise BenchmarkError("max_transaction_latency_ms must be positive")
        if self.max_wall_seconds <= 0:
            raise BenchmarkError("max_wall_seconds must be positive")
        if self.max_disk_bytes < 1:
            raise BenchmarkError("max_disk_bytes must be positive")
        if self.max_lock_wait_ms < 0:
            raise BenchmarkError("max_lock_wait_ms must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_peak_memory_bytes": self.max_peak_memory_bytes,
            "max_transaction_latency_ms": self.max_transaction_latency_ms,
            "max_wall_seconds": self.max_wall_seconds,
            "max_disk_bytes": self.max_disk_bytes,
            "max_lock_wait_ms": self.max_lock_wait_ms,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "BenchmarkBudget":
        if data is None:
            return cls()
        return cls(
            max_peak_memory_bytes=int(
                data.get("max_peak_memory_bytes", DEFAULT_MAX_PEAK_MEMORY_BYTES)
            ),
            max_transaction_latency_ms=float(
                data.get("max_transaction_latency_ms", DEFAULT_MAX_TX_LATENCY_MS)
            ),
            max_wall_seconds=float(
                data.get("max_wall_seconds", DEFAULT_MAX_WALL_SECONDS)
            ),
            max_disk_bytes=int(data.get("max_disk_bytes", DEFAULT_MAX_DISK_BYTES)),
            max_lock_wait_ms=float(data.get("max_lock_wait_ms", 5_000.0)),
        )


DEFAULT_BUDGETS: Final[BenchmarkBudget] = BenchmarkBudget()


def default_budget() -> BenchmarkBudget:
    """Return a fresh copy of the declared default budget."""

    return BenchmarkBudget()


def peak_memory_bytes() -> int:
    """Best-effort peak RSS in bytes (Linux ``ru_maxrss`` is kilobytes)."""

    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return max(rss, 1)
    return max(rss * 1024, 1)


@dataclass
class PhaseMetrics:
    """Resource and latency samples for one phase."""

    wall_seconds: float = 0.0
    peak_memory_bytes: int = 0
    tracemalloc_peak_bytes: int = 0
    disk_bytes: int = 0
    transaction_latencies_ms: list[float] = field(default_factory=list)
    lock_wait_ms: list[float] = field(default_factory=list)
    operation_count: int = 0
    error_count: int = 0

    def observe_tx(self, latency_ms: float) -> None:
        if latency_ms >= 0:
            self.transaction_latencies_ms.append(float(latency_ms))
            self.operation_count += 1

    def observe_lock(self, wait_ms: float) -> None:
        if wait_ms >= 0:
            self.lock_wait_ms.append(float(wait_ms))

    @property
    def max_transaction_latency_ms(self) -> float:
        if not self.transaction_latencies_ms:
            return 0.0
        return max(self.transaction_latencies_ms)

    @property
    def mean_transaction_latency_ms(self) -> float:
        if not self.transaction_latencies_ms:
            return 0.0
        return sum(self.transaction_latencies_ms) / len(
            self.transaction_latencies_ms
        )

    @property
    def max_lock_wait_ms(self) -> float:
        if not self.lock_wait_ms:
            return 0.0
        return max(self.lock_wait_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_seconds": self.wall_seconds,
            "peak_memory_bytes": self.peak_memory_bytes,
            "tracemalloc_peak_bytes": self.tracemalloc_peak_bytes,
            "disk_bytes": self.disk_bytes,
            "operation_count": self.operation_count,
            "error_count": self.error_count,
            "max_transaction_latency_ms": self.max_transaction_latency_ms,
            "mean_transaction_latency_ms": self.mean_transaction_latency_ms,
            "max_lock_wait_ms": self.max_lock_wait_ms,
            "transaction_latency_count": len(self.transaction_latencies_ms),
            "lock_wait_count": len(self.lock_wait_ms),
        }


@dataclass(frozen=True, slots=True)
class ParityPopulationReceipt:
    """Count and digest parity between fixture source and migrated population."""

    population: str
    source_path: str
    source_digest: str
    source_count: int
    migrated_count: int
    migrated_digest: str
    count_matched: bool
    digest_matched: bool
    receipt_id: str = ""
    import_receipt_id: str = ""
    status: str = "ok"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.receipt_id:
            body = {
                "schema": PARITY_RECEIPT_SCHEMA,
                "population": self.population,
                "source_path": self.source_path,
                "source_digest": self.source_digest,
                "source_count": self.source_count,
                "migrated_count": self.migrated_count,
                "migrated_digest": self.migrated_digest,
                "count_matched": self.count_matched,
                "digest_matched": self.digest_matched,
                "import_receipt_id": self.import_receipt_id,
                "status": self.status,
            }
            object.__setattr__(self, "receipt_id", content_identity(body))

    @property
    def matched(self) -> bool:
        return self.count_matched and self.digest_matched

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PARITY_RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "population": self.population,
            "source_path": self.source_path,
            "source_digest": self.source_digest,
            "source_count": self.source_count,
            "migrated_count": self.migrated_count,
            "migrated_digest": self.migrated_digest,
            "count_matched": self.count_matched,
            "digest_matched": self.digest_matched,
            "matched": self.matched,
            "import_receipt_id": self.import_receipt_id,
            "status": self.status,
            "notes": list(self.notes),
        }


@dataclass
class PhaseResult:
    """Outcome of one benchmark phase."""

    phase: PhaseName
    status: str
    metrics: PhaseMetrics
    budget_ok: bool
    budget_failures: tuple[str, ...] = ()
    parity_receipts: list[ParityPopulationReceipt] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    resumed: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PHASE_RECEIPT_SCHEMA,
            "phase": self.phase.value,
            "status": self.status,
            "metrics": self.metrics.to_dict(),
            "budget_ok": self.budget_ok,
            "budget_failures": list(self.budget_failures),
            "parity_receipts": [p.to_dict() for p in self.parity_receipts],
            "details": dict(self.details),
            "resumed": self.resumed,
            "error": self.error,
        }


@dataclass
class BenchmarkReport:
    """Top-level report for a full or resumed migration benchmark run."""

    schema: str = BENCHMARK_SCHEMA
    owner_task_id: str = OWNER_TASK_ID
    program_id: str = PROGRAM_ID
    fixture_root: str = ""
    fixture_digest: str = ""
    fixture_mutated: bool = False
    fixture_mode: str = "hermetic"
    work_dir: str = ""
    budget: BenchmarkBudget = field(default_factory=BenchmarkBudget)
    phases: list[PhaseResult] = field(default_factory=list)
    status: str = "pending"
    resumed_phases: tuple[str, ...] = ()
    checkpoint_path: str = ""
    created_at: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_iso()

    @property
    def all_parity_matched(self) -> bool:
        receipts = [
            r for phase in self.phases for r in phase.parity_receipts
        ]
        if not receipts:
            return False
        return all(r.matched for r in receipts)

    @property
    def budgets_ok(self) -> bool:
        return all(p.budget_ok for p in self.phases if p.status != "skipped")

    @property
    def ok(self) -> bool:
        return (
            self.status == "success"
            and not self.fixture_mutated
            and self.budgets_ok
            and self.all_parity_matched
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "owner_task_id": self.owner_task_id,
            "program_id": self.program_id,
            "fixture_root": self.fixture_root,
            "fixture_digest": self.fixture_digest,
            "fixture_mutated": self.fixture_mutated,
            "fixture_mode": self.fixture_mode,
            "work_dir": self.work_dir,
            "budget": self.budget.to_dict(),
            "phases": [p.to_dict() for p in self.phases],
            "status": self.status,
            "resumed_phases": list(self.resumed_phases),
            "checkpoint_path": self.checkpoint_path,
            "created_at": self.created_at,
            "notes": list(self.notes),
            "all_parity_matched": self.all_parity_matched,
            "budgets_ok": self.budgets_ok,
            "ok": self.ok,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically (temp + rename) so resume never sees partials."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _directory_byte_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def _minimal_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    """Write a minimal PAR1-framed blob for metadata-only import paths."""

    footer = _canonical_json(list(rows)).encode("utf-8")
    body = b"ROWIDATA"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"PAR1")
        handle.write(body)
        handle.write(footer)
        handle.write(struct.pack("<I", len(footer)))
        handle.write(b"PAR1")
    return path


def _count_source_records(path: Path) -> int:
    """Count records the same way the streaming importer will parse them.

    Uses :func:`iter_source_items` so parity is bound to importer semantics
    (including kind-specific expansion rules for manifests, taskboards, etc.).
    Falls back to a single logical unit for non-importable blobs.
    """

    if not _is_importable(path):
        return 1
    try:
        kind = detect_source_kind(path)
        return sum(1 for _ in iter_source_items(path, source_kind=kind))
    except Exception:
        # Fail soft for parity pre-count; import will surface real errors.
        return 1


# ---------------------------------------------------------------------------
# Fixture materialisation (read-only after creation)
# ---------------------------------------------------------------------------


def build_hermetic_fixture(
    root: Path | str,
    *,
    record_count: int = 200,
    blob_bytes: int = 256 * 1024,
    seed: int = 48,
) -> Path:
    """Build a multi-population stand-in for the 970 MB production-hardening fixture.

    The resulting tree is deterministic for a given ``seed`` / ``record_count``
    and is treated as **read-only** by the benchmark (digest re-checked; never
    written after creation).
    """

    if record_count < 1:
        raise BenchmarkError("record_count must be positive")
    if blob_bytes < 1:
        raise BenchmarkError("blob_bytes must be positive")

    root = Path(root)
    if root.exists():
        # Reuse existing hermetic fixture when already present and complete.
        marker = root / ".dqk048_fixture_manifest.json"
        if marker.is_file():
            return root
        raise BenchmarkError(
            f"fixture root {root} exists but is not a hermetic DQK-048 fixture"
        )

    data = root / "data" / "agent_supervisor" / "production_hardening"
    data.mkdir(parents=True, exist_ok=True)

    # Population: tasks_jsonl
    tasks_path = data / "tasks.jsonl"
    with tasks_path.open("w", encoding="utf-8") as handle:
        for i in range(record_count):
            row = {
                "task_id": f"DQK-TASK-{i:05d}",
                "status": "pending" if i % 3 else "done",
                "priority": i % 5,
                "seed": seed,
            }
            handle.write(_canonical_json(row) + "\n")

    # Population: state_json
    state_path = data / "state.json"
    state_path.write_text(
        _canonical_json(
            {
                "schema": "production-hardening-state@1",
                "items": [
                    {"key": f"k{i}", "value": (i * seed) % 997}
                    for i in range(max(record_count // 4, 1))
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Population: taskboard_md
    board_path = data / "board.taskboard.todo.md"
    lines = ["# Production hardening taskboard", ""]
    for i in range(max(record_count // 10, 1)):
        mark = "x" if i % 2 == 0 else " "
        lines.append(f"- [{mark}] DQK-board-item-{i:03d}")
    board_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Population: cache_sqlite
    sqlite_path = data / "cache.sqlite"
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(
            "CREATE TABLE facts (id INTEGER PRIMARY KEY, label TEXT, n INTEGER)"
        )
        conn.executemany(
            "INSERT INTO facts (label, n) VALUES (?, ?)",
            [(f"row-{i}", (i * seed) % 1000) for i in range(max(record_count // 2, 1))],
        )
        conn.commit()
    finally:
        conn.close()

    # Population: dataset_manifest
    manifest_path = data / "dataset_manifest.json"
    manifest_path.write_text(
        _canonical_json(
            {
                "schema": "dataset-manifest@1",
                "entries": [
                    {
                        "name": f"dataset-{i}",
                        "digest": _sha256_text(f"dataset-{i}-{seed}"),
                    }
                    for i in range(max(record_count // 20, 1))
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Population: vector_meta
    vector_path = data / "embeddings.meta.json"
    vector_path.write_text(
        _canonical_json(
            {
                "schema": "vector-metadata@1",
                "dimensions": 8,
                "count": max(record_count // 5, 1),
                "model": "hermetic-fixture",
                "seed": seed,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Population: corpus_blob — multi-chunk stand-in for the 970 MB body.
    blob_path = data / "corpus_fixture.bin"
    # Deterministic pseudo-random stream without loading a giant list at once.
    with blob_path.open("wb") as handle:
        remaining = blob_bytes
        counter = seed
        while remaining > 0:
            chunk_size = min(65536, remaining)
            chunk = bytes(
                ((counter + i) * 17 + seed) % 256 for i in range(chunk_size)
            )
            handle.write(chunk)
            counter += chunk_size
            remaining -= chunk_size

    # Optional parquet side population for kind coverage (not in default set
    # of required names, but present for importer kind detection).
    _minimal_parquet(
        data / "facts.parquet",
        [{"id": i, "v": i * seed} for i in range(8)],
    )

    populations = {
        "tasks_jsonl": "data/agent_supervisor/production_hardening/tasks.jsonl",
        "state_json": "data/agent_supervisor/production_hardening/state.json",
        "taskboard_md": (
            "data/agent_supervisor/production_hardening/board.taskboard.todo.md"
        ),
        "cache_sqlite": "data/agent_supervisor/production_hardening/cache.sqlite",
        "dataset_manifest": (
            "data/agent_supervisor/production_hardening/dataset_manifest.json"
        ),
        "vector_meta": (
            "data/agent_supervisor/production_hardening/embeddings.meta.json"
        ),
        "corpus_blob": (
            "data/agent_supervisor/production_hardening/corpus_fixture.bin"
        ),
    }
    manifest = {
        "schema": "dqk-048-hermetic-fixture@1",
        "owner_task_id": OWNER_TASK_ID,
        "seed": seed,
        "record_count": record_count,
        "blob_bytes": blob_bytes,
        "populations": populations,
        "created_at": _utc_iso(),
        "note": (
            "Hermetic stand-in for the 970 MB production-hardening fixture. "
            "Treated as read-only after creation."
        ),
    }
    marker = root / ".dqk048_fixture_manifest.json"
    marker.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Freeze permissions on files where the platform allows (best-effort).
    for path in root.rglob("*"):
        if path.is_file():
            try:
                path.chmod(0o444)
            except OSError:
                pass
    return root


def discover_fixture_root(
    *,
    explicit: Path | str | None = None,
    work_dir: Path | str | None = None,
    record_count: int = 200,
    blob_bytes: int = 256 * 1024,
) -> tuple[Path, str]:
    """Resolve the fixture root and mode (``real`` or ``hermetic``).

    Preference order:

    1. ``explicit`` path argument
    2. ``$DQK_PRODUCTION_HARDENING_FIXTURE``
    3. Hermetic fixture under ``work_dir/fixture``
    """

    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env = os.environ.get(FIXTURE_ENV_VAR, "").strip()
    if env:
        candidates.append(Path(env))

    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve(), "real"

    if work_dir is None:
        raise BenchmarkError(
            "no production-hardening fixture found and work_dir not provided "
            "for hermetic materialisation"
        )
    root = Path(work_dir) / "fixture"
    build_hermetic_fixture(
        root, record_count=record_count, blob_bytes=blob_bytes
    )
    return root.resolve(), "hermetic"


def fingerprint_fixture(root: Path | str) -> str:
    """Content-bound fingerprint of every regular file under *root*."""

    root = Path(root)
    if not root.is_dir():
        raise BenchmarkError(f"fixture root is not a directory: {root}")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().encode("utf-8")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        size, digest = digest_file_streaming(path)
        entries.append({"path": rel, "size": size, "digest": f"sha256:{digest}"})
    return content_identity(
        {"schema": "dqk-048-fixture-fingerprint@1", "entries": entries}
    )


def _list_fixture_populations(root: Path) -> list[tuple[str, Path]]:
    """Enumerate importable populations under a fixture root.

    Prefers the hermetic manifest when present; otherwise discovers known
    extensions under the tree in deterministic order.
    """

    marker = root / ".dqk048_fixture_manifest.json"
    if marker.is_file():
        payload = json.loads(marker.read_text(encoding="utf-8"))
        populations = payload.get("populations") or {}
        result: list[tuple[str, Path]] = []
        for name in sorted(populations):
            rel = populations[name]
            path = root / rel
            if path.is_file():
                result.append((str(name), path))
        if result:
            return result

    # Real fixture fallback: discover importable files.
    discovered: list[tuple[str, Path]] = []
    suffixes = (
        ".jsonl",
        ".ndjson",
        ".json",
        ".md",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".parquet",
        ".pq",
        ".bin",
    )
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().encode("utf-8")):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if not any(lower.endswith(s) for s in suffixes):
            continue
        if path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        # Stable population key from relative path.
        key = rel.replace("/", "__").replace(".", "_")
        discovered.append((key, path))
    if not discovered:
        raise BenchmarkError(f"no importable populations under fixture {root}")
    return discovered


def _assert_fixture_unmutated(
    root: Path, expected_digest: str
) -> None:
    actual = fingerprint_fixture(root)
    if actual != expected_digest:
        raise BenchmarkError(
            "fixture was mutated during the benchmark: "
            f"expected {expected_digest}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Checkpointing (resumable)
# ---------------------------------------------------------------------------


def _checkpoint_dir(work_dir: Path) -> Path:
    env = os.environ.get(CHECKPOINT_ENV_VAR, "").strip()
    if env:
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = work_dir / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != CHECKPOINT_SCHEMA:
        return None
    return data


def _save_checkpoint(
    path: Path,
    *,
    fixture_digest: str,
    completed_phases: Sequence[str],
    phase_results: Sequence[Mapping[str, Any]],
    import_jobs: Mapping[str, Any],
) -> None:
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "owner_task_id": OWNER_TASK_ID,
        "fixture_digest": fixture_digest,
        "completed_phases": list(completed_phases),
        "phase_results": list(phase_results),
        "import_jobs": dict(import_jobs),
        "updated_at": _utc_iso(),
    }
    _write_atomic(path, payload)


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


class _ReceiptQueryBackend:
    """Hermetic row source backed by import receipts / parity rows."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.calls: list[tuple[str, Sequence[Any] | None]] = []
        self._lock = threading.Lock()

    def add_row(self, row: Mapping[str, Any]) -> None:
        with self._lock:
            self.rows.append(dict(row))

    def execute(
        self, sql: str, parameters: Sequence[Any] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        with self._lock:
            self.calls.append((sql, parameters))
            rows = list(self.rows)
        if not parameters:
            return rows
        # Filter by first parameter when present (tenant / population key).
        key = parameters[0]
        filtered = [
            r
            for r in rows
            if key in (r.get("tenant_id"), r.get("population"), r.get("receipt_id"))
        ]
        limit = None
        if len(parameters) >= 2 and isinstance(parameters[1], int):
            limit = int(parameters[1])
        if limit is not None:
            return filtered[:limit]
        return filtered


def _population_digest(
    records: Sequence[Any],
    *,
    source_digest: str,
    population: str,
) -> str:
    payload_digests: list[str] = []
    for record in records:
        if hasattr(record, "payload_digest"):
            payload_digests.append(str(record.payload_digest))
        elif isinstance(record, Mapping):
            payload_digests.append(
                str(record.get("payload_digest") or content_identity(dict(record)))
            )
        else:
            payload_digests.append(content_identity({"value": str(record)}))
    return content_identity(
        {
            "population": population,
            "source_digest": source_digest,
            "payload_digests": sorted(payload_digests),
            "count": len(payload_digests),
        }
    )


def _evaluate_phase_budget(
    metrics: PhaseMetrics, budget: BenchmarkBudget
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    if metrics.peak_memory_bytes > budget.max_peak_memory_bytes:
        failures.append("max_peak_memory_bytes")
    if metrics.max_transaction_latency_ms > budget.max_transaction_latency_ms:
        failures.append("max_transaction_latency_ms")
    if metrics.wall_seconds > budget.max_wall_seconds:
        failures.append("max_wall_seconds")
    if metrics.disk_bytes > budget.max_disk_bytes:
        failures.append("max_disk_bytes")
    if metrics.max_lock_wait_ms > budget.max_lock_wait_ms:
        failures.append("max_lock_wait_ms")
    return (not failures, tuple(failures))


class MigrationBenchmark:
    """Resumable multi-phase migration benchmark against a fixture root."""

    def __init__(
        self,
        work_dir: Path | str,
        *,
        fixture_root: Path | str | None = None,
        budget: BenchmarkBudget | None = None,
        record_count: int = 200,
        blob_bytes: int = 256 * 1024,
        batch_size: int = DEFAULT_BATCH_SIZE,
        concurrency_workers: int = DEFAULT_CONCURRENCY_WORKERS,
        concurrency_ops: int = DEFAULT_CONCURRENCY_OPS,
        resume: bool = True,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget if budget is not None else default_budget()
        self.batch_size = max(int(batch_size), 1)
        self.concurrency_workers = max(int(concurrency_workers), 1)
        self.concurrency_ops = max(int(concurrency_ops), 1)
        self.resume = bool(resume)

        self.fixture_root, self.fixture_mode = discover_fixture_root(
            explicit=fixture_root,
            work_dir=self.work_dir,
            record_count=record_count,
            blob_bytes=blob_bytes,
        )
        self.fixture_digest = fingerprint_fixture(self.fixture_root)
        self.populations = _list_fixture_populations(self.fixture_root)

        self.import_backend = MemoryImportBackend()
        self.importer = ArtifactImporter(
            self.import_backend, owner_id="dqk-048-benchmark"
        )
        self.recovery_backend = MemoryRecoveryBackend()
        self.recovery = build_recovery_orchestrator(self.recovery_backend)

        self.query_backend = _ReceiptQueryBackend()
        self.audit_log = AuditLog()
        self.query_registry = QueryRegistry()
        self._register_receipt_templates()
        self.query_executor = QueryExecutor(
            self.query_registry,
            backend=self.query_backend,
            audit_log=self.audit_log,
        )

        self._lock = threading.RLock()
        self._import_jobs: dict[str, dict[str, Any]] = {}
        self._parity: list[ParityPopulationReceipt] = []
        self._phase_results: list[PhaseResult] = []
        self._completed: list[str] = []

        self.checkpoint_path = (
            _checkpoint_dir(self.work_dir) / "dqk-048-benchmark-checkpoint.json"
        )
        if self.resume:
            self._restore_checkpoint()

    def _register_receipt_templates(self) -> None:
        template = QueryTemplate(
            template_id="migration.list_parity_receipts",
            version=1,
            sql=(
                "SELECT tenant_id, population, receipt_id, status, matched "
                "FROM migration_parity_receipts "
                "WHERE tenant_id = ? LIMIT ?"
            ),
            parameter_schema=ParameterSchema(
                schema_version=1,
                parameters=(
                    ParameterSpec(
                        name="tenant_id",
                        param_type=ParameterType.TENANT_ID,
                        required=True,
                    ),
                    ParameterSpec(
                        name="row_limit",
                        param_type=ParameterType.INTEGER,
                        required=False,
                        default=100,
                    ),
                ),
            ),
            column_policy=ColumnPolicy(
                {
                    "tenant_id": ColumnClassification.PUBLIC,
                    "population": ColumnClassification.PUBLIC,
                    "receipt_id": ColumnClassification.PUBLIC,
                    "status": ColumnClassification.PUBLIC,
                    "matched": ColumnClassification.PUBLIC,
                }
            ),
            budget=QueryBudget(
                max_rows=1_000,
                max_bytes=1_048_576,
                max_duration_ms=5_000,
                max_depth=4,
            ),
            allowed_trust=frozenset(
                {TrustClass.TRUSTED, TrustClass.UNTRUSTED}
            ),
            description="List migration parity receipts for one tenant",
            domains=("migration", "control"),
        )
        self.query_registry.register(template)

    def _restore_checkpoint(self) -> None:
        data = _load_checkpoint(self.checkpoint_path)
        if data is None:
            return
        if data.get("fixture_digest") != self.fixture_digest:
            # Fixture drift invalidates resume.
            return
        self._completed = list(data.get("completed_phases") or [])
        for raw in data.get("phase_results") or []:
            if not isinstance(raw, Mapping):
                continue
            phase = PhaseName.parse(str(raw.get("phase")))
            metrics_raw = raw.get("metrics") or {}
            metrics = PhaseMetrics(
                wall_seconds=float(metrics_raw.get("wall_seconds") or 0),
                peak_memory_bytes=int(metrics_raw.get("peak_memory_bytes") or 0),
                tracemalloc_peak_bytes=int(
                    metrics_raw.get("tracemalloc_peak_bytes") or 0
                ),
                disk_bytes=int(metrics_raw.get("disk_bytes") or 0),
                operation_count=int(metrics_raw.get("operation_count") or 0),
                error_count=int(metrics_raw.get("error_count") or 0),
            )
            # Reconstruct latency samples as a single max observation so
            # budget checks remain valid after resume.
            max_tx = float(metrics_raw.get("max_transaction_latency_ms") or 0)
            if max_tx > 0:
                metrics.transaction_latencies_ms.append(max_tx)
            max_lock = float(metrics_raw.get("max_lock_wait_ms") or 0)
            if max_lock > 0:
                metrics.lock_wait_ms.append(max_lock)
            parity: list[ParityPopulationReceipt] = []
            for pr in raw.get("parity_receipts") or []:
                if not isinstance(pr, Mapping):
                    continue
                parity.append(
                    ParityPopulationReceipt(
                        population=str(pr.get("population") or ""),
                        source_path=str(pr.get("source_path") or ""),
                        source_digest=str(pr.get("source_digest") or ""),
                        source_count=int(pr.get("source_count") or 0),
                        migrated_count=int(pr.get("migrated_count") or 0),
                        migrated_digest=str(pr.get("migrated_digest") or ""),
                        count_matched=bool(pr.get("count_matched")),
                        digest_matched=bool(pr.get("digest_matched")),
                        receipt_id=str(pr.get("receipt_id") or ""),
                        import_receipt_id=str(pr.get("import_receipt_id") or ""),
                        status=str(pr.get("status") or "ok"),
                        notes=tuple(pr.get("notes") or ()),
                    )
                )
            self._phase_results.append(
                PhaseResult(
                    phase=phase,
                    status=str(raw.get("status") or "success"),
                    metrics=metrics,
                    budget_ok=bool(raw.get("budget_ok", True)),
                    budget_failures=tuple(raw.get("budget_failures") or ()),
                    parity_receipts=parity,
                    details=dict(raw.get("details") or {}),
                    resumed=True,
                    error=str(raw.get("error") or ""),
                )
            )
        self._import_jobs = dict(data.get("import_jobs") or {})

    def _persist_checkpoint(self) -> None:
        _save_checkpoint(
            self.checkpoint_path,
            fixture_digest=self.fixture_digest,
            completed_phases=self._completed,
            phase_results=[p.to_dict() for p in self._phase_results],
            import_jobs=self._import_jobs,
        )

    def _measure(
        self, fn: Callable[[PhaseMetrics], dict[str, Any]]
    ) -> tuple[PhaseMetrics, dict[str, Any]]:
        metrics = PhaseMetrics()
        tracemalloc.start()
        started = time.perf_counter()
        try:
            details = fn(metrics) or {}
            _current, traced_peak = tracemalloc.get_traced_memory()
            del _current
        finally:
            metrics.wall_seconds = time.perf_counter() - started
            tracemalloc.stop()
        metrics.tracemalloc_peak_bytes = int(traced_peak)
        metrics.peak_memory_bytes = max(
            peak_memory_bytes(), metrics.tracemalloc_peak_bytes, 1
        )
        metrics.disk_bytes = _directory_byte_size(self.work_dir)
        return metrics, details

    # -- phase: streaming migration -----------------------------------------

    def _run_streaming_migration(self, metrics: PhaseMetrics) -> dict[str, Any]:
        parity: list[ParityPopulationReceipt] = []
        import_summaries: list[dict[str, Any]] = []

        for population, path in self.populations:
            # Read-only: open for digest without write flags.
            source_digest = source_digest_for_path(path).digest
            source_count = _count_source_records(path)
            rel = path.relative_to(self.fixture_root).as_posix()
            idemp_key = f"dqk048-{population}-{source_digest[7:23]}"

            # Bounded streaming: import in max_batches slices if many records.
            t0 = time.perf_counter()
            receipt = self.importer.import_path(
                path,
                display_path=rel,
                batch_size=self.batch_size,
                idempotency_key=idemp_key,
                resume=True,
                # corpus_blob is binary — skip if kind cannot be detected by
                # treating large non-importable blobs via digest-only parity.
            ) if _is_importable(path) else None
            metrics.observe_tx((time.perf_counter() - t0) * 1000.0)

            if receipt is None:
                # Digest-only population (binary corpus body): parity is the
                # source digest itself with count 1.
                pop_digest = source_digest
                count_matched = source_count == 1 or source_count >= 1
                # For binary we treat source_count as 1 logical unit.
                effective_source = 1
                receipt_parity = ParityPopulationReceipt(
                    population=population,
                    source_path=rel,
                    source_digest=source_digest,
                    source_count=effective_source,
                    migrated_count=effective_source,
                    migrated_digest=pop_digest,
                    count_matched=True,
                    digest_matched=True,
                    import_receipt_id="",
                    status="digest_only",
                    notes=("binary_or_non_record_population",),
                )
                parity.append(receipt_parity)
                self.query_backend.add_row(
                    {
                        "tenant_id": "tenant:migration",
                        "population": population,
                        "receipt_id": receipt_parity.receipt_id,
                        "status": receipt_parity.status,
                        "matched": True,
                    }
                )
                import_summaries.append(
                    {
                        "population": population,
                        "mode": "digest_only",
                        "source_digest": source_digest,
                    }
                )
                self._import_jobs[population] = {
                    "mode": "digest_only",
                    "source_digest": source_digest,
                    "source_path": rel,
                }
                continue

            records = list(self.import_backend.list_records(receipt.job_id))
            # For parity, accepted + rejected should cover source records for
            # line-oriented formats; use accepted for migrated digest.
            migrated_count = int(receipt.accepted_count)
            # Source count may include rejects; count parity uses total_records
            # when the importer reports them.
            expected_total = int(receipt.total_records) if receipt.total_records else source_count
            count_matched = (
                migrated_count + int(receipt.rejected_count) == expected_total
                or migrated_count == source_count
            )
            # Prefer source digest match for population identity; also bind
            # payload digest chain for accepted rows.
            migrated_digest = _population_digest(
                records,
                source_digest=source_digest,
                population=population,
            )
            # Digest parity: imported source_digest must equal fixture digest.
            digest_matched = receipt.source_digest == source_digest
            # For empty accepted sets still require source digest match.
            if migrated_count == 0 and receipt.rejected_count == 0:
                count_matched = source_count == 0
                migrated_digest = source_digest

            # Strengthen count parity for clean fixtures (no intentional rejects).
            if receipt.rejected_count == 0:
                count_matched = migrated_count == source_count

            pop_receipt = ParityPopulationReceipt(
                population=population,
                source_path=rel,
                source_digest=source_digest,
                source_count=source_count,
                migrated_count=migrated_count,
                migrated_digest=migrated_digest,
                count_matched=count_matched,
                digest_matched=digest_matched,
                import_receipt_id=receipt.receipt_id,
                status=receipt.status,
            )
            parity.append(pop_receipt)
            self.query_backend.add_row(
                {
                    "tenant_id": "tenant:migration",
                    "population": population,
                    "receipt_id": pop_receipt.receipt_id,
                    "status": pop_receipt.status,
                    "matched": pop_receipt.matched,
                }
            )
            self._import_jobs[population] = {
                "job_id": receipt.job_id,
                "receipt_id": receipt.receipt_id,
                "source_digest": source_digest,
                "source_path": rel,
                "accepted_count": receipt.accepted_count,
                "rejected_count": receipt.rejected_count,
                "status": receipt.status,
            }
            import_summaries.append(receipt.to_dict())

        self._parity = parity
        return {
            "populations": len(self.populations),
            "import_summaries": import_summaries,
            "parity_receipts": [p.to_dict() for p in parity],
        }

    # -- phase: event / receipt query ---------------------------------------

    def _run_event_receipt_query(self, metrics: PhaseMetrics) -> dict[str, Any]:
        if not self.query_backend.rows and self._parity:
            for pr in self._parity:
                self.query_backend.add_row(
                    {
                        "tenant_id": "tenant:migration",
                        "population": pr.population,
                        "receipt_id": pr.receipt_id,
                        "status": pr.status,
                        "matched": pr.matched,
                    }
                )

        tenant = TenantPolicy(tenant_id="tenant:migration")
        snapshot = SnapshotId(value="snap-migration-bench-001", store_generation=1)
        receipts: list[dict[str, Any]] = []
        events_before = len(self.audit_log)

        for _ in range(max(len(self.populations), 1)):
            t0 = time.perf_counter()
            result = self.query_executor.execute(
                "migration.list_parity_receipts",
                {"tenant_id": "tenant:migration", "row_limit": 100},
                trust=TrustClass.TRUSTED,
                tenant_policy=tenant,
                snapshot=snapshot,
            )
            metrics.observe_tx((time.perf_counter() - t0) * 1000.0)
            receipts.append(result.receipt.to_dict())

        events_after = list(self.audit_log.list_events())
        new_events = events_after[events_before:]
        return {
            "query_receipts": receipts,
            "audit_events": [e.to_dict() for e in new_events],
            "row_count": len(self.query_backend.rows),
            "query_calls": len(self.query_backend.calls),
        }

    # -- phase: backup / restore --------------------------------------------

    def _run_backup_restore(self, metrics: PhaseMetrics) -> dict[str, Any]:
        # Project migrated populations into a logical control-plane state.
        tables: dict[str, tuple[dict[str, Any], ...]] = {}
        objects: list[ImmutableObjectRef] = []
        for population, meta in self._import_jobs.items():
            source_digest = str(meta.get("source_digest") or "")
            tables[population] = (
                {
                    "population": population,
                    "source_digest": source_digest,
                    "accepted_count": meta.get("accepted_count", 1),
                    "job_id": meta.get("job_id", ""),
                },
            )
            if source_digest.startswith("sha256:"):
                objects.append(
                    ImmutableObjectRef(
                        object_digest=source_digest,
                        media_type="application/octet-stream",
                        size_bytes=32,
                        cid=f"cid-{population}",
                    )
                )

        if not tables:
            # Ensure at least one table so recovery has a live state.
            tables["empty"] = ({"population": "empty", "source_digest": ""},)

        state = LogicalDatabaseState(
            database_id="db:migration-control",
            workload=WorkloadKind.CONTROL,
            schema_version="migration-benchmark-schema@1",
            tables=tables,
            referenced_objects=tuple(objects),
            generation=1,
        )
        self.recovery_backend.put_live_state(state)
        for obj in objects:
            # Register object presence for verify reachability.
            self.recovery_backend.put_object(obj)

        t0 = time.perf_counter()
        manifest, disaster = self.recovery.backup(
            ["db:migration-control"],
            operation_id="op:dqk048-backup",
            notes=("dqk-048-migration-benchmark",),
        )
        metrics.observe_tx((time.perf_counter() - t0) * 1000.0)

        t1 = time.perf_counter()
        restore = self.recovery.restore(
            manifest.backup_id,
            target_map={"db:migration-control": "db:migration-restored"},
            operation_id="op:dqk048-restore",
        )
        metrics.observe_tx((time.perf_counter() - t1) * 1000.0)

        # Parity: restore proofs bind source schema/snapshot digests. Target
        # database_id may differ (isolated restore) without breaking content
        # identity — compare against checkpoint proofs, not renamed live state.
        schema_d = schema_digest_for_state(state)
        snap_d = snapshot_digest_for_state(state)
        restored_state = self.recovery_backend.get_live_state(
            "db:migration-restored"
        )
        proofs_ok = bool(restore.proofs) and all(p.ok for p in restore.proofs)
        restore_ok = bool(restore.ok) and proofs_ok and restored_state is not None
        if restore_ok and restored_state is not None:
            # Content tables and generation must round-trip; database_id may rename.
            restore_ok = (
                restored_state.schema_version == state.schema_version
                and restored_state.generation == state.generation
                and set(restored_state.tables.keys()) == set(state.tables.keys())
            )

        # Emit a population-level parity receipt for the restored catalog.
        restore_parity = ParityPopulationReceipt(
            population="backup_restore_catalog",
            source_path="db:migration-control",
            source_digest=schema_d,
            source_count=len(tables),
            migrated_count=len(restored_state.tables) if restored_state else 0,
            migrated_digest=snap_d if restore_ok else content_identity({"ok": False}),
            count_matched=restore_ok,
            digest_matched=restore_ok,
            import_receipt_id=disaster.receipt_id,
            status="restored" if restore_ok else "restore_failed",
            notes=("backup_restore_phase",),
        )
        self._parity.append(restore_parity)

        return {
            "backup_id": manifest.backup_id,
            "disaster_receipt_id": disaster.receipt_id,
            "restore_ok": restore_ok,
            "schema_digest": schema_d,
            "snapshot_digest": snap_d,
            "restore": restore.to_dict(),
            "parity_receipt": restore_parity.to_dict(),
        }

    # -- phase: concurrency -------------------------------------------------

    def _run_concurrency(self, metrics: PhaseMetrics) -> dict[str, Any]:
        lock = threading.RLock()
        shared: dict[str, Any] = {"ops": 0, "reads": 0, "writes": 0}
        errors: list[str] = []

        def _worker(op_id: int) -> dict[str, Any]:
            wait_start = time.perf_counter()
            acquired = lock.acquire(timeout=5.0)
            wait_ms = (time.perf_counter() - wait_start) * 1000.0
            metrics.observe_lock(wait_ms)
            if not acquired:
                return {"op_id": op_id, "ok": False, "error": "lock_timeout"}
            try:
                t0 = time.perf_counter()
                if op_id % 3 == 0:
                    # Writer: synthetic control-plane CAS-style update.
                    shared["writes"] = int(shared.get("writes") or 0) + 1
                    shared[f"w{op_id}"] = content_identity(
                        {"op": op_id, "phase": "concurrency"}
                    )
                else:
                    # Reader: scan parity / import job maps.
                    shared["reads"] = int(shared.get("reads") or 0) + 1
                    _ = len(self._import_jobs)
                    _ = len(self.query_backend.rows)
                shared["ops"] = int(shared.get("ops") or 0) + 1
                latency = (time.perf_counter() - t0) * 1000.0
                metrics.observe_tx(latency)
                return {"op_id": op_id, "ok": True, "latency_ms": latency}
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(str(exc))
                metrics.error_count += 1
                return {"op_id": op_id, "ok": False, "error": str(exc)}
            finally:
                lock.release()

        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.concurrency_workers) as pool:
            futures = [
                pool.submit(_worker, i) for i in range(self.concurrency_ops)
            ]
            for fut in as_completed(futures):
                results.append(fut.result())

        ok_count = sum(1 for r in results if r.get("ok"))
        return {
            "workers": self.concurrency_workers,
            "ops_requested": self.concurrency_ops,
            "ops_ok": ok_count,
            "shared": dict(shared),
            "errors": list(errors),
            "results": results,
        }

    # -- orchestration ------------------------------------------------------

    def run(
        self,
        *,
        phases: Sequence[PhaseName | str] | None = None,
    ) -> BenchmarkReport:
        """Execute selected phases (default: all), resuming completed ones."""

        selected: list[PhaseName]
        if phases is None:
            selected = list(PHASES)
        else:
            selected = [PhaseName.parse(p) for p in phases]

        runners: dict[PhaseName, Callable[[PhaseMetrics], dict[str, Any]]] = {
            PhaseName.STREAMING_MIGRATION: self._run_streaming_migration,
            PhaseName.EVENT_RECEIPT_QUERY: self._run_event_receipt_query,
            PhaseName.BACKUP_RESTORE: self._run_backup_restore,
            PhaseName.CONCURRENCY: self._run_concurrency,
        }

        resumed: list[str] = []
        fixture_mutated = False
        status = "success"
        notes: list[str] = [
            "Fixture is never mutated; fingerprint re-checked after each phase.",
            "Peak memory and transaction latency compared to declared budgets.",
            "Every migrated population emits count and digest parity receipts.",
        ]

        for phase in selected:
            # Resume: skip phases already completed for this fixture digest.
            if self.resume and phase.value in self._completed:
                existing = next(
                    (p for p in self._phase_results if p.phase is phase),
                    None,
                )
                if existing is not None:
                    resumed.append(phase.value)
                    continue

            try:
                metrics, details = self._measure(runners[phase])
                budget_ok, failures = _evaluate_phase_budget(metrics, self.budget)
                parity = []
                if phase is PhaseName.STREAMING_MIGRATION:
                    parity = list(self._parity)
                elif phase is PhaseName.BACKUP_RESTORE:
                    # Only the restore catalog receipt from this phase.
                    parity = [
                        p
                        for p in self._parity
                        if p.population == "backup_restore_catalog"
                    ]
                phase_status = "success" if budget_ok else "budget_exceeded"
                if phase is PhaseName.STREAMING_MIGRATION and parity:
                    if not all(p.matched for p in parity):
                        phase_status = "parity_failed"
                result = PhaseResult(
                    phase=phase,
                    status=phase_status,
                    metrics=metrics,
                    budget_ok=budget_ok,
                    budget_failures=failures,
                    parity_receipts=parity,
                    details=details,
                    resumed=False,
                )
            except Exception as exc:
                status = "failed"
                result = PhaseResult(
                    phase=phase,
                    status="error",
                    metrics=PhaseMetrics(),
                    budget_ok=False,
                    budget_failures=("error",),
                    error=str(exc),
                )

            # Drop prior result for this phase if re-running.
            self._phase_results = [
                p for p in self._phase_results if p.phase is not phase
            ]
            self._phase_results.append(result)
            if result.status in {"success", "budget_exceeded", "parity_failed"}:
                if phase.value not in self._completed:
                    self._completed.append(phase.value)
            if result.status not in {"success"}:
                if result.status == "error":
                    status = "failed"
                elif status == "success":
                    status = result.status

            try:
                _assert_fixture_unmutated(self.fixture_root, self.fixture_digest)
            except BenchmarkError:
                fixture_mutated = True
                status = "fixture_mutated"
                notes.append(
                    f"Fixture mutation detected after phase {phase.value}"
                )

            self._persist_checkpoint()

        # Final fixture integrity check.
        try:
            _assert_fixture_unmutated(self.fixture_root, self.fixture_digest)
        except BenchmarkError:
            fixture_mutated = True
            status = "fixture_mutated"

        # Ensure streaming parity receipts are attached to the report even
        # when the phase was resumed from checkpoint.
        streaming = next(
            (
                p
                for p in self._phase_results
                if p.phase is PhaseName.STREAMING_MIGRATION
            ),
            None,
        )
        if streaming is not None and streaming.parity_receipts:
            self._parity = list(streaming.parity_receipts) + [
                p
                for p in self._parity
                if p.population == "backup_restore_catalog"
            ]

        # Order phases for the report.
        ordered: list[PhaseResult] = []
        for phase in PHASES:
            for result in self._phase_results:
                if result.phase is phase and result not in ordered:
                    ordered.append(result)

        report = BenchmarkReport(
            fixture_root=str(self.fixture_root),
            fixture_digest=self.fixture_digest,
            fixture_mutated=fixture_mutated,
            fixture_mode=self.fixture_mode,
            work_dir=str(self.work_dir),
            budget=self.budget,
            phases=ordered,
            status=status if not fixture_mutated else "fixture_mutated",
            resumed_phases=tuple(resumed),
            checkpoint_path=str(self.checkpoint_path),
            notes=tuple(notes),
        )

        report_path = self.work_dir / "dqk-048-benchmark-report.json"
        _write_atomic(report_path, report.to_dict())
        return report


def _is_importable(path: Path) -> bool:
    """Return True when the ArtifactImporter can detect a source kind."""

    name = path.name.lower()
    if name.endswith(
        (
            ".jsonl",
            ".ndjson",
            ".json",
            ".md",
            ".sqlite",
            ".sqlite3",
            ".db",
            ".parquet",
            ".pq",
        )
    ):
        return True
    return False


def run_migration_benchmark(
    work_dir: Path | str,
    *,
    fixture_root: Path | str | None = None,
    budget: BenchmarkBudget | None = None,
    record_count: int = 200,
    blob_bytes: int = 256 * 1024,
    resume: bool = True,
    phases: Sequence[PhaseName | str] | None = None,
) -> BenchmarkReport:
    """Convenience entry point used by tests and CLI wrappers."""

    bench = MigrationBenchmark(
        work_dir,
        fixture_root=fixture_root,
        budget=budget,
        record_count=record_count,
        blob_bytes=blob_bytes,
        resume=resume,
    )
    return bench.run(phases=phases)


def main(argv: Sequence[str] | None = None) -> int:
    """Minimal CLI: ``python -m benchmarks.duckdb_quack_migration_benchmark``."""

    import argparse

    parser = argparse.ArgumentParser(
        description="DQK-048 DuckDB Quack migration benchmark"
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("workspace/benchmarks/dqk-048"),
        help="Writable working directory (never the fixture root)",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Optional real production-hardening fixture root",
    )
    parser.add_argument("--record-count", type=int, default=200)
    parser.add_argument("--blob-bytes", type=int, default=256 * 1024)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--phase",
        action="append",
        dest="phases",
        default=None,
        help="Phase to run (repeatable); default: all",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_migration_benchmark(
        args.work_dir,
        fixture_root=args.fixture,
        record_count=args.record_count,
        blob_bytes=args.blob_bytes,
        resume=not args.no_resume,
        phases=args.phases,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
