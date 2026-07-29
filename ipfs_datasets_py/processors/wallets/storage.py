"""Transactional dataset sinks and content-addressed raw payload storage.

Streaming ingestion never accumulates whole-history state in the sink: each
:class:`~protocols.RecordBatch` is staged independently, deduplicated by
stable ``record_id``, and only becomes durable after :meth:`DatasetSink.commit`.
Partial or cancelled runs leave staged data aborted and do not invent a
successful sink commit for checkpoint CAS.

Importing this module performs no network I/O.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from .canonical import canonical_json_bytes, content_digest
from .errors import DatasetSinkError, InvalidRequestError, ResourceLimitError
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

# Conservative custody defaults: explicit retention is always bounded.
DEFAULT_MAX_RAW_OBJECT_BYTES = 1_048_576  # 1 MiB per object
DEFAULT_MAX_RAW_TOTAL_BYTES = 16 * 1024 * 1024  # 16 MiB per store / run
DEFAULT_MAX_RAW_OBJECTS = 1_000

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


def _required_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    return value


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
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


@dataclass(frozen=True, slots=True)
class RawPayloadCustodyLimits:
    """Positive per-object, per-run byte, and retained-object custody ceilings.

    These limits are independent of transport :class:`~protocols.RequestLimits`
    and are enforced by raw-payload stores **before** copying, hashing, or
    durable writes so failed puts leave store state unchanged.
    """

    max_object_bytes: int = DEFAULT_MAX_RAW_OBJECT_BYTES
    max_total_bytes: int = DEFAULT_MAX_RAW_TOTAL_BYTES
    max_objects: int = DEFAULT_MAX_RAW_OBJECTS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_object_bytes",
            _positive_int(self.max_object_bytes, "max_object_bytes"),
        )
        object.__setattr__(
            self,
            "max_total_bytes",
            _positive_int(self.max_total_bytes, "max_total_bytes"),
        )
        object.__setattr__(
            self, "max_objects", _positive_int(self.max_objects, "max_objects")
        )
        if self.max_object_bytes > self.max_total_bytes:
            raise InvalidRequestError(
                "max_object_bytes must not exceed max_total_bytes"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_object_bytes": self.max_object_bytes,
            "max_total_bytes": self.max_total_bytes,
            "max_objects": self.max_objects,
        }


@runtime_checkable
class RawPayloadEncryptor(Protocol):
    """Injected encryptor for :attr:`RawPayloadPolicy.SEPARATELY_ENCRYPTED` custody."""

    def encrypt(self, plaintext: bytes) -> bytes:
        """Return ciphertext for *plaintext* without logging the input."""

        ...

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Return plaintext for *ciphertext* without logging the material."""

        ...


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


def _as_body_bytes(body: object) -> bytes:
    """Validate body type without allocating a second copy for ``bytes`` inputs."""

    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, memoryview):
        return body.tobytes()
    raise InvalidRequestError("body must be bytes")


def _enforce_object_size(
    body: bytes,
    *,
    limits: RawPayloadCustodyLimits,
    context: OperationContext,
) -> int:
    """Reject oversized payloads before hashing, allocation, or writes.

    Returns the inspected byte length.  Uses ``len`` only so no extra buffer is
    allocated for the size check itself.
    """

    size = len(body)
    if size > limits.max_object_bytes:
        raise ResourceLimitError(
            f"raw payload exceeds max_object_bytes ({limits.max_object_bytes})"
        )
    # Operation-level response ceiling also bounds retained raw objects.
    if size > context.limits.max_response_bytes:
        raise ResourceLimitError(
            "raw payload exceeds operation max_response_bytes"
        )
    return size


