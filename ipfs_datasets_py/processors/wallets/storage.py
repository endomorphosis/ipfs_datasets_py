"""Transactional dataset sinks and content-addressed raw payload storage.

Streaming ingestion never accumulates whole-history state in the sink: each
:class:`~protocols.RecordBatch` is staged independently, deduplicated by
stable ``record_id``, and only becomes durable after :meth:`DatasetSink.commit`.
Partial or cancelled runs leave staged data aborted and do not invent a
successful sink commit for checkpoint CAS.

Importing this module performs no network I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from .canonical import canonical_json_bytes, content_digest
from .errors import DatasetSinkError, InvalidRequestError
from .models import (
    ExportManifest,
    ExportPartition,
    Finality,
    LedgerRecord,
    RawPayloadPolicy,
    RawPayloadRef,
)
from .protocols import OperationContext, RecordBatch


SINK_RECEIPT_SCHEMA_VERSION = "wallet-sink-receipt-v1"
RAW_PAYLOAD_SCHEMA_VERSION = "wallet-raw-payload-v1"


def _required_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    return value


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def record_identity(record: object) -> str:
    """Return the stable identity used for sink-level deduplication."""

    if isinstance(record, LedgerRecord):
        return record.record_id
    if isinstance(record, Mapping):
        record_id = record.get("record_id")
        if isinstance(record_id, str) and record_id.strip():
            return record_id
    record_id_attr = getattr(record, "record_id", None)
    if isinstance(record_id_attr, str) and record_id_attr.strip():
        return record_id_attr
    # Fallback: content digest of a dict projection.  Tests and pure fixtures
    # should always supply record_id; this path only keeps the sink fail-safe.
    if hasattr(record, "to_dict") and callable(record.to_dict):
        return content_digest(record.to_dict())
    return content_digest({"repr": repr(record)})


def record_as_dict(record: object) -> dict[str, Any]:
    """Project a normalized record into a JSON-serializable mapping."""

    if isinstance(record, LedgerRecord):
        return record.to_dict()
    if hasattr(record, "to_dict") and callable(record.to_dict):
        value = record.to_dict()
        if isinstance(value, Mapping):
            return dict(value)
    if isinstance(record, Mapping):
        return dict(record)
    raise DatasetSinkError(
        f"record of type {type(record).__name__} is not serializable"
    )


def record_finality(record: object) -> Finality:
    """Extract a :class:`Finality` from a record or mapping."""

    if isinstance(record, LedgerRecord):
        return record.finality
    if isinstance(record, Mapping):
        raw = record.get("finality")
        if isinstance(raw, Finality):
            return raw
        if isinstance(raw, str):
            return Finality(raw)
    attr = getattr(record, "finality", None)
    if isinstance(attr, Finality):
        return attr
    if isinstance(attr, str):
        return Finality(attr)
    return Finality.UNKNOWN


def record_sequence(record: object) -> int | None:
    """Best-effort ledger sequence for min/max position accounting."""

    if isinstance(record, LedgerRecord):
        return record.ledger_position.sequence
    position = None
    if isinstance(record, Mapping):
        position = record.get("ledger_position")
    else:
        position = getattr(record, "ledger_position", None)
    if isinstance(position, Mapping):
        sequence = position.get("sequence")
        return sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None
    sequence = getattr(position, "sequence", None)
    if isinstance(sequence, int) and not isinstance(sequence, bool):
        return sequence
    return None


@dataclass(frozen=True, slots=True)
class BatchWriteReceipt:
    """Accounting for one staged :class:`~protocols.RecordBatch` write."""

    write_id: str
    accepted_count: int
    duplicate_count: int
    out_of_order_count: int
    byte_count: int
    record_ids: tuple[str, ...]
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "write_id", _required_str(self.write_id, "write_id"))
        _non_negative_int(self.accepted_count, "accepted_count")
        _non_negative_int(self.duplicate_count, "duplicate_count")
        _non_negative_int(self.out_of_order_count, "out_of_order_count")
        _non_negative_int(self.byte_count, "byte_count")
        object.__setattr__(self, "record_ids", tuple(self.record_ids))
        object.__setattr__(
            self, "content_digest", _required_str(self.content_digest, "content_digest")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "write_id": self.write_id,
            "accepted_count": self.accepted_count,
            "duplicate_count": self.duplicate_count,
            "out_of_order_count": self.out_of_order_count,
            "byte_count": self.byte_count,
            "record_ids": list(self.record_ids),
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class SinkCommitReceipt:
    """Proof that a dataset sink committed staged data (pipeline-facing)."""

    commit_id: str
    scope: str
    record_count: int
    content_digest: str
    manifest: ExportManifest | None = None
    partitions: tuple[ExportPartition, ...] = ()
    schema_version: str = field(default=SINK_RECEIPT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "commit_id", _required_str(self.commit_id, "commit_id"))
        object.__setattr__(self, "scope", _required_str(self.scope, "scope"))
        _non_negative_int(self.record_count, "record_count")
        object.__setattr__(
            self, "content_digest", _required_str(self.content_digest, "content_digest")
        )
        object.__setattr__(self, "partitions", tuple(self.partitions))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "commit_id": self.commit_id,
            "scope": self.scope,
            "record_count": self.record_count,
            "content_digest": self.content_digest,
            "partitions": [part.to_dict() for part in self.partitions],
        }
        if self.manifest is not None:
            result["manifest_id"] = self.manifest.manifest_id
        return result


@dataclass(frozen=True, slots=True)
class StoredRawPayload:
    """One content-addressed raw provider payload."""

    digest: str
    body: bytes = field(repr=False)
    media_type: str = "application/json"
    cid: str | None = None
    schema_version: str = field(default=RAW_PAYLOAD_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", _required_str(self.digest, "digest"))
        if not isinstance(self.body, (bytes, bytearray)):
            raise InvalidRequestError("raw payload body must be bytes")
        object.__setattr__(self, "body", bytes(self.body))
        object.__setattr__(
            self, "media_type", _required_str(self.media_type, "media_type")
        )
        if self.cid is not None:
            object.__setattr__(self, "cid", _required_str(self.cid, "cid"))

    @property
    def byte_length(self) -> int:
        return len(self.body)

    def to_ref(self) -> RawPayloadRef:
        return RawPayloadRef(
            digest=self.digest,
            cid=self.cid,
            media_type=self.media_type,
            byte_length=self.byte_length,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "digest": self.digest,
            "media_type": self.media_type,
            "byte_length": self.byte_length,
        }
        if self.cid is not None:
            result["cid"] = self.cid
        return result


def digest_bytes(body: bytes) -> str:
    """Return a tagged SHA-256 digest for raw payload bytes."""

    if not isinstance(body, (bytes, bytearray, memoryview)):
        raise InvalidRequestError("body must be bytes")
    return f"sha256:{sha256(bytes(body)).hexdigest()}"


@runtime_checkable
class RawPayloadStore(Protocol):
    """Content-addressed store for optional lossless provider payloads."""

    async def put(
        self,
        body: bytes,
        *,
        media_type: str = "application/json",
        cid: str | None = None,
        context: OperationContext,
    ) -> StoredRawPayload:
        """Store *body* and return its digest reference."""

        ...

    async def get(
        self,
        digest: str,
        *,
        context: OperationContext,
    ) -> StoredRawPayload | None:
        """Load a previously stored payload by digest."""

        ...


class InMemoryRawPayloadStore:
    """Process-local raw payload store; suitable for tests and single-process runs."""

    def __init__(self) -> None:
        self._entries: dict[str, StoredRawPayload] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def digests(self) -> frozenset[str]:
        return frozenset(self._entries)

    async def put(
        self,
        body: bytes,
        *,
        media_type: str = "application/json",
        cid: str | None = None,
        context: OperationContext,
    ) -> StoredRawPayload:
        context.check_active()
        if not isinstance(body, (bytes, bytearray)):
            raise InvalidRequestError("body must be bytes")
        payload = StoredRawPayload(
            digest=digest_bytes(body),
            body=bytes(body),
            media_type=media_type,
            cid=cid,
        )
        existing = self._entries.get(payload.digest)
        if existing is not None and existing.body != payload.body:
            raise DatasetSinkError(
                f"raw payload digest collision for {payload.digest}"
            )
        self._entries[payload.digest] = payload
        return payload

    async def get(
        self,
        digest: str,
        *,
        context: OperationContext,
    ) -> StoredRawPayload | None:
        context.check_active()
        _required_str(digest, "digest")
        return self._entries.get(digest)


class DirectoryRawPayloadStore:
    """Filesystem-backed raw payload store keyed by digest filename."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str) -> Path:
        # Digest is "sha256:<hex>"; keep the algorithm prefix out of the name.
        safe = digest.replace(":", "_")
        return self._root / f"{safe}.bin"

    async def put(
        self,
        body: bytes,
        *,
        media_type: str = "application/json",
        cid: str | None = None,
        context: OperationContext,
    ) -> StoredRawPayload:
        context.check_active()
        payload = StoredRawPayload(
            digest=digest_bytes(body),
            body=bytes(body),
            media_type=media_type,
            cid=cid,
        )
        path = self._path_for(payload.digest)
        meta_path = path.with_suffix(".meta.json")
        if path.exists():
            if path.read_bytes() != payload.body:
                raise DatasetSinkError(
                    f"raw payload digest collision for {payload.digest}"
                )
            return payload
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(payload.body)
        tmp.replace(path)
        meta_path.write_bytes(canonical_json_bytes(payload.to_dict()))
        return payload

    async def get(
        self,
        digest: str,
        *,
        context: OperationContext,
    ) -> StoredRawPayload | None:
        context.check_active()
        _required_str(digest, "digest")
        path = self._path_for(digest)
        if not path.exists():
            return None
        body = path.read_bytes()
        media_type = "application/json"
        cid = None
        meta_path = path.with_suffix(".meta.json")
        if meta_path.exists():
            import json

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            media_type = str(meta.get("media_type") or media_type)
            cid = meta.get("cid")
        return StoredRawPayload(digest=digest, body=body, media_type=media_type, cid=cid)


