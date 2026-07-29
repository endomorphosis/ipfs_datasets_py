"""Verified block store for sharded graph payloads (KGP-014).

Every put records sha256 + CIDv1 (raw/sha2-256). Every get verifies bytes
against the declared checksum and/or CID before returning data. Corrupt and
missing objects surface as typed :class:`ShardBlockError` instances that the
query runtime maps into partial/failure policy outcomes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Protocol, runtime_checkable

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    ContentChecksum,
    canonical_json_bytes,
)
from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import (
    compute_cid_v1,
    verify_bytes_against_cid,
)


# ---------------------------------------------------------------------------
# Typed errors (aligned with kg-service-contract vocabulary)
# ---------------------------------------------------------------------------

TYPED_SHARD_ERROR_CODES = frozenset(
    {
        "NOT_FOUND",
        "INTEGRITY",
        "STORAGE",
        "BUDGET_EXCEEDED",
        "TIMEOUT",
        "INVALID_REQUEST",
        "PARTIAL",
        "INTERNAL",
    }
)


class ShardBlockError(Exception):
    """Typed failure while storing or fetching a shard/index block."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        cid: Optional[str] = None,
        path: Optional[str] = None,
        physical_shard_id: Optional[str] = None,
        retryable: bool = False,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if code not in TYPED_SHARD_ERROR_CODES:
            code = "INTERNAL"
        self.code = code
        self.message = message
        self.cid = cid
        self.path = path
        self.physical_shard_id = physical_shard_id
        self.retryable = bool(retryable)
        self.details = dict(details or {})
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "cid": self.cid,
            "path": self.path,
            "physical_shard_id": self.physical_shard_id,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_of_bytes(data: bytes) -> ContentChecksum:
    return ContentChecksum.of_bytes(bytes(data))


def cid_for_bytes(data: bytes, *, codec: str = "raw") -> str:
    """Content CID for *data* (raw/sha2-256 by default)."""
    return compute_cid_v1(bytes(data), codec=codec)


