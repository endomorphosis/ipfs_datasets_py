"""Public file-wrapper document metadata and byte synchronization (PATLAW-023).

``DocumentSyncProcessor`` retrieves ODP document inventory for an application,
compares upstream update markers against a durable checkpoint, downloads only
authorized changed artifacts into a bounded quarantine, verifies media type /
size / digest, and admits immutable versions into a local store.

Acceptance invariants:

* Sync key is ``source_document_id + content_sha256`` — same key deduplicates.
* Changed bytes for an existing source id create a new version (history kept).
* Partial / truncated / size-mismatched downloads never become admitted artifacts.
* Unavailable NPL or private documents are explicit outcomes (not silent skips).
* Delayed inventory (metadata present, bytes not yet available) is a
  **freshness gap**, never proof of nonreceipt by USPTO.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import urlsplit

from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
    build_artifact_manifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AuthorityRelation,
    DisclosureClassification,
    SourceReceipt,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    DEFAULT_ODP_BASE_URL,
    ProviderOutcomeKind,
    ProviderResult,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    OdpDocumentRecord,
    PatentFileWrapperClient,
)

DOCUMENT_SYNC_SCHEMA_VERSION: Final = "uspto.document_sync.v1"
DOCUMENT_SYNC_INTERFACE: Final = "DocumentSyncProcessor@1"
FIXTURE_SCHEMA_VERSION: Final = "odp-document-sync-fixture-v1"

# Default bound for a single download session (16 MiB, matches provider default).
DEFAULT_MAX_DOWNLOAD_BYTES: Final = 16 * 1024 * 1024

# Media-type / magic-byte probes used only as admission gates (no parsing).
_PDF_MAGIC: Final = b"%PDF"
_MIME_BY_IDENTIFIER: Final[Mapping[str, str]] = MappingProxyType(
    {
        "PDF": "application/pdf",
        "XML": "application/xml",
        "JSON": "application/json",
        "TXT": "text/plain",
        "HTML": "text/html",
        "ZIP": "application/zip",
        "MSWORD": "application/msword",
        "DOCX": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    }
)

# Tokens that mark inventory entries as explicitly unavailable (NPL / private).
_UNAVAILABLE_REASON_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "npl",
        "non_patent_literature",
        "non-patent-literature",
        "private",
        "confidential",
        "restricted",
        "not_public",
        "not-public",
        "unavailable",
        "access_denied",
        "access-denied",
    }
)

_SAFE_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,200}\Z")


# ---------------------------------------------------------------------------
# Outcome taxonomy
# ---------------------------------------------------------------------------


class DocumentSyncOutcomeKind(str, Enum):
    """Per-document sync outcome."""

    ADMITTED = "admitted"
    """First admitted version for this source document id."""

    DEDUPLICATED = "deduplicated"
    """Same source id + content hash already admitted; no new version."""

    VERSIONED = "versioned"
    """Same source id, different content hash → new immutable version."""

    UNCHANGED = "unchanged"
    """Upstream markers match checkpoint; download skipped."""

    FRESHNESS_GAP = "freshness_gap"
    """Inventory lists the document but bytes are delayed/unavailable (not nonreceipt)."""

    UNAVAILABLE = "unavailable"
    """Explicit NPL / private / confidential limitation (not a silent skip)."""

    PARTIAL_REJECTED = "partial_rejected"
    """Partial/truncated/size-mismatched download discarded; never admitted."""

    VERIFICATION_FAILED = "verification_failed"
    """Hash / media / size verification failed after complete download."""

    ERROR = "error"
    """Transport, schema, or configuration failure for this document."""

    METADATA_ERROR = "metadata_error"
    """Inventory retrieval itself failed (application-level)."""


class GapInterpretation(str, Enum):
    """How a missing-byte inventory entry must be interpreted."""

    FRESHNESS_GAP = "freshness_gap"
    """Delayed publication / not yet downloadable — never nonreceipt."""

    UNAVAILABLE_NPL = "unavailable_npl"
    UNAVAILABLE_PRIVATE = "unavailable_private"
    UNAVAILABLE_OTHER = "unavailable_other"


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentSyncKey:
    """Canonical dedup key: upstream source id + content digest."""

    source_document_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_document_id",
            _require_id(self.source_document_id, "source_document_id"),
        )
        digest = str(self.content_sha256 or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("content_sha256 must be 64-char lowercase hex")
        object.__setattr__(self, "content_sha256", digest)

    @property
    def composite(self) -> str:
        return f"{self.source_document_id}|{self.content_sha256}"

    def to_dict(self) -> dict[str, str]:
        return {
            "content_sha256": self.content_sha256,
            "source_document_id": self.source_document_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentSyncKey":
        return cls(
            source_document_id=str(value.get("source_document_id") or ""),
            content_sha256=str(value.get("content_sha256") or ""),
        )


@dataclass(frozen=True, slots=True)
class UpstreamUpdateMarker:
    """Markers compared before downloading to skip unchanged artifacts."""

    official_date: str | None = None
    last_modified: str | None = None
    etag: str | None = None
    download_url: str | None = None
    mime_type_identifier: str | None = None
    page_total_quantity: int | None = None
    raw_marker_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "download_url": self.download_url,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "mime_type_identifier": self.mime_type_identifier,
            "official_date": self.official_date,
            "page_total_quantity": self.page_total_quantity,
            "raw_marker_digest": self.raw_marker_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "UpstreamUpdateMarker":
        if not value:
            return cls()
        pages = value.get("page_total_quantity")
        return cls(
            official_date=_optional_str(value.get("official_date")),
            last_modified=_optional_str(value.get("last_modified")),
            etag=_optional_str(value.get("etag")),
            download_url=_optional_str(value.get("download_url")),
            mime_type_identifier=_optional_str(value.get("mime_type_identifier")),
            page_total_quantity=None if pages is None else int(pages),
            raw_marker_digest=_optional_str(value.get("raw_marker_digest")),
        )

    def matches(self, other: "UpstreamUpdateMarker") -> bool:
        """True when both sides carry equal non-empty marker digests or fields."""

        if self.raw_marker_digest and other.raw_marker_digest:
            return self.raw_marker_digest == other.raw_marker_digest
        return (
            self.official_date == other.official_date
            and self.last_modified == other.last_modified
            and self.etag == other.etag
            and self.download_url == other.download_url
            and self.mime_type_identifier == other.mime_type_identifier
            and self.page_total_quantity == other.page_total_quantity
        )


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    """One admitted immutable version of a source document."""

    schema_version: str
    source_document_id: str
    version: int
    content_sha256: str
    size_bytes: int
    media_type: str
    artifact_id: str
    sync_key: DocumentSyncKey
    classification: DisclosureClassification
    source_receipt_id: str | None
    admitted_utc: str
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOCUMENT_SYNC_SCHEMA_VERSION:
            raise ValueError(
                f"DocumentVersionRecord.schema_version must be "
                f"{DOCUMENT_SYNC_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self,
            "source_document_id",
            _require_id(self.source_document_id, "source_document_id"),
        )
        if not isinstance(self.version, int) or isinstance(self.version, bool):
            raise TypeError("version must be int")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        object.__setattr__(
            self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
        )
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise TypeError("size_bytes must be int")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be >= 0")
        object.__setattr__(
            self, "media_type", _require_str(self.media_type, "media_type", max_len=256)
        )
        object.__setattr__(
            self, "artifact_id", _require_id(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.sync_key, DocumentSyncKey):
            raise TypeError("sync_key must be DocumentSyncKey")
        if self.sync_key.source_document_id != self.source_document_id:
            raise ValueError("sync_key.source_document_id mismatch")
        if self.sync_key.content_sha256 != self.content_sha256:
            raise ValueError("sync_key.content_sha256 mismatch")
        if not isinstance(self.classification, DisclosureClassification):
            try:
                object.__setattr__(
                    self,
                    "classification",
                    DisclosureClassification(str(self.classification)),
                )
            except ValueError as exc:
                raise ValueError(f"invalid classification: {self.classification!r}") from exc
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_str(self.source_receipt_id),
        )
        object.__setattr__(
            self, "admitted_utc", _require_str(self.admitted_utc, "admitted_utc", max_len=64)
        )
        labels = {
            str(k): str(v) for k, v in dict(self.labels or {}).items()
        }
        object.__setattr__(self, "labels", MappingProxyType(dict(sorted(labels.items()))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_utc": self.admitted_utc,
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "labels": dict(self.labels),
            "media_type": self.media_type,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "source_document_id": self.source_document_id,
            "source_receipt_id": self.source_receipt_id,
            "sync_key": self.sync_key.to_dict(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentVersionRecord":
        return cls(
            schema_version=str(
                value.get("schema_version") or DOCUMENT_SYNC_SCHEMA_VERSION
            ),
            source_document_id=str(value.get("source_document_id") or ""),
            version=int(value.get("version") or 0),
            content_sha256=str(value.get("content_sha256") or ""),
            size_bytes=int(value.get("size_bytes") or 0),
            media_type=str(value.get("media_type") or "application/octet-stream"),
            artifact_id=str(value.get("artifact_id") or ""),
            sync_key=DocumentSyncKey.from_dict(value.get("sync_key") or {}),
            classification=DisclosureClassification(
                str(
                    value.get("classification")
                    or DisclosureClassification.PUBLIC_OFFICIAL.value
                )
            ),
            source_receipt_id=value.get("source_receipt_id"),
            admitted_utc=str(value.get("admitted_utc") or ""),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DocumentCheckpointEntry:
    """Per-document durable checkpoint (markers + last admitted version)."""

    source_document_id: str
    marker: UpstreamUpdateMarker
    last_content_sha256: str | None = None
    last_version: int = 0
    last_artifact_id: str | None = None
    last_outcome: str | None = None
    updated_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_artifact_id": self.last_artifact_id,
            "last_content_sha256": self.last_content_sha256,
            "last_outcome": self.last_outcome,
            "last_version": self.last_version,
            "marker": self.marker.to_dict(),
            "source_document_id": self.source_document_id,
            "updated_utc": self.updated_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentCheckpointEntry":
        return cls(
            source_document_id=str(value.get("source_document_id") or ""),
            marker=UpstreamUpdateMarker.from_dict(value.get("marker")),
            last_content_sha256=_optional_str(value.get("last_content_sha256")),
            last_version=int(value.get("last_version") or 0),
            last_artifact_id=_optional_str(value.get("last_artifact_id")),
            last_outcome=_optional_str(value.get("last_outcome")),
            updated_utc=_optional_str(value.get("updated_utc")),
        )


@dataclass
class DocumentSyncCheckpoint:
    """Application-level document sync checkpoint (resumable)."""

    schema_version: str
    application_number: str
    entries: dict[str, DocumentCheckpointEntry] = field(default_factory=dict)
    inventory_receipt_id: str | None = None
    inventory_retrieved_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "entries": {
                key: entry.to_dict() for key, entry in sorted(self.entries.items())
            },
            "inventory_receipt_id": self.inventory_receipt_id,
            "inventory_retrieved_utc": self.inventory_retrieved_utc,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentSyncCheckpoint":
        raw_entries = value.get("entries") or {}
        entries: dict[str, DocumentCheckpointEntry] = {}
        if isinstance(raw_entries, Mapping):
            for key, raw in raw_entries.items():
                if isinstance(raw, Mapping):
                    entries[str(key)] = DocumentCheckpointEntry.from_dict(raw)
        return cls(
            schema_version=str(
                value.get("schema_version") or DOCUMENT_SYNC_SCHEMA_VERSION
            ),
            application_number=str(value.get("application_number") or ""),
            entries=entries,
            inventory_receipt_id=_optional_str(value.get("inventory_receipt_id")),
            inventory_retrieved_utc=_optional_str(value.get("inventory_retrieved_utc")),
        )

    def get(self, source_document_id: str) -> DocumentCheckpointEntry | None:
        return self.entries.get(source_document_id)

    def put(self, entry: DocumentCheckpointEntry) -> None:
        self.entries[entry.source_document_id] = entry


@dataclass(frozen=True, slots=True)
class DocumentSyncItemResult:
    """Outcome for one inventory document."""

    schema_version: str
    source_document_id: str
    kind: DocumentSyncOutcomeKind
    application_number: str
    document_code: str | None = None
    version: int | None = None
    sync_key: DocumentSyncKey | None = None
    artifact_id: str | None = None
    content_sha256: str | None = None
    size_bytes: int | None = None
    media_type: str | None = None
    gap_interpretation: GapInterpretation | None = None
    message: str | None = None
    error_code: str | None = None
    source_receipt_id: str | None = None
    classification: DisclosureClassification | None = None
    is_nonreceipt: bool = False
    """Always False for freshness gaps; reserved so callers cannot confuse gap/nonreceipt."""

    def __post_init__(self) -> None:
        # Freshness gaps must never be reported as nonreceipt.
        if self.kind is DocumentSyncOutcomeKind.FRESHNESS_GAP and self.is_nonreceipt:
            raise ValueError(
                "freshness_gap must not set is_nonreceipt=True "
                "(delayed inventory is not proof of nonreceipt)"
            )
        if self.kind is DocumentSyncOutcomeKind.UNAVAILABLE and self.is_nonreceipt:
            raise ValueError(
                "unavailable documents must not be reported as nonreceipt"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "artifact_id": self.artifact_id,
            "classification": None
            if self.classification is None
            else self.classification.value,
            "content_sha256": self.content_sha256,
            "document_code": self.document_code,
            "error_code": self.error_code,
            "gap_interpretation": None
            if self.gap_interpretation is None
            else self.gap_interpretation.value,
            "is_nonreceipt": self.is_nonreceipt,
            "kind": self.kind.value,
            "media_type": self.media_type,
            "message": self.message,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "source_document_id": self.source_document_id,
            "source_receipt_id": self.source_receipt_id,
            "sync_key": None if self.sync_key is None else self.sync_key.to_dict(),
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class DocumentSyncResult:
    """Aggregate result of a sync run for one application."""

    schema_version: str
    application_number: str
    items: tuple[DocumentSyncItemResult, ...]
    inventory_count: int
    admitted_count: int
    deduplicated_count: int
    versioned_count: int
    freshness_gap_count: int
    unavailable_count: int
    partial_rejected_count: int
    inventory_receipt_id: str | None = None
    metadata_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.metadata_error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_count": self.admitted_count,
            "application_number": self.application_number,
            "deduplicated_count": self.deduplicated_count,
            "freshness_gap_count": self.freshness_gap_count,
            "inventory_count": self.inventory_count,
            "inventory_receipt_id": self.inventory_receipt_id,
            "items": [item.to_dict() for item in self.items],
            "metadata_error": self.metadata_error,
            "partial_rejected_count": self.partial_rejected_count,
            "schema_version": self.schema_version,
            "unavailable_count": self.unavailable_count,
            "versioned_count": self.versioned_count,
        }


# ---------------------------------------------------------------------------
# Download result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DownloadBytesResult:
    """Bytes-download outcome used by the sync processor."""

    kind: ProviderOutcomeKind
    status_code: int | None
    body: bytes
    content_type: str | None = None
    content_length: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    receipt: SourceReceipt | None = None
    error_code: str | None = None
    message: str | None = None
    truncated: bool = False
    """True when the transport reported a partial/interrupted body."""

    @property
    def ok(self) -> bool:
        return (
            self.kind is ProviderOutcomeKind.SUCCESS
            and not self.truncated
            and self.status_code is not None
            and 200 <= self.status_code < 300
        )


@runtime_checkable
class DocumentBytesDownloader(Protocol):
    """Injectable downloader for public document bytes."""

    def download(
        self,
        download_url: str,
        *,
        document_identifier: str,
        expected_size: int | None = None,
    ) -> DownloadBytesResult:
        ...


# ---------------------------------------------------------------------------
# Quarantine (fail-closed admission)
# ---------------------------------------------------------------------------


class QuarantineError(Exception):
    """Raised when a quarantine session cannot be admitted."""

    def __init__(self, message: str, *, code: str = "quarantine_error") -> None:
        super().__init__(message)
        self.code = code


class BoundedQuarantineSession:
    """Stream download bytes into a temp file under a hard size bound.

    Incomplete sessions are discarded. Only :meth:`admit` returns durable
    content, and only after size/hash/media verification succeeds.
    """

    def __init__(
        self,
        *,
        root: Path,
        source_document_id: str,
        max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self.source_document_id = source_document_id
        self.max_bytes = int(max_bytes)
        self._fd: int | None = None
        self._path: Path | None = None
        self._hasher = hashlib.sha256()
        self._written = 0
        self._closed = False
        self._admitted = False
        fd, name = tempfile.mkstemp(
            prefix=f"q-{_safe_filename(source_document_id)}-",
            suffix=".part",
            dir=str(self._root),
        )
        self._fd = fd
        self._path = Path(name)

    @property
    def written(self) -> int:
        return self._written

    @property
    def path(self) -> Path | None:
        return self._path

    def write(self, chunk: bytes) -> None:
        if self._closed or self._fd is None:
            raise QuarantineError("session closed", code="session_closed")
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("chunk must be bytes")
        data = bytes(chunk)
        if self._written + len(data) > self.max_bytes:
            self.discard()
            raise QuarantineError(
                f"download exceeded max_bytes={self.max_bytes}",
                code="download_too_large",
            )
        os.write(self._fd, data)
        self._hasher.update(data)
        self._written += len(data)

    def write_all(self, body: bytes) -> None:
        # Chunked write keeps the bound check path uniform.
        view = memoryview(body)
        step = 64 * 1024
        for offset in range(0, len(view), step):
            self.write(bytes(view[offset : offset + step]))

    def content_sha256(self) -> str:
        return self._hasher.hexdigest()

    def discard(self) -> None:
        """Abandon the session; partial bytes never become admitted."""

        if self._admitted:
            return
        self._close_fd()
        if self._path is not None and self._path.exists():
            try:
                self._path.unlink()
            except OSError:
                pass
        self._closed = True

    def admit(
        self,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
        media_type: str,
        mime_type_identifier: str | None = None,
        require_nonempty: bool = True,
        truncated: bool = False,
    ) -> tuple[bytes, str, int]:
        """Verify and return complete bytes. Failures discard quarantine data."""

        if self._admitted:
            raise QuarantineError("already admitted", code="already_admitted")
        if truncated:
            self.discard()
            raise QuarantineError(
                "partial download rejected", code="partial_download"
            )
        if self._fd is not None:
            os.fsync(self._fd)
        self._close_fd()
        if self._path is None or not self._path.exists():
            raise QuarantineError("missing quarantine file", code="missing_file")
        size = self._written
        digest = self.content_sha256()
        if require_nonempty and size == 0:
            self.discard()
            raise QuarantineError("empty download body", code="empty_body")
        if expected_size is not None and size != int(expected_size):
            self.discard()
            raise QuarantineError(
                f"size mismatch: got {size}, expected {expected_size}",
                code="size_mismatch",
            )
        if expected_sha256 is not None:
            want = expected_sha256.strip().lower()
            if digest != want:
                self.discard()
                raise QuarantineError(
                    "content sha256 mismatch", code="hash_mismatch"
                )
        raw = self._path.read_bytes()
        if len(raw) != size:
            self.discard()
            raise QuarantineError(
                "on-disk size diverged from written counter",
                code="size_mismatch",
            )
        # Media gate: soft magic check for declared PDF / zip.
        _verify_media_bytes(
            raw,
            media_type=media_type,
            mime_type_identifier=mime_type_identifier,
        )
        # Promote part → admitted temp name then delete part (atomic enough for local).
        admitted_path = self._path.with_suffix(".admitted")
        try:
            self._path.replace(admitted_path)
        except OSError as exc:
            self.discard()
            raise QuarantineError(
                f"failed to promote quarantine file: {exc}", code="promote_failed"
            ) from exc
        try:
            admitted_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            # Python <3.8 style (not expected on 3.12); keep portable.
            if admitted_path.exists():
                admitted_path.unlink()
        self._admitted = True
        self._closed = True
        self._path = None
        return raw, digest, size

    def _close_fd(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            if not self._admitted:
                self.discard()
        except Exception:
            pass


def _verify_media_bytes(
    raw: bytes,
    *,
    media_type: str,
    mime_type_identifier: str | None,
) -> None:
    mt = (media_type or "").lower()
    ident = (mime_type_identifier or "").upper()
    if "pdf" in mt or ident == "PDF":
        if not raw.startswith(_PDF_MAGIC):
            raise QuarantineError(
                "declared PDF but magic bytes missing", code="media_mismatch"
            )
    if "zip" in mt or ident == "ZIP" or "wordprocessingml" in mt or ident == "DOCX":
        if not raw.startswith(b"PK"):
            raise QuarantineError(
                "declared ZIP/DOCX but PK magic missing", code="media_mismatch"
            )


# ---------------------------------------------------------------------------
# Admitted artifact store
# ---------------------------------------------------------------------------


class AdmittedDocumentStore:
    """In-memory admitted artifact index with optional durable root for bytes.

    Deduplicates by :class:`DocumentSyncKey`. Versions are append-only per
    ``source_document_id``.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
        self._by_sync_key: dict[str, DocumentVersionRecord] = {}
        self._versions: dict[str, list[DocumentVersionRecord]] = {}
        self._bytes: dict[str, bytes] = {}
        self._manifests: dict[str, ArtifactManifest] = {}

    @property
    def version_count(self) -> int:
        return sum(len(v) for v in self._versions.values())

    def get_by_sync_key(self, key: DocumentSyncKey) -> DocumentVersionRecord | None:
        return self._by_sync_key.get(key.composite)

    def versions_for(self, source_document_id: str) -> tuple[DocumentVersionRecord, ...]:
        return tuple(self._versions.get(source_document_id, ()))

    def latest(self, source_document_id: str) -> DocumentVersionRecord | None:
        versions = self._versions.get(source_document_id) or []
        return versions[-1] if versions else None

    def get_bytes(self, artifact_id: str) -> bytes | None:
        return self._bytes.get(artifact_id)

    def get_manifest(self, artifact_id: str) -> ArtifactManifest | None:
        return self._manifests.get(artifact_id)

    def list_all(self) -> tuple[DocumentVersionRecord, ...]:
        out: list[DocumentVersionRecord] = []
        for versions in self._versions.values():
            out.extend(versions)
        return tuple(out)

    def admit(
        self,
        *,
        source_document_id: str,
        content: bytes,
        content_sha256: str,
        media_type: str,
        classification: DisclosureClassification,
        source_receipt_id: str | None,
        admitted_utc: str,
        matter_id: str | None = None,
        labels: Mapping[str, str] | None = None,
        media_signature: str | None = None,
    ) -> tuple[DocumentVersionRecord, bool]:
        """Admit bytes. Returns ``(record, is_new)``.

        ``is_new`` is False when the sync key already exists (dedup).
        """

        key = DocumentSyncKey(
            source_document_id=source_document_id,
            content_sha256=content_sha256,
        )
        existing = self._by_sync_key.get(key.composite)
        if existing is not None:
            return existing, False

        prior = self._versions.get(source_document_id) or []
        version_no = len(prior) + 1
        artifact_id = (
            f"art:uspto:doc:{_safe_filename(source_document_id)}:v{version_no}"
        )
        # Ensure uniqueness if caller reuses ids across applications.
        if artifact_id in self._bytes:
            artifact_id = f"{artifact_id}:{uuid.uuid4().hex[:8]}"

        manifest = build_artifact_manifest(
            artifact_id=artifact_id,
            sha256=content_sha256,
            size_bytes=len(content),
            classification=classification,
            media_type=media_type,
            media_signature=media_signature,
            matter_id=matter_id,
            source_receipt_id=source_receipt_id,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            labels=labels or {},
            parser_versions={
                "document_sync": DOCUMENT_SYNC_SCHEMA_VERSION,
                "artifact_manifest": ARTIFACT_MANIFEST_SCHEMA_VERSION,
            },
        )
        record = DocumentVersionRecord(
            schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
            source_document_id=source_document_id,
            version=version_no,
            content_sha256=content_sha256,
            size_bytes=len(content),
            media_type=media_type,
            artifact_id=artifact_id,
            sync_key=key,
            classification=classification,
            source_receipt_id=source_receipt_id,
            admitted_utc=admitted_utc,
            labels=labels or {},
        )
        self._by_sync_key[key.composite] = record
        self._versions.setdefault(source_document_id, []).append(record)
        self._bytes[artifact_id] = bytes(content)
        self._manifests[artifact_id] = manifest
        if self._root is not None:
            path = self._root / f"{_safe_filename(artifact_id)}.bin"
            path.write_bytes(content)
            meta_path = self._root / f"{_safe_filename(artifact_id)}.json"
            meta_path.write_text(
                canonical_json(
                    {
                        "manifest": manifest.to_dict(),
                        "version": record.to_dict(),
                    }
                ),
                encoding="utf-8",
            )
        return record, True


