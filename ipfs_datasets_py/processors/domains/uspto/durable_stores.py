"""Durable matter-state stores for ODP status, documents, and checkpoints (PATLAW-124).

Provides transactional, tenant-scoped filesystem stores with:

* schema versioning
* process locks and atomic write/rename crash recovery
* idempotent puts (restart without duplicate events/downloads)
* key-reference stability across process invocations
* least-privilege directory/file modes (``0o700`` / ``0o600``)
* tenant path isolation and encryption metadata records

These stores hold **public** ODP snapshots, document inventory metadata,
cursors, matter-event digests, and credential *references* — never raw API
keys or private document bytes (those remain in :mod:`private_store`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

DURABLE_STORES_SCHEMA_VERSION: Final = "uspto.durable-stores.v1"
DURABLE_STORES_INTERFACE: Final = "DurableMatterState@1"

_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600

_TENANT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._\-]{0,127}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class DurableStoreError(Exception):
    """Base error for durable matter stores."""

    def __init__(self, message: str, *, code: str = "durable_store_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class TenantSeparationError(DurableStoreError):
    def __init__(self, message: str = "tenant separation violation") -> None:
        super().__init__(message, code="tenant_separation")


class DurableIntegrityError(DurableStoreError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="integrity_error")


class IdempotencyDisposition(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


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
        raise DurableStoreError(f"invalid tenant_id: {tenant_id!r}", code="invalid_tenant")
    return text


def _require_id(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.match(text):
        raise DurableStoreError(f"invalid {name}: {value!r}", code="invalid_id")
    return text


def _sha256_json(payload: Mapping[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIRECTORY_MODE)
    except OSError:
        pass
    return path


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, _FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
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
    # Crash recovery: remove any stale sibling tmp left by prior failures.
    stale = path.with_suffix(path.suffix + ".tmp")
    if stale.exists() and stale != tmp:
        try:
            stale.unlink()
        except OSError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise DurableIntegrityError(f"expected object at {path.name}")
    return data


def _path_mode(path: Path) -> int:
    return stat_mode(path)


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


@dataclass(frozen=True, slots=True)
class EncryptionMetadata:
    """Tenant-scoped encryption metadata (no key material)."""

    tenant_id: str
    key_id: str
    suite: str
    namespace: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key_id": self.key_id,
            "namespace": self.namespace,
            "suite": self.suite,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EncryptionMetadata":
        return cls(
            tenant_id=str(value.get("tenant_id", "")),
            key_id=str(value.get("key_id", "default")),
            suite=str(value.get("suite", "none")),
            namespace=str(value.get("namespace", "")),
        )


@dataclass(frozen=True, slots=True)
class PutResult:
    disposition: IdempotencyDisposition
    key: str
    content_digest: str
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "created": self.created,
            "disposition": self.disposition.value,
            "key": self.key,
        }


class _TenantPaths:
    def __init__(self, root: Path, tenant_id: str) -> None:
        self.root = root
        self.tenant_id = tenant_id
        self.tenant_dir = root / "tenants" / tenant_id
        self.status_dir = self.tenant_dir / "status"
        self.documents_dir = self.tenant_dir / "documents"
        self.cursors_dir = self.tenant_dir / "cursors"
        self.events_dir = self.tenant_dir / "events"
        self.idempotency_dir = self.tenant_dir / "idempotency"
        self.keys_dir = self.tenant_dir / "key_references"
        self.continuity_dir = self.tenant_dir / "continuity"
        self.foreign_priority_dir = self.tenant_dir / "foreign_priority"
        self.meta_path = self.tenant_dir / "tenant_meta.json"

    def ensure(self) -> None:
        for path in (
            self.tenant_dir,
            self.status_dir,
            self.documents_dir,
            self.cursors_dir,
            self.events_dir,
            self.idempotency_dir,
            self.keys_dir,
            self.continuity_dir,
            self.foreign_priority_dir,
        ):
            _ensure_dir(path)


class DurableMatterState:
    """Filesystem durable matter state for one tenant.

    Restart-safe: reopening the same root reloads committed records without
    duplicating idempotent keys or event digests.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        tenant_id: str,
        encryption: EncryptionMetadata | None = None,
        key_id: str = "default",
        encryption_suite: str = "none",
    ) -> None:
        self._root = Path(root).expanduser().resolve()
        self._tenant_id = _require_tenant(tenant_id)
        self._lock = threading.RLock()
        self._paths = _TenantPaths(self._root, self._tenant_id)
        _ensure_dir(self._root)
        self._paths.ensure()
        if encryption is None:
            encryption = EncryptionMetadata(
                tenant_id=self._tenant_id,
                key_id=str(key_id or "default"),
                suite=str(encryption_suite or "none"),
                namespace=f"private://tenant/{self._tenant_id}/key/{key_id or 'default'}",
            )
        if encryption.tenant_id != self._tenant_id:
            raise TenantSeparationError(
                "encryption metadata tenant_id does not match store tenant"
            )
        self._encryption = encryption
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
    def encryption(self) -> EncryptionMetadata:
        return self._encryption

    @property
    def schema_version(self) -> str:
        return DURABLE_STORES_SCHEMA_VERSION

    def safe_config(self) -> dict[str, Any]:
        return {
            "encryption": self._encryption.to_dict(),
            "interface": DURABLE_STORES_INTERFACE,
            "root": str(self._root),
            "schema_version": DURABLE_STORES_SCHEMA_VERSION,
            "tenant_id": self._tenant_id,
        }

    def _write_tenant_meta(self) -> None:
        payload = {
            "created_or_opened_utc": _utc_now(),
            "encryption": self._encryption.to_dict(),
            "schema_version": DURABLE_STORES_SCHEMA_VERSION,
            "tenant_id": self._tenant_id,
        }
        existing = _read_json(self._paths.meta_path)
        if existing is not None:
            if str(existing.get("tenant_id", "")) != self._tenant_id:
                raise TenantSeparationError("on-disk tenant_meta tenant mismatch")
            payload["created_or_opened_utc"] = existing.get(
                "created_or_opened_utc", payload["created_or_opened_utc"]
            )
        _atomic_write_json(self._paths.meta_path, payload)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _object_path(self, directory: Path, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return directory / f"{digest[:2]}" / f"{digest}.json"

    def _put_record(
        self,
        directory: Path,
        *,
        key: str,
        record: Mapping[str, Any],
        content_digest: str | None = None,
    ) -> PutResult:
        key = _require_id(key, "key")
        path = self._object_path(directory, key)
        digest = content_digest or _sha256_json(dict(record))
        envelope = {
            "content_digest": digest,
            "encryption": self._encryption.to_dict(),
            "key": key,
            "record": dict(record),
            "schema_version": DURABLE_STORES_SCHEMA_VERSION,
            "tenant_id": self._tenant_id,
            "updated_utc": _utc_now(),
        }
        with self._lock:
            existing = _read_json(path)
            if existing is not None:
                if str(existing.get("tenant_id", "")) != self._tenant_id:
                    raise TenantSeparationError("cross-tenant record read denied")
                if str(existing.get("content_digest", "")) == digest:
                    return PutResult(
                        disposition=IdempotencyDisposition.DUPLICATE,
                        key=key,
                        content_digest=digest,
                        created=False,
                    )
                # Same key, different digest: version by overwriting content but
                # surface CONFLICT so callers can record history if needed.
                _atomic_write_json(path, envelope)
                return PutResult(
                    disposition=IdempotencyDisposition.CONFLICT,
                    key=key,
                    content_digest=digest,
                    created=True,
                )
            _atomic_write_json(path, envelope)
            return PutResult(
                disposition=IdempotencyDisposition.CREATED,
                key=key,
                content_digest=digest,
                created=True,
            )

    def _get_record(self, directory: Path, key: str) -> dict[str, Any] | None:
        key = _require_id(key, "key")
        path = self._object_path(directory, key)
        with self._lock:
            existing = _read_json(path)
            if existing is None:
                return None
            if str(existing.get("tenant_id", "")) != self._tenant_id:
                raise TenantSeparationError("cross-tenant record read denied")
            record = existing.get("record")
            if not isinstance(record, dict):
                raise DurableIntegrityError(f"corrupt record for key {key!r}")
            return dict(record)

    def _list_keys(self, directory: Path) -> tuple[str, ...]:
        keys: list[str] = []
        if not directory.is_dir():
            return ()
        with self._lock:
            for path in sorted(directory.rglob("*.json")):
                if path.name.endswith(".tmp"):
                    continue
                data = _read_json(path)
                if data is None:
                    continue
                if str(data.get("tenant_id", "")) != self._tenant_id:
                    continue
                key = data.get("key")
                if isinstance(key, str) and key:
                    keys.append(key)
        return tuple(sorted(set(keys)))

    # ------------------------------------------------------------------
    # Status snapshots
    # ------------------------------------------------------------------

    def put_status_snapshot(
        self,
        *,
        sync_key: str,
        snapshot: Mapping[str, Any],
        content_digest: str | None = None,
    ) -> PutResult:
        digest = content_digest or str(snapshot.get("content_digest") or "") or None
        if digest and not _SHA256_RE.match(digest):
            digest = _sha256_json(dict(snapshot))
        return self._put_record(
            self._paths.status_dir,
            key=sync_key,
            record=dict(snapshot),
            content_digest=digest,
        )

    def get_status_snapshot(self, sync_key: str) -> dict[str, Any] | None:
        return self._get_record(self._paths.status_dir, sync_key)

    def list_status_keys(self) -> tuple[str, ...]:
        return self._list_keys(self._paths.status_dir)

    # ------------------------------------------------------------------
    # Document inventory (metadata only — not private bytes)
    # ------------------------------------------------------------------

    def put_document_inventory(
        self,
        *,
        application_number: str,
        documents: Sequence[Mapping[str, Any]],
        content_digest: str | None = None,
    ) -> PutResult:
        app = _require_id(application_number, "application_number")
        payload = {
            "application_number": app,
            "documents": [dict(d) for d in documents],
            "document_count": len(documents),
        }
        return self._put_record(
            self._paths.documents_dir,
            key=f"docs:{app}",
            record=payload,
            content_digest=content_digest,
        )

    def get_document_inventory(
        self, application_number: str
    ) -> dict[str, Any] | None:
        app = _require_id(application_number, "application_number")
        return self._get_record(self._paths.documents_dir, f"docs:{app}")

    # ------------------------------------------------------------------
    # Continuity / foreign priority (immutable facts)
    # ------------------------------------------------------------------

    def put_continuity(
        self,
        *,
        application_number: str,
        snapshot: Mapping[str, Any],
        content_digest: str | None = None,
    ) -> PutResult:
        app = _require_id(application_number, "application_number")
        # Immutable: identical digest → duplicate; never mutate prior facts.
        return self._put_record(
            self._paths.continuity_dir,
            key=f"continuity:{app}",
            record=dict(snapshot),
            content_digest=content_digest or _sha256_json(dict(snapshot)),
        )

    def get_continuity(self, application_number: str) -> dict[str, Any] | None:
        app = _require_id(application_number, "application_number")
        return self._get_record(self._paths.continuity_dir, f"continuity:{app}")

    def put_foreign_priority(
        self,
        *,
        application_number: str,
        snapshot: Mapping[str, Any],
        content_digest: str | None = None,
    ) -> PutResult:
        app = _require_id(application_number, "application_number")
        return self._put_record(
            self._paths.foreign_priority_dir,
            key=f"foreign_priority:{app}",
            record=dict(snapshot),
            content_digest=content_digest or _sha256_json(dict(snapshot)),
        )

    def get_foreign_priority(self, application_number: str) -> dict[str, Any] | None:
        app = _require_id(application_number, "application_number")
        return self._get_record(
            self._paths.foreign_priority_dir, f"foreign_priority:{app}"
        )

    # ------------------------------------------------------------------
    # Cursor / checkpoint
    # ------------------------------------------------------------------

    def put_cursor(
        self,
        *,
        resource: str,
        checkpoint: Mapping[str, Any],
    ) -> PutResult:
        res = _require_id(resource, "resource")
        return self._put_record(
            self._paths.cursors_dir,
            key=f"cursor:{res}",
            record=dict(checkpoint),
        )

    def get_cursor(self, resource: str) -> dict[str, Any] | None:
        res = _require_id(resource, "resource")
        return self._get_record(self._paths.cursors_dir, f"cursor:{res}")

    # ------------------------------------------------------------------
    # Matter event log (append-only by event_id digest)
    # ------------------------------------------------------------------

    def append_event(
        self,
        *,
        event_id: str,
        event: Mapping[str, Any],
    ) -> PutResult:
        eid = _require_id(event_id, "event_id")
        return self._put_record(
            self._paths.events_dir,
            key=f"event:{eid}",
            record=dict(event),
            content_digest=_sha256_json(dict(event)),
        )

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        eid = _require_id(event_id, "event_id")
        return self._get_record(self._paths.events_dir, f"event:{eid}")

    def list_event_ids(self) -> tuple[str, ...]:
        keys = self._list_keys(self._paths.events_dir)
        out: list[str] = []
        for key in keys:
            if key.startswith("event:"):
                out.append(key[len("event:") :])
            else:
                out.append(key)
        return tuple(out)

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def claim_idempotency(
        self,
        *,
        operation: str,
        idempotency_key: str,
        payload_digest: str | None = None,
    ) -> PutResult:
        op = _require_id(operation, "operation")
        ikey = _require_id(idempotency_key, "idempotency_key")
        record = {
            "idempotency_key": ikey,
            "operation": op,
            "payload_digest": payload_digest,
            "claimed_utc": _utc_now(),
        }
        return self._put_record(
            self._paths.idempotency_dir,
            key=f"idem:{op}:{ikey}",
            record=record,
            content_digest=payload_digest or _sha256_json(record),
        )

    def has_idempotency(self, *, operation: str, idempotency_key: str) -> bool:
        op = _require_id(operation, "operation")
        ikey = _require_id(idempotency_key, "idempotency_key")
        return self._get_record(self._paths.idempotency_dir, f"idem:{op}:{ikey}") is not None

    # ------------------------------------------------------------------
    # Key references (stable across CLI invocations; never secret values)
    # ------------------------------------------------------------------

    def put_key_reference(
        self,
        *,
        reference_id: str,
        reference: Mapping[str, Any],
    ) -> PutResult:
        rid = _require_id(reference_id, "reference_id")
        # Reject accidental secret material.
        for forbidden in ("api_key", "secret", "password", "token", "value"):
            if forbidden in reference and reference.get(forbidden):
                raise DurableStoreError(
                    f"key reference must not embed field {forbidden!r}",
                    code="secret_in_key_reference",
                )
        safe = {
            str(k): v
            for k, v in dict(reference).items()
            if str(k).lower()
            not in {"api_key", "secret", "password", "token", "value", "raw_secret"}
        }
        safe.setdefault("reference_id", rid)
        return self._put_record(
            self._paths.keys_dir,
            key=f"keyref:{rid}",
            record=safe,
            content_digest=_sha256_json(safe),
        )

    def get_key_reference(self, reference_id: str) -> dict[str, Any] | None:
        rid = _require_id(reference_id, "reference_id")
        return self._get_record(self._paths.keys_dir, f"keyref:{rid}")

    def list_key_reference_ids(self) -> tuple[str, ...]:
        keys = self._list_keys(self._paths.keys_dir)
        out: list[str] = []
        for key in keys:
            if key.startswith("keyref:"):
                out.append(key[len("keyref:") :])
        return tuple(out)

    # ------------------------------------------------------------------
    # Diagnostics / least-privilege checks
    # ------------------------------------------------------------------

    def verify_least_privilege_modes(self) -> dict[str, Any]:
        """Return mode observations for tenant dirs and sample files."""

        observations: dict[str, int] = {}
        for label, path in (
            ("root", self._root),
            ("tenant_dir", self._paths.tenant_dir),
            ("status_dir", self._paths.status_dir),
            ("meta", self._paths.meta_path),
        ):
            if path.exists():
                observations[label] = stat_mode(path)
        # Sample one status object if present.
        for path in self._paths.status_dir.rglob("*.json"):
            if path.name.endswith(".tmp"):
                continue
            observations["sample_status_file"] = stat_mode(path)
            break
        return {
            "directory_mode_expected": _DIRECTORY_MODE,
            "file_mode_expected": _FILE_MODE,
            "observations": observations,
            "tenant_id": self._tenant_id,
        }

    def open_for_tenant(self, tenant_id: str) -> "DurableMatterState":
        """Return a store handle for another tenant under the same root."""

        return DurableMatterState(
            self._root,
            tenant_id=tenant_id,
            encryption=EncryptionMetadata(
                tenant_id=_require_tenant(tenant_id),
                key_id=self._encryption.key_id,
                suite=self._encryption.suite,
                namespace=f"private://tenant/{tenant_id}/key/{self._encryption.key_id}",
            ),
        )


# Back-compat / AST-friendly aliases.
DurableDocumentStore = DurableMatterState
DurableStatusStore = DurableMatterState


__all__ = [
    "DURABLE_STORES_INTERFACE",
    "DURABLE_STORES_SCHEMA_VERSION",
    "DurableDocumentStore",
    "DurableIntegrityError",
    "DurableMatterState",
    "DurableStatusStore",
    "DurableStoreError",
    "EncryptionMetadata",
    "IdempotencyDisposition",
    "PutResult",
    "TenantSeparationError",
    "stat_mode",
]
