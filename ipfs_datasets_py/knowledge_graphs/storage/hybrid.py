"""Verified hybrid cache + GraphStore (KGP-012).

Storage profile ``hybrid`` combines:

* **Immutable local Parquet/CAR payloads** (optional local revision tree)
* A **verified local object cache** with atomic writes and bounded eviction
* A **CID-backed remote root** (IPFS/IPLD or ipfs_kit GraphStore)

Every cache hit and remote fetch verifies bytes against the expected CID /
descriptor. The cache (and optional catalog metadata) records which copy is
**authoritative** so readers never silently prefer a stale local mirror.

GC reachability/pin policy lives in :mod:`gc`; this module exposes the object
inventory, pin set, staged-object registry, and authority bookkeeping that GC
consumes.

DQK-061: after DuckDB-only graph control promotion, mutable control files
(``authority.json``, ``index.json``) are not written implicitly. Runtime cache
state is held in memory (and optionally projected to DuckDB). Identity-bearing
``meta/<cid>.json`` descriptors and object binaries remain durable. Explicit
export/import compatibility obtains a filesystem-guard permit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
    Union,
    runtime_checkable,
)

from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import (
    TYPED_ERROR_CODES,
    GraphStoreError,
    IPLDGraphStore,
    PutResult,
    compute_cid_v1,
    looks_like_cid,
    normalize_codec,
    verify_bytes_against_cid,
)

logger = logging.getLogger(__name__)

STORAGE_PROFILE: str = "hybrid"
DEFAULT_CACHE_MAX_BYTES: int = 256 * 1024 * 1024  # 256 MiB
DEFAULT_CACHE_MAX_ENTRIES: int = 4096
CACHE_SCHEMA_VERSION: str = "1"

CancelCheck = Callable[[], None]
PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Authority + object lifecycle
# ---------------------------------------------------------------------------


class AuthoritativeCopy(str, Enum):
    """Which durable location is the source of truth for an object."""

    LOCAL_CACHE = "local_cache"
    REMOTE_ROOT = "remote_root"
    PARQUET_LOCAL = "parquet_local"
    STAGED = "staged"


class ObjectLifecycle(str, Enum):
    """Lifecycle of a hybrid-tracked content object."""

    STAGED = "staged"  # prepared write; not yet reachable from catalog roots
    COMMITTED = "committed"  # reachable from a pin root / branch head
    ABANDONED = "abandoned"  # staged, no active lease, safe for GC


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObjectDescriptor:
    """Content-addressed object descriptor used for cache verification.

    ``cid`` is the primary identity. Optional ``sha256`` / ``size`` / ``codec``
    provide additional checks when present (e.g. Parquet partition descriptors).
    """

    cid: str
    codec: str = "raw"
    size: Optional[int] = None
    sha256: Optional[str] = None
    path: Optional[str] = None  # logical path / partition id
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.cid, str) or not self.cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "descriptor.cid must be non-empty")
        object.__setattr__(self, "cid", self.cid.strip())
        object.__setattr__(self, "codec", normalize_codec(self.codec))
        if self.sha256 is not None:
            digest = str(self.sha256).lower()
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise GraphStoreError(
                    "INVALID_REQUEST",
                    "descriptor.sha256 must be a 64-char hex digest",
                    details={"sha256": self.sha256},
                )
            object.__setattr__(self, "sha256", digest)
        if self.size is not None and int(self.size) < 0:
            raise GraphStoreError("INVALID_REQUEST", "descriptor.size must be >= 0")
        if self.size is not None:
            object.__setattr__(self, "size", int(self.size))
        object.__setattr__(self, "extra", dict(self.extra or {}))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cid": self.cid,
            "codec": self.codec,
            "size": self.size,
            "sha256": self.sha256,
            "path": self.path,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObjectDescriptor":
        if not isinstance(data, Mapping):
            raise GraphStoreError("INVALID_REQUEST", "descriptor must be a mapping")
        return cls(
            cid=str(data["cid"]),
            codec=str(data.get("codec") or "raw"),
            size=data.get("size"),
            sha256=data.get("sha256"),
            path=data.get("path"),
            extra=dict(data.get("extra") or {}),
        )

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        codec: str = "raw",
        path: Optional[str] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> "ObjectDescriptor":
        payload = bytes(data)
        codec_n = normalize_codec(codec)
        cid = compute_cid_v1(payload, codec=codec_n)
        return cls(
            cid=cid,
            codec=codec_n,
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            path=path,
            extra=dict(extra or {}),
        )


@dataclass(frozen=True, slots=True)
class CacheEntryMeta:
    """Durable metadata for one cached object."""

    cid: str
    codec: str
    size: int
    sha256: str
    authoritative: str
    lifecycle: str
    created_at: float
    last_access: float
    pin_count: int = 0
    path: Optional[str] = None
    lease_id: Optional[str] = None
    tenant: Optional[str] = None
    graph_id: Optional[str] = None
    revision_id: Optional[str] = None
    root_kind: Optional[str] = None  # branch|tag|snapshot|lease|staged|manifest|...
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CacheEntryMeta":
        return cls(
            cid=str(data["cid"]),
            codec=str(data.get("codec") or "raw"),
            size=int(data["size"]),
            sha256=str(data["sha256"]),
            authoritative=str(data.get("authoritative") or AuthoritativeCopy.LOCAL_CACHE.value),
            lifecycle=str(data.get("lifecycle") or ObjectLifecycle.COMMITTED.value),
            created_at=float(data.get("created_at") or 0.0),
            last_access=float(data.get("last_access") or 0.0),
            pin_count=int(data.get("pin_count") or 0),
            path=data.get("path"),
            lease_id=data.get("lease_id"),
            tenant=data.get("tenant"),
            graph_id=data.get("graph_id"),
            revision_id=data.get("revision_id"),
            root_kind=data.get("root_kind"),
            extra=dict(data.get("extra") or {}),
        )


@dataclass(frozen=True, slots=True)
class AuthorityRecord:
    """Records which copy is authoritative for a CID."""

    cid: str
    authoritative: AuthoritativeCopy
    local_path: Optional[str] = None
    remote_root: Optional[str] = None
    updated_at: float = 0.0
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cid": self.cid,
            "authoritative": self.authoritative.value
            if isinstance(self.authoritative, AuthoritativeCopy)
            else str(self.authoritative),
            "local_path": self.local_path,
            "remote_root": self.remote_root,
            "updated_at": self.updated_at,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthorityRecord":
        auth_raw = data.get("authoritative") or AuthoritativeCopy.REMOTE_ROOT.value
        try:
            auth = AuthoritativeCopy(str(auth_raw))
        except ValueError:
            auth = AuthoritativeCopy.REMOTE_ROOT
        return cls(
            cid=str(data["cid"]),
            authoritative=auth,
            local_path=data.get("local_path"),
            remote_root=data.get("remote_root"),
            updated_at=float(data.get("updated_at") or 0.0),
            details=dict(data.get("details") or {}),
        )


# ---------------------------------------------------------------------------
# Atomic filesystem helpers
# ---------------------------------------------------------------------------


def _fsync_fd(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        pass


def _fsync_path(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        _fsync_fd(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _fsync_path(path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` via temp file + fsync + ``os.replace`` (crash-safe)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            _fsync_fd(fh.fileno())
        os.replace(str(tmp), str(path))
        _fsync_directory(path.parent)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    atomic_write_bytes(path, text.encode("utf-8"))


def _mutable_control_io_allowed() -> bool:
    """Return True when hybrid may persist mutable control JSON files."""

    try:
        from ipfs_datasets_py.knowledge_graphs.catalog.store import (
            duckdb_only_graph_control,
            get_graph_authority,
            get_graph_filesystem_guard,
            get_graph_shadow_authority,
            legacy_graph_control_io_allowed,
        )

        auth = get_graph_authority() or get_graph_shadow_authority()
        if auth is not None and not getattr(auth, "legacy_io_allowed", True):
            guard = get_graph_filesystem_guard()
            return bool(guard._has_permit())  # noqa: SLF001
        if duckdb_only_graph_control():
            return legacy_graph_control_io_allowed()
        return True
    except Exception:
        return True


def _assert_mutable_control_write(path: Path) -> None:
    """Fail closed on mutable graph-control JSON writes after DuckDB-only cutover."""

    try:
        from ipfs_datasets_py.knowledge_graphs.catalog.store import (
            get_graph_filesystem_guard,
        )

        get_graph_filesystem_guard().assert_allowed(
            path, kind="mutable_control_json", operation="write"
        )
    except Exception as exc:
        # Re-raise guard rejections; ignore import/other issues only when allowed.
        from ipfs_datasets_py.knowledge_graphs.catalog.store import (
            ImplicitLegacyGraphControlError,
        )

        if isinstance(exc, ImplicitLegacyGraphControlError):
            raise
        if not _mutable_control_io_allowed():
            raise


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_against_descriptor(
    data: bytes,
    descriptor: ObjectDescriptor,
    *,
    verify_cid: bool = True,
) -> str:
    """Verify ``data`` against a descriptor; return canonical CID.

    Raises :class:`GraphStoreError` with code ``INTEGRITY`` on mismatch.
    """
    payload = bytes(data)
    if descriptor.size is not None and len(payload) != descriptor.size:
        raise GraphStoreError(
            "INTEGRITY",
            "cached object size does not match descriptor",
            details={
                "cid": descriptor.cid,
                "expected_size": descriptor.size,
                "actual_size": len(payload),
            },
            cause_code="SIZE_MISMATCH",
        )
    if descriptor.sha256 is not None:
        actual = sha256_bytes(payload)
        if actual != descriptor.sha256:
            raise GraphStoreError(
                "INTEGRITY",
                "cached object sha256 does not match descriptor",
                details={"cid": descriptor.cid, "expected": descriptor.sha256, "actual": actual},
                cause_code="SHA256_MISMATCH",
            )
    if verify_cid:
        return verify_bytes_against_cid(
            descriptor.cid,
            payload,
            expected_codec=descriptor.codec,
        )
    return descriptor.cid


# ---------------------------------------------------------------------------
# Remote backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class RemoteBlockStore(Protocol):
    """Minimal remote/CID store surface used by the hybrid layer."""

    def put(
        self,
        data: bytes,
        *,
        codec: str = "raw",
        pin: Optional[bool] = None,
    ) -> PutResult: ...

    def get(self, cid: str, *, expected_codec: Optional[str] = None) -> bytes: ...

    def has(self, cid: str) -> bool: ...

    def pin(self, cid: str) -> None: ...

    def unpin(self, cid: str) -> None: ...

    def is_pinned(self, cid: str) -> bool: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Verified hybrid cache
# ---------------------------------------------------------------------------


class VerifiedHybridCache:
    """Filesystem-backed object cache with CID verification and bounded eviction.

    Layout::

        <root>/
          objects/<cid>.bin          # payload bytes (atomic write)
          meta/<cid>.json            # CacheEntryMeta
          authority.json             # cid -> AuthorityRecord
          index.json                 # schema + totals + lru order

    Writes always go to a temp file, fsync, then ``os.replace``. Reads always
    re-verify against the stored descriptor/CID before returning bytes.
    """

    def __init__(
        self,
        root_dir: PathLike,
        *,
        max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
        max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        verify_on_read: bool = True,
        shadow_authority: Any = None,
        persist_mutable_control: Optional[bool] = None,
    ) -> None:
        if max_bytes < 0:
            raise GraphStoreError("INVALID_REQUEST", "max_bytes must be >= 0")
        if max_entries < 1:
            raise GraphStoreError("INVALID_REQUEST", "max_entries must be >= 1")
        self.root = Path(root_dir)
        self.max_bytes = int(max_bytes)
        self.max_entries = int(max_entries)
        self.verify_on_read = bool(verify_on_read)
        self._lock = threading.RLock()
        self._entries: "OrderedDict[str, CacheEntryMeta]" = OrderedDict()
        self._authority: Dict[str, AuthorityRecord] = {}
        self._total_bytes: int = 0
        # DQK-059/060/061: optional DuckDB shadow/dual for control metadata;
        # payload bytes (Parquet/IPLD) always remain local content authority.
        self._shadow_authority = shadow_authority
        # None → derive from process DuckDB-only guard (DQK-061).
        self._persist_mutable_control_override = persist_mutable_control
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        (self.root / "meta").mkdir(parents=True, exist_ok=True)
        self._load()

    def attach_shadow_authority(self, authority: Any) -> None:
        """Bind DuckDB shadow/dual authority for metadata projection.

        Payload bytes and CIDs remain the content authority regardless of
        control-metadata mode (DQK-060).
        """

        self._shadow_authority = authority

    # Alias used by dual-mode cutover callers.
    attach_authority = attach_shadow_authority

    @property
    def shadow_authority(self) -> Any:
        return self._shadow_authority

    @property
    def authority(self) -> Any:
        return self._shadow_authority

    @property
    def content_authority(self) -> str:
        """Content always stays on local/IPLD bytes — never DuckDB (DQK-060)."""

        return "parquet_ipld"

    @property
    def persist_mutable_control(self) -> bool:
        """Whether ``authority.json`` / ``index.json`` may be written."""

        if self._persist_mutable_control_override is not None:
            return bool(self._persist_mutable_control_override)
        return _mutable_control_io_allowed()

    def set_persist_mutable_control(self, allowed: bool) -> None:
        """Explicitly enable/disable mutable control JSON persistence."""

        self._persist_mutable_control_override = bool(allowed)

    def export_control_json(self) -> Dict[str, Path]:
        """Explicit export of mutable control JSON (import/export compatibility).

        Obtains a filesystem-guard export permit so DQK-061 guards allow the
        write. Identity-bearing CID meta files are not part of this export.
        """

        try:
            from ipfs_datasets_py.knowledge_graphs.catalog.store import (
                get_graph_filesystem_guard,
            )

            guard = get_graph_filesystem_guard()
            with guard.permit_export():
                with self._lock:
                    self._persist_authority(force=True)
                    self._persist_index(force=True)
        except Exception:
            # Fallback when store module is unavailable: write directly.
            with self._lock:
                payload_auth = {
                    cid: rec.to_dict()
                    for cid, rec in sorted(self._authority.items())
                }
                atomic_write_json(self._authority_path(), payload_auth)
                payload_idx = {
                    "schema_version": CACHE_SCHEMA_VERSION,
                    "total_bytes": self._total_bytes,
                    "entry_count": len(self._entries),
                    "max_bytes": self.max_bytes,
                    "max_entries": self.max_entries,
                    "lru": list(self._entries.keys()),
                }
                atomic_write_json(self._index_path(), payload_idx)
        return {
            "authority": self._authority_path(),
            "index": self._index_path(),
        }

    def _resolve_authority(self) -> Any:
        shadow = self._shadow_authority
        if shadow is not None:
            return shadow
        try:
            from ipfs_datasets_py.knowledge_graphs.catalog.store import (
                get_graph_authority,
                get_graph_shadow_authority,
            )

            shadow = get_graph_authority() or get_graph_shadow_authority()
            if shadow is not None:
                self._shadow_authority = shadow
            return shadow
        except Exception:
            return None

    def _emit_storage_shadow(
        self,
        kind: str,
        cid: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
        content_bytes: Optional[bytes] = None,
        checksum: str = "",
        operation_id: Optional[str] = None,
    ) -> None:
        shadow = self._resolve_authority()
        if shadow is None:
            return
        try:
            body = dict(payload or {})
            body.setdefault("cid", cid)
            # Dual/db-primary: metadata is outbox-projected; content stays local.
            body.setdefault(
                "legacy_is_outbox_projection",
                bool(getattr(shadow, "legacy_is_outbox_projection", False)),
            )
            body.setdefault("content_authority", self.content_authority)
            if hasattr(shadow, "_authority_label"):
                body.setdefault("control_authority", shadow._authority_label())
            shadow.record_storage_mutation(
                kind=kind,
                cid=cid,
                payload=body,
                operation_id=operation_id,
                content_bytes=content_bytes,
                checksum=checksum,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hybrid storage shadow quarantined (legacy ok) cid=%s: %s",
                cid,
                exc,
            )

    # -- paths -------------------------------------------------------------

    def _object_path(self, cid: str) -> Path:
        return self.root / "objects" / f"{cid}.bin"

    def _meta_path(self, cid: str) -> Path:
        return self.root / "meta" / f"{cid}.json"

    def _authority_path(self) -> Path:
        return self.root / "authority.json"

    def _index_path(self) -> Path:
        return self.root / "index.json"

    # -- load / persist ----------------------------------------------------

    def _load(self) -> None:
        index_path = self._index_path()
        auth_path = self._authority_path()
        if auth_path.is_file():
            try:
                raw = json.loads(auth_path.read_text(encoding="utf-8"))
                if isinstance(raw, Mapping):
                    for cid, rec in raw.items():
                        if isinstance(rec, Mapping):
                            self._authority[str(cid)] = AuthorityRecord.from_dict(rec)
            except Exception:
                logger.warning("failed to load authority map at %s", auth_path, exc_info=True)

        # Prefer scanning meta/ so a partial index still recovers.
        meta_dir = self.root / "meta"
        loaded: List[CacheEntryMeta] = []
        if meta_dir.is_dir():
            for path in meta_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, Mapping):
                        continue
                    meta = CacheEntryMeta.from_dict(data)
                    obj = self._object_path(meta.cid)
                    if not obj.is_file():
                        # Drop orphan meta.
                        try:
                            path.unlink()
                        except OSError:
                            pass
                        continue
                    loaded.append(meta)
                except Exception:
                    logger.debug("skip corrupt cache meta %s", path, exc_info=True)

        # Restore LRU order from index when available.
        order: List[str] = []
        if index_path.is_file():
            try:
                idx = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(idx, Mapping) and isinstance(idx.get("lru"), list):
                    order = [str(c) for c in idx["lru"]]
            except Exception:
                order = []

        by_cid = {m.cid: m for m in loaded}
        if order:
            for cid in order:
                meta = by_cid.pop(cid, None)
                if meta is not None:
                    self._entries[cid] = meta
                    self._total_bytes += meta.size
            for cid, meta in by_cid.items():
                self._entries[cid] = meta
                self._total_bytes += meta.size
        else:
            for meta in sorted(loaded, key=lambda m: m.last_access):
                self._entries[meta.cid] = meta
                self._total_bytes += meta.size

        # Clean leftover temp files from interrupted writes.
        for directory in (self.root / "objects", self.root / "meta", self.root):
            if not directory.is_dir():
                continue
            for tmp in directory.glob(".*.tmp"):
                try:
                    tmp.unlink()
                except OSError:
                    pass

        self._persist_index()

    def _persist_meta(self, meta: CacheEntryMeta) -> None:
        # Identity-bearing CID descriptor — always durable (DQK-061).
        atomic_write_json(self._meta_path(meta.cid), meta.to_dict())

    def _persist_authority(self, *, force: bool = False) -> None:
        """Persist mutable authority map; blocked after DuckDB-only unless force/permit."""

        path = self._authority_path()
        if not force and not self.persist_mutable_control:
            # Project control metadata to DuckDB when available; skip JSON.
            self._emit_storage_shadow(
                "skip_mutable_authority_json",
                "hybrid-authority",
                payload={
                    "reason": "duckdb_only_graph_control",
                    "authority_records": len(self._authority),
                    "mutable_control_json_writer": False,
                },
            )
            return
        if not force:
            try:
                _assert_mutable_control_write(path)
            except Exception:
                if not _mutable_control_io_allowed():
                    return
        payload = {cid: rec.to_dict() for cid, rec in sorted(self._authority.items())}
        atomic_write_json(path, payload)

    def _persist_index(self, *, force: bool = False) -> None:
        """Persist mutable index JSON; blocked after DuckDB-only unless force/permit."""

        path = self._index_path()
        if not force and not self.persist_mutable_control:
            self._emit_storage_shadow(
                "skip_mutable_index_json",
                "hybrid-index",
                payload={
                    "reason": "duckdb_only_graph_control",
                    "entry_count": len(self._entries),
                    "mutable_control_json_writer": False,
                },
            )
            return
        if not force:
            try:
                _assert_mutable_control_write(path)
            except Exception:
                if not _mutable_control_io_allowed():
                    return
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "total_bytes": self._total_bytes,
            "entry_count": len(self._entries),
            "max_bytes": self.max_bytes,
            "max_entries": self.max_entries,
            "lru": list(self._entries.keys()),
        }
        atomic_write_json(path, payload)

    # -- public stats ------------------------------------------------------

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._total_bytes

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pinned = sum(1 for m in self._entries.values() if m.pin_count > 0)
            staged = sum(
                1 for m in self._entries.values() if m.lifecycle == ObjectLifecycle.STAGED.value
            )
            abandoned = sum(
                1
                for m in self._entries.values()
                if m.lifecycle == ObjectLifecycle.ABANDONED.value
            )
            return {
                "root": str(self.root),
                "total_bytes": self._total_bytes,
                "entry_count": len(self._entries),
                "max_bytes": self.max_bytes,
                "max_entries": self.max_entries,
                "pinned_entries": pinned,
                "staged_entries": staged,
                "abandoned_entries": abandoned,
                "authority_records": len(self._authority),
            }

    # -- authority ---------------------------------------------------------

    def record_authoritative(
        self,
        cid: str,
        authoritative: Union[AuthoritativeCopy, str],
        *,
        local_path: Optional[str] = None,
        remote_root: Optional[str] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> AuthorityRecord:
        """Record which copy is authoritative for ``cid``."""
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "cid must be a non-empty string")
        if isinstance(authoritative, AuthoritativeCopy):
            auth = authoritative
        else:
            try:
                auth = AuthoritativeCopy(str(authoritative))
            except ValueError as exc:
                raise GraphStoreError(
                    "INVALID_REQUEST",
                    f"unknown authoritative copy: {authoritative!r}",
                ) from exc
        rec = AuthorityRecord(
            cid=cid.strip(),
            authoritative=auth,
            local_path=local_path,
            remote_root=remote_root,
            updated_at=time.time(),
            details=dict(details or {}),
        )
        with self._lock:
            self._authority[rec.cid] = rec
            # Reflect into cache meta when present.
            meta = self._entries.get(rec.cid)
            if meta is not None:
                updated = CacheEntryMeta(
                    cid=meta.cid,
                    codec=meta.codec,
                    size=meta.size,
                    sha256=meta.sha256,
                    authoritative=auth.value,
                    lifecycle=meta.lifecycle,
                    created_at=meta.created_at,
                    last_access=meta.last_access,
                    pin_count=meta.pin_count,
                    path=meta.path,
                    lease_id=meta.lease_id,
                    tenant=meta.tenant,
                    graph_id=meta.graph_id,
                    revision_id=meta.revision_id,
                    root_kind=meta.root_kind,
                    extra=meta.extra,
                )
                self._entries[rec.cid] = updated
                self._persist_meta(updated)
            self._persist_authority()
            self._persist_index()
        return rec

    def get_authority(self, cid: str) -> Optional[AuthorityRecord]:
        with self._lock:
            return self._authority.get(cid)

    def list_authority(self) -> List[AuthorityRecord]:
        with self._lock:
            return [self._authority[c] for c in sorted(self._authority.keys())]

    # -- core put/get ------------------------------------------------------

    def contains(self, cid: str) -> bool:
        with self._lock:
            return cid in self._entries and self._object_path(cid).is_file()

    def get_meta(self, cid: str) -> Optional[CacheEntryMeta]:
        with self._lock:
            return self._entries.get(cid)

    def put(
        self,
        data: bytes,
        *,
        descriptor: Optional[ObjectDescriptor] = None,
        codec: str = "raw",
        authoritative: Union[AuthoritativeCopy, str] = AuthoritativeCopy.LOCAL_CACHE,
        lifecycle: Union[ObjectLifecycle, str] = ObjectLifecycle.COMMITTED,
        pin: bool = False,
        lease_id: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        revision_id: Optional[str] = None,
        root_kind: Optional[str] = None,
        path: Optional[str] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> CacheEntryMeta:
        """Atomically cache ``data`` after verifying against the descriptor/CID."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise GraphStoreError(
                "INVALID_REQUEST",
                "cache put requires bytes",
                details={"type": type(data).__name__},
            )
        payload = bytes(data)
        if descriptor is None:
            descriptor = ObjectDescriptor.from_bytes(
                payload, codec=codec, path=path, extra=extra
            )
        else:
            # Fill missing fields from observed bytes without weakening identity.
            if descriptor.path is None and path is not None:
                descriptor = ObjectDescriptor(
                    cid=descriptor.cid,
                    codec=descriptor.codec,
                    size=descriptor.size if descriptor.size is not None else len(payload),
                    sha256=descriptor.sha256 or sha256_bytes(payload),
                    path=path,
                    extra=descriptor.extra,
                )
            elif descriptor.size is None or descriptor.sha256 is None:
                descriptor = ObjectDescriptor(
                    cid=descriptor.cid,
                    codec=descriptor.codec,
                    size=descriptor.size if descriptor.size is not None else len(payload),
                    sha256=descriptor.sha256 or sha256_bytes(payload),
                    path=descriptor.path or path,
                    extra=descriptor.extra,
                )

        verify_against_descriptor(payload, descriptor, verify_cid=True)

        if isinstance(authoritative, AuthoritativeCopy):
            auth = authoritative
        else:
            auth = AuthoritativeCopy(str(authoritative))
        if isinstance(lifecycle, ObjectLifecycle):
            life = lifecycle
        else:
            life = ObjectLifecycle(str(lifecycle))

        now = time.time()
        with self._lock:
            existing = self._entries.get(descriptor.cid)
            base_pins = existing.pin_count if existing is not None else 0
            pin_count = base_pins + 1 if pin else base_pins

            meta = CacheEntryMeta(
                cid=descriptor.cid,
                codec=descriptor.codec,
                size=len(payload),
                sha256=descriptor.sha256 or sha256_bytes(payload),
                authoritative=auth.value,
                lifecycle=life.value,
                created_at=existing.created_at if existing else now,
                last_access=now,
                pin_count=max(0, pin_count),
                path=descriptor.path or path,
                lease_id=lease_id if lease_id is not None else (existing.lease_id if existing else None),
                tenant=tenant if tenant is not None else (existing.tenant if existing else None),
                graph_id=graph_id if graph_id is not None else (existing.graph_id if existing else None),
                revision_id=revision_id
                if revision_id is not None
                else (existing.revision_id if existing else None),
                root_kind=root_kind if root_kind is not None else (existing.root_kind if existing else None),
                extra=dict(extra or (existing.extra if existing else {})),
            )

            # Atomic payload write first, then meta.
            atomic_write_bytes(self._object_path(descriptor.cid), payload)
            self._persist_meta(meta)

            old_size = existing.size if existing else 0
            if existing is not None:
                # Move to MRU end.
                self._entries.pop(descriptor.cid, None)
                self._total_bytes -= old_size
            self._entries[descriptor.cid] = meta
            self._total_bytes += meta.size

            prev_auth = self._authority.get(descriptor.cid)
            self._authority[descriptor.cid] = AuthorityRecord(
                cid=descriptor.cid,
                authoritative=auth,
                local_path=str(self._object_path(descriptor.cid)),
                remote_root=prev_auth.remote_root if prev_auth is not None else None,
                updated_at=now,
                details={"source": "cache_put"},
            )

            self._evict_if_needed(protected={descriptor.cid})
            self._persist_authority()
            self._persist_index()
            result_meta = self._entries[descriptor.cid]

        # Shadow projects metadata + content fingerprint; never rewrites bytes.
        self._emit_storage_shadow(
            "put",
            descriptor.cid,
            payload={
                "cid": descriptor.cid,
                "size": result_meta.size,
                "sha256": result_meta.sha256,
                "codec": result_meta.codec,
                "authoritative": result_meta.authoritative,
                "lifecycle": result_meta.lifecycle,
                "pin_count": result_meta.pin_count,
                "tenant": result_meta.tenant,
                "graph_id": result_meta.graph_id,
                "revision_id": result_meta.revision_id,
            },
            content_bytes=payload,
            checksum=result_meta.sha256 or "",
        )
        return result_meta

    def get(
        self,
        cid: str,
        *,
        descriptor: Optional[ObjectDescriptor] = None,
        expected_codec: Optional[str] = None,
    ) -> bytes:
        """Return verified cache bytes for ``cid`` or raise ``NOT_FOUND``."""
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "cid must be a non-empty string")
        cid = cid.strip()
        with self._lock:
            meta = self._entries.get(cid)
            path = self._object_path(cid)
            if meta is None or not path.is_file():
                raise GraphStoreError(
                    "NOT_FOUND",
                    f"cache miss for {cid}",
                    details={"cid": cid},
                    cause_code="CACHE_MISS",
                )
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise GraphStoreError(
                    "STORAGE",
                    f"failed to read cache object: {cid}",
                    details={"cid": cid, "path": str(path)},
                    cause_code="CACHE_READ_FAILED",
                ) from exc

            desc = descriptor or ObjectDescriptor(
                cid=cid,
                codec=expected_codec or meta.codec,
                size=meta.size,
                sha256=meta.sha256,
                path=meta.path,
            )
            if self.verify_on_read:
                verify_against_descriptor(payload, desc, verify_cid=True)

            # Touch LRU.
            now = time.time()
            updated = CacheEntryMeta(
                cid=meta.cid,
                codec=meta.codec,
                size=meta.size,
                sha256=meta.sha256,
                authoritative=meta.authoritative,
                lifecycle=meta.lifecycle,
                created_at=meta.created_at,
                last_access=now,
                pin_count=meta.pin_count,
                path=meta.path,
                lease_id=meta.lease_id,
                tenant=meta.tenant,
                graph_id=meta.graph_id,
                revision_id=meta.revision_id,
                root_kind=meta.root_kind,
                extra=meta.extra,
            )
            self._entries.pop(cid, None)
            self._entries[cid] = updated
            self._persist_meta(updated)
            self._persist_index()
            return payload

    def pin(self, cid: str) -> CacheEntryMeta:
        with self._lock:
            meta = self._entries.get(cid)
            if meta is None:
                raise GraphStoreError("NOT_FOUND", f"cannot pin missing cache object: {cid}")
            updated = CacheEntryMeta(
                cid=meta.cid,
                codec=meta.codec,
                size=meta.size,
                sha256=meta.sha256,
                authoritative=meta.authoritative,
                lifecycle=meta.lifecycle,
                created_at=meta.created_at,
                last_access=time.time(),
                pin_count=meta.pin_count + 1,
                path=meta.path,
                lease_id=meta.lease_id,
                tenant=meta.tenant,
                graph_id=meta.graph_id,
                revision_id=meta.revision_id,
                root_kind=meta.root_kind,
                extra=meta.extra,
            )
            self._entries[cid] = updated
            self._persist_meta(updated)
            self._persist_index()
            pin_result = updated
        self._emit_storage_shadow(
            "pin",
            cid,
            payload={
                "cid": cid,
                "pin_count": pin_result.pin_count,
                "sha256": pin_result.sha256,
            },
            checksum=pin_result.sha256 or "",
        )
        return pin_result

    def unpin(self, cid: str) -> CacheEntryMeta:
        with self._lock:
            meta = self._entries.get(cid)
            if meta is None:
                raise GraphStoreError("NOT_FOUND", f"cannot unpin missing cache object: {cid}")
            updated = CacheEntryMeta(
                cid=meta.cid,
                codec=meta.codec,
                size=meta.size,
                sha256=meta.sha256,
                authoritative=meta.authoritative,
                lifecycle=meta.lifecycle,
                created_at=meta.created_at,
                last_access=time.time(),
                pin_count=max(0, meta.pin_count - 1),
                path=meta.path,
                lease_id=meta.lease_id,
                tenant=meta.tenant,
                graph_id=meta.graph_id,
                revision_id=meta.revision_id,
                root_kind=meta.root_kind,
                extra=meta.extra,
            )
            self._entries[cid] = updated
            self._persist_meta(updated)
            self._persist_index()
            unpin_result = updated
        self._emit_storage_shadow(
            "unpin",
            cid,
            payload={
                "cid": cid,
                "pin_count": unpin_result.pin_count,
                "sha256": unpin_result.sha256,
            },
            checksum=unpin_result.sha256 or "",
        )
        return unpin_result

    def is_pinned(self, cid: str) -> bool:
        with self._lock:
            meta = self._entries.get(cid)
            return bool(meta and meta.pin_count > 0)

    def set_lifecycle(
        self,
        cid: str,
        lifecycle: Union[ObjectLifecycle, str],
        *,
        root_kind: Optional[str] = None,
        lease_id: Optional[str] = None,
    ) -> CacheEntryMeta:
        if isinstance(lifecycle, ObjectLifecycle):
            life = lifecycle
        else:
            life = ObjectLifecycle(str(lifecycle))
        with self._lock:
            meta = self._entries.get(cid)
            if meta is None:
                raise GraphStoreError("NOT_FOUND", f"unknown cache object: {cid}")
            updated = CacheEntryMeta(
                cid=meta.cid,
                codec=meta.codec,
                size=meta.size,
                sha256=meta.sha256,
                authoritative=meta.authoritative,
                lifecycle=life.value,
                created_at=meta.created_at,
                last_access=meta.last_access,
                pin_count=meta.pin_count,
                path=meta.path,
                lease_id=lease_id if lease_id is not None else meta.lease_id,
                tenant=meta.tenant,
                graph_id=meta.graph_id,
                revision_id=meta.revision_id,
                root_kind=root_kind if root_kind is not None else meta.root_kind,
                extra=meta.extra,
            )
            self._entries[cid] = updated
            self._persist_meta(updated)
            self._persist_index()
            return updated

    def mark_abandoned(self, cid: str) -> CacheEntryMeta:
        return self.set_lifecycle(cid, ObjectLifecycle.ABANDONED)

    def delete(self, cid: str, *, force: bool = False) -> bool:
        """Delete a cache object. Refuses pinned objects unless ``force``."""
        with self._lock:
            meta = self._entries.get(cid)
            if meta is None:
                return False
            if meta.pin_count > 0 and not force:
                raise GraphStoreError(
                    "CONFLICT",
                    f"refusing to delete pinned cache object: {cid}",
                    details={"cid": cid, "pin_count": meta.pin_count},
                    cause_code="PINNED",
                )
            self._entries.pop(cid, None)
            self._total_bytes = max(0, self._total_bytes - meta.size)
            for path in (self._object_path(cid), self._meta_path(cid)):
                try:
                    if path.exists():
                        path.unlink()
                except OSError:
                    pass
            self._authority.pop(cid, None)
            self._persist_authority()
            self._persist_index()
            return True

    def list_entries(
        self,
        *,
        lifecycle: Optional[Union[ObjectLifecycle, str]] = None,
    ) -> List[CacheEntryMeta]:
        with self._lock:
            items = list(self._entries.values())
        if lifecycle is None:
            return items
        life = lifecycle.value if isinstance(lifecycle, ObjectLifecycle) else str(lifecycle)
        return [m for m in items if m.lifecycle == life]

    def list_cids(self) -> List[str]:
        with self._lock:
            return list(self._entries.keys())

    # -- eviction ----------------------------------------------------------

    def _evict_if_needed(self, *, protected: Optional[Set[str]] = None) -> List[str]:
        """Evict unpinned LRU entries until under max_bytes/max_entries.

        Never evicts pinned objects or CIDs in ``protected``.
        """
        protected = set(protected or ())
        evicted: List[str] = []
        # Entry bound first, then byte bound.
        while len(self._entries) > self.max_entries or (
            self.max_bytes > 0 and self._total_bytes > self.max_bytes
        ):
            victim: Optional[str] = None
            for cid, meta in self._entries.items():
                if cid in protected:
                    continue
                if meta.pin_count > 0:
                    continue
                if meta.lifecycle == ObjectLifecycle.STAGED.value:
                    # Staged objects are GC's concern, not cache eviction —
                    # but still skip if pinned (pin_count check above).
                    # Allow eviction of staged only when over hard limits.
                    pass
                victim = cid
                break
            if victim is None:
                # Only pinned / protected remain; stop (may exceed bounds).
                logger.warning(
                    "hybrid cache over capacity but all remaining entries are "
                    "pinned/protected (entries=%s bytes=%s)",
                    len(self._entries),
                    self._total_bytes,
                )
                break
            meta = self._entries.pop(victim)
            self._total_bytes = max(0, self._total_bytes - meta.size)
            for path in (self._object_path(victim), self._meta_path(victim)):
                try:
                    if path.exists():
                        path.unlink()
                except OSError:
                    pass
            # Keep authority record so remote remains known as authoritative.
            auth = self._authority.get(victim)
            if auth is not None and auth.authoritative == AuthoritativeCopy.LOCAL_CACHE:
                self._authority[victim] = AuthorityRecord(
                    cid=victim,
                    authoritative=AuthoritativeCopy.REMOTE_ROOT,
                    local_path=None,
                    remote_root=auth.remote_root,
                    updated_at=time.time(),
                    details={"evicted_from_cache": True},
                )
            evicted.append(victim)
        return evicted

    def evict_to_bounds(self) -> List[str]:
        with self._lock:
            evicted = self._evict_if_needed()
            if evicted:
                self._persist_authority()
                self._persist_index()
            return evicted

    def close(self) -> None:
        with self._lock:
            self._persist_authority()
            self._persist_index()