# ---------------------------------------------------------------------------
# Checkpoint store
# ---------------------------------------------------------------------------


class CheckpointStore:
    """Filesystem or in-memory checkpoint persistence."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, DocumentSyncCheckpoint] = {}

    def load(self, application_number: str) -> DocumentSyncCheckpoint:
        app = str(application_number).strip()
        if self._root is not None:
            path = self._checkpoint_path(app)
            if path.is_file():
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, Mapping):
                    return DocumentSyncCheckpoint.from_dict(payload)
        return self._memory.get(
            app,
            DocumentSyncCheckpoint(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                application_number=app,
            ),
        )

    def save(self, checkpoint: DocumentSyncCheckpoint) -> None:
        app = checkpoint.application_number
        self._memory[app] = checkpoint
        if self._root is None:
            return
        path = self._checkpoint_path(app)
        tmp = path.with_suffix(".tmp")
        payload = checkpoint.to_dict()
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def _checkpoint_path(self, application_number: str) -> Path:
        assert self._root is not None
        return self._root / f"doc-sync-{_safe_filename(application_number)}.json"


# ---------------------------------------------------------------------------
# Default downloader (uses ODP client HTTP layer)
# ---------------------------------------------------------------------------


class OdpDocumentBytesDownloader:
    """Download document bytes via a :class:`PatentFileWrapperClient` transport."""

    def __init__(self, client: PatentFileWrapperClient) -> None:
        self._client = client

    def download(
        self,
        download_url: str,
        *,
        document_identifier: str,
        expected_size: int | None = None,
    ) -> DownloadBytesResult:
        path = _download_path_from_url(download_url)
        # Access the shared ProviderHttpClient; client owns auth/retry/sanitization.
        http = getattr(self._client, "_http", None)
        if http is None:
            return DownloadBytesResult(
                kind=ProviderOutcomeKind.CLIENT_ERROR,
                status_code=None,
                body=b"",
                error_code="no_http_client",
                message="PatentFileWrapperClient has no HTTP transport",
            )
        result: ProviderResult = http.request(
            "GET",
            path,
            enable_conditional_cache=False,
            upstream_id=document_identifier,
            metadata={
                "resource": "document_bytes",
                "document_identifier": document_identifier,
            },
        )
        return _provider_result_to_download(result, expected_size=expected_size)


def _provider_result_to_download(
    result: ProviderResult,
    *,
    expected_size: int | None,
) -> DownloadBytesResult:
    body: bytes
    if isinstance(result.payload, (bytes, bytearray)):
        body = bytes(result.payload)
    elif result.payload is None:
        body = b""
    elif isinstance(result.payload, str):
        body = result.payload.encode("utf-8")
    else:
        # JSON payloads are unexpected for document bytes but preserve deterministically.
        body = canonical_json(result.payload).encode("utf-8")

    content_type = None
    content_length = None
    etag = None
    last_modified = None
    if result.receipt is not None:
        last_modified = result.receipt.last_modified
        # Content-Type may live only on transport headers; receipt metadata may carry it.
        meta = result.receipt.metadata or {}
        content_type = meta.get("content_type") or meta.get("Content-Type")
        if "content_length" in meta:
            try:
                content_length = int(meta["content_length"])
            except (TypeError, ValueError):
                content_length = None

    truncated = False
    if expected_size is not None and len(body) < int(expected_size):
        truncated = True
    if content_length is not None and len(body) < content_length:
        truncated = True

    return DownloadBytesResult(
        kind=result.kind,
        status_code=result.status_code,
        body=body,
        content_type=content_type,
        content_length=content_length if content_length is not None else expected_size,
        etag=etag,
        last_modified=last_modified,
        receipt=result.receipt,
        error_code=result.error_code,
        message=result.message,
        truncated=truncated,
    )


class MappingDocumentBytesDownloader:
    """Fixture/test downloader: map path → :class:`DownloadBytesResult`."""

    def __init__(
        self,
        responses: Mapping[str, DownloadBytesResult | Mapping[str, Any]] | None = None,
    ) -> None:
        self._responses: dict[str, DownloadBytesResult] = {}
        for key, value in dict(responses or {}).items():
            path = _download_path_from_url(str(key))
            if isinstance(value, DownloadBytesResult):
                self._responses[path] = value
            else:
                self._responses[path] = _download_from_mapping(value)

    def add(self, path_or_url: str, result: DownloadBytesResult | Mapping[str, Any]) -> None:
        path = _download_path_from_url(path_or_url)
        if isinstance(result, DownloadBytesResult):
            self._responses[path] = result
        else:
            self._responses[path] = _download_from_mapping(result)

    def download(
        self,
        download_url: str,
        *,
        document_identifier: str,
        expected_size: int | None = None,
    ) -> DownloadBytesResult:
        path = _download_path_from_url(download_url)
        if path not in self._responses:
            return DownloadBytesResult(
                kind=ProviderOutcomeKind.NOT_FOUND,
                status_code=404,
                body=b"",
                error_code="fixture_miss",
                message=f"no download fixture for {path}",
            )
        result = self._responses[path]
        # Re-evaluate truncation against caller expected_size if provided.
        if expected_size is not None and len(result.body) < int(expected_size):
            return DownloadBytesResult(
                kind=result.kind,
                status_code=result.status_code,
                body=result.body,
                content_type=result.content_type,
                content_length=expected_size,
                etag=result.etag,
                last_modified=result.last_modified,
                receipt=result.receipt,
                error_code=result.error_code,
                message=result.message,
                truncated=True,
            )
        return result


def _download_from_mapping(value: Mapping[str, Any]) -> DownloadBytesResult:
    body_raw = value.get("body", b"")
    if isinstance(body_raw, str):
        # Support base64 via body_b64 or raw utf-8 text.
        if value.get("body_encoding") == "base64" or "body_b64" in value:
            import base64

            b64 = value.get("body_b64") if "body_b64" in value else body_raw
            body = base64.b64decode(str(b64))
        else:
            body = body_raw.encode("utf-8")
    elif isinstance(body_raw, (bytes, bytearray)):
        body = bytes(body_raw)
    else:
        body = b""
    if "body_b64" in value and not body:
        import base64

        body = base64.b64decode(str(value["body_b64"]))
    status = int(value.get("status") or value.get("status_code") or 200)
    kind_raw = value.get("kind")
    if kind_raw:
        kind = ProviderOutcomeKind(str(kind_raw))
    else:
        from ipfs_datasets_py.processors.domains.uspto.providers.base import (
            classify_http_status,
        )

        kind = (
            ProviderOutcomeKind.SUCCESS
            if 200 <= status < 300
            else classify_http_status(status)
        )
    content_length = value.get("content_length")
    if content_length is not None:
        content_length = int(content_length)
    truncated = bool(value.get("truncated", False))
    if content_length is not None and len(body) < content_length:
        truncated = True
    return DownloadBytesResult(
        kind=kind,
        status_code=status,
        body=body,
        content_type=_optional_str(value.get("content_type") or value.get("media_type")),
        content_length=content_length,
        etag=_optional_str(value.get("etag")),
        last_modified=_optional_str(value.get("last_modified")),
        error_code=_optional_str(value.get("error_code")),
        message=_optional_str(value.get("message")),
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InventoryDocument:
    """Normalized inventory row used by the sync processor."""

    application_number: str
    document_identifier: str
    document_code: str | None
    official_date: str | None
    document_code_description: str | None
    direction_category: str | None
    download_options: tuple[Mapping[str, Any], ...]
    raw: Mapping[str, Any]
    availability: str | None = None
    """Optional explicit availability: public | private | npl | unavailable | delayed."""

    @property
    def source_document_id(self) -> str:
        return self.document_identifier

    @classmethod
    def from_odp(cls, record: OdpDocumentRecord) -> "InventoryDocument":
        raw = dict(record.raw)
        availability = _optional_str(
            raw.get("availability")
            or raw.get("availabilityStatus")
            or raw.get("accessLimitation")
            or raw.get("documentAccessCategory")
        )
        return cls(
            application_number=record.application_number,
            document_identifier=record.document_identifier,
            document_code=record.document_code,
            official_date=record.official_date,
            document_code_description=record.document_code_description,
            direction_category=record.direction_category,
            download_options=record.download_options,
            raw=MappingProxyType(raw),
            availability=availability,
        )

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, application_number: str
    ) -> "InventoryDocument":
        doc_id = value.get("documentIdentifier") or value.get("document_identifier")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("documentIdentifier is required")
        downloads_raw = (
            value.get("downloadOptionBag")
            or value.get("download_options")
            or ()
        )
        downloads: list[Mapping[str, Any]] = []
        if isinstance(downloads_raw, Sequence) and not isinstance(
            downloads_raw, (str, bytes)
        ):
            for item in downloads_raw:
                if isinstance(item, Mapping):
                    downloads.append(dict(item))
        availability = _optional_str(
            value.get("availability")
            or value.get("availabilityStatus")
            or value.get("accessLimitation")
            or value.get("documentAccessCategory")
        )
        return cls(
            application_number=str(
                value.get("applicationNumberText")
                or value.get("application_number")
                or application_number
            ).strip(),
            document_identifier=doc_id.strip(),
            document_code=_optional_str(
                value.get("documentCode") or value.get("document_code")
            ),
            official_date=_optional_str(
                value.get("officialDate") or value.get("official_date")
            ),
            document_code_description=_optional_str(
                value.get("documentCodeDescriptionText")
                or value.get("document_code_description")
            ),
            direction_category=_optional_str(
                value.get("documentDirectionCategory")
                or value.get("direction_category")
            ),
            download_options=tuple(downloads),
            raw=MappingProxyType(dict(value)),
            availability=availability,
        )


def build_update_marker(doc: InventoryDocument) -> UpstreamUpdateMarker:
    option = doc.download_options[0] if doc.download_options else {}
    pages = option.get("pageTotalQuantity")
    material = {
        "document_identifier": doc.document_identifier,
        "download_url": option.get("downloadUrl"),
        "mime": option.get("mimeTypeIdentifier"),
        "official_date": doc.official_date,
        "pages": pages,
        "availability": doc.availability,
    }
    return UpstreamUpdateMarker(
        official_date=doc.official_date,
        last_modified=_optional_str(doc.raw.get("lastModified") or doc.raw.get("last_modified")),
        etag=_optional_str(doc.raw.get("etag") or doc.raw.get("ETag")),
        download_url=_optional_str(option.get("downloadUrl")),
        mime_type_identifier=_optional_str(option.get("mimeTypeIdentifier")),
        page_total_quantity=None if pages is None else int(pages),
        raw_marker_digest=sha256_hex(canonical_json(material)),
    )


def classify_unavailable(
    doc: InventoryDocument,
) -> tuple[bool, GapInterpretation | None, str | None]:
    """Return (is_unavailable, interpretation, message)."""

    tokens: list[str] = []
    if doc.availability:
        tokens.append(doc.availability.lower().replace(" ", "_"))
    for key in (
        "availabilityStatus",
        "accessLimitation",
        "documentAccessCategory",
        "documentCategory",
        "restrictionReason",
        "unavailableReason",
    ):
        raw = doc.raw.get(key)
        if isinstance(raw, str) and raw.strip():
            tokens.append(raw.strip().lower().replace(" ", "_"))
    # Description heuristics for explicit NPL markers only (not inventing).
    desc = (doc.document_code_description or "").lower()
    code = (doc.document_code or "").upper()
    joined = " ".join(tokens)
    for token in tokens:
        normalized = token.replace("-", "_")
        if normalized in _UNAVAILABLE_REASON_TOKENS or any(
            t in normalized for t in ("npl", "private", "confidential", "restricted")
        ):
            if "npl" in normalized or "non_patent" in normalized:
                return True, GapInterpretation.UNAVAILABLE_NPL, f"explicit NPL: {token}"
            if any(
                p in normalized
                for p in ("private", "confidential", "restricted", "not_public")
            ):
                return (
                    True,
                    GapInterpretation.UNAVAILABLE_PRIVATE,
                    f"explicit private/confidential: {token}",
                )
            return (
                True,
                GapInterpretation.UNAVAILABLE_OTHER,
                f"explicit unavailable: {token}",
            )
    if "npl" in joined or "non-patent literature" in desc or code in {"NPL", "NPL.I"}:
        # Only when no download options and NPL signal is present.
        if not doc.download_options:
            return (
                True,
                GapInterpretation.UNAVAILABLE_NPL,
                "NPL document without public download options",
            )
    if not doc.download_options and any(
        t in joined for t in ("private", "confidential")
    ):
        return (
            True,
            GapInterpretation.UNAVAILABLE_PRIVATE,
            "private document without public download options",
        )
    return False, None, None


def resolve_media_type(
    *,
    mime_type_identifier: str | None,
    content_type: str | None,
    download_url: str | None,
) -> str:
    if content_type:
        # Strip parameters (e.g. charset).
        return content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
    if mime_type_identifier:
        mapped = _MIME_BY_IDENTIFIER.get(mime_type_identifier.upper())
        if mapped:
            return mapped
    if download_url:
        lower = download_url.lower()
        if lower.endswith(".pdf"):
            return "application/pdf"
        if lower.endswith(".xml"):
            return "application/xml"
        if lower.endswith(".docx"):
            return (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            )
        if lower.endswith(".zip"):
            return "application/zip"
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class DocumentSyncProcessor:
    """Synchronize public ODP file-wrapper document metadata and bytes.

    Parameters
    ----------
    client:
        Optional :class:`PatentFileWrapperClient` for inventory retrieval.
    downloader:
        Injectable bytes downloader (defaults to ODP client transport).
    store:
        Admitted artifact store (dedup + version history).
    checkpoints:
        Durable per-application checkpoint store.
    quarantine_root:
        Directory for temporary download quarantine.
    max_download_bytes:
        Hard bound for a single download session.
    classification:
        Default disclosure classification for public ODP artifacts.
    wall_clock_utc:
        Injectable clock returning ISO-8601 UTC strings.
    """

    def __init__(
        self,
        *,
        client: PatentFileWrapperClient | None = None,
        downloader: DocumentBytesDownloader | None = None,
        store: AdmittedDocumentStore | None = None,
        checkpoints: CheckpointStore | None = None,
        quarantine_root: Path | str | None = None,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        classification: DisclosureClassification = DisclosureClassification.PUBLIC_OFFICIAL,
        wall_clock_utc: Callable[[], str] | None = None,
        matter_id: str | None = None,
    ) -> None:
        self._client = client
        if downloader is not None:
            self._downloader = downloader
        elif client is not None:
            self._downloader = OdpDocumentBytesDownloader(client)
        else:
            self._downloader = MappingDocumentBytesDownloader()
        self._store = store or AdmittedDocumentStore()
        self._checkpoints = checkpoints or CheckpointStore()
        if quarantine_root is not None:
            self._quarantine_root = Path(quarantine_root)
            self._quarantine_root.mkdir(parents=True, exist_ok=True)
            self._owns_quarantine = False
        else:
            self._quarantine_root = Path(
                tempfile.mkdtemp(prefix="uspto-doc-quarantine-")
            )
            self._owns_quarantine = True
        self._max_download_bytes = int(max_download_bytes)
        self._classification = classification
        self._wall_clock = wall_clock_utc or _default_utc
        self._matter_id = matter_id

    @property
    def store(self) -> AdmittedDocumentStore:
        return self._store

    @property
    def checkpoints(self) -> CheckpointStore:
        return self._checkpoints

    def close(self) -> None:
        if self._owns_quarantine and self._quarantine_root.exists():
            shutil.rmtree(self._quarantine_root, ignore_errors=True)

    def __enter__(self) -> "DocumentSyncProcessor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_application(
        self,
        application_number: str,
        *,
        document_codes: str | Sequence[str] | None = None,
        force_download: bool = False,
    ) -> DocumentSyncResult:
        """Fetch inventory from ODP and synchronize documents."""

        app = str(application_number).strip()
        if not app:
            raise ValueError("application_number is required")
        if self._client is None:
            raise RuntimeError(
                "sync_application requires a PatentFileWrapperClient; "
                "use sync_inventory for offline/fixture inventory"
            )
        result = self._client.get_documents(app, document_codes=document_codes)
        if not result.ok:
            item = DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id="*",
                kind=DocumentSyncOutcomeKind.METADATA_ERROR,
                application_number=app,
                message=result.message or result.error_code or result.kind.value,
                error_code=result.error_code or result.kind.value,
            )
            return DocumentSyncResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                application_number=app,
                items=(item,),
                inventory_count=0,
                admitted_count=0,
                deduplicated_count=0,
                versioned_count=0,
                freshness_gap_count=0,
                unavailable_count=0,
                partial_rejected_count=0,
                inventory_receipt_id=None
                if result.receipt is None
                else result.receipt.receipt_id,
                metadata_error=item.message,
            )
        records = result.payload
        if not isinstance(records, tuple):
            records = tuple(records or ())
        inventory = tuple(
            InventoryDocument.from_odp(rec)
            for rec in records
            if isinstance(rec, OdpDocumentRecord)
        )
        receipt_id = None if result.receipt is None else result.receipt.receipt_id
        retrieved = None if result.receipt is None else result.receipt.retrieval_utc
        return self.sync_inventory(
            app,
            inventory,
            inventory_receipt_id=receipt_id,
            inventory_retrieved_utc=retrieved,
            force_download=force_download,
        )

    def sync_inventory(
        self,
        application_number: str,
        inventory: Sequence[InventoryDocument | Mapping[str, Any] | OdpDocumentRecord],
        *,
        inventory_receipt_id: str | None = None,
        inventory_retrieved_utc: str | None = None,
        force_download: bool = False,
    ) -> DocumentSyncResult:
        """Synchronize a pre-fetched or fixture inventory (no live metadata call)."""

        app = str(application_number).strip()
        docs = tuple(self._coerce_inventory(inventory, application_number=app))
        checkpoint = self._checkpoints.load(app)
        checkpoint.inventory_receipt_id = inventory_receipt_id
        checkpoint.inventory_retrieved_utc = (
            inventory_retrieved_utc or self._wall_clock()
        )

        items: list[DocumentSyncItemResult] = []
        for doc in docs:
            item = self._sync_one(doc, checkpoint=checkpoint, force_download=force_download)
            items.append(item)

        self._checkpoints.save(checkpoint)
        return self._aggregate(app, items, inventory_receipt_id=inventory_receipt_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _coerce_inventory(
        self,
        inventory: Sequence[InventoryDocument | Mapping[str, Any] | OdpDocumentRecord],
        *,
        application_number: str,
    ) -> Iterable[InventoryDocument]:
        for raw in inventory:
            if isinstance(raw, InventoryDocument):
                yield raw
            elif isinstance(raw, OdpDocumentRecord):
                yield InventoryDocument.from_odp(raw)
            elif isinstance(raw, Mapping):
                yield InventoryDocument.from_mapping(
                    raw, application_number=application_number
                )
            else:
                raise TypeError(
                    f"unsupported inventory item type: {type(raw).__name__}"
                )

    def _sync_one(
        self,
        doc: InventoryDocument,
        *,
        checkpoint: DocumentSyncCheckpoint,
        force_download: bool,
    ) -> DocumentSyncItemResult:
        source_id = doc.source_document_id
        marker = build_update_marker(doc)
        prior = checkpoint.get(source_id)

        # 1) Explicit NPL / private unavailability.
        is_unavail, interpretation, unavail_msg = classify_unavailable(doc)
        if is_unavail:
            checkpoint.put(
                DocumentCheckpointEntry(
                    source_document_id=source_id,
                    marker=marker,
                    last_content_sha256=None if prior is None else prior.last_content_sha256,
                    last_version=0 if prior is None else prior.last_version,
                    last_artifact_id=None if prior is None else prior.last_artifact_id,
                    last_outcome=DocumentSyncOutcomeKind.UNAVAILABLE.value,
                    updated_utc=self._wall_clock(),
                )
            )
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.UNAVAILABLE,
                application_number=doc.application_number,
                document_code=doc.document_code,
                gap_interpretation=interpretation,
                message=unavail_msg,
                error_code="unavailable",
                is_nonreceipt=False,
            )

        # 2) No download options → freshness gap (delayed inventory), not nonreceipt.
        if not doc.download_options:
            checkpoint.put(
                DocumentCheckpointEntry(
                    source_document_id=source_id,
                    marker=marker,
                    last_content_sha256=None if prior is None else prior.last_content_sha256,
                    last_version=0 if prior is None else prior.last_version,
                    last_artifact_id=None if prior is None else prior.last_artifact_id,
                    last_outcome=DocumentSyncOutcomeKind.FRESHNESS_GAP.value,
                    updated_utc=self._wall_clock(),
                )
            )
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.FRESHNESS_GAP,
                application_number=doc.application_number,
                document_code=doc.document_code,
                gap_interpretation=GapInterpretation.FRESHNESS_GAP,
                message=(
                    "document listed in inventory without download options; "
                    "treated as freshness gap, not nonreceipt"
                ),
                error_code="bytes_not_yet_available",
                is_nonreceipt=False,
            )

        # 3) Unchanged markers → skip download when we already hold a version.
        if (
            not force_download
            and prior is not None
            and prior.last_content_sha256
            and prior.marker.matches(marker)
            and self._store.get_by_sync_key(
                DocumentSyncKey(
                    source_document_id=source_id,
                    content_sha256=prior.last_content_sha256,
                )
            )
            is not None
        ):
            existing = self._store.get_by_sync_key(
                DocumentSyncKey(
                    source_document_id=source_id,
                    content_sha256=prior.last_content_sha256,
                )
            )
            assert existing is not None
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.UNCHANGED,
                application_number=doc.application_number,
                document_code=doc.document_code,
                version=existing.version,
                sync_key=existing.sync_key,
                artifact_id=existing.artifact_id,
                content_sha256=existing.content_sha256,
                size_bytes=existing.size_bytes,
                media_type=existing.media_type,
                source_receipt_id=existing.source_receipt_id,
                classification=existing.classification,
                message="upstream markers unchanged; download skipped",
            )

        option = dict(doc.download_options[0])
        download_url = option.get("downloadUrl") or option.get("download_url")
        if not isinstance(download_url, str) or not download_url.strip():
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.FRESHNESS_GAP,
                application_number=doc.application_number,
                document_code=doc.document_code,
                gap_interpretation=GapInterpretation.FRESHNESS_GAP,
                message="download option missing downloadUrl; freshness gap",
                error_code="missing_download_url",
                is_nonreceipt=False,
            )

        mime_id = _optional_str(option.get("mimeTypeIdentifier"))
        expected_pages = option.get("pageTotalQuantity")
        # page count is not a byte size; content-length comes from download headers.
        expected_size = option.get("byteSize") or option.get("contentLength")
        if expected_size is not None:
            try:
                expected_size = int(expected_size)
            except (TypeError, ValueError):
                expected_size = None

        download = self._downloader.download(
            str(download_url).strip(),
            document_identifier=source_id,
            expected_size=expected_size,
        )

        # 4) Delayed / not found bytes → freshness gap (never nonreceipt).
        if download.kind is ProviderOutcomeKind.NOT_FOUND or download.status_code == 404:
            checkpoint.put(
                DocumentCheckpointEntry(
                    source_document_id=source_id,
                    marker=marker,
                    last_content_sha256=None if prior is None else prior.last_content_sha256,
                    last_version=0 if prior is None else prior.last_version,
                    last_artifact_id=None if prior is None else prior.last_artifact_id,
                    last_outcome=DocumentSyncOutcomeKind.FRESHNESS_GAP.value,
                    updated_utc=self._wall_clock(),
                )
            )
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.FRESHNESS_GAP,
                application_number=doc.application_number,
                document_code=doc.document_code,
                gap_interpretation=GapInterpretation.FRESHNESS_GAP,
                message=(
                    "inventory lists document but bytes returned 404; "
                    "freshness gap, not nonreceipt"
                ),
                error_code="bytes_delayed_or_missing",
                source_receipt_id=None
                if download.receipt is None
                else download.receipt.receipt_id,
                is_nonreceipt=False,
            )

        # 5) Forbidden often means private/restricted on public surface.
        if download.kind is ProviderOutcomeKind.FORBIDDEN or download.status_code == 403:
            checkpoint.put(
                DocumentCheckpointEntry(
                    source_document_id=source_id,
                    marker=marker,
                    last_content_sha256=None if prior is None else prior.last_content_sha256,
                    last_version=0 if prior is None else prior.last_version,
                    last_artifact_id=None if prior is None else prior.last_artifact_id,
                    last_outcome=DocumentSyncOutcomeKind.UNAVAILABLE.value,
                    updated_utc=self._wall_clock(),
                )
            )
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.UNAVAILABLE,
                application_number=doc.application_number,
                document_code=doc.document_code,
                gap_interpretation=GapInterpretation.UNAVAILABLE_PRIVATE,
                message="download forbidden on public ODP surface (private/restricted)",
                error_code="forbidden",
                source_receipt_id=None
                if download.receipt is None
                else download.receipt.receipt_id,
                is_nonreceipt=False,
            )

        # 5b) Truncated / partial HTTP bodies never reach admission.
        if download.truncated:
            checkpoint.put(
                DocumentCheckpointEntry(
                    source_document_id=source_id,
                    marker=marker,
                    last_content_sha256=None if prior is None else prior.last_content_sha256,
                    last_version=0 if prior is None else prior.last_version,
                    last_artifact_id=None if prior is None else prior.last_artifact_id,
                    last_outcome=DocumentSyncOutcomeKind.PARTIAL_REJECTED.value,
                    updated_utc=self._wall_clock(),
                )
            )
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.PARTIAL_REJECTED,
                application_number=doc.application_number,
                document_code=doc.document_code,
                message=(
                    "partial download rejected (body shorter than declared length); "
                    "bytes never admitted"
                ),
                error_code="partial_download",
                source_receipt_id=None
                if download.receipt is None
                else download.receipt.receipt_id,
            )

        if not download.ok:
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=DocumentSyncOutcomeKind.ERROR,
                application_number=doc.application_number,
                document_code=doc.document_code,
                message=download.message or download.error_code or download.kind.value,
                error_code=download.error_code or download.kind.value,
                source_receipt_id=None
                if download.receipt is None
                else download.receipt.receipt_id,
            )

        media_type = resolve_media_type(
            mime_type_identifier=mime_id,
            content_type=download.content_type,
            download_url=str(download_url),
        )

        # 6) Stream into quarantine and admit only after full verification.
        session = BoundedQuarantineSession(
            root=self._quarantine_root,
            source_document_id=source_id,
            max_bytes=self._max_download_bytes,
        )
        try:
            session.write_all(download.body)
            # Prefer Content-Length from download when present.
            size_gate = download.content_length
            if size_gate is None:
                size_gate = expected_size
            content, digest, size = session.admit(
                expected_size=size_gate,
                media_type=media_type,
                mime_type_identifier=mime_id,
                truncated=download.truncated,
            )
        except QuarantineError as exc:
            kind = (
                DocumentSyncOutcomeKind.PARTIAL_REJECTED
                if exc.code
                in {
                    "partial_download",
                    "size_mismatch",
                    "empty_body",
                    "download_too_large",
                }
                else DocumentSyncOutcomeKind.VERIFICATION_FAILED
            )
            checkpoint.put(
                DocumentCheckpointEntry(
                    source_document_id=source_id,
                    marker=marker,
                    last_content_sha256=None if prior is None else prior.last_content_sha256,
                    last_version=0 if prior is None else prior.last_version,
                    last_artifact_id=None if prior is None else prior.last_artifact_id,
                    last_outcome=kind.value,
                    updated_utc=self._wall_clock(),
                )
            )
            return DocumentSyncItemResult(
                schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
                source_document_id=source_id,
                kind=kind,
                application_number=doc.application_number,
                document_code=doc.document_code,
                message=str(exc),
                error_code=exc.code,
                source_receipt_id=None
                if download.receipt is None
                else download.receipt.receipt_id,
            )
        finally:
            # Ensure no lingering partials if admit failed mid-way.
            if not session._admitted:  # noqa: SLF001 — intentional cleanup
                session.discard()

        # 7) Admit into versioned store (dedup by source id + hash).
        receipt_id = None if download.receipt is None else download.receipt.receipt_id
        labels = {
            "document_code": doc.document_code or "",
            "application_number": doc.application_number,
            "source": "odp_patent_file_wrapper",
        }
        if expected_pages is not None:
            labels["page_total_quantity"] = str(expected_pages)
        record, is_new = self._store.admit(
            source_document_id=source_id,
            content=content,
            content_sha256=digest,
            media_type=media_type,
            classification=self._classification,
            source_receipt_id=receipt_id,
            admitted_utc=self._wall_clock(),
            matter_id=self._matter_id,
            labels={k: v for k, v in labels.items() if v},
            media_signature=mime_id,
        )

        if not is_new:
            outcome = DocumentSyncOutcomeKind.DEDUPLICATED
        elif record.version > 1:
            outcome = DocumentSyncOutcomeKind.VERSIONED
        else:
            outcome = DocumentSyncOutcomeKind.ADMITTED

        checkpoint.put(
            DocumentCheckpointEntry(
                source_document_id=source_id,
                marker=marker,
                last_content_sha256=record.content_sha256,
                last_version=record.version,
                last_artifact_id=record.artifact_id,
                last_outcome=outcome.value,
                updated_utc=self._wall_clock(),
            )
        )
        return DocumentSyncItemResult(
            schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
            source_document_id=source_id,
            kind=outcome,
            application_number=doc.application_number,
            document_code=doc.document_code,
            version=record.version,
            sync_key=record.sync_key,
            artifact_id=record.artifact_id,
            content_sha256=record.content_sha256,
            size_bytes=record.size_bytes,
            media_type=record.media_type,
            source_receipt_id=record.source_receipt_id,
            classification=record.classification,
            message=None
            if is_new
            else "same source id + content hash already admitted",
        )

    def _aggregate(
        self,
        application_number: str,
        items: Sequence[DocumentSyncItemResult],
        *,
        inventory_receipt_id: str | None,
    ) -> DocumentSyncResult:
        def count(kind: DocumentSyncOutcomeKind) -> int:
            return sum(1 for item in items if item.kind is kind)

        return DocumentSyncResult(
            schema_version=DOCUMENT_SYNC_SCHEMA_VERSION,
            application_number=application_number,
            items=tuple(items),
            inventory_count=len(items),
            admitted_count=count(DocumentSyncOutcomeKind.ADMITTED),
            deduplicated_count=count(DocumentSyncOutcomeKind.DEDUPLICATED),
            versioned_count=count(DocumentSyncOutcomeKind.VERSIONED),
            freshness_gap_count=count(DocumentSyncOutcomeKind.FRESHNESS_GAP),
            unavailable_count=count(DocumentSyncOutcomeKind.UNAVAILABLE),
            partial_rejected_count=count(DocumentSyncOutcomeKind.PARTIAL_REJECTED),
            inventory_receipt_id=inventory_receipt_id,
        )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    here = Path(__file__).resolve()
    # uspto/ -> domains/ -> processors/ -> ipfs_datasets_py/ -> repo
    candidates = [
        here.parents[4] / "tests" / "fixtures" / "uspto" / "odp" / "documents",
        Path.cwd() / "tests" / "fixtures" / "uspto" / "odp" / "documents",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def load_document_sync_recipe(
    recipe: Mapping[str, Any] | Path | str,
) -> dict[str, Any]:
    """Load a compact document-sync fixture recipe."""

    if isinstance(recipe, Mapping):
        payload = dict(recipe)
    else:
        path = Path(recipe)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ValueError(f"fixture root must be a mapping: {path}")
        payload = dict(payload)
    schema = payload.get("schema_version")
    if schema and str(schema) not in {
        FIXTURE_SCHEMA_VERSION,
        DOCUMENT_SYNC_SCHEMA_VERSION,
    }:
        if not str(schema).startswith("odp-document"):
            raise ValueError(f"unsupported fixture schema_version {schema!r}")
    return payload


def recipe_case(recipe: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    cases = recipe.get("cases") or []
    if isinstance(cases, Mapping):
        if case_id not in cases:
            raise KeyError(case_id)
        case = cases[case_id]
        if not isinstance(case, Mapping):
            raise TypeError("case must be a mapping")
        out = dict(case)
        out.setdefault("id", case_id)
        return out
    if isinstance(cases, Sequence):
        for item in cases:
            if isinstance(item, Mapping) and item.get("id") == case_id:
                return dict(item)
    raise KeyError(case_id)


def processor_from_recipe_case(
    case: Mapping[str, Any],
    *,
    store: AdmittedDocumentStore | None = None,
    checkpoints: CheckpointStore | None = None,
    quarantine_root: Path | None = None,
    wall_clock_utc: Callable[[], str] | None = None,
) -> tuple[DocumentSyncProcessor, str, list[InventoryDocument]]:
    """Build a processor + inventory from one compact fixture case."""

    app = str(case.get("application_number") or "16123456")
    docs_raw = case.get("documents") or case.get("documentBag") or []
    inventory = [
        InventoryDocument.from_mapping(item, application_number=app)
        for item in docs_raw
        if isinstance(item, Mapping)
    ]
    downloads = case.get("downloads") or {}
    downloader = MappingDocumentBytesDownloader()
    if isinstance(downloads, Mapping):
        for path, spec in downloads.items():
            if isinstance(spec, Mapping):
                downloader.add(str(path), spec)
    elif isinstance(downloads, Sequence):
        for item in downloads:
            if not isinstance(item, Mapping):
                continue
            path = item.get("path") or item.get("downloadUrl") or item.get("url")
            if path:
                downloader.add(str(path), item)
    processor = DocumentSyncProcessor(
        downloader=downloader,
        store=store,
        checkpoints=checkpoints,
        quarantine_root=quarantine_root,
        wall_clock_utc=wall_clock_utc,
    )
    return processor, app, inventory


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _default_utc() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value).strip() or None
    text = value.strip()
    return text or None


def _require_id(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _SAFE_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _require_sha256(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"{field} must be 64-char lowercase hex")
    return text


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return cleaned[:120] or "doc"


def _download_path_from_url(url: str) -> str:
    text = str(url).strip()
    if not text:
        raise ValueError("download url is empty")
    if text.startswith("/"):
        return text.split("?", 1)[0]
    parts = urlsplit(text)
    if parts.path:
        return parts.path
    # Relative path without leading slash.
    return "/" + text.split("?", 1)[0].lstrip("/")


__all__ = [
    "DEFAULT_MAX_DOWNLOAD_BYTES",
    "DOCUMENT_SYNC_INTERFACE",
    "DOCUMENT_SYNC_SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "AdmittedDocumentStore",
    "BoundedQuarantineSession",
    "CheckpointStore",
    "DocumentBytesDownloader",
    "DocumentCheckpointEntry",
    "DocumentSyncCheckpoint",
    "DocumentSyncItemResult",
    "DocumentSyncKey",
    "DocumentSyncOutcomeKind",
    "DocumentSyncProcessor",
    "DocumentSyncResult",
    "DocumentVersionRecord",
    "DownloadBytesResult",
    "GapInterpretation",
    "InventoryDocument",
    "MappingDocumentBytesDownloader",
    "OdpDocumentBytesDownloader",
    "QuarantineError",
    "UpstreamUpdateMarker",
    "build_update_marker",
    "classify_unavailable",
    "default_fixture_dir",
    "load_document_sync_recipe",
    "processor_from_recipe_case",
    "recipe_case",
    "resolve_media_type",
]
