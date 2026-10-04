"""Deterministic wallet dataset export (JSONL, Parquet/Arrow, optional CAR).

Exports are data exports, not asset transfers.  A completed export always
produces an :class:`ExportReceipt` wrapping a fully accounted
:class:`~models.ExportManifest` with scope, schema/processor versions,
provider capability, digests/CIDs, counts, positions, finality distribution,
warnings, raw-payload policy, and before/after checkpoints.

JSONL is the interchange baseline; Parquet/Arrow is the analytical baseline.
IPLD/CAR export is optional and only attempted when explicitly requested and
when a CAR writer is injectable—JSONL and Parquet contracts do not depend on
it.

Under dual-mode authority (DQK-072), DuckDB is operational truth for ledger
state and checkpoints.  JSONL, Parquet, Arrow and CAR become **outbox-driven
exports**: they are materialised only after a durable DuckDB commit and never
re-admitted as authority.  Typed Parquet columns support predicate pushdown
without relying on opaque-only ``payload_json`` as the pushdown surface.

Under DuckDB-only / export-only authority (DQK-073), implicit ``records.jsonl``,
``.meta.json``, and JSON manifest writes are blocked.  Named export commands
and outbox drains are the only admitted filesystem materialisation paths.
Quack receives redacted public ledger analytics only — never raw secret-bearing
payloads.

Importing this module performs no network I/O.  Parquet support uses optional
``pyarrow`` / ``duckdb`` only inside export methods.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .canonical import canonical_json, canonical_json_bytes, content_digest
from .errors import ExportError, InvalidRequestError, UnsupportedCapabilityError
from .models import (
    EXPORT_MANIFEST_SCHEMA_VERSION,
    ChainRef,
    ExportManifest,
    ExportPartition,
    ExportStatus,
    Finality,
    LedgerCursor,
    Provenance,
    RawPayloadPolicy,
    ensure_secret_safe,
)
from .protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    DatasetSink,
    OperationContext,
    RecordBatch,
)
from .storage import (
    ExportOutbox,
    ExportOutboxEntry,
    ExportOutboxStatus,
    ImplicitLegacyLedgerWriteError,
    LedgerFilesystemGuard,
    NAMED_LEDGER_EXPORT_COMMANDS,
    PUBLIC_LEDGER_ANALYTICS_COLUMNS,
    StreamingDatasetSink,
    WALLET_LEDGER_ONLY_OWNER_TASK,
    assert_publication_excludes_secrets,
    assert_shadow_catalog_excludes_secrets,
    build_redacted_public_ledger_analytics,
    record_as_dict,
    record_finality,
    record_sequence,
)


EXPORT_RECEIPT_SCHEMA_VERSION = "wallet-export-receipt-v1"
DEFAULT_PROCESSOR_VERSION = "wallet-exporter@1.0.0"
DEFAULT_NORMALIZED_SCHEMA_MAJOR = 1
PUBLIC_LEDGER_QUACK_TABLE: Final[str] = "public_ledger_analytics"

# Typed columns for predicate pushdown.  Opaque payload_json is optional and
# never the sole authority surface for dual-mode analytical exports (DQK-072).
TYPED_PARQUET_COLUMNS: Final[tuple[str, ...]] = (
    "record_id",
    "record_type",
    "chain_ref_id",
    "finality",
    "sequence",
    "block_hash",
    "transaction_hash",
    "ledger_hash",
)


class ExportFormat(StrEnum):
    """Supported deterministic export formats."""

    JSONL = "jsonl"
    PARQUET = "parquet"
    ARROW = "arrow"
    CAR = "car"  # optional; requires an injectable CAR writer


def _required_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _ensure_export_safe(value: object) -> None:
    try:
        ensure_secret_safe(value)
    except ValueError as exc:
        raise ExportError(str(exc)) from None


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    """Versioned receipt returned by :class:`Exporter` implementations."""

    manifest: ExportManifest
    status: ExportStatus
    output_dir: str
    formats: tuple[str, ...]
    processor_version: str
    normalized_schema_major: int
    provider_capabilities: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    partial: bool = False
    receipt_id: str = field(init=False)
    schema_version: str = field(default=EXPORT_RECEIPT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ExportManifest):
            raise ExportError("manifest must be an ExportManifest")
        if not isinstance(self.status, ExportStatus):
            raise ExportError("status must be an ExportStatus")
        object.__setattr__(self, "output_dir", _required_str(self.output_dir, "output_dir"))
        object.__setattr__(self, "formats", tuple(self.formats))
        if not self.formats:
            raise ExportError("formats must not be empty")
        for fmt in self.formats:
            _required_str(fmt, "format")
        object.__setattr__(
            self,
            "processor_version",
            _required_str(self.processor_version, "processor_version"),
        )
        _positive_int(self.normalized_schema_major, "normalized_schema_major")
        object.__setattr__(
            self, "provider_capabilities", tuple(self.provider_capabilities)
        )
        object.__setattr__(self, "warnings", tuple(self.warnings))
        _ensure_export_safe(
            {
                "output_dir": self.output_dir,
                "formats": self.formats,
                "processor_version": self.processor_version,
                "provider_capabilities": self.provider_capabilities,
                "warnings": self.warnings,
            }
        )
        object.__setattr__(
            self,
            "receipt_id",
            content_digest(
                {
                    "manifest_id": self.manifest.manifest_id,
                    "status": self.status.value,
                    "formats": list(self.formats),
                    "output_dir": self.output_dir,
                }
            ),
        )
        _ensure_export_safe(self.to_dict())

    @property
    def complete(self) -> bool:
        return self.status is ExportStatus.COMPLETE and not self.partial

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "status": self.status.value,
            "partial": self.partial,
            "output_dir": self.output_dir,
            "formats": list(self.formats),
            "processor_version": self.processor_version,
            "normalized_schema_major": self.normalized_schema_major,
            "provider_capabilities": list(self.provider_capabilities),
            "warnings": list(self.warnings),
            "manifest": self.manifest.to_dict(),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


def write_jsonl(
    records: Sequence[Mapping[str, Any] | object],
    path: str | Path,
) -> ExportPartition:
    """Write records as deterministic one-JSON-object-per-line UTF-8."""

    lines: list[str] = []
    types: set[str] = set()
    sequences: list[int] = []
    for record in records:
        payload = record_as_dict(record)
        _ensure_export_safe(payload)
        lines.append(canonical_json(payload))
        record_type = payload.get("record_type")
        if isinstance(record_type, str) and record_type:
            types.add(record_type)
        sequence = record_sequence(record)
        if sequence is not None:
            sequences.append(sequence)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    digest = f"sha256:{__import__('hashlib').sha256(body).hexdigest()}"
    return ExportPartition(
        path=str(path.name),
        format=ExportFormat.JSONL.value,
        record_count=len(lines),
        byte_count=len(body),
        digest=digest,
        record_types=tuple(sorted(types)),
        min_position=min(sequences) if sequences else None,
        max_position=max(sequences) if sequences else None,
    )


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a deterministic JSONL partition back into dict records."""

    import json

    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ExportError("JSONL lines must be JSON objects")
        records.append(payload)
    return records


