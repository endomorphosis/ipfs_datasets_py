"""Bounded asynchronous artifact persistence for LegalIR trainer runs."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .modal_autoencoder_checkpoint import (
    MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
    MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION,
    append_delta_segment as append_compact_delta_segment,
    serialize_checkpoint,
    serialize_delta,
)


ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION = "legal-ir-async-artifact-writer-v1"
STATE_DELTA_SCHEMA_VERSION = "legal-ir-autoencoder-state-delta-v1"


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


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class ArtifactFsyncPolicy:
    """Durability policy for worker writes.

    ``data`` fsyncs file contents before a rename/completion.  ``directory``
    fsyncs the parent directory after renames or manifest removal.  ``manifest``
    fsyncs worker payloads and manifests before a future is completed.
    """

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
            "metadata": dict(self.metadata),
            "path": self.path,
            "replayed": bool(self.replayed),
            "schema_version": ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
        }


class AsyncArtifactBackpressureTimeout(TimeoutError):
    """Raised when the bounded writer cannot accept work before timeout."""


class AsyncArtifactWriteError(RuntimeError):
    """Raised when an accepted artifact write fails."""


class ArtifactWriteFuture:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._event = threading.Event()
        self._receipt: Optional[ArtifactWriteReceipt] = None
        self._error: Optional[BaseException] = None

    def set_result(self, receipt: ArtifactWriteReceipt) -> None:
        self._receipt = receipt
        self._event.set()

    def set_exception(self, error: BaseException) -> None:
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
    payload_factory: Callable[[], bytes]
    created_at: str
    append_jsonl: bool = False
    append_state_delta: bool = False
    dedupe_keys: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    future: Optional[ArtifactWriteFuture] = None


class AsyncArtifactWriter:
    """Persist JSON, JSONL, and compact state artifacts with crash replay."""

    def __init__(
        self,
        spool_dir: str | Path,
        *,
        queue_capacity: int = 64,
        fsync_policy: ArtifactFsyncPolicy | None = None,
        backpressure_timeout_seconds: float = 30.0,
        autostart: bool = True,
        name: str = "legal-ir-artifact-writer",
    ) -> None:
        self.spool_dir = Path(spool_dir)
        self.queue_capacity = max(1, int(queue_capacity))
        self.backpressure_timeout_seconds = max(
            0.0,
            float(backpressure_timeout_seconds),
        )
        self.fsync_policy = fsync_policy or ArtifactFsyncPolicy()
        self.name = name
        self._queue: queue.Queue[_ArtifactJob | None] = queue.Queue(
            maxsize=self.queue_capacity
        )
        self._thread: Optional[threading.Thread] = None
        self._closed = False
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._pending = 0
        self._completed = 0
        self._failed = 0
        self._replayed = 0
        self._backpressure_waits = 0
        self._backpressure_timeouts = 0
        self._bytes_written = 0
        self._last_receipt: Optional[ArtifactWriteReceipt] = None
        self._last_error: str = ""
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        if autostart:
            self.start()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run,
                name=self.name,
                daemon=True,
            )
            self._thread.start()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._pending

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            last_receipt = self._last_receipt.to_dict() if self._last_receipt else None
            return {
                "backpressure_timeouts": self._backpressure_timeouts,
                "backpressure_waits": self._backpressure_waits,
                "bytes_written": self._bytes_written,
                "completed_count": self._completed,
                "enabled": True,
                "failed_count": self._failed,
                "fsync_policy": self.fsync_policy.to_dict(),
                "last_error": self._last_error,
                "last_receipt": last_receipt,
                "pending_count": self._pending,
                "queue_capacity": self.queue_capacity,
                "queue_depth": self._queue.qsize(),
                "replayed_count": self._replayed,
                "schema_version": ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
                "spool_dir": str(self.spool_dir),
            }

    def replay_crash_artifacts(self) -> List[ArtifactWriteReceipt]:
        """Apply durable manifests left by a prior process."""

        self._cleanup_orphaned_temporary_files()
        receipts: List[ArtifactWriteReceipt] = []
        for manifest_path in sorted(self.spool_dir.glob("*.manifest.json")):
            try:
                receipt = self._apply_manifest(manifest_path, replayed=True)
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
        frozen_records = copy.deepcopy([dict(record) for record in records])

        def payload_factory() -> bytes:
            lines = [
                json.dumps(
                    record,
                    default=str,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for record in frozen_records
            ]
            if not lines:
                return b""
            return ("\n".join(lines) + "\n").encode("utf-8")

        future = self._submit(
            kind=kind,
            path=Path(path),
            payload_factory=payload_factory,
            append_jsonl=True,
            dedupe_keys=tuple(dedupe_keys),
            metadata={
                "record_count": len(frozen_records),
                **dict(metadata or {}),
            },
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
        frozen_lines = [str(line).rstrip("\n") for line in lines if str(line).strip()]

        def payload_factory() -> bytes:
            if not frozen_lines:
                return b""
            return ("\n".join(frozen_lines) + "\n").encode("utf-8")

        future = self._submit(
            kind=kind,
            path=Path(path),
            payload_factory=payload_factory,
            append_jsonl=True,
            dedupe_keys=tuple(dedupe_keys),
            metadata={
                "record_count": len(frozen_lines),
                **dict(metadata or {}),
            },
            timeout=timeout,
        )
        return future.result(timeout) if wait else future

    def write_json_atomic(
        self,
        path: str | Path,
        payload: Mapping[str, Any],
        *,
        kind: str = "json",
        indent: Optional[int] = 2,
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        frozen_payload = copy.deepcopy(dict(payload))

        def payload_factory() -> bytes:
            return _json_bytes(frozen_payload, indent=indent)

        future = self._submit(
            kind=kind,
            path=Path(path),
            payload_factory=payload_factory,
            metadata=metadata,
            timeout=timeout,
        )
        return future.result(timeout) if wait else future

    def write_text_atomic(
        self,
        path: str | Path,
        text: str,
        *,
        kind: str = "text",
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        wait: bool = False,
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        frozen_text = str(text)

        def payload_factory() -> bytes:
            return frozen_text.encode("utf-8")

        future = self._submit(
            kind=kind,
            path=Path(path),
            payload_factory=payload_factory,
            metadata=metadata,
            timeout=timeout,
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
    ) -> ArtifactWriteFuture | ArtifactWriteReceipt:
        state_copy = state.copy() if hasattr(state, "copy") else copy.deepcopy(state)
        source_revision = int(getattr(state, "state_revision", 0))
        tracker = getattr(state_copy, "_state_identity_tracker", None)
        restore_revision = getattr(tracker, "restore_revision", None)
        if callable(restore_revision):
            restore_revision(source_revision)
        use_compact = (
            Path(path).suffix.lower() not in {".json", ".jsonl"}
            if compact is None
            else bool(compact)
        )
        base_copy = None
        base_revision = None
        if not full:
            if base_state is None:
                raise ValueError("base_state is required for a compact state delta")
            base_copy = (
                base_state.copy()
                if hasattr(base_state, "copy")
                else copy.deepcopy(base_state)
            )
            base_revision = int(getattr(base_state, "state_revision", 0))
            base_tracker = getattr(base_copy, "_state_identity_tracker", None)
            base_restore = getattr(base_tracker, "restore_revision", None)
            if callable(base_restore):
                base_restore(base_revision)
            use_compact = True

        def payload_factory() -> bytes:
            if use_compact:
                if full:
                    return serialize_checkpoint(
                        state_copy,
                        float_precision=float_precision,
                        metric_lineage=metric_lineage,
                        metadata={"cycle": int(cycle), **dict(metadata or {})},
                        revision=source_revision,
                    )
                assert base_copy is not None
                return serialize_delta(
                    base_copy,
                    state_copy,
                    float_precision=float_precision,
                    metric_lineage=metric_lineage,
                    metadata={"cycle": int(cycle), **dict(metadata or {})},
                    base_revision=base_revision,
                    revision=source_revision,
                )
            to_json = getattr(state_copy, "to_json", None)
            if callable(to_json):
                return (to_json() + "\n").encode("utf-8")
            if isinstance(state_copy, Mapping):
                return _json_bytes(state_copy, indent=None)
            raise TypeError(f"unsupported checkpoint state: {type(state_copy).__name__}")

        future = self._submit(
            kind="state_checkpoint_full" if full else "state_checkpoint_delta",
            path=Path(path),
            payload_factory=payload_factory,
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
                "revision": source_revision,
                **dict(metadata or {}),
            },
            timeout=timeout,
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
        if not isinstance(delta, Mapping) or base_state is not None:
            if base_state is None:
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
            )
        payload = {
            "created_at": _utc_now(),
            "schema_version": STATE_DELTA_SCHEMA_VERSION,
            **copy.deepcopy(dict(delta)),
        }
        payload.setdefault(
            "delta_id",
            "lir-state-delta-" + _sha256(_json_bytes(payload, indent=None))[:24],
        )
        return self.append_jsonl(
            path,
            [payload],
            kind="state_delta",
            dedupe_keys=("delta_id",),
            timeout=timeout,
            wait=wait,
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

    def close(
        self,
        *,
        wait: bool = True,
        timeout: Optional[float] = None,
        cancel_pending: bool = False,
    ) -> bool:
        drained = True
        if wait:
            drained = self.wait_until_idle(timeout)
        if cancel_pending and (not wait or not drained):
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not None and item.future is not None:
                    item.future.set_exception(
                        AsyncArtifactWriteError("artifact writer closed before write")
                    )
                self._queue.task_done()
                with self._idle:
                    self._pending = max(0, self._pending - 1)
                    self._idle.notify_all()
        with self._lock:
            if self._closed:
                return drained
            self._closed = True
        if self._thread is not None:
            deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
            while True:
                try:
                    self._queue.put(None, timeout=0.1)
                    break
                except queue.Full:
                    if cancel_pending:
                        try:
                            item = self._queue.get_nowait()
                        except queue.Empty:
                            continue
                        if item is not None and item.future is not None:
                            item.future.set_exception(
                                AsyncArtifactWriteError(
                                    "artifact writer closed before write"
                                )
                            )
                        self._queue.task_done()
                        with self._idle:
                            self._pending = max(0, self._pending - 1)
                            self._idle.notify_all()
                        continue
                    if deadline is not None and time.monotonic() >= deadline:
                        return False
            self._thread.join(timeout=timeout)
        return drained

    def _submit(
        self,
        *,
        kind: str,
        path: Path,
        payload_factory: Callable[[], bytes],
        append_jsonl: bool = False,
        append_state_delta: bool = False,
        dedupe_keys: Sequence[str] = (),
        metadata: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> ArtifactWriteFuture:
        with self._lock:
            if self._closed:
                raise RuntimeError("artifact writer is closed")
            self._pending += 1
        job_id = f"lir-artifact-{time.time_ns()}-{uuid.uuid4().hex[:12]}"
        future = ArtifactWriteFuture(job_id)
        job = _ArtifactJob(
            job_id=job_id,
            kind=str(kind),
            path=path,
            payload_factory=payload_factory,
            append_jsonl=append_jsonl,
            append_state_delta=append_state_delta,
            dedupe_keys=tuple(dedupe_keys),
            metadata=copy.deepcopy(dict(metadata or {})),
            created_at=_utc_now(),
            future=future,
        )
        effective_timeout = (
            self.backpressure_timeout_seconds if timeout is None else max(0.0, timeout)
        )
        started = time.monotonic()
        try:
            self._queue.put(job, timeout=effective_timeout)
        except queue.Full as exc:
            with self._idle:
                self._pending = max(0, self._pending - 1)
                self._backpressure_timeouts += 1
                self._idle.notify_all()
            error = AsyncArtifactBackpressureTimeout(
                f"artifact writer queue full after {effective_timeout:.3f}s"
            )
            future.set_exception(error)
            raise error from exc
        waited = time.monotonic() - started
        if waited > 0.001:
            with self._lock:
                self._backpressure_waits += 1
        return future

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                self._queue.task_done()
                return
            try:
                receipt = self._write_job(job)
                if job.future is not None:
                    job.future.set_result(receipt)
                with self._lock:
                    self._completed += 1
                    self._bytes_written += int(receipt.bytes_written)
                    self._last_receipt = receipt
            except BaseException as exc:  # noqa: BLE001 - must surface to future
                if job.future is not None:
                    job.future.set_exception(exc)
                with self._lock:
                    self._failed += 1
                    self._last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            finally:
                self._queue.task_done()
                with self._idle:
                    self._pending = max(0, self._pending - 1)
                    self._idle.notify_all()

    def _write_job(self, job: _ArtifactJob) -> ArtifactWriteReceipt:
        payload = job.payload_factory()
        manifest_path = self._manifest_path(job.job_id)
        payload_path = self._payload_path(job.job_id)
        self._write_payload_atomic(payload_path, payload)
        if self.fsync_policy.directory:
            _fsync_directory(payload_path.parent)
        manifest = {
            "append_jsonl": bool(job.append_jsonl),
            "append_state_delta": bool(job.append_state_delta),
            "checksum": _sha256(payload),
            "created_at": job.created_at,
            "dedupe_keys": list(job.dedupe_keys),
            "kind": job.kind,
            "metadata": dict(job.metadata),
            "path": str(job.path),
            "payload_path": str(payload_path),
            "schema_version": ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION,
        }
        self._write_manifest_atomic(manifest_path, manifest)
        return self._apply_manifest(manifest_path, replayed=False)

    def _write_payload_atomic(self, path: Path, payload: bytes) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            temporary.write_bytes(payload)
            if self.fsync_policy.manifest:
                with temporary.open("rb") as handle:
                    os.fsync(handle.fileno())
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
                os.fsync(handle.fileno())
        os.replace(temporary, path)
        if self.fsync_policy.directory:
            _fsync_directory(path.parent)

    def _apply_manifest(self, manifest_path: Path, *, replayed: bool) -> ArtifactWriteReceipt:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != ASYNC_ARTIFACT_WRITER_SCHEMA_VERSION:
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
                destination,
                payload,
                fsync=self.fsync_policy.data,
            )
            if self.fsync_policy.directory:
                _fsync_directory(destination.parent)
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
            metadata=dict(manifest.get("metadata") or {}),
            path=str(destination),
            replayed=replayed,
        )
        try:
            manifest_path.unlink()
            payload_path.unlink()
            if self.fsync_policy.directory:
                _fsync_directory(self.spool_dir)
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
                    os.fsync(handle.fileno())
            os.replace(temporary, destination)
            if self.fsync_policy.directory:
                _fsync_directory(destination.parent)
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
        flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND
        fd = os.open(str(destination), flags, 0o644)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
            if self.fsync_policy.data:
                os.fsync(fd)
        finally:
            os.close(fd)
        if self.fsync_policy.directory:
            _fsync_directory(destination.parent)
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