def verify_block(
    data: bytes,
    *,
    checksum: Optional[ContentChecksum] = None,
    expected_sha256: Optional[str] = None,
    cid: Optional[str] = None,
    expected_codec: Optional[str] = None,
    label: str = "block",
) -> ContentChecksum:
    """Verify *data* against checksum and/or CID. Always required on fetch.

    Returns the computed :class:`ContentChecksum` on success.
    Raises :class:`ShardBlockError` with code ``INTEGRITY`` on mismatch.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ShardBlockError(
            "INVALID_REQUEST",
            f"{label}: data must be bytes-like",
            details={"type": type(data).__name__},
        )
    payload = bytes(data)
    computed = ContentChecksum.of_bytes(payload)

    if expected_sha256 is not None:
        want = expected_sha256.lower().strip()
        if computed.hex_digest != want:
            raise ShardBlockError(
                "INTEGRITY",
                f"{label}: sha256 mismatch",
                cid=cid,
                details={
                    "expected_sha256": want,
                    "actual_sha256": computed.hex_digest,
                },
            )

    if checksum is not None:
        if checksum.hex_digest != computed.hex_digest:
            raise ShardBlockError(
                "INTEGRITY",
                f"{label}: checksum mismatch",
                cid=cid or checksum.as_cid(),
                details={
                    "expected_sha256": checksum.hex_digest,
                    "actual_sha256": computed.hex_digest,
                },
            )

    if cid is not None and str(cid).strip():
        try:
            # Prefer ContentChecksum CID equality (raw/sha2-256) used by manifests.
            if cid.strip() == computed.as_cid():
                return computed
            verify_bytes_against_cid(
                cid.strip(),
                payload,
                expected_codec=expected_codec or "raw",
            )
        except ShardBlockError:
            raise
        except Exception as exc:
            # GraphStoreError or other integrity failures.
            code = getattr(exc, "code", None) or "INTEGRITY"
            if code not in TYPED_SHARD_ERROR_CODES:
                code = "INTEGRITY"
            raise ShardBlockError(
                str(code),
                f"{label}: CID verification failed: {exc}",
                cid=cid,
                details={"error": str(exc)[:300]},
            ) from exc

    return computed


def encode_json_block(obj: Any) -> bytes:
    """Canonical JSON bytes for deterministic index/adjacency blocks."""
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj)
    return canonical_json_bytes(obj)


def decode_json_block(data: bytes) -> Any:
    return json.loads(bytes(data).decode("utf-8"))


# ---------------------------------------------------------------------------
# Block store protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredBlock:
    """Metadata for a verified stored block."""

    cid: str
    checksum: ContentChecksum
    size_bytes: int
    path: Optional[str] = None
    codec: str = "raw"


@runtime_checkable
class BlockStore(Protocol):
    """Content-addressed store for CAR shards, index buckets, and adjacency."""

    def put(
        self,
        data: bytes,
        *,
        path: Optional[str] = None,
        codec: str = "raw",
    ) -> StoredBlock:
        ...

    def get(
        self,
        *,
        cid: Optional[str] = None,
        path: Optional[str] = None,
        checksum: Optional[ContentChecksum] = None,
        expected_sha256: Optional[str] = None,
        label: str = "block",
    ) -> bytes:
        ...

    def has(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> bool:
        ...

    def corrupt(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> None:
        """Test hook: overwrite stored bytes without updating checksum."""
        ...

    def remove(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> None:
        ...

    def set_latency(self, seconds: float, *, cid: Optional[str] = None) -> None:
        """Test hook: inject artificial delay for a CID or all gets."""
        ...


class MemoryBlockStore:
    """In-memory block store with mandatory fetch verification."""

    def __init__(self) -> None:
        self._by_cid: MutableMapping[str, bytes] = {}
        self._by_path: MutableMapping[str, str] = {}  # path -> cid
        self._meta: MutableMapping[str, StoredBlock] = {}
        self._latency_all: float = 0.0
        self._latency_cid: MutableMapping[str, float] = {}
        self._lock = threading.RLock()

    def put(
        self,
        data: bytes,
        *,
        path: Optional[str] = None,
        codec: str = "raw",
    ) -> StoredBlock:
        payload = bytes(data)
        # Manifest index buckets require cid == ContentChecksum.as_cid() (raw/sha2-256).
        checksum = ContentChecksum.of_bytes(payload)
        cid = checksum.as_cid()
        block = StoredBlock(
            cid=cid,
            checksum=checksum,
            size_bytes=len(payload),
            path=path,
            codec=codec,
        )
        with self._lock:
            self._by_cid[cid] = payload
            self._meta[cid] = block
            if path is not None:
                self._by_path[path] = cid
        return block

    def _resolve_cid(
        self,
        *,
        cid: Optional[str],
        path: Optional[str],
    ) -> str:
        if cid:
            return cid
        if path and path in self._by_path:
            return self._by_path[path]
        raise ShardBlockError(
            "NOT_FOUND",
            "block not found",
            cid=cid,
            path=path,
        )

    def get(
        self,
        *,
        cid: Optional[str] = None,
        path: Optional[str] = None,
        checksum: Optional[ContentChecksum] = None,
        expected_sha256: Optional[str] = None,
        label: str = "block",
    ) -> bytes:
        with self._lock:
            try:
                resolved = self._resolve_cid(cid=cid, path=path)
            except ShardBlockError:
                raise
            delay = self._latency_cid.get(resolved, self._latency_all)
            if delay > 0:
                time.sleep(delay)
            data = self._by_cid.get(resolved)
            if data is None:
                raise ShardBlockError(
                    "NOT_FOUND",
                    f"{label}: missing block",
                    cid=resolved,
                    path=path,
                )
            payload = bytes(data)

        # Always verify against the content CID key and any caller-supplied checksum.
        verify_block(
            payload,
            checksum=checksum,
            expected_sha256=expected_sha256,
            cid=resolved,
            label=label,
        )
        return payload

    def has(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> bool:
        with self._lock:
            try:
                resolved = self._resolve_cid(cid=cid, path=path)
            except ShardBlockError:
                return False
            return resolved in self._by_cid

    def corrupt(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> None:
        with self._lock:
            resolved = self._resolve_cid(cid=cid, path=path)
            original = self._by_cid.get(resolved)
            if original is None:
                raise ShardBlockError("NOT_FOUND", "cannot corrupt missing block", cid=resolved)
            # Flip bytes without changing the CID key so fetch verification fails.
            self._by_cid[resolved] = b"\x00" + original[1:] if original else b"\xffCORRUPT"

    def remove(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> None:
        with self._lock:
            try:
                resolved = self._resolve_cid(cid=cid, path=path)
            except ShardBlockError:
                return
            self._by_cid.pop(resolved, None)
            self._meta.pop(resolved, None)
            if path and path in self._by_path:
                self._by_path.pop(path, None)
            # Drop path aliases pointing at this cid.
            dead = [p for p, c in self._by_path.items() if c == resolved]
            for p in dead:
                self._by_path.pop(p, None)

    def set_latency(self, seconds: float, *, cid: Optional[str] = None) -> None:
        with self._lock:
            if cid is None:
                self._latency_all = max(0.0, float(seconds))
            else:
                self._latency_cid[cid] = max(0.0, float(seconds))


class FileBlockStore:
    """Filesystem block store: objects under ``root/objects/<cid>`` + path map."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.paths_dir = self.root / "paths"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.paths_dir.mkdir(parents=True, exist_ok=True)
        self._latency_all: float = 0.0
        self._latency_cid: MutableMapping[str, float] = {}
        self._lock = threading.RLock()

    def put(
        self,
        data: bytes,
        *,
        path: Optional[str] = None,
        codec: str = "raw",
    ) -> StoredBlock:
        payload = bytes(data)
        checksum = ContentChecksum.of_bytes(payload)
        cid = checksum.as_cid()
        block = StoredBlock(
            cid=cid,
            checksum=checksum,
            size_bytes=len(payload),
            path=path,
            codec=codec,
        )
        obj_path = self.objects / cid
        tmp = obj_path.with_suffix(".tmp")
        with self._lock:
            tmp.write_bytes(payload)
            os.replace(tmp, obj_path)
            if path is not None:
                safe = path.replace("/", "__")
                map_file = self.paths_dir / safe
                map_file.write_text(cid, encoding="utf-8")
        return block

    def _resolve_cid(
        self,
        *,
        cid: Optional[str],
        path: Optional[str],
    ) -> str:
        if cid:
            return cid
        if path:
            safe = path.replace("/", "__")
            map_file = self.paths_dir / safe
            if map_file.is_file():
                return map_file.read_text(encoding="utf-8").strip()
        raise ShardBlockError("NOT_FOUND", "block not found", cid=cid, path=path)

    def get(
        self,
        *,
        cid: Optional[str] = None,
        path: Optional[str] = None,
        checksum: Optional[ContentChecksum] = None,
        expected_sha256: Optional[str] = None,
        label: str = "block",
    ) -> bytes:
        with self._lock:
            resolved = self._resolve_cid(cid=cid, path=path)
            delay = self._latency_cid.get(resolved, self._latency_all)
            if delay > 0:
                time.sleep(delay)
            obj_path = self.objects / resolved
            if not obj_path.is_file():
                raise ShardBlockError(
                    "NOT_FOUND",
                    f"{label}: missing block file",
                    cid=resolved,
                    path=path,
                )
            payload = obj_path.read_bytes()

        verify_block(
            payload,
            checksum=checksum,
            expected_sha256=expected_sha256,
            cid=resolved,
            label=label,
        )
        return payload

    def has(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> bool:
        try:
            resolved = self._resolve_cid(cid=cid, path=path)
        except ShardBlockError:
            return False
        return (self.objects / resolved).is_file()

    def corrupt(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> None:
        resolved = self._resolve_cid(cid=cid, path=path)
        obj_path = self.objects / resolved
        if not obj_path.is_file():
            raise ShardBlockError("NOT_FOUND", "cannot corrupt missing block", cid=resolved)
        original = obj_path.read_bytes()
        obj_path.write_bytes(b"\x00" + original[1:] if original else b"\xffCORRUPT")

    def remove(self, *, cid: Optional[str] = None, path: Optional[str] = None) -> None:
        try:
            resolved = self._resolve_cid(cid=cid, path=path)
        except ShardBlockError:
            return
        obj_path = self.objects / resolved
        if obj_path.is_file():
            obj_path.unlink()
        if path:
            safe = path.replace("/", "__")
            map_file = self.paths_dir / safe
            if map_file.is_file():
                map_file.unlink()

    def set_latency(self, seconds: float, *, cid: Optional[str] = None) -> None:
        if cid is None:
            self._latency_all = max(0.0, float(seconds))
        else:
            self._latency_cid[cid] = max(0.0, float(seconds))


__all__ = [
    "TYPED_SHARD_ERROR_CODES",
    "ShardBlockError",
    "StoredBlock",
    "BlockStore",
    "MemoryBlockStore",
    "FileBlockStore",
    "sha256_hex",
    "checksum_of_bytes",
    "cid_for_bytes",
    "verify_block",
    "encode_json_block",
    "decode_json_block",
]
