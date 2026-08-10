"""Fenced DuckDB control plane for active transactions and MVCC metadata (DQK-017).

Moves process-local active transaction and MVCC metadata into a single-owner
DuckDB file while retaining the immutable IPLD WAL chain as content authority.

Design invariants
-----------------
* **WAL CIDs never change.** DuckDB stores only the WAL head pointer and
  idempotent-replay key → CID mappings. Entry payloads remain content-
  addressed IPLD objects produced by :class:`WriteAheadLog`.
* **Owner fencing.** Exactly one ``owner_id`` / ``generation`` pair may
  mutate control state. Stale owners fail closed with a fenced error.
* **Crash recovery is exact.** Committed revisions (COMPLETE) neither
  disappear nor duplicate; PUBLISH-without-COMPLETE is finished once
  via the existing recovery matrix; INTENT/PREPARE discard staged work.

Importing this module does not open DuckDB until a state path is constructed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

from .types import (
    HeadCASResult,
    IdempotencyConflictError,
    IsolationLevel,
    LeaseFence,
    LeaseFencedError,
    Operation,
    RecoveryAction,
    RecoveryDecision,
    SnapshotRevision,
    StagedDelta,
    Transaction,
    TransactionState,
    WALEntry,
    WALPhase,
    phase_to_txn_state,
    recovery_action_for_phase,
)

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

SCHEMA_VERSION: int = 1
STATE_SCHEMA: str = "ipfs_datasets_py/kg-duckdb-transaction-state@1"

# Typed error codes for the transaction-control DuckDB surface.
STATE_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "NOT_FOUND",
        "CONFLICT",
        "FENCED",
        "STORAGE",
        "INTERNAL",
    }
)

_DEFAULT_RETRYABLE: Mapping[str, bool] = {
    "INVALID_REQUEST": False,
    "NOT_FOUND": False,
    "CONFLICT": True,
    "FENCED": False,
    "STORAGE": True,
    "INTERNAL": False,
}


class TransactionStateError(Exception):
    """Typed failure for the DuckDB transaction-control plane."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: Optional[bool] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if code not in STATE_ERROR_CODES:
            raise ValueError(f"unknown transaction-state error code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = (
            bool(_DEFAULT_RETRYABLE[code]) if retryable is None else bool(retryable)
        )
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }

    def __str__(self) -> str:
        if self.details:
            return f"{self.code}: {self.message} {self.details}"
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class OwnerFence:
    """Single-writer ownership token for a transaction-state database."""

    owner_id: str
    generation: int
    process_birth: str
    acquired_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "generation": self.generation,
            "process_birth": self.process_birth,
            "acquired_at": self.acquired_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OwnerFence":
        return cls(
            owner_id=str(data["owner_id"]),
            generation=int(data["generation"]),
            process_birth=str(data["process_birth"]),
            acquired_at=float(data.get("acquired_at") or 0.0),
        )


_SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS state_meta (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS owner_fence (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        owner_id VARCHAR NOT NULL,
        generation INTEGER NOT NULL,
        process_birth VARCHAR NOT NULL,
        acquired_at DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_transactions (
        txn_id VARCHAR PRIMARY KEY,
        tenant VARCHAR,
        graph_id VARCHAR,
        branch VARCHAR,
        state VARCHAR NOT NULL,
        phase VARCHAR NOT NULL,
        isolation_level VARCHAR NOT NULL,
        base_revision VARCHAR,
        staged_revision_id VARCHAR,
        staged_root_cid VARCHAR,
        lease_id VARCHAR,
        lease_epoch INTEGER,
        idempotency_key VARCHAR,
        record_seq INTEGER NOT NULL DEFAULT 0,
        start_time DOUBLE NOT NULL,
        snapshot_cid VARCHAR,
        operations_json VARCHAR NOT NULL DEFAULT '[]',
        read_set_json VARCHAR NOT NULL DEFAULT '[]',
        write_set_json VARCHAR NOT NULL DEFAULT '[]',
        wal_entries_json VARCHAR NOT NULL DEFAULT '[]',
        owner_id VARCHAR NOT NULL,
        owner_generation INTEGER NOT NULL,
        updated_at DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staged_deltas (
        txn_id VARCHAR PRIMARY KEY,
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        branch VARCHAR NOT NULL,
        base_revision VARCHAR NOT NULL,
        staged_revision_id VARCHAR,
        staged_root_cid VARCHAR,
        checksum VARCHAR,
        byte_size INTEGER NOT NULL DEFAULT 0,
        payload_json VARCHAR NOT NULL,
        owner_id VARCHAR NOT NULL,
        owner_generation INTEGER NOT NULL,
        updated_at DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS branch_heads (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        branch VARCHAR NOT NULL,
        head_revision VARCHAR NOT NULL,
        updated_at DOUBLE NOT NULL,
        PRIMARY KEY (tenant, graph_id, branch)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS revisions (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        revision_id VARCHAR NOT NULL,
        parent_revision VARCHAR,
        root_cid VARCHAR,
        checksum VARCHAR,
        created_at DOUBLE NOT NULL,
        metadata_json VARCHAR NOT NULL DEFAULT '{}',
        PRIMARY KEY (tenant, graph_id, revision_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS writer_leases (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        branch VARCHAR NOT NULL,
        lease_id VARCHAR NOT NULL,
        holder VARCHAR NOT NULL,
        epoch INTEGER NOT NULL,
        expires_at DOUBLE NOT NULL,
        created_at DOUBLE NOT NULL,
        PRIMARY KEY (tenant, graph_id, branch)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staged_roots (
        root_cid VARCHAR PRIMARY KEY,
        payload_json VARCHAR NOT NULL,
        created_at DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        key VARCHAR PRIMARY KEY,
        request_hash VARCHAR NOT NULL,
        response_json VARCHAR NOT NULL,
        created_at DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wal_control (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        wal_head_cid VARCHAR,
        entry_count INTEGER NOT NULL DEFAULT 0,
        updated_at DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wal_applied_keys (
        replay_key VARCHAR PRIMARY KEY,
        wal_cid VARCHAR NOT NULL,
        recorded_at DOUBLE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS committed_revisions (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        branch VARCHAR NOT NULL,
        revision_id VARCHAR NOT NULL,
        parent_revision VARCHAR,
        txn_id VARCHAR,
        wal_complete_cid VARCHAR,
        committed_at DOUBLE NOT NULL,
        PRIMARY KEY (tenant, graph_id, branch, revision_id)
    )
    """,
)


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise TransactionStateError(
            "STORAGE",
            "duckdb package is required for DuckDBTransactionState",
        ) from exc
    return duckdb


def _row_map(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {columns[i]: row[i] for i in range(len(columns))}


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _json_loads(raw: Optional[str], default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


def transaction_to_dict(txn: Transaction) -> Dict[str, Any]:
    """Serialize a :class:`Transaction` for durable control-plane storage."""

    return {
        "txn_id": txn.txn_id,
        "isolation_level": txn.isolation_level.value,
        "state": txn.state.value,
        "operations": [op.to_dict() for op in txn.operations],
        "read_set": list(txn.read_set),
        "write_set": list(txn.write_set),
        "start_time": float(txn.start_time),
        "snapshot_cid": txn.snapshot_cid,
        "wal_entries": list(txn.wal_entries),
        "tenant": txn.tenant,
        "graph_id": txn.graph_id,
        "branch": txn.branch,
        "base_revision": txn.base_revision,
        "staged_revision_id": txn.staged_revision_id,
        "staged_root_cid": txn.staged_root_cid,
        "lease_id": txn.lease_id,
        "lease_epoch": txn.lease_epoch,
        "idempotency_key": txn.idempotency_key,
        "phase": txn.phase.value,
        "record_seq": int(txn.record_seq),
    }


def transaction_from_dict(data: Mapping[str, Any]) -> Transaction:
    """Deserialize a :class:`Transaction` from control-plane storage."""

    phase_raw = data.get("phase")
    return Transaction(
        txn_id=str(data["txn_id"]),
        isolation_level=IsolationLevel(
            data.get("isolation_level", IsolationLevel.REPEATABLE_READ.value)
        ),
        state=TransactionState(data.get("state", TransactionState.ACTIVE.value)),
        operations=[
            Operation.from_dict(op) for op in (data.get("operations") or [])
        ],
        read_set=list(data.get("read_set") or []),
        write_set=list(data.get("write_set") or []),
        start_time=float(data.get("start_time") or 0.0),
        snapshot_cid=data.get("snapshot_cid"),
        wal_entries=list(data.get("wal_entries") or []),
        tenant=data.get("tenant"),
        graph_id=data.get("graph_id"),
        branch=data.get("branch"),
        base_revision=data.get("base_revision"),
        staged_revision_id=data.get("staged_revision_id"),
        staged_root_cid=data.get("staged_root_cid"),
        lease_id=data.get("lease_id"),
        lease_epoch=(
            int(data["lease_epoch"]) if data.get("lease_epoch") is not None else None
        ),
        idempotency_key=data.get("idempotency_key"),
        phase=WALPhase(phase_raw) if phase_raw else WALPhase.INTENT,
        record_seq=int(data.get("record_seq") or 0),
    )


class DuckDBTransactionState:
    """
    Fenced DuckDB store for active transactions and MVCC control metadata.

    Implements the same branch/lease/revision contracts as
    :class:`~.mvcc.InMemoryBranchStore` so :class:`~.mvcc.DurableMVCC` can
    use this as a durable ``branch_store``. WAL entry bytes stay on IPLD;
    this class only tracks the head CID and applied replay keys.
    """

    def __init__(
        self,
        path: PathLike,
        *,
        owner_id: Optional[str] = None,
        process_birth: Optional[str] = None,
        claim_on_open: bool = True,
    ) -> None:
        duckdb = _require_duckdb()
        self._path = Path(path)
        if self._path.parent and str(self._path.parent) not in ("", "."):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self._path))
        self._closed = False
        self._owner: Optional[OwnerFence] = None
        self._initialize_schema()
        if claim_on_open:
            self.claim_owner(
                owner_id or f"owner-{uuid.uuid4().hex[:12]}",
                process_birth or f"birth-{uuid.uuid4().hex[:16]}",
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def owner(self) -> Optional[OwnerFence]:
        return self._owner

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.close()
            finally:
                self._closed = True

    def __enter__(self) -> "DuckDBTransactionState":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise TransactionStateError("STORAGE", "transaction state is closed")

    def _initialize_schema(self) -> None:
        with self._lock:
            for statement in _SCHEMA_SQL:
                self._conn.execute(statement)
            row = self._conn.execute(
                "SELECT value FROM state_meta WHERE key = ?",
                ["schema_version"],
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO state_meta (key, value) VALUES (?, ?)",
                    ["schema_version", str(SCHEMA_VERSION)],
                )
                self._conn.execute(
                    "INSERT INTO state_meta (key, value) VALUES (?, ?)",
                    ["state_schema", STATE_SCHEMA],
                )
            else:
                version = int(row[0])
                if version > SCHEMA_VERSION:
                    raise TransactionStateError(
                        "STORAGE",
                        f"transaction state schema version {version} is newer "
                        f"than supported {SCHEMA_VERSION}",
                    )
            # Ensure wal_control singleton row exists.
            existing = self._conn.execute(
                "SELECT singleton FROM wal_control WHERE singleton = 1"
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    "INSERT INTO wal_control "
                    "(singleton, wal_head_cid, entry_count, updated_at) "
                    "VALUES (1, NULL, 0, ?)",
                    [time.time()],
                )

    @contextmanager
    def _txn(self) -> Iterator[Any]:
        self._ensure_open()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def _fetchone(
        self, conn: Any, sql: str, params: Sequence[Any] = ()
    ) -> Optional[dict[str, Any]]:
        cur = conn.execute(sql, list(params))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return _row_map(cols, row)

    def _fetchall(
        self, conn: Any, sql: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        cur = conn.execute(sql, list(params))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [_row_map(cols, row) for row in rows]

    # ------------------------------------------------------------------
    # Owner fencing
    # ------------------------------------------------------------------

    def claim_owner(
        self,
        owner_id: str,
        process_birth: str,
        *,
        now: Optional[float] = None,
    ) -> OwnerFence:
        """
        Claim sole writer ownership, fencing any previous owner.

        Bumps ``generation`` so stale holders fail closed on mutation.
        """
        if not owner_id or not str(owner_id).strip():
            raise TransactionStateError(
                "INVALID_REQUEST", "owner_id is required"
            )
        if not process_birth or not str(process_birth).strip():
            raise TransactionStateError(
                "INVALID_REQUEST", "process_birth is required"
            )
        now = float(now if now is not None else time.time())
        with self._txn() as conn:
            row = self._fetchone(
                conn, "SELECT * FROM owner_fence WHERE singleton = 1"
            )
            if row is None:
                generation = 1
                conn.execute(
                    "INSERT INTO owner_fence "
                    "(singleton, owner_id, generation, process_birth, acquired_at) "
                    "VALUES (1, ?, ?, ?, ?)",
                    [str(owner_id), generation, str(process_birth), now],
                )
            else:
                generation = int(row["generation"]) + 1
                conn.execute(
                    "UPDATE owner_fence SET owner_id = ?, generation = ?, "
                    "process_birth = ?, acquired_at = ? WHERE singleton = 1",
                    [str(owner_id), generation, str(process_birth), now],
                )
            fence = OwnerFence(
                owner_id=str(owner_id),
                generation=generation,
                process_birth=str(process_birth),
                acquired_at=now,
            )
            self._owner = fence
            logger.info(
                "transaction state owner claimed id=%s gen=%s birth=%s",
                fence.owner_id,
                fence.generation,
                fence.process_birth,
            )
            return fence

    def get_owner(self) -> Optional[OwnerFence]:
        """Return the durable owner fence (re-reads from DuckDB)."""
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn, "SELECT * FROM owner_fence WHERE singleton = 1"
            )
            if row is None:
                return None
            fence = OwnerFence(
                owner_id=str(row["owner_id"]),
                generation=int(row["generation"]),
                process_birth=str(row["process_birth"]),
                acquired_at=float(row["acquired_at"]),
            )
            return fence

    def _require_owner(self, conn: Any) -> OwnerFence:
        if self._owner is None:
            raise TransactionStateError(
                "FENCED",
                "no local owner token; claim_owner required",
            )
        row = self._fetchone(
            conn, "SELECT * FROM owner_fence WHERE singleton = 1"
        )
        if row is None:
            raise TransactionStateError(
                "FENCED", "owner fence row missing"
            )
        if (
            str(row["owner_id"]) != self._owner.owner_id
            or int(row["generation"]) != int(self._owner.generation)
        ):
            raise TransactionStateError(
                "FENCED",
                "stale transaction owner is fenced",
                details={
                    "local_owner_id": self._owner.owner_id,
                    "local_generation": self._owner.generation,
                    "current_owner_id": row["owner_id"],
                    "current_generation": row["generation"],
                },
            )
        return self._owner

    def assert_owner(self) -> OwnerFence:
        """Public check that this process still holds the owner fence."""
        with self._txn() as conn:
            return self._require_owner(conn)

    # ------------------------------------------------------------------
    # WAL control (pointers only — CIDs immutable)
    # ------------------------------------------------------------------

    def get_wal_head_cid(self) -> Optional[str]:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT wal_head_cid FROM wal_control WHERE singleton = 1",
            )
            if row is None or not row.get("wal_head_cid"):
                return None
            return str(row["wal_head_cid"])

    def set_wal_head_cid(self, cid: Optional[str]) -> None:
        """
        Record the current IPLD WAL head CID.

        Never rewrites WAL entry content; only updates the control pointer.
        """
        with self._txn() as conn:
            self._require_owner(conn)
            conn.execute(
                "UPDATE wal_control SET wal_head_cid = ?, updated_at = ? "
                "WHERE singleton = 1",
                [cid, time.time()],
            )

    def bump_wal_entry_count(self, delta: int = 1) -> int:
        with self._txn() as conn:
            self._require_owner(conn)
            row = self._fetchone(
                conn, "SELECT entry_count FROM wal_control WHERE singleton = 1"
            )
            current = int(row["entry_count"]) if row else 0
            new_count = current + int(delta)
            conn.execute(
                "UPDATE wal_control SET entry_count = ?, updated_at = ? "
                "WHERE singleton = 1",
                [new_count, time.time()],
            )
            return new_count

    def get_wal_entry_count(self) -> int:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT entry_count FROM wal_control WHERE singleton = 1",
            )
            return int(row["entry_count"]) if row else 0

    def record_wal_applied_key(self, replay_key: str, wal_cid: str) -> None:
        """
        Persist an idempotent WAL replay key → CID mapping.

        Re-recording the same key with the same CID is a no-op. A different
        CID for the same key is a conflict (would imply CID mutation).
        """
        if not replay_key or not wal_cid:
            raise TransactionStateError(
                "INVALID_REQUEST", "replay_key and wal_cid are required"
            )
        with self._txn() as conn:
            self._require_owner(conn)
            existing = self._fetchone(
                conn,
                "SELECT wal_cid FROM wal_applied_keys WHERE replay_key = ?",
                [replay_key],
            )
            if existing is not None:
                if str(existing["wal_cid"]) != str(wal_cid):
                    raise TransactionStateError(
                        "CONFLICT",
                        "WAL applied key maps to a different CID "
                        "(WAL CIDs must remain unchanged)",
                        details={
                            "replay_key": replay_key,
                            "existing_cid": existing["wal_cid"],
                            "new_cid": wal_cid,
                        },
                    )
                return
            conn.execute(
                "INSERT INTO wal_applied_keys "
                "(replay_key, wal_cid, recorded_at) VALUES (?, ?, ?)",
                [replay_key, wal_cid, time.time()],
            )

    def get_wal_applied_key(self, replay_key: str) -> Optional[str]:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT wal_cid FROM wal_applied_keys WHERE replay_key = ?",
                [replay_key],
            )
            return str(row["wal_cid"]) if row else None

    def list_wal_applied_keys(self) -> Dict[str, str]:
        with self._lock:
            self._ensure_open()
            rows = self._fetchall(
                self._conn, "SELECT replay_key, wal_cid FROM wal_applied_keys"
            )
            return {str(r["replay_key"]): str(r["wal_cid"]) for r in rows}

    def bind_wal(self, wal: Any) -> None:
        """
        Wire a :class:`WriteAheadLog` to this control plane.

        Loads durable head + applied keys into the WAL process object without
        rewriting any IPLD CID content.
        """
        head = self.get_wal_head_cid()
        if head is not None:
            wal.wal_head_cid = head
        applied = self.list_wal_applied_keys()
        if applied:
            # Preserve existing in-memory keys; durable keys take precedence.
            wal._applied_keys.update(applied)  # noqa: SLF001 — intentional restore
        count = self.get_wal_entry_count()
        if count:
            wal._entry_count = max(int(getattr(wal, "_entry_count", 0)), count)

    def note_wal_append(self, wal: Any, cid: str, entry: Optional[WALEntry] = None) -> None:
        """
        After a successful IPLD WAL append, record head/keys without mutation.

        The ``cid`` must be the exact CID returned by the IPLD store.
        """
        with self._txn() as conn:
            self._require_owner(conn)
            conn.execute(
                "UPDATE wal_control SET wal_head_cid = ?, "
                "entry_count = entry_count + 1, updated_at = ? WHERE singleton = 1",
                [cid, time.time()],
            )
            if entry is not None:
                key = None
                if entry.idempotency_key:
                    phase = entry.resolved_phase().value
                    key = f"idem:{entry.idempotency_key}:{phase}:{entry.record_seq}"
                if key:
                    existing = self._fetchone(
                        conn,
                        "SELECT wal_cid FROM wal_applied_keys WHERE replay_key = ?",
                        [key],
                    )
                    if existing is None:
                        conn.execute(
                            "INSERT INTO wal_applied_keys "
                            "(replay_key, wal_cid, recorded_at) VALUES (?, ?, ?)",
                            [key, cid, time.time()],
                        )
                    elif str(existing["wal_cid"]) != str(cid):
                        raise TransactionStateError(
                            "CONFLICT",
                            "WAL applied key would change CID",
                            details={
                                "replay_key": key,
                                "existing_cid": existing["wal_cid"],
                                "new_cid": cid,
                            },
                        )

    # ------------------------------------------------------------------
    # Active transactions / staged deltas
    # ------------------------------------------------------------------

    def put_active_transaction(self, txn: Transaction) -> None:
        """Upsert an active (or in-flight) transaction record."""
        with self._txn() as conn:
            owner = self._require_owner(conn)
            now = time.time()
            conn.execute(
                "INSERT OR REPLACE INTO active_transactions ("
                "txn_id, tenant, graph_id, branch, state, phase, isolation_level, "
                "base_revision, staged_revision_id, staged_root_cid, lease_id, "
                "lease_epoch, idempotency_key, record_seq, start_time, snapshot_cid, "
                "operations_json, read_set_json, write_set_json, wal_entries_json, "
                "owner_id, owner_generation, updated_at"
                ") VALUES ("
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
                ")",
                [
                    txn.txn_id,
                    txn.tenant,
                    txn.graph_id,
                    txn.branch,
                    txn.state.value,
                    txn.phase.value,
                    txn.isolation_level.value,
                    txn.base_revision,
                    txn.staged_revision_id,
                    txn.staged_root_cid,
                    txn.lease_id,
                    txn.lease_epoch,
                    txn.idempotency_key,
                    int(txn.record_seq),
                    float(txn.start_time),
                    txn.snapshot_cid,
                    _json_dumps([op.to_dict() for op in txn.operations]),
                    _json_dumps(list(txn.read_set)),
                    _json_dumps(list(txn.write_set)),
                    _json_dumps(list(txn.wal_entries)),
                    owner.owner_id,
                    owner.generation,
                    now,
                ],
            )

    def get_active_transaction(self, txn_id: str) -> Optional[Transaction]:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT * FROM active_transactions WHERE txn_id = ?",
                [txn_id],
            )
            if row is None:
                return None
            return self._txn_from_row(row)

    def list_active_transactions(self) -> List[Transaction]:
        with self._lock:
            self._ensure_open()
            rows = self._fetchall(
                self._conn, "SELECT * FROM active_transactions ORDER BY start_time"
            )
            return [self._txn_from_row(r) for r in rows]

    def remove_active_transaction(self, txn_id: str) -> bool:
        with self._txn() as conn:
            self._require_owner(conn)
            before = self._fetchone(
                conn,
                "SELECT txn_id FROM active_transactions WHERE txn_id = ?",
                [txn_id],
            )
            if before is None:
                return False
            conn.execute(
                "DELETE FROM active_transactions WHERE txn_id = ?", [txn_id]
            )
            return True

    def put_staged_delta(self, delta: StagedDelta) -> None:
        with self._txn() as conn:
            owner = self._require_owner(conn)
            conn.execute(
                "INSERT OR REPLACE INTO staged_deltas ("
                "txn_id, tenant, graph_id, branch, base_revision, "
                "staged_revision_id, staged_root_cid, checksum, byte_size, "
                "payload_json, owner_id, owner_generation, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    delta.txn_id,
                    delta.tenant,
                    delta.graph_id,
                    delta.branch,
                    delta.base_revision,
                    delta.staged_revision_id,
                    delta.staged_root_cid,
                    delta.checksum,
                    int(delta.byte_size),
                    _json_dumps(delta.to_dict()),
                    owner.owner_id,
                    owner.generation,
                    time.time(),
                ],
            )

    def get_staged_delta(self, txn_id: str) -> Optional[StagedDelta]:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT payload_json FROM staged_deltas WHERE txn_id = ?",
                [txn_id],
            )
            if row is None:
                return None
            return StagedDelta.from_dict(_json_loads(row["payload_json"], {}))

    def remove_staged_delta(self, txn_id: str) -> bool:
        with self._txn() as conn:
            self._require_owner(conn)
            before = self._fetchone(
                conn,
                "SELECT txn_id FROM staged_deltas WHERE txn_id = ?",
                [txn_id],
            )
            if before is None:
                return False
            conn.execute("DELETE FROM staged_deltas WHERE txn_id = ?", [txn_id])
            return True

    def _txn_from_row(self, row: Mapping[str, Any]) -> Transaction:
        return transaction_from_dict(
            {
                "txn_id": row["txn_id"],
                "tenant": row.get("tenant"),
                "graph_id": row.get("graph_id"),
                "branch": row.get("branch"),
                "state": row["state"],
                "phase": row["phase"],
                "isolation_level": row["isolation_level"],
                "base_revision": row.get("base_revision"),
                "staged_revision_id": row.get("staged_revision_id"),
                "staged_root_cid": row.get("staged_root_cid"),
                "lease_id": row.get("lease_id"),
                "lease_epoch": row.get("lease_epoch"),
                "idempotency_key": row.get("idempotency_key"),
                "record_seq": row.get("record_seq") or 0,
                "start_time": row.get("start_time") or 0.0,
                "snapshot_cid": row.get("snapshot_cid"),
                "operations": _json_loads(row.get("operations_json"), []),
                "read_set": _json_loads(row.get("read_set_json"), []),
                "write_set": _json_loads(row.get("write_set_json"), []),
                "wal_entries": _json_loads(row.get("wal_entries_json"), []),
            }
        )

    # ------------------------------------------------------------------
    # Branch store contract (MVCC metadata)
    # ------------------------------------------------------------------

    def ensure_branch(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        initial_revision: str = "rev-genesis",
    ) -> SnapshotRevision:
        with self._txn() as conn:
            self._require_owner(conn)
            row = self._fetchone(
                conn,
                "SELECT head_revision FROM branch_heads "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                [tenant, graph_id, branch],
            )
            now = time.time()
            if row is None:
                snap = SnapshotRevision(
                    tenant=tenant,
                    graph_id=graph_id,
                    revision_id=initial_revision,
                    parent_revision=None,
                    root_cid=None,
                    checksum=_checksum_empty(),
                    created_at=now,
                )
                conn.execute(
                    "INSERT INTO branch_heads "
                    "(tenant, graph_id, branch, head_revision, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [tenant, graph_id, branch, initial_revision, now],
                )
                conn.execute(
                    "INSERT INTO revisions ("
                    "tenant, graph_id, revision_id, parent_revision, root_cid, "
                    "checksum, created_at, metadata_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        tenant,
                        graph_id,
                        initial_revision,
                        None,
                        None,
                        snap.checksum,
                        now,
                        "{}",
                    ],
                )
                return snap
            return self._get_revision_conn(
                conn, tenant, graph_id, str(row["head_revision"])
            )

    def get_head(self, tenant: str, graph_id: str, branch: str) -> str:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT head_revision FROM branch_heads "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                [tenant, graph_id, branch],
            )
            if row is None:
                raise KeyError(f"unknown branch {tenant}/{graph_id}/{branch}")
            return str(row["head_revision"])

    def get_revision(
        self, tenant: str, graph_id: str, revision_id: str
    ) -> SnapshotRevision:
        with self._lock:
            self._ensure_open()
            return self._get_revision_conn(
                self._conn, tenant, graph_id, revision_id
            )

    def _get_revision_conn(
        self, conn: Any, tenant: str, graph_id: str, revision_id: str
    ) -> SnapshotRevision:
        row = self._fetchone(
            conn,
            "SELECT * FROM revisions "
            "WHERE tenant = ? AND graph_id = ? AND revision_id = ?",
            [tenant, graph_id, revision_id],
        )
        if row is None:
            raise KeyError(f"unknown revision {tenant}/{graph_id}/{revision_id}")
        return SnapshotRevision(
            tenant=str(row["tenant"]),
            graph_id=str(row["graph_id"]),
            revision_id=str(row["revision_id"]),
            parent_revision=row.get("parent_revision"),
            root_cid=row.get("root_cid"),
            checksum=row.get("checksum"),
            created_at=float(row.get("created_at") or 0.0),
            metadata=_json_loads(row.get("metadata_json"), {}),
        )

    def put_revision(self, snap: SnapshotRevision) -> None:
        with self._txn() as conn:
            self._require_owner(conn)
            conn.execute(
                "INSERT OR REPLACE INTO revisions ("
                "tenant, graph_id, revision_id, parent_revision, root_cid, "
                "checksum, created_at, metadata_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    snap.tenant,
                    snap.graph_id,
                    snap.revision_id,
                    snap.parent_revision,
                    snap.root_cid,
                    snap.checksum,
                    float(snap.created_at),
                    _json_dumps(dict(snap.metadata) if snap.metadata else {}),
                ],
            )

    def put_staged_root(self, root_cid: str, payload: Dict[str, Any]) -> None:
        with self._txn() as conn:
            self._require_owner(conn)
            conn.execute(
                "INSERT OR REPLACE INTO staged_roots "
                "(root_cid, payload_json, created_at) VALUES (?, ?, ?)",
                [root_cid, _json_dumps(payload), time.time()],
            )

    def discard_staged_root(self, root_cid: Optional[str]) -> bool:
        if not root_cid:
            return False
        with self._txn() as conn:
            self._require_owner(conn)
            before = self._fetchone(
                conn,
                "SELECT root_cid FROM staged_roots WHERE root_cid = ?",
                [root_cid],
            )
            if before is None:
                return False
            conn.execute(
                "DELETE FROM staged_roots WHERE root_cid = ?", [root_cid]
            )
            return True

    def has_staged_root(self, root_cid: str) -> bool:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT root_cid FROM staged_roots WHERE root_cid = ?",
                [root_cid],
            )
            return row is not None

    def cas_set_head(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        expected_revision: str,
        new_revision: str,
        lease_id: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> HeadCASResult:
        with self._txn() as conn:
            self._require_owner(conn)
            if lease_id is not None or lease_epoch is not None:
                self._check_lease_conn(
                    conn,
                    tenant,
                    graph_id,
                    branch,
                    lease_id=lease_id,
                    lease_epoch=lease_epoch,
                    now=now if now is not None else time.time(),
                )
            row = self._fetchone(
                conn,
                "SELECT head_revision FROM branch_heads "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                [tenant, graph_id, branch],
            )
            if row is None:
                raise KeyError(f"unknown branch {tenant}/{graph_id}/{branch}")
            current = str(row["head_revision"])
            if current != expected_revision:
                return HeadCASResult(
                    success=False,
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    expected_revision=expected_revision,
                    new_revision=new_revision,
                    current_revision=current,
                    conflict=True,
                )
            conn.execute(
                "UPDATE branch_heads SET head_revision = ?, updated_at = ? "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                [new_revision, time.time(), tenant, graph_id, branch],
            )
            return HeadCASResult(
                success=True,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                expected_revision=expected_revision,
                new_revision=new_revision,
                current_revision=new_revision,
                conflict=False,
            )

    def acquire_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        holder: str,
        ttl_seconds: float = 300.0,
        now: Optional[float] = None,
    ) -> LeaseFence:
        with self._txn() as conn:
            self._require_owner(conn)
            now = float(now if now is not None else time.time())
            existing = self._fetchone(
                conn,
                "SELECT * FROM writer_leases "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                [tenant, graph_id, branch],
            )
            if existing is not None and float(existing["expires_at"]) > now:
                if str(existing["holder"]) == holder:
                    renewed = LeaseFence(
                        tenant=tenant,
                        graph_id=graph_id,
                        branch=branch,
                        lease_id=str(existing["lease_id"]),
                        holder=holder,
                        epoch=int(existing["epoch"]),
                        expires_at=now + float(ttl_seconds),
                        created_at=float(existing["created_at"]),
                    )
                    conn.execute(
                        "UPDATE writer_leases SET expires_at = ? "
                        "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                        [renewed.expires_at, tenant, graph_id, branch],
                    )
                    return renewed
                raise LeaseFencedError(
                    "writer lease held by another holder",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "holder": holder,
                        "current_holder": existing["holder"],
                        "epoch": existing["epoch"],
                    },
                )
            epoch = (int(existing["epoch"]) + 1) if existing is not None else 1
            lease = LeaseFence(
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                lease_id=f"lease-{uuid.uuid4().hex[:12]}",
                holder=holder,
                epoch=epoch,
                expires_at=now + float(ttl_seconds),
                created_at=now,
            )
            conn.execute(
                "INSERT OR REPLACE INTO writer_leases ("
                "tenant, graph_id, branch, lease_id, holder, epoch, "
                "expires_at, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    tenant,
                    graph_id,
                    branch,
                    lease.lease_id,
                    lease.holder,
                    lease.epoch,
                    lease.expires_at,
                    lease.created_at,
                ],
            )
            return lease

    def _check_lease_conn(
        self,
        conn: Any,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        lease_id: Optional[str],
        lease_epoch: Optional[int],
        now: float,
    ) -> None:
        if lease_id is None and lease_epoch is None:
            return
        if lease_id is None or lease_epoch is None:
            raise LeaseFencedError(
                "lease_id and lease_epoch must be provided together",
                details={"lease_id": lease_id, "lease_epoch": lease_epoch},
            )
        current = self._fetchone(
            conn,
            "SELECT * FROM writer_leases "
            "WHERE tenant = ? AND graph_id = ? AND branch = ?",
            [tenant, graph_id, branch],
        )
        if current is None:
            raise LeaseFencedError(
                "no active writer lease for branch",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                },
            )
        if float(current["expires_at"]) <= now:
            raise LeaseFencedError(
                "writer lease expired",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                    "expires_at": current["expires_at"],
                },
            )
        if (
            str(current["lease_id"]) != str(lease_id)
            or int(current["epoch"]) != int(lease_epoch)
        ):
            raise LeaseFencedError(
                "writer lease epoch is stale",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                    "current_lease_id": current["lease_id"],
                    "current_epoch": current["epoch"],
                },
            )

    def check_idempotency(
        self, key: str, request_hash: str
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_open()
            row = self._fetchone(
                self._conn,
                "SELECT request_hash, response_json FROM idempotency_keys "
                "WHERE key = ?",
                [key],
            )
            if row is None:
                return None
            if str(row["request_hash"]) != str(request_hash):
                raise IdempotencyConflictError(
                    "idempotency key reused with different request",
                    details={"key": key},
                )
            return dict(_json_loads(row["response_json"], {}))

    def record_idempotency(
        self, key: str, request_hash: str, response: Dict[str, Any]
    ) -> None:
        with self._txn() as conn:
            self._require_owner(conn)
            conn.execute(
                "INSERT OR REPLACE INTO idempotency_keys "
                "(key, request_hash, response_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                [key, request_hash, _json_dumps(response), time.time()],
            )

    def record_committed_revision(
        self,
        *,
        tenant: str,
        graph_id: str,
        branch: str,
        revision_id: str,
        parent_revision: Optional[str] = None,
        txn_id: Optional[str] = None,
        wal_complete_cid: Optional[str] = None,
        committed_at: Optional[float] = None,
    ) -> bool:
        """
        Record a fully committed revision exactly once.

        Returns True if newly recorded, False if already present (idempotent).
        """
        with self._txn() as conn:
            self._require_owner(conn)
            existing = self._fetchone(
                conn,
                "SELECT revision_id FROM committed_revisions "
                "WHERE tenant = ? AND graph_id = ? AND branch = ? "
                "AND revision_id = ?",
                [tenant, graph_id, branch, revision_id],
            )
            if existing is not None:
                return False
            conn.execute(
                "INSERT INTO committed_revisions ("
                "tenant, graph_id, branch, revision_id, parent_revision, "
                "txn_id, wal_complete_cid, committed_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    tenant,
                    graph_id,
                    branch,
                    revision_id,
                    parent_revision,
                    txn_id,
                    wal_complete_cid,
                    float(committed_at if committed_at is not None else time.time()),
                ],
            )
            return True

    def list_committed_revisions(
        self, tenant: str, graph_id: str, branch: str = "main"
    ) -> List[str]:
        with self._lock:
            self._ensure_open()
            rows = self._fetchall(
                self._conn,
                "SELECT revision_id FROM committed_revisions "
                "WHERE tenant = ? AND graph_id = ? AND branch = ? "
                "ORDER BY committed_at, revision_id",
                [tenant, graph_id, branch],
            )
            return [str(r["revision_id"]) for r in rows]

    # ------------------------------------------------------------------
    # Recovery coordination
    # ------------------------------------------------------------------

    def recover(
        self,
        wal: Any,
        *,
        clear_active: bool = True,
    ) -> List[RecoveryDecision]:
        """
        Crash recovery that neither loses nor duplicates committed revisions.

        Uses the immutable IPLD WAL chain (via ``wal.plan_recovery`` /
        ``wal.apply_recovery``) and durable branch heads in DuckDB.

        * DISCARD_STAGED / ABORT_CLEANUP → drop staged roots + active rows
        * FINISH_PUBLICATION → ensure head + COMPLETE once; record commit
        * IDEMPOTENT_SKIP → reaffirm committed revision row without re-CAS
        """
        self.bind_wal(wal)
        with self._txn() as conn:
            self._require_owner(conn)

        decisions = wal.plan_recovery()

        def _discard(decision: RecoveryDecision) -> None:
            self.discard_staged_root(decision.staged_root_cid)
            if decision.txn_id:
                try:
                    self.remove_active_transaction(decision.txn_id)
                except TransactionStateError:
                    pass
                try:
                    self.remove_staged_delta(decision.txn_id)
                except TransactionStateError:
                    pass
            logger.info(
                "recovery discard staged txn=%s root=%s",
                decision.txn_id,
                decision.staged_root_cid,
            )

        def _finish(decision: RecoveryDecision) -> None:
            history = list(wal.get_transaction_history(decision.txn_id))
            tenant = graph_id = branch = None
            complete_cid = None
            for e in history:
                tenant = tenant or e.tenant
                graph_id = graph_id or e.graph_id
                branch = branch or e.branch
            if (
                decision.new_revision
                and decision.base_revision is not None
                and tenant
                and graph_id
                and branch
            ):
                try:
                    self.cas_set_head(
                        tenant,
                        graph_id,
                        branch,
                        expected_revision=decision.base_revision,
                        new_revision=decision.new_revision,
                    )
                except (KeyError, LeaseFencedError, TransactionStateError):
                    # Head already advanced or branch missing: leave as-is.
                    pass
                # Append COMPLETE if not already present (idempotent via WAL keys).
                if not any(
                    e.resolved_phase() == WALPhase.COMPLETE for e in history
                ):
                    complete_cid = wal.append_phase(
                        txn_id=decision.txn_id,
                        phase=WALPhase.COMPLETE,
                        tenant=tenant,
                        graph_id=graph_id,
                        branch=branch,
                        base_revision=decision.base_revision,
                        new_revision=decision.new_revision,
                        staged_root_cid=decision.staged_root_cid,
                        idempotency_key=None,
                        record_seq=max(
                            (e.record_seq for e in history), default=0
                        )
                        + 1,
                    )
                    self.note_wal_append(wal, complete_cid)
                else:
                    for e in history:
                        if e.resolved_phase() == WALPhase.COMPLETE:
                            # History order is reverse chronological in some APIs;
                            # take first COMPLETE we see in list order.
                            complete_cid = getattr(
                                e, "prev_wal_cid", None
                            )  # may not be entry's own cid
                            break
                self.record_committed_revision(
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    revision_id=decision.new_revision,
                    parent_revision=decision.base_revision,
                    txn_id=decision.txn_id,
                    wal_complete_cid=complete_cid
                    if isinstance(complete_cid, str)
                    else None,
                )
            if decision.txn_id:
                try:
                    self.remove_active_transaction(decision.txn_id)
                except TransactionStateError:
                    pass
                try:
                    self.remove_staged_delta(decision.txn_id)
                except TransactionStateError:
                    pass
            logger.info(
                "recovery finish publication txn=%s rev=%s",
                decision.txn_id,
                decision.new_revision,
            )

        def _skip(decision: RecoveryDecision) -> None:
            # Reaffirm committed revision without re-CAS / re-append.
            history = list(wal.get_transaction_history(decision.txn_id))
            tenant = graph_id = branch = None
            for e in history:
                tenant = tenant or e.tenant
                graph_id = graph_id or e.graph_id
                branch = branch or e.branch
            if (
                decision.new_revision
                and tenant
                and graph_id
                and branch
            ):
                self.record_committed_revision(
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    revision_id=decision.new_revision,
                    parent_revision=decision.base_revision,
                    txn_id=decision.txn_id,
                )
            if decision.txn_id:
                try:
                    self.remove_active_transaction(decision.txn_id)
                except TransactionStateError:
                    pass
                try:
                    self.remove_staged_delta(decision.txn_id)
                except TransactionStateError:
                    pass

        # Custom apply so IDEMPOTENT_SKIP still reaffirms commit rows.
        applied: List[RecoveryDecision] = []
        for decision in decisions:
            action = decision.action
            if action in (
                RecoveryAction.DISCARD_STAGED,
                RecoveryAction.ABORT_CLEANUP,
            ):
                _discard(decision)
            elif action == RecoveryAction.FINISH_PUBLICATION:
                _finish(decision)
            elif action == RecoveryAction.IDEMPOTENT_SKIP:
                _skip(decision)
            applied.append(decision)

        # Sync WAL head pointer after recovery appends.
        head = getattr(wal, "wal_head_cid", None)
        if head is not None:
            current = self.get_wal_head_cid()
            if current != head:
                self.set_wal_head_cid(head)

        if clear_active:
            # Drop any remaining active rows owned by a crashed process.
            remaining = self.list_active_transactions()
            for txn in remaining:
                phase = txn.phase
                action = recovery_action_for_phase(phase)
                if action in (
                    RecoveryAction.DISCARD_STAGED,
                    RecoveryAction.ABORT_CLEANUP,
                ):
                    self.discard_staged_root(txn.staged_root_cid)
                    self.remove_active_transaction(txn.txn_id)
                    self.remove_staged_delta(txn.txn_id)

        return applied

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_open()
            active = self._fetchone(
                self._conn, "SELECT COUNT(*) AS n FROM active_transactions"
            )
            heads = self._fetchone(
                self._conn, "SELECT COUNT(*) AS n FROM branch_heads"
            )
            commits = self._fetchone(
                self._conn, "SELECT COUNT(*) AS n FROM committed_revisions"
            )
            owner = self.get_owner()
            return {
                "path": str(self._path),
                "schema_version": SCHEMA_VERSION,
                "state_schema": STATE_SCHEMA,
                "owner": owner.to_dict() if owner else None,
                "active_transactions": int(active["n"]) if active else 0,
                "branch_heads": int(heads["n"]) if heads else 0,
                "committed_revisions": int(commits["n"]) if commits else 0,
                "wal_head_cid": self.get_wal_head_cid(),
                "wal_entry_count": self.get_wal_entry_count(),
                "wal_applied_keys": len(self.list_wal_applied_keys()),
            }


def _checksum_empty() -> str:
    import hashlib

    return hashlib.sha256(b"{}").hexdigest()


def create_duckdb_transaction_state(
    path: PathLike,
    *,
    owner_id: Optional[str] = None,
    process_birth: Optional[str] = None,
    claim_on_open: bool = True,
) -> DuckDBTransactionState:
    """Factory for :class:`DuckDBTransactionState`."""
    return DuckDBTransactionState(
        path,
        owner_id=owner_id,
        process_birth=process_birth,
        claim_on_open=claim_on_open,
    )


__all__ = [
    "SCHEMA_VERSION",
    "STATE_SCHEMA",
    "STATE_ERROR_CODES",
    "OwnerFence",
    "TransactionStateError",
    "DuckDBTransactionState",
    "create_duckdb_transaction_state",
    "transaction_to_dict",
    "transaction_from_dict",
]
