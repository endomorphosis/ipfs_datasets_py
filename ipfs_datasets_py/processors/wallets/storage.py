"""Transactional dataset sinks and content-addressed raw payload storage.

Streaming ingestion never accumulates whole-history state in the sink: each
:class:`~protocols.RecordBatch` is staged independently, deduplicated by
stable ``record_id``, and only becomes durable after :meth:`DatasetSink.commit`.
Partial or cancelled runs leave staged data aborted and do not invent a
successful sink commit for checkpoint CAS.

Authority modes (DQK-071 / DQK-072 / DQK-073):

* ``off`` — JSONL / in-memory only (legacy unit-test path).
* ``shadow`` — dual-write into DuckDB; JSONL / in-memory remain authority
  (DQK-071).
* ``dual`` — DuckDB is authoritative for normalized ledger state; JSONL,
  Parquet, Arrow and CAR are outbox-driven exports (DQK-072).
* ``db-primary`` / ``export-only`` — DuckDB is sole operational authority
  (DQK-073).  Implicit ``records.jsonl``, ``.meta.json``, and JSON manifests
  are never operational truth; only explicit import/export and encrypted/CID
  raw-object references remain.

Secrets, signing payloads, and unrestricted raw bytes never enter DuckDB
(CID/digest refs only).  Quack publication receives redacted public ledger
analytics only.

Importing this module performs no network I/O.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable
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
    ensure_secret_safe,
)
from .protocols import OperationContext, RecordBatch


SINK_RECEIPT_SCHEMA_VERSION = "wallet-sink-receipt-v1"
RAW_PAYLOAD_SCHEMA_VERSION = "wallet-raw-payload-v1"
SHADOW_LEDGER_MODE_SCHEMA_VERSION = "wallet-shadow-ledger-v1"
AUTHORITY_LEDGER_MODE_SCHEMA_VERSION = "wallet-authority-ledger-v1"
EXPORT_OUTBOX_SCHEMA_VERSION = "wallet-export-outbox-v1"
PUBLIC_LEDGER_ANALYTICS_SCHEMA_VERSION = "wallet-public-ledger-analytics-v1"

# DQK-073 cutover pins.
WALLET_LEDGER_ONLY_OWNER_TASK: Final[str] = "DQK-073"
WALLET_LEDGER_ONLY_DEFAULT_MODE: Final[str] = "db-primary"
LEGACY_WALLET_LEDGER_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        "records.jsonl",
        "export-manifest.json",
        "export-partitions.json",
        "content.digest",
        "export.manifest.json",
        "records.meta.json",
    }
)
LEGACY_META_JSON_SUFFIX: Final[str] = ".meta.json"
NAMED_LEDGER_EXPORT_COMMANDS: Final[tuple[str, ...]] = (
    "export_ledger_jsonl",
    "export_ledger_parquet",
    "export_ledger_manifest",
    "drain_export_outbox",
    "import_legacy_bundle",
)
# Columns admitted into the Quack publication plane for redacted analytics.
PUBLIC_LEDGER_ANALYTICS_COLUMNS: Final[tuple[str, ...]] = (
    "scope",
    "record_type",
    "finality",
    "count",
    "min_sequence",
    "max_sequence",
    "chain_ref_id",
)

# Fact tables dual-written by the shadow/dual ledger projection (DQK-071/072).
_SHADOW_FACT_TABLES: Final = (
    "blocks",
    "transactions",
    "transfers",
    "utxos",
    "token_accounts",
    "contract_events",
)
_AUTHORITY_FACT_TABLES: Final = _SHADOW_FACT_TABLES

# Map LedgerRecord.record_type → catalog fact table.
_RECORD_TYPE_TO_TABLE: Mapping[str, str] = MappingProxyType(
    {
        "block": "blocks",
        "transaction": "transactions",
        "transfer": "transfers",
        "utxo": "utxos",
        "token_account": "token_accounts",
        "contract_event": "contract_events",
    }
)

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


class ImplicitLegacyLedgerWriteError(DatasetSinkError):
    """Raised when an implicit records.jsonl / .meta.json / manifest write is blocked."""

    def __init__(self, message: str, *, path: str = "", kind: str = "") -> None:
        super().__init__(message)
        self.path = path
        self.kind = kind


class LedgerFilesystemGuard:
    """Blocks implicit legacy ledger file writes under DuckDB-only authority.

    Explicit import/export paths obtain a short-lived permit via
    :meth:`permit_export` / :meth:`permit_import`.  All other attempts to write
    ``records.jsonl``, ``*.meta.json``, or JSON manifests fail closed.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else None
        self._lock = threading.RLock()
        self._export_permits: int = 0
        self._import_permits: int = 0

    @contextmanager
    def permit_export(self) -> Iterator[None]:
        with self._lock:
            self._export_permits += 1
        try:
            yield
        finally:
            with self._lock:
                self._export_permits = max(0, self._export_permits - 1)

    @contextmanager
    def permit_import(self) -> Iterator[None]:
        with self._lock:
            self._import_permits += 1
        try:
            yield
        finally:
            with self._lock:
                self._import_permits = max(0, self._import_permits - 1)

    def assert_write_allowed(self, path: Path | str, *, kind: str = "legacy") -> None:
        path = Path(path)
        if not self._is_guarded_path(path):
            return
        with self._lock:
            allowed = self._export_permits > 0 or self._import_permits > 0
        if allowed:
            return
        raise ImplicitLegacyLedgerWriteError(
            f"implicit {kind} write blocked by filesystem guard: {path} "
            f"(use explicit export/import; owner task {WALLET_LEDGER_ONLY_OWNER_TASK})",
            path=str(path),
            kind=kind,
        )

    def check_path_write(self, path: Path | str, *, kind: str = "legacy") -> None:
        self.assert_write_allowed(path, kind=kind)

    def _is_guarded_path(self, path: Path) -> bool:
        name = path.name
        if name in LEGACY_WALLET_LEDGER_FILENAMES:
            return True
        if name.endswith(LEGACY_META_JSON_SUFFIX):
            return True
        if name.endswith(".jsonl") and name.startswith("records"):
            return True
        if name in {"export-manifest.json", "export-partitions.json"}:
            return True
        if name.endswith(".manifest.json") or name.endswith("-manifest.json"):
            return True
        return False


def is_legacy_wallet_ledger_filename(name: str) -> bool:
    """Return whether *name* is a legacy wallet ledger authority surface file."""

    if name in LEGACY_WALLET_LEDGER_FILENAMES:
        return True
    if name.endswith(LEGACY_META_JSON_SUFFIX):
        return True
    if name.endswith(".jsonl") and name.startswith("records"):
        return True
    if name.endswith(".manifest.json") or name.endswith("-manifest.json"):
        return True
    return False


def legacy_wallet_ledger_files_present(root: str | Path) -> tuple[str, ...]:
    """Return sorted basenames of legacy ledger files found under *root*."""

    root_path = Path(root)
    if not root_path.exists():
        return ()
    found: list[str] = []
    for path in root_path.rglob("*"):
        if path.is_file() and is_legacy_wallet_ledger_filename(path.name):
            try:
                rel = str(path.relative_to(root_path))
            except ValueError:
                rel = path.name
            found.append(rel)
    return tuple(sorted(found))