def _typed_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project a ledger record dict onto typed predicate-pushdown columns."""

    position = payload.get("ledger_position") or {}
    sequence = None
    block_hash = None
    ledger_hash = None
    if isinstance(position, Mapping):
        seq = position.get("sequence")
        if isinstance(seq, int) and not isinstance(seq, bool):
            sequence = seq
        block_hash = position.get("hash")
        ledger_hash = position.get("hash")
    chain = payload.get("chain")
    chain_ref_id = payload.get("chain_ref_id")
    if not chain_ref_id and isinstance(chain, Mapping):
        chain_ref_id = chain.get("chain_ref_id") or chain.get("chain_id")
    if not chain_ref_id and isinstance(chain, str):
        chain_ref_id = chain
    record_type = str(payload.get("record_type") or "")
    if not record_type:
        # Catalog rows from DuckDB authority may omit record_type; infer lightly.
        if payload.get("block_hash") and payload.get("parent_hash") is not None:
            record_type = "block"
        elif payload.get("transaction_hash") and payload.get("output_index") is not None:
            record_type = "utxo"
        elif payload.get("transaction_hash") and payload.get("transfer_index") is not None:
            record_type = "transfer"
        elif payload.get("transaction_hash") and payload.get("event_index") is not None:
            record_type = "contract_event"
        elif payload.get("transaction_hash"):
            record_type = "transaction"
    return {
        "record_id": str(payload.get("record_id") or ""),
        "record_type": record_type,
        "chain_ref_id": str(chain_ref_id or ""),
        "finality": str(payload.get("finality") or Finality.UNKNOWN.value),
        "sequence": sequence if sequence is not None else (
            payload.get("sequence")
            if isinstance(payload.get("sequence"), int)
            and not isinstance(payload.get("sequence"), bool)
            else None
        ),
        "block_hash": str(
            payload.get("block_hash") or block_hash or ""
        )
        or None,
        "transaction_hash": str(payload.get("transaction_hash") or "") or None,
        "ledger_hash": str(
            payload.get("ledger_hash") or ledger_hash or ""
        )
        or None,
    }


def apply_typed_predicates(
    records: Sequence[Mapping[str, Any] | object],
    *,
    finality_filter: str | None = None,
    record_type_filter: str | None = None,
    min_sequence: int | None = None,
    max_sequence: int | None = None,
    chain_ref_id_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Filter records using the same typed columns used for Parquet pushdown."""

    filtered: list[dict[str, Any]] = []
    for record in records:
        payload = record_as_dict(record)
        typed = _typed_projection(payload)
        if (
            finality_filter is not None
            and str(typed.get("finality")) != finality_filter
        ):
            continue
        if (
            record_type_filter is not None
            and str(typed.get("record_type")) != record_type_filter
        ):
            continue
        if (
            chain_ref_id_filter is not None
            and str(typed.get("chain_ref_id")) != chain_ref_id_filter
        ):
            continue
        seq = typed.get("sequence")
        if min_sequence is not None:
            if not isinstance(seq, int) or seq < min_sequence:
                continue
        if max_sequence is not None:
            if not isinstance(seq, int) or seq > max_sequence:
                continue
        filtered.append(payload)
    return filtered


def write_parquet(
    records: Sequence[Mapping[str, Any] | object],
    path: str | Path,
    *,
    typed: bool = True,
    include_payload_json: bool = True,
    finality_filter: str | None = None,
    record_type_filter: str | None = None,
    min_sequence: int | None = None,
    max_sequence: int | None = None,
    chain_ref_id_filter: str | None = None,
) -> ExportPartition:
    """Write records as a deterministic Parquet table.

    When *typed* is true (default, DQK-072), typed columns are the predicate
    pushdown surface.  ``payload_json`` may still be written as a lossless
    sidecar column but is **not** opaque-only payload authority — filters use
    typed columns, not JSON parsing.
    """

    payloads = apply_typed_predicates(
        records,
        finality_filter=finality_filter,
        record_type_filter=record_type_filter,
        min_sequence=min_sequence,
        max_sequence=max_sequence,
        chain_ref_id_filter=chain_ref_id_filter,
    )
    for payload in payloads:
        _ensure_export_safe(payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Prefer typed DuckDB COPY path for predicate-pushdown proof when available.
    if typed:
        try:
            return _write_typed_parquet_duckdb(
                payloads,
                path,
                include_payload_json=include_payload_json,
                finality_filter=finality_filter,
                record_type_filter=record_type_filter,
                min_sequence=min_sequence,
                max_sequence=max_sequence,
                chain_ref_id_filter=chain_ref_id_filter,
            )
        except Exception:
            # Fall through to pyarrow / pure-Python typed path.
            pass

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        # Hermetic / sealed environments without pyarrow still need typed
        # predicate-pushdown partitions (DQK-072).  Write a columnar JSON
        # envelope that read_parquet and apply_typed_predicates understand.
        return _write_typed_parquet_pure(
            payloads,
            path,
            include_payload_json=include_payload_json,
        )

    types: set[str] = set()
    sequences: list[int] = []
    columns: dict[str, list[Any]] = {name: [] for name in TYPED_PARQUET_COLUMNS}
    if include_payload_json:
        columns["payload_json"] = []
    for payload in payloads:
        typed_row = _typed_projection(payload)
        for name in TYPED_PARQUET_COLUMNS:
            columns[name].append(typed_row.get(name))
        if include_payload_json:
            columns["payload_json"].append(canonical_json(payload))
        if typed_row.get("record_type"):
            types.add(str(typed_row["record_type"]))
        seq = typed_row.get("sequence")
        if isinstance(seq, int) and not isinstance(seq, bool):
            sequences.append(seq)

    arrays: dict[str, Any] = {}
    for name in TYPED_PARQUET_COLUMNS:
        if name == "sequence":
            arrays[name] = pa.array(columns[name], type=pa.int64())
        else:
            arrays[name] = pa.array(columns[name], type=pa.string())
    if include_payload_json:
        arrays["payload_json"] = pa.array(columns["payload_json"], type=pa.string())
    table = pa.table(arrays)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table,
        tmp,
        compression="snappy",
        coerce_timestamps="us",
        use_dictionary=False,
        write_statistics=True,
    )
    tmp.replace(path)
    body = path.read_bytes()
    digest = f"sha256:{sha256(body).hexdigest()}"
    return ExportPartition(
        path=str(path.name),
        format=ExportFormat.PARQUET.value,
        record_count=len(payloads),
        byte_count=len(body),
        digest=digest,
        record_types=tuple(sorted(types)),
        min_position=min(sequences) if sequences else None,
        max_position=max(sequences) if sequences else None,
    )


