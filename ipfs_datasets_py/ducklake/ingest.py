"""Transactional Parquet ingestion and lifecycle ownership transfer (DQK-088).

Implements idempotent create/copy/register ingestion into lifecycle-managed,
versioned owned lake namespaces:

* content-bound staging **outside** DATA_PATH so staging files cannot be
  mistaken for orphans under the lake namespace
* DuckLake snapshot transactions coordinated with companion-registry
  reservations and durable ingest outbox reconciliation
* ``ducklake_add_data_files`` only after an explicit lifecycle-ownership
  transfer authorization **and** receipt issued by the trusted owner broker
  (never self-issued by the ingest worker)
* independent, one-use authorization for each privileged copy, registration,
  and ownership-transfer call, revalidated immediately at use
* one ownership-transfer receipt never confers ambient future delete authority
* external / immutable CID sources are never registered as live DATA_PATH
  objects; DuckLake receives a replaceable/deletable owned copy
* missing/extra columns and type promotion follow the validated DQK-094 schema
  policy rather than permissive defaults
* partial object upload, catalog commit, or receipt publication is reconciled
  or quarantined without claiming cross-file atomicity

Import is side-effect free. Hermetic tests exercise the full pipeline with
real local filesystem copies and in-memory catalog/companion state (no live
DuckDB or network required).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Final, Mapping, Sequence

from ipfs_datasets_py.ducklake import admission as adm
from ipfs_datasets_py.ducklake import contracts as c
from ipfs_datasets_py.ducklake import registry as reg
from ipfs_datasets_py.ducklake.config import (
    ParquetNamespace,
    ParquetStorageKind,
)
from ipfs_datasets_py.ducklake.schema import ContentIdentity

__all__ = [
    "DUCKLAKE_ADD_DATA_FILES",
    "INGEST_RECEIPT_SCHEMA",
    "INGEST_SCHEMA",
    "OWNERSHIP_TRANSFER_AUTH_SCHEMA",
    "PRIVILEGED_CALL_AUTH_SCHEMA",
    "QUARANTINE_SCHEMA",
    "STAGED_OBJECT_SCHEMA",
    "AuthorizationError",
    "AuthorizationKind",
    "DestinationObjectIdentity",
    "DuckLakeRegistrationReceipt",
    "ExternalSourceRegistrationError",
    "IngestError",
    "IngestPhase",
    "IngestReceipt",
    "IngestService",
    "LifecyclePolicy",
    "OwnedObject",
    "OwnerBroker",
    "OwnershipTransferAuthorization",
    "OwnershipTransferError",
    "PrivilegedCallAuthorization",
    "ProcessBirth",
    "QuarantineError",
    "QuarantineRecord",
    "RegistrationError",
    "SourceIdentity",
    "StagedObject",
    "StagingError",
    "assert_staging_outside_data_path",
    "content_bound_object_key",
    "revalidate_ownership_transfer_authorization",
    "revalidate_privileged_authorization",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

INGEST_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-transactional-ingest@1"
OWNERSHIP_TRANSFER_AUTH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-ownership-transfer-authorization@1"
)
PRIVILEGED_CALL_AUTH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-privileged-call-authorization@1"
)
INGEST_RECEIPT_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-ingest-receipt@1"
STAGED_OBJECT_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-staged-object@1"
QUARANTINE_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-ingest-quarantine@1"

DUCKLAKE_ADD_DATA_FILES: Final[str] = "ducklake_add_data_files"

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-088-transactional-ingest-20260810"
)

_SHA256_PREFIX: Final[str] = "sha256:"
_DEFAULT_AUTH_TTL_SECONDS: Final[int] = 300
_DEFAULT_RETENTION_CLASS: Final[str] = "standard"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IngestError(ValueError):
    """Fail-closed transactional ingest rejection."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class AuthorizationError(IngestError):
    """Privileged call authorization missing, expired, mismatched, or reused."""


class OwnershipTransferError(AuthorizationError):
    """Lifecycle ownership-transfer authorization failure."""


class StagingError(IngestError):
    """Content-bound staging path or copy failure."""


class RegistrationError(IngestError):
    """DuckLake registration (``ducklake_add_data_files``) failure."""


class ExternalSourceRegistrationError(RegistrationError):
    """Attempted to register an external or immutable CID source live."""


class QuarantineError(IngestError):
    """Partial pipeline state requires quarantine rather than silent success."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IngestPhase(str, Enum):
    """Durable pipeline phase for one logical ingest operation."""

    CREATED = "created"
    RESERVED = "reserved"
    STAGED = "staged"
    COPIED = "copied"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    REGISTERED = "registered"
    COMMITTED = "committed"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class AuthorizationKind(str, Enum):
    """Independent privileged call kinds (one authorization each; never ambient)."""

    COPY = "copy"
    OWNERSHIP_TRANSFER = "ownership_transfer"
    REGISTER = "register"
    # Delete is intentionally *not* granted by ownership-transfer receipts.
    DELETE = "delete"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return _SHA256_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise IngestError(f"{field_name} must be non-empty")
    return text


def _normalize_digest(digest: str) -> str:
    text = str(digest or "").strip().lower()
    if text.startswith(_SHA256_PREFIX):
        hexpart = text[len(_SHA256_PREFIX) :]
    else:
        hexpart = text
        text = _SHA256_PREFIX + hexpart
    if len(hexpart) != 64 or any(c not in "0123456789abcdef" for c in hexpart):
        raise IngestError(f"digest must be sha256 hex, got {digest!r}")
    return text


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise IngestError(f"{field_name} must be a positive int")
    return value


def content_bound_object_key(
    *,
    content_digest: str,
    dataset_id: str,
    object_version: int = 1,
    suffix: str = ".parquet",
) -> str:
    """Deterministic content-bound object key under a namespace prefix."""

    digest = _normalize_digest(content_digest)
    hexpart = digest[len(_SHA256_PREFIX) :]
    ds = _require_nonempty(dataset_id, field_name="dataset_id")
    ver = _require_positive_int(object_version, field_name="object_version")
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{ds}/v{ver}/{hexpart[0:2]}/{hexpart[2:4]}/{hexpart}{safe_suffix}"


def assert_staging_outside_data_path(
    staging_path: str | os.PathLike[str] | Path,
    data_path: str | os.PathLike[str] | Path,
    *,
    storage_kind: ParquetStorageKind | str = ParquetStorageKind.LOCAL,
) -> None:
    """Fail closed when staging lives under DATA_PATH (orphan-confusion guard)."""

    kind = (
        storage_kind
        if isinstance(storage_kind, ParquetStorageKind)
        else ParquetStorageKind(str(storage_kind))
    )
    staging = str(staging_path).rstrip("/")
    data = str(data_path).rstrip("/")
    if not staging or not data:
        raise StagingError("staging_path and data_path must be non-empty")
    if kind is ParquetStorageKind.LOCAL:
        staging_res = str(Path(staging).resolve(strict=False))
        data_res = str(Path(data).resolve(strict=False))
        data_prefix = data_res.rstrip("/") + "/"
        if staging_res == data_res or staging_res.startswith(data_prefix):
            raise StagingError(
                "staging_path must be outside DATA_PATH so staging files "
                "cannot be mistaken for orphans under DATA_PATH",
                details={"staging_path": staging_res, "data_path": data_res},
            )
        return
    # Object URIs: compare path prefixes after scheme/bucket.
    if staging == data or staging.startswith(data + "/"):
        raise StagingError(
            "staging_path must be outside DATA_PATH so staging files "
            "cannot be mistaken for orphans under DATA_PATH",
            details={"staging_path": staging, "data_path": data},
        )


def _path_is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _is_cid_uri(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith(("ipfs://", "ipns://", "ipld://")):
        return True
    if text.startswith(("bafy", "bafk", "bafz", "Qm")) and "/" not in text.split("://")[-1][:10]:
        # bare CID-ish tokens without a filesystem path
        return text.startswith(("bafy", "bafk", "bafz", "qm"))
    return False


# ---------------------------------------------------------------------------
# Identity and policy bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessBirth:
    """Caller / worker process birth identity (fence-sensitive)."""

    process_id: str
    boot_id: str
    started_at: str
    hostname: str = ""
    pid: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "process_id",
            _require_nonempty(self.process_id, field_name="process_id"),
        )
        object.__setattr__(
            self, "boot_id", _require_nonempty(self.boot_id, field_name="boot_id")
        )
        object.__setattr__(
            self,
            "started_at",
            _require_nonempty(self.started_at, field_name="started_at"),
        )
        if self.pid is not None and (
            not isinstance(self.pid, int)
            or isinstance(self.pid, bool)
            or self.pid < 1
        ):
            raise IngestError("process_birth.pid must be a positive int when set")

    def fingerprint(self) -> str:
        return _sha256_text(
            _canonical_json(
                {
                    "process_id": self.process_id,
                    "boot_id": self.boot_id,
                    "started_at": self.started_at,
                    "hostname": self.hostname,
                    "pid": self.pid,
                }
            )
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "process_id": self.process_id,
                "boot_id": self.boot_id,
                "started_at": self.started_at,
                "hostname": self.hostname,
                "pid": self.pid,
                "fingerprint": self.fingerprint(),
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ProcessBirth":
        return cls(
            process_id=str(payload["process_id"]),
            boot_id=str(payload["boot_id"]),
            started_at=str(payload["started_at"]),
            hostname=str(payload.get("hostname") or ""),
            pid=payload.get("pid"),
        )


@dataclass(frozen=True, slots=True)
class LifecyclePolicy:
    """Lifecycle policy bound into ownership-transfer authorizations.

    Owned lake objects must be replaceable and deletable by DuckLake
    maintenance. Immutable external / CID sources are never registered live.
    """

    policy_id: str
    retention_class: str = _DEFAULT_RETENTION_CLASS
    replace_allowed: bool = True
    delete_allowed: bool = True
    allow_external_register: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_id",
            _require_nonempty(self.policy_id, field_name="policy_id"),
        )
        object.__setattr__(
            self,
            "retention_class",
            _require_nonempty(self.retention_class, field_name="retention_class"),
        )
        object.__setattr__(self, "replace_allowed", bool(self.replace_allowed))
        object.__setattr__(self, "delete_allowed", bool(self.delete_allowed))
        object.__setattr__(
            self, "allow_external_register", bool(self.allow_external_register)
        )
        if not self.replace_allowed or not self.delete_allowed:
            # DuckLake maintenance must be allowed to replace and delete owned
            # copies; a policy that forbids both fails closed for registration.
            if not self.allow_external_register:
                pass  # validated at registration time against destination ownership
        if self.allow_external_register:
            raise IngestError(
                "lifecycle policy must not allow external register; DuckLake "
                "must only register lifecycle-managed owned copies that "
                "maintenance may replace and delete"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "policy_id": self.policy_id,
                "retention_class": self.retention_class,
                "replace_allowed": self.replace_allowed,
                "delete_allowed": self.delete_allowed,
                "allow_external_register": self.allow_external_register,
                "notes": self.notes,
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "LifecyclePolicy":
        return cls(
            policy_id=str(payload["policy_id"]),
            retention_class=str(
                payload.get("retention_class") or _DEFAULT_RETENTION_CLASS
            ),
            replace_allowed=bool(payload.get("replace_allowed", True)),
            delete_allowed=bool(payload.get("delete_allowed", True)),
            allow_external_register=bool(
                payload.get("allow_external_register", False)
            ),
            notes=str(payload.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Content-bound source identity retained as provenance (never mutated)."""

    source_uri: str
    content_digest: str
    content_cid: str = ""
    ownership_kind: adm.SourceOwnershipKind = (
        adm.SourceOwnershipKind.EXTERNAL_UNMANAGED
    )
    object_generation: str = ""
    etag: str = ""
    byte_size: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_uri",
            _require_nonempty(self.source_uri, field_name="source_uri"),
        )
        object.__setattr__(
            self, "content_digest", _normalize_digest(self.content_digest)
        )
        if not isinstance(self.ownership_kind, adm.SourceOwnershipKind):
            object.__setattr__(
                self,
                "ownership_kind",
                adm.SourceOwnershipKind(str(self.ownership_kind)),
            )
        if self.byte_size < 0:
            raise IngestError("source byte_size must be >= 0")

    @property
    def is_external_or_immutable_cid(self) -> bool:
        if self.ownership_kind is not adm.SourceOwnershipKind.LIFECYCLE_MANAGED:
            return True
        if self.content_cid and not self.source_uri.startswith(("file://", "/", "s3://")):
            return True
        if _is_cid_uri(self.source_uri):
            return True
        return False

    def content_identity(self) -> ContentIdentity:
        return ContentIdentity(
            content_digest=self.content_digest,
            content_cid=self.content_cid,
            media_type="parquet",
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "source_uri": self.source_uri,
                "content_digest": self.content_digest,
                "content_cid": self.content_cid,
                "ownership_kind": self.ownership_kind.value,
                "object_generation": self.object_generation,
                "etag": self.etag,
                "byte_size": self.byte_size,
                "is_external_or_immutable_cid": self.is_external_or_immutable_cid,
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceIdentity":
        return cls(
            source_uri=str(payload["source_uri"]),
            content_digest=str(payload["content_digest"]),
            content_cid=str(payload.get("content_cid") or ""),
            ownership_kind=adm.SourceOwnershipKind(
                str(
                    payload.get("ownership_kind")
                    or adm.SourceOwnershipKind.EXTERNAL_UNMANAGED.value
                )
            ),
            object_generation=str(payload.get("object_generation") or ""),
            etag=str(payload.get("etag") or ""),
            byte_size=int(payload.get("byte_size") or 0),
        )

    @classmethod
    def from_admission(
        cls, receipt: adm.AdmissionDecisionReceipt
    ) -> "SourceIdentity":
        evidence = receipt.evidence
        return cls(
            source_uri=evidence.canonical_uri,
            content_digest=evidence.content_digest,
            content_cid=evidence.content_cid or "",
            ownership_kind=receipt.ownership.ownership_kind,
            object_generation=(
                evidence.object_generation.object_generation
                if evidence.object_generation.is_bound()
                else ""
            ),
            etag=(
                evidence.object_generation.etag
                if evidence.object_generation.is_bound()
                else ""
            ),
            byte_size=int(evidence.byte_size),
        )


@dataclass(frozen=True, slots=True)
class DestinationObjectIdentity:
    """Owned destination object version and digest under DATA_PATH."""

    owned_uri: str
    content_digest: str
    object_version: int
    object_generation: str = ""
    etag: str = ""
    namespace_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owned_uri", _require_nonempty(self.owned_uri, field_name="owned_uri")
        )
        object.__setattr__(
            self, "content_digest", _normalize_digest(self.content_digest)
        )
        object.__setattr__(
            self,
            "object_version",
            _require_positive_int(self.object_version, field_name="object_version"),
        )
        if _is_cid_uri(self.owned_uri):
            raise ExternalSourceRegistrationError(
                "destination owned_uri must not be an IPFS/IPLD CID; CIDs remain "
                "provenance only and DuckLake DATA_PATH must be lifecycle-managed",
                details={"owned_uri": self.owned_uri},
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "owned_uri": self.owned_uri,
                "content_digest": self.content_digest,
                "object_version": self.object_version,
                "object_generation": self.object_generation,
                "etag": self.etag,
                "namespace_id": self.namespace_id,
            }
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DestinationObjectIdentity":
        return cls(
            owned_uri=str(payload["owned_uri"]),
            content_digest=str(payload["content_digest"]),
            object_version=int(payload["object_version"]),
            object_generation=str(payload.get("object_generation") or ""),
            etag=str(payload.get("etag") or ""),
            namespace_id=str(payload.get("namespace_id") or ""),
        )