def assert_legacy_wallet_ledger_files_absent(root: str | Path) -> None:
    """Fail closed when any legacy operational ledger file is present under *root*."""

    present = legacy_wallet_ledger_files_present(root)
    if present:
        raise DatasetSinkError(
            f"legacy wallet ledger files present under {root}: {list(present)}; "
            f"DuckDB-only authority ({WALLET_LEDGER_ONLY_OWNER_TASK}) requires them absent"
        )


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

    Under DuckDB-only authority (DQK-073), ``write_meta_json=False`` keeps
    operational identity on digest/CID refs only — ``.meta.json`` sidecars are
    never authority and are only materialised when an explicit export permit
    is active on the optional *filesystem_guard*.
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
        write_meta_json: bool = True,
        filesystem_guard: LedgerFilesystemGuard | None = None,
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
        self._write_meta_json = bool(write_meta_json)
        self._filesystem_guard = filesystem_guard
        self._total_bytes = 0
        self._object_count = 0
        self._known_digests: set[str] = set()
        # In-process meta for digest → media_type/cid when sidecars are disabled.
        self._meta: dict[str, dict[str, Any]] = {}
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
    def write_meta_json(self) -> bool:
        return self._write_meta_json

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def __len__(self) -> int:
        return self._object_count

    def _path_for(self, digest: str) -> Path:
        # Digest is "sha256:<hex>"; keep the algorithm prefix out of the name.
        safe = digest.replace(":", "_")
        return self._root / f"{safe}.bin"

    def _write_meta_sidecar(self, meta_path: Path, payload: StoredRawPayload) -> None:
        """Write optional ``.meta.json`` only when explicitly enabled / permitted."""

        if not self._write_meta_json:
            # In-process meta only — digest/CID remain the durable identity.
            self._meta[payload.digest] = payload.to_dict()
            return
        if self._filesystem_guard is not None:
            self._filesystem_guard.assert_write_allowed(
                meta_path, kind="raw_payload_meta"
            )
        _restrictive_write_bytes(meta_path, canonical_json_bytes(payload.to_dict()))
        self._meta[payload.digest] = payload.to_dict()

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
        meta_path = path.with_suffix(LEGACY_META_JSON_SUFFIX)
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
        # Body is the content-addressed object; meta is never operational authority.
        _restrictive_write_bytes(path, payload.body)
        try:
            self._write_meta_sidecar(meta_path, payload)
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
        # Prefer in-process meta (DuckDB-only path); fall back to optional sidecar.
        cached = self._meta.get(digest)
        if isinstance(cached, Mapping):
            media_type = str(cached.get("media_type") or media_type)
            cid = cached.get("cid")
        else:
            meta_path = path.with_suffix(LEGACY_META_JSON_SUFFIX)
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


class ShadowLedgerMode(StrEnum):
    """Authority mode for dual-written wallet ledger sinks (DQK-071..073).

    * ``off`` — JSONL / in-memory only (legacy unit-test path).
    * ``shadow`` — dual-write into DuckDB; JSONL / in-memory remain authority
      (DQK-071).
    * ``dual`` — dual writes with DuckDB as ledger/checkpoint authority and a
      crash-recoverable export outbox for JSONL/Parquet/Arrow/CAR (DQK-072).
    * ``db-primary`` — DuckDB is sole authority; file formats are outbox exports
      only and never re-admitted as operational truth (DQK-072/073).
    * ``export-only`` — post-promotion greenfield state (DQK-073): DuckDB sole
      authority; implicit ``records.jsonl`` / ``.meta.json`` / JSON manifests
      are blocked; only named export/import commands materialise files.
    """

    OFF = "off"
    SHADOW = "shadow"
    DUAL = "dual"
    DB_PRIMARY = "db-primary"
    EXPORT_ONLY = "export-only"

    @classmethod
    def parse(cls, value: "ShadowLedgerMode | str | None") -> "ShadowLedgerMode":
        if value is None:
            return cls.OFF
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower().replace("_", "-")
        aliases = {
            "off": cls.OFF,
            "none": cls.OFF,
            "legacy": cls.OFF,
            "shadow": cls.SHADOW,
            "dual": cls.DUAL,
            "dual-write": cls.DUAL,
            "dualwrite": cls.DUAL,
            "db-primary": cls.DB_PRIMARY,
            "dbprimary": cls.DB_PRIMARY,
            "duckdb-primary": cls.DB_PRIMARY,
            "export-only": cls.EXPORT_ONLY,
            "exportonly": cls.EXPORT_ONLY,
            "export_only": cls.EXPORT_ONLY,
            "authority": cls.DUAL,
        }
        if text not in aliases:
            raise InvalidRequestError(
                f"unknown ledger authority mode {value!r}; expected one of "
                f"{sorted({m.value for m in cls})}"
            )
        return aliases[text]

    @property
    def duckdb_is_authority(self) -> bool:
        """True when DuckDB is the operational truth for ledger rows."""

        return self in {
            ShadowLedgerMode.DUAL,
            ShadowLedgerMode.DB_PRIMARY,
            ShadowLedgerMode.EXPORT_ONLY,
        }

    @property
    def dual_writes(self) -> bool:
        """True when both DuckDB and a legacy projection path are active."""

        return self in {
            ShadowLedgerMode.SHADOW,
            ShadowLedgerMode.DUAL,
            ShadowLedgerMode.DB_PRIMARY,
            ShadowLedgerMode.EXPORT_ONLY,
        }

    @property
    def blocks_implicit_legacy_files(self) -> bool:
        """True when implicit records.jsonl / meta / manifest writes are blocked."""

        return self in {
            ShadowLedgerMode.DB_PRIMARY,
            ShadowLedgerMode.EXPORT_ONLY,
        }

    @property
    def memory_is_authority(self) -> bool:
        """True when the in-memory / JSONL projection is operational authority."""

        return self in {ShadowLedgerMode.OFF, ShadowLedgerMode.SHADOW}


class ExportOutboxStatus(StrEnum):
    """Lifecycle for outbox-driven JSONL/Parquet/Arrow/CAR exports."""

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExportOutboxEntry:
    """One durable export job drained after DuckDB authority commit (DQK-072)."""

    outbox_id: str
    commit_id: str
    scope: str
    formats: tuple[str, ...]
    record_ids: tuple[str, ...]
    content_digest: str
    status: ExportOutboxStatus = ExportOutboxStatus.PENDING
    output_dir: str | None = None
    error: str | None = None
    schema_version: str = field(default=EXPORT_OUTBOX_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outbox_id", _required_str(self.outbox_id, "outbox_id"))
        object.__setattr__(self, "commit_id", _required_str(self.commit_id, "commit_id"))
        object.__setattr__(self, "scope", _required_str(self.scope, "scope"))
        object.__setattr__(self, "formats", tuple(self.formats))
        object.__setattr__(self, "record_ids", tuple(self.record_ids))
        object.__setattr__(
            self, "content_digest", _required_str(self.content_digest, "content_digest")
        )
        if not isinstance(self.status, ExportOutboxStatus):
            object.__setattr__(
                self, "status", ExportOutboxStatus(str(self.status))
            )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "outbox_id": self.outbox_id,
            "commit_id": self.commit_id,
            "scope": self.scope,
            "formats": list(self.formats),
            "record_ids": list(self.record_ids),
            "content_digest": self.content_digest,
            "status": self.status.value,
        }
        if self.output_dir is not None:
            result["output_dir"] = self.output_dir
        if self.error is not None:
            result["error"] = self.error
        return result

    def with_status(
        self,
        status: ExportOutboxStatus,
        *,
        error: str | None = None,
        output_dir: str | None = None,
    ) -> "ExportOutboxEntry":
        return ExportOutboxEntry(
            outbox_id=self.outbox_id,
            commit_id=self.commit_id,
            scope=self.scope,
            formats=self.formats,
            record_ids=self.record_ids,
            content_digest=self.content_digest,
            status=status,
            output_dir=output_dir if output_dir is not None else self.output_dir,
            error=error,
        )