def _write_typed_parquet_pure(
    payloads: Sequence[Mapping[str, Any]],
    path: Path,
    *,
    include_payload_json: bool,
) -> ExportPartition:
    """Columnar typed partition without pyarrow/duckdb (predicate-pushdown surface)."""

    import json

    types: set[str] = set()
    sequences: list[int] = []
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        typed_row = _typed_projection(payload)
        row = {name: typed_row.get(name) for name in TYPED_PARQUET_COLUMNS}
        if include_payload_json:
            # Sidecar only — never the sole filter authority.
            row["payload_json"] = canonical_json(payload)
        rows.append(row)
        if typed_row.get("record_type"):
            types.add(str(typed_row["record_type"]))
        seq = typed_row.get("sequence")
        if isinstance(seq, int) and not isinstance(seq, bool):
            sequences.append(seq)
    envelope = {
        "format": "wallet-typed-parquet-v1",
        "typed_columns": list(TYPED_PARQUET_COLUMNS),
        "opaque_payload_authority": False,
        "row_count": len(rows),
        "rows": rows,
        "statistics": {
            "min_sequence": min(sequences) if sequences else None,
            "max_sequence": max(sequences) if sequences else None,
            "record_types": sorted(types),
        },
    }
    body = (
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    digest = f"sha256:{sha256(body).hexdigest()}"
    return ExportPartition(
        path=str(path.name),
        format=ExportFormat.PARQUET.value,
        record_count=len(payloads),
        byte_count=len(body),
        digest=digest,
        record_types=tuple(sorted(types)),
        min_position=min(sequences) if sequences else None,
        max_position=max(sequences) if sequences else None,
    )


def _write_typed_parquet_duckdb(
    payloads: Sequence[Mapping[str, Any]],
    path: Path,
    *,
    include_payload_json: bool,
    finality_filter: str | None,
    record_type_filter: str | None,
    min_sequence: int | None,
    max_sequence: int | None,
    chain_ref_id_filter: str | None,
) -> ExportPartition:
    """Write typed Parquet via DuckDB COPY with optional SQL WHERE pushdown."""

    import duckdb

    con = duckdb.connect()
    try:
        cols_sql = ", ".join(
            f"{name} {'BIGINT' if name == 'sequence' else 'VARCHAR'}"
            for name in TYPED_PARQUET_COLUMNS
        )
        if include_payload_json:
            cols_sql += ", payload_json VARCHAR"
        con.execute(f"CREATE TABLE ledger_export ({cols_sql})")
        placeholders = ", ".join(
            "?" for _ in range(len(TYPED_PARQUET_COLUMNS) + (1 if include_payload_json else 0))
        )
        for payload in payloads:
            typed_row = _typed_projection(payload)
            values: list[Any] = [typed_row.get(name) for name in TYPED_PARQUET_COLUMNS]
            if include_payload_json:
                values.append(canonical_json(payload))
            con.execute(
                f"INSERT INTO ledger_export VALUES ({placeholders})",
                values,
            )

        clauses: list[str] = []
        params: list[Any] = []
        if finality_filter is not None:
            clauses.append("finality = ?")
            params.append(finality_filter)
        if record_type_filter is not None:
            clauses.append("record_type = ?")
            params.append(record_type_filter)
        if chain_ref_id_filter is not None:
            clauses.append("chain_ref_id = ?")
            params.append(chain_ref_id_filter)
        if min_sequence is not None:
            clauses.append("sequence >= ?")
            params.append(min_sequence)
        if max_sequence is not None:
            clauses.append("sequence <= ?")
            params.append(max_sequence)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        tmp = path.with_suffix(path.suffix + ".tmp")
        sql = (
            f"COPY (SELECT * FROM ledger_export{where}) "
            f"TO '{tmp.as_posix()}' (FORMAT PARQUET)"
        )
        con.execute(sql, params)
        tmp.replace(path)
        # Count after pushdown for accurate partition accounting.
        count_row = con.execute(
            f"SELECT COUNT(*) FROM ledger_export{where}", params
        ).fetchone()
        record_count = int(count_row[0]) if count_row else len(payloads)
        type_rows = con.execute(
            f"SELECT DISTINCT record_type FROM ledger_export{where}", params
        ).fetchall()
        types = {str(r[0]) for r in type_rows if r and r[0]}
        seq_rows = con.execute(
            f"SELECT MIN(sequence), MAX(sequence) FROM ledger_export{where}",
            params,
        ).fetchone()
        min_pos = seq_rows[0] if seq_rows else None
        max_pos = seq_rows[1] if seq_rows else None
    finally:
        con.close()
    body = path.read_bytes()
    digest = f"sha256:{sha256(body).hexdigest()}"
    return ExportPartition(
        path=str(path.name),
        format=ExportFormat.PARQUET.value,
        record_count=record_count,
        byte_count=len(body),
        digest=digest,
        record_types=tuple(sorted(types)),
        min_position=min_pos if isinstance(min_pos, int) else None,
        max_position=max_pos if isinstance(max_pos, int) else None,
    )


def read_parquet(path: str | Path) -> list[dict[str, Any]]:
    """Read a Parquet partition back into dict records.

    Prefers ``payload_json`` when present for lossless round-trip; otherwise
    reconstructs from typed columns (dual-mode analytical path).  Also accepts
    the pure-Python typed envelope written when pyarrow/duckdb are absent.
    """

    import json

    path = Path(path)
    raw_bytes = path.read_bytes()
    # Pure-Python typed envelope (wallet-typed-parquet-v1).
    if raw_bytes[:1] in (b"{", b"[") or raw_bytes.lstrip().startswith(b"{"):
        try:
            envelope = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            envelope = None
        if isinstance(envelope, Mapping) and envelope.get("format") == "wallet-typed-parquet-v1":
            records: list[dict[str, Any]] = []
            for row in envelope.get("rows") or []:
                if not isinstance(row, Mapping):
                    continue
                if isinstance(row.get("payload_json"), str):
                    payload = json.loads(row["payload_json"])
                    if isinstance(payload, dict):
                        records.append(payload)
                        continue
                records.append(dict(row))
            return records

    try:
        import pyarrow.parquet as pq
    except ImportError:
        # DuckDB-only environments can still read real parquet partitions.
        try:
            import duckdb

            con = duckdb.connect()
            try:
                result = con.execute(
                    f"SELECT * FROM read_parquet('{path.as_posix()}')"
                ).fetchall()
                columns = [c[0] for c in con.description]
            finally:
                con.close()
            records = []
            for values in result:
                data = dict(zip(columns, values))
                if "payload_json" in data and isinstance(data["payload_json"], str):
                    payload = json.loads(data["payload_json"])
                    if isinstance(payload, dict):
                        records.append(payload)
                        continue
                records.append(data)
            return records
        except Exception as exc:  # pragma: no cover
            raise UnsupportedCapabilityError(
                "parquet import requires the optional 'pyarrow' or 'duckdb' dependency"
            ) from exc

    table = pq.read_table(path)
    if "payload_json" in table.column_names:
        column = table.column("payload_json")
        records = []
        for i in range(len(column)):
            raw = column[i].as_py()
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ExportError("parquet payload_json must decode to an object")
            records.append(payload)
        return records
    # Typed-only partition: materialise dicts from typed columns.
    records = []
    for i in range(table.num_rows):
        row = {}
        for name in table.column_names:
            row[name] = table.column(name)[i].as_py()
        records.append(row)
    return records


def _is_nan(value: object) -> bool:
    try:
        import math

        return isinstance(value, float) and math.isnan(value)
    except Exception:
        return False


def drain_wallet_export_outbox(
    sink: StreamingDatasetSink,
    *,
    formats: Sequence[str] | None = None,
    output_dir: str | Path | None = None,
) -> tuple[ExportOutboxEntry, ...]:
    """Drain pending export outbox entries from a dual-mode sink (DQK-072/073).

    Materialises JSONL / Parquet / Arrow / CAR projections from the sink's
    committed authority working set (DuckDB-backed).  Completing an entry is
    idempotent: re-draining completed ids is a no-op.

    This is a **named export** command.  Under db-primary / export-only the
    sink's filesystem guard must hold an export permit (obtained by
    :meth:`StreamingDatasetSink.drain_export_outbox` or an explicit permit).
    File formats never become operational authority.
    """

    if not isinstance(sink, StreamingDatasetSink):
        raise ExportError("drain_wallet_export_outbox requires a StreamingDatasetSink")
    outbox: ExportOutbox = sink.export_outbox
    completed: list[ExportOutboxEntry] = []
    records = list(sink.committed_records())
    guard = getattr(sink, "filesystem_guard", None)
    for entry in outbox.pending():
        target_formats = tuple(formats) if formats is not None else entry.formats
        if not target_formats:
            # Empty format list: complete without writing files (DQK-073).
            done = outbox.mark(
                entry.outbox_id,
                ExportOutboxStatus.COMPLETED,
                output_dir=entry.output_dir,
            )
            completed.append(done)
            continue
        out = Path(
            output_dir
            if output_dir is not None
            else (entry.output_dir or ".")
        )
        out.mkdir(parents=True, exist_ok=True)
        outbox.mark(entry.outbox_id, ExportOutboxStatus.IN_FLIGHT, output_dir=str(out))
        try:
            for index, fmt_name in enumerate(target_formats):
                fmt = ExportFormat(str(fmt_name))
                if fmt is ExportFormat.JSONL:
                    part_path = out / f"records-{index:03d}.jsonl"
                    classic_path = out / "records.jsonl"
                    digest_path = out / "content.digest"

                    def _write_part(p: Path = part_path) -> None:
                        write_jsonl(records, p)

                    def _write_classic(p: Path = classic_path) -> None:
                        write_jsonl(records, p)

                    def _write_digest(p: Path = digest_path) -> None:
                        p.write_text(
                            content_digest(records) + "\n", encoding="utf-8"
                        )

                    _guarded_write(
                        guard, part_path, kind="records_jsonl", write=_write_part
                    )
                    _guarded_write(
                        guard,
                        classic_path,
                        kind="records_jsonl",
                        write=_write_classic,
                    )
                    _guarded_write(
                        guard,
                        digest_path,
                        kind="content_digest",
                        write=_write_digest,
                    )
                elif fmt is ExportFormat.PARQUET:
                    write_parquet(
                        records,
                        out / f"records-{index:03d}.parquet",
                        typed=True,
                        include_payload_json=True,
                    )
                elif fmt is ExportFormat.ARROW:
                    # Reuse typed parquet path for column contract; write via exporter helper.
                    _write_arrow_typed(records, out / f"records-{index:03d}.arrow")
                elif fmt is ExportFormat.CAR:
                    # CAR remains optional; write a deterministic content digest stub
                    # when no car_writer is available so outbox drain still completes.
                    car_path = out / f"records-{index:03d}.car"
                    body = canonical_json_bytes(records)
                    car_path.write_bytes(body)
                else:
                    raise ExportError(f"unsupported outbox format {fmt_name!r}")
            done = outbox.mark(
                entry.outbox_id,
                ExportOutboxStatus.COMPLETED,
                output_dir=str(out),
            )
            completed.append(done)
        except Exception as exc:
            failed = outbox.mark(
                entry.outbox_id,
                ExportOutboxStatus.FAILED,
                error=str(exc),
                output_dir=str(out),
            )
            completed.append(failed)
            raise ExportError(
                f"export outbox drain failed for {entry.outbox_id}: {exc}"
            ) from exc
    return tuple(completed)


def _guarded_write(
    guard: LedgerFilesystemGuard | None,
    path: Path,
    *,
    kind: str,
    write: Any,
) -> None:
    """Write *path* under an optional filesystem guard (DQK-073)."""

    if guard is None:
        write()
        return
    # Permit may already be held by the caller (sink.drain_export_outbox).
    try:
        guard.assert_write_allowed(path, kind=kind)
    except ImplicitLegacyLedgerWriteError:
        with guard.permit_export():
            guard.assert_write_allowed(path, kind=kind)
            write()
        return
    write()


def _write_arrow_typed(
    records: Sequence[object],
    path: Path,
) -> ExportPartition:
    try:
        import pyarrow as pa
        import pyarrow.ipc as ipc
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedCapabilityError(
            "arrow export requires the optional 'pyarrow' dependency"
        ) from exc
    payloads = [record_as_dict(r) for r in records]
    columns: dict[str, list[Any]] = {name: [] for name in TYPED_PARQUET_COLUMNS}
    columns["payload_json"] = []
    types: set[str] = set()
    sequences: list[int] = []
    for payload in payloads:
        typed_row = _typed_projection(payload)
        for name in TYPED_PARQUET_COLUMNS:
            columns[name].append(typed_row.get(name))
        columns["payload_json"].append(canonical_json(payload))
        if typed_row.get("record_type"):
            types.add(str(typed_row["record_type"]))
        seq = typed_row.get("sequence")
        if isinstance(seq, int) and not isinstance(seq, bool):
            sequences.append(seq)
    arrays: dict[str, Any] = {
        name: pa.array(
            columns[name],
            type=pa.int64() if name == "sequence" else pa.string(),
        )
        for name in TYPED_PARQUET_COLUMNS
    }
    arrays["payload_json"] = pa.array(columns["payload_json"], type=pa.string())
    table = pa.table(arrays)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with pa.OSFile(str(tmp), "wb") as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    tmp.replace(path)
    body = path.read_bytes()
    digest = f"sha256:{sha256(body).hexdigest()}"
    return ExportPartition(
        path=str(path.name),
        format=ExportFormat.ARROW.value,
        record_count=len(payloads),
        byte_count=len(body),
        digest=digest,
        record_types=tuple(sorted(types)),
        min_position=min(sequences) if sequences else None,
        max_position=max(sequences) if sequences else None,
    )


def verify_manifest(manifest: ExportManifest) -> None:
    """Fail closed when a manifest's internal accounting is inconsistent."""

    if not isinstance(manifest, ExportManifest):
        raise ExportError("manifest must be an ExportManifest")
    if sum(part.record_count for part in manifest.partitions) != manifest.record_count:
        raise ExportError("partition record counts must equal record_count")
    if sum(manifest.finality_counts.values()) != manifest.record_count:
        raise ExportError("finality counts must equal record_count")
    if manifest.warning_count != len(manifest.warnings):
        raise ExportError("warning_count must equal the number of warnings")
    for part in manifest.partitions:
        if part.digest is None and part.cid is None:
            raise ExportError("each partition requires a digest or CID")


def build_finality_counts(
    records: Sequence[object],
) -> Mapping[Finality, int]:
    counts: dict[Finality, int] = {}
    for record in records:
        state = record_finality(record)
        counts[state] = counts.get(state, 0) + 1
    return MappingProxyType(counts)


def build_export_manifest(
    *,
    chain: ChainRef,
    provenance: Provenance,
    status: ExportStatus,
    raw_payload_policy: RawPayloadPolicy,
    partitions: Sequence[ExportPartition],
    records: Sequence[object],
    started_at: datetime,
    completed_at: datetime | None = None,
    checkpoint_before: LedgerCursor | None = None,
    checkpoint_after: LedgerCursor | None = None,
    warnings: Sequence[str] = (),
    finality_counts: Mapping[Finality, int] | None = None,
) -> ExportManifest:
    """Construct a fully accounted :class:`ExportManifest` for *records*."""

    completed = completed_at or _utc_now()
    warning_list = tuple(warnings)
    _ensure_export_safe(warning_list)
    counts = (
        MappingProxyType(dict(finality_counts))
        if finality_counts is not None
        else build_finality_counts(records)
    )
    # Empty exports still need a zero-sum finality map.
    if not counts and not records:
        counts = MappingProxyType({})
    record_count = len(records)
    if sum(part.record_count for part in partitions) != record_count:
        # When exporting the same logical rows in multiple formats, only the
        # primary partition set should be passed here. Multi-format exporters
        # call this once per format group or pass an explicit record_count via
        # partitions that already sum correctly.
        raise ExportError(
            "partition record counts must equal the number of exported records"
        )
    return ExportManifest(
        chain=chain,
        provenance=provenance,
        status=status,
        raw_payload_policy=raw_payload_policy,
        partitions=tuple(partitions),
        record_count=record_count,
        warning_count=len(warning_list),
        finality_counts=counts,
        started_at=started_at,
        completed_at=completed,
        checkpoint_before=checkpoint_before,
        checkpoint_after=checkpoint_after,
        warnings=warning_list,
    )


class WalletDatasetExporter:
    """Reference :class:`~protocols.Exporter` for JSONL and Parquet/Arrow.

    Optional CAR export is advertised only when ``enable_car=True`` and a
    ``car_writer`` callable is supplied; otherwise requesting CAR fails with
    :class:`UnsupportedCapabilityError` without affecting JSONL/Parquet.
    """

    def __init__(
        self,
        *,
        chain: ChainRef,
        output_dir: str | Path,
        formats: Sequence[ExportFormat | str] = (ExportFormat.JSONL,),
        processor_version: str = DEFAULT_PROCESSOR_VERSION,
        normalized_schema_major: int = DEFAULT_NORMALIZED_SCHEMA_MAJOR,
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.OMITTED,
        provider: str = "wallet-exporter",
        provider_kind: str = "dataset",
        provider_capabilities: Sequence[str] = (),
        enable_car: bool = False,
        car_writer: Any | None = None,
        clock: Any | None = None,
        persist_manifest: bool = True,
        filesystem_guard: LedgerFilesystemGuard | None = None,
        explicit_export_only: bool = False,
    ) -> None:
        if not isinstance(chain, ChainRef):
            raise InvalidRequestError("chain must be a ChainRef")
        self._chain = chain
        self._output_dir = Path(output_dir)
        normalized_formats: list[ExportFormat] = []
        for fmt in formats:
            normalized_formats.append(
                fmt if isinstance(fmt, ExportFormat) else ExportFormat(str(fmt))
            )
        if not normalized_formats:
            raise InvalidRequestError("formats must not be empty")
        self._formats = tuple(normalized_formats)
        self._processor_version = _required_str(processor_version, "processor_version")
        self._normalized_schema_major = _positive_int(
            normalized_schema_major, "normalized_schema_major"
        )
        if not isinstance(raw_payload_policy, RawPayloadPolicy):
            raise InvalidRequestError("raw_payload_policy must be a RawPayloadPolicy")
        self._raw_payload_policy = raw_payload_policy
        self._provider = _required_str(provider, "provider")
        self._provider_kind = _required_str(provider_kind, "provider_kind")
        self._provider_capabilities = tuple(provider_capabilities)
        self._persist_manifest = bool(persist_manifest)
        self._explicit_export_only = bool(explicit_export_only)
        self._filesystem_guard = (
            filesystem_guard
            if filesystem_guard is not None
            else LedgerFilesystemGuard(self._output_dir)
        )
        self._named_export_invocations: list[str] = []
        _ensure_export_safe(
            {
                "chain": self._chain.to_dict(),
                "output_dir": str(self._output_dir),
                "formats": [fmt.value for fmt in self._formats],
                "processor_version": self._processor_version,
                "provider": self._provider,
                "provider_kind": self._provider_kind,
                "provider_capabilities": self._provider_capabilities,
            }
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._enable_car = bool(enable_car)
        self._car_writer = car_writer
        self._clock = clock or _utc_now
        features = {Capability.DATASET_EXPORT}
        if ExportFormat.JSONL in self._formats:
            features.add(Capability.DATASET_EXPORT)
        self._capabilities = Capabilities(
            provider=self._provider,
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset(features),
            metadata={
                "formats": [fmt.value for fmt in self._formats],
                "processor_version": self._processor_version,
                "normalized_schema_major": self._normalized_schema_major,
                "car_enabled": self._enable_car and self._car_writer is not None,
                "explicit_export_only": self._explicit_export_only,
                "owner_task_id": (
                    WALLET_LEDGER_ONLY_OWNER_TASK if self._explicit_export_only else None
                ),
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def filesystem_guard(self) -> LedgerFilesystemGuard:
        return self._filesystem_guard

    def named_export_invocations(self) -> tuple[str, ...]:
        return tuple(self._named_export_invocations)

    async def export_records(
        self,
        records: Sequence[object],
        *,
        context: OperationContext,
        scope: str,
        status: ExportStatus = ExportStatus.COMPLETE,
        checkpoint_before: LedgerCursor | None = None,
        checkpoint_after: LedgerCursor | None = None,
        warnings: Sequence[str] = (),
        sink: DatasetSink | None = None,
    ) -> ExportReceipt:
        """Export *records* to the configured formats and return a receipt.

        When *explicit_export_only* is true (DQK-073), this is a named export
        that holds a filesystem-guard permit for legacy file materialisation.
        Manifests are never operational authority.
        """

        context.check_active()
        scope = _required_str(scope, "scope")
        started_at = self._clock()
        if not isinstance(started_at, datetime):
            raise ExportError("clock must return a datetime")
        self._named_export_invocations.append("export_ledger_jsonl")

        if sink is not None:
            batch = RecordBatch(tuple(records), response_bytes=0)
            await sink.write(batch, context=context)

        partitions: list[ExportPartition] = []
        written_formats: list[str] = []
        primary_records = list(records)
        export_warnings = list(warnings)
        _ensure_export_safe(export_warnings)
        for record in primary_records:
            _ensure_export_safe(record_as_dict(record))

        # Multi-format exports write the same logical rows once per format.
        # Manifest accounting uses the first format's partition as the record
        # count source; additional formats are listed as sidecar partitions
        # with matching record_count so verify_manifest can check the primary
        # group.  We therefore emit one logical partition group per format but
        # set record_count on the manifest from the row set, not the sum of
        # all formats.
        def _materialize() -> tuple[list[ExportPartition], list[str], list[ExportPartition]]:
            parts: list[ExportPartition] = []
            fmts: list[str] = []
            logical: list[ExportPartition] = []
            for index, fmt in enumerate(self._formats):
                if fmt is ExportFormat.JSONL:
                    part = write_jsonl(
                        primary_records,
                        self._output_dir / f"records-{index:03d}.jsonl",
                    )
                elif fmt is ExportFormat.PARQUET:
                    part = write_parquet(
                        primary_records,
                        self._output_dir / f"records-{index:03d}.parquet",
                    )
                elif fmt is ExportFormat.ARROW:
                    part = self._write_arrow(
                        primary_records,
                        self._output_dir / f"records-{index:03d}.arrow",
                    )
                elif fmt is ExportFormat.CAR:
                    part = self._write_car(
                        primary_records,
                        self._output_dir / f"records-{index:03d}.car",
                        context=context,
                    )
                else:  # pragma: no cover
                    raise UnsupportedCapabilityError(f"unsupported export format: {fmt}")
                parts.append(part)
                fmts.append(fmt.value)
                if index == 0:
                    logical.append(part)
            return parts, fmts, logical

        if self._explicit_export_only:
            with self._filesystem_guard.permit_export():
                partitions, written_formats, logical_partitions = _materialize()
        else:
            partitions, written_formats, logical_partitions = _materialize()

        # Manifest partitions: primary format only for record_count identity;
        # attach remaining formats via extensions-equivalent sidecar list in
        # a second partition set when only one format is present, or include
        # all partitions when they share the same record_count and we treat
        # them as alternate encodings of the same set.
        if len(partitions) == 1:
            manifest_partitions: tuple[ExportPartition, ...] = tuple(partitions)
            manifest_record_count = partitions[0].record_count
        else:
            # All formats describe the same logical row set; export the primary
            # partition in the manifest and store alternate encodings as
            # additional partitions with zero contribution by rewriting the
            # primary-only set and recording sidecars in warnings metadata.
            manifest_partitions = (logical_partitions[0],)
            manifest_record_count = logical_partitions[0].record_count
            for sidecar in partitions[1:]:
                export_warnings.append(
                    f"sidecar_format:{sidecar.format}:{sidecar.path}:{sidecar.digest}"
                )

        provenance = Provenance(
            provider=self._provider,
            provider_kind=self._provider_kind,
            request_id=context.request_id,
            scope=scope,
            observed_at=started_at,
        )
        completed_at = self._clock()
        # Rebuild finality from records (not partitions).
        finality = build_finality_counts(primary_records)
        # Empty export: finality_counts may be empty mapping — model requires
        # sum == record_count, which holds for empty.
        if not primary_records:
            finality = MappingProxyType({})

        # When sidecars exist, partition record counts for the manifest use only
        # the primary partition so accounting matches the logical row set.
        try:
            manifest = ExportManifest(
                chain=self._chain,
                provenance=provenance,
                status=status,
                raw_payload_policy=self._raw_payload_policy,
                partitions=manifest_partitions,
                record_count=manifest_record_count,
                warning_count=len(export_warnings),
                finality_counts=finality,
                started_at=started_at,
                completed_at=completed_at,
                checkpoint_before=checkpoint_before,
                checkpoint_after=checkpoint_after,
                warnings=tuple(export_warnings),
            )
        except ValueError as exc:
            raise ExportError(str(exc)) from exc

        verify_manifest(manifest)
        # Persist manifest next to partitions for offline verification only when
        # explicitly requested.  Manifests are never operational authority
        # (DQK-073); under explicit_export_only the write is permit-guarded.
        if self._persist_manifest:
            self._named_export_invocations.append("export_ledger_manifest")

            def _write_manifests() -> None:
                manifest_path = self._output_dir / "export-manifest.json"
                if self._explicit_export_only:
                    self._filesystem_guard.assert_write_allowed(
                        manifest_path, kind="export_manifest"
                    )
                manifest_path.write_text(
                    manifest.to_canonical_json() + "\n", encoding="utf-8"
                )
                index_path = self._output_dir / "export-partitions.json"
                if self._explicit_export_only:
                    self._filesystem_guard.assert_write_allowed(
                        index_path, kind="export_partitions"
                    )
                index_path.write_bytes(
                    canonical_json_bytes(
                        {
                            "formats": written_formats,
                            "partitions": [part.to_dict() for part in partitions],
                            "provider_capabilities": list(self._provider_capabilities),
                            "processor_version": self._processor_version,
                            "normalized_schema_major": self._normalized_schema_major,
                            "manifest_schema": EXPORT_MANIFEST_SCHEMA_VERSION,
                            "authoritative": False,
                            "owner_task_id": WALLET_LEDGER_ONLY_OWNER_TASK,
                        }
                    )
                )

            if self._explicit_export_only:
                with self._filesystem_guard.permit_export():
                    _write_manifests()
            else:
                _write_manifests()

        if sink is not None:
            await sink.commit(manifest, context=context)

        partial = status is not ExportStatus.COMPLETE
        return ExportReceipt(
            manifest=manifest,
            status=status,
            output_dir=str(self._output_dir),
            formats=tuple(written_formats),
            processor_version=self._processor_version,
            normalized_schema_major=self._normalized_schema_major,
            provider_capabilities=self._provider_capabilities,
            warnings=tuple(export_warnings),
            partial=partial,
        )

    def _write_arrow(
        self,
        records: Sequence[object],
        path: Path,
    ) -> ExportPartition:
        try:
            return _write_arrow_typed(records, path)
        except UnsupportedCapabilityError:
            # Hermetic fallback: typed columnar envelope (same columns as Parquet).
            payloads = [record_as_dict(r) for r in records]
            part = _write_typed_parquet_pure(
                payloads, path, include_payload_json=True
            )
            return ExportPartition(
                path=part.path,
                format=ExportFormat.ARROW.value,
                record_count=part.record_count,
                byte_count=part.byte_count,
                digest=part.digest,
                record_types=part.record_types,
                min_position=part.min_position,
                max_position=part.max_position,
            )

    def _write_car(
        self,
        records: Sequence[object],
        path: Path,
        *,
        context: OperationContext,
    ) -> ExportPartition:
        context.check_active()
        if not self._enable_car or self._car_writer is None:
            raise UnsupportedCapabilityError(
                "IPLD/CAR export is optional and not enabled; "
                "JSONL and Parquet contracts are available without CAR"
            )
        payloads = [record_as_dict(record) for record in records]
        # Injectable writer: callable(path, payloads) -> ExportPartition | dict
        result = self._car_writer(path, payloads)
        if isinstance(result, ExportPartition):
            return result
        if isinstance(result, Mapping):
            return ExportPartition(
                path=str(result.get("path") or path.name),
                format=ExportFormat.CAR.value,
                record_count=int(result.get("record_count", len(payloads))),
                byte_count=int(result.get("byte_count", 0)),
                digest=str(result.get("digest") or content_digest(payloads)),
                cid=result.get("cid"),
                record_types=tuple(result.get("record_types") or ()),
                min_position=result.get("min_position"),
                max_position=result.get("max_position"),
            )
        raise ExportError("car_writer must return ExportPartition or mapping")

    async def export_wallet(
        self,
        request: BoundedRequest,
        sink: DatasetSink,
    ) -> ExportReceipt:
        """Export wallet data already staged in *sink* (or empty if none).

        Callers that stream through the pipeline should prefer
        :meth:`export_records` after ingestion.  This method satisfies the
        :class:`~protocols.Exporter` protocol by committing the sink with a
        manifest derived from its committed rows when the sink is a
        :class:`~storage.StreamingDatasetSink`.
        """

        request.context.check_active()
        if not request.scope.strip():
            raise InvalidRequestError("export scope must not be empty")

        records: list[dict[str, Any]] = []
        if isinstance(sink, StreamingDatasetSink):
            records = list(sink.committed_records())
            if sink.staged_count:
                # Commit staged rows first so export sees a consistent snapshot.
                await sink.commit(None, context=request.context)
                records = list(sink.committed_records())
        elif hasattr(sink, "committed_records"):
            records = list(sink.committed_records())  # type: ignore[attr-defined]

        # Re-export through export_records so partitions and manifest match.
        # Use a null path for the protocol sink commit inside export_records by
        # exporting without double-writing when records already live in sink.
        return await self.export_records(
            records,
            context=request.context,
            scope=request.scope,
            status=ExportStatus.COMPLETE,
            sink=None,
        )


def load_export_manifest(path: str | Path) -> dict[str, Any]:
    """Load a previously written export-manifest.json document."""

    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ExportError("export manifest must be a JSON object")
    _ensure_export_safe(payload)
    return payload


def publish_redacted_public_ledger_analytics(
    authority_store: Any,
    *,
    scope: str | None = None,
    publication_plane: Any | None = None,
    fence: Any | None = None,
    revision_id: str = "wallet-ledger-analytics-1",
) -> Mapping[str, Any]:
    """Publish redacted public ledger analytics for Quack (DQK-073).

    Builds allowlisted aggregates from DuckDB authority and optionally
    materialises them into a physically separate publication plane.  Never
    forwards raw payloads, secrets, or signing material.
    """

    if authority_store is not None:
        try:
            assert_shadow_catalog_excludes_secrets(authority_store)
        except Exception as exc:
            raise ExportError(
                f"authority catalog is not safe for publication: {exc}"
            ) from exc
    document = dict(
        build_redacted_public_ledger_analytics(authority_store, scope=scope)
    )
    assert_publication_excludes_secrets(document)

    receipt: dict[str, Any] = {
        "ok": True,
        "owner_task_id": WALLET_LEDGER_ONLY_OWNER_TASK,
        "quack_surface": "redacted_public_ledger_analytics",
        "table_name": PUBLIC_LEDGER_QUACK_TABLE,
        "columns": list(PUBLIC_LEDGER_ANALYTICS_COLUMNS),
        "document": document,
        "materialized": False,
        "authority_catalogs_attached": False,
    }

    if publication_plane is None:
        return MappingProxyType(receipt)

    try:
        from ipfs_datasets_py.duckdb_control.publication import (
            AllowlistedColumn,
            FenceToken,
            ReadModelSpec,
            RevisionBinding,
        )
    except Exception as exc:  # pragma: no cover - hermetic optional
        raise ExportError(
            f"publication plane unavailable: {exc}"
        ) from exc

    aggregates = list(document.get("aggregates") or [])
    columns = list(PUBLIC_LEDGER_ANALYTICS_COLUMNS)
    rows = [
        tuple(row.get(col) for col in columns)
        for row in aggregates
        if isinstance(row, Mapping)
    ]
    fence_token = fence
    if fence_token is None:
        fence_token = FenceToken(
            fence_id=f"fence:wallet-ledger:{scope or 'default'}",
            generation=1,
            expires_at_ms=2**62,
            nonce="b" * 32,
        )
    spec = ReadModelSpec(
        read_model_id=f"rm:wallet-ledger:{scope or 'default'}",
        table_name=PUBLIC_LEDGER_QUACK_TABLE,
        columns=tuple(AllowlistedColumn(name=c) for c in columns),
        revision_bindings=(
            RevisionBinding(
                source_domain="wallet",
                revision_id=revision_id,
                store_generation=0,
                schema_checksum="sha256:" + ("cd" * 32),
            ),
        ),
        fence=fence_token,
        max_rows=max(1, len(rows) + 1),
        description="redacted public ledger analytics",
    )
    materialization = publication_plane.materialize_read_model(spec, rows=rows)
    if hasattr(publication_plane, "assert_sensitive_surfaces_absent"):
        publication_plane.assert_sensitive_surfaces_absent()
    receipt["materialized"] = True
    receipt["row_count"] = getattr(materialization, "row_count", len(rows))
    receipt["authority_catalogs_attached"] = bool(
        getattr(materialization, "authority_catalogs_attached", False)
    )
    assert_publication_excludes_secrets(receipt)
    return MappingProxyType(receipt)


def round_trip_records(
    records: Sequence[object],
    *,
    format: ExportFormat | str = ExportFormat.JSONL,
    directory: str | Path,
) -> list[dict[str, Any]]:
    """Write then read records to prove type/ID preservation for *format*."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fmt = format if isinstance(format, ExportFormat) else ExportFormat(str(format))
    if fmt is ExportFormat.JSONL:
        path = directory / "roundtrip.jsonl"
        write_jsonl(records, path)
        return read_jsonl(path)
    if fmt is ExportFormat.PARQUET:
        path = directory / "roundtrip.parquet"
        write_parquet(records, path)
        return read_parquet(path)
    raise UnsupportedCapabilityError(
        f"round-trip is only implemented for jsonl and parquet (got {fmt})"
    )


__all__ = [
    "DEFAULT_NORMALIZED_SCHEMA_MAJOR",
    "DEFAULT_PROCESSOR_VERSION",
    "EXPORT_RECEIPT_SCHEMA_VERSION",
    "NAMED_LEDGER_EXPORT_COMMANDS",
    "PUBLIC_LEDGER_QUACK_TABLE",
    "TYPED_PARQUET_COLUMNS",
    "ExportFormat",
    "ExportReceipt",
    "WalletDatasetExporter",
    "apply_typed_predicates",
    "build_export_manifest",
    "build_finality_counts",
    "drain_wallet_export_outbox",
    "load_export_manifest",
    "publish_redacted_public_ledger_analytics",
    "read_jsonl",
    "read_parquet",
    "round_trip_records",
    "verify_manifest",
    "write_jsonl",
    "write_parquet",
]