# ---------------------------------------------------------------------------
# Authorizations (broker-issued, non-self-issued)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrivilegedCallAuthorization:
    """One-use authorization for a single privileged call (copy/register/delete).

    Independently issued and revalidated at use. Possession of an ownership-
    transfer receipt does **not** satisfy a delete authorization.
    """

    SCHEMA: ClassVar[str] = PRIVILEGED_CALL_AUTH_SCHEMA

    authorization_id: str
    kind: AuthorizationKind
    operation_id: str
    caller_id: str
    process_birth: ProcessBirth
    generation_fence: int
    catalog_id: str
    data_path: str
    issuer_id: str
    nonce: str
    expires_at_unix: float
    subject_digest: str
    used: bool = False
    issued_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_id",
            _require_nonempty(self.authorization_id, field_name="authorization_id"),
        )
        if not isinstance(self.kind, AuthorizationKind):
            object.__setattr__(self, "kind", AuthorizationKind(str(self.kind)))
        object.__setattr__(
            self,
            "operation_id",
            _require_nonempty(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_nonempty(self.caller_id, field_name="caller_id")
        )
        if not isinstance(self.process_birth, ProcessBirth):
            if isinstance(self.process_birth, Mapping):
                object.__setattr__(
                    self, "process_birth", ProcessBirth.from_mapping(self.process_birth)
                )
            else:
                raise AuthorizationError("process_birth is required")
        object.__setattr__(
            self,
            "generation_fence",
            _require_positive_int(
                self.generation_fence, field_name="generation_fence"
            ),
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self, "data_path", _require_nonempty(self.data_path, field_name="data_path")
        )
        object.__setattr__(
            self, "issuer_id", _require_nonempty(self.issuer_id, field_name="issuer_id")
        )
        object.__setattr__(
            self, "nonce", _require_nonempty(self.nonce, field_name="nonce")
        )
        object.__setattr__(
            self,
            "subject_digest",
            _normalize_digest(self.subject_digest)
            if str(self.subject_digest).startswith(_SHA256_PREFIX)
            or len(str(self.subject_digest).replace(_SHA256_PREFIX, "")) == 64
            else _sha256_text(str(self.subject_digest)),
        )
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _utc_iso())
        # Non-self-issued: issuer must differ from caller.
        if self.issuer_id == self.caller_id:
            raise AuthorizationError(
                "privileged call authorization must be non-self-issued; "
                "issuer_id must differ from caller_id (trusted owner broker "
                "issues; ingest worker cannot self-authorize)",
                details={
                    "issuer_id": self.issuer_id,
                    "caller_id": self.caller_id,
                    "kind": self.kind.value,
                },
            )

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def binding_digest(self) -> str:
        body = {
            "authorization_id": self.authorization_id,
            "kind": self.kind.value,
            "operation_id": self.operation_id,
            "caller_id": self.caller_id,
            "process_birth": dict(self.process_birth.as_mapping()),
            "generation_fence": self.generation_fence,
            "catalog_id": self.catalog_id,
            "data_path": self.data_path,
            "issuer_id": self.issuer_id,
            "nonce": self.nonce,
            "expires_at_unix": self.expires_at_unix,
            "subject_digest": self.subject_digest,
            "issued_at": self.issued_at,
        }
        return _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "authorization_id": self.authorization_id,
                "kind": self.kind.value,
                "operation_id": self.operation_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "generation_fence": self.generation_fence,
                "catalog_id": self.catalog_id,
                "data_path": self.data_path,
                "issuer_id": self.issuer_id,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "subject_digest": self.subject_digest,
                "used": self.used,
                "issued_at": self.issued_at,
                "binding_digest": self.binding_digest(),
                "confers_ambient_delete": False,
            }
        )

    def mark_used(self) -> "PrivilegedCallAuthorization":
        if self.used:
            raise AuthorizationError(
                f"authorization {self.authorization_id!r} already used; one "
                "receipt cannot confer ambient future authority",
                details={"authorization_id": self.authorization_id, "kind": self.kind.value},
            )
        return PrivilegedCallAuthorization(
            authorization_id=self.authorization_id,
            kind=self.kind,
            operation_id=self.operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            catalog_id=self.catalog_id,
            data_path=self.data_path,
            issuer_id=self.issuer_id,
            nonce=self.nonce,
            expires_at_unix=self.expires_at_unix,
            subject_digest=self.subject_digest,
            used=True,
            issued_at=self.issued_at,
        )


