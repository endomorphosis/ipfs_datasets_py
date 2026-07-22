"""Reference-based, coalesced, and bounded artifact persistence.

Callers publish immutable :class:`ArtifactSnapshotHandle` objects.  A handle
owns the final serialized bytes and revision identity, so mutation of the
source object after publication cannot change an accepted write.  Admission is
bounded by both job count and exact serialized bytes.  Replace-style summary
writes are coalesced while queued; checkpoint and append jobs are never
silently discarded.

The on-disk manifest/payload spool remains deliberately simple.  A manifest is
installed only after its checksummed payload is durable, allowing an abandoned
write to be replayed safely by the next process.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .modal_autoencoder_checkpoint import (
    MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
    MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION,
    append_delta_segment as append_compact_delta_segment,
    serialize_checkpoint,
    serialize_delta,
)


ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION = "legal-ir-async-artifact-writer-v2"
_READABLE_WRITER_SCHEMA_VERSIONS = frozenset(
    {ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION, "legal-ir-async-artifact-writer-v1"}
)
STATE_DELTA_SCHEMA_VERSION = "legal-ir-autoencoder-state-delta-v1"
DEFAULT_MAX_QUEUE_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_WRITE_CONCURRENCY = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: Mapping[str, Any], *, indent: Optional[int] = None) -> bytes:
    separators = (",", ":") if indent is None else None
    text = json.dumps(
        dict(payload),
        default=str,
        ensure_ascii=True,
        indent=indent,
        sort_keys=True,
        separators=separators,
    )
    return (text + "\n").encode("utf-8")


def _immutable_json(value: Any) -> Any:
    """Freeze metadata without retaining mutable caller-owned containers."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _immutable_json(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(_immutable_json(item) for item in value)
    return value


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


@dataclass
class _TimingMetric:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0
    last: float = 0.0

    def observe(self, seconds: float) -> None:
        value = max(0.0, float(seconds))
        self.count += 1
        self.total += value
        self.maximum = max(self.maximum, value)
        self.last = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "last": self.last,
            "max": self.maximum,
            "total": self.total,
        }


@dataclass(frozen=True)
class ArtifactSnapshotHandle:
    """Immutable, revision-bound bytes accepted by the writer.

    Serialization happens before admission.  Consequently the exact memory
    reservation is known and a later source mutation is unable to race with a
    worker.  ``identity`` binds state snapshots to their source revision token;
    for ordinary JSON/text it is the serialized SHA-256.
    """

    payload: bytes
    revision: int = 0
    identity: str = ""
    created_at: str = field(default_factory=_utc_now)
    serialization_seconds: float = 0.0

    def __post_init__(self) -> None:
        immutable = bytes(self.payload)
        object.__setattr__(self, "payload", immutable)
        if not self.identity:
            object.__setattr__(self, "identity", _sha256(immutable))
        object.__setattr__(self, "revision", int(self.revision))
        object.__setattr__(
            self,
            "serialization_seconds",
            max(0.0, float(self.serialization_seconds)),
        )

    @property
    def byte_size(self) -> int:
        return len(self.payload)

    @classmethod
    def from_bytes(
        cls,
        payload: bytes | bytearray | memoryview,
        *,
        revision: int = 0,
        identity: str = "",
        serialization_seconds: float = 0.0,
    ) -> "ArtifactSnapshotHandle":
        return cls(
            bytes(payload),
            revision=revision,
            identity=identity,
            serialization_seconds=serialization_seconds,
        )


# Explicit alias used by callers that want to emphasize state lineage.
RevisionBoundArtifactSnapshot = ArtifactSnapshotHandle


@dataclass(frozen=True)
class ArtifactFsyncPolicy:
    """Durability policy for worker writes."""

    data: bool = True
    directory: bool = True
    manifest: bool = True

    @classmethod
    def disabled(cls) -> "ArtifactFsyncPolicy":
        return cls(data=False, directory=False, manifest=False)

    def to_dict(self) -> Dict[str, bool]:
        return {
            "data": bool(self.data),
            "directory": bool(self.directory),
            "manifest": bool(self.manifest),
        }


@dataclass(frozen=True)
class ArtifactWriteReceipt:
    job_id: str
    kind: str
    path: str
    checksum: str
    bytes_written: int
    created_at: str
    completed_at: str
    manifest_path: str
    replayed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bytes_written": int(self.bytes_written),
            "checksum": self.checksum,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
            "job_id": self.job_id,
            "kind": self.kind,
            "manifest_path": self.manifest_path,
            "metadata": _plain_json(self.metadata),
            "path": self.path,
            "replayed": bool(self.replayed),
            "schema_version": ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
        }