# ---------------------------------------------------------------------------
# Hybrid GraphStore
# ---------------------------------------------------------------------------


class HybridGraphStore:
    """Hybrid GraphStore: verified local cache + remote CID store.

    * ``put`` writes to remote (authoritative by default) and populates cache
    * ``get`` prefers verified cache; falls back to remote and fills cache
    * staged puts mark lifecycle ``staged`` for GC (abandoned when lease ends)
    * authority map records which copy is authoritative
    """

    storage_profile: str = STORAGE_PROFILE

    def __init__(
        self,
        cache: VerifiedHybridCache,
        remote: Optional[RemoteBlockStore] = None,
        *,
        pin_by_default: bool = True,
        cache_on_put: bool = True,
        cache_on_get: bool = True,
        cancel_check: Optional[CancelCheck] = None,
        remote_is_authoritative: bool = True,
    ) -> None:
        self.cache = cache
        self.remote: RemoteBlockStore = remote if remote is not None else IPLDGraphStore.open_memory()
        self.pin_by_default = pin_by_default
        self.cache_on_put = cache_on_put
        self.cache_on_get = cache_on_get
        self._cancel_check = cancel_check
        self.remote_is_authoritative = remote_is_authoritative
        self._lock = threading.RLock()
        # Explicit extra roots (tags/snapshots) registered outside the catalog.
        self._extra_roots: Dict[str, Dict[str, Any]] = {}

    # -- constructors ------------------------------------------------------

    @classmethod
    def open(
        cls,
        cache_dir: PathLike,
        *,
        remote: Optional[RemoteBlockStore] = None,
        max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
        max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        **kwargs: Any,
    ) -> "HybridGraphStore":
        cache = VerifiedHybridCache(
            cache_dir,
            max_bytes=max_bytes,
            max_entries=max_entries,
        )
        return cls(cache, remote=remote, **kwargs)

    def close(self) -> None:
        try:
            self.cache.close()
        except Exception:
            logger.debug("cache close failed", exc_info=True)
        try:
            self.remote.close()
        except Exception:
            logger.debug("remote close failed", exc_info=True)

    def _check_cancelled(self) -> None:
        if self._cancel_check is not None:
            self._cancel_check()

    # -- extra roots (tags / snapshots) ------------------------------------

    def register_root(
        self,
        cid: str,
        *,
        kind: str,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        name: Optional[str] = None,
        pin: bool = True,
    ) -> None:
        """Register a durable root (branch head, tag, snapshot, lease)."""
        if kind not in {"branch", "tag", "snapshot", "lease", "manifest", "pin", "staged"}:
            raise GraphStoreError(
                "INVALID_REQUEST",
                f"unknown root kind: {kind!r}",
                details={"kind": kind},
            )
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "cid must be non-empty")
        cid = cid.strip()
        with self._lock:
            self._extra_roots[cid] = {
                "cid": cid,
                "kind": kind,
                "tenant": tenant,
                "graph_id": graph_id,
                "name": name,
            }
        if pin:
            self.pin(cid, root_kind=kind)

    def unregister_root(self, cid: str) -> None:
        with self._lock:
            self._extra_roots.pop(cid, None)

    def list_registered_roots(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._extra_roots.values()]

    # -- put / get ---------------------------------------------------------

    def put(
        self,
        data: bytes,
        *,
        codec: str = "raw",
        pin: Optional[bool] = None,
        staged: bool = False,
        lease_id: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        revision_id: Optional[str] = None,
        root_kind: Optional[str] = None,
        descriptor: Optional[ObjectDescriptor] = None,
    ) -> PutResult:
        """Store bytes on the remote (authoritative) and optionally cache."""
        self._check_cancelled()
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise GraphStoreError(
                "INVALID_REQUEST",
                "put requires bytes",
                details={"type": type(data).__name__},
            )
        payload = bytes(data)
        codec_n = normalize_codec(codec)
        if descriptor is not None:
            verify_against_descriptor(payload, descriptor, verify_cid=True)
            codec_n = descriptor.codec

        should_pin = self.pin_by_default if pin is None else bool(pin)
        if staged:
            # Staged objects are not pin roots until commit.
            should_pin = False if pin is None else bool(pin)

        remote_result = self.remote.put(payload, codec=codec_n, pin=should_pin and not staged)
        cid = remote_result.cid
        if descriptor is not None and descriptor.cid != cid:
            # Ensure remote identity matches descriptor.
            verify_bytes_against_cid(descriptor.cid, payload, expected_codec=codec_n)
            cid = descriptor.cid

        auth = (
            AuthoritativeCopy.STAGED
            if staged
            else (
                AuthoritativeCopy.REMOTE_ROOT
                if self.remote_is_authoritative
                else AuthoritativeCopy.LOCAL_CACHE
            )
        )
        life = ObjectLifecycle.STAGED if staged else ObjectLifecycle.COMMITTED

        if self.cache_on_put or staged:
            self.cache.put(
                payload,
                descriptor=descriptor
                or ObjectDescriptor(
                    cid=cid,
                    codec=codec_n,
                    size=len(payload),
                    sha256=sha256_bytes(payload),
                ),
                codec=codec_n,
                authoritative=auth,
                lifecycle=life,
                pin=should_pin,
                lease_id=lease_id,
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
                root_kind=root_kind or ("staged" if staged else None),
            )
        else:
            self.cache.record_authoritative(
                cid,
                auth,
                remote_root=cid,
                details={"size": len(payload), "codec": codec_n},
            )

        if should_pin:
            self.pin(cid, root_kind=root_kind)

        return PutResult(
            cid=cid,
            codec=codec_n,
            size=len(payload),
            pinned=should_pin,
        )

    def get(
        self,
        cid: str,
        *,
        expected_codec: Optional[str] = None,
        descriptor: Optional[ObjectDescriptor] = None,
    ) -> bytes:
        """Fetch verified bytes: cache first, then remote."""
        self._check_cancelled()
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "cid must be a non-empty string")
        cid = cid.strip()

        # Cache path.
        if self.cache.contains(cid):
            try:
                return self.cache.get(
                    cid,
                    descriptor=descriptor,
                    expected_codec=expected_codec,
                )
            except GraphStoreError as err:
                if err.code == "INTEGRITY":
                    # Drop corrupt cache entry and fall through to remote.
                    logger.warning("dropping corrupt cache entry %s: %s", cid, err)
                    try:
                        self.cache.delete(cid, force=True)
                    except GraphStoreError:
                        pass
                elif err.code != "NOT_FOUND":
                    raise

        # Remote path.
        data = self.remote.get(cid, expected_codec=expected_codec)
        payload = bytes(data)
        if descriptor is not None:
            verify_against_descriptor(payload, descriptor, verify_cid=True)
        else:
            verify_bytes_against_cid(cid, payload, expected_codec=expected_codec)

        if self.cache_on_get:
            try:
                self.cache.put(
                    payload,
                    descriptor=descriptor
                    or ObjectDescriptor(
                        cid=cid,
                        codec=expected_codec or "raw",
                        size=len(payload),
                        sha256=sha256_bytes(payload),
                    ),
                    authoritative=AuthoritativeCopy.REMOTE_ROOT
                    if self.remote_is_authoritative
                    else AuthoritativeCopy.LOCAL_CACHE,
                    lifecycle=ObjectLifecycle.COMMITTED,
                    pin=False,
                )
                self.cache.record_authoritative(
                    cid,
                    AuthoritativeCopy.REMOTE_ROOT
                    if self.remote_is_authoritative
                    else AuthoritativeCopy.LOCAL_CACHE,
                    local_path=str(self.cache._object_path(cid)),
                    remote_root=cid,
                )
            except GraphStoreError:
                logger.debug("cache fill failed for %s", cid, exc_info=True)
        return payload

    def has(self, cid: str) -> bool:
        if self.cache.contains(cid):
            return True
        try:
            return bool(self.remote.has(cid))
        except GraphStoreError as err:
            if err.code == "NOT_FOUND":
                return False
            raise

    # -- pin / unpin -------------------------------------------------------

    def pin(self, cid: str, *, root_kind: Optional[str] = None) -> None:
        self._check_cancelled()
        try:
            self.remote.pin(cid)
        except GraphStoreError as err:
            # Remote may not have the block if only cached; still pin locally.
            if err.code not in {"NOT_FOUND", "NOT_IMPLEMENTED"}:
                raise
        if self.cache.contains(cid):
            self.cache.pin(cid)
            if root_kind is not None:
                self.cache.set_lifecycle(
                    cid,
                    ObjectLifecycle.COMMITTED,
                    root_kind=root_kind,
                )
        else:
            # Ensure authority notes a pin root even without local bytes.
            self.cache.record_authoritative(
                cid,
                AuthoritativeCopy.REMOTE_ROOT,
                remote_root=cid,
                details={"pinned": True, "root_kind": root_kind},
            )

    def unpin(self, cid: str) -> None:
        self._check_cancelled()
        try:
            self.remote.unpin(cid)
        except GraphStoreError as err:
            if err.code not in {"NOT_FOUND", "NOT_IMPLEMENTED"}:
                raise
        if self.cache.contains(cid):
            self.cache.unpin(cid)

    def is_pinned(self, cid: str) -> bool:
        if self.cache.is_pinned(cid):
            return True
        try:
            return bool(self.remote.is_pinned(cid))
        except GraphStoreError:
            return False

    # -- staged lifecycle --------------------------------------------------

    def stage(
        self,
        data: bytes,
        *,
        codec: str = "raw",
        lease_id: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        descriptor: Optional[ObjectDescriptor] = None,
    ) -> PutResult:
        """Stage an object that is not yet a catalog pin root."""
        return self.put(
            data,
            codec=codec,
            pin=False,
            staged=True,
            lease_id=lease_id,
            tenant=tenant,
            graph_id=graph_id,
            root_kind="staged",
            descriptor=descriptor,
        )

    def commit_staged(
        self,
        cid: str,
        *,
        root_kind: str = "manifest",
        pin: bool = True,
        revision_id: Optional[str] = None,
    ) -> None:
        """Promote a staged object to committed (+ optional pin root)."""
        if self.cache.contains(cid):
            self.cache.set_lifecycle(
                cid,
                ObjectLifecycle.COMMITTED,
                root_kind=root_kind,
            )
        if pin:
            self.pin(cid, root_kind=root_kind)
        self.cache.record_authoritative(
            cid,
            AuthoritativeCopy.REMOTE_ROOT
            if self.remote_is_authoritative
            else AuthoritativeCopy.LOCAL_CACHE,
            remote_root=cid,
            details={"committed": True, "root_kind": root_kind, "revision_id": revision_id},
        )

    def abandon_staged(self, cid: str) -> None:
        """Mark a staged object abandoned (eligible for GC)."""
        if not self.cache.contains(cid):
            # Still record abandonment for inventory/GC.
            self.cache.record_authoritative(
                cid,
                AuthoritativeCopy.STAGED,
                remote_root=cid,
                details={"lifecycle": ObjectLifecycle.ABANDONED.value},
            )
            return
        self.cache.mark_abandoned(cid)
        # Ensure not pinned.
        meta = self.cache.get_meta(cid)
        while meta is not None and meta.pin_count > 0:
            meta = self.cache.unpin(cid)

    def list_staged(self) -> List[CacheEntryMeta]:
        return self.cache.list_entries(lifecycle=ObjectLifecycle.STAGED)

    def list_abandoned(self) -> List[CacheEntryMeta]:
        return self.cache.list_entries(lifecycle=ObjectLifecycle.ABANDONED)

    # -- inventory for GC --------------------------------------------------

    def list_objects(self) -> List[CacheEntryMeta]:
        return self.cache.list_entries()

    def delete_object(self, cid: str, *, force: bool = False) -> bool:
        """Remove object from cache and unpin remote when force/abandoned."""
        deleted = False
        if self.cache.contains(cid):
            deleted = self.cache.delete(cid, force=force)
        try:
            if force or not self.is_pinned(cid):
                self.remote.unpin(cid)
        except GraphStoreError:
            pass
        # Best-effort remote block removal when backend supports it.
        backend = getattr(self.remote, "_backend", None)
        if backend is not None and hasattr(backend, "_blocks"):
            try:
                with getattr(backend, "_lock", threading.RLock()):
                    backend._blocks.pop(cid, None)  # type: ignore[attr-defined]
                    if hasattr(backend, "_pins"):
                        backend._pins.discard(cid)  # type: ignore[attr-defined]
            except Exception:
                pass
        return deleted

    def get_authority(self, cid: str) -> Optional[AuthorityRecord]:
        return self.cache.get_authority(cid)