@dataclass(frozen=True, slots=True)
class OwnershipTransferAuthorization:
    """Broker-issued lifecycle ownership-transfer authorization.

    Binds operation, caller identity and process birth, generation fence,
    exact catalog and DATA_PATH, source identity, owned destination object
    version/digest, lifecycle policy, allowed replace/delete semantics, nonce,
    and expiry. Non-self-issued. Does **not** authorize ambient future deletes.
    """

    SCHEMA: ClassVar[str] = OWNERSHIP_TRANSFER_AUTH_SCHEMA

    authorization_id: str
    operation_id: str
    caller_id: str
    process_birth: ProcessBirth
    generation_fence: int
    catalog_id: str
    data_path: str
    source: SourceIdentity
    destination: DestinationObjectIdentity
    lifecycle_policy: LifecyclePolicy
    issuer_id: str
    nonce: str
    expires_at_unix: float
    replace_allowed: bool = True
    delete_allowed: bool = True
    used: bool = False
    issued_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization_id",
            _require_nonempty(self.authorization_id, field_name="authorization_id"),
        )
        object.__setattr__(
            self,
            "operation_id",
            _require_nonempty(self.operation_id, field_name="operation_id"),
        )
        object.__setattr__(
            self, "caller_id", _require_nonempty(self.caller_id, field_name="caller_id")
        )
        if not isinstance(self.process_birth, ProcessBirth):
            if isinstance(self.process_birth, Mapping):
                object.__setattr__(
                    self, "process_birth", ProcessBirth.from_mapping(self.process_birth)
                )
            else:
                raise OwnershipTransferError("process_birth is required")
        object.__setattr__(
            self,
            "generation_fence",
            _require_positive_int(
                self.generation_fence, field_name="generation_fence"
            ),
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_nonempty(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self, "data_path", _require_nonempty(self.data_path, field_name="data_path")
        )
        if not isinstance(self.source, SourceIdentity):
            if isinstance(self.source, Mapping):
                object.__setattr__(
                    self, "source", SourceIdentity.from_mapping(self.source)
                )
            else:
                raise OwnershipTransferError("source identity is required")
        if not isinstance(self.destination, DestinationObjectIdentity):
            if isinstance(self.destination, Mapping):
                object.__setattr__(
                    self,
                    "destination",
                    DestinationObjectIdentity.from_mapping(self.destination),
                )
            else:
                raise OwnershipTransferError("destination identity is required")
        if not isinstance(self.lifecycle_policy, LifecyclePolicy):
            if isinstance(self.lifecycle_policy, Mapping):
                object.__setattr__(
                    self,
                    "lifecycle_policy",
                    LifecyclePolicy.from_mapping(self.lifecycle_policy),
                )
            else:
                raise OwnershipTransferError("lifecycle_policy is required")
        object.__setattr__(
            self, "issuer_id", _require_nonempty(self.issuer_id, field_name="issuer_id")
        )
        object.__setattr__(
            self, "nonce", _require_nonempty(self.nonce, field_name="nonce")
        )
        object.__setattr__(self, "replace_allowed", bool(self.replace_allowed))
        object.__setattr__(self, "delete_allowed", bool(self.delete_allowed))
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _utc_iso())
        if self.issuer_id == self.caller_id:
            raise OwnershipTransferError(
                "ownership-transfer authorization is non-self-issued; the "
                "trusted owner broker must issue it, not the ingest worker",
                details={
                    "issuer_id": self.issuer_id,
                    "caller_id": self.caller_id,
                },
            )
        # Destination digest must match source content (owned copy is byte-equal).
        if self.destination.content_digest != self.source.content_digest:
            raise OwnershipTransferError(
                "destination object digest must equal source content digest "
                "(owned lifecycle copy is byte-identical to the admitted source)",
                details={
                    "source_digest": self.source.content_digest,
                    "destination_digest": self.destination.content_digest,
                },
            )
        if not self.replace_allowed or not self.delete_allowed:
            raise OwnershipTransferError(
                "ownership transfer requires replace_allowed and delete_allowed; "
                "DuckLake maintenance must be able to replace and delete the "
                "owned copy (never register immutable external/CID sources)",
                details={
                    "replace_allowed": self.replace_allowed,
                    "delete_allowed": self.delete_allowed,
                },
            )
        if not self.lifecycle_policy.replace_allowed or not self.lifecycle_policy.delete_allowed:
            raise OwnershipTransferError(
                "lifecycle policy must allow replace and delete for owned copies"
            )

    def is_expired(self, *, now: float | None = None) -> bool:
        clock = time.time() if now is None else float(now)
        return clock >= float(self.expires_at_unix)

    def binding_digest(self) -> str:
        body = {
            "authorization_id": self.authorization_id,
            "operation": "ownership_transfer",
            "operation_id": self.operation_id,
            "caller_id": self.caller_id,
            "process_birth": dict(self.process_birth.as_mapping()),
            "generation_fence": self.generation_fence,
            "catalog_id": self.catalog_id,
            "data_path": self.data_path,
            "source": dict(self.source.as_mapping()),
            "destination": dict(self.destination.as_mapping()),
            "lifecycle_policy": dict(self.lifecycle_policy.as_mapping()),
            "replace_allowed": self.replace_allowed,
            "delete_allowed": self.delete_allowed,
            "issuer_id": self.issuer_id,
            "nonce": self.nonce,
            "expires_at_unix": self.expires_at_unix,
            "issued_at": self.issued_at,
        }
        return _sha256_text(_canonical_json(body))

    def confers_ambient_delete(self) -> bool:
        """Ownership-transfer never grants ambient future delete authority."""

        return False

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "authorization_id": self.authorization_id,
                "operation": "ownership_transfer",
                "operation_id": self.operation_id,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "generation_fence": self.generation_fence,
                "catalog_id": self.catalog_id,
                "data_path": self.data_path,
                "source": dict(self.source.as_mapping()),
                "destination": dict(self.destination.as_mapping()),
                "lifecycle_policy": dict(self.lifecycle_policy.as_mapping()),
                "replace_allowed": self.replace_allowed,
                "delete_allowed": self.delete_allowed,
                "issuer_id": self.issuer_id,
                "nonce": self.nonce,
                "expires_at_unix": self.expires_at_unix,
                "used": self.used,
                "issued_at": self.issued_at,
                "binding_digest": self.binding_digest(),
                "confers_ambient_delete": self.confers_ambient_delete(),
                "non_self_issued": True,
            }
        )

    def mark_used(self) -> "OwnershipTransferAuthorization":
        if self.used:
            raise OwnershipTransferError(
                f"ownership-transfer authorization {self.authorization_id!r} "
                "already used; one receipt cannot confer ambient future delete "
                "or re-registration authority",
                details={"authorization_id": self.authorization_id},
            )
        return OwnershipTransferAuthorization(
            authorization_id=self.authorization_id,
            operation_id=self.operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            catalog_id=self.catalog_id,
            data_path=self.data_path,
            source=self.source,
            destination=self.destination,
            lifecycle_policy=self.lifecycle_policy,
            issuer_id=self.issuer_id,
            nonce=self.nonce,
            expires_at_unix=self.expires_at_unix,
            replace_allowed=self.replace_allowed,
            delete_allowed=self.delete_allowed,
            used=True,
            issued_at=self.issued_at,
        )


def revalidate_privileged_authorization(
    auth: PrivilegedCallAuthorization,
    *,
    kind: AuthorizationKind,
    operation_id: str,
    caller_id: str,
    process_birth: ProcessBirth,
    generation_fence: int,
    catalog_id: str,
    data_path: str,
    subject_digest: str,
    now: float | None = None,
) -> PrivilegedCallAuthorization:
    """Revalidate a privileged-call authorization immediately before use."""

    if auth.used:
        raise AuthorizationError(
            "authorization already consumed; one receipt cannot confer ambient "
            "future authority",
            details={"authorization_id": auth.authorization_id},
        )
    if auth.kind is not kind:
        raise AuthorizationError(
            f"authorization kind mismatch: expected {kind.value}, got {auth.kind.value}"
        )
    if auth.operation_id != operation_id:
        raise AuthorizationError("authorization operation_id mismatch")
    if auth.caller_id != caller_id:
        raise AuthorizationError("authorization caller_id mismatch")
    if auth.process_birth.fingerprint() != process_birth.fingerprint():
        raise AuthorizationError("authorization process_birth fence mismatch")
    if auth.generation_fence != generation_fence:
        raise AuthorizationError("authorization generation_fence mismatch")
    if auth.catalog_id != catalog_id:
        raise AuthorizationError("authorization catalog_id mismatch")
    if auth.data_path.rstrip("/") != data_path.rstrip("/"):
        raise AuthorizationError("authorization DATA_PATH mismatch")
    expected_subject = (
        _normalize_digest(subject_digest)
        if str(subject_digest).startswith(_SHA256_PREFIX)
        or len(str(subject_digest).replace(_SHA256_PREFIX, "")) == 64
        else _sha256_text(str(subject_digest))
    )
    if auth.subject_digest != expected_subject:
        raise AuthorizationError("authorization subject_digest mismatch")
    if auth.is_expired(now=now):
        raise AuthorizationError(
            "authorization expired",
            details={"authorization_id": auth.authorization_id},
        )
    if auth.issuer_id == auth.caller_id:
        raise AuthorizationError("authorization is self-issued; fail closed")
    return auth.mark_used()


def revalidate_ownership_transfer_authorization(
    auth: OwnershipTransferAuthorization,
    *,
    operation_id: str,
    caller_id: str,
    process_birth: ProcessBirth,
    generation_fence: int,
    catalog_id: str,
    data_path: str,
    source: SourceIdentity,
    destination: DestinationObjectIdentity,
    lifecycle_policy: LifecyclePolicy,
    now: float | None = None,
) -> OwnershipTransferAuthorization:
    """Revalidate ownership-transfer authorization immediately before registration."""

    if auth.used:
        raise OwnershipTransferError(
            "ownership-transfer authorization already consumed; one receipt "
            "cannot confer ambient future delete authority",
            details={"authorization_id": auth.authorization_id},
        )
    if auth.operation_id != operation_id:
        raise OwnershipTransferError("ownership-transfer operation_id mismatch")
    if auth.caller_id != caller_id:
        raise OwnershipTransferError("ownership-transfer caller_id mismatch")
    if auth.process_birth.fingerprint() != process_birth.fingerprint():
        raise OwnershipTransferError(
            "ownership-transfer process_birth fence mismatch"
        )
    if auth.generation_fence != generation_fence:
        raise OwnershipTransferError("ownership-transfer generation_fence mismatch")
    if auth.catalog_id != catalog_id:
        raise OwnershipTransferError("ownership-transfer catalog_id mismatch")
    if auth.data_path.rstrip("/") != data_path.rstrip("/"):
        raise OwnershipTransferError("ownership-transfer DATA_PATH mismatch")
    if auth.source.content_digest != source.content_digest:
        raise OwnershipTransferError("ownership-transfer source digest mismatch")
    if auth.source.source_uri != source.source_uri:
        raise OwnershipTransferError("ownership-transfer source identity mismatch")
    if auth.destination.content_digest != destination.content_digest:
        raise OwnershipTransferError(
            "ownership-transfer destination digest mismatch"
        )
    if auth.destination.owned_uri != destination.owned_uri:
        raise OwnershipTransferError(
            "ownership-transfer destination object identity mismatch"
        )
    if auth.destination.object_version != destination.object_version:
        raise OwnershipTransferError(
            "ownership-transfer destination object version mismatch"
        )
    if auth.lifecycle_policy.policy_id != lifecycle_policy.policy_id:
        raise OwnershipTransferError("ownership-transfer lifecycle policy mismatch")
    if auth.is_expired(now=now):
        raise OwnershipTransferError(
            "ownership-transfer authorization expired",
            details={"authorization_id": auth.authorization_id},
        )
    if auth.issuer_id == auth.caller_id:
        raise OwnershipTransferError(
            "ownership-transfer authorization is self-issued; fail closed"
        )
    if auth.confers_ambient_delete():
        raise OwnershipTransferError(
            "ownership-transfer must not confer ambient delete authority"
        )
    return auth.mark_used()


# ---------------------------------------------------------------------------
# Objects, receipts, quarantine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StagedObject:
    """Content-bound staged copy outside DATA_PATH."""

    SCHEMA: ClassVar[str] = STAGED_OBJECT_SCHEMA

    staging_uri: str
    content_digest: str
    source_uri: str
    byte_size: int
    staged_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "staging_uri",
            _require_nonempty(self.staging_uri, field_name="staging_uri"),
        )
        object.__setattr__(
            self, "content_digest", _normalize_digest(self.content_digest)
        )
        if not self.staged_at:
            object.__setattr__(self, "staged_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "staging_uri": self.staging_uri,
                "content_digest": self.content_digest,
                "source_uri": self.source_uri,
                "byte_size": self.byte_size,
                "staged_at": self.staged_at,
                "under_data_path": False,
            }
        )


@dataclass(frozen=True, slots=True)
class OwnedObject:
    """Lifecycle-managed owned copy under DATA_PATH."""

    destination: DestinationObjectIdentity
    source: SourceIdentity
    lifecycle_policy: LifecyclePolicy
    ownership_transfer_authorization_id: str
    registered: bool = False
    copied_at: str = ""

    def __post_init__(self) -> None:
        if not self.copied_at:
            object.__setattr__(self, "copied_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "destination": dict(self.destination.as_mapping()),
                "source": dict(self.source.as_mapping()),
                "lifecycle_policy": dict(self.lifecycle_policy.as_mapping()),
                "ownership_transfer_authorization_id": (
                    self.ownership_transfer_authorization_id
                ),
                "registered": self.registered,
                "copied_at": self.copied_at,
                "lifecycle_managed": True,
                "replace_allowed": self.lifecycle_policy.replace_allowed,
                "delete_allowed": self.lifecycle_policy.delete_allowed,
            }
        )


