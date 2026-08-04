"""Tenant-isolated encrypted private artifact store for USPTO material.

Encrypts document bytes **before** durable write. Private CIDs, extracted
text, and ciphertext never leave the authorized store for public sinks.
Credentials and payment-card material are refused (document vault only).

The encryption backend is pluggable; the default is AES-256-GCM with AAD
bound to tenant, artifact, digest, and classification so wrong-tenant or
wrong-key reads fail closed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Protocol, runtime_checkable

from .artifact_manifest import ArtifactManifest, build_artifact_manifest
from .contracts import AuthorityRelation, DisclosureClassification, canonical_json
from .privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    UsptoPrivacyPolicy,
    VaultKind,
    DEFAULT_PRIVACY_POLICY,
)

PRIVATE_STORE_SCHEMA_VERSION: Final = "uspto.private-store.v1"
PRIVATE_STORE_INTERFACE: Final = "PrivateArtifactStore@1"
ENCRYPTION_SUITE: Final = "AES-256-GCM"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_TENANT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._\-]{0,127}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")

_PROHIBITED_NAME_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "credit_card",
        "payment-card",
        "cookie_jar",
        "payment_card",
        "mfa-secret",
        "browser_profile",
        "session-cookie",
        "card-number",
        "pan_dump",
        "cvv",
        "cvc",
        "apikey",
        "mfa_secret",
        "api_key",
        "session_cookie",
        "card_number",
        "totp",
        "password",
        "passwd",
        "credit-card",
    }
)

_PROHIBITED_CONTENT_MARKERS: Final[tuple[bytes, ...]] = (
    b"BEGIN USPTO CREDENTIAL BLOB",
    b"payment_card_data=",
    b"session_cookie=",
    b"mfa_secret=",
    b"reusable_signature_credential=",
    b"CREDIT_CARD_NUMBER=",
    b"CVV=",
)

_PAN_CANDIDATE_RE = re.compile(rb"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


class PrivateStoreError(Exception):
    """Base error for the private artifact store."""

    def __init__(self, message: str, *, code: str = "private_store_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class TenantIsolationError(PrivateStoreError):
    """Raised when tenant binding or key material does not match."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="tenant_isolation")


class DecryptionFailedError(PrivateStoreError):
    """Raised when ciphertext cannot be authenticated under the active key."""

    def __init__(self, message: str = "decryption failed") -> None:
        super().__init__(message, code="decryption_failed")


class ProhibitedContentError(PrivateStoreError):
    """Raised when credential or payment-card material is presented."""

    def __init__(
        self, message: str, *, code: str = "prohibited_content"
    ) -> None:
        super().__init__(message, code=code)