class AsyncArtifactBackpressureTimeout(TimeoutError):
    """Raised when byte or count admission cannot complete before timeout."""


class AsyncArtifactWriteError(RuntimeError):
    """Raised when an accepted artifact write fails."""


class ConcurrentArtifactMutationError(AsyncArtifactWriteError):
    """Raised when a mutable state changes while its snapshot is serialized."""


class ArtifactWriteFuture:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._event = threading.Event()
        self._receipt: Optional[ArtifactWriteReceipt] = None
        self._error: Optional[BaseException] = None

    def set_result(self, receipt: ArtifactWriteReceipt) -> None:
        if not self._event.is_set():
            self._receipt = receipt
            self._event.set()

    def set_exception(self, error: BaseException) -> None:
        if not self._event.is_set():
            self._error = error
            self._event.set()

    def done(self) -> bool:
        return self._event.is_set()

    def result(self, timeout: Optional[float] = None) -> ArtifactWriteReceipt:
        if not self._event.wait(timeout):
            raise TimeoutError(f"artifact write {self.job_id} did not finish")
        if self._error is not None:
            raise self._error
        assert self._receipt is not None
        return self._receipt


@dataclass
class _ArtifactJob:
    job_id: str
    kind: str
    path: Path
    snapshot: ArtifactSnapshotHandle
    created_at: str
    append_jsonl: bool = False
    append_state_delta: bool = False
    dedupe_keys: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    future: Optional[ArtifactWriteFuture] = None
    coalesce_key: str = ""
    required: bool = False
    followers: List[ArtifactWriteFuture] = field(default_factory=list)
    worker_observer: Optional[Callable[[], Any]] = None

    @property
    def byte_size(self) -> int:
        return self.snapshot.byte_size