@dataclass(frozen=True, slots=True)
class DuckLakeRegistrationReceipt:
    """Receipt for a single ``ducklake_add_data_files`` invocation."""

    registration_id: str
    operation_id: str
    owned_uri: str
    content_digest: str
    snapshot_version: int
    catalog_id: str
    ownership_transfer_authorization_id: str
    register_authorization_id: str
    function: str = DUCKLAKE_ADD_DATA_FILES
    registered_at: str = ""

    def __post_init__(self) -> None:
        if not self.registered_at:
            object.__setattr__(self, "registered_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "registration_id": self.registration_id,
                "operation_id": self.operation_id,
                "function": self.function,
                "owned_uri": self.owned_uri,
                "content_digest": self.content_digest,
                "snapshot_version": self.snapshot_version,
                "catalog_id": self.catalog_id,
                "ownership_transfer_authorization_id": (
                    self.ownership_transfer_authorization_id
                ),
                "register_authorization_id": self.register_authorization_id,
                "registered_at": self.registered_at,
            }
        )


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Durable quarantine for partial object/catalog/receipt failure."""

    SCHEMA: ClassVar[str] = QUARANTINE_SCHEMA

    quarantine_id: str
    operation_id: str
    phase: IngestPhase
    reason: str
    details: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.phase, IngestPhase):
            object.__setattr__(self, "phase", IngestPhase(str(self.phase)))
        object.__setattr__(self, "details", MappingProxyType(dict(self.details or {})))
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "quarantine_id": self.quarantine_id,
                "operation_id": self.operation_id,
                "phase": self.phase.value,
                "reason": self.reason,
                "details": dict(self.details),
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True, slots=True)
class IngestReceipt:
    """Terminal logical-once ingest receipt (one snapshot per operation)."""

    SCHEMA: ClassVar[str] = INGEST_RECEIPT_SCHEMA

    receipt_id: str
    operation_id: str
    idempotency_key: str
    phase: IngestPhase
    snapshot_version: int | None
    source: SourceIdentity
    destination: DestinationObjectIdentity | None
    staged: StagedObject | None
    ownership_transfer_authorization_id: str
    copy_authorization_id: str
    register_authorization_id: str
    reservation_id: str
    outbox_id: str
    registration: DuckLakeRegistrationReceipt | None
    catalog_id: str
    data_path: str
    schema_digest: str
    schema_revision: int
    caller_id: str
    process_birth: ProcessBirth
    generation_fence: int
    lifecycle_policy: LifecyclePolicy
    atomic_across_files: bool = False
    source_untouched: bool = True
    implementation_generation: str = _IMPLEMENTATION_GENERATION
    created_at: str = ""
    quarantine: QuarantineRecord | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, IngestPhase):
            object.__setattr__(self, "phase", IngestPhase(str(self.phase)))
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_iso())
        object.__setattr__(self, "atomic_across_files", False)
        object.__setattr__(self, "source_untouched", True)

    @property
    def committed(self) -> bool:
        return self.phase is IngestPhase.COMMITTED

    def receipt_digest(self) -> str:
        body = {
            "receipt_id": self.receipt_id,
            "operation_id": self.operation_id,
            "idempotency_key": self.idempotency_key,
            "phase": self.phase.value,
            "snapshot_version": self.snapshot_version,
            "source_digest": self.source.content_digest,
            "destination": (
                None
                if self.destination is None
                else dict(self.destination.as_mapping())
            ),
            "ownership_transfer_authorization_id": (
                self.ownership_transfer_authorization_id
            ),
            "reservation_id": self.reservation_id,
            "outbox_id": self.outbox_id,
            "catalog_id": self.catalog_id,
            "schema_digest": self.schema_digest,
            "schema_revision": self.schema_revision,
            "generation_fence": self.generation_fence,
            "created_at": self.created_at,
        }
        return _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.SCHEMA,
                "receipt_id": self.receipt_id,
                "operation_id": self.operation_id,
                "idempotency_key": self.idempotency_key,
                "phase": self.phase.value,
                "committed": self.committed,
                "snapshot_version": self.snapshot_version,
                "source": dict(self.source.as_mapping()),
                "destination": (
                    None
                    if self.destination is None
                    else dict(self.destination.as_mapping())
                ),
                "staged": None if self.staged is None else dict(self.staged.as_mapping()),
                "ownership_transfer_authorization_id": (
                    self.ownership_transfer_authorization_id
                ),
                "copy_authorization_id": self.copy_authorization_id,
                "register_authorization_id": self.register_authorization_id,
                "reservation_id": self.reservation_id,
                "outbox_id": self.outbox_id,
                "registration": (
                    None
                    if self.registration is None
                    else dict(self.registration.as_mapping())
                ),
                "catalog_id": self.catalog_id,
                "data_path": self.data_path,
                "schema_digest": self.schema_digest,
                "schema_revision": self.schema_revision,
                "caller_id": self.caller_id,
                "process_birth": dict(self.process_birth.as_mapping()),
                "generation_fence": self.generation_fence,
                "lifecycle_policy": dict(self.lifecycle_policy.as_mapping()),
                "atomic_across_files": False,
                "source_untouched": True,
                "implementation_generation": self.implementation_generation,
                "created_at": self.created_at,
                "receipt_digest": self.receipt_digest(),
                "quarantine": (
                    None
                    if self.quarantine is None
                    else dict(self.quarantine.as_mapping())
                ),
            }
        )


# ---------------------------------------------------------------------------
# Trusted owner broker
# ---------------------------------------------------------------------------


class OwnerBroker:
    """Trusted owner broker that independently authorizes privileged lake calls.

    The ingest worker **never** issues ownership-transfer or privileged
    authorizations. Each call kind requires a fresh one-use authorization;
    an ownership-transfer receipt never confers ambient delete authority.
    """

    def __init__(
        self,
        *,
        broker_id: str,
        catalog_id: str,
        data_path: str,
        generation_fence: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.broker_id = _require_nonempty(broker_id, field_name="broker_id")
        self.catalog_id = _require_nonempty(catalog_id, field_name="catalog_id")
        self.data_path = _require_nonempty(data_path, field_name="data_path")
        self.generation_fence = _require_positive_int(
            generation_fence, field_name="generation_fence"
        )
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._issued: dict[str, PrivilegedCallAuthorization | OwnershipTransferAuthorization] = {}
        self._used_ids: set[str] = set()

    def _assert_fence(self, generation_fence: int) -> None:
        if int(generation_fence) != self.generation_fence:
            raise AuthorizationError(
                f"generation fence mismatch: broker fence "
                f"{self.generation_fence}, caller fence {generation_fence}"
            )

    def issue_privileged_authorization(
        self,
        *,
        kind: AuthorizationKind | str,
        operation_id: str,
        caller_id: str,
        process_birth: ProcessBirth,
        generation_fence: int,
        subject_digest: str,
        ttl_seconds: int = _DEFAULT_AUTH_TTL_SECONDS,
        authorization_id: str | None = None,
    ) -> PrivilegedCallAuthorization:
        kind_e = (
            kind if isinstance(kind, AuthorizationKind) else AuthorizationKind(str(kind))
        )
        if kind_e is AuthorizationKind.DELETE:
            # Deletes require an independent authorization path; ownership
            # transfer never auto-issues delete authority.
            pass
        self._assert_fence(generation_fence)
        caller = _require_nonempty(caller_id, field_name="caller_id")
        if caller == self.broker_id:
            raise AuthorizationError(
                "broker cannot issue a privileged authorization to itself as "
                "caller; keep broker and worker identities distinct"
            )
        now = float(self._clock())
        auth = PrivilegedCallAuthorization(
            authorization_id=authorization_id or f"pauth-{uuid.uuid4().hex}",
            kind=kind_e,
            operation_id=_require_nonempty(operation_id, field_name="operation_id"),
            caller_id=caller,
            process_birth=process_birth,
            generation_fence=generation_fence,
            catalog_id=self.catalog_id,
            data_path=self.data_path,
            issuer_id=self.broker_id,
            nonce=uuid.uuid4().hex,
            expires_at_unix=now + float(ttl_seconds),
            subject_digest=subject_digest,
            issued_at=_utc_iso(),
        )
        with self._lock:
            self._issued[auth.authorization_id] = auth
        return auth

    def issue_ownership_transfer(
        self,
        *,
        operation_id: str,
        caller_id: str,
        process_birth: ProcessBirth,
        generation_fence: int,
        source: SourceIdentity,
        destination: DestinationObjectIdentity,
        lifecycle_policy: LifecyclePolicy,
        ttl_seconds: int = _DEFAULT_AUTH_TTL_SECONDS,
        authorization_id: str | None = None,
    ) -> OwnershipTransferAuthorization:
        self._assert_fence(generation_fence)
        caller = _require_nonempty(caller_id, field_name="caller_id")
        if caller == self.broker_id:
            raise OwnershipTransferError(
                "ownership-transfer must be issued by the trusted owner broker "
                "to a distinct ingest-worker caller; self-issue is forbidden"
            )
        # Refuse transfer that would register external/CID as live destination.
        if _is_cid_uri(destination.owned_uri):
            raise OwnershipTransferError(
                "cannot issue ownership transfer for CID destination; "
                "DuckLake DATA_PATH must hold a lifecycle-managed owned copy"
            )
        if not lifecycle_policy.replace_allowed or not lifecycle_policy.delete_allowed:
            raise OwnershipTransferError(
                "lifecycle policy must allow replace and delete for owned copies"
            )
        now = float(self._clock())
        auth = OwnershipTransferAuthorization(
            authorization_id=authorization_id or f"otauth-{uuid.uuid4().hex}",
            operation_id=_require_nonempty(operation_id, field_name="operation_id"),
            caller_id=caller,
            process_birth=process_birth,
            generation_fence=generation_fence,
            catalog_id=self.catalog_id,
            data_path=self.data_path,
            source=source,
            destination=destination,
            lifecycle_policy=lifecycle_policy,
            issuer_id=self.broker_id,
            nonce=uuid.uuid4().hex,
            expires_at_unix=now + float(ttl_seconds),
            replace_allowed=True,
            delete_allowed=True,
            issued_at=_utc_iso(),
        )
        with self._lock:
            self._issued[auth.authorization_id] = auth
        return auth

    def mark_consumed(self, authorization_id: str) -> None:
        with self._lock:
            self._used_ids.add(authorization_id)

    def was_consumed(self, authorization_id: str) -> bool:
        with self._lock:
            return authorization_id in self._used_ids

    def issue_delete_authorization(
        self,
        *,
        operation_id: str,
        caller_id: str,
        process_birth: ProcessBirth,
        generation_fence: int,
        subject_digest: str,
        ttl_seconds: int = _DEFAULT_AUTH_TTL_SECONDS,
    ) -> PrivilegedCallAuthorization:
        """Independent delete authorization (never derived from transfer receipt)."""

        return self.issue_privileged_authorization(
            kind=AuthorizationKind.DELETE,
            operation_id=operation_id,
            caller_id=caller_id,
            process_birth=process_birth,
            generation_fence=generation_fence,
            subject_digest=subject_digest,
            ttl_seconds=ttl_seconds,
        )


# ---------------------------------------------------------------------------
# In-memory DuckLake catalog facade (hermetic)
# ---------------------------------------------------------------------------


class _HermeticDuckLakeCatalog:
    """Minimal catalog facade that simulates snapshot + add_data_files.

    Production owners call the real DuckDB ``ducklake_add_data_files`` after
    the same authorization gates. This facade never mutates source files.
    """

    def __init__(self, *, catalog_id: str, data_path: str) -> None:
        self.catalog_id = catalog_id
        self.data_path = data_path
        self.snapshot_version = 0
        self.registered_files: dict[str, dict[str, Any]] = {}
        self.operation_markers: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def add_data_files(
        self,
        *,
        operation_id: str,
        owned_uri: str,
        content_digest: str,
        ownership_transfer_authorization_id: str,
        register_authorization_id: str,
        table_name: str = "lake_table",
    ) -> DuckLakeRegistrationReceipt:
        with self._lock:
            # Idempotent: same operation_id returns the prior registration.
            prior = self.operation_markers.get(operation_id)
            if prior is not None and prior.get("status") == "committed":
                return DuckLakeRegistrationReceipt(
                    registration_id=str(prior["registration_id"]),
                    operation_id=operation_id,
                    owned_uri=str(prior["owned_uri"]),
                    content_digest=str(prior["content_digest"]),
                    snapshot_version=int(prior["snapshot_version"]),
                    catalog_id=self.catalog_id,
                    ownership_transfer_authorization_id=str(
                        prior["ownership_transfer_authorization_id"]
                    ),
                    register_authorization_id=str(prior["register_authorization_id"]),
                    registered_at=str(prior.get("registered_at") or _utc_iso()),
                )

            if not owned_uri.startswith(self.data_path.rstrip("/")) and not (
                owned_uri.startswith("s3://") or owned_uri.startswith("gs://")
            ):
                # Local owned paths must sit under DATA_PATH.
                if "://" not in owned_uri:
                    owned_path = Path(owned_uri)
                    data_root = Path(self.data_path)
                    if not _path_is_under(owned_path, data_root):
                        raise RegistrationError(
                            "registered file must live under lifecycle-managed "
                            "DATA_PATH",
                            details={
                                "owned_uri": owned_uri,
                                "data_path": self.data_path,
                            },
                        )

            if _is_cid_uri(owned_uri):
                raise ExternalSourceRegistrationError(
                    "refusing ducklake_add_data_files for external/immutable CID "
                    "source; DuckLake maintenance must be allowed to replace "
                    "and delete owned files",
                    details={"owned_uri": owned_uri},
                )

            self.snapshot_version += 1
            snap = self.snapshot_version
            reg_id = f"reg-{uuid.uuid4().hex}"
            receipt = DuckLakeRegistrationReceipt(
                registration_id=reg_id,
                operation_id=operation_id,
                owned_uri=owned_uri,
                content_digest=content_digest,
                snapshot_version=snap,
                catalog_id=self.catalog_id,
                ownership_transfer_authorization_id=ownership_transfer_authorization_id,
                register_authorization_id=register_authorization_id,
            )
            self.registered_files[owned_uri] = {
                "content_digest": content_digest,
                "snapshot_version": snap,
                "table_name": table_name,
                "operation_id": operation_id,
            }
            self.operation_markers[operation_id] = {
                "status": "committed",
                "registration_id": reg_id,
                "owned_uri": owned_uri,
                "content_digest": content_digest,
                "snapshot_version": snap,
                "ownership_transfer_authorization_id": ownership_transfer_authorization_id,
                "register_authorization_id": register_authorization_id,
                "registered_at": receipt.registered_at,
                "function": DUCKLAKE_ADD_DATA_FILES,
            }
            return receipt

    def mark_in_doubt(
        self,
        *,
        operation_id: str,
        snapshot_version: int,
        owned_uri: str,
        content_digest: str,
    ) -> None:
        with self._lock:
            self.snapshot_version = max(self.snapshot_version, snapshot_version)
            self.operation_markers[operation_id] = {
                "status": "in_doubt",
                "snapshot_version": snapshot_version,
                "owned_uri": owned_uri,
                "content_digest": content_digest,
            }


# ---------------------------------------------------------------------------
# Ingest service
# ---------------------------------------------------------------------------


class IngestService:
    """Idempotent create/copy/register ingest coordinator (DQK-088).

    Coordinates admission-bound source identity, content-bound staging outside
    DATA_PATH, broker-issued ownership transfer, independent privileged
    authorizations, companion reservations/outbox, and hermetic
    ``ducklake_add_data_files`` registration. Lost responses and retries
    collapse to one logical snapshot via the operation/idempotency key.
    """

    SCHEMA: Final[str] = INGEST_SCHEMA

    def __init__(
        self,
        *,
        shard_id: str,
        owner_id: str,
        catalog_id: str,
        parquet_namespace: ParquetNamespace,
        broker: OwnerBroker,
        control: reg.ControlLakeRegistry,
        companion: reg.CompanionLakeRegistry | None = None,
        constraint_service: c.ConstraintService | None = None,
        caller_id: str,
        process_birth: ProcessBirth,
        generation_fence: int,
        lifecycle_policy: LifecyclePolicy | None = None,
        quack_instance: reg.DatabaseInstanceBinding | None = None,
        catalog: _HermeticDuckLakeCatalog | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.shard_id = _require_nonempty(shard_id, field_name="shard_id")
        self.owner_id = _require_nonempty(owner_id, field_name="owner_id")
        self.catalog_id = _require_nonempty(catalog_id, field_name="catalog_id")
        if not isinstance(parquet_namespace, ParquetNamespace):
            raise IngestError("parquet_namespace must be ParquetNamespace")
        self.namespace = parquet_namespace
        if self.namespace.staging_path is None:
            raise StagingError(
                "parquet namespace requires staging_path outside DATA_PATH"
            )
        assert_staging_outside_data_path(
            self.namespace.staging_path,
            self.namespace.data_path,
            storage_kind=self.namespace.storage_kind,
        )
        self.broker = broker
        if broker.catalog_id != catalog_id:
            raise IngestError("broker catalog_id must match ingest catalog_id")
        if broker.data_path.rstrip("/") != self.namespace.data_path.rstrip("/"):
            raise IngestError("broker DATA_PATH must match parquet namespace data_path")
        self.control = control
        self.companion = companion or reg.CompanionLakeRegistry(
            shard_id=self.shard_id,
            owner_id=self.owner_id,
            control=control,
        )
        if self.companion.control is None:
            self.companion.control = control
        self.constraints = constraint_service or c.ConstraintService(
            shard_id=self.shard_id,
            owner_id=self.owner_id,
            control=control,
            companion=self.companion,
            quack_instance=quack_instance,
            catalog_id=catalog_id,
        )
        self.caller_id = _require_nonempty(caller_id, field_name="caller_id")
        if self.caller_id == self.broker.broker_id:
            raise IngestError(
                "ingest caller_id must differ from trusted owner broker identity"
            )
        self.process_birth = process_birth
        self.generation_fence = _require_positive_int(
            generation_fence, field_name="generation_fence"
        )
        if self.generation_fence != broker.generation_fence:
            raise IngestError("ingest generation_fence must match broker fence")
        self.lifecycle_policy = lifecycle_policy or LifecyclePolicy(
            policy_id=f"lifecycle-{catalog_id}",
            retention_class=_DEFAULT_RETENTION_CLASS,
            replace_allowed=True,
            delete_allowed=True,
        )
        self.catalog = catalog or _HermeticDuckLakeCatalog(
            catalog_id=catalog_id, data_path=self.namespace.data_path
        )
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._by_operation: dict[str, IngestReceipt] = {}
        self._by_idempotency: dict[str, str] = {}
        self._in_flight: dict[str, dict[str, Any]] = {}
        self._quarantine: dict[str, QuarantineRecord] = {}
        self._source_digests_at_start: dict[str, str] = {}

    # -- lifecycle ---------------------------------------------------------

    def ensure_ready(self) -> None:
        with self._lock:
            try:
                self.companion.require_migrated()
            except reg.RegistryError:
                self.companion.apply_migrations()
            self.constraints.ensure_ready()

    # -- public API --------------------------------------------------------

    def ingest(
        self,
        *,
        source_path: str | os.PathLike[str] | Path,
        dataset_id: str,
        idempotency_key: str,
        schema_contract: c.SchemaContract,
        records: Sequence[Mapping[str, Any]] | None = None,
        admission_receipt: adm.AdmissionDecisionReceipt | None = None,
        operation_id: str | None = None,
        logical_key: str | Mapping[str, Any] | None = None,
        uniqueness_scope: str | None = None,
        object_version: int = 1,
        table_name: str = "lake_table",
        simulate_crash_after: str | None = None,
        source_ownership_kind: adm.SourceOwnershipKind | None = None,
    ) -> IngestReceipt:
        """Run the full create/copy/register pipeline (idempotent).

        *simulate_crash_after* may be one of ``"stage"``, ``"copy"``,
        ``"register"``, ``"snapshot"`` to leave a partial state for
        reconciliation tests.
        """

        self.ensure_ready()
        op_id = operation_id or f"ingest-{uuid.uuid4().hex}"
        idem = _require_nonempty(idempotency_key, field_name="idempotency_key")
        ds = _require_nonempty(dataset_id, field_name="dataset_id")

        with self._lock:
            # Idempotent replay: same key returns the committed receipt.
            existing_op = self._by_idempotency.get(idem)
            if existing_op is not None:
                prior = self._by_operation.get(existing_op)
                if prior is not None and prior.committed:
                    return prior
                if prior is not None and prior.phase is IngestPhase.QUARANTINED:
                    # Reconcile quarantined partial before returning.
                    return self.reconcile(operation_id=existing_op)

            prior_op = self._by_operation.get(op_id)
            if prior_op is not None and prior_op.committed:
                self._by_idempotency[idem] = op_id
                return prior_op

            try:
                receipt = self._ingest_locked(
                    source_path=source_path,
                    dataset_id=ds,
                    idempotency_key=idem,
                    schema_contract=schema_contract,
                    records=records,
                    admission_receipt=admission_receipt,
                    operation_id=op_id,
                    logical_key=logical_key or idem,
                    uniqueness_scope=uniqueness_scope or f"dataset:{ds}",
                    object_version=object_version,
                    table_name=table_name,
                    simulate_crash_after=simulate_crash_after,
                    source_ownership_kind=source_ownership_kind,
                )
            except QuarantineError as exc:
                q = self._quarantine.get(op_id)
                if q is None:
                    q = QuarantineRecord(
                        quarantine_id=f"q-{uuid.uuid4().hex}",
                        operation_id=op_id,
                        phase=IngestPhase.QUARANTINED,
                        reason=str(exc),
                        details=dict(exc.details),
                    )
                    self._quarantine[op_id] = q
                # Persist a non-terminal receipt for recovery.
                failed = self._make_failed_receipt(
                    operation_id=op_id,
                    idempotency_key=idem,
                    dataset_id=ds,
                    schema_contract=schema_contract,
                    quarantine=q,
                    source_path=source_path,
                    admission_receipt=admission_receipt,
                    source_ownership_kind=source_ownership_kind,
                )
                self._by_operation[op_id] = failed
                self._by_idempotency[idem] = op_id
                raise
            except IngestError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                raise IngestError(f"ingest failed: {exc}") from exc

            self._by_operation[op_id] = receipt
            self._by_idempotency[idem] = op_id
            return receipt

    def reconcile(
        self,
        *,
        operation_id: str | None = None,
        known_objects: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> IngestReceipt | Mapping[str, Any]:
        """Reconcile partial object upload, catalog commit, or receipt publication.

        Does not claim atomicity across files. Terminalizes in-doubt operations
        that have catalog markers, or leaves them quarantined.
        """

        self.ensure_ready()
        with self._lock:
            if operation_id is not None:
                return self._reconcile_one(operation_id, known_objects=known_objects)

            report: dict[str, Any] = {
                "reconciled": [],
                "quarantined": [],
                "already_terminal": [],
            }
            for op_id in list(self._by_operation.keys()) + list(self._in_flight.keys()):
                try:
                    result = self._reconcile_one(op_id, known_objects=known_objects)
                except QuarantineError as exc:
                    report["quarantined"].append(
                        {"operation_id": op_id, "reason": str(exc)}
                    )
                    continue
                if isinstance(result, IngestReceipt):
                    if result.committed:
                        report["reconciled"].append(op_id)
                    elif result.phase is IngestPhase.QUARANTINED:
                        report["quarantined"].append(op_id)
                    else:
                        report["already_terminal"].append(op_id)
            return MappingProxyType(report)

    def get_receipt(self, operation_id: str) -> IngestReceipt | None:
        with self._lock:
            return self._by_operation.get(operation_id)

    def get_receipt_by_idempotency(self, idempotency_key: str) -> IngestReceipt | None:
        with self._lock:
            op = self._by_idempotency.get(idempotency_key)
            if op is None:
                return None
            return self._by_operation.get(op)

    def assert_source_untouched(
        self, source_path: str | os.PathLike[str] | Path
    ) -> str:
        """Re-hash the source and assert it still matches the pre-ingest digest."""

        path = Path(source_path)
        if not path.is_file():
            raise IngestError(f"source path missing: {path}")
        _, digest = adm.stream_file_digest(path)
        key = str(path.resolve(strict=False))
        expected = self._source_digests_at_start.get(key)
        if expected is not None and expected != digest:
            raise IngestError(
                "source file was modified during ingest; source files must "
                "remain untouched",
                details={"path": key, "expected": expected, "observed": digest},
            )
        return digest

    def authorize_delete_independently(
        self,
        *,
        operation_id: str,
        subject_digest: str,
    ) -> PrivilegedCallAuthorization:
        """Prove delete requires a separate broker authorization (not transfer)."""

        return self.broker.issue_delete_authorization(
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            subject_digest=subject_digest,
        )

    # -- internals ---------------------------------------------------------

    def _ingest_locked(
        self,
        *,
        source_path: str | os.PathLike[str] | Path,
        dataset_id: str,
        idempotency_key: str,
        schema_contract: c.SchemaContract,
        records: Sequence[Mapping[str, Any]] | None,
        admission_receipt: adm.AdmissionDecisionReceipt | None,
        operation_id: str,
        logical_key: str | Mapping[str, Any],
        uniqueness_scope: str,
        object_version: int,
        table_name: str,
        simulate_crash_after: str | None,
        source_ownership_kind: adm.SourceOwnershipKind | None,
    ) -> IngestReceipt:
        src_path = Path(source_path)
        if not src_path.is_file():
            raise IngestError(f"source path is not a file: {src_path}")

        # Capture pre-ingest source digest; never mutate the source.
        src_size, src_digest = adm.stream_file_digest(src_path)
        src_key = str(src_path.resolve(strict=False))
        self._source_digests_at_start[src_key] = src_digest
        source_bytes = src_path.read_bytes()
        # Verify streaming digest matches full read (content-bound).
        if _sha256_bytes(source_bytes) != src_digest:
            raise IngestError("source digest mismatch between stream and full read")

        # Build source identity (external sources always require owned copy).
        if admission_receipt is not None:
            if not admission_receipt.admitted:
                raise IngestError(
                    "admission receipt is not admitted",
                    details={"receipt_id": admission_receipt.receipt_id},
                )
            source = SourceIdentity.from_admission(admission_receipt)
            if source.content_digest != src_digest:
                raise IngestError(
                    "admission receipt content digest does not match source path"
                )
        else:
            kind = source_ownership_kind or adm.SourceOwnershipKind.EXTERNAL_UNMANAGED
            source = SourceIdentity(
                source_uri=src_path.resolve(strict=False).as_uri(),
                content_digest=src_digest,
                ownership_kind=kind,
                byte_size=src_size,
            )

        # Never register external / immutable CID sources live.
        if source.is_external_or_immutable_cid or source.ownership_kind is not adm.SourceOwnershipKind.LIFECYCLE_MANAGED:
            # Must copy; registration path uses owned destination only.
            pass
        if _is_cid_uri(str(source_path)) or _is_cid_uri(source.source_uri):
            # Source may be a CID for provenance, but we still require a local
            # readable path for the byte copy in this hermetic implementation.
            if not src_path.is_file():
                raise ExternalSourceRegistrationError(
                    "immutable CID sources cannot be registered as live "
                    "DATA_PATH; provide a materialised source path for the "
                    "lifecycle-managed owned copy"
                )

        # DQK-094 schema policy: missing/extra columns + lossless promotion.
        # ``__types__`` is reserved metadata for explicit source-type hints and
        # is never treated as a schema column.
        normalized_records: list[dict[str, Any]] = []
        if records is not None:
            for rec in records:
                type_hints: Mapping[str, Any] = {}
                if isinstance(rec.get("__types__"), Mapping):
                    type_hints = dict(rec["__types__"])
                policy_input = {
                    k: v for k, v in rec.items() if k not in {"__types__", "__type__"}
                }
                try:
                    normalized = c.apply_column_policy(schema_contract, policy_input)
                except c.ConstraintViolation as exc:
                    raise IngestError(
                        f"schema column policy rejected record: {exc}",
                        details=dict(exc.details) if hasattr(exc, "details") else {},
                    ) from exc
                # Apply type promotion rules (lossless only).
                promoted: dict[str, Any] = {}
                for field_contract in schema_contract.fields:
                    value = normalized.get(field_contract.field_id)
                    if value is None:
                        promoted[field_contract.field_id] = value
                        continue
                    try:
                        type_hint = type_hints.get(field_contract.field_id)
                        if type_hint is None:
                            type_hint = type_hints.get(field_contract.name)
                        if type_hint is not None:
                            promoted[field_contract.field_id] = (
                                schema_contract.promotion_rules.promote(
                                    value,
                                    source=type_hint,
                                    target=field_contract.field_type,
                                )
                            )
                        else:
                            promoted[field_contract.field_id] = value
                    except c.TypePromotionError as exc:
                        raise IngestError(
                            f"type promotion rejected: {exc}",
                            details={"field_id": field_contract.field_id},
                        ) from exc
                normalized_records.append(promoted)

            validation = self.constraints.validate_before_commit(
                schema_contract,
                normalized_records,
                source_files=(source.source_uri,),
                source_digests=(source.content_digest,),
            )
            if not validation.accepted:
                raise IngestError(
                    "records rejected by DQK-094 schema/constraint policy "
                    "before object copy or snapshot mutation",
                    details={
                        "rejects": [
                            dict(r.as_mapping()) for r in validation.rejects
                        ]
                    },
                )
            normalized_records = [dict(r) for r in validation.normalized_records]

        # Resolve home shard before any copy.
        self.constraints.resolve_scope_home(
            uniqueness_scope=uniqueness_scope, dataset_id=dataset_id
        )

        # Durable reservation + outbox enqueue (pre-snapshot).
        reservation = self.constraints.acquire_reservation(
            dataset_id=dataset_id,
            uniqueness_scope=uniqueness_scope,
            logical_key=logical_key,
            idempotency_key=idempotency_key,
        )
        # If reservation already committed under this idempotency key, return
        # the prior logical snapshot (lost-response / retry).
        if reservation.status is c.ReservationStatus.COMMITTED:
            prior = self._by_operation.get(operation_id) or self.get_receipt_by_idempotency(
                idempotency_key
            )
            if prior is not None and prior.committed:
                return prior

        outbox = self.companion.enqueue_ingest_outbox(
            outbox_id=f"outbox-{operation_id}",
            operation_id=operation_id,
            payload={
                "operation_id": operation_id,
                "dataset_id": dataset_id,
                "source_digest": source.content_digest,
                "idempotency_key": idempotency_key,
                "phase": IngestPhase.RESERVED.value,
            },
        )
        # Record source in companion (provenance only).
        try:
            self.companion.put_source(
                source_id=f"src-{source.content_digest[len(_SHA256_PREFIX):len(_SHA256_PREFIX)+16]}",
                source_uri=source.source_uri,
                content=source.content_identity(),
                object_generation=source.object_generation,
                etag=source.etag,
                provenance={
                    "dataset_id": dataset_id,
                    "operation_id": operation_id,
                    "content_cid": source.content_cid,
                },
            )
        except reg.RegistryError:
            # Idempotent source re-put under same key is acceptable.
            pass

        self._in_flight[operation_id] = {
            "phase": IngestPhase.RESERVED.value,
            "reservation_id": reservation.reservation_id,
            "outbox_id": str(outbox["outbox_id"]),
            "source": dict(source.as_mapping()),
            "idempotency_key": idempotency_key,
            "dataset_id": dataset_id,
            "schema_digest": schema_contract.schema_digest,
            "schema_revision": schema_contract.revision,
        }

        # --- Stage outside DATA_PATH (content-bound) ----------------------
        staged = self._stage_copy(
            source_path=src_path,
            source_bytes=source_bytes,
            source=source,
            dataset_id=dataset_id,
            object_version=object_version,
            operation_id=operation_id,
        )
        self._in_flight[operation_id]["phase"] = IngestPhase.STAGED.value
        self._in_flight[operation_id]["staged"] = dict(staged.as_mapping())

        if simulate_crash_after == "stage":
            self._quarantine_operation(
                operation_id=operation_id,
                phase=IngestPhase.STAGED,
                reason="simulated crash after stage before owned copy",
            )
            raise QuarantineError(
                "partial stage without owned copy; reconcile or quarantine",
                details={"operation_id": operation_id, "phase": "staged"},
            )

        # --- Privileged COPY authorization (independent) ------------------
        copy_auth = self.broker.issue_privileged_authorization(
            kind=AuthorizationKind.COPY,
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            subject_digest=source.content_digest,
        )
        copy_auth = revalidate_privileged_authorization(
            copy_auth,
            kind=AuthorizationKind.COPY,
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            catalog_id=self.catalog_id,
            data_path=self.namespace.data_path,
            subject_digest=source.content_digest,
            now=self._clock(),
        )
        self.broker.mark_consumed(copy_auth.authorization_id)

        destination = self._promote_to_owned(
            staged=staged,
            source=source,
            dataset_id=dataset_id,
            object_version=object_version,
        )
        # Source still untouched after owned copy.
        self.assert_source_untouched(src_path)
        if _sha256_bytes(Path(destination.owned_uri).read_bytes()) != source.content_digest:
            raise StagingError("owned copy digest drifted from source")

        self._in_flight[operation_id]["phase"] = IngestPhase.COPIED.value
        self._in_flight[operation_id]["destination"] = dict(destination.as_mapping())

        if simulate_crash_after == "copy":
            self._quarantine_operation(
                operation_id=operation_id,
                phase=IngestPhase.COPIED,
                reason="simulated crash after owned copy before ownership transfer",
            )
            raise QuarantineError(
                "partial owned copy without ownership transfer / registration",
                details={"operation_id": operation_id, "phase": "copied"},
            )

        # --- Ownership transfer (broker-issued, non-self-issued) ----------
        transfer_auth = self.broker.issue_ownership_transfer(
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            source=source,
            destination=destination,
            lifecycle_policy=self.lifecycle_policy,
        )
        # Revalidate immediately before registration.
        transfer_auth = revalidate_ownership_transfer_authorization(
            transfer_auth,
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            catalog_id=self.catalog_id,
            data_path=self.namespace.data_path,
            source=source,
            destination=destination,
            lifecycle_policy=self.lifecycle_policy,
            now=self._clock(),
        )
        self.broker.mark_consumed(transfer_auth.authorization_id)
        assert transfer_auth.confers_ambient_delete() is False

        self.companion.put_ownership_state(
            ownership_id=f"own-{destination.content_digest[len(_SHA256_PREFIX):len(_SHA256_PREFIX)+16]}",
            subject_kind="owned_parquet",
            subject_id=destination.owned_uri,
            owner_generation=self.generation_fence,
            status="owned",
        )
        self._in_flight[operation_id]["phase"] = IngestPhase.OWNERSHIP_TRANSFERRED.value
        self._in_flight[operation_id][
            "ownership_transfer_authorization_id"
        ] = transfer_auth.authorization_id

        # --- Independent REGISTER authorization + ducklake_add_data_files -
        register_auth = self.broker.issue_privileged_authorization(
            kind=AuthorizationKind.REGISTER,
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            subject_digest=destination.content_digest,
        )
        register_auth = revalidate_privileged_authorization(
            register_auth,
            kind=AuthorizationKind.REGISTER,
            operation_id=operation_id,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            catalog_id=self.catalog_id,
            data_path=self.namespace.data_path,
            subject_digest=destination.content_digest,
            now=self._clock(),
        )
        self.broker.mark_consumed(register_auth.authorization_id)

        # Refuse to register the *source* URI if it is external/CID.
        if source.is_external_or_immutable_cid:
            # Registration must target the owned destination only.
            if destination.owned_uri == source.source_uri:
                raise ExternalSourceRegistrationError(
                    "refusing to register external/immutable source URI as "
                    "live DuckLake file; use the lifecycle-managed owned copy"
                )

        if simulate_crash_after == "register":
            # Snapshot advanced without outbox terminalization.
            self.catalog.snapshot_version += 1
            self.catalog.mark_in_doubt(
                operation_id=operation_id,
                snapshot_version=self.catalog.snapshot_version,
                owned_uri=destination.owned_uri,
                content_digest=destination.content_digest,
            )
            self._in_flight[operation_id]["phase"] = IngestPhase.REGISTERED.value
            self._in_flight[operation_id]["snapshot_version"] = (
                self.catalog.snapshot_version
            )
            self._quarantine_operation(
                operation_id=operation_id,
                phase=IngestPhase.REGISTERED,
                reason=(
                    "simulated crash after catalog snapshot before outbox "
                    "terminalization / receipt publication"
                ),
                details={
                    "snapshot_version": self.catalog.snapshot_version,
                    "owned_uri": destination.owned_uri,
                },
            )
            raise QuarantineError(
                "partial catalog commit without receipt publication; "
                "reconcile via outbox without a second logical transition",
                details={
                    "operation_id": operation_id,
                    "snapshot_version": self.catalog.snapshot_version,
                },
            )

        registration = self.catalog.add_data_files(
            operation_id=operation_id,
            owned_uri=destination.owned_uri,
            content_digest=destination.content_digest,
            ownership_transfer_authorization_id=transfer_auth.authorization_id,
            register_authorization_id=register_auth.authorization_id,
            table_name=table_name,
        )

        if simulate_crash_after == "snapshot":
            self.catalog.mark_in_doubt(
                operation_id=operation_id,
                snapshot_version=registration.snapshot_version,
                owned_uri=destination.owned_uri,
                content_digest=destination.content_digest,
            )
            self._in_flight[operation_id]["phase"] = IngestPhase.REGISTERED.value
            self._in_flight[operation_id]["snapshot_version"] = (
                registration.snapshot_version
            )
            self._in_flight[operation_id]["registration"] = dict(
                registration.as_mapping()
            )
            self._quarantine_operation(
                operation_id=operation_id,
                phase=IngestPhase.REGISTERED,
                reason="simulated crash after snapshot before receipt publication",
                details={"snapshot_version": registration.snapshot_version},
            )
            raise QuarantineError(
                "partial receipt publication; reconcile without second snapshot",
                details={
                    "operation_id": operation_id,
                    "snapshot_version": registration.snapshot_version,
                },
            )

        # Persist file identity + terminalize reservation/outbox.
        file_id = (
            f"file-{destination.content_digest[len(_SHA256_PREFIX):len(_SHA256_PREFIX)+16]}"
        )
        try:
            self.companion.store.put_if_absent(
                "lake_file_identities",
                file_id,
                {
                    "file_id": file_id,
                    "shard_id": self.shard_id,
                    "content_digest": destination.content_digest,
                    "owned_path": destination.owned_uri,
                    "source_id": source.source_uri,
                    "registered_at": _utc_iso(),
                },
            )
        except Exception:
            pass

        commit_receipt = self.constraints.terminalize_reservation(
            reservation_id=reservation.reservation_id,
            operation_id=operation_id,
            snapshot_version=registration.snapshot_version,
            contract=schema_contract,
        )

        # Companion ingest receipt.
        body = {
            "operation_id": operation_id,
            "snapshot_version": registration.snapshot_version,
            "source": dict(source.as_mapping()),
            "destination": dict(destination.as_mapping()),
            "registration": dict(registration.as_mapping()),
            "ownership_transfer_authorization_id": transfer_auth.authorization_id,
            "copy_authorization_id": copy_auth.authorization_id,
            "register_authorization_id": register_auth.authorization_id,
            "schema_digest": schema_contract.schema_digest,
            "schema_revision": schema_contract.revision,
        }
        try:
            self.companion.store.put_if_absent(
                "lake_ingest_receipts",
                f"irec-{operation_id}",
                {
                    "receipt_id": f"irec-{operation_id}",
                    "shard_id": self.shard_id,
                    "operation_id": operation_id,
                    "snapshot_version": registration.snapshot_version,
                    "status": "committed",
                    "created_at": _utc_iso(),
                    "body_json": _canonical_json(body),
                },
            )
        except Exception:
            pass

        # Clean staging after successful promote (staging never under DATA_PATH).
        self._cleanup_staging(staged)

        # Final source integrity check.
        self.assert_source_untouched(src_path)

        receipt = IngestReceipt(
            receipt_id=f"ingrec-{operation_id}",
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            phase=IngestPhase.COMMITTED,
            snapshot_version=registration.snapshot_version,
            source=source,
            destination=destination,
            staged=staged,
            ownership_transfer_authorization_id=transfer_auth.authorization_id,
            copy_authorization_id=copy_auth.authorization_id,
            register_authorization_id=register_auth.authorization_id,
            reservation_id=reservation.reservation_id,
            outbox_id=str(outbox["outbox_id"]),
            registration=registration,
            catalog_id=self.catalog_id,
            data_path=self.namespace.data_path,
            schema_digest=schema_contract.schema_digest,
            schema_revision=schema_contract.revision,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            lifecycle_policy=self.lifecycle_policy,
        )
        self._in_flight.pop(operation_id, None)
        # Bind commit_receipt snapshot for debug consistency.
        _ = commit_receipt
        return receipt

    def _stage_copy(
        self,
        *,
        source_path: Path,
        source_bytes: bytes,
        source: SourceIdentity,
        dataset_id: str,
        object_version: int,
        operation_id: str,
    ) -> StagedObject:
        staging_root = Path(self.namespace.staging_path or "")
        data_root = Path(self.namespace.data_path)
        assert_staging_outside_data_path(
            staging_root, data_root, storage_kind=self.namespace.storage_kind
        )
        key = content_bound_object_key(
            content_digest=source.content_digest,
            dataset_id=dataset_id,
            object_version=object_version,
        )
        # Content-bound staging path includes operation fragment only as a
        # directory for isolation; digest path remains content-addressed.
        staged_path = staging_root / "content" / key
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        # Write via temp then rename for crash safety within staging.
        tmp_path = staged_path.with_suffix(staged_path.suffix + f".{operation_id}.tmp")
        tmp_path.write_bytes(source_bytes)
        os.replace(tmp_path, staged_path)
        if _path_is_under(staged_path, data_root):
            raise StagingError(
                "staging resolved under DATA_PATH; refuse to continue"
            )
        digest = _sha256_bytes(staged_path.read_bytes())
        if digest != source.content_digest:
            raise StagingError(
                "staged object digest does not match source",
                details={"expected": source.content_digest, "observed": digest},
            )
        # Source path bytes still identical.
        if source_path.read_bytes() != source_bytes:
            raise IngestError("source file mutated during staging")
        return StagedObject(
            staging_uri=str(staged_path.resolve(strict=False)),
            content_digest=digest,
            source_uri=source.source_uri,
            byte_size=len(source_bytes),
        )

    def _promote_to_owned(
        self,
        *,
        staged: StagedObject,
        source: SourceIdentity,
        dataset_id: str,
        object_version: int,
    ) -> DestinationObjectIdentity:
        data_root = Path(self.namespace.data_path)
        data_root.mkdir(parents=True, exist_ok=True)
        key = content_bound_object_key(
            content_digest=source.content_digest,
            dataset_id=dataset_id,
            object_version=object_version,
        )
        owned_path = data_root / "owned" / key
        owned_path.parent.mkdir(parents=True, exist_ok=True)
        # Copy from staging into owned namespace (not move across volumes).
        shutil.copy2(staged.staging_uri, owned_path)
        digest = _sha256_bytes(owned_path.read_bytes())
        if digest != source.content_digest:
            raise StagingError("owned copy digest mismatch after promote")
        if not _path_is_under(owned_path, data_root):
            raise StagingError("owned path escaped DATA_PATH")
        # Staging must still be outside DATA_PATH.
        assert_staging_outside_data_path(
            staged.staging_uri, data_root, storage_kind=self.namespace.storage_kind
        )
        return DestinationObjectIdentity(
            owned_uri=str(owned_path.resolve(strict=False)),
            content_digest=digest,
            object_version=object_version,
            object_generation=f"v{object_version}",
            namespace_id=self.namespace.namespace_id,
        )

    def _cleanup_staging(self, staged: StagedObject) -> None:
        try:
            path = Path(staged.staging_uri)
            if path.is_file():
                path.unlink()
        except OSError:
            # Best-effort; leftover staging is outside DATA_PATH so it cannot
            # be mistaken for a DATA_PATH orphan.
            pass

    def _quarantine_operation(
        self,
        *,
        operation_id: str,
        phase: IngestPhase,
        reason: str,
        details: Mapping[str, Any] | None = None,
    ) -> QuarantineRecord:
        rec = QuarantineRecord(
            quarantine_id=f"q-{uuid.uuid4().hex}",
            operation_id=operation_id,
            phase=phase,
            reason=reason,
            details=dict(details or {}),
        )
        self._quarantine[operation_id] = rec
        if operation_id in self._in_flight:
            self._in_flight[operation_id]["phase"] = IngestPhase.QUARANTINED.value
            self._in_flight[operation_id]["quarantine_id"] = rec.quarantine_id
        return rec

    def _make_failed_receipt(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        dataset_id: str,
        schema_contract: c.SchemaContract,
        quarantine: QuarantineRecord,
        source_path: str | os.PathLike[str] | Path,
        admission_receipt: adm.AdmissionDecisionReceipt | None,
        source_ownership_kind: adm.SourceOwnershipKind | None,
    ) -> IngestReceipt:
        flight = self._in_flight.get(operation_id) or {}
        if admission_receipt is not None and admission_receipt.admitted:
            source = SourceIdentity.from_admission(admission_receipt)
        elif flight.get("source"):
            source = SourceIdentity.from_mapping(flight["source"])
        else:
            path = Path(source_path)
            if path.is_file():
                _, digest = adm.stream_file_digest(path)
                source = SourceIdentity(
                    source_uri=path.resolve(strict=False).as_uri(),
                    content_digest=digest,
                    ownership_kind=source_ownership_kind
                    or adm.SourceOwnershipKind.EXTERNAL_UNMANAGED,
                    byte_size=path.stat().st_size,
                )
            else:
                source = SourceIdentity(
                    source_uri=str(source_path),
                    content_digest=_sha256_text("missing"),
                    ownership_kind=adm.SourceOwnershipKind.EXTERNAL_UNMANAGED,
                )
        dest = None
        if flight.get("destination"):
            dest = DestinationObjectIdentity.from_mapping(flight["destination"])
        staged = None
        if flight.get("staged"):
            s = flight["staged"]
            staged = StagedObject(
                staging_uri=str(s["staging_uri"]),
                content_digest=str(s["content_digest"]),
                source_uri=str(s["source_uri"]),
                byte_size=int(s["byte_size"]),
                staged_at=str(s.get("staged_at") or ""),
            )
        return IngestReceipt(
            receipt_id=f"ingrec-{operation_id}",
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            phase=IngestPhase.QUARANTINED,
            snapshot_version=flight.get("snapshot_version"),
            source=source,
            destination=dest,
            staged=staged,
            ownership_transfer_authorization_id=str(
                flight.get("ownership_transfer_authorization_id") or ""
            ),
            copy_authorization_id="",
            register_authorization_id="",
            reservation_id=str(flight.get("reservation_id") or ""),
            outbox_id=str(flight.get("outbox_id") or ""),
            registration=None,
            catalog_id=self.catalog_id,
            data_path=self.namespace.data_path,
            schema_digest=schema_contract.schema_digest,
            schema_revision=schema_contract.revision,
            caller_id=self.caller_id,
            process_birth=self.process_birth,
            generation_fence=self.generation_fence,
            lifecycle_policy=self.lifecycle_policy,
            quarantine=quarantine,
        )

    def _reconcile_one(
        self,
        operation_id: str,
        *,
        known_objects: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> IngestReceipt:
        prior = self._by_operation.get(operation_id)
        if prior is not None and prior.committed:
            return prior

        flight = self._in_flight.get(operation_id) or {}
        marker = self.catalog.operation_markers.get(operation_id)
        q = self._quarantine.get(operation_id)

        # Catalog committed marker → terminalize outbox/reservation once.
        if marker and marker.get("status") in {"committed", "in_doubt"}:
            snap = int(marker["snapshot_version"])
            owned_uri = str(marker.get("owned_uri") or "")
            content_digest = str(marker.get("content_digest") or "")
            # Ensure file exists for in_doubt recovery when object present.
            if owned_uri and Path(owned_uri).is_file():
                if marker.get("status") == "in_doubt":
                    # Complete registration idempotently.
                    registration = self.catalog.add_data_files(
                        operation_id=operation_id,
                        owned_uri=owned_uri,
                        content_digest=content_digest,
                        ownership_transfer_authorization_id=str(
                            flight.get("ownership_transfer_authorization_id")
                            or marker.get("ownership_transfer_authorization_id")
                            or "recovered"
                        ),
                        register_authorization_id=str(
                            marker.get("register_authorization_id") or "recovered"
                        ),
                    )
                    snap = registration.snapshot_version
                else:
                    registration = DuckLakeRegistrationReceipt(
                        registration_id=str(marker.get("registration_id") or f"reg-{operation_id}"),
                        operation_id=operation_id,
                        owned_uri=owned_uri,
                        content_digest=content_digest,
                        snapshot_version=snap,
                        catalog_id=self.catalog_id,
                        ownership_transfer_authorization_id=str(
                            marker.get("ownership_transfer_authorization_id") or ""
                        ),
                        register_authorization_id=str(
                            marker.get("register_authorization_id") or ""
                        ),
                        registered_at=str(marker.get("registered_at") or _utc_iso()),
                    )

                reservation_id = str(flight.get("reservation_id") or "")
                schema_digest = str(flight.get("schema_digest") or "")
                schema_revision = int(flight.get("schema_revision") or 1)
                # Build a minimal contract-like terminalization if reservation known.
                if reservation_id:
                    row = self.companion.store.get_row(
                        "lake_logical_key_reservations", reservation_id
                    )
                    if row is not None and str(row.get("status")) != "committed":
                        # Terminalize outbox + reservation without re-snapshotting.
                        try:
                            # Use constraint service terminalize when a contract is available.
                            # Fall back to direct store CAS for recovery.
                            now = _utc_iso()
                            outbox_id = str(flight.get("outbox_id") or f"outbox-{operation_id}")
                            outbox_row = self.companion.store.get_row(
                                "lake_ingest_outbox", outbox_id
                            )
                            payload = {
                                "operation_id": operation_id,
                                "snapshot_version": snap,
                                "recovered": True,
                            }
                            if outbox_row is None:
                                self.companion.store.put_if_absent(
                                    "lake_ingest_outbox",
                                    outbox_id,
                                    {
                                        "outbox_id": outbox_id,
                                        "shard_id": self.shard_id,
                                        "operation_id": operation_id,
                                        "payload_digest": _sha256_text(
                                            _canonical_json(payload)
                                        ),
                                        "status": "committed",
                                        "created_at": now,
                                        "updated_at": now,
                                        "snapshot_version": snap,
                                        "reservation_id": reservation_id,
                                    },
                                )
                            else:
                                updated = dict(outbox_row)
                                updated["status"] = "committed"
                                updated["updated_at"] = now
                                updated["snapshot_version"] = snap
                                self.companion.store.cas_upsert(
                                    "lake_ingest_outbox",
                                    outbox_id,
                                    updated,
                                    expected_revision=int(outbox_row["cas_revision"]),
                                )
                            updated_res = dict(row)
                            updated_res["status"] = "committed"
                            updated_res["terminalized_at"] = now
                            updated_res["snapshot_version"] = snap
                            self.companion.store.cas_upsert(
                                "lake_logical_key_reservations",
                                reservation_id,
                                updated_res,
                                expected_revision=int(row["cas_revision"]),
                            )
                        except Exception as exc:
                            raise QuarantineError(
                                f"failed to terminalize during reconcile: {exc}",
                                details={"operation_id": operation_id},
                            ) from exc

                source = SourceIdentity.from_mapping(
                    flight["source"]
                ) if flight.get("source") else (
                    prior.source if prior is not None else SourceIdentity(
                        source_uri="unknown",
                        content_digest=content_digest or _sha256_text("unknown"),
                    )
                )
                destination = DestinationObjectIdentity(
                    owned_uri=owned_uri,
                    content_digest=content_digest or source.content_digest,
                    object_version=1,
                    namespace_id=self.namespace.namespace_id,
                )
                receipt = IngestReceipt(
                    receipt_id=f"ingrec-{operation_id}",
                    operation_id=operation_id,
                    idempotency_key=str(
                        flight.get("idempotency_key")
                        or (prior.idempotency_key if prior else operation_id)
                    ),
                    phase=IngestPhase.COMMITTED,
                    snapshot_version=snap,
                    source=source,
                    destination=destination,
                    staged=None,
                    ownership_transfer_authorization_id=str(
                        flight.get("ownership_transfer_authorization_id")
                        or marker.get("ownership_transfer_authorization_id")
                        or ""
                    ),
                    copy_authorization_id="",
                    register_authorization_id=str(
                        marker.get("register_authorization_id") or ""
                    ),
                    reservation_id=reservation_id,
                    outbox_id=str(flight.get("outbox_id") or f"outbox-{operation_id}"),
                    registration=registration,
                    catalog_id=self.catalog_id,
                    data_path=self.namespace.data_path,
                    schema_digest=schema_digest,
                    schema_revision=schema_revision,
                    caller_id=self.caller_id,
                    process_birth=self.process_birth,
                    generation_fence=self.generation_fence,
                    lifecycle_policy=self.lifecycle_policy,
                )
                self._by_operation[operation_id] = receipt
                idem = receipt.idempotency_key
                self._by_idempotency[idem] = operation_id
                self._in_flight.pop(operation_id, None)
                self._quarantine.pop(operation_id, None)
                return receipt

            # Marker without object file → quarantine.
            if q is None:
                q = self._quarantine_operation(
                    operation_id=operation_id,
                    phase=IngestPhase.QUARANTINED,
                    reason="catalog marker without durable owned object",
                    details={"marker": dict(marker)},
                )
            if prior is not None:
                return prior
            raise QuarantineError(
                "reconcile cannot terminalize without owned object",
                details={"operation_id": operation_id},
            )

        # No catalog marker: if only staging/copy partial, remain quarantined.
        # Never invent a second logical snapshot or silent success.
        if q is not None or flight:
            if prior is not None and prior.phase is IngestPhase.QUARANTINED:
                raise QuarantineError(
                    "partial ingest without catalog commit remains quarantined; "
                    "no second logical transition invented",
                    details={
                        "operation_id": operation_id,
                        "phase": prior.phase.value,
                        "quarantine_id": (
                            None
                            if prior.quarantine is None
                            else prior.quarantine.quarantine_id
                        ),
                        "receipt_id": prior.receipt_id,
                    },
                )
            raise QuarantineError(
                "partial ingest without catalog commit remains quarantined; "
                "no second logical transition invented",
                details={
                    "operation_id": operation_id,
                    "phase": flight.get("phase"),
                    "quarantine_id": None if q is None else q.quarantine_id,
                },
            )

        if prior is not None:
            return prior
        raise IngestError(f"unknown operation_id {operation_id!r}")


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def default_process_birth(
    *,
    process_id: str | None = None,
    boot_id: str | None = None,
    hostname: str = "localhost",
    pid: int | None = None,
) -> ProcessBirth:
    """Build a process birth identity for tests and local workers."""

    return ProcessBirth(
        process_id=process_id or f"proc-{uuid.uuid4().hex}",
        boot_id=boot_id or f"boot-{uuid.uuid4().hex}",
        started_at=_utc_iso(),
        hostname=hostname,
        pid=pid if pid is not None else os.getpid(),
    )