class PrivateStoreIntegrityError(PrivateStoreError):
    """Raised when on-disk metadata and ciphertext digests disagree."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="integrity_error")


@runtime_checkable
class EncryptionBackend(Protocol):
    """Pluggable encrypt/decrypt surface used by :class:`PrivateArtifactStore`."""

    suite: str

    def encrypt(
        self, plaintext: bytes, *, key: bytes, aad: bytes
    ) -> tuple[bytes, bytes]:
        """Return ``(nonce, ciphertext_with_tag)``."""
        ...

    def decrypt(
        self, ciphertext: bytes, *, key: bytes, nonce: bytes, aad: bytes
    ) -> bytes:
        """Return plaintext or raise :class:`DecryptionFailedError`."""
        ...


class AESGCMEncryptionBackend:
    """Default AES-256-GCM backend (cryptography)."""

    suite: str = ENCRYPTION_SUITE

    def encrypt(
        self, plaintext: bytes, *, key: bytes, aad: bytes
    ) -> tuple[bytes, bytes]:
        if len(key) != 32:
            raise PrivateStoreError(
                "AES-256-GCM key must be 32 bytes", code="invalid_key"
            )
        if not isinstance(plaintext, (bytes, bytearray)):
            raise TypeError("plaintext must be bytes")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, bytes(plaintext), aad)
        return nonce, ciphertext

    def decrypt(
        self, ciphertext: bytes, *, key: bytes, nonce: bytes, aad: bytes
    ) -> bytes:
        if len(key) != 32:
            raise PrivateStoreError(
                "AES-256-GCM key must be 32 bytes", code="invalid_key"
            )
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        try:
            return AESGCM(key).decrypt(bytes(nonce), bytes(ciphertext), aad)
        except InvalidTag as exc:
            raise DecryptionFailedError(
                "unable to authenticate ciphertext (wrong key/tenant/AAD)"
            ) from exc


@dataclass(frozen=True, slots=True)
class TenantKeyMaterial:
    """Tenant-bound raw key material (never persisted by this module)."""

    tenant_id: str
    key_bytes: bytes
    key_id: str = "default"

    def __post_init__(self) -> None:
        tenant = str(self.tenant_id).strip()
        if not _TENANT_RE.match(tenant):
            raise ValueError(f"invalid tenant_id: {self.tenant_id!r}")
        object.__setattr__(self, "tenant_id", tenant)
        key = self.key_bytes
        if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
            raise ValueError("key_bytes must be exactly 32 bytes")
        object.__setattr__(self, "key_bytes", bytes(key))
        kid = str(self.key_id).strip() or "default"
        if not _ID_RE.match(kid):
            raise ValueError(f"invalid key_id: {self.key_id!r}")
        object.__setattr__(self, "key_id", kid)

    @property
    def encryption_namespace(self) -> str:
        return f"private://tenant/{self.tenant_id}/key/{self.key_id}"


@dataclass(frozen=True, slots=True)
class StoredObjectRecord:
    """On-disk metadata for one encrypted object (no plaintext, no key)."""

    schema_version: str
    artifact_id: str
    tenant_id: str
    key_id: str
    sha256: str
    size_bytes: int
    classification: str
    media_type: str
    encryption_suite: str
    encryption_namespace: str
    private_cid: str
    nonce_b64: str
    ciphertext_sha256: str
    content_kind: str
    matter_id: str | None
    source_receipt_id: str | None
    authority_relation: str
    labels: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation,
            "classification": self.classification,
            "content_kind": self.content_kind,
            "ciphertext_sha256": self.ciphertext_sha256,
            "encryption_namespace": self.encryption_namespace,
            "encryption_suite": self.encryption_suite,
            "key_id": self.key_id,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "media_type": self.media_type,
            "nonce_b64": self.nonce_b64,
            "private_cid": self.private_cid,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_receipt_id": self.source_receipt_id,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StoredObjectRecord":
        if not isinstance(value, Mapping):
            raise TypeError("StoredObjectRecord must be a mapping")
        labels_raw = value.get("labels") or {}
        if not isinstance(labels_raw, Mapping):
            raise TypeError("labels must be a mapping")
        labels = MappingProxyType(
            {str(k): str(v) for k, v in labels_raw.items()}
        )
        return cls(
            schema_version=str(
                value.get("schema_version", PRIVATE_STORE_SCHEMA_VERSION)
            ),
            artifact_id=str(value.get("artifact_id", "")),
            tenant_id=str(value.get("tenant_id", "")),
            key_id=str(value.get("key_id", "default")),
            sha256=str(value.get("sha256", "")).lower(),
            size_bytes=int(value.get("size_bytes", 0)),
            classification=str(value.get("classification", "")),
            media_type=str(value.get("media_type", "application/octet-stream")),
            encryption_suite=str(
                value.get("encryption_suite", ENCRYPTION_SUITE)
            ),
            encryption_namespace=str(value.get("encryption_namespace", "")),
            private_cid=str(value.get("private_cid", "")),
            nonce_b64=str(value.get("nonce_b64", "")),
            ciphertext_sha256=str(value.get("ciphertext_sha256", "")).lower(),
            content_kind=str(
                value.get("content_kind", ContentKind.DOCUMENT_BYTES.value)
            ),
            matter_id=(
                str(value["matter_id"])
                if value.get("matter_id") is not None
                else None
            ),
            source_receipt_id=(
                str(value["source_receipt_id"])
                if value.get("source_receipt_id") is not None
                else None
            ),
            authority_relation=str(
                value.get(
                    "authority_relation",
                    AuthorityRelation.UNKNOWN.value,
                )
            ),
            labels=labels,
        )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


def make_private_cid(sha256_digest: str) -> str:
    """Deterministic private-network CID-shaped reference (not a public IPFS pin).

    Encodes a CIDv1-like multibase base32 form of ``raw`` + sha2-256 multihash so
    the value validates against the artifact-manifest CID grammar while remaining
    a local private-store handle only.
    """
    digest = str(sha256_digest).strip().lower()
    if not _SHA256_RE.match(digest):
        raise ValueError("sha256_digest must be 64-char lowercase hex")
    # CIDv1 + raw codec + sha2-256 multihash (len=32)
    payload = b"\x01U\x12 " + bytes.fromhex(digest)
    encoded = (
        base64.b32encode(payload).decode("ascii").lower().rstrip("=")
    )
    return "b" + encoded


def encryption_aad(
    *,
    tenant_id: str,
    artifact_id: str,
    sha256: str,
    classification: str,
    key_id: str,
) -> bytes:
    """Canonical AAD binding ciphertext to tenant identity and object metadata."""
    payload = {
        "artifact_id": artifact_id,
        "classification": classification,
        "key_id": key_id,
        "schema_version": PRIVATE_STORE_SCHEMA_VERSION,
        "sha256": sha256,
        "tenant_id": tenant_id,
    }
    return canonical_json(payload).encode("utf-8")


def _luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = ord(ch) - 48
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def detect_prohibited_content(
    data: bytes | None,
    *,
    relative_path: str | None = None,
    labels: Mapping[str, str] | None = None,
    classification: DisclosureClassification | str | None = None,
) -> str | None:
    """Return a reason code if *data* / names look like credential or payment material.

    Uses synthetic markers and Luhn-checked digit runs only. Never logs matched
    content.
    """
    if isinstance(classification, DisclosureClassification):
        cls_text = classification.value
    else:
        cls_text = str(classification or "").strip()

    if cls_text == DisclosureClassification.CREDENTIAL_OR_PAYMENT.value:
        return "classification_credential_or_payment"

    name_parts: list[str] = []
    if relative_path:
        name_parts.append(relative_path.replace("\\", "/").lower())
    if labels:
        for k, v in labels.items():
            name_parts.append(str(k).lower())
            name_parts.append(str(v).lower())
    joined = " ".join(name_parts)
    for token in _PROHIBITED_NAME_TOKENS:
        if token in joined:
            return f"prohibited_name_token:{token}"

    lower = data.lower() if data else b""
    for marker in _PROHIBITED_CONTENT_MARKERS:
        if marker.lower() in lower:
            return "prohibited_content_marker"

    for match in _PAN_CANDIDATE_RE.finditer(data or b""):
        digits = re.sub(rb"[^0-9]", b"", match.group(0)).decode(
            "ascii", errors="ignore"
        )
        if _luhn_ok(digits):
            return "payment_card_pattern"
    return None


def assert_no_prohibited_content(
    data: bytes | None,
    *,
    relative_path: str | None = None,
    labels: Mapping[str, str] | None = None,
    classification: DisclosureClassification | str | None = None,
) -> None:
    reason = detect_prohibited_content(
        data,
        relative_path=relative_path,
        labels=labels,
        classification=classification,
    )
    if reason:
        raise ProhibitedContentError(
            "credential or payment-card material is prohibited in the document store",
            code=reason,
        )


def _require_regular_dir(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.exists() and path.is_symlink():
        raise PrivateStoreError(
            f"{label} must not be a symlink", code="symlink_rejected"
        )
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve()
    if not resolved.is_dir():
        raise PrivateStoreError(
            f"{label} is not a directory", code="invalid_root"
        )
    return resolved


class PrivateArtifactStore:
    """Encrypted, tenant-bound document vault with restartable put semantics."""

    def __init__(
        self,
        root: str | Path,
        tenant_key: TenantKeyMaterial,
        *,
        backend: EncryptionBackend | None = None,
        privacy_policy: UsptoPrivacyPolicy | None = None,
    ) -> None:
        self._root = _require_regular_dir(Path(root), "private store root")
        if not isinstance(tenant_key, TenantKeyMaterial):
            raise TypeError("tenant_key must be TenantKeyMaterial")
        self._tenant_key = tenant_key
        self._backend: EncryptionBackend = backend or AESGCMEncryptionBackend()
        self._policy = privacy_policy or DEFAULT_PRIVACY_POLICY
        self._lock = threading.RLock()
        self._tenant_dir = self._root / "tenants" / tenant_key.tenant_id
        self._objects_dir = self._tenant_dir / "objects"
        self._meta_dir = self._tenant_dir / "meta"
        self._index_path = self._tenant_dir / "index.json"
        self._tenant_dir.mkdir(parents=True, exist_ok=True)
        self._objects_dir.mkdir(parents=True, exist_ok=True)
        self._meta_dir.mkdir(parents=True, exist_ok=True)
        if not self._index_path.exists():
            self._atomic_write_json(
                self._index_path,
                {
                    "schema_version": PRIVATE_STORE_SCHEMA_VERSION,
                    "by_sha256": {},
                },
            )

    @property
    def root(self) -> Path:
        return self._root

    @property
    def tenant_id(self) -> str:
        return self._tenant_key.tenant_id

    @property
    def key_id(self) -> str:
        return self._tenant_key.key_id

    @property
    def encryption_namespace(self) -> str:
        return self._tenant_key.encryption_namespace

    @property
    def encryption_suite(self) -> str:
        return self._backend.suite

    def _meta_path(self, artifact_id: str) -> Path:
        safe = hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()
        return self._meta_dir / f"{safe}.json"

    def _object_path(self, sha256: str) -> Path:
        return self._objects_dir / sha256[:2] / f"{sha256}.enc"

    def _load_index(self) -> dict[str, Any]:
        if not self._index_path.is_file():
            return {
                "schema_version": PRIVATE_STORE_SCHEMA_VERSION,
                "by_sha256": {},
            }
        with self._index_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise PrivateStoreIntegrityError("index.json is not an object")
        by = data.get("by_sha256")
        if not isinstance(by, dict):
            raise PrivateStoreIntegrityError("index by_sha256 is not an object")
        return data

    def _atomic_write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)

    def _read_record(self, artifact_id: str) -> StoredObjectRecord | None:
        path = self._meta_path(artifact_id)
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        record = StoredObjectRecord.from_dict(raw)
        if record.tenant_id != self.tenant_id:
            raise TenantIsolationError(
                "metadata tenant_id does not match store tenant binding"
            )
        return record

    def has_artifact(self, artifact_id: str) -> bool:
        with self._lock:
            return self._read_record(artifact_id) is not None

    def get_record(self, artifact_id: str) -> StoredObjectRecord | None:
        with self._lock:
            return self._read_record(artifact_id)

    def find_by_sha256(self, sha256: str) -> str | None:
        digest = str(sha256).strip().lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("sha256 must be 64-char lowercase hex")
        with self._lock:
            index = self._load_index()
            by = index.get("by_sha256") or {}
            value = by.get(digest)
            return str(value) if value is not None else None

    def list_artifact_ids(self) -> tuple[str, ...]:
        with self._lock:
            ids: list[str] = []
            for path in sorted(self._meta_dir.glob("*.json")):
                with path.open("r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                if not isinstance(raw, Mapping):
                    continue
                aid = str(raw.get("artifact_id", ""))
                tid = str(raw.get("tenant_id", ""))
                if aid and tid == self.tenant_id:
                    ids.append(aid)
            return tuple(sorted(set(ids)))

    def put_bytes(
        self,
        data: bytes,
        *,
        artifact_id: str,
        classification: DisclosureClassification | str,
        media_type: str = "application/octet-stream",
        matter_id: str | None = None,
        source_receipt_id: str | None = None,
        authority_relation: AuthorityRelation | str = (
            AuthorityRelation.AUTHORITATIVE_ORIGINAL
        ),
        labels: Mapping[str, str] | None = None,
        relative_path: str | None = None,
        content_kind: ContentKind | str = ContentKind.DOCUMENT_BYTES,
    ) -> tuple[ArtifactManifest, bool]:
        """Encrypt and store *data*. Returns ``(manifest, created)``.

        Idempotent: if the same SHA-256 is already stored for this tenant under
        the same ``artifact_id``, returns the existing manifest with
        ``created=False``. A digest collision under a different artifact_id
        reuses ciphertext and returns the existing record without rewriting.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        payload = bytes(data)
        labels_map = {
            str(k): str(v) for k, v in (labels or {}).items()
        }
        cls = self._policy.coerce_classification(classification)
        if cls is DisclosureClassification.CREDENTIAL_OR_PAYMENT:
            raise ProhibitedContentError(
                "credential_or_payment is prohibited document-store content",
                code="classification_credential_or_payment",
            )
        kind = (
            content_kind
            if isinstance(content_kind, ContentKind)
            else ContentKind(str(content_kind))
        )
        self._policy.assert_vault_allowed(VaultKind.DOCUMENT, kind, cls)
        if kind is ContentKind.CREDENTIAL_SECRET:
            raise ProhibitedContentError(
                "credential secrets must not enter the document vault",
                code="credential_secret",
            )
        assert_no_prohibited_content(
            payload,
            relative_path=relative_path,
            labels=labels_map,
            classification=cls,
        )
        artifact = str(artifact_id).strip()
        if not artifact or not _ID_RE.match(artifact):
            raise ValueError(f"invalid artifact_id: {artifact_id!r}")
        digest = sha256_hex(payload)
        size_bytes = len(payload)

        with self._lock:
            existing_id = self.find_by_sha256(digest)
            if existing_id is not None:
                existing = self._read_record(existing_id)
                if existing is None:
                    raise PrivateStoreIntegrityError(
                        "index references missing metadata for existing digest"
                    )
                manifest = self._manifest_from_record(existing)
                return manifest, False

            existing_same_id = self._read_record(artifact)
            if existing_same_id is not None:
                if existing_same_id.sha256 == digest:
                    return self._manifest_from_record(existing_same_id), False
                raise PrivateStoreError(
                    "artifact_id already stores different content",
                    code="artifact_id_conflict",
                )

            aad = encryption_aad(
                tenant_id=self.tenant_id,
                artifact_id=artifact,
                sha256=digest,
                classification=cls.value,
                key_id=self.key_id,
            )
            nonce, ciphertext = self._backend.encrypt(
                payload, key=self._tenant_key.key_bytes, aad=aad
            )
            ct_digest = sha256_hex(ciphertext)
            private_cid = make_private_cid(digest)
            namespace = self.encryption_namespace
            ar_value = (
                authority_relation.value
                if isinstance(authority_relation, AuthorityRelation)
                else str(authority_relation)
            )
            record = StoredObjectRecord(
                schema_version=PRIVATE_STORE_SCHEMA_VERSION,
                artifact_id=artifact,
                tenant_id=self.tenant_id,
                key_id=self.key_id,
                sha256=digest,
                size_bytes=size_bytes,
                classification=cls.value,
                media_type=(str(media_type).strip() or "application/octet-stream"),
                encryption_suite=self._backend.suite,
                encryption_namespace=namespace,
                private_cid=private_cid,
                nonce_b64=b64encode(nonce),
                ciphertext_sha256=ct_digest,
                content_kind=kind.value,
                matter_id=matter_id,
                source_receipt_id=source_receipt_id,
                authority_relation=ar_value,
                labels=MappingProxyType(dict(sorted(labels_map.items()))),
            )
            obj_path = self._object_path(digest)
            self._atomic_write_bytes(obj_path, ciphertext)
            self._atomic_write_json(self._meta_path(artifact), record.to_dict())
            index = self._load_index()
            by = dict(index.get("by_sha256") or {})
            by[digest] = artifact
            index["by_sha256"] = by
            index["schema_version"] = PRIVATE_STORE_SCHEMA_VERSION
            self._atomic_write_json(self._index_path, index)
            return self._manifest_from_record(record), True

    def get_bytes(self, artifact_id: str) -> bytes:
        """Decrypt and return plaintext for *artifact_id* under this tenant key."""
        with self._lock:
            record = self._read_record(artifact_id)
            if record is None:
                raise PrivateStoreError(
                    f"artifact not found: {artifact_id}", code="not_found"
                )
            if record.tenant_id != self.tenant_id:
                raise TenantIsolationError("cross-tenant read denied")
            obj_path = self._object_path(record.sha256)
            if not obj_path.is_file():
                raise PrivateStoreIntegrityError("ciphertext object missing")
            ciphertext = obj_path.read_bytes()
            if sha256_hex(ciphertext) != record.ciphertext_sha256:
                raise PrivateStoreIntegrityError("ciphertext digest mismatch")
            aad = encryption_aad(
                tenant_id=self.tenant_id,
                artifact_id=record.artifact_id,
                sha256=record.sha256,
                classification=record.classification,
                key_id=self.key_id,
            )
            try:
                nonce = b64decode(record.nonce_b64)
            except Exception as exc:
                raise PrivateStoreIntegrityError("invalid nonce encoding") from exc
            plaintext = self._backend.decrypt(
                ciphertext,
                key=self._tenant_key.key_bytes,
                nonce=nonce,
                aad=aad,
            )
            if sha256_hex(plaintext) != record.sha256:
                raise PrivateStoreIntegrityError(
                    "plaintext digest mismatch after decrypt"
                )
            return plaintext

    def get_manifest(self, artifact_id: str) -> ArtifactManifest:
        with self._lock:
            record = self._read_record(artifact_id)
            if record is None:
                raise PrivateStoreError(
                    f"artifact not found: {artifact_id}", code="not_found"
                )
            return self._manifest_from_record(record)

    def _manifest_from_record(self, record: StoredObjectRecord) -> ArtifactManifest:
        return build_artifact_manifest(
            artifact_id=record.artifact_id,
            sha256=record.sha256,
            size_bytes=record.size_bytes,
            classification=record.classification,
            media_type=record.media_type,
            private_cid=record.private_cid,
            public_cid=None,
            encryption_namespace=record.encryption_namespace,
            matter_id=record.matter_id,
            source_receipt_id=record.source_receipt_id,
            authority_relation=record.authority_relation,
            labels=dict(record.labels),
            policy=self._policy,
        )

    def open_for_tenant(self, tenant_key: TenantKeyMaterial) -> "PrivateArtifactStore":
        """Return a store handle bound to *tenant_key* under the same root."""
        return PrivateArtifactStore(
            self._root,
            tenant_key,
            backend=self._backend,
            privacy_policy=self._policy,
        )

    def export_to_public_sink(
        self,
        artifact_id: str,
        sink: PublicSink | str,
        content_kind: ContentKind | str,
    ) -> None:
        """Always deny private substance leaving authorized storage for public sinks."""
        record = self.get_record(artifact_id)
        if record is None:
            raise PrivateStoreError(
                f"artifact not found: {artifact_id}", code="not_found"
            )
        decision = self._policy.evaluate_sink(
            record.classification, sink, content_kind
        )
        if not decision.allowed:
            raise PrivacyBoundaryError(
                decision.reason,
                code=decision.code.value,
                classification=decision.classification.value,
                sink=decision.sink.value
                if isinstance(decision.sink, PublicSink)
                else str(decision.sink),
                content_kind=decision.content_kind.value
                if isinstance(decision.content_kind, ContentKind)
                else str(decision.content_kind),
            )
        raise PrivacyBoundaryError(
            "PrivateArtifactStore refuses public-sink export of stored material",
            code="denied_private_store_export",
            classification=record.classification,
            sink=sink.value if isinstance(sink, PublicSink) else str(sink),
            content_kind=(
                content_kind.value
                if isinstance(content_kind, ContentKind)
                else str(content_kind)
            ),
        )

    def audit_safe_summary(self, artifact_id: str) -> Mapping[str, Any]:
        """Return a log-safe projection (ids/digests only, never body/CID for private)."""
        record = self.get_record(artifact_id)
        if record is None:
            raise PrivateStoreError(
                f"artifact not found: {artifact_id}", code="not_found"
            )
        payload = {
            "artifact_id": record.artifact_id,
            "matter_id": record.matter_id,
            "classification": record.classification,
            "digest": record.sha256,
            "private_cid": record.private_cid,
            "text": "<must-not-appear>",
        }
        return self._policy.redact_for_logs(
            record.classification,
            payload,
            allowed_keys=("artifact_id", "matter_id", "classification", "digest"),
        )

    def ciphertext_bytes_for_tests(self, artifact_id: str) -> bytes:
        """Return raw ciphertext for integrity tests (no decryption)."""
        record = self.get_record(artifact_id)
        if record is None:
            raise PrivateStoreError(
                f"artifact not found: {artifact_id}", code="not_found"
            )
        return self._object_path(record.sha256).read_bytes()


def generate_tenant_key(
    tenant_id: str, *, key_id: str = "default"
) -> TenantKeyMaterial:
    """Create a fresh random tenant key (for tests and bootstrap only)."""
    return TenantKeyMaterial(
        tenant_id=tenant_id,
        key_bytes=os.urandom(32),
        key_id=key_id,
    )


__all__ = [
    "AESGCMEncryptionBackend",
    "ENCRYPTION_SUITE",
    "PRIVATE_STORE_INTERFACE",
    "PRIVATE_STORE_SCHEMA_VERSION",
    "DecryptionFailedError",
    "EncryptionBackend",
    "PrivateArtifactStore",
    "PrivateStoreError",
    "PrivateStoreIntegrityError",
    "ProhibitedContentError",
    "StoredObjectRecord",
    "TenantIsolationError",
    "TenantKeyMaterial",
    "assert_no_prohibited_content",
    "detect_prohibited_content",
    "encryption_aad",
    "generate_tenant_key",
    "make_private_cid",
    "sha256_hex",
]