def create_hybrid_graph_store(
    cache_dir: PathLike,
    *,
    remote: Optional[RemoteBlockStore] = None,
    remote_mode: str = "memory",
    max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
    max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
    pin_by_default: bool = True,
) -> HybridGraphStore:
    """Factory for a hybrid store with a deterministic remote by default."""
    if remote is None:
        if remote_mode in {"memory", "mem"}:
            remote = IPLDGraphStore.open_memory(pin_by_default=pin_by_default)
        elif remote_mode in {"directory", "fs", "filesystem"}:
            remote = IPLDGraphStore.open_directory(
                Path(cache_dir) / "remote-blocks",
                pin_by_default=pin_by_default,
            )
        else:
            remote = IPLDGraphStore.open_auto(pin_by_default=pin_by_default)
    return HybridGraphStore.open(
        cache_dir,
        remote=remote,
        max_bytes=max_bytes,
        max_entries=max_entries,
        pin_by_default=pin_by_default,
    )


__all__ = [
    "STORAGE_PROFILE",
    "DEFAULT_CACHE_MAX_BYTES",
    "DEFAULT_CACHE_MAX_ENTRIES",
    "AuthoritativeCopy",
    "ObjectLifecycle",
    "ObjectDescriptor",
    "CacheEntryMeta",
    "AuthorityRecord",
    "VerifiedHybridCache",
    "HybridGraphStore",
    "RemoteBlockStore",
    "atomic_write_bytes",
    "atomic_write_json",
    "verify_against_descriptor",
    "sha256_bytes",
    "create_hybrid_graph_store",
    "GraphStoreError",
]