def _enforce_capacity(
    *,
    size: int,
    is_new: bool,
    object_count: int,
    total_bytes: int,
    limits: RawPayloadCustodyLimits,
) -> None:
    """Reject over-count / over-total retention before mutating store state."""

    if not is_new:
        return
    if object_count >= limits.max_objects:
        raise ResourceLimitError(
            f"raw payload store exceeds max_objects ({limits.max_objects})"
        )
    if total_bytes + size > limits.max_total_bytes:
        raise ResourceLimitError(
            f"raw payload store exceeds max_total_bytes ({limits.max_total_bytes})"
        )


def _require_encryptor_for_policy(
    policy: RawPayloadPolicy,
    encryptor: RawPayloadEncryptor | None,
) -> None:
    """Fail closed when encrypted custody is requested without an encryptor."""

    if policy is RawPayloadPolicy.SEPARATELY_ENCRYPTED and encryptor is None:
        raise InvalidRequestError(
            "separately_encrypted raw payload policy requires an injected encryptor"
        )


def _restrictive_mkdir(path: Path) -> None:
    """Create *path* (and parents) with owner-only directory permissions."""

    path.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
    try:
        path.chmod(_DIRECTORY_MODE)
    except OSError:
        # Best-effort on platforms that ignore POSIX modes (e.g. some tmpfs/mnt).
        pass