class AsyncArtifactWriter:
    """Persist immutable JSON, JSONL, text, and compact state snapshots."""

    def __init__(
        self,
        spool_dir: str | Path,
        *,
        queue_capacity: int = 64,
        max_queue_bytes: int = DEFAULT_MAX_QUEUE_BYTES,
        max_write_concurrency: int = DEFAULT_MAX_WRITE_CONCURRENCY,
        fsync_policy: ArtifactFsyncPolicy | None = None,
        backpressure_timeout_seconds: float = 30.0,
        autostart: bool = True,
        name: str = "legal-ir-artifact-writer",
    ) -> None:
        self.spool_dir = Path(spool_dir)
        self.queue_capacity = max(1, int(queue_capacity))
        self.max_queue_bytes = max(1, int(max_queue_bytes))
        self.max_write_concurrency = max(1, int(max_write_concurrency))
        self.backpressure_timeout_seconds = max(
            0.0, float(backpressure_timeout_seconds)
        )
        self.fsync_policy = fsync_policy or ArtifactFsyncPolicy()
        self.name = name
        self._jobs: deque[_ArtifactJob] = deque()
        self._coalescible: Dict[str, _ArtifactJob] = {}
        self._threads: List[threading.Thread] = []
        self._thread: Optional[threading.Thread] = None  # compatibility/introspection
        self._closed = False
        self._stop_workers = False
        self._lock = threading.RLock()
        self._available = threading.Condition(self._lock)
        self._idle = threading.Condition(self._lock)
        self._pending = 0
        self._required_pending = 0
        self._reserved_bytes = 0
        self._peak_reserved_bytes = 0
        self._active_writes = 0
        self._peak_active_writes = 0
        self._completed = 0
        self._failed = 0
        self._replayed = 0
        self._backpressure_waits = 0
        self._backpressure_timeouts = 0
        self._coalesced = 0
        self._coalesced_bytes = 0
        self._bytes_written = 0
        self._last_receipt: Optional[ArtifactWriteReceipt] = None
        self._last_error: str = ""
        self._timings = {
            name: _TimingMetric()
            for name in (
                "enqueue",
                "serialization",
                "write",
                "fsync",
                "coalescing",
                "backpressure",
            )
        }
        self._path_locks: Dict[str, threading.Lock] = {}
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        if autostart:
            self.start()

    def start(self) -> None:
        with self._available:
            if self._threads:
                return
            if self._closed:
                raise RuntimeError("artifact writer is closed")
            for index in range(self.max_write_concurrency):
                thread = threading.Thread(
                    target=self._run,
                    name=f"{self.name}-{index + 1}",
                    daemon=True,
                )
                self._threads.append(thread)
                thread.start()
            self._thread = self._threads[0]

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._pending

    @property
    def pending_bytes(self) -> int:
        with self._lock:
            return self._reserved_bytes

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            last_receipt = self._last_receipt.to_dict() if self._last_receipt else None
            phase_timings = {
                name: metric.to_dict() for name, metric in self._timings.items()
            }
            result = {
                "active_write_count": self._active_writes,
                "backpressure_timeouts": self._backpressure_timeouts,
                "backpressure_waits": self._backpressure_waits,
                "bytes_written": self._bytes_written,
                "coalesced_bytes": self._coalesced_bytes,
                "coalesced_count": self._coalesced,
                "completed_count": self._completed,
                "enabled": True,
                "failed_count": self._failed,
                "fsync_policy": self.fsync_policy.to_dict(),
                "last_error": self._last_error,
                "last_receipt": last_receipt,
                "max_queue_bytes": self.max_queue_bytes,
                "max_write_concurrency": self.max_write_concurrency,
                "peak_active_write_count": self._peak_active_writes,
                "peak_queue_bytes": self._peak_reserved_bytes,
                "pending_bytes": self._reserved_bytes,
                "pending_count": self._pending,
                "queue_bytes": self._reserved_bytes,
                "queue_capacity": self.queue_capacity,
                "queue_depth": len(self._jobs),
                "replayed_count": self._replayed,
                "required_pending_count": self._required_pending,
                "schema_version": ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
                "spool_dir": str(self.spool_dir),
                "timings": phase_timings,
                "timings_seconds": phase_timings,
            }
            result.update(
                {
                    f"{name}_seconds": values["total"]
                    for name, values in phase_timings.items()
                }
            )
            return result

    def _observe(self, phase: str, seconds: float) -> None:
        with self._lock:
            self._timings[phase].observe(seconds)

    def _timed_fsync(self, fd: int) -> None:
        started = time.monotonic()
        os.fsync(fd)
        self._observe("fsync", time.monotonic() - started)

    def _fsync_directory(self, path: Path) -> None:
        if os.name == "nt":
            return
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            self._timed_fsync(fd)
        finally:
            os.close(fd)

    def snapshot_bytes(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        revision: int = 0,
        identity: str = "",
        serialization_seconds: float = 0.0,
    ) -> ArtifactSnapshotHandle:
        snapshot = ArtifactSnapshotHandle.from_bytes(
            payload,
            revision=revision,
            identity=identity,
            serialization_seconds=serialization_seconds,
        )
        self._observe("serialization", snapshot.serialization_seconds)
        return snapshot

    def snapshot_state_checkpoint(
        self,
        state: Any,
        *,
        cycle: int,
        full: bool = True,
        compact: bool = True,
        float_precision: str = "float64",
        metric_lineage: Any = None,
        base_state: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ArtifactSnapshotHandle:
        """Serialize one stable state revision into an immutable handle.

        A revision change during serialization fails closed instead of queuing
        bytes that claim a lineage they may not represent.
        """

        source_revision = int(getattr(state, "state_revision", 0))
        base_revision = (
            int(getattr(base_state, "state_revision", 0))
            if base_state is not None
            else None
        )
        state_identity = getattr(state, "state_identity", None)
        source_identity = (
            str(state_identity(metric_lineage=metric_lineage))
            if callable(state_identity)
            else ""
        )
        started = time.monotonic()
        if compact:
            if full:
                payload = serialize_checkpoint(
                    state,
                    float_precision=float_precision,
                    metric_lineage=metric_lineage,
                    metadata={"cycle": int(cycle), **dict(metadata or {})},
                    revision=source_revision,
                )
            else:
                if base_state is None:
                    raise ValueError("base_state is required for a compact state delta")
                payload = serialize_delta(
                    base_state,
                    state,
                    float_precision=float_precision,
                    metric_lineage=metric_lineage,
                    metadata={"cycle": int(cycle), **dict(metadata or {})},
                    base_revision=base_revision,
                    revision=source_revision,
                )
        else:
            to_dict = getattr(state, "to_dict", None)
            if callable(to_dict):
                payload = _json_bytes(to_dict(), indent=None)
            elif isinstance(state, Mapping):
                payload = _json_bytes(state, indent=None)
            else:
                raise TypeError(f"unsupported checkpoint state: {type(state).__name__}")
        elapsed = time.monotonic() - started
        if int(getattr(state, "state_revision", source_revision)) != source_revision:
            raise ConcurrentArtifactMutationError(
                "state mutated while checkpoint snapshot was being serialized"
            )
        if base_state is not None and int(
            getattr(base_state, "state_revision", base_revision)
        ) != base_revision:
            raise ConcurrentArtifactMutationError(
                "base state mutated while delta snapshot was being serialized"
            )
        return self.snapshot_bytes(
            payload,
            revision=source_revision,
            identity=source_identity or _sha256(payload),
            serialization_seconds=elapsed,
        )

    def replay_crash_artifacts(self) -> List[ArtifactWriteReceipt]:
        """Apply durable manifests left by a prior process."""

        self._cleanup_orphaned_temporary_files()
        receipts: List[ArtifactWriteReceipt] = []
        for manifest_path in sorted(self.spool_dir.glob("*.manifest.json")):
            try:
                started = time.monotonic()
                receipt = self._apply_manifest(manifest_path, replayed=True)
                self._observe("write", time.monotonic() - started)
            except Exception as exc:  # pragma: no cover - surfaced in summary
                with self._lock:
                    self._failed += 1
                    self._last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
                continue
            receipts.append(receipt)
            with self._lock:
                self._replayed += 1
                self._bytes_written += int(receipt.bytes_written)
                self._last_receipt = receipt
        return receipts

    def append_jsonl(
        self,
        path: str | Path,
        records: Iterable[Mapping[str, Any]],
        *,
        kind: str = "append_jsonl",
        dedupe_keys: Sequence[str] = ("evidence_id", "delta_id", "artifact_id", "job_id"),
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        started = time.monotonic()
        record_list = list(records)
        lines = [
            json.dumps(
                record,
                default=str,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            for record in record_list
        ]
        payload = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
        snapshot = self.snapshot_bytes(
            payload, serialization_seconds=time.monotonic() - started
        )
        future = self.submit_snapshot(
            path,
            snapshot,
            kind=kind,
            append_jsonl=True,
            dedupe_keys=tuple(dedupe_keys),
            metadata={"record_count": len(record_list), **dict(metadata or {})},
            timeout=timeout,
        )
        return future.result(timeout) if wait else future

    def append_jsonl_lines(
        self,
        path: str | Path,
        lines: Sequence[str],
        *,
        kind: str = "append_jsonl",
        dedupe_keys: Sequence[str] = ("evidence_id", "delta_id", "artifact_id", "job_id"),
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        started = time.monotonic()
        frozen_lines = [str(line).rstrip("\n") for line in lines if str(line).strip()]
        payload = (
            (("\n".join(frozen_lines) + "\n").encode("utf-8"))
            if frozen_lines
            else b""
        )
        snapshot = self.snapshot_bytes(
            payload, serialization_seconds=time.monotonic() - started
        )
        future = self.submit_snapshot(
            path,
            snapshot,
            kind=kind,
            append_jsonl=True,
            dedupe_keys=tuple(dedupe_keys),
            metadata={"record_count": len(frozen_lines), **dict(metadata or {})},
            timeout=timeout,
        )
        return future.result(timeout) if wait else future

    def write_json_atomic(
        self,
        path: str | Path,
        payload: Mapping[str, Any] | ArtifactSnapshotHandle,
        *,
        kind: str = "json",
        indent: Optional[int] = 2,
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
        coalesce: Optional[bool] = None,
        coalesce_key: Optional[str] = None,
        required: bool = False,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        if isinstance(payload, ArtifactSnapshotHandle):
            snapshot = payload
        else:
            started = time.monotonic()
            encoded = _json_bytes(payload, indent=indent)
            snapshot = self.snapshot_bytes(
                encoded, serialization_seconds=time.monotonic() - started
            )
        should_coalesce = kind == "summary" if coalesce is None else bool(coalesce)
        key = (
            str(coalesce_key)
            if coalesce_key is not None
            else (f"replace:{Path(path).absolute()}" if should_coalesce else "")
        )
        future = self.submit_snapshot(
            path,
            snapshot,
            kind=kind,
            metadata=metadata,
            timeout=timeout,
            coalesce_key=key,
            required=required,
        )
        return future.result(timeout) if wait else future

    def write_text_atomic(
        self,
        path: str | Path,
        text: str | ArtifactSnapshotHandle,
        *,
        kind: str = "text",
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
        coalesce_key: str = "",
        required: bool = False,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        if isinstance(text, ArtifactSnapshotHandle):
            snapshot = text
        else:
            started = time.monotonic()
            snapshot = self.snapshot_bytes(
                str(text).encode("utf-8"),
                serialization_seconds=time.monotonic() - started,
            )
        future = self.submit_snapshot(
            path,
            snapshot,
            kind=kind,
            metadata=metadata,
            timeout=timeout,
            coalesce_key=coalesce_key,
            required=required,
        )
        return future.result(timeout) if wait else future

    def write_state_checkpoint(
        self,
        path: str | Path,
        state: Any,
        *,
        cycle: int,
        full: bool = True,
        compact: Optional[bool] = None,
        float_precision: str = "float64",
        metric_lineage: Any = None,
        base_state: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
        required: bool = True,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        use_compact = (
            Path(path).suffix.lower() not in {".json", ".jsonl"}
            if compact is None
            else bool(compact)
        )
        worker_observer: Optional[Callable[[], Any]] = None
        if isinstance(state, ArtifactSnapshotHandle):
            snapshot = state
        else:
            snapshot = self.snapshot_state_checkpoint(
                state,
                cycle=cycle,
                full=full,
                compact=use_compact,
                float_precision=float_precision,
                metric_lineage=metric_lineage,
                base_state=base_state,
                metadata=metadata,
            )
            # Legacy JSON callers historically observed ``to_json`` on the
            # worker.  Keep that notification without using its mutable result;
            # the accepted snapshot bytes above are the sole write source.
            legacy_to_json = getattr(state, "to_json", None)
            if not use_compact and callable(legacy_to_json):
                worker_observer = legacy_to_json
        future = self.submit_snapshot(
            path,
            snapshot,
            kind="state_checkpoint_full" if full else "state_checkpoint_delta",
            append_state_delta=bool(use_compact and not full),
            metadata={
                "checkpoint_schema_version": (
                    MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION
                    if full
                    else MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION
                ) if use_compact else "legacy-json",
                "compact": bool(use_compact),
                "cycle": int(cycle),
                "float_precision": str(float_precision),
                "full": bool(full),
                "revision": snapshot.revision,
                "snapshot_identity": snapshot.identity,
                **dict(metadata or {}),
            },
            timeout=timeout,
            required=required,
            worker_observer=worker_observer,
        )
        return future.result(timeout) if wait else future

    def append_state_delta(
        self,
        path: str | Path,
        delta: Any,
        *,
        base_state: Any = None,
        cycle: int = 0,
        float_precision: str = "float64",
        metric_lineage: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        if isinstance(delta, ArtifactSnapshotHandle) or not isinstance(delta, Mapping) or base_state is not None:
            if not isinstance(delta, ArtifactSnapshotHandle) and base_state is None:
                raise ValueError("base_state is required for a compact state delta")
            return self.write_state_checkpoint(
                path,
                delta,
                cycle=cycle,
                full=False,
                compact=True,
                float_precision=float_precision,
                metric_lineage=metric_lineage,
                base_state=base_state,
                metadata=metadata,
                timeout=timeout,
                wait=wait,
                required=True,
            )
        payload = {
            "created_at": _utc_now(),
            "schema_version": STATE_DELTA_SCHEMA_VERSION,
            **dict(delta),
        }
        payload.setdefault(
            "delta_id", "lir-state-delta-" + _sha256(_json_bytes(payload))[:24]
        )
        return self.append_jsonl(
            path,
            [payload],
            kind="state_delta",
            dedupe_keys=("delta_id",),
            metadata=metadata,
            timeout=timeout,
            wait=wait,
        )

    def submit_snapshot(
        self,
        path: str | Path,
        snapshot: ArtifactSnapshotHandle,
        *,
        kind: str,
        append_jsonl: bool = False,
        append_state_delta: bool = False,
        dedupe_keys: Sequence[str] = (),
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        coalesce_key: str = "",
        required: bool = False,
        worker_observer: Optional[Callable[[], Any]] = None,
    ) -> ArtifactWriteFuture:
        if not isinstance(snapshot, ArtifactSnapshotHandle):
            raise TypeError("snapshot must be an immutable ArtifactSnapshotHandle")
        return self._submit(
            kind=kind,
            path=Path(path),
            snapshot=snapshot,
            append_jsonl=append_jsonl,
            append_state_delta=append_state_delta,
            dedupe_keys=dedupe_keys,
            metadata=metadata,
            timeout=timeout,
            coalesce_key=coalesce_key,
            required=required,
            worker_observer=worker_observer,
        )

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._idle:
            while self._pending > 0:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._idle.wait(remaining)
            return True

    def _wait_required(self) -> None:
        with self._idle:
            while self._required_pending > 0:
                self._idle.wait()

    def close(
        self,
        *,
        wait: bool = True,
        timeout: Optional[float] = None,
        cancel_pending: bool = False,
    ) -> bool:
        with self._available:
            if self._closed:
                return self._pending == 0
            self._closed = True
            if cancel_pending:
                retained: deque[_ArtifactJob] = deque()
                while self._jobs:
                    job = self._jobs.popleft()
                    if job.required:
                        retained.append(job)
                        continue
                    self._cancel_job_locked(job)
                self._jobs = retained
                self._coalescible = {
                    job.coalesce_key: job for job in retained if job.coalesce_key
                }
            self._available.notify_all()

        # Required checkpoint/delta writes are a durability contract.  They are
        # never cancelled merely because optional summary work hit a timeout.
        if self.pending_count and not self._threads:
            if self._required_pending or not cancel_pending:
                self.start_after_close_for_required()
        drained = self.wait_until_idle(timeout) if wait else self.pending_count == 0
        if self._required_pending:
            self._wait_required()

        with self._available:
            self._stop_workers = True
            self._available.notify_all()
            still_pending = self._pending > 0
        if still_pending:
            # The caller's timeout remains meaningful.  Workers are daemons and
            # will drain already accepted optional jobs, then observe the stop
            # flag and exit; required jobs were synchronously flushed above.
            return False
        for thread in self._threads:
            thread.join()
        return drained

    def start_after_close_for_required(self) -> None:
        """Start workers solely to honor already accepted required jobs."""

        with self._available:
            if self._threads:
                return
            for index in range(self.max_write_concurrency):
                thread = threading.Thread(
                    target=self._run,
                    name=f"{self.name}-shutdown-{index + 1}",
                    daemon=True,
                )
                self._threads.append(thread)
                thread.start()
            self._thread = self._threads[0]

    def _cancel_job_locked(self, job: _ArtifactJob) -> None:
        error = AsyncArtifactWriteError("artifact writer closed before write")
        if job.future is not None:
            job.future.set_exception(error)
        for follower in job.followers:
            follower.set_exception(error)
        self._pending = max(0, self._pending - 1)
        if job.required:
            self._required_pending = max(0, self._required_pending - 1)
        self._reserved_bytes = max(0, self._reserved_bytes - job.byte_size)
        if job.coalesce_key:
            self._coalescible.pop(job.coalesce_key, None)
        self._idle.notify_all()

    def _submit(
        self,
        *,
        kind: str,
        path: Path,
        snapshot: ArtifactSnapshotHandle,
        append_jsonl: bool = False,
        append_state_delta: bool = False,
        dedupe_keys: Sequence[str] = (),
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        coalesce_key: str = "",
        required: bool = False,
        worker_observer: Optional[Callable[[], Any]] = None,
    ) -> ArtifactWriteFuture:
        enqueue_started = time.monotonic()
        job_id = f"lir-artifact-{time.time_ns()}-{uuid.uuid4().hex[:12]}"
        future = ArtifactWriteFuture(job_id)
        job = _ArtifactJob(
            job_id=job_id,
            kind=str(kind),
            path=path,
            snapshot=snapshot,
            append_jsonl=append_jsonl,
            append_state_delta=append_state_delta,
            dedupe_keys=tuple(dedupe_keys),
            metadata=_immutable_json(dict(metadata or {})),
            created_at=snapshot.created_at,
            future=future,
            coalesce_key=str(coalesce_key or ""),
            required=bool(required),
            worker_observer=worker_observer,
        )
        effective_timeout = (
            self.backpressure_timeout_seconds if timeout is None else max(0.0, timeout)
        )
        deadline = time.monotonic() + effective_timeout
        waited = False
        with self._available:
            if self._closed:
                raise RuntimeError("artifact writer is closed")
            if job.byte_size > self.max_queue_bytes:
                self._backpressure_timeouts += 1
                error = AsyncArtifactBackpressureTimeout(
                    f"artifact snapshot is {job.byte_size} bytes; byte limit is "
                    f"{self.max_queue_bytes}"
                )
                future.set_exception(error)
                self._timings["backpressure"].observe(
                    time.monotonic() - enqueue_started
                )
                self._timings["enqueue"].observe(time.monotonic() - enqueue_started)
                raise error

            previous = self._coalescible.get(job.coalesce_key) if job.coalesce_key else None
            extra_bytes = job.byte_size - previous.byte_size if previous else job.byte_size
            while (
                (previous is None and self._pending >= self.queue_capacity)
                or self._reserved_bytes + max(0, extra_bytes) > self.max_queue_bytes
            ):
                waited = True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._backpressure_timeouts += 1
                    error = AsyncArtifactBackpressureTimeout(
                        "artifact writer admission full after "
                        f"{effective_timeout:.3f}s (jobs={self._pending}/"
                        f"{self.queue_capacity}, bytes={self._reserved_bytes}/"
                        f"{self.max_queue_bytes})"
                    )
                    future.set_exception(error)
                    self._timings["backpressure"].observe(
                        time.monotonic() - enqueue_started
                    )
                    self._timings["enqueue"].observe(
                        time.monotonic() - enqueue_started
                    )
                    raise error
                self._available.wait(remaining)
                if self._closed:
                    raise RuntimeError("artifact writer is closed")
                previous = (
                    self._coalescible.get(job.coalesce_key)
                    if job.coalesce_key
                    else None
                )
                extra_bytes = (
                    job.byte_size - previous.byte_size if previous else job.byte_size
                )

            if waited:
                self._backpressure_waits += 1
                self._timings["backpressure"].observe(
                    time.monotonic() - enqueue_started
                )

            if previous is not None:
                coalesce_started = time.monotonic()
                try:
                    index = self._jobs.index(previous)
                except ValueError:
                    previous = None
                else:
                    job.followers.extend(previous.followers)
                    if previous.future is not None:
                        job.followers.append(previous.future)
                    # A required final summary cannot lose that property when
                    # it supersedes or is superseded by another queued write.
                    job.required = bool(job.required or previous.required)
                    self._jobs[index] = job
                    self._coalescible[job.coalesce_key] = job
                    self._reserved_bytes += job.byte_size - previous.byte_size
                    if job.required and not previous.required:
                        self._required_pending += 1
                    self._coalesced += 1
                    self._coalesced_bytes += previous.byte_size
                    self._timings["coalescing"].observe(
                        time.monotonic() - coalesce_started
                    )

            if previous is None:
                self._jobs.append(job)
                if job.coalesce_key:
                    self._coalescible[job.coalesce_key] = job
                self._pending += 1
                if job.required:
                    self._required_pending += 1
                self._reserved_bytes += job.byte_size
            self._peak_reserved_bytes = max(
                self._peak_reserved_bytes, self._reserved_bytes
            )
            self._timings["enqueue"].observe(time.monotonic() - enqueue_started)
            self._available.notify()
        return future

    def _run(self) -> None:
        while True:
            with self._available:
                while not self._jobs and not self._stop_workers:
                    self._available.wait()
                if self._stop_workers and not self._jobs:
                    return
                job = self._jobs.popleft()
                if job.coalesce_key:
                    self._coalescible.pop(job.coalesce_key, None)
                self._active_writes += 1
                self._peak_active_writes = max(
                    self._peak_active_writes, self._active_writes
                )
            try:
                path_key = str(job.path.absolute())
                with self._lock:
                    path_lock = self._path_locks.setdefault(path_key, threading.Lock())
                started = time.monotonic()
                with path_lock:
                    receipt = self._write_job(job)
                self._observe("write", time.monotonic() - started)
                futures = ([job.future] if job.future is not None else []) + job.followers
                for future in futures:
                    future.set_result(receipt)
                with self._lock:
                    self._completed += 1
                    self._bytes_written += int(receipt.bytes_written)
                    self._last_receipt = receipt
            except BaseException as exc:  # noqa: BLE001 - must surface to future
                futures = ([job.future] if job.future is not None else []) + job.followers
                for future in futures:
                    future.set_exception(exc)
                with self._lock:
                    self._failed += 1
                    self._last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            finally:
                with self._available:
                    self._active_writes = max(0, self._active_writes - 1)
                    self._pending = max(0, self._pending - 1)
                    if job.required:
                        self._required_pending = max(0, self._required_pending - 1)
                    self._reserved_bytes = max(
                        0, self._reserved_bytes - job.byte_size
                    )
                    self._available.notify_all()
                    self._idle.notify_all()

    def _write_job(self, job: _ArtifactJob) -> ArtifactWriteReceipt:
        if job.worker_observer is not None:
            job.worker_observer()
        payload = job.snapshot.payload
        manifest_path = self._manifest_path(job.job_id)
        payload_path = self._payload_path(job.job_id)
        self._write_payload_atomic(payload_path, payload)
        if self.fsync_policy.directory:
            self._fsync_directory(payload_path.parent)
        manifest = {
            "append_jsonl": bool(job.append_jsonl),
            "append_state_delta": bool(job.append_state_delta),
            "checksum": _sha256(payload),
            "created_at": job.created_at,
            "dedupe_keys": list(job.dedupe_keys),
            "kind": job.kind,
            "metadata": _plain_json(job.metadata),
            "path": str(job.path),
            "payload_path": str(payload_path),
            "revision": job.snapshot.revision,
            "schema_version": ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
            "snapshot_identity": job.snapshot.identity,
        }
        self._write_manifest_atomic(manifest_path, manifest)
        return self._apply_manifest(manifest_path, replayed=False)

    def _write_payload_atomic(self, path: Path, payload: bytes) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            temporary.write_bytes(payload)
            if self.fsync_policy.manifest:
                with temporary.open("rb") as handle:
                    self._timed_fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def _manifest_path(self, job_id: str) -> Path:
        return self.spool_dir / f"{job_id}.manifest.json"

    def _payload_path(self, job_id: str) -> Path:
        return self.spool_dir / f"{job_id}.payload"

    def _write_manifest_atomic(self, path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        temporary.write_bytes(_json_bytes(payload, indent=2))
        if self.fsync_policy.manifest:
            with temporary.open("rb") as handle:
                self._timed_fsync(handle.fileno())
        os.replace(temporary, path)
        if self.fsync_policy.directory:
            self._fsync_directory(path.parent)

    def _apply_manifest(self, manifest_path: Path, *, replayed: bool) -> ArtifactWriteReceipt:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") not in _READABLE_WRITER_SCHEMA_VERSIONS:
            raise AsyncArtifactWriteError(f"unsupported manifest: {manifest_path}")
        payload_path = Path(str(manifest["payload_path"]))
        payload = payload_path.read_bytes()
        checksum = _sha256(payload)
        if checksum != str(manifest.get("checksum") or ""):
            raise AsyncArtifactWriteError(f"checksum mismatch for {payload_path}")
        destination = Path(str(manifest["path"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if bool(manifest.get("append_state_delta", False)):
            bytes_written = append_compact_delta_segment(
                destination, payload, fsync=self.fsync_policy.data
            )
            if self.fsync_policy.directory:
                self._fsync_directory(destination.parent)
        elif bool(manifest.get("append_jsonl", False)):
            bytes_written = self._append_jsonl_payload(
                destination,
                payload,
                dedupe_keys=tuple(str(key) for key in manifest.get("dedupe_keys", [])),
            )
        else:
            bytes_written = self._replace_payload(destination, payload)
        receipt = ArtifactWriteReceipt(
            bytes_written=bytes_written,
            checksum=checksum,
            completed_at=_utc_now(),
            created_at=str(manifest.get("created_at") or ""),
            job_id=manifest_path.name.removesuffix(".manifest.json"),
            kind=str(manifest.get("kind") or ""),
            manifest_path=str(manifest_path),
            metadata=_immutable_json(dict(manifest.get("metadata") or {})),
            path=str(destination),
            replayed=replayed,
        )
        try:
            manifest_path.unlink()
            payload_path.unlink()
            if self.fsync_policy.directory:
                self._fsync_directory(self.spool_dir)
        except OSError:
            pass
        return receipt

    def _replace_payload(self, destination: Path, payload: bytes) -> int:
        if destination.exists():
            try:
                if _sha256(destination.read_bytes()) == _sha256(payload):
                    return 0
            except OSError:
                pass
        temporary = destination.with_name(
            f".{destination.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        try:
            temporary.write_bytes(payload)
            if self.fsync_policy.data:
                with temporary.open("rb") as handle:
                    self._timed_fsync(handle.fileno())
            os.replace(temporary, destination)
            if self.fsync_policy.directory:
                self._fsync_directory(destination.parent)
            return len(payload)
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def _append_jsonl_payload(
        self,
        destination: Path,
        payload: bytes,
        *,
        dedupe_keys: Sequence[str],
    ) -> int:
        if not payload:
            return 0
        lines = [line for line in payload.decode("utf-8").splitlines() if line.strip()]
        existing_ids = self._existing_jsonl_ids(destination, dedupe_keys)
        selected: List[str] = []
        for line in lines:
            record_id = self._jsonl_record_id(line, dedupe_keys)
            if record_id and record_id in existing_ids:
                continue
            selected.append(line)
            if record_id:
                existing_ids.add(record_id)
        if not selected:
            return 0
        data = ("\n".join(selected) + "\n").encode("utf-8")
        fd = os.open(str(destination), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
            if self.fsync_policy.data:
                self._timed_fsync(fd)
        finally:
            os.close(fd)
        if self.fsync_policy.directory:
            self._fsync_directory(destination.parent)
        return int(written)

    def _existing_jsonl_ids(self, path: Path, keys: Sequence[str]) -> set[str]:
        if not keys or not path.exists():
            return set()
        ids: set[str] = set()
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    record_id = self._jsonl_record_id(line, keys)
                    if record_id:
                        ids.add(record_id)
        except OSError:
            return ids
        return ids

    @staticmethod
    def _jsonl_record_id(line: str, keys: Sequence[str]) -> str:
        if not keys:
            return ""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return ""
        if not isinstance(payload, Mapping):
            return ""
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return f"{key}:{value}"
        return ""

    def _cleanup_orphaned_temporary_files(self) -> None:
        for pattern in ("*.tmp-*", ".*.tmp-*"):
            for path in self.spool_dir.glob(pattern):
                if path.name.endswith(".manifest.json"):
                    continue
                try:
                    path.unlink()
                except OSError:
                    pass
