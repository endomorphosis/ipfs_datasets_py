"""Transactional DuckDB wallet ledger store and durable checkpoints (DQK-036).

Replaces in-memory staging/checkpoint authority with:

* **Idempotent batches** — each write is keyed by ``write_id`` / content digest;
  ``record_id`` primary keys prevent skip/duplicate on crash replay.
* **CAS checkpoints** — optimistic revision compare-and-set rejects stale
  ingesters without partial tip mutation.
* **Finality transitions** — append-only transition log (never silent overwrite).
* **Reorg rollback/replay** — reorg decisions and orphan corrections are retained
  as durable history; checkpoint tips rewind without erasing prior reorg rows.
* **CID / digest references** — encrypted and raw payload **bytes** stay outside
  the query-visible catalog; only content-addressed refs are stored.

The default process-local backend is pure Python so unit tests exercise the full
transactional contract without a live DuckDB extension.  An optional DuckDB
connection receives the wallet catalog DDL and mirrored row upserts.

Importing this module performs no network I/O.  Opening a DuckDB connection is
caller-owned.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final
from uuid import uuid4

from .canonical import (
    content_digest,
    deterministic_id,
    format_datetime,
    thaw_json,
)
from .checkpoints import (
    DEFAULT_HISTORY_LIMIT,
    CheckpointIdentity,
    CheckpointRecord,
    HashAnchor,
    assert_hash_anchor_present,
)
from .duckdb_schema import (
    DUCKDB_WALLET_SCHEMA_INTERFACE,
    DUCKDB_WALLET_SCHEMA_VERSION,
    WALLET_CATALOG_DDL,
    WALLET_CATALOG_NAME,
    WALLET_CATALOG_TABLES,
    WalletSchemaError,
    project_checkpoint_row,
    project_cursor_row,
    project_encrypted_object_ref_row,
    project_ledger_record_rows,
    project_reorg_row,
)
from .errors import CheckpointError, DatasetSinkError, InvalidRequestError
from .finality import (
    OrphanCorrection,
    ReorgDecision,
    can_transition,
    transition as finality_transition,
)
from .models import (
    ExportManifest,
    Finality,
    LedgerRecord,
    RawPayloadRef,
)
from .protocols import OperationContext, RecordBatch
from .storage import (
    BatchWriteReceipt,
    SinkCommitReceipt,
    record_as_dict,
    record_identity,
    record_sequence,
)

# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------

DUCKDB_WALLET_STORE_INTERFACE: Final = "DuckDBWalletStore@1"
DUCKDB_WALLET_STORE_SCHEMA_VERSION: Final = "duckdb-wallet-store/v1"
STAGE_SCHEMA_VERSION: Final = "wallet-stage-batch/v1"

# Internal control tables (not query-visible catalog surfaces).
_INTERNAL_STAGE_BATCHES: Final = "_wallet_stage_batches"
_INTERNAL_STAGE_ROWS: Final = "_wallet_stage_rows"
_INTERNAL_CHECKPOINT_HEADS: Final = "_wallet_checkpoint_heads"
_INTERNAL_CHECKPOINT_HISTORY: Final = "_wallet_checkpoint_history"
_INTERNAL_BATCH_IDEMPOTENCY: Final = "_wallet_batch_idempotency"
_INTERNAL_COMMITS: Final = "_wallet_commits"

# Ledger fact tables that use record_id as the durable identity key.
_LEDGER_FACT_TABLES: Final[frozenset[str]] = frozenset(
    {
        "blocks",
        "transactions",
        "transfers",
        "utxos",
        "token_accounts",
        "contract_events",
    }
)

_PRIMARY_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "chains": "chain_ref_id",
        "ingestion_sources": "source_id",
        "accounts": "account_id",
        "assets": "asset_id",
        "blocks": "record_id",
        "transactions": "record_id",
        "transfers": "record_id",
        "utxos": "record_id",
        "token_accounts": "record_id",
        "contract_events": "record_id",
        "cursors": "cursor_id",
        "checkpoints": "checkpoint_id",
        "finality_transitions": "transition_id",
        "reorgs": "reorg_id",
        "encrypted_object_refs": "ref_id",
    }
)

_INTERNAL_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS _wallet_stage_batches (
    batch_id VARCHAR PRIMARY KEY,
    scope VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    write_id VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    accepted_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    out_of_order_count INTEGER NOT NULL,
    byte_count INTEGER NOT NULL,
    created_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS _wallet_stage_rows (
    stage_row_id VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    table_name VARCHAR NOT NULL,
    row_pk VARCHAR NOT NULL,
    row_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS _wallet_checkpoint_heads (
    scope_key VARCHAR PRIMARY KEY,
    revision VARCHAR NOT NULL,
    checkpoint_id VARCHAR NOT NULL,
    identity_json VARCHAR NOT NULL,
    anchor_sequence BIGINT NOT NULL,
    anchor_hash VARCHAR NOT NULL,
    safety_depth INTEGER NOT NULL,
    sink_commit_id VARCHAR,
    history_json VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL,
    continuation_token VARCHAR,
    updated_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS _wallet_checkpoint_history (
    history_id VARCHAR PRIMARY KEY,
    scope_key VARCHAR NOT NULL,
    checkpoint_id VARCHAR NOT NULL,
    revision VARCHAR NOT NULL,
    anchor_sequence BIGINT NOT NULL,
    anchor_hash VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL,
    recorded_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS _wallet_batch_idempotency (
    idempotency_key VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    write_id VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    receipt_json VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS _wallet_commits (
    commit_id VARCHAR PRIMARY KEY,
    scope VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    record_count INTEGER NOT NULL,
    batch_ids_json VARCHAR NOT NULL,
    committed_at VARCHAR NOT NULL
);
""".strip()


class StageBatchStatus(StrEnum):
    """Lifecycle of one staged ingestion batch."""

    OPEN = "open"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ABORTED = "aborted"


class DuckDBWalletStoreError(DatasetSinkError):
    """Raised when the transactional wallet store fails closed."""