class ExportOutbox:
    """Process-local export outbox for dual-mode authority cutover (DQK-072).

    Entries are enqueued only after a successful DuckDB authority commit so
    kill/restart at export boundaries can drain idempotently without inventing
    or losing ledger rows.  File formats are never operational authority.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ExportOutboxEntry] = {}
        self._order: list[str] = []

    def __len__(self) -> int:
        return len(self._entries)

    def enqueue(self, entry: ExportOutboxEntry) -> ExportOutboxEntry:
        if not isinstance(entry, ExportOutboxEntry):
            raise InvalidRequestError("entry must be an ExportOutboxEntry")
        existing = self._entries.get(entry.outbox_id)
        if existing is not None:
            # Idempotent: identical commit+digest is a no-op; conflict fails closed.
            if (
                existing.commit_id != entry.commit_id
                or existing.content_digest != entry.content_digest
            ):
                raise DatasetSinkError(
                    f"export outbox id {entry.outbox_id!r} reused with different payload"
                )
            return existing
        self._entries[entry.outbox_id] = entry
        self._order.append(entry.outbox_id)
        return entry

    def get(self, outbox_id: str) -> ExportOutboxEntry | None:
        return self._entries.get(outbox_id)

    def pending(self) -> tuple[ExportOutboxEntry, ...]:
        return tuple(
            self._entries[oid]
            for oid in self._order
            if self._entries[oid].status
            in {ExportOutboxStatus.PENDING, ExportOutboxStatus.IN_FLIGHT, ExportOutboxStatus.FAILED}
        )

    def completed(self) -> tuple[ExportOutboxEntry, ...]:
        return tuple(
            self._entries[oid]
            for oid in self._order
            if self._entries[oid].status is ExportOutboxStatus.COMPLETED
        )

    def mark(
        self,
        outbox_id: str,
        status: ExportOutboxStatus,
        *,
        error: str | None = None,
        output_dir: str | None = None,
    ) -> ExportOutboxEntry:
        current = self._entries.get(outbox_id)
        if current is None:
            raise DatasetSinkError(f"unknown export outbox id {outbox_id!r}")
        updated = current.with_status(status, error=error, output_dir=output_dir)
        self._entries[outbox_id] = updated
        return updated

    def list_entries(self) -> tuple[ExportOutboxEntry, ...]:
        return tuple(self._entries[oid] for oid in self._order)


@dataclass(frozen=True, slots=True)
class ShadowWriteReceipt:
    """Accounting for one dual-written shadow batch (parity / diagnostics)."""

    write_id: str
    accepted_count: int
    duplicate_count: int
    content_digest: str
    mode: str = ShadowLedgerMode.SHADOW.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "write_id": self.write_id,
            "accepted_count": self.accepted_count,
            "duplicate_count": self.duplicate_count,
            "content_digest": self.content_digest,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class ShadowParityReport:
    """JSONL vs DuckDB projection parity for one sink commit window."""

    matched_record_ids: tuple[str, ...]
    missing_in_db: tuple[str, ...]
    missing_in_jsonl: tuple[str, ...]
    mismatched: tuple[str, ...]
    mode: str = ShadowLedgerMode.SHADOW.value
    schema_version: str = field(
        default=SHADOW_LEDGER_MODE_SCHEMA_VERSION, init=False
    )

    @property
    def matched(self) -> bool:
        return (
            not self.missing_in_db
            and not self.missing_in_jsonl
            and not self.mismatched
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "matched": self.matched,
            "matched_record_ids": list(self.matched_record_ids),
            "missing_in_db": list(self.missing_in_db),
            "missing_in_jsonl": list(self.missing_in_jsonl),
            "mismatched": list(self.mismatched),
        }


class StreamingDatasetSink:
    """Reference :class:`~protocols.DatasetSink` with transactional staging.

    Records are staged in memory (optionally flushed to a directory on commit).
    Deduplication is by stable ``record_id`` so duplicate and out-of-order pages
    never produce multiple durable rows.  :meth:`abort` discards the stage and
    must be used on partial/cancelled runs so checkpoints are not advanced.

    When *shadow_store* is provided (or *shadow* is true and a store is
    constructed), every :meth:`write` / :meth:`commit` / :meth:`abort` is also
    applied to the DuckDB ledger store (DQK-071 shadow / DQK-072 dual).

    Authority:

    * ``shadow`` — in-memory / JSONL remains authority; DuckDB is dual-written.
    * ``dual`` — DuckDB is authority; JSONL and other file formats are projected
      only through the export outbox after a durable DuckDB commit.
    * ``db-primary`` / ``export-only`` (DQK-073) — DuckDB is sole authority.
      Implicit ``records.jsonl``, ``.meta.json``, and JSON manifests are blocked;
      only named export/import commands materialise files.  Resume rehydrates
      exclusively from DuckDB.
    """

    def __init__(
        self,
        *,
        scope: str,
        output_dir: str | Path | None = None,
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.OMITTED,
        shadow_store: Any | None = None,
        shadow: bool | Any | None = None,
        authority_mode: ShadowLedgerMode | str | None = None,
        export_formats: Sequence[str] = (),
        export_outbox: ExportOutbox | None = None,
        filesystem_guard: LedgerFilesystemGuard | None = None,
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
        self._shadow_write_receipts: list[ShadowWriteReceipt] = []
        self._last_parity: ShadowParityReport | None = None
        self._export_formats = tuple(str(fmt) for fmt in export_formats)
        self._export_outbox = export_outbox if export_outbox is not None else ExportOutbox()
        self._crash_boundary: str | None = None
        self._named_export_invocations: list[str] = []
        self._shadow = _resolve_shadow_store(
            shadow_store=shadow_store,
            shadow=shadow,
            scope=self._scope,
        )
        self._shadow_mode = _resolve_ledger_mode(
            authority_mode=authority_mode,
            shadow=shadow,
            has_store=self._shadow is not None,
        )
        if self._shadow_mode.dual_writes and self._shadow is None:
            # Dual / shadow / db-primary without a store opens a process-local
            # pure-Python DuckDB wallet store so authority is never file-only.
            self._shadow = _open_default_shadow_store(scope=self._scope)
        self._filesystem_guard = (
            filesystem_guard
            if filesystem_guard is not None
            else LedgerFilesystemGuard(self._output_dir)
        )

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def raw_payload_policy(self) -> RawPayloadPolicy:
        return self._raw_payload_policy

    @property
    def shadow_store(self) -> Any | None:
        """Injected DuckDB wallet store used for dual-write / dual-mode authority."""

        return self._shadow

    @property
    def authority_store(self) -> Any | None:
        """DuckDB store when it is operational authority (dual / db-primary)."""

        if self._shadow_mode.duckdb_is_authority:
            return self._shadow
        return None

    @property
    def shadow_mode(self) -> ShadowLedgerMode:
        return self._shadow_mode

    @property
    def authority_mode(self) -> ShadowLedgerMode:
        """Alias for :attr:`shadow_mode` (DQK-072 dual-mode naming)."""

        return self._shadow_mode

    @property
    def export_outbox(self) -> ExportOutbox:
        return self._export_outbox

    @property
    def filesystem_guard(self) -> LedgerFilesystemGuard:
        return self._filesystem_guard

    @property
    def memory_is_authority(self) -> bool:
        return self._shadow_mode.memory_is_authority

    @property
    def owner_task_id(self) -> str | None:
        if self._shadow_mode.blocks_implicit_legacy_files:
            return WALLET_LEDGER_ONLY_OWNER_TASK
        return None

    @property
    def shadow_write_receipts(self) -> tuple[ShadowWriteReceipt, ...]:
        return tuple(self._shadow_write_receipts)

    def promote_to_db_primary(self) -> ShadowLedgerMode:
        """Promote dual → db-primary (DuckDB sole authority; files export-only)."""

        if self._shadow is None:
            raise DatasetSinkError("cannot promote without a DuckDB store")
        if self._shadow_mode is ShadowLedgerMode.SHADOW:
            self._shadow_mode = ShadowLedgerMode.DUAL
        if self._shadow_mode is ShadowLedgerMode.EXPORT_ONLY:
            return self._shadow_mode
        self._shadow_mode = ShadowLedgerMode.DB_PRIMARY
        return self._shadow_mode

    def promote_to_export_only(self) -> ShadowLedgerMode:
        """Promote to export-only (DQK-073 greenfield; no implicit legacy files)."""

        if self._shadow is None:
            raise DatasetSinkError("cannot promote without a DuckDB store")
        self._shadow_mode = ShadowLedgerMode.EXPORT_ONLY
        return self._shadow_mode

    def named_export_invocations(self) -> tuple[str, ...]:
        return tuple(self._named_export_invocations)

    def assert_json_write_allowed(
        self, path: str | Path, *, kind: str = "legacy"
    ) -> None:
        """Fail closed on implicit legacy ledger file writes (DQK-073)."""

        if not self._shadow_mode.blocks_implicit_legacy_files:
            return
        self._filesystem_guard.assert_write_allowed(path, kind=kind)

    @property
    def last_parity(self) -> ShadowParityReport | None:
        return self._last_parity

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

    def set_crash_boundary(self, boundary: str | None) -> None:
        """Inject a crash at a named boundary (tests / chaos only).

        Supported boundaries: ``before_page_commit``, ``before_block_commit``,
        ``before_export_outbox``, ``after_db_commit``, ``before_jsonl_flush``.
        The boundary fires once then clears so resume can complete.
        """

        self._crash_boundary = boundary

    def _maybe_crash(self, boundary: str) -> None:
        if self._crash_boundary is not None and self._crash_boundary == boundary:
            self._crash_boundary = None
            raise DatasetSinkError(f"crash injected at boundary {boundary!r}")

    async def write(
        self,
        batch: RecordBatch,
        *,
        context: OperationContext,
    ) -> BatchWriteReceipt:
        """Stage one bounded batch, dropping already-seen record identities.

        Dual / db-primary mode stages DuckDB first (authority), then mirrors
        into the in-memory working set so kill/restart recovers from DuckDB.
        Shadow mode stages memory first and dual-writes DuckDB (DQK-071).
        """

        context.check_active()
        if self._aborted:
            raise DatasetSinkError("cannot write to an aborted dataset sink")
        if not isinstance(batch, RecordBatch):
            raise DatasetSinkError("batch must be a RecordBatch")
        batch.enforce(context.limits)

        # Dual-mode: DuckDB is authority — write there first so a crash before
        # memory promotion still leaves a recoverable stage or durable row set.
        authority_first = (
            self._shadow_mode.duckdb_is_authority and self._shadow is not None
        )
        db_receipt: BatchWriteReceipt | None = None
        if authority_first:
            try:
                db_receipt = await self._shadow.write(batch, context=context)
            except Exception as exc:
                raise DatasetSinkError(
                    f"authority ledger write failed: {exc}"
                ) from exc
            self._shadow_write_receipts.append(
                ShadowWriteReceipt(
                    write_id=str(getattr(db_receipt, "write_id", "write:db")),
                    accepted_count=int(
                        getattr(db_receipt, "accepted_count", 0) or 0
                    ),
                    duplicate_count=int(
                        getattr(db_receipt, "duplicate_count", 0) or 0
                    ),
                    content_digest=str(
                        getattr(db_receipt, "content_digest", content_digest([]))
                    ),
                    mode=self._shadow_mode.value,
                )
            )

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
        write_id = (
            str(getattr(db_receipt, "write_id", None))
            if db_receipt is not None
            else f"write:{uuid4().hex}"
        )
        receipt = BatchWriteReceipt(
            write_id=write_id or f"write:{uuid4().hex}",
            accepted_count=len(accepted),
            duplicate_count=duplicate,
            out_of_order_count=out_of_order,
            byte_count=len(encoded) + max(0, batch.response_bytes),
            record_ids=tuple(accepted),
            content_digest=content_digest(payloads),
        )
        # Shadow mode: dual-write DuckDB after memory staging (DQK-071).
        if not authority_first:
            await self._shadow_write(batch, context=context, authority=receipt)
        return receipt

    async def _shadow_write(
        self,
        batch: RecordBatch,
        *,
        context: OperationContext,
        authority: BatchWriteReceipt,
    ) -> None:
        """Mirror a staged batch into the DuckDB wallet store when enabled."""

        if self._shadow is None:
            return
        try:
            shadow_receipt = await self._shadow.write(batch, context=context)
        except Exception as exc:
            raise DatasetSinkError(
                f"shadow ledger write failed: {exc}"
            ) from exc
        accepted = int(getattr(shadow_receipt, "accepted_count", 0) or 0)
        duplicate = int(getattr(shadow_receipt, "duplicate_count", 0) or 0)
        # Authority and shadow may diverge on accepted_count when one side has
        # already seen identities (resume).  Track both for parity diagnostics.
        self._shadow_write_receipts.append(
            ShadowWriteReceipt(
                write_id=str(
                    getattr(shadow_receipt, "write_id", authority.write_id)
                ),
                accepted_count=accepted,
                duplicate_count=duplicate,
                content_digest=str(
                    getattr(
                        shadow_receipt,
                        "content_digest",
                        authority.content_digest,
                    )
                ),
                mode=self._shadow_mode.value,
            )
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

        Dual / db-primary (DQK-072): DuckDB commits first (authority).  JSONL
        flush and multi-format exports are enqueued on the export outbox and
        only materialize after the authority commit succeeds.  Shadow mode
        (DQK-071) still commits memory/JSONL first, then DuckDB.
        """

        context.check_active()
        if self._aborted:
            raise DatasetSinkError("cannot commit an aborted dataset sink")

        export_manifest: ExportManifest | None = None
        if manifest is not None and not isinstance(manifest, ExportManifest):
            raise DatasetSinkError("manifest must be an ExportManifest or None")
        if isinstance(manifest, ExportManifest):
            export_manifest = manifest

        authority_first = (
            self._shadow_mode.duckdb_is_authority and self._shadow is not None
        )

        if authority_first:
            self._maybe_crash("before_page_commit")
            self._maybe_crash("before_block_commit")
            try:
                db_receipt = await self._shadow.commit(manifest, context=context)
            except Exception as exc:
                raise DatasetSinkError(
                    f"authority ledger commit failed: {exc}"
                ) from exc
            self._maybe_crash("after_db_commit")
            commit_id = str(
                getattr(db_receipt, "commit_id", None) or f"commit:{uuid4().hex}"
            )
        else:
            commit_id = f"commit:{uuid4().hex}"

        promoting = list(self._staged)
        self._committed.extend(promoting)
        self._staged.clear()
        self._commit_count += 1

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

        # Shadow mode: flush JSONL as authority surface immediately.
        # Dual mode: JSONL is outbox-driven (not authority).
        if self._output_dir is not None and not authority_first:
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

        if not authority_first and self._shadow is not None:
            try:
                await self._shadow.commit(manifest, context=context)
            except Exception as exc:
                raise DatasetSinkError(
                    f"shadow ledger commit failed: {exc}"
                ) from exc
            self._last_parity = compare_jsonl_db_projections(
                self.committed_records(),
                self._shadow,
            )
            if not self._last_parity.matched:
                raise DatasetSinkError(
                    "shadow ledger parity mismatch after commit: "
                    f"missing_in_db={list(self._last_parity.missing_in_db)} "
                    f"mismatched={list(self._last_parity.mismatched)}"
                )
        elif authority_first and self._shadow is not None:
            # Dual mode: parity still required between memory working set and DB.
            self._last_parity = compare_jsonl_db_projections(
                self.committed_records(),
                self._shadow,
            )
            if not self._last_parity.matched:
                raise DatasetSinkError(
                    "authority ledger parity mismatch after commit: "
                    f"missing_in_db={list(self._last_parity.missing_in_db)} "
                    f"mismatched={list(self._last_parity.mismatched)}"
                )
            self._enqueue_export_outbox(receipt)

        return receipt

    def _enqueue_export_outbox(self, receipt: SinkCommitReceipt) -> ExportOutboxEntry:
        """Enqueue outbox-driven export after a durable DuckDB commit.

        Under db-primary / export-only (DQK-073) formats are never implied from
        ``output_dir``: callers must pass *export_formats* explicitly so
        ``records.jsonl`` is not materialised by accident.
        """

        self._maybe_crash("before_export_outbox")
        if self._shadow_mode.blocks_implicit_legacy_files:
            formats = self._export_formats  # explicit only; may be empty
            if not formats:
                # No outbox entry when no explicit formats — DuckDB is enough.
                return ExportOutboxEntry(
                    outbox_id=f"outbox:{receipt.commit_id}:noop",
                    commit_id=receipt.commit_id,
                    scope=receipt.scope,
                    formats=(),
                    record_ids=tuple(item.record_id for item in self._committed),
                    content_digest=receipt.content_digest,
                    status=ExportOutboxStatus.COMPLETED,
                    output_dir=(
                        str(self._output_dir) if self._output_dir is not None else None
                    ),
                )
        else:
            formats = self._export_formats or ("jsonl",)
            if self._output_dir is not None and "jsonl" not in formats:
                formats = ("jsonl",) + tuple(formats)
        entry = ExportOutboxEntry(
            outbox_id=f"outbox:{receipt.commit_id}",
            commit_id=receipt.commit_id,
            scope=receipt.scope,
            formats=tuple(formats),
            record_ids=tuple(item.record_id for item in self._committed),
            content_digest=receipt.content_digest,
            status=ExportOutboxStatus.PENDING,
            output_dir=str(self._output_dir) if self._output_dir is not None else None,
        )
        return self._export_outbox.enqueue(entry)

    def _flush_committed_jsonl(self, digest: str) -> Path:
        assert self._output_dir is not None
        self._maybe_crash("before_jsonl_flush")
        path = self._output_dir / "records.jsonl"
        if self._shadow_mode.blocks_implicit_legacy_files:
            raise ImplicitLegacyLedgerWriteError(
                f"implicit records.jsonl flush blocked under "
                f"{self._shadow_mode.value} (DQK-073); use drain_export_outbox "
                f"or export_ledger_jsonl",
                path=str(path),
                kind="records_jsonl",
            )
        tmp = path.with_suffix(".jsonl.tmp")
        lines = [
            canonical_json_bytes(item.payload).decode("utf-8")
            for item in self._committed
        ]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(path)
        (self._output_dir / "content.digest").write_text(digest + "\n", encoding="utf-8")
        return path

    def drain_export_outbox(
        self,
        *,
        formats: Sequence[str] | None = None,
        output_dir: str | Path | None = None,
    ) -> tuple[ExportOutboxEntry, ...]:
        """Materialize pending outbox exports from DuckDB authority rows.

        Idempotent: completed entries are skipped.  File formats never become
        operational authority — they are one-way projections of DuckDB state.
        This is a **named export** command (DQK-073).
        """

        from .export import drain_wallet_export_outbox

        out_dir = Path(output_dir) if output_dir is not None else self._output_dir
        self._named_export_invocations.append("drain_export_outbox")
        if self._shadow_mode.blocks_implicit_legacy_files and out_dir is not None:
            with self._filesystem_guard.permit_export():
                return drain_wallet_export_outbox(
                    self,
                    formats=formats,
                    output_dir=out_dir,
                )
        return drain_wallet_export_outbox(
            self,
            formats=formats,
            output_dir=out_dir,
        )

    def recover_authority(self) -> Mapping[str, Any]:
        """Recover DuckDB open/committing stages and rehydrate the working set.

        Safe at page/block/reorg/export boundaries: open stages abort (no
        durable mutation), committing stages finalize with INSERT-OR-IGNORE,
        and the in-memory projection is rebuilt from durable fact tables so
        resume neither loses nor duplicates committed records.
        """

        report: dict[str, Any] = {
            "mode": self._shadow_mode.value,
            "recovered": False,
            "record_count": self.committed_count,
        }
        if self._shadow is None:
            return MappingProxyType(report)
        recover = getattr(self._shadow, "recover", None)
        recovery: Mapping[str, Any] = {}
        if callable(recover):
            recovery = dict(recover())
            report["recovery"] = dict(recovery)
            report["recovered"] = True
        if self._shadow_mode.duckdb_is_authority:
            rehydrated = self.rehydrate_from_authority()
            report["record_count"] = rehydrated
            report["rehydrated"] = True
        # Re-open for resume after recover aborted open stages.
        self._aborted = False
        self._staged.clear()
        reset = getattr(self._shadow, "reset_for_resume", None)
        if callable(reset):
            reset()
        return MappingProxyType(report)

    def rehydrate_from_authority(self) -> int:
        """Rebuild in-memory committed rows from DuckDB fact tables."""

        if self._shadow is None:
            return len(self._committed)
        list_records = getattr(self._shadow, "list_records", None)
        if not callable(list_records):
            return len(self._committed)
        rows_by_id: dict[str, dict[str, Any]] = {}
        for table in _AUTHORITY_FACT_TABLES:
            try:
                rows = list_records(table)
            except Exception:
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                rid = row.get("record_id")
                if isinstance(rid, str) and rid.strip() and rid not in rows_by_id:
                    rows_by_id[rid] = dict(row)
        # Preserve prior payload_json shapes when present; otherwise store the
        # typed catalog row as the working-set projection.
        rebuilt: list[_StagedRecord] = []
        seen: set[str] = set()
        order = 0
        for rid, row in sorted(rows_by_id.items()):
            seen.add(rid)
            finality_raw = row.get("finality")
            try:
                finality = (
                    finality_raw
                    if isinstance(finality_raw, Finality)
                    else Finality(str(finality_raw or Finality.UNKNOWN.value))
                )
            except Exception:
                finality = Finality.UNKNOWN
            sequence = row.get("sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool):
                sequence = None
            rebuilt.append(
                _StagedRecord(
                    record_id=rid,
                    payload=dict(row),
                    finality=finality,
                    sequence=sequence,
                    order=order,
                )
            )
            order += 1
        self._committed = rebuilt
        self._seen = seen
        self._staged.clear()
        sequences = [item.sequence for item in rebuilt if item.sequence is not None]
        self._last_sequence = max(sequences) if sequences else None
        return len(rebuilt)

    def authority_record_ids(self) -> frozenset[str]:
        """Return durable record identities from DuckDB when authoritative."""

        if self._shadow is None or not self._shadow_mode.duckdb_is_authority:
            return frozenset(self._seen)
        list_records = getattr(self._shadow, "list_records", None)
        if not callable(list_records):
            return frozenset(self._seen)
        ids: set[str] = set()
        for table in _AUTHORITY_FACT_TABLES:
            try:
                rows = list_records(table)
            except Exception:
                continue
            for row in rows:
                if isinstance(row, Mapping):
                    rid = row.get("record_id")
                    if isinstance(rid, str) and rid.strip():
                        ids.add(rid)
        return frozenset(ids)

    async def abort(self, *, context: OperationContext) -> None:
        """Discard uncommitted staged data without inventing a sink commit.

        Abort is a cleanup path and must succeed even when the caller has
        already cancelled the operation; it never advances durable state.
        Dual-mode aborts DuckDB open stages first (authority), then memory.
        """

        # Deliberately skip cancellation checks so partial/cancelled runs can
        # always drop staged data without raising OperationCancelledError.
        _ = context
        if self._shadow is not None and self._shadow_mode.duckdb_is_authority:
            try:
                await self._shadow.abort(context=context)
            except Exception:
                pass
        self._staged.clear()
        self._aborted = True
        if self._shadow is not None and not self._shadow_mode.duckdb_is_authority:
            try:
                await self._shadow.abort(context=context)
            except Exception:
                # Abort must not invent sink commits; best-effort shadow cleanup.
                pass

    def reset_for_resume(self) -> None:
        """Clear abort state so a resumed pipeline can stage further batches.

        Committed rows and the seen-identity set are retained so resume never
        re-emits already durable records.  Dual mode rehydrates seen ids from
        DuckDB authority when available.
        """

        self._aborted = False
        self._staged.clear()
        if self._shadow is not None:
            reset = getattr(self._shadow, "reset_for_resume", None)
            if callable(reset):
                reset()
            if self._shadow_mode.duckdb_is_authority:
                # Keep memory aligned with durable authority after resume.
                self.rehydrate_from_authority()

    def jsonl_path(self) -> Path | None:
        """Return the durable JSONL path when *output_dir* is configured."""

        if self._output_dir is None:
            return None
        return self._output_dir / "records.jsonl"

    def read_jsonl_records(self) -> tuple[dict[str, Any], ...]:
        """Load committed JSONL projections (export surface; dual-mode outbox).

        Dual / db-primary / export-only: JSONL is **not** authority.  When the
        outbox has not been drained yet, return the in-memory projection of
        DuckDB authority so parity checks remain available without re-admitting
        files as truth.  Under DuckDB-only modes, file reads are treated as
        explicit export inspection only.
        """

        path = self.jsonl_path()
        if path is not None and path.is_file():
            if self._shadow_mode.duckdb_is_authority:
                # Prefer authority projection; JSONL is export/compatibility only.
                return self.committed_records()
            rows: list[dict[str, Any]] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text:
                    continue
                import json

                payload = json.loads(text)
                if isinstance(payload, dict):
                    rows.append(payload)
            return tuple(rows)
        return self.committed_records()

    def reject_legacy_file_authority(
        self, *, artifact: str = "records.jsonl"
    ) -> None:
        """Fail closed when a caller attempts to treat a legacy file as truth."""

        raise DatasetSinkError(
            f"legacy file {artifact!r} is not operational authority under "
            f"{self._shadow_mode.value} ({WALLET_LEDGER_ONLY_OWNER_TASK}); "
            "resume from DuckDB and use named export/import only"
        )


def _resolve_shadow_store(
    *,
    shadow_store: Any | None,
    shadow: bool | Any | None,
    scope: str,
) -> Any | None:
    """Normalize *shadow* / *shadow_store* constructor options.

    * ``shadow_store=<store>`` — use the injected DuckDB wallet store.
    * ``shadow=True`` / ``shadow=None`` with no store — open a process-local
      pure-Python DuckDB wallet store (no network, no file I/O).
    * ``shadow=False`` — disable dual-write.
    * ``shadow=<store>`` — treat a non-bool as an explicit store instance.
    """

    if shadow_store is not None:
        return shadow_store
    if shadow is False:
        return None
    if shadow is True or shadow is None:
        # Default remains OFF when callers omit both kwargs so unit tests that
        # only pass scope= stay JSONL-only.  Explicit shadow=True enables dual
        # write; pipeline/API/registry pass a store or shadow=True.
        if shadow is True:
            return _open_default_shadow_store(scope=scope)
        return None
    # Non-bool *shadow* is treated as an injected store instance.
    return shadow


def _resolve_ledger_mode(
    *,
    authority_mode: ShadowLedgerMode | str | None,
    shadow: bool | Any | None,
    has_store: bool,
) -> ShadowLedgerMode:
    """Resolve ledger authority mode for a sink constructor."""

    if authority_mode is not None:
        return ShadowLedgerMode.parse(authority_mode)
    if shadow is False:
        return ShadowLedgerMode.OFF
    if has_store or shadow is True:
        # Explicit store without mode defaults to shadow (DQK-071) so existing
        # callers keep memory/JSONL authority until they opt into dual mode.
        return ShadowLedgerMode.SHADOW
    return ShadowLedgerMode.OFF


def _open_default_shadow_store(*, scope: str) -> Any:
    """Lazily construct a pure-Python DuckDB wallet store for dual-write."""

    # Lazy import avoids circular dependency (duckdb_storage imports storage).
    from .duckdb_storage import open_wallet_store

    return open_wallet_store(scope=scope, auto_recover=True)


def fact_table_for_record(record: object) -> str | None:
    """Return the catalog fact table for a ledger record or mapping."""

    if isinstance(record, LedgerRecord):
        return _RECORD_TYPE_TO_TABLE.get(record.record_type)
    if isinstance(record, Mapping):
        record_type = record.get("record_type")
        if isinstance(record_type, str):
            return _RECORD_TYPE_TO_TABLE.get(record_type)
        table = record.get("table")
        if isinstance(table, str) and table in _SHADOW_FACT_TABLES:
            return table
    record_type_attr = getattr(record, "record_type", None)
    if isinstance(record_type_attr, str):
        return _RECORD_TYPE_TO_TABLE.get(record_type_attr)
    return None


def compare_jsonl_db_projections(
    jsonl_records: Sequence[Mapping[str, Any]] | Sequence[object],
    shadow_store: Any,
) -> ShadowParityReport:
    """Compare JSONL authority payloads with DuckDB fact-table projections.

    Matching is by deterministic ``record_id``.  Finality and chain binding
    fields must agree when present on both sides.  Secrets and raw payload
    bodies are never loaded from DuckDB — only public fact columns.
    """

    if shadow_store is None:
        raise InvalidRequestError("shadow_store is required for parity comparison")

    jsonl_by_id: dict[str, dict[str, Any]] = {}
    for record in jsonl_records:
        payload = record_as_dict(record)
        record_id = record_identity(payload)
        jsonl_by_id[record_id] = payload

    db_by_id: dict[str, Mapping[str, Any]] = {}
    list_records = getattr(shadow_store, "list_records", None)
    get_record = getattr(shadow_store, "get_record", None)
    if callable(list_records):
        for table in _SHADOW_FACT_TABLES:
            try:
                rows = list_records(table)
            except Exception:
                continue
            for row in rows:
                rid = row.get("record_id") if isinstance(row, Mapping) else None
                if isinstance(rid, str) and rid.strip():
                    db_by_id[rid] = row
    elif callable(get_record):
        for record_id in jsonl_by_id:
            row = get_record(record_id)
            if row is not None:
                db_by_id[record_id] = row

    matched: list[str] = []
    missing_in_db: list[str] = []
    mismatched: list[str] = []
    for record_id, payload in sorted(jsonl_by_id.items()):
        row = db_by_id.get(record_id)
        if row is None:
            missing_in_db.append(record_id)
            continue
        if not _projection_fields_match(payload, row):
            mismatched.append(record_id)
            continue
        matched.append(record_id)

    missing_in_jsonl = tuple(
        sorted(rid for rid in db_by_id if rid not in jsonl_by_id)
    )
    return ShadowParityReport(
        matched_record_ids=tuple(matched),
        missing_in_db=tuple(missing_in_db),
        missing_in_jsonl=missing_in_jsonl,
        mismatched=tuple(mismatched),
    )


def _projection_fields_match(
    jsonl: Mapping[str, Any], db_row: Mapping[str, Any]
) -> bool:
    """True when durable identity and finality fields agree across surfaces."""

    if str(jsonl.get("record_id") or "") != str(db_row.get("record_id") or ""):
        return False
    # Finality must agree when both sides expose it.
    j_fin = jsonl.get("finality")
    d_fin = db_row.get("finality")
    if j_fin is not None and d_fin is not None:
        j_val = j_fin.value if isinstance(j_fin, Finality) else str(j_fin)
        if str(j_val) != str(d_fin):
            return False
    # Chain binding: JSONL nests chain; DB uses chain_ref_id.
    chain = jsonl.get("chain")
    if isinstance(chain, Mapping) and db_row.get("chain_ref_id"):
        # Prefer explicit chain_ref_id on JSONL when present; otherwise derive.
        j_ref = chain.get("chain_ref_id")
        if isinstance(j_ref, str) and j_ref and j_ref != db_row.get("chain_ref_id"):
            return False
    # Sequence / block hash anchors when present on both sides.
    position = jsonl.get("ledger_position")
    if isinstance(position, Mapping):
        seq = position.get("sequence")
        if (
            seq is not None
            and db_row.get("sequence") is not None
            and int(seq) != int(db_row["sequence"])
        ):
            return False
        block_hash = position.get("hash")
        if (
            isinstance(block_hash, str)
            and isinstance(db_row.get("block_hash"), str)
            and block_hash
            and db_row["block_hash"]
            and block_hash != db_row["block_hash"]
        ):
            # Transaction/transfer rows may use ledger hash without block_hash.
            if "block_hash" in db_row and db_row.get("block_hash") != block_hash:
                # Only enforce when both claim a block_hash field on the fact.
                if "block_hash" in jsonl and jsonl.get("block_hash") != db_row.get(
                    "block_hash"
                ):
                    return False
    if (
        isinstance(jsonl.get("block_hash"), str)
        and isinstance(db_row.get("block_hash"), str)
        and jsonl["block_hash"]
        and db_row["block_hash"]
        and jsonl["block_hash"] != db_row["block_hash"]
    ):
        return False
    if (
        isinstance(jsonl.get("transaction_hash"), str)
        and isinstance(db_row.get("transaction_hash"), str)
        and jsonl["transaction_hash"]
        and db_row["transaction_hash"]
        and jsonl["transaction_hash"] != db_row["transaction_hash"]
    ):
        return False
    return True


def assert_shadow_catalog_excludes_secrets(shadow_store: Any) -> None:
    """Fail closed if any query-visible row carries secrets or raw bytes.

    Scans fact and dimension tables for forbidden key fragments and byte-valued
    payload bodies.  Encrypted object **refs** (digest/CID only) are allowed.
    """

    if shadow_store is None:
        raise InvalidRequestError("shadow_store is required")
    list_records = getattr(shadow_store, "list_records", None)
    catalog_tables = getattr(shadow_store, "catalog_tables", None)
    tables: Sequence[str]
    if callable(catalog_tables):
        tables = tuple(catalog_tables())
    else:
        tables = _SHADOW_FACT_TABLES
    if not callable(list_records):
        raise DatasetSinkError("shadow_store does not expose list_records")

    forbidden_fragments = (
        "secret",
        "private_key",
        "mnemonic",
        "signing",
        "password",
        "api_key",
        "raw_payload",
        "payload_bytes",
        "ciphertext",
        "plaintext",
    )
    for table in tables:
        try:
            rows = list_records(table)
        except Exception:
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            for key, value in row.items():
                lowered = str(key).casefold()
                for fragment in forbidden_fragments:
                    if fragment in lowered:
                        # encrypted_object_refs may mention digest fields only.
                        if table == "encrypted_object_refs" and fragment in {
                            "raw_payload",
                            "ciphertext",
                            "plaintext",
                            "payload_bytes",
                        }:
                            raise DatasetSinkError(
                                f"shadow catalog {table} forbids key {key!r}"
                            )
                        if table != "encrypted_object_refs":
                            raise DatasetSinkError(
                                f"shadow catalog {table} forbids key {key!r}"
                            )
                if isinstance(value, (bytes, bytearray, memoryview)):
                    raise DatasetSinkError(
                        f"shadow catalog {table} must not store raw bytes "
                        f"in column {key!r}"
                    )
                if isinstance(value, str) and len(value) > 16_384:
                    # Unrestricted raw blobs must not land as unbounded strings.
                    raise DatasetSinkError(
                        f"shadow catalog {table}.{key} exceeds redacted size bound"
                    )


def iter_record_dicts(records: Iterable[object]) -> list[dict[str, Any]]:
    """Project an iterable of records to dicts (test/export helper)."""

    return [record_as_dict(record) for record in records]


def build_redacted_public_ledger_analytics(
    authority_store: Any,
    *,
    scope: str | None = None,
) -> Mapping[str, Any]:
    """Build redacted public ledger analytics for Quack publication (DQK-073).

    Aggregates only allowlisted columns (counts / finality / sequence bounds /
    chain_ref_id).  Never includes raw payloads, secrets, signing material, or
    unrestricted bytes.  Suitable for the physically separate publication plane.
    """

    if authority_store is None:
        raise InvalidRequestError("authority_store is required")
    list_records = getattr(authority_store, "list_records", None)
    if not callable(list_records):
        raise DatasetSinkError("authority_store does not expose list_records")

    aggregates: dict[tuple[str, str, str], dict[str, Any]] = {}
    total_records = 0
    for table in _AUTHORITY_FACT_TABLES:
        try:
            rows = list_records(table)
        except Exception:
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            total_records += 1
            record_type = str(row.get("record_type") or table)
            finality = str(row.get("finality") or Finality.UNKNOWN.value)
            chain_ref_id = str(row.get("chain_ref_id") or "")
            key = (record_type, finality, chain_ref_id)
            bucket = aggregates.get(key)
            if bucket is None:
                bucket = {
                    "scope": scope or "",
                    "record_type": record_type,
                    "finality": finality,
                    "count": 0,
                    "min_sequence": None,
                    "max_sequence": None,
                    "chain_ref_id": chain_ref_id,
                }
                aggregates[key] = bucket
            bucket["count"] = int(bucket["count"]) + 1
            seq = row.get("sequence")
            if isinstance(seq, int) and not isinstance(seq, bool):
                min_seq = bucket["min_sequence"]
                max_seq = bucket["max_sequence"]
                bucket["min_sequence"] = seq if min_seq is None else min(int(min_seq), seq)
                bucket["max_sequence"] = seq if max_seq is None else max(int(max_seq), seq)

    rows_out = sorted(
        aggregates.values(),
        key=lambda r: (r["record_type"], r["finality"], r["chain_ref_id"]),
    )
    # Fail closed on secret-shaped keys/values before publication.
    for row in rows_out:
        ensure_secret_safe(row)
        for col in row:
            if col not in PUBLIC_LEDGER_ANALYTICS_COLUMNS:
                raise DatasetSinkError(
                    f"public ledger analytics forbids column {col!r}"
                )

    document: dict[str, Any] = {
        "schema_version": PUBLIC_LEDGER_ANALYTICS_SCHEMA_VERSION,
        "publication_type": "wallet_public_ledger_analytics_v1",
        "owner_task_id": WALLET_LEDGER_ONLY_OWNER_TASK,
        "operational_authority": "duckdb",
        "sensitive_raw_excluded": True,
        "payload_body_excluded": True,
        "legacy_file_authority": False,
        "quack_surface": "redacted_public_ledger_analytics",
        "scope": scope or "",
        "total_records": total_records,
        "aggregates": rows_out,
        "columns": list(PUBLIC_LEDGER_ANALYTICS_COLUMNS),
    }
    ensure_secret_safe(document)
    return MappingProxyType(document)


def assert_publication_excludes_secrets(document: Mapping[str, Any]) -> None:
    """Fail closed if a publication document carries secret-bearing material."""

    ensure_secret_safe(document)
    for key in document:
        lowered = str(key).casefold()
        for fragment in ("private_key", "mnemonic", "password", "api_key"):
            if fragment in lowered:
                raise DatasetSinkError(
                    f"publication document forbids key {key!r}"
                )
    # Nested aggregates must stay within the allowlisted column set.
    aggregates = document.get("aggregates")
    if isinstance(aggregates, Sequence) and not isinstance(aggregates, (str, bytes)):
        for row in aggregates:
            if not isinstance(row, Mapping):
                continue
            for col in row:
                if col not in PUBLIC_LEDGER_ANALYTICS_COLUMNS:
                    raise DatasetSinkError(
                        f"publication aggregate forbids column {col!r}"
                    )


__all__ = [
    "AUTHORITY_LEDGER_MODE_SCHEMA_VERSION",
    "DEFAULT_MAX_RAW_OBJECT_BYTES",
    "DEFAULT_MAX_RAW_OBJECTS",
    "DEFAULT_MAX_RAW_TOTAL_BYTES",
    "EXPORT_OUTBOX_SCHEMA_VERSION",
    "LEGACY_META_JSON_SUFFIX",
    "LEGACY_WALLET_LEDGER_FILENAMES",
    "NAMED_LEDGER_EXPORT_COMMANDS",
    "PUBLIC_LEDGER_ANALYTICS_COLUMNS",
    "PUBLIC_LEDGER_ANALYTICS_SCHEMA_VERSION",
    "RAW_PAYLOAD_SCHEMA_VERSION",
    "SHADOW_LEDGER_MODE_SCHEMA_VERSION",
    "SINK_RECEIPT_SCHEMA_VERSION",
    "WALLET_LEDGER_ONLY_DEFAULT_MODE",
    "WALLET_LEDGER_ONLY_OWNER_TASK",
    "BatchWriteReceipt",
    "DirectoryRawPayloadStore",
    "ExportOutbox",
    "ExportOutboxEntry",
    "ExportOutboxStatus",
    "ImplicitLegacyLedgerWriteError",
    "InMemoryRawPayloadStore",
    "LedgerFilesystemGuard",
    "RawPayloadCustodyLimits",
    "RawPayloadEncryptor",
    "RawPayloadStore",
    "ShadowLedgerMode",
    "ShadowParityReport",
    "ShadowWriteReceipt",
    "SinkCommitReceipt",
    "StoredRawPayload",
    "StreamingDatasetSink",
    "assert_legacy_wallet_ledger_files_absent",
    "assert_publication_excludes_secrets",
    "assert_shadow_catalog_excludes_secrets",
    "build_redacted_public_ledger_analytics",
    "compare_jsonl_db_projections",
    "digest_bytes",
    "fact_table_for_record",
    "is_legacy_wallet_ledger_filename",
    "iter_record_dicts",
    "legacy_wallet_ledger_files_present",
    "record_as_dict",
    "record_finality",
    "record_identity",
    "record_sequence",
]