@dataclass
class _StagedRecord:
    record_id: str
    payload: dict[str, Any]
    finality: Finality
    sequence: int | None
    order: int


class StreamingDatasetSink:
    """Reference :class:`~protocols.DatasetSink` with transactional staging.

    Records are staged in memory (optionally flushed to a directory on commit).
    Deduplication is by stable ``record_id`` so duplicate and out-of-order pages
    never produce multiple durable rows.  :meth:`abort` discards the stage and
    must be used on partial/cancelled runs so checkpoints are not advanced.
    """

    def __init__(
        self,
        *,
        scope: str,
        output_dir: str | Path | None = None,
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.OMITTED,
    ) -> None:
        self._scope = _required_str(scope, "scope")
        self._output_dir = Path(output_dir) if output_dir is not None else None
        if self._output_dir is not None:
            self._output_dir.mkdir(parents=True, exist_ok=True)
        if not isinstance(raw_payload_policy, RawPayloadPolicy):
            raise InvalidRequestError("raw_payload_policy must be a RawPayloadPolicy")
        self._raw_payload_policy = raw_payload_policy
        self._seen: set[str] = set()
        self._staged: list[_StagedRecord] = []
        self._committed: list[_StagedRecord] = []
        self._aborted = False
        self._commit_count = 0
        self._write_count = 0
        self._last_sequence: int | None = None
        self._duplicate_total = 0
        self._out_of_order_total = 0
        self._last_commit: SinkCommitReceipt | None = None

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def raw_payload_policy(self) -> RawPayloadPolicy:
        return self._raw_payload_policy

    @property
    def staged_count(self) -> int:
        return len(self._staged)

    @property
    def committed_count(self) -> int:
        return len(self._committed)

    @property
    def duplicate_total(self) -> int:
        return self._duplicate_total

    @property
    def out_of_order_total(self) -> int:
        return self._out_of_order_total

    @property
    def is_aborted(self) -> bool:
        return self._aborted

    @property
    def last_commit(self) -> SinkCommitReceipt | None:
        return self._last_commit

    def seen_record_ids(self) -> frozenset[str]:
        return frozenset(self._seen)

    def staged_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(item.payload for item in self._staged)

    def committed_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(item.payload for item in self._committed)

    def finality_counts(
        self, records: Sequence[_StagedRecord] | None = None
    ) -> Mapping[Finality, int]:
        items = self._committed if records is None else records
        counts: dict[Finality, int] = {}
        for item in items:
            counts[item.finality] = counts.get(item.finality, 0) + 1
        return MappingProxyType(counts)

    def position_bounds(
        self, records: Sequence[_StagedRecord] | None = None
    ) -> tuple[int | None, int | None]:
        items = self._committed if records is None else records
        sequences = [item.sequence for item in items if item.sequence is not None]
        if not sequences:
            return None, None
        return min(sequences), max(sequences)

    async def write(
        self,
        batch: RecordBatch,
        *,
        context: OperationContext,
    ) -> BatchWriteReceipt:
        """Stage one bounded batch, dropping already-seen record identities."""

        context.check_active()
        if self._aborted:
            raise DatasetSinkError("cannot write to an aborted dataset sink")
        if not isinstance(batch, RecordBatch):
            raise DatasetSinkError("batch must be a RecordBatch")
        batch.enforce(context.limits)

        accepted: list[str] = []
        duplicate = 0
        out_of_order = 0
        payloads: list[dict[str, Any]] = []
        for record in batch.records:
            record_id = record_identity(record)
            if record_id in self._seen:
                duplicate += 1
                continue
            sequence = record_sequence(record)
            if (
                sequence is not None
                and self._last_sequence is not None
                and sequence < self._last_sequence
            ):
                out_of_order += 1
            payload = record_as_dict(record)
            payloads.append(payload)
            accepted.append(record_id)
            self._seen.add(record_id)
            self._staged.append(
                _StagedRecord(
                    record_id=record_id,
                    payload=payload,
                    finality=record_finality(record),
                    sequence=sequence,
                    order=len(self._staged) + len(self._committed),
                )
            )
            if sequence is not None:
                if self._last_sequence is None or sequence > self._last_sequence:
                    self._last_sequence = sequence

        self._duplicate_total += duplicate
        self._out_of_order_total += out_of_order
        self._write_count += 1
        encoded = canonical_json_bytes(payloads) if payloads else b"[]"
        write_id = f"write:{uuid4().hex}"
        return BatchWriteReceipt(
            write_id=write_id,
            accepted_count=len(accepted),
            duplicate_count=duplicate,
            out_of_order_count=out_of_order,
            byte_count=len(encoded) + max(0, batch.response_bytes),
            record_ids=tuple(accepted),
            content_digest=content_digest(payloads),
        )

    async def commit(
        self,
        manifest: object,
        *,
        context: OperationContext,
    ) -> SinkCommitReceipt:
        """Commit staged data atomically and return a durable sink receipt.

        *manifest* may be an :class:`ExportManifest` or ``None`` when the
        caller builds the manifest after inspecting the receipt.  Checkpoint
        CAS must only proceed after this receipt is obtained.
        """

        context.check_active()
        if self._aborted:
            raise DatasetSinkError("cannot commit an aborted dataset sink")

        export_manifest: ExportManifest | None = None
        if manifest is not None and not isinstance(manifest, ExportManifest):
            raise DatasetSinkError("manifest must be an ExportManifest or None")
        if isinstance(manifest, ExportManifest):
            export_manifest = manifest

        promoting = list(self._staged)
        self._committed.extend(promoting)
        self._staged.clear()
        self._commit_count += 1
        commit_id = f"commit:{uuid4().hex}"

        partitions: tuple[ExportPartition, ...] = ()
        if export_manifest is not None:
            partitions = export_manifest.partitions
            if export_manifest.record_count != len(self._committed):
                # Allow partial manifests that describe only the newly committed
                # slice when the caller has not yet finalized multi-partition
                # accounting; still require non-negative consistency.
                if export_manifest.record_count > len(self._committed):
                    raise DatasetSinkError(
                        "manifest record_count exceeds committed sink rows"
                    )

        digest = content_digest([item.payload for item in self._committed])
        if self._output_dir is not None:
            self._flush_committed_jsonl(digest)

        receipt = SinkCommitReceipt(
            commit_id=commit_id,
            scope=self._scope,
            record_count=len(self._committed),
            content_digest=digest,
            manifest=export_manifest,
            partitions=partitions,
        )
        self._last_commit = receipt
        return receipt

    def _flush_committed_jsonl(self, digest: str) -> Path:
        assert self._output_dir is not None
        path = self._output_dir / "records.jsonl"
        tmp = path.with_suffix(".jsonl.tmp")
        lines = [
            canonical_json_bytes(item.payload).decode("utf-8")
            for item in self._committed
        ]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(path)
        (self._output_dir / "content.digest").write_text(digest + "\n", encoding="utf-8")
        return path

    async def abort(self, *, context: OperationContext) -> None:
        """Discard uncommitted staged data without inventing a sink commit.

        Abort is a cleanup path and must succeed even when the caller has
        already cancelled the operation; it never advances durable state.
        """

        # Deliberately skip cancellation checks so partial/cancelled runs can
        # always drop staged data without raising OperationCancelledError.
        _ = context
        self._staged.clear()
        self._aborted = True

    def reset_for_resume(self) -> None:
        """Clear abort state so a resumed pipeline can stage further batches.

        Committed rows and the seen-identity set are retained so resume never
        re-emits already durable records.
        """

        self._aborted = False
        self._staged.clear()


def iter_record_dicts(records: Iterable[object]) -> list[dict[str, Any]]:
    """Project an iterable of records to dicts (test/export helper)."""

    return [record_as_dict(record) for record in records]


__all__ = [
    "RAW_PAYLOAD_SCHEMA_VERSION",
    "SINK_RECEIPT_SCHEMA_VERSION",
    "BatchWriteReceipt",
    "DirectoryRawPayloadStore",
    "InMemoryRawPayloadStore",
    "RawPayloadStore",
    "SinkCommitReceipt",
    "StoredRawPayload",
    "StreamingDatasetSink",
    "digest_bytes",
    "iter_record_dicts",
    "record_as_dict",
    "record_finality",
    "record_identity",
    "record_sequence",
]