def _restrictive_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write *data* with owner-only file permissions."""

    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    # Prefer exclusive owner-only create; fall back when the platform rejects mode.
    fd = os.open(tmp, flags, _FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    try:
        path.chmod(_FILE_MODE)
    except OSError:
        pass


class InMemoryRawPayloadStore:
    """Process-local raw payload store with hard custody ceilings.

    Suitable for tests and single-process runs.  Bounds are enforced before
    hashing or retaining body bytes so rejected puts leave the store unchanged.
    """

    def __init__(
        self,
        *,
        limits: RawPayloadCustodyLimits | None = None,
        max_object_bytes: int | None = None,
        max_total_bytes: int | None = None,
        max_objects: int | None = None,
        policy: RawPayloadPolicy = RawPayloadPolicy.REFERENCED,
        encryptor: RawPayloadEncryptor | None = None,
    ) -> None:
        if limits is not None and not isinstance(limits, RawPayloadCustodyLimits):
            raise InvalidRequestError("limits must be a RawPayloadCustodyLimits")
        if limits is None:
            limits = RawPayloadCustodyLimits(
                max_object_bytes=(
                    DEFAULT_MAX_RAW_OBJECT_BYTES
                    if max_object_bytes is None
                    else max_object_bytes
                ),
                max_total_bytes=(
                    DEFAULT_MAX_RAW_TOTAL_BYTES
                    if max_total_bytes is None
                    else max_total_bytes
                ),
                max_objects=(
                    DEFAULT_MAX_RAW_OBJECTS if max_objects is None else max_objects
                ),
            )
        elif any(v is not None for v in (max_object_bytes, max_total_bytes, max_objects)):
            raise InvalidRequestError(
                "pass either limits= or individual max_* kwargs, not both"
            )
        if not isinstance(policy, RawPayloadPolicy):
            raise InvalidRequestError("policy must be a RawPayloadPolicy")
        _require_encryptor_for_policy(policy, encryptor)
        self._limits = limits
        self._policy = policy
        self._encryptor = encryptor
        self._entries: dict[str, StoredRawPayload] = {}
        self._total_bytes = 0

    @property
    def limits(self) -> RawPayloadCustodyLimits:
        return self._limits

    @property
    def policy(self) -> RawPayloadPolicy:
        return self._policy

    @property
    def encryptor(self) -> RawPayloadEncryptor | None:
        return self._encryptor

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

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
        if self._policy is RawPayloadPolicy.OMITTED:
            raise InvalidRequestError(
                "raw payload retention is omitted by policy; enable an explicit "
                "retention policy with positive custody limits"
            )
        _require_encryptor_for_policy(self._policy, self._encryptor)
        raw = _as_body_bytes(body)
        # Size / operation bounds before any copy, hash, encrypt, or allocation.
        size = _enforce_object_size(raw, limits=self._limits, context=context)

        digest = digest_bytes(raw)
        existing = self._entries.get(digest)
        if existing is not None:
            # Content-addressed: identical digest is a no-op; never inflate totals.
            # Defensive equality check only applies to plaintext custody (encrypted
            # ciphertext may be non-deterministic across encrypt calls).
            if self._encryptor is None and existing.body != raw:
                raise DatasetSinkError(
                    f"raw payload digest collision for {digest}"
                )
            return existing

        _enforce_capacity(
            size=size,
            is_new=True,
            object_count=len(self._entries),
            total_bytes=self._total_bytes,
            limits=self._limits,
        )

        stored_body = raw
        if self._encryptor is not None:
            try:
                stored_body = self._encryptor.encrypt(raw)
            except Exception as exc:
                raise DatasetSinkError("raw payload encryption failed") from exc
            if not isinstance(stored_body, (bytes, bytearray)):
                raise DatasetSinkError("encryptor.encrypt must return bytes")
            stored_body = bytes(stored_body)

        payload = StoredRawPayload(
            digest=digest,
            body=stored_body,
            media_type=media_type,
            cid=cid,
        )
        # Accounting uses plaintext size so encryption overhead cannot bypass caps.
        self._entries[digest] = payload
        self._total_bytes += size
        return payload

    async def get(
        self,
        digest: str,
        *,
        context: OperationContext,
    ) -> StoredRawPayload | None:
        context.check_active()
        _required_str(digest, "digest")
        stored = self._entries.get(digest)
        if stored is None:
            return None
        body = stored.body
        if self._encryptor is not None:
            body = self._encryptor.decrypt(body)
            if not isinstance(body, (bytes, bytearray)):
                raise DatasetSinkError("encryptor.decrypt must return bytes")
            body = bytes(body)
        return StoredRawPayload(
            digest=stored.digest,
            body=body,
            media_type=stored.media_type,
            cid=stored.cid,
        )


class DirectoryRawPayloadStore:
    """Filesystem-backed raw payload store with hard custody ceilings.

    The store directory is created with owner-only permissions (``0o700``) and
    payload files with owner-only permissions (``0o600``).  Bounds are enforced
    before hashing or durable writes so rejected puts leave the store unchanged.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        limits: RawPayloadCustodyLimits | None = None,
        max_object_bytes: int | None = None,
        max_total_bytes: int | None = None,
        max_objects: int | None = None,
        policy: RawPayloadPolicy = RawPayloadPolicy.REFERENCED,
        encryptor: RawPayloadEncryptor | None = None,
    ) -> None:
        if limits is not None and not isinstance(limits, RawPayloadCustodyLimits):
            raise InvalidRequestError("limits must be a RawPayloadCustodyLimits")
        if limits is None:
            limits = RawPayloadCustodyLimits(
                max_object_bytes=(
                    DEFAULT_MAX_RAW_OBJECT_BYTES
                    if max_object_bytes is None
                    else max_object_bytes
                ),
                max_total_bytes=(
                    DEFAULT_MAX_RAW_TOTAL_BYTES
                    if max_total_bytes is None
                    else max_total_bytes
                ),
                max_objects=(
                    DEFAULT_MAX_RAW_OBJECTS if max_objects is None else max_objects
                ),
            )
        elif any(v is not None for v in (max_object_bytes, max_total_bytes, max_objects)):
            raise InvalidRequestError(
                "pass either limits= or individual max_* kwargs, not both"
            )
        if not isinstance(policy, RawPayloadPolicy):
            raise InvalidRequestError("policy must be a RawPayloadPolicy")
        _require_encryptor_for_policy(policy, encryptor)
        self._root = Path(root)
        _restrictive_mkdir(self._root)
        self._limits = limits
        self._policy = policy
        self._encryptor = encryptor
        self._total_bytes = 0
        self._object_count = 0
        self._known_digests: set[str] = set()
        self._hydrate_accounting()

    def _hydrate_accounting(self) -> None:
        """Initialize in-process counters from any pre-existing payload files."""

        for path in self._root.glob("*.bin"):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            digest = path.stem.replace("_", ":", 1)
            self._known_digests.add(digest)
            self._object_count += 1
            self._total_bytes += size

    @property
    def root(self) -> Path:
        return self._root

    @property
    def limits(self) -> RawPayloadCustodyLimits:
        return self._limits

    @property
    def policy(self) -> RawPayloadPolicy:
        return self._policy

    @property
    def encryptor(self) -> RawPayloadEncryptor | None:
        return self._encryptor

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def __len__(self) -> int:
        return self._object_count

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
        if self._policy is RawPayloadPolicy.OMITTED:
            raise InvalidRequestError(
                "raw payload retention is omitted by policy; enable an explicit "
                "retention policy with positive custody limits"
            )
        _require_encryptor_for_policy(self._policy, self._encryptor)
        raw = _as_body_bytes(body)
        size = _enforce_object_size(raw, limits=self._limits, context=context)

        digest = digest_bytes(raw)
        path = self._path_for(digest)
        meta_path = path.with_suffix(".meta.json")
        if path.exists():
            # Idempotent content-addressed hit: no new capacity consumed.
            # Encrypted ciphertext may be non-deterministic, so when an encryptor
            # is present we trust the digest key and skip byte equality.
            existing_body = path.read_bytes()
            if self._encryptor is None and existing_body != raw:
                raise DatasetSinkError(
                    f"raw payload digest collision for {digest}"
                )
            return StoredRawPayload(
                digest=digest,
                body=existing_body if self._encryptor is not None else raw,
                media_type=media_type,
                cid=cid,
            )

        _enforce_capacity(
            size=size,
            is_new=True,
            object_count=self._object_count,
            total_bytes=self._total_bytes,
            limits=self._limits,
        )

        stored_body = raw
        if self._encryptor is not None:
            try:
                stored_body = self._encryptor.encrypt(raw)
            except Exception as exc:
                # Encryption failure must not leave partial files or counters.
                raise DatasetSinkError("raw payload encryption failed") from exc
            if not isinstance(stored_body, (bytes, bytearray)):
                raise DatasetSinkError("encryptor.encrypt must return bytes")
            stored_body = bytes(stored_body)

        payload = StoredRawPayload(
            digest=digest,
            body=stored_body,
            media_type=media_type,
            cid=cid,
        )
        # Write body then meta; counters update only after both succeed.
        _restrictive_write_bytes(path, payload.body)
        try:
            _restrictive_write_bytes(
                meta_path, canonical_json_bytes(payload.to_dict())
            )
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        self._known_digests.add(digest)
        self._object_count += 1
        self._total_bytes += size
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
        if self._encryptor is not None:
            try:
                body = self._encryptor.decrypt(body)
            except Exception as exc:
                raise DatasetSinkError("raw payload decryption failed") from exc
            if not isinstance(body, (bytes, bytearray)):
                raise DatasetSinkError("encryptor.decrypt must return bytes")
            body = bytes(body)
        return StoredRawPayload(
            digest=digest, body=body, media_type=media_type, cid=cid
        )


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
    "DEFAULT_MAX_RAW_OBJECT_BYTES",
    "DEFAULT_MAX_RAW_OBJECTS",
    "DEFAULT_MAX_RAW_TOTAL_BYTES",
    "RAW_PAYLOAD_SCHEMA_VERSION",
    "SINK_RECEIPT_SCHEMA_VERSION",
    "BatchWriteReceipt",
    "DirectoryRawPayloadStore",
    "InMemoryRawPayloadStore",
    "RawPayloadCustodyLimits",
    "RawPayloadEncryptor",
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
