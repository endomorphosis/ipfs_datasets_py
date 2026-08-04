"""Crash-safe local persistence for content-addressed patent index snapshots.

Implements :class:`PatentIndexStore` (PATLAW-144) over a tenant-scoped
filesystem layout. Design invariants:

* Snapshots are content-addressed; identical payloads are idempotent, and
  divergent payloads under the same digest fail closed.
* Prior roots (parent, compaction, rollback, checkpoint) are retained
  immutably — resume / tombstone / compact / rollback never rewrite history.
* Corrupt JSON, tenant mismatch, unknown schema versions, and unknown model
  pins fail closed and cannot open a snapshot.
* Every stored record joins to a source CID and version (enforced by the
  contracts layer on put and open).
* Directory/file modes prefer least privilege (``0o700`` / ``0o600``).
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from .index_snapshot_contracts import (
    INDEX_SNAPSHOT_INTERFACE,
    INDEX_SNAPSHOT_SCHEMA_VERSION,
    INDEX_STORE_INTERFACE,
    CheckpointCursor,
    ContentAddress,
    CorruptManifestError,
    CrossTenantManifestError,
    IndexFamily,
    IndexSnapshotError,
    IndexSnapshotManifest,
    IndexSnapshotRecord,
    PartitionClass,
    PatentIndexSnapshot,
    RootPointer,
    SnapshotIdentityBundle,
    SnapshotImmutabilityError,
    SnapshotKind,
    UnknownSchemaVersionError,
    assert_known_model_pin,
    assert_known_schema_version,
    build_tombstone_record,
    canonical_json,
    open_snapshot_payload,
)
from .retrieval_contracts import DisclosureClass

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_TENANT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._\-]{0,127}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")

_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600

SNAPSHOT_FILENAME: Final = "snapshot.json"
MANIFEST_FILENAME: Final = "manifest.json"
HEAD_FILENAME: Final = "HEAD.json"
CHECKPOINT_DIRNAME: Final = "checkpoints"
ROOTS_DIRNAME: Final = "roots"
TENANTS_DIRNAME: Final = "tenants"
META_FILENAME: Final = "tenant_meta.json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IndexStoreError(IndexSnapshotError):
    """Base error for patent index store operations."""

    code = "index_store_error"


class SnapshotNotFoundError(IndexStoreError):
    """Raised when a requested snapshot root is absent."""

    code = "snapshot_not_found"


class CheckpointNotFoundError(IndexStoreError):
    """Raised when a resume checkpoint is absent."""

    code = "checkpoint_not_found"


class TenantSeparationError(IndexStoreError, CrossTenantManifestError):
    """Raised on cross-tenant path or manifest access."""

    code = "tenant_separation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_tenant(tenant_id: str) -> str:
    text = str(tenant_id or "").strip()
    if not _TENANT_RE.match(text):
        raise IndexStoreError(f"invalid tenant_id: {tenant_id!r}", code="invalid_tenant")
    return text


def _require_sha256(value: str, name: str = "digest") -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.match(text):
        raise IndexStoreError(
            f"{name} must be a 64-char lowercase hex SHA-256", code="invalid_digest"
        )
    return text


def _require_id(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.match(text):
        raise IndexStoreError(f"invalid {name}: {value!r}", code="invalid_id")
    return text


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIRECTORY_MODE)
    except OSError:
        pass
    return path


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, _FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if tmp.exists():
                tmp.unlink()
        raise
    os.replace(tmp, path)
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass
    stale = path.with_suffix(path.suffix + ".tmp")
    if stale.exists() and stale != tmp:
        try:
            stale.unlink()
        except OSError:
            pass


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = canonical_json(dict(payload)) + "\n"
    _atomic_write_bytes(path, text.encode("utf-8"))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CorruptManifestError(f"corrupt JSON at {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise CorruptManifestError(f"expected object at {path.name}")
    return data


def _root_pointer_from_snapshot(
    snapshot: PatentIndexSnapshot, *, kind: SnapshotKind, note: str | None = None
) -> RootPointer:
    return RootPointer(
        root_cid=snapshot.root_cid,
        root_digest=snapshot.root_digest,
        kind=kind,
        retained_from_utc=_utc_now(),
        note=note,
    )


# ---------------------------------------------------------------------------
# Put result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PutSnapshotResult:
    """Outcome of a content-addressed snapshot put."""

    root_cid: str
    root_digest: str
    created: bool
    snapshot_id: str
    tenant_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "root_cid": self.root_cid,
            "root_digest": self.root_digest,
            "snapshot_id": self.snapshot_id,
            "tenant_id": self.tenant_id,
        }


# ---------------------------------------------------------------------------
# PatentIndexStore
# ---------------------------------------------------------------------------


class PatentIndexStore:
    """Tenant-scoped, crash-safe content-addressed index snapshot store.

    Layout::

        {root}/tenants/{tenant_id}/
            tenant_meta.json
            HEAD.json
            roots/{sha256}/snapshot.json
            roots/{sha256}/manifest.json
            checkpoints/{checkpoint_id}.json

    Opening a store for tenant A cannot read or write tenant B's objects.
    """

    def __init__(self, root: str | Path, *, tenant_id: str) -> None:
        self._root = Path(root).expanduser().resolve()
        self._tenant_id = _require_tenant(tenant_id)
        self._lock = threading.RLock()
        self._tenant_dir = self._root / TENANTS_DIRNAME / self._tenant_id
        self._roots_dir = self._tenant_dir / ROOTS_DIRNAME
        self._checkpoints_dir = self._tenant_dir / CHECKPOINT_DIRNAME
        self._head_path = self._tenant_dir / HEAD_FILENAME
        self._meta_path = self._tenant_dir / META_FILENAME
        _ensure_dir(self._root)
        _ensure_dir(self._tenant_dir)
        _ensure_dir(self._roots_dir)
        _ensure_dir(self._checkpoints_dir)
        self._write_tenant_meta()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def schema_version(self) -> str:
        return INDEX_SNAPSHOT_SCHEMA_VERSION

    def safe_config(self) -> dict[str, Any]:
        return {
            "interface": INDEX_STORE_INTERFACE,
            "root": str(self._root),
            "schema_version": INDEX_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_interface": INDEX_SNAPSHOT_INTERFACE,
            "tenant_id": self._tenant_id,
        }

    @classmethod
    def open_for_tenant(cls, root: str | Path, tenant_id: str) -> "PatentIndexStore":
        """Open (or create) a store bound to *tenant_id*."""
        return cls(root, tenant_id=tenant_id)

    def _write_tenant_meta(self) -> None:
        payload = {
            "created_or_opened_utc": _utc_now(),
            "interface": INDEX_STORE_INTERFACE,
            "schema_version": INDEX_SNAPSHOT_SCHEMA_VERSION,
            "tenant_id": self._tenant_id,
        }
        existing = None
        if self._meta_path.is_file():
            try:
                existing = _read_json(self._meta_path)
            except CorruptManifestError:
                # Fail closed: do not silently repair a corrupt meta file by
                # overwriting if tenant claim is unreadable — re-raise.
                raise
        if existing is not None:
            if str(existing.get("tenant_id", "")) != self._tenant_id:
                raise TenantSeparationError(
                    "on-disk tenant_meta tenant mismatch"
                )
            on_disk_schema = str(existing.get("schema_version") or "")
            if on_disk_schema and on_disk_schema != INDEX_SNAPSHOT_SCHEMA_VERSION:
                raise UnknownSchemaVersionError(
                    f"store schema_version {on_disk_schema!r} is not supported"
                )
            payload["created_or_opened_utc"] = existing.get(
                "created_or_opened_utc", payload["created_or_opened_utc"]
            )
        _atomic_write_json(self._meta_path, payload)

    def _root_dir(self, digest: str) -> Path:
        return self._roots_dir / digest

    def _snapshot_path(self, digest: str) -> Path:
        return self._root_dir(digest) / SNAPSHOT_FILENAME

    def _manifest_path(self, digest: str) -> Path:
        return self._root_dir(digest) / MANIFEST_FILENAME

    def _assert_tenant_on_payload(self, payload: Mapping[str, Any]) -> None:
        tenant = None
        if isinstance(payload.get("manifest"), Mapping):
            tenant = payload["manifest"].get("tenant_id")
        if tenant is None:
            tenant = payload.get("tenant_id")
        if tenant is None:
            raise CorruptManifestError("payload missing tenant_id")
        if str(tenant) != self._tenant_id:
            raise TenantSeparationError(
                f"cross-tenant access denied: payload tenant {tenant!r}, "
                f"store tenant {self._tenant_id!r}"
            )

    # ------------------------------------------------------------------
    # Snapshot put / get / open
    # ------------------------------------------------------------------

    def put_snapshot(
        self,
        snapshot: PatentIndexSnapshot | Mapping[str, Any],
        *,
        set_head: bool = True,
    ) -> PutSnapshotResult:
        """Persist *snapshot* immutably under its content address."""
        if isinstance(snapshot, Mapping):
            snap = open_snapshot_payload(
                snapshot, expected_tenant_id=self._tenant_id
            )
        elif isinstance(snapshot, PatentIndexSnapshot):
            if snapshot.manifest.tenant_id != self._tenant_id:
                raise TenantSeparationError(
                    f"snapshot tenant {snapshot.manifest.tenant_id!r} does not "
                    f"match store tenant {self._tenant_id!r}"
                )
            # Re-validate model/schema pins on every put.
            assert_known_schema_version(snapshot.manifest.schema_version)
            model = snapshot.manifest.identities.model
            if model is not None:
                assert_known_model_pin(model.model_pin)
            snapshot.verify_source_joins()
            snap = snapshot
        else:
            raise TypeError("snapshot must be PatentIndexSnapshot or mapping")

        address = snap.content_address()
        dest_file = self._snapshot_path(address.sha256)
        payload_bytes = snap.to_canonical_bytes()

        with self._lock:
            if dest_file.is_file():
                existing = dest_file.read_bytes()
                # Allow trailing newline differences only if digests match via
                # re-parse; otherwise exact bytes must match.
                if existing != payload_bytes and existing.rstrip(b"\n") != payload_bytes.rstrip(
                    b"\n"
                ):
                    raise SnapshotImmutabilityError(
                        f"refusing to mutate snapshot {address.sha256}: "
                        "existing bytes differ from new payload"
                    )
                if set_head:
                    self._write_head(address, snap)
                return PutSnapshotResult(
                    root_cid=address.cid,
                    root_digest=address.sha256,
                    created=False,
                    snapshot_id=snap.manifest.snapshot_id,
                    tenant_id=self._tenant_id,
                )

            _ensure_dir(self._root_dir(address.sha256))
            _atomic_write_bytes(dest_file, payload_bytes)
            _atomic_write_json(
                self._manifest_path(address.sha256), snap.manifest.to_dict()
            )
            if set_head:
                self._write_head(address, snap)
            return PutSnapshotResult(
                root_cid=address.cid,
                root_digest=address.sha256,
                created=True,
                snapshot_id=snap.manifest.snapshot_id,
                tenant_id=self._tenant_id,
            )

    def _write_head(
        self, address: ContentAddress, snapshot: PatentIndexSnapshot
    ) -> None:
        head = {
            "root_cid": address.cid,
            "root_digest": address.sha256,
            "schema_version": INDEX_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot.manifest.snapshot_id,
            "tenant_id": self._tenant_id,
            "updated_utc": _utc_now(),
        }
        _atomic_write_json(self._head_path, head)

    def get_snapshot(self, root_digest: str) -> PatentIndexSnapshot:
        """Load a snapshot by content digest; fail closed on corruption."""
        digest = _require_sha256(root_digest, "root_digest")
        path = self._snapshot_path(digest)
        if not path.is_file():
            raise SnapshotNotFoundError(f"snapshot not found: {digest}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CorruptManifestError(f"unable to read snapshot: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorruptManifestError(f"corrupt snapshot JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise CorruptManifestError("snapshot root must be a mapping")
        self._assert_tenant_on_payload(payload)
        snap = open_snapshot_payload(payload, expected_tenant_id=self._tenant_id)
        # Integrity: on-disk digest must match content identity.
        if snap.root_digest != digest:
            raise CorruptManifestError(
                f"snapshot content digest {snap.root_digest} does not match "
                f"path digest {digest}"
            )
        return snap

    def open_snapshot(
        self, root_digest: str | None = None
    ) -> PatentIndexSnapshot:
        """Open HEAD (or *root_digest*) after schema/model/tenant checks."""
        if root_digest is None:
            head = self.get_head()
            if head is None:
                raise SnapshotNotFoundError("store has no HEAD snapshot")
            root_digest = str(head["root_digest"])
        return self.get_snapshot(root_digest)

    def get_head(self) -> dict[str, Any] | None:
        with self._lock:
            data = _read_json(self._head_path)
            if data is None:
                return None
            if str(data.get("tenant_id", "")) != self._tenant_id:
                raise TenantSeparationError("HEAD tenant mismatch")
            schema = str(data.get("schema_version") or "")
            if schema:
                assert_known_schema_version(schema)
            return dict(data)

    def list_root_digests(self) -> tuple[str, ...]:
        if not self._roots_dir.is_dir():
            return ()
        digests: list[str] = []
        with self._lock:
            for child in sorted(self._roots_dir.iterdir()):
                if child.is_dir() and _SHA256_RE.fullmatch(child.name):
                    if (child / SNAPSHOT_FILENAME).is_file():
                        digests.append(child.name)
        return tuple(digests)

    def contains(self, root_digest: str) -> bool:
        digest = _require_sha256(root_digest, "root_digest")
        return self._snapshot_path(digest).is_file()

    # ------------------------------------------------------------------
    # Checkpoints (resume)
    # ------------------------------------------------------------------

    def put_checkpoint(self, cursor: CheckpointCursor | Mapping[str, Any]) -> CheckpointCursor:
        """Write a resume checkpoint retaining the prior committed root."""
        if isinstance(cursor, Mapping):
            cur = CheckpointCursor.from_dict(cursor)
        elif isinstance(cursor, CheckpointCursor):
            cur = cursor
        else:
            raise TypeError("cursor must be CheckpointCursor or mapping")
        if cur.tenant_id != self._tenant_id:
            raise TenantSeparationError(
                f"checkpoint tenant {cur.tenant_id!r} does not match store"
            )
        assert_known_schema_version(cur.schema_version)
        # Prior root must already be durable (or empty store is disallowed).
        if not self.contains(cur.prior_root_digest):
            raise SnapshotNotFoundError(
                f"checkpoint prior_root_digest not found: {cur.prior_root_digest}"
            )
        path = self._checkpoints_dir / f"{cur.checkpoint_id}.json"
        payload = cur.to_dict()
        with self._lock:
            _atomic_write_json(path, payload)
        return cur

    def get_checkpoint(self, checkpoint_id: str) -> CheckpointCursor:
        cid = _require_id(checkpoint_id, "checkpoint_id")
        path = self._checkpoints_dir / f"{cid}.json"
        with self._lock:
            data = _read_json(path)
        if data is None:
            raise CheckpointNotFoundError(f"checkpoint not found: {cid}")
        if str(data.get("tenant_id", "")) != self._tenant_id:
            raise TenantSeparationError("checkpoint tenant mismatch")
        cur = CheckpointCursor.from_dict(data)
        # Prior root must still exist — resume retains immutable prior roots.
        if not self.contains(cur.prior_root_digest):
            raise CorruptManifestError(
                f"checkpoint {cid!r} prior root missing: {cur.prior_root_digest}"
            )
        return cur

    def list_checkpoints(self) -> tuple[str, ...]:
        if not self._checkpoints_dir.is_dir():
            return ()
        names: list[str] = []
        with self._lock:
            for path in sorted(self._checkpoints_dir.glob("*.json")):
                if path.name.endswith(".tmp"):
                    continue
                names.append(path.stem)
        return tuple(names)

    def resume_from_checkpoint(
        self, checkpoint_id: str
    ) -> tuple[CheckpointCursor, PatentIndexSnapshot]:
        """Load checkpoint + its retained prior root snapshot."""
        cur = self.get_checkpoint(checkpoint_id)
        snap = self.get_snapshot(cur.prior_root_digest)
        return cur, snap

    # ------------------------------------------------------------------
    # Tombstone / compact / rollback (retain prior roots)
    # ------------------------------------------------------------------

    def apply_tombstones(
        self,
        *,
        base: PatentIndexSnapshot | str,
        record_ids: Sequence[str],
        snapshot_id: str,
        tombstoned_utc: str | None = None,
        set_head: bool = True,
    ) -> PutSnapshotResult:
        """Produce a new snapshot with tombstones; retain base as prior root."""
        base_snap = (
            self.get_snapshot(base)
            if isinstance(base, str)
            else base
        )
        if base_snap.manifest.tenant_id != self._tenant_id:
            raise TenantSeparationError("base snapshot tenant mismatch")
        # Ensure base is durable so the prior root is retained on disk.
        base_put = self.put_snapshot(base_snap, set_head=False)
        when = tombstoned_utc or _utc_now()
        by_id = dict(base_snap.records_by_id())
        new_records: list[IndexSnapshotRecord] = []
        tombstoned: set[str] = set()
        for rid in record_ids:
            if rid not in by_id:
                raise IndexStoreError(f"record not found for tombstone: {rid!r}")
            prior = by_id[rid]
            if prior.is_tombstone():
                new_records.append(prior)
            else:
                new_records.append(
                    build_tombstone_record(prior, tombstoned_utc=when)
                )
            tombstoned.add(rid)
        for rid, rec in by_id.items():
            if rid not in tombstoned:
                new_records.append(rec)
        prior_ptr = RootPointer(
            root_cid=base_put.root_cid,
            root_digest=base_put.root_digest,
            kind=base_snap.manifest.kind,
            retained_from_utc=when,
            note="tombstone_base",
        )
        prior_roots = list(base_snap.manifest.prior_roots) + [prior_ptr]
        tombstone_count = sum(1 for r in new_records if r.is_tombstone())
        active = len(new_records) - tombstone_count
        manifest = IndexSnapshotManifest(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=snapshot_id,
            tenant_id=self._tenant_id,
            partition=base_snap.manifest.partition,
            kind=SnapshotKind.INCREMENTAL,
            identities=base_snap.manifest.identities,
            families=base_snap.manifest.families,
            record_count=len(new_records),
            tombstone_count=tombstone_count,
            active_record_count=active,
            created_utc=when,
            parent_root=prior_ptr,
            compaction_root=base_snap.manifest.compaction_root,
            rollback_root=base_snap.manifest.rollback_root,
            prior_roots=tuple(prior_roots),
            checkpoint=None,
            allowed_disclosures=base_snap.manifest.allowed_disclosures,
            metadata=dict(base_snap.manifest.metadata),
        )
        snap = PatentIndexSnapshot(manifest=manifest, records=tuple(new_records))
        return self.put_snapshot(snap, set_head=set_head)

    def compact(
        self,
        *,
        base: PatentIndexSnapshot | str,
        snapshot_id: str,
        set_head: bool = True,
        created_utc: str | None = None,
    ) -> PutSnapshotResult:
        """Compact active records into a new root; retain base as compaction_root."""
        base_snap = (
            self.get_snapshot(base)
            if isinstance(base, str)
            else base
        )
        if base_snap.manifest.tenant_id != self._tenant_id:
            raise TenantSeparationError("base snapshot tenant mismatch")
        base_put = self.put_snapshot(base_snap, set_head=False)
        when = created_utc or _utc_now()
        active = list(base_snap.active_records())
        compaction_ptr = RootPointer(
            root_cid=base_put.root_cid,
            root_digest=base_put.root_digest,
            kind=base_snap.manifest.kind,
            retained_from_utc=when,
            note="compaction_source",
        )
        prior_roots = list(base_snap.manifest.retained_prior_roots()) + [
            compaction_ptr
        ]
        manifest = IndexSnapshotManifest(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=snapshot_id,
            tenant_id=self._tenant_id,
            partition=base_snap.manifest.partition,
            kind=SnapshotKind.COMPACTION,
            identities=base_snap.manifest.identities,
            families=base_snap.manifest.families,
            record_count=len(active),
            tombstone_count=0,
            active_record_count=len(active),
            created_utc=when,
            parent_root=compaction_ptr,
            compaction_root=compaction_ptr,
            rollback_root=base_snap.manifest.rollback_root,
            prior_roots=tuple(prior_roots),
            checkpoint=None,
            allowed_disclosures=base_snap.manifest.allowed_disclosures,
            metadata=dict(base_snap.manifest.metadata),
        )
        snap = PatentIndexSnapshot(manifest=manifest, records=tuple(active))
        return self.put_snapshot(snap, set_head=set_head)

    def rollback(
        self,
        *,
        target_root_digest: str,
        current: PatentIndexSnapshot | str | None = None,
        snapshot_id: str,
        set_head: bool = True,
        created_utc: str | None = None,
    ) -> PutSnapshotResult:
        """Point HEAD at a historical root via a rollback snapshot.

        The historical target and the previous HEAD remain durable under their
        original digests; the new rollback snapshot records both as retained
        prior roots.
        """
        target = self.get_snapshot(target_root_digest)
        when = created_utc or _utc_now()
        if current is None:
            head = self.get_head()
            if head is None:
                current_snap = None
            else:
                current_snap = self.get_snapshot(str(head["root_digest"]))
        elif isinstance(current, str):
            current_snap = self.get_snapshot(current)
        else:
            current_snap = current
            self.put_snapshot(current_snap, set_head=False)

        target_ptr = RootPointer(
            root_cid=target.root_cid,
            root_digest=target.root_digest,
            kind=target.manifest.kind,
            retained_from_utc=when,
            note="rollback_target",
        )
        prior_roots = list(target.manifest.retained_prior_roots()) + [target_ptr]
        rollback_from: RootPointer | None = None
        if current_snap is not None:
            rollback_from = RootPointer(
                root_cid=current_snap.root_cid,
                root_digest=current_snap.root_digest,
                kind=current_snap.manifest.kind,
                retained_from_utc=when,
                note="rollback_from",
            )
            if all(
                p.root_digest != rollback_from.root_digest for p in prior_roots
            ):
                prior_roots.append(rollback_from)

        # Rollback snapshot re-materializes the target record log under a new
        # snapshot_id so the operation is explicit and auditable, while the
        # target root itself remains immutable on disk.
        manifest = IndexSnapshotManifest(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=snapshot_id,
            tenant_id=self._tenant_id,
            partition=target.manifest.partition,
            kind=SnapshotKind.ROLLBACK,
            identities=target.manifest.identities,
            families=target.manifest.families,
            record_count=target.manifest.record_count,
            tombstone_count=target.manifest.tombstone_count,
            active_record_count=target.manifest.active_record_count,
            created_utc=when,
            parent_root=target_ptr,
            compaction_root=target.manifest.compaction_root,
            rollback_root=target_ptr,
            prior_roots=tuple(prior_roots),
            checkpoint=None,
            allowed_disclosures=target.manifest.allowed_disclosures,
            metadata=dict(target.manifest.metadata),
        )
        snap = PatentIndexSnapshot(
            manifest=manifest, records=target.records
        )
        result = self.put_snapshot(snap, set_head=set_head)
        # Historical roots must still be loadable.
        assert self.contains(target.root_digest)
        if current_snap is not None:
            assert self.contains(current_snap.root_digest)
        return result

    # ------------------------------------------------------------------
    # Build helpers exposed for tests / builders
    # ------------------------------------------------------------------

    def build_and_put(
        self,
        *,
        snapshot_id: str,
        identities: SnapshotIdentityBundle,
        records: Sequence[IndexSnapshotRecord],
        families: Sequence[IndexFamily] | None = None,
        partition: PartitionClass = PartitionClass.PUBLIC,
        kind: SnapshotKind = SnapshotKind.FULL,
        allowed_disclosures: Sequence[DisclosureClass] | None = None,
        parent_root: RootPointer | None = None,
        created_utc: str | None = None,
        set_head: bool = True,
        metadata: Mapping[str, str] | None = None,
    ) -> PutSnapshotResult:
        """Assemble a snapshot from records and persist it."""
        recs = tuple(records)
        if any(r.tenant_id != self._tenant_id for r in recs):
            raise TenantSeparationError("record tenant mismatch on build_and_put")
        fams = tuple(families) if families is not None else tuple(
            sorted({r.family for r in recs}, key=lambda f: f.value)
        )
        if not fams and recs:
            fams = (IndexFamily.BM25,)
        if not fams:
            fams = (IndexFamily.BM25,)
        tombstones = sum(1 for r in recs if r.is_tombstone())
        active = len(recs) - tombstones
        when = created_utc or _utc_now()
        disclosures = tuple(allowed_disclosures or ())
        if not disclosures:
            disclosures = tuple(sorted({r.disclosure for r in recs}, key=lambda d: d.value))
        prior: tuple[RootPointer, ...] = ()
        if parent_root is not None:
            prior = (parent_root,)
        manifest = IndexSnapshotManifest(
            schema_version=INDEX_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=snapshot_id,
            tenant_id=self._tenant_id,
            partition=partition,
            kind=kind,
            identities=identities,
            families=fams,
            record_count=len(recs),
            tombstone_count=tombstones,
            active_record_count=active,
            created_utc=when,
            parent_root=parent_root,
            prior_roots=prior,
            allowed_disclosures=disclosures,
            metadata=dict(metadata or {}),
        )
        snap = PatentIndexSnapshot(manifest=manifest, records=recs)
        return self.put_snapshot(snap, set_head=set_head)


__all__ = [
    "INDEX_STORE_INTERFACE",
    "SNAPSHOT_FILENAME",
    "MANIFEST_FILENAME",
    "IndexStoreError",
    "SnapshotNotFoundError",
    "CheckpointNotFoundError",
    "TenantSeparationError",
    "PutSnapshotResult",
    "PatentIndexStore",
    # Re-export contract surface used by callers/tests.
    "PatentIndexSnapshot",
    "IndexSnapshotManifest",
    "IndexSnapshotRecord",
    "CheckpointCursor",
    "RootPointer",
    "SnapshotKind",
    "PartitionClass",
    "IndexFamily",
    "SnapshotIdentityBundle",
    "CorruptManifestError",
    "CrossTenantManifestError",
    "UnknownSchemaVersionError",
    "SnapshotImmutabilityError",
    "open_snapshot_payload",
    "canonical_json",
    "build_tombstone_record",
]