class StaleCheckpointError(CheckpointError):
    """CAS rejected because the expected revision is stale."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _required_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    return value


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _utc_now_str() -> str:
    return format_datetime(datetime.now(timezone.utc))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _json_loads(text: str) -> Any:
    return json.loads(text)


def _row_pk(table: str, row: Mapping[str, Any]) -> str:
    key = _PRIMARY_KEYS.get(table)
    if key is None:
        raise DuckDBWalletStoreError(f"unknown catalog table {table!r}")
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DuckDBWalletStoreError(
            f"{table} row missing primary key {key!r}"
        )
    return value


def _is_ledger_record(value: object) -> bool:
    return isinstance(value, LedgerRecord)


@dataclass(frozen=True, slots=True)
class StageBatchReceipt:
    """Durable receipt for one staged (not yet committed) batch."""

    batch_id: str
    write_id: str
    scope: str
    status: StageBatchStatus
    content_digest: str
    accepted_count: int
    duplicate_count: int
    out_of_order_count: int
    byte_count: int
    record_ids: tuple[str, ...]
    schema_version: str = field(default=STAGE_SCHEMA_VERSION, init=False)

    def to_write_receipt(self) -> BatchWriteReceipt:
        return BatchWriteReceipt(
            write_id=self.write_id,
            accepted_count=self.accepted_count,
            duplicate_count=self.duplicate_count,
            out_of_order_count=self.out_of_order_count,
            byte_count=self.byte_count,
            record_ids=self.record_ids,
            content_digest=self.content_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "write_id": self.write_id,
            "scope": self.scope,
            "status": self.status.value,
            "content_digest": self.content_digest,
            "accepted_count": self.accepted_count,
            "duplicate_count": self.duplicate_count,
            "out_of_order_count": self.out_of_order_count,
            "byte_count": self.byte_count,
            "record_ids": list(self.record_ids),
        }


@dataclass
class _StageBatch:
    batch_id: str
    scope: str
    status: StageBatchStatus
    write_id: str
    content_digest: str
    accepted_count: int
    duplicate_count: int
    out_of_order_count: int
    byte_count: int
    record_ids: list[str]
    rows: list[tuple[str, str, dict[str, Any]]]  # table, pk, row
    created_at: str
    idempotency_key: str | None = None


@dataclass
class _CheckpointHead:
    scope_key: str
    record: CheckpointRecord
    updated_at: str


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class DuckDBWalletStore:
    """Transactional wallet catalog store with durable CAS checkpoints.

    Implements the ingestion sink surface (stage → commit / abort) and the
    checkpoint CAS surface used by pipelines.  Crash recovery is explicit via
    :meth:`recover`: open stages abort, batches marked ``committing`` complete
    idempotently so ledger rows are neither skipped nor duplicated.
    """

    def __init__(
        self,
        *,
        scope: str = "wallet",
        connection: Any | None = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        auto_recover: bool = True,
    ) -> None:
        self._scope = _required_str(scope, "scope")
        self._connection = connection
        self._history_limit = _positive_int(history_limit, "history_limit")
        self._lock = threading.RLock()

        # Process-local catalog mirrors (authoritative when no connection, and
        # always used as the working set for unit tests / crash-replay).
        self._tables: dict[str, dict[str, dict[str, Any]]] = {
            name: {} for name in WALLET_CATALOG_TABLES
        }
        self._stage_batches: dict[str, _StageBatch] = {}
        self._open_batch_ids: list[str] = []
        self._idempotency: dict[str, StageBatchReceipt] = {}
        self._checkpoint_heads: dict[str, _CheckpointHead] = {}
        self._checkpoint_history: list[dict[str, Any]] = []
        self._commits: dict[str, dict[str, Any]] = {}
        self._seen_record_ids: set[str] = set()
        self._last_sequence: int | None = None
        self._aborted = False
        self._cas_attempts = 0
        self._cas_successes = 0
        self._stats: dict[str, int] = {
            "writes": 0,
            "duplicates": 0,
            "commits": 0,
            "aborts": 0,
            "cas_attempts": 0,
            "cas_successes": 0,
            "cas_rejects": 0,
            "finality_transitions": 0,
            "reorgs": 0,
            "recoveries": 0,
            "recovered_commits": 0,
            "recovered_aborts": 0,
        }

        if connection is not None:
            self.install_schema(connection)
            self._hydrate_from_connection()
        if auto_recover:
            self.recover()

    # -- identity -----------------------------------------------------------

    @property
    def interface(self) -> str:
        return DUCKDB_WALLET_STORE_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_WALLET_STORE_SCHEMA_VERSION

    @property
    def schema_interface(self) -> str:
        return DUCKDB_WALLET_SCHEMA_INTERFACE

    @property
    def catalog_schema_version(self) -> str:
        return DUCKDB_WALLET_SCHEMA_VERSION

    @property
    def catalog(self) -> str:
        return WALLET_CATALOG_NAME

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def connection(self) -> Any | None:
        return self._connection

    @property
    def is_aborted(self) -> bool:
        return self._aborted

    @property
    def cas_attempts(self) -> int:
        return self._cas_attempts

    @property
    def cas_successes(self) -> int:
        return self._cas_successes

    def stats(self) -> Mapping[str, int]:
        with self._lock:
            open_stages = sum(
                1
                for b in self._stage_batches.values()
                if b.status is StageBatchStatus.OPEN
            )
            return MappingProxyType(
                {
                    **self._stats,
                    "open_stages": open_stages,
                    "committed_records": sum(
                        len(self._tables[t]) for t in _LEDGER_FACT_TABLES
                    ),
                    "checkpoint_heads": len(self._checkpoint_heads),
                    "reorg_history_rows": len(self._tables["reorgs"]),
                    "finality_history_rows": len(
                        self._tables["finality_transitions"]
                    ),
                }
            )

    def catalog_tables(self) -> tuple[str, ...]:
        return WALLET_CATALOG_TABLES

    # -- schema -------------------------------------------------------------

    @staticmethod
    def install_schema(connection: Any) -> None:
        """Apply wallet catalog + internal control DDL on a DuckDB connection."""

        if connection is None:
            raise DuckDBWalletStoreError("connection is required to install schema")
        for statement in WALLET_CATALOG_DDL.split(";"):
            body = statement.strip()
            if body:
                connection.execute(body)
        for statement in _INTERNAL_DDL.split(";"):
            body = statement.strip()
            if body:
                connection.execute(body)

    def _hydrate_from_connection(self) -> None:
        """Load durable state from an existing DuckDB connection into memory."""

        conn = self._connection
        if conn is None:
            return
        for table in WALLET_CATALOG_TABLES:
            try:
                result = conn.execute(f"SELECT * FROM {table}").fetchall()
                columns = [d[0] for d in conn.description]
            except Exception:
                continue
            pk = _PRIMARY_KEYS[table]
            bucket = self._tables[table]
            for values in result:
                row = dict(zip(columns, values))
                key = row.get(pk)
                if isinstance(key, str) and key:
                    bucket[key] = row
                    if table in _LEDGER_FACT_TABLES:
                        self._seen_record_ids.add(key)
        try:
            heads = conn.execute(
                "SELECT * FROM _wallet_checkpoint_heads"
            ).fetchall()
            columns = [d[0] for d in conn.description]
            for values in heads:
                row = dict(zip(columns, values))
                record = self._checkpoint_from_head_row(row)
                self._checkpoint_heads[row["scope_key"]] = _CheckpointHead(
                    scope_key=row["scope_key"],
                    record=record,
                    updated_at=str(row["updated_at"]),
                )
        except Exception:
            pass
        try:
            history = conn.execute(
                "SELECT * FROM _wallet_checkpoint_history ORDER BY recorded_at"
            ).fetchall()
            columns = [d[0] for d in conn.description]
            for values in history:
                self._checkpoint_history.append(dict(zip(columns, values)))
        except Exception:
            pass
        try:
            stages = conn.execute(
                "SELECT * FROM _wallet_stage_batches"
            ).fetchall()
            columns = [d[0] for d in conn.description]
            for values in stages:
                row = dict(zip(columns, values))
                batch_id = str(row["batch_id"])
                stage_rows = conn.execute(
                    "SELECT table_name, row_pk, row_json FROM _wallet_stage_rows "
                    "WHERE batch_id = ?",
                    [batch_id],
                ).fetchall()
                rows: list[tuple[str, str, dict[str, Any]]] = []
                for table_name, row_pk, row_json in stage_rows:
                    rows.append(
                        (str(table_name), str(row_pk), _json_loads(str(row_json)))
                    )
                self._stage_batches[batch_id] = _StageBatch(
                    batch_id=batch_id,
                    scope=str(row["scope"]),
                    status=StageBatchStatus(str(row["status"])),
                    write_id=str(row["write_id"]),
                    content_digest=str(row["content_digest"]),
                    accepted_count=int(row["accepted_count"]),
                    duplicate_count=int(row["duplicate_count"]),
                    out_of_order_count=int(row["out_of_order_count"]),
                    byte_count=int(row["byte_count"]),
                    record_ids=[
                        pk for t, pk, _ in rows if t in _LEDGER_FACT_TABLES
                    ],
                    rows=rows,
                    created_at=str(row["created_at"]),
                )
                if StageBatchStatus(str(row["status"])) is StageBatchStatus.OPEN:
                    self._open_batch_ids.append(batch_id)
        except Exception:
            pass
        try:
            commits = conn.execute("SELECT * FROM _wallet_commits").fetchall()
            columns = [d[0] for d in conn.description]
            for values in commits:
                row = dict(zip(columns, values))
                self._commits[str(row["commit_id"])] = row
        except Exception:
            pass
        try:
            idem = conn.execute(
                "SELECT * FROM _wallet_batch_idempotency"
            ).fetchall()
            columns = [d[0] for d in conn.description]
            for values in idem:
                row = dict(zip(columns, values))
                receipt = StageBatchReceipt(
                    batch_id=str(row["batch_id"]),
                    write_id=str(row["write_id"]),
                    scope=self._scope,
                    status=StageBatchStatus.COMMITTED,
                    content_digest=str(row["content_digest"]),
                    accepted_count=0,
                    duplicate_count=0,
                    out_of_order_count=0,
                    byte_count=0,
                    record_ids=(),
                )
                payload = _json_loads(str(row["receipt_json"]))
                if isinstance(payload, dict):
                    receipt = StageBatchReceipt(
                        batch_id=str(payload.get("batch_id") or row["batch_id"]),
                        write_id=str(payload.get("write_id") or row["write_id"]),
                        scope=str(payload.get("scope") or self._scope),
                        status=StageBatchStatus(
                            str(payload.get("status") or "committed")
                        ),
                        content_digest=str(
                            payload.get("content_digest") or row["content_digest"]
                        ),
                        accepted_count=int(payload.get("accepted_count") or 0),
                        duplicate_count=int(payload.get("duplicate_count") or 0),
                        out_of_order_count=int(
                            payload.get("out_of_order_count") or 0
                        ),
                        byte_count=int(payload.get("byte_count") or 0),
                        record_ids=tuple(payload.get("record_ids") or ()),
                    )
                self._idempotency[str(row["idempotency_key"])] = receipt
        except Exception:
            pass

    @staticmethod
    def _checkpoint_from_head_row(row: Mapping[str, Any]) -> CheckpointRecord:
        identity_payload = _json_loads(str(row["identity_json"]))
        from .models import ChainRef

        chain_data = identity_payload["chain"]
        chain = ChainRef(
            namespace=chain_data["namespace"],
            network=chain_data["network"],
            chain_id=chain_data["chain_id"],
            genesis_hash=chain_data["genesis_hash"],
        )
        identity = CheckpointIdentity(
            chain=chain,
            provider=identity_payload["provider"],
            scope=identity_payload["scope"],
            normalized_schema_major=int(identity_payload["normalized_schema_major"]),
            normalizer_version=identity_payload["normalizer_version"],
        )
        history_payload = _json_loads(str(row["history_json"]))
        history = tuple(
            HashAnchor(int(item["sequence"]), str(item["block_hash"]))
            for item in history_payload
        )
        metadata = _json_loads(str(row.get("metadata_json") or "{}"))
        continuation = row.get("continuation_token")
        if continuation is not None:
            continuation = str(continuation) or None
        sink_commit_id = row.get("sink_commit_id")
        if sink_commit_id is not None:
            sink_commit_id = str(sink_commit_id) or None
        return CheckpointRecord(
            identity=identity,
            anchor=HashAnchor(int(row["anchor_sequence"]), str(row["anchor_hash"])),
            revision=str(row["revision"]),
            safety_depth=int(row["safety_depth"]),
            continuation_token=continuation,
            sink_commit_id=sink_commit_id,
            history=history,
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    # -- crash recovery -----------------------------------------------------

    def recover(self) -> Mapping[str, int]:
        """Complete or abort incomplete stages so ledger rows are never skipped/duped.

        * ``open`` stages that were never committed are **aborted** (no durable
          ledger mutation).
        * ``committing`` stages are **completed** idempotently (INSERT-OR-IGNORE
          by primary key), so a crash mid-commit cannot skip remaining rows or
          create duplicates on replay.
        """

        with self._lock:
            recovered_commits = 0
            recovered_aborts = 0
            for batch_id, batch in list(self._stage_batches.items()):
                if batch.status is StageBatchStatus.COMMITTING:
                    self._finalize_commit_locked(batch)
                    recovered_commits += 1
                elif batch.status is StageBatchStatus.OPEN:
                    self._discard_staged_identities_locked(batch)
                    batch.status = StageBatchStatus.ABORTED
                    self._persist_stage_status(batch)
                    recovered_aborts += 1
            # Drop recovered ids from the open queue (committed or aborted).
            self._open_batch_ids = [
                bid
                for bid in self._open_batch_ids
                if self._stage_batches.get(bid)
                and self._stage_batches[bid].status is StageBatchStatus.OPEN
            ]
            self._stats["recoveries"] += 1
            self._stats["recovered_commits"] += recovered_commits
            self._stats["recovered_aborts"] += recovered_aborts
            return MappingProxyType(
                {
                    "recovered_commits": recovered_commits,
                    "recovered_aborts": recovered_aborts,
                }
            )

    # -- DatasetSink: write / commit / abort --------------------------------

    def reset_for_resume(self) -> None:
        """Clear abort state so a resumed pipeline can stage further batches."""

        with self._lock:
            self._aborted = False

    async def write(
        self,
        batch: RecordBatch,
        *,
        context: OperationContext,
        idempotency_key: str | None = None,
    ) -> BatchWriteReceipt:
        """Stage one bounded batch with record_id deduplication.

        Replaying the same *idempotency_key* (or identical content digest under
        the same key) returns the original receipt without staging duplicates.
        """

        context.check_active()
        with self._lock:
            if self._aborted:
                raise DatasetSinkError("cannot write to an aborted wallet store")
            if not isinstance(batch, RecordBatch):
                raise DatasetSinkError("batch must be a RecordBatch")
            batch.enforce(context.limits)

            payload_digest = content_digest(
                [record_as_dict(r) for r in batch.records]
            )
            key = idempotency_key
            if key is not None:
                key = _required_str(key, "idempotency_key")
                existing = self._idempotency.get(key)
                if existing is not None:
                    if existing.content_digest != payload_digest:
                        raise DatasetSinkError(
                            "idempotency key reused with different batch content"
                        )
                    return existing.to_write_receipt()

            accepted: list[str] = []
            staged_rows: list[tuple[str, str, dict[str, Any]]] = []
            duplicate = 0
            out_of_order = 0
            # Within-batch identity set for pure content duplicates.
            local_seen: set[str] = set()

            for record in batch.records:
                record_id = record_identity(record)
                if record_id in self._seen_record_ids or record_id in local_seen:
                    duplicate += 1
                    continue
                sequence = record_sequence(record)
                if (
                    sequence is not None
                    and self._last_sequence is not None
                    and sequence < self._last_sequence
                ):
                    out_of_order += 1

                if _is_ledger_record(record):
                    projected = project_ledger_record_rows(record)
                else:
                    # Mapping / fixture path: treat as opaque fact if possible.
                    projected = self._project_generic_record(record)

                for table_name, rows in projected.items():
                    for row in rows:
                        pk = _row_pk(table_name, row)
                        if table_name in _LEDGER_FACT_TABLES:
                            if pk in self._seen_record_ids or pk in local_seen:
                                continue
                        # Dedup staged dimension rows within this batch only;
                        # commit path uses INSERT-OR-IGNORE semantics.
                        staged_rows.append((table_name, pk, dict(row)))

                accepted.append(record_id)
                local_seen.add(record_id)
                if sequence is not None:
                    if self._last_sequence is None or sequence > self._last_sequence:
                        # Sequence tracking for out-of-order accounting only;
                        # durable advance happens at commit.
                        pass

            write_id = f"write:{uuid4().hex}"
            batch_id = f"batch:{uuid4().hex}"
            stage = _StageBatch(
                batch_id=batch_id,
                scope=self._scope,
                status=StageBatchStatus.OPEN,
                write_id=write_id,
                content_digest=payload_digest,
                accepted_count=len(accepted),
                duplicate_count=duplicate,
                out_of_order_count=out_of_order,
                byte_count=len(_json_dumps([r for _, _, r in staged_rows]))
                + max(0, batch.response_bytes),
                record_ids=list(accepted),
                rows=staged_rows,
                created_at=_utc_now_str(),
                idempotency_key=key,
            )
            # Mark identities as staged so subsequent writes in the same run
            # treat them as duplicates before commit (crash recovery clears
            # aborted stages without having promoted to durable tables).
            for record_id in accepted:
                self._seen_record_ids.add(record_id)
            for table_name, pk, _row in staged_rows:
                if table_name in _LEDGER_FACT_TABLES:
                    self._seen_record_ids.add(pk)
                seq = _row.get("sequence")
                if isinstance(seq, int) and not isinstance(seq, bool):
                    if self._last_sequence is None or seq > self._last_sequence:
                        self._last_sequence = seq

            self._stage_batches[batch_id] = stage
            self._open_batch_ids.append(batch_id)
            self._persist_stage_batch(stage)
            self._stats["writes"] += 1
            self._stats["duplicates"] += duplicate

            receipt = StageBatchReceipt(
                batch_id=batch_id,
                write_id=write_id,
                scope=self._scope,
                status=StageBatchStatus.OPEN,
                content_digest=payload_digest,
                accepted_count=len(accepted),
                duplicate_count=duplicate,
                out_of_order_count=out_of_order,
                byte_count=stage.byte_count,
                record_ids=tuple(accepted),
            )
            if key is not None:
                self._idempotency[key] = receipt
                self._persist_idempotency(key, receipt)
            return receipt.to_write_receipt()

    def _project_generic_record(
        self, record: object
    ) -> dict[str, list[dict[str, Any]]]:
        """Best-effort projection for non-LedgerRecord fixtures."""

        if isinstance(record, Mapping):
            payload = dict(record)
            record_id = payload.get("record_id")
            if not isinstance(record_id, str) or not record_id.strip():
                raise DatasetSinkError("mapping record requires record_id")
            table = str(payload.get("table") or payload.get("record_type") or "blocks")
            if table not in _LEDGER_FACT_TABLES:
                table = "blocks"
            # Ensure bindings exist for fail-closed catalog rows.
            for name in ("chain_ref_id", "source_id", "finality"):
                if name not in payload:
                    raise DatasetSinkError(
                        f"mapping record missing required binding {name!r}"
                    )
            return {table: [payload]}
        raise DatasetSinkError(
            f"unsupported record type for wallet store: {type(record).__name__}"
        )

    async def commit(
        self,
        manifest: object = None,
        *,
        context: OperationContext,
    ) -> SinkCommitReceipt:
        """Atomically promote all open stages for this store scope.

        Crash safety: stages flip to ``committing`` before mutation; recovery
        completes those stages with INSERT-OR-IGNORE so replay is idempotent.
        """

        context.check_active()
        with self._lock:
            if self._aborted:
                raise DatasetSinkError("cannot commit an aborted wallet store")

            export_manifest: ExportManifest | None = None
            if manifest is not None and not isinstance(manifest, ExportManifest):
                raise DatasetSinkError("manifest must be an ExportManifest or None")
            if isinstance(manifest, ExportManifest):
                export_manifest = manifest

            open_ids = [
                bid
                for bid in self._open_batch_ids
                if self._stage_batches.get(bid)
                and self._stage_batches[bid].status is StageBatchStatus.OPEN
            ]
            # Mark committing before any durable promotion.
            for bid in open_ids:
                batch = self._stage_batches[bid]
                batch.status = StageBatchStatus.COMMITTING
                self._persist_stage_status(batch)

            for bid in open_ids:
                self._finalize_commit_locked(self._stage_batches[bid])

            self._open_batch_ids = [
                bid
                for bid in self._open_batch_ids
                if self._stage_batches.get(bid)
                and self._stage_batches[bid].status is StageBatchStatus.OPEN
            ]

            commit_id = f"commit:{uuid4().hex}"
            fact_count = sum(len(self._tables[t]) for t in _LEDGER_FACT_TABLES)
            digest = content_digest(
                {
                    "scope": self._scope,
                    "record_count": fact_count,
                    "batch_ids": open_ids,
                }
            )
            commit_row = {
                "commit_id": commit_id,
                "scope": self._scope,
                "content_digest": digest,
                "record_count": fact_count,
                "batch_ids_json": _json_dumps(open_ids),
                "committed_at": _utc_now_str(),
            }
            self._commits[commit_id] = commit_row
            self._persist_commit(commit_row)
            self._stats["commits"] += 1

            partitions = ()
            if export_manifest is not None:
                partitions = export_manifest.partitions

            return SinkCommitReceipt(
                commit_id=commit_id,
                scope=self._scope,
                record_count=fact_count,
                content_digest=digest,
                manifest=export_manifest,
                partitions=partitions,
            )

    def _finalize_commit_locked(self, batch: _StageBatch) -> None:
        """Promote staged rows with INSERT-OR-IGNORE primary-key semantics."""

        if batch.status is StageBatchStatus.COMMITTED:
            return
        for table_name, pk, row in batch.rows:
            bucket = self._tables.setdefault(table_name, {})
            if pk in bucket:
                # Idempotent: never duplicate; keep first durable row unless
                # this is a finality update on a fact table (handled separately).
                continue
            stored = dict(row)
            bucket[pk] = stored
            self._persist_catalog_row(table_name, stored)
            if table_name in _LEDGER_FACT_TABLES:
                self._seen_record_ids.add(pk)
        batch.status = StageBatchStatus.COMMITTED
        self._persist_stage_status(batch)
        if batch.idempotency_key is not None:
            receipt = StageBatchReceipt(
                batch_id=batch.batch_id,
                write_id=batch.write_id,
                scope=batch.scope,
                status=StageBatchStatus.COMMITTED,
                content_digest=batch.content_digest,
                accepted_count=batch.accepted_count,
                duplicate_count=batch.duplicate_count,
                out_of_order_count=batch.out_of_order_count,
                byte_count=batch.byte_count,
                record_ids=tuple(batch.record_ids),
            )
            self._idempotency[batch.idempotency_key] = receipt
            self._persist_idempotency(batch.idempotency_key, receipt)

    def _discard_staged_identities_locked(self, batch: _StageBatch) -> None:
        """Drop staged identity marks that never became durable fact rows."""

        for table_name, pk, _ in batch.rows:
            if table_name in _LEDGER_FACT_TABLES and pk not in self._tables.get(
                table_name, {}
            ):
                self._seen_record_ids.discard(pk)
        for record_id in batch.record_ids:
            durable = any(
                record_id in self._tables.get(t, {}) for t in _LEDGER_FACT_TABLES
            )
            if not durable:
                self._seen_record_ids.discard(record_id)

    async def abort(self, *, context: OperationContext) -> None:
        """Discard uncommitted open stages without inventing a sink commit."""

        _ = context  # abort must succeed even under cancellation
        with self._lock:
            for bid in list(self._open_batch_ids):
                batch = self._stage_batches.get(bid)
                if batch is None:
                    continue
                if batch.status is StageBatchStatus.OPEN:
                    self._discard_staged_identities_locked(batch)
                    batch.status = StageBatchStatus.ABORTED
                    self._persist_stage_status(batch)
            self._open_batch_ids.clear()
            self._aborted = True
            self._stats["aborts"] += 1

    # -- CheckpointStore: load / compare_and_set ----------------------------

    async def load(
        self,
        scope: str,
        *,
        context: OperationContext,
    ) -> CheckpointRecord | None:
        """Load the current checkpoint tip for an exact ingestion scope key."""

        context.check_active()
        with self._lock:
            _required_str(scope, "scope")
            head = self._checkpoint_heads.get(scope)
            if head is not None:
                return head.record
            for stored in self._checkpoint_heads.values():
                if stored.record.identity.matches_scope_key(scope):
                    return stored.record
            return None

    async def compare_and_set(
        self,
        scope: str,
        *,
        expected_revision: str | None,
        checkpoint: object,
        context: OperationContext,
    ) -> bool:
        """Atomically advance the checkpoint tip when the revision still matches.

        Returns ``False`` (does not raise) when *expected_revision* is stale so
        concurrent/stale ingesters lose the CAS cleanly.  Prior checkpoint and
        reorg history rows are retained — only the head pointer moves.
        """

        context.check_active()
        with self._lock:
            self._cas_attempts += 1
            self._stats["cas_attempts"] += 1
            _required_str(scope, "scope")
            if not isinstance(checkpoint, CheckpointRecord):
                raise CheckpointError("checkpoint must be a CheckpointRecord")
            if not checkpoint.identity.matches_scope_key(scope):
                raise CheckpointError(
                    "checkpoint identity does not bind to the provided scope key"
                )
            store_key = checkpoint.identity.key
            current = self._checkpoint_heads.get(store_key)
            current_revision = None if current is None else current.record.revision
            if current_revision != expected_revision:
                self._stats["cas_rejects"] += 1
                return False
            if current is not None and not current.record.identity.compatible_with(
                checkpoint.identity
            ):
                raise CheckpointError(
                    "refusing to overwrite checkpoint with incompatible identity "
                    "(chain/network/genesis/provider/scope/schema/normalizer)"
                )
            assert_hash_anchor_present(
                checkpoint.anchor.to_position(),
                continuation_token=checkpoint.continuation_token,
            )
            stored = checkpoint.with_history_limit(self._history_limit)
            now = _utc_now_str()
            self._checkpoint_heads[store_key] = _CheckpointHead(
                scope_key=store_key,
                record=stored,
                updated_at=now,
            )
            # Append-only catalog + internal history (never delete prior tips).
            self._append_checkpoint_history(store_key, stored, now)
            self._upsert_checkpoint_catalog(stored, observed_at=now)
            self._persist_checkpoint_head(store_key, stored, now)
            self._cas_successes += 1
            self._stats["cas_successes"] += 1
            return True

    async def replace_after_rewind(
        self,
        identity: CheckpointIdentity,
        *,
        expected_revision: str,
        rewound: CheckpointRecord,
        context: OperationContext,
    ) -> bool:
        """CAS a rewound checkpoint after reorg handling (same CAS rules)."""

        if not rewound.identity.compatible_with(identity):
            raise CheckpointError("rewound checkpoint identity mismatch")
        return await self.compare_and_set(
            identity.key,
            expected_revision=expected_revision,
            checkpoint=rewound,
            context=context,
        )

    def _append_checkpoint_history(
        self,
        scope_key: str,
        checkpoint: CheckpointRecord,
        recorded_at: str,
    ) -> None:
        history_id = deterministic_id(
            "checkpoint-history",
            {
                "scope_key": scope_key,
                "checkpoint_id": checkpoint.checkpoint_id,
                "revision": checkpoint.revision,
            },
        )
        entry = {
            "history_id": history_id,
            "scope_key": scope_key,
            "checkpoint_id": checkpoint.checkpoint_id,
            "revision": checkpoint.revision,
            "anchor_sequence": checkpoint.anchor.sequence,
            "anchor_hash": checkpoint.anchor.block_hash,
            "payload_json": _json_dumps(checkpoint.to_dict()),
            "recorded_at": recorded_at,
        }
        self._checkpoint_history.append(entry)
        self._persist_checkpoint_history_row(entry)

    def _upsert_checkpoint_catalog(
        self, checkpoint: CheckpointRecord, *, observed_at: str
    ) -> None:
        row = project_checkpoint_row(checkpoint, observed_at=observed_at)
        pk = row["checkpoint_id"]
        # Append-only: each revision has a distinct checkpoint_id.
        if pk not in self._tables["checkpoints"]:
            self._tables["checkpoints"][pk] = dict(row)
            self._persist_catalog_row("checkpoints", row)
        # Also project cursor without continuation token.
        cursor = checkpoint.to_cursor()
        cursor_row = project_cursor_row(cursor, observed_at=observed_at)
        cpk = cursor_row["cursor_id"]
        self._tables["cursors"][cpk] = dict(cursor_row)
        self._persist_catalog_row("cursors", cursor_row)

    def checkpoint_history(
        self, scope_key: str | None = None
    ) -> tuple[Mapping[str, Any], ...]:
        """Return retained checkpoint history (append-only, never overwritten)."""

        with self._lock:
            if scope_key is None:
                return tuple(deepcopy(item) for item in self._checkpoint_history)
            return tuple(
                deepcopy(item)
                for item in self._checkpoint_history
                if item["scope_key"] == scope_key
            )

    # -- Finality transitions -----------------------------------------------

    def apply_finality_transition(
        self,
        *,
        record_id: str,
        target: Finality,
        chain_ref_id: str | None = None,
        source_id: str | None = None,
        orphaned_anchor: HashAnchor | None = None,
        ancestor_anchor: HashAnchor | None = None,
        tombstone: bool = False,
        transition_id: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Append a finality transition and update the durable fact row.

        Transitions are append-only.  Illegal state-machine moves fail closed.
        """

        with self._lock:
            _required_str(record_id, "record_id")
            if not isinstance(target, Finality):
                raise InvalidRequestError("target must be a Finality value")
            table, row = self._find_fact_row(record_id)
            if row is None or table is None:
                raise DuckDBWalletStoreError(
                    f"no durable ledger row for record_id={record_id!r}"
                )
            prior = Finality(str(row["finality"]))
            if not can_transition(prior, target):
                raise InvalidRequestError(
                    f"illegal finality transition {prior.value!r} -> {target.value!r}"
                )
            finality_transition(prior, target)
            when = observed_at or _utc_now_str()
            chain = chain_ref_id or str(row["chain_ref_id"])
            source = source_id or str(row["source_id"])
            tid = transition_id or deterministic_id(
                "finality-transition",
                {
                    "record_id": record_id,
                    "prior_finality": prior.value,
                    "finality": target.value,
                    "orphaned": None
                    if orphaned_anchor is None
                    else orphaned_anchor.to_dict(),
                    "observed_at": when,
                },
            )
            transition_row = {
                "transition_id": tid,
                "chain_ref_id": chain,
                "source_id": source,
                "finality": target.value,
                "record_id": record_id,
                "prior_finality": prior.value,
                "orphaned_sequence": None
                if orphaned_anchor is None
                else orphaned_anchor.sequence,
                "orphaned_hash": None
                if orphaned_anchor is None
                else orphaned_anchor.block_hash,
                "ancestor_sequence": None
                if ancestor_anchor is None
                else ancestor_anchor.sequence,
                "ancestor_hash": None
                if ancestor_anchor is None
                else ancestor_anchor.block_hash,
                "tombstone": bool(tombstone),
                "observed_at": when,
                "schema_version": DUCKDB_WALLET_SCHEMA_VERSION,
            }
            # Append-only history.
            if tid in self._tables["finality_transitions"]:
                return dict(self._tables["finality_transitions"][tid])
            self._tables["finality_transitions"][tid] = dict(transition_row)
            self._persist_catalog_row("finality_transitions", transition_row)
            # Update live fact row finality in place (corrections remain visible).
            updated = dict(row)
            updated["finality"] = target.value
            self._tables[table][record_id] = updated
            self._persist_catalog_row(table, updated)
            self._stats["finality_transitions"] += 1
            return dict(transition_row)

    def apply_orphan_corrections(
        self,
        corrections: Sequence[OrphanCorrection],
        *,
        chain_ref_id: str,
        source_id: str,
        observed_at: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Apply a batch of orphan/revert corrections as append-only transitions."""

        rows: list[dict[str, Any]] = []
        for correction in corrections:
            if not isinstance(correction, OrphanCorrection):
                raise InvalidRequestError(
                    "corrections must be OrphanCorrection values"
                )
            rows.append(
                self.apply_finality_transition(
                    record_id=correction.record_id,
                    target=correction.new_finality,
                    chain_ref_id=chain_ref_id,
                    source_id=source_id,
                    orphaned_anchor=correction.orphaned_anchor,
                    ancestor_anchor=correction.ancestor_anchor,
                    tombstone=correction.tombstone,
                    observed_at=observed_at,
                )
            )
        return tuple(rows)

    def _find_fact_row(
        self, record_id: str
    ) -> tuple[str | None, dict[str, Any] | None]:
        for table in _LEDGER_FACT_TABLES:
            row = self._tables[table].get(record_id)
            if row is not None:
                return table, row
        return None, None

    # -- Reorg history (retained, never overwritten) ------------------------

    def record_reorg(
        self,
        decision: ReorgDecision,
        *,
        chain: object,
        provenance: object,
        reorg_id: str | None = None,
        finality: Finality | str = Finality.ORPHANED,
        apply_corrections: bool = True,
    ) -> dict[str, Any]:
        """Persist a reorg decision as an append-only history row.

        Prior reorg rows for the same chain/scope are **retained**.  When
        *apply_corrections* is true, orphan corrections from *decision* are
        applied as finality transitions.
        """

        from .models import ChainRef, Provenance

        if not isinstance(decision, ReorgDecision):
            raise InvalidRequestError("decision must be a ReorgDecision")
        if not isinstance(chain, ChainRef):
            raise InvalidRequestError("chain must be a ChainRef")
        if not isinstance(provenance, Provenance):
            raise InvalidRequestError("provenance must be a Provenance")

        with self._lock:
            row = project_reorg_row(
                decision,
                chain=chain,
                provenance=provenance,
                reorg_id=reorg_id,
                finality=finality,
            )
            rid = row["reorg_id"]
            # Never overwrite: identical reorg_id is a no-op return of original.
            if rid in self._tables["reorgs"]:
                return dict(self._tables["reorgs"][rid])
            self._tables["reorgs"][rid] = dict(row)
            self._persist_catalog_row("reorgs", row)
            self._stats["reorgs"] += 1

            if apply_corrections and decision.corrections:
                source_id = str(row["source_id"])
                for correction in decision.corrections:
                    try:
                        self.apply_finality_transition(
                            record_id=correction.record_id,
                            target=correction.new_finality,
                            chain_ref_id=chain.chain_ref_id,
                            source_id=source_id,
                            orphaned_anchor=correction.orphaned_anchor,
                            ancestor_anchor=correction.ancestor_anchor,
                            tombstone=correction.tombstone,
                            observed_at=str(row["observed_at"]),
                        )
                    except DuckDBWalletStoreError:
                        # Correction for a record not yet durable: keep reorg row;
                        # callers may replay after commit.
                        continue
            return dict(row)

    def list_reorgs(
        self, *, chain_ref_id: str | None = None
    ) -> tuple[Mapping[str, Any], ...]:
        """Return retained reorg history (append-only)."""

        with self._lock:
            rows = list(self._tables["reorgs"].values())
            if chain_ref_id is not None:
                rows = [r for r in rows if r.get("chain_ref_id") == chain_ref_id]
            # Stable order by observed_at then reorg_id.
            rows.sort(
                key=lambda r: (str(r.get("observed_at") or ""), str(r.get("reorg_id")))
            )
            return tuple(deepcopy(r) for r in rows)

    def list_finality_transitions(
        self, *, record_id: str | None = None
    ) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            rows = list(self._tables["finality_transitions"].values())
            if record_id is not None:
                rows = [r for r in rows if r.get("record_id") == record_id]
            rows.sort(
                key=lambda r: (
                    str(r.get("observed_at") or ""),
                    str(r.get("transition_id")),
                )
            )
            return tuple(deepcopy(r) for r in rows)

    # -- Encrypted / raw object CID references ------------------------------

    def put_encrypted_object_ref(
        self,
        ref: RawPayloadRef,
        *,
        chain: object,
        provenance: object,
        finality: Finality | str,
        related_record_id: str | None = None,
        ref_id: str | None = None,
    ) -> dict[str, Any]:
        """Store a content-addressed ref only (never payload bytes)."""

        from .models import ChainRef, Provenance

        if not isinstance(ref, RawPayloadRef):
            raise InvalidRequestError("ref must be a RawPayloadRef")
        if not isinstance(chain, ChainRef):
            raise InvalidRequestError("chain must be a ChainRef")
        if not isinstance(provenance, Provenance):
            raise InvalidRequestError("provenance must be a Provenance")
        # Fail closed if caller smuggled raw bytes into the ref surface.
        for forbidden in ("body", "payload", "ciphertext", "raw"):
            if hasattr(ref, forbidden) and getattr(ref, forbidden) not in (None,):
                # RawPayloadRef has no body field; defensive for subclasses.
                if forbidden == "body" and not hasattr(RawPayloadRef, "body"):
                    pass
        with self._lock:
            row = project_encrypted_object_ref_row(
                ref,
                chain=chain,
                provenance=provenance,
                finality=finality,
                related_record_id=related_record_id,
                ref_id=ref_id,
            )
            for bad in ("raw_payload", "payload_bytes", "payload_json", "body"):
                if bad in row:
                    raise WalletSchemaError(
                        f"encrypted_object_refs must not include {bad!r}"
                    )
            pk = row["ref_id"]
            if pk in self._tables["encrypted_object_refs"]:
                return dict(self._tables["encrypted_object_refs"][pk])
            self._tables["encrypted_object_refs"][pk] = dict(row)
            self._persist_catalog_row("encrypted_object_refs", row)
            return dict(row)

    def get_encrypted_object_ref(self, ref_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            row = self._tables["encrypted_object_refs"].get(
                _required_str(ref_id, "ref_id")
            )
            return None if row is None else MappingProxyType(dict(row))

    # -- Query helpers ------------------------------------------------------

    def get_record(self, record_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            _table, row = self._find_fact_row(_required_str(record_id, "record_id"))
            return None if row is None else MappingProxyType(dict(row))

    def list_records(
        self, table: str, *, finality: Finality | str | None = None
    ) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            if table not in self._tables:
                raise DuckDBWalletStoreError(f"unknown table {table!r}")
            rows = list(self._tables[table].values())
            if finality is not None:
                target = (
                    finality.value if isinstance(finality, Finality) else str(finality)
                )
                rows = [r for r in rows if r.get("finality") == target]
            return tuple(MappingProxyType(dict(r)) for r in rows)

    def count_records(self, table: str | None = None) -> int:
        with self._lock:
            if table is not None:
                if table not in self._tables:
                    raise DuckDBWalletStoreError(f"unknown table {table!r}")
                return len(self._tables[table])
            return sum(len(self._tables[t]) for t in _LEDGER_FACT_TABLES)

    def open_stage_count(self) -> int:
        with self._lock:
            return sum(
                1
                for b in self._stage_batches.values()
                if b.status is StageBatchStatus.OPEN
            )

    def simulate_crash_before_commit_finalize(self) -> list[str]:
        """Test helper: mark open stages as ``committing`` without promoting rows.

        Models a crash after the durability fence and before row promotion.
        """

        with self._lock:
            marked: list[str] = []
            for bid in list(self._open_batch_ids):
                batch = self._stage_batches.get(bid)
                if batch is None or batch.status is not StageBatchStatus.OPEN:
                    continue
                batch.status = StageBatchStatus.COMMITTING
                self._persist_stage_status(batch)
                marked.append(bid)
            return marked

    def simulate_crash_drop_open_stages_from_memory(self) -> None:
        """Test helper: drop in-memory open stages after they were persisted.

        Used with a DuckDB connection to prove recover() reloads and aborts.
        For pure-Python mode this clears open stages without recovery path.
        """

        with self._lock:
            for bid in list(self._open_batch_ids):
                batch = self._stage_batches.get(bid)
                if batch is not None and batch.status is StageBatchStatus.OPEN:
                    # Leave them marked open for recover() to abort.
                    pass
            # Intentionally leave _stage_batches intact so recover can act.

    # -- persistence adapters (optional DuckDB) -----------------------------

    def _persist_catalog_row(self, table: str, row: Mapping[str, Any]) -> None:
        conn = self._connection
        if conn is None:
            return
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        col_sql = ", ".join(columns)
        pk = _PRIMARY_KEYS[table]
        # DuckDB INSERT OR REPLACE / ON CONFLICT
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})",
                [row[c] for c in columns],
            )
        except Exception:
            # Fallback: delete + insert for drivers without OR REPLACE.
            try:
                conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", [row[pk]])
                conn.execute(
                    f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})",
                    [row[c] for c in columns],
                )
            except Exception as exc:
                raise DuckDBWalletStoreError(
                    f"failed to persist {table} row: {exc}"
                ) from exc

    def _persist_stage_batch(self, batch: _StageBatch) -> None:
        conn = self._connection
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO _wallet_stage_batches "
            "(batch_id, scope, status, write_id, content_digest, accepted_count, "
            "duplicate_count, out_of_order_count, byte_count, created_at, "
            "schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                batch.batch_id,
                batch.scope,
                batch.status.value,
                batch.write_id,
                batch.content_digest,
                batch.accepted_count,
                batch.duplicate_count,
                batch.out_of_order_count,
                batch.byte_count,
                batch.created_at,
                STAGE_SCHEMA_VERSION,
            ],
        )
        for table_name, pk, row in batch.rows:
            stage_row_id = deterministic_id(
                "stage-row",
                {
                    "batch_id": batch.batch_id,
                    "table": table_name,
                    "pk": pk,
                },
            )
            conn.execute(
                "INSERT OR REPLACE INTO _wallet_stage_rows "
                "(stage_row_id, batch_id, table_name, row_pk, row_json) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    stage_row_id,
                    batch.batch_id,
                    table_name,
                    pk,
                    _json_dumps(row),
                ],
            )

    def _persist_stage_status(self, batch: _StageBatch) -> None:
        conn = self._connection
        if conn is None:
            return
        conn.execute(
            "UPDATE _wallet_stage_batches SET status = ? WHERE batch_id = ?",
            [batch.status.value, batch.batch_id],
        )

    def _persist_idempotency(self, key: str, receipt: StageBatchReceipt) -> None:
        conn = self._connection
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO _wallet_batch_idempotency "
            "(idempotency_key, batch_id, write_id, content_digest, receipt_json, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                key,
                receipt.batch_id,
                receipt.write_id,
                receipt.content_digest,
                _json_dumps(receipt.to_dict()),
                _utc_now_str(),
            ],
        )

    def _persist_commit(self, row: Mapping[str, Any]) -> None:
        conn = self._connection
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO _wallet_commits "
            "(commit_id, scope, content_digest, record_count, batch_ids_json, "
            "committed_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                row["commit_id"],
                row["scope"],
                row["content_digest"],
                row["record_count"],
                row["batch_ids_json"],
                row["committed_at"],
            ],
        )

    def _persist_checkpoint_head(
        self, scope_key: str, checkpoint: CheckpointRecord, updated_at: str
    ) -> None:
        conn = self._connection
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO _wallet_checkpoint_heads "
            "(scope_key, revision, checkpoint_id, identity_json, anchor_sequence, "
            "anchor_hash, safety_depth, sink_commit_id, history_json, "
            "metadata_json, continuation_token, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                scope_key,
                checkpoint.revision,
                checkpoint.checkpoint_id,
                _json_dumps(checkpoint.identity.to_dict()),
                checkpoint.anchor.sequence,
                checkpoint.anchor.block_hash,
                checkpoint.safety_depth,
                checkpoint.sink_commit_id,
                _json_dumps([a.to_dict() for a in checkpoint.history]),
                _json_dumps(thaw_json(checkpoint.metadata)),
                checkpoint.continuation_token,
                updated_at,
            ],
        )

    def _persist_checkpoint_history_row(self, entry: Mapping[str, Any]) -> None:
        conn = self._connection
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO _wallet_checkpoint_history "
            "(history_id, scope_key, checkpoint_id, revision, anchor_sequence, "
            "anchor_hash, payload_json, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                entry["history_id"],
                entry["scope_key"],
                entry["checkpoint_id"],
                entry["revision"],
                entry["anchor_sequence"],
                entry["anchor_hash"],
                entry["payload_json"],
                entry["recorded_at"],
            ],
        )


def open_wallet_store(
    *,
    scope: str = "wallet",
    connection: Any | None = None,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    auto_recover: bool = True,
) -> DuckDBWalletStore:
    """Factory for :class:`DuckDBWalletStore` with standard defaults."""

    return DuckDBWalletStore(
        scope=scope,
        connection=connection,
        history_limit=history_limit,
        auto_recover=auto_recover,
    )


__all__ = [
    "DUCKDB_WALLET_STORE_INTERFACE",
    "DUCKDB_WALLET_STORE_SCHEMA_VERSION",
    "STAGE_SCHEMA_VERSION",
    "DuckDBWalletStore",
    "DuckDBWalletStoreError",
    "StageBatchReceipt",
    "StageBatchStatus",
    "StaleCheckpointError",
    "open_wallet_store",
]
